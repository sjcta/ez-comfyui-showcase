import unittest

import app


class InstanceIdleGuardTest(unittest.TestCase):
    def test_starting_comfyui_job_counts_as_active_for_idle_guard(self):
        job = {"instance": "A", "status": "starting_comfyui"}

        self.assertTrue(app._job_is_active_for_instance(job, "A"))

    def test_done_job_does_not_count_as_active_for_idle_guard(self):
        job = {"instance": "A", "status": "done"}

        self.assertFalse(app._job_is_active_for_instance(job, "A"))


if __name__ == "__main__":
    unittest.main()
