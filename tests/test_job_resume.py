import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


class JobResumeTest(unittest.TestCase):
    def setUp(self):
        self._old_jobs = dict(app.jobs)
        self._old_job_tasks = dict(app._job_tasks)
        self._old_logs = list(app._log_buffer)
        self._old_jobs_file = app.JOBS_FILE
        self._old_cancelled_file = app.CANCELLED_PROMPTS_FILE
        self._old_cancelled_prompts = dict(app._cancelled_remote_prompts)
        self._tmp = tempfile.TemporaryDirectory()
        app.jobs.clear()
        app._job_tasks.clear()
        app.JOBS_FILE = os.path.join(self._tmp.name, "jobs.json")
        app.CANCELLED_PROMPTS_FILE = os.path.join(self._tmp.name, "cancelled_prompts.json")
        app._cancelled_remote_prompts.clear()

    def tearDown(self):
        app.jobs.clear()
        app.jobs.update(self._old_jobs)
        app._job_tasks.clear()
        app._job_tasks.update(self._old_job_tasks)
        app._log_buffer[:] = self._old_logs
        app.JOBS_FILE = self._old_jobs_file
        app.CANCELLED_PROMPTS_FILE = self._old_cancelled_file
        app._cancelled_remote_prompts.clear()
        app._cancelled_remote_prompts.update(self._old_cancelled_prompts)
        self._tmp.cleanup()

    def test_load_jobs_restores_active_prompt_jobs_instead_of_deleting_file(self):
        persisted = [
            {
                "id": "job-running",
                "status": "generating",
                "workflow": "i2v_ltx23_sulphur.json",
                "instance": "B",
                "prompt_id": "prompt-123",
                "fields": {"1::text": "hello"},
            },
            {"id": "job-done", "status": "done", "workflow": "x.json"},
        ]
        with open(app.JOBS_FILE, "w", encoding="utf-8") as fh:
            json.dump(persisted, fh)

        app.load_jobs()

        self.assertIn("job-running", app.jobs)
        self.assertNotIn("job-done", app.jobs)
        self.assertTrue(os.path.isfile(app.JOBS_FILE))
        self.assertEqual(app.jobs["job-running"]["prompt_id"], "prompt-123")

    def test_loaded_prompt_id_prevents_remote_prompt_cleanup(self):
        app.jobs["job-running"] = {
            "id": "job-running",
            "status": "generating",
            "instance": "B",
            "prompt_id": "prompt-123",
        }

        untracked = app._untracked_remote_prompt_ids(
            "B",
            {"running_prompt_ids": ["prompt-123"], "pending_prompt_ids": []},
        )

        self.assertEqual(untracked, [])

    def test_resume_persisted_generation_jobs_schedules_prompt_tracker(self):
        app.jobs["job-running"] = {
            "id": "job-running",
            "status": "generating",
            "workflow": "i2v_ltx23_sulphur.json",
            "instance": "B",
            "prompt_id": "prompt-123",
            "fields": {},
            "seed": "123",
        }

        created = []

        async def fake_resume(job_id):
            return job_id

        def fake_create_task(coro):
            created.append(coro)
            return "task"

        with mock.patch("app._resume_persisted_generation_job", new=fake_resume):
            with mock.patch("app.asyncio.create_task", side_effect=fake_create_task):
                app._resume_persisted_generation_jobs()

        self.assertEqual(list(app._job_tasks.keys()), ["job-running"])
        self.assertEqual(created[0].cr_code.co_name, "fake_resume")
        created[0].close()

    def test_prompt_id_can_be_recovered_from_recent_submit_log_tail(self):
        job_id = "job_1234567890_running"
        app._log_buffer.append({
            "job_id": job_id[-12:],
            "msg": "任务已提交: abcdef123456",
        })
        inst = {"name": "B", "url": "http://comfy"}

        with mock.patch("app._get_instance_queue_counts", return_value={
            "running_prompt_ids": ["full-prompt-abcdef123456"],
            "pending_prompt_ids": [],
        }):
            prompt_id = app._recover_prompt_id_from_recent_logs(
                {"id": job_id, "instance": "B"},
                inst,
            )

        self.assertEqual(prompt_id, "full-prompt-abcdef123456")

    def test_untracked_remote_prompt_is_adopted_from_submit_log(self):
        prompt_id = "a2a2604a-f3d1-406e-a655-5fcd50ae35f4"
        app._log_buffer.append({
            "ts": 1234.5,
            "job_id": "0772082_1374",
            "msg": "任务已提交: 5fcd50ae35f4",
            "workflow": "i2v_ltx23_sulphur.json",
            "workflow_type": "图生视频",
            "user_id": "u1",
        })
        inst = {"name": "B", "url": "http://comfy", "_node_id": "n1"}
        created = []

        async def fake_resume(job_id):
            return job_id

        def fake_create_task(coro):
            created.append(coro)
            return "task"

        with mock.patch("app._resolve_workflow", return_value="/tmp/i2v_ltx23_sulphur.json"):
            with mock.patch("app._resume_persisted_generation_job", new=fake_resume):
                with mock.patch("app._job_runner", object()):
                    with mock.patch("app.add_log"):
                        with mock.patch("app.asyncio.create_task", side_effect=fake_create_task):
                            adopted = app._adopt_untracked_remote_prompts(inst, {
                                "running_prompt_ids": [prompt_id],
                                "pending_prompt_ids": [],
                            })

        self.assertEqual(adopted, [prompt_id])
        self.assertIn("job_recovered_0772082_1374", app.jobs)
        recovered = app.jobs["job_recovered_0772082_1374"]
        self.assertEqual(recovered["prompt_id"], prompt_id)
        self.assertEqual(recovered["workflow"], "i2v_ltx23_sulphur.json")
        self.assertEqual(recovered["user_id"], "u1")
        self.assertEqual(recovered["instance"], "B")
        self.assertEqual(list(app._job_tasks.keys()), ["job_recovered_0772082_1374"])
        self.assertEqual(created[0].cr_code.co_name, "fake_resume")
        created[0].close()

    def test_cancelled_remote_prompt_is_not_adopted_again(self):
        prompt_id = "a2a2604a-f3d1-406e-a655-5fcd50ae35f4"
        app._mark_remote_prompt_cancelled("B", prompt_id)
        app._log_buffer.append({
            "ts": 1234.5,
            "job_id": "0772082_1374",
            "msg": "任务已提交: 5fcd50ae35f4",
            "workflow": "i2v_ltx23_sulphur.json",
            "workflow_type": "图生视频",
            "user_id": "u1",
        })

        with mock.patch("app._resolve_workflow", return_value="/tmp/i2v_ltx23_sulphur.json"):
            adopted = app._adopt_untracked_remote_prompts(
                {"name": "B", "url": "http://comfy"},
                {"running_prompt_ids": [prompt_id], "pending_prompt_ids": []},
            )

        self.assertEqual(adopted, [])
        self.assertNotIn("job_recovered_0772082_1374", app.jobs)

    def test_cancel_job_deletes_remote_prompt_and_marks_cancelled(self):
        prompt_id = "prompt-cancel-me"
        app.jobs["job-cancel"] = {
            "id": "job-cancel",
            "status": "generating",
            "instance": "B",
            "prompt_id": prompt_id,
            "user_id": "u1",
        }

        with mock.patch("app._get_enabled_instances", return_value=[{"name": "B", "url": "http://b"}]):
            with mock.patch("app.comfyui_post", return_value={}) as comfyui_post:
                asyncio.run(app.api_cancel_job("job-cancel", current_user={"sub": "u1", "role": "user"}))

        self.assertNotIn("job-cancel", app.jobs)
        self.assertTrue(app._remote_prompt_was_cancelled("B", prompt_id))
        comfyui_post.assert_any_call("/queue", {"delete": [prompt_id]}, base_url="http://b")
        comfyui_post.assert_any_call("/interrupt", {}, base_url="http://b")

    def test_queue_prompt_client_id_extracts_comfyui_metadata(self):
        self.assertEqual(
            app._queue_prompt_client_id([1, "prompt-123", {}, {"client_id": "client-list"}]),
            "client-list",
        )
        self.assertEqual(
            app._queue_prompt_client_id({"prompt_id": "prompt-123", "extra_data": {"client_id": "client-dict"}}),
            "client-dict",
        )
        self.assertEqual(app._queue_prompt_client_id(["bad"]), "")

    def test_resume_recovers_client_id_and_starts_ws_progress(self):
        prompt_id = "prompt-resume"
        graph = {"1": {"class_type": "SaveImage", "inputs": {}}}
        app.jobs["job-running"] = {
            "id": "job-running",
            "status": "generating",
            "workflow": "resume.json",
            "instance": "B",
            "prompt_id": prompt_id,
            "fields": {},
            "seed": "123",
        }

        async def fake_save_output(**_kwargs):
            app.jobs["job-running"]["status"] = "done"

        fake_runner = mock.Mock()
        fake_runner._save_output = mock.AsyncMock(side_effect=fake_save_output)

        async def fake_broadcast(_payload):
            return None

        def fake_get(path, base_url=None):
            if path.startswith("/history/"):
                return {prompt_id: {"status": {"completed": True}, "outputs": {}}}
            return {}

        with mock.patch("app._instance_for_job", return_value={"name": "B", "url": "http://comfy"}):
            with mock.patch("app._resolve_workflow", return_value="/tmp/resume.json"):
                with mock.patch("app._remote_queue_prompt_graph", return_value=graph):
                    with mock.patch("app._remote_queue_prompt_client_id", return_value="client-recovered"):
                        with mock.patch("app._start_resume_ws_progress", return_value=None) as start_ws:
                            with mock.patch("app.comfyui_get", side_effect=fake_get):
                                with mock.patch("app.broadcast", side_effect=fake_broadcast):
                                    with mock.patch.object(app, "_job_runner", fake_runner):
                                        asyncio.run(app._resume_persisted_generation_job("job-running"))

        self.assertEqual(app.jobs["job-running"]["client_id"], "client-recovered")
        start_ws.assert_called_once()
        args = start_ws.call_args.args
        self.assertEqual(args[0], "job-running")
        self.assertEqual(args[2], graph)
        self.assertEqual(args[3], prompt_id)
        self.assertEqual(args[4], "client-recovered")

    def test_job_runner_persists_client_id_before_ws_submit(self):
        src = (Path(__file__).resolve().parents[1] / "modules/job_runner.py").read_text()

        self.assertIn('self._jobs[job_id]["client_id"] = client_id', src)
        self.assertIn("client_id=client_id", src)


if __name__ == "__main__":
    unittest.main()
