import unittest

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


if __name__ == "__main__":
    unittest.main()
