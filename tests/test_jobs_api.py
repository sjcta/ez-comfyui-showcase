import asyncio
import unittest
from unittest import mock

import app


class JobsApiTest(unittest.TestCase):
    def setUp(self):
        self._old_jobs = dict(app.jobs)
        app.jobs.clear()

    def tearDown(self):
        app.jobs.clear()
        app.jobs.update(self._old_jobs)

    def test_admin_can_see_all_active_jobs(self):
        app.jobs["job-user"] = {"id": "job-user", "user_id": "u1", "status": "generating"}
        app.jobs["job-admin"] = {"id": "job-admin", "user_id": "admin", "status": "queued"}

        result = app.api_all_jobs(current_user={"sub": "admin", "role": "admin"})

        self.assertEqual({job["id"] for job in result}, {"job-user", "job-admin"})

    def test_user_only_sees_own_active_jobs(self):
        app.jobs["job-user"] = {"id": "job-user", "user_id": "u1", "status": "generating"}
        app.jobs["job-other"] = {"id": "job-other", "user_id": "u2", "status": "queued"}

        result = app.api_all_jobs(current_user={"sub": "u1", "role": "user"})

        self.assertEqual([job["id"] for job in result], ["job-user"])

    def test_jobs_list_uses_snapshot_when_jobs_change_during_render(self):
        app.jobs["job-user"] = {"id": "job-user", "user_id": "u1", "status": "generating"}
        app.jobs["job-other"] = {"id": "job-other", "user_id": "u1", "status": "queued"}
        original_can_access = app._can_access_job
        mutated = False

        def mutating_can_access(job, current_user):
            nonlocal mutated
            if not mutated:
                mutated = True
                app.jobs["job-new"] = {"id": "job-new", "user_id": "u1", "status": "queued"}
            return original_can_access(job, current_user)

        try:
            app._can_access_job = mutating_can_access
            result = app.api_all_jobs(current_user={"sub": "u1", "role": "user"})
        finally:
            app._can_access_job = original_can_access

        self.assertEqual({job["id"] for job in result}, {"job-user", "job-other"})

    def test_pause_job_keeps_card_but_prevents_dispatch(self):
        async def run_case():
            app.jobs["job-pause"] = {
                "id": "job-pause",
                "user_id": "u1",
                "status": "queued",
                "workflow": "x.json",
                "pause_epoch": 3,
            }

            with mock.patch("app.save_jobs"), \
                    mock.patch("app.add_log"), \
                    mock.patch("app.broadcast", new=mock.AsyncMock()):
                result = await app.api_pause_job("job-pause", current_user={"sub": "u1", "role": "user"})

            self.assertTrue(result["ok"])
            self.assertIn("job-pause", app.jobs)
            self.assertEqual(app.jobs["job-pause"]["status"], "paused")
            self.assertEqual(app.jobs["job-pause"]["message"], "已暂停，等待恢复")
            self.assertEqual(app.jobs["job-pause"]["pause_epoch"], 4)

        asyncio.run(run_case())

    def test_resume_paused_job_requeues_existing_record(self):
        async def run_case():
            old_queue = app._job_queue
            app._job_queue = asyncio.Queue()
            app.jobs["job-resume"] = {
                "id": "job-resume",
                "user_id": "u1",
                "status": "paused",
                "workflow": "x.json",
                "fields": {"1::text": "hello"},
                "seed": "42",
                "width": 512,
                "height": 768,
            }

            try:
                with mock.patch("app._resolve_workflow", return_value="/tmp/x.json"), \
                        mock.patch("app.save_jobs"), \
                        mock.patch("app.add_log"), \
                        mock.patch("app.broadcast", new=mock.AsyncMock()):
                    result = await app.api_resume_job("job-resume", current_user={"sub": "u1", "role": "user"})

                self.assertTrue(result["ok"])
                self.assertEqual(app.jobs["job-resume"]["status"], "queued")
                queued = app._job_queue.get_nowait()
                self.assertEqual(queued[0], "job-resume")
                self.assertEqual(queued[3], 42)
                app._job_queue.task_done()
            finally:
                app._job_queue = old_queue

        asyncio.run(run_case())


if __name__ == "__main__":
    unittest.main()
