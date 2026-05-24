import unittest
from unittest import mock

import app
from modules.job_runner import _filter_retry_instances, _workflow_track_timeout


class InstanceIdleGuardTest(unittest.TestCase):
    def test_i2i_retry_keeps_strict_b_lane_after_b_submit_stall(self):
        instances = [{"name": "A"}, {"name": "B"}]

        kept = _filter_retry_instances(
            instances,
            "i2i-FireRed-Edit-8step.json",
            {"B"},
        )

        self.assertEqual([inst["name"] for inst in kept], ["A", "B"])

    def test_non_strict_retry_can_exclude_failed_instance(self):
        instances = [{"name": "A"}, {"name": "B"}]

        kept = _filter_retry_instances(instances, "other-workflow.json", {"B"})

        self.assertEqual([inst["name"] for inst in kept], ["A"])

    def test_starting_comfyui_job_counts_as_active_for_idle_guard(self):
        job = {"instance": "A", "status": "starting_comfyui"}

        self.assertTrue(app._job_is_active_for_instance(job, "A"))

    def test_done_job_does_not_count_as_active_for_idle_guard(self):
        job = {"instance": "A", "status": "done"}

        self.assertFalse(app._job_is_active_for_instance(job, "A"))

    def test_active_instance_job_blocks_lifecycle_restart(self):
        app.jobs["job-active-instance"] = {"instance": "A", "status": "generating"}
        try:
            self.assertTrue(app._has_active_instance_job("A"))
        finally:
            app.jobs.pop("job-active-instance", None)

    def test_done_instance_job_does_not_block_lifecycle_restart(self):
        app.jobs["job-done-instance"] = {"instance": "A", "status": "done"}
        try:
            self.assertFalse(app._has_active_instance_job("A"))
        finally:
            app.jobs.pop("job-done-instance", None)

    def test_firered_instance_stays_warm_longer(self):
        app._instance_group["B"] = "i2i-firered"
        try:
            self.assertEqual(app._idle_timeout_for_instance("B"), app.FIRERED_INSTANCE_IDLE_TIMEOUT)
            self.assertGreater(app._idle_timeout_for_instance("B"), app.DEFAULT_INSTANCE_IDLE_TIMEOUT)
        finally:
            app._instance_group.pop("B", None)

    def test_successful_stop_clears_idle_timestamp(self):
        app._instance_last_active["A"] = 123.0
        app._instance_group["A"] = "seedvr"

        class Result:
            returncode = 0

        node = {"id": "n1", "name": "Node", "host": "127.0.0.1", "connection": "local"}
        inst = {"id": "i1", "name": "A", "service": "comfyui-a"}

        with mock.patch("app.subprocess.run", return_value=Result()):
            self.assertTrue(app._run_instance_action(node, inst, "stop"))

        self.assertEqual(app._instance_last_active.get("A"), 0)
        self.assertEqual(app._instance_group.get("A"), "")

    def test_remote_instance_action_places_ssh_port_before_destination(self):
        calls = []

        class Result:
            returncode = 0

        def fake_run(cmd, **_kwargs):
            calls.append(cmd)
            return Result()

        node = {
            "id": "n1",
            "name": "DGX Spark",
            "host": "10.10.10.75",
            "connection": "remote-ssh",
            "ssh_config": {"user": "sjcta", "port": 2222},
        }
        inst = {"id": "i1", "name": "B", "service": "comfyui-b"}

        with mock.patch("app.subprocess.run", side_effect=fake_run):
            self.assertTrue(app._run_instance_action(node, inst, "start"))

        self.assertTrue(calls)
        cmd = calls[0]
        self.assertEqual(cmd[:4], ["ssh", "-p", "2222", "sjcta@10.10.10.75"])
        self.assertIn("systemctl", cmd)
        self.assertLess(cmd.index("2222"), cmd.index("sjcta@10.10.10.75"))

    def test_remote_status_checks_place_ssh_port_before_destination(self):
        calls = []

        class Result:
            returncode = 0
            stdout = "ok\n"
            stderr = ""

        def fake_run(cmd, **_kwargs):
            calls.append(cmd)
            return Result()

        node = {
            "id": "n1",
            "name": "DGX Spark",
            "host": "10.10.10.75",
            "connection": "remote-ssh",
            "ssh_config": {"user": "sjcta", "port": 2222},
        }

        with mock.patch("app.subprocess.run", side_effect=fake_run):
            self.assertTrue(app._check_node_ssh(node))
            app._run_remote_gpu_query(node)

        self.assertGreaterEqual(len(calls), 2)
        for cmd in calls:
            self.assertEqual(cmd[:4], ["ssh", "-p", "2222", "sjcta@10.10.10.75"])
            self.assertLess(cmd.index("2222"), cmd.index("sjcta@10.10.10.75"))

    def test_remote_service_active_places_ssh_port_before_destination(self):
        calls = []

        class Result:
            stdout = "active\n"

        def fake_run(cmd, **_kwargs):
            calls.append(cmd)
            return Result()

        node = {
            "id": "n1",
            "name": "DGX Spark",
            "host": "10.10.10.75",
            "connection": "remote-ssh",
            "ssh_config": {"user": "sjcta", "port": 2222},
        }
        inst = {"id": "i1", "name": "B", "service": "comfyui-b"}

        with mock.patch("app.subprocess.run", side_effect=fake_run):
            self.assertTrue(app._check_service_active(node, inst))

        self.assertEqual(calls[0][:4], ["ssh", "-p", "2222", "sjcta@10.10.10.75"])
        self.assertLess(calls[0].index("2222"), calls[0].index("sjcta@10.10.10.75"))

    def test_submitting_jobs_use_short_stuck_timeout(self):
        job = {"status": "submitting", "last_update": 100.0}

        stuck, age, timeout = app._job_stuck_state(job, now=191.0)

        self.assertTrue(stuck)
        self.assertEqual(age, 91.0)
        self.assertEqual(timeout, app.JOB_STAGE_TIMEOUTS["submitting"])

    def test_generating_jobs_use_longer_progress_timeout(self):
        job = {"status": "generating", "last_update": 100.0}

        stuck, age, timeout = app._job_stuck_state(job, now=500.0)

        self.assertFalse(stuck)
        self.assertEqual(age, 400.0)
        self.assertEqual(timeout, app.JOB_STAGE_TIMEOUTS["generating"])

    def test_video_generating_jobs_allow_long_decode_quiet_period(self):
        job = {"status": "generating", "last_update": 100.0, "workflow_type": "图生视频"}

        stuck, age, timeout = app._job_stuck_state(job, now=1401.0)

        self.assertFalse(stuck)
        self.assertEqual(age, 1301.0)
        self.assertGreater(timeout, app.JOB_STAGE_TIMEOUTS["generating"])

    def test_video_workflows_use_longer_ws_track_timeout(self):
        self.assertGreater(
            _workflow_track_timeout({"workflow_type": "图生视频"}, "i2v_ltx23_sulphur.json"),
            900,
        )

    def test_stuck_job_finalizer_marks_error_and_cancels_task(self):
        async def never_finishes():
            await app.asyncio.sleep(60)

        async def run_case():
            app.jobs["job-stuck"] = {
                "id": "job-stuck",
                "status": "submitting",
                "last_update": 100.0,
                "instance": "A",
            }
            task = app.asyncio.create_task(never_finishes())
            app._job_tasks["job-stuck"] = task
            try:
                app._finalize_stuck_job("job-stuck", app.jobs["job-stuck"], now=200.0)
                self.assertEqual(app.jobs["job-stuck"]["status"], "error")
                self.assertIn("提交阶段超时", app.jobs["job-stuck"]["message"])
                self.assertTrue(task.cancelled() or task.cancelling())
                self.assertNotIn("job-stuck", app._job_tasks)
            finally:
                if not task.done():
                    task.cancel()
                app.jobs.pop("job-stuck", None)
                app._job_tasks.pop("job-stuck", None)

        app.asyncio.run(run_case())


if __name__ == "__main__":
    unittest.main()
