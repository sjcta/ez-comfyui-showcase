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


if __name__ == "__main__":
    unittest.main()
