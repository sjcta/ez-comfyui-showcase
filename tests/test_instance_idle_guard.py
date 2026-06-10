import asyncio
import unittest
from unittest import mock

import app
from modules import instance_manager as instance_manager_module
from modules.instance_manager import InstanceManager
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
            self.assertEqual(cmd[:3], ["ssh", "-p", "2222"])
            self.assertIn("sjcta@10.10.10.75", cmd)
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

    def test_instance_manager_force_restarts_if_cold_start_not_ready_after_30s(self):
        inst = {"id": "i-b", "name": "B", "service": "comfyui-b", "url": "http://b", "_node_id": "n1"}
        mgr = InstanceManager(lambda: [inst])
        actions = []
        clock = {"now": 0.0}

        async def fake_sleep(seconds):
            clock["now"] += float(seconds)

        async def fake_health(_inst, force=False):
            return "force-restart" in actions and clock["now"] >= 34

        def fake_action(_node, _inst, action):
            actions.append(action)
            return True

        async def run_case():
            with mock.patch.object(instance_manager_module.asyncio, "sleep", side_effect=fake_sleep), \
                 mock.patch.object(instance_manager_module.time, "time", side_effect=lambda: clock["now"]):
                mgr.health = fake_health
                mgr._get_node_by_id = lambda _node_id: {"id": "n1", "connection": "remote-ssh"}
                mgr._run_instance_action = fake_action
                self.assertTrue(await mgr.ensure_running(inst, timeout=60))

        asyncio.run(run_case())

        self.assertEqual(actions, ["start", "force-restart"])

    def test_submitting_jobs_use_short_stuck_timeout(self):
        job = {"status": "submitting", "last_update": 100.0}

        stuck, age, timeout = app._job_stuck_state(job, now=191.0)

        self.assertTrue(stuck)
        self.assertEqual(age, 91.0)
        self.assertEqual(timeout, app.JOB_STAGE_TIMEOUTS["submitting"])

    def test_queued_jobs_do_not_expire_while_waiting(self):
        job = {"status": "queued", "last_update": 100.0}

        stuck, age, timeout = app._job_stuck_state(job, now=864100.0)

        self.assertFalse(stuck)
        self.assertEqual(age, 864000.0)
        self.assertIsNone(timeout)

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

    def test_longcat_workflows_use_video_timeouts_even_when_tagged_as_test(self):
        job = {"status": "generating", "last_update": 100.0, "workflow": "longcat_avatar15_q4_smoke.json"}

        stuck, age, timeout = app._job_stuck_state(job, now=1401.0)

        self.assertFalse(stuck)
        self.assertEqual(age, 1301.0)
        self.assertGreater(timeout, app.JOB_STAGE_TIMEOUTS["generating"])
        self.assertEqual(
            _workflow_track_timeout({"workflow_type": "测试"}, "longcat_avatar15_q4_smoke.json"),
            3600,
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

    def test_node_instance_stop_finalizes_active_job_and_kicks_queue(self):
        old_queue = app._job_queue
        old_tasks = dict(app._job_tasks)
        app._job_queue = asyncio.Queue()
        cancel_task = mock.Mock()
        cancel_task.done.return_value = False
        node = {
            "id": "n1",
            "name": "DGX Spark",
            "connection": "remote-ssh",
            "instances": [{"id": "i-b", "name": "B"}],
        }
        app.jobs["job-active-b"] = {
            "id": "job-active-b",
            "status": "generating",
            "instance": "B",
            "last_update": 100.0,
        }
        app.jobs["job-next"] = {
            "id": "job-next",
            "status": "queued",
            "workflow": "i2v_ltx23_sulphur.json",
            "fields": {},
            "seed": "123",
            "user_id": "u1",
        }
        app._job_tasks["job-active-b"] = cancel_task

        try:
            with mock.patch("app._get_node_by_id", return_value=node), \
                    mock.patch("app._ensure_node_access", return_value=node), \
                    mock.patch("app._run_instance_action", return_value=True), \
                    mock.patch("app._resolve_workflow", return_value="/tmp/i2v_ltx23_sulphur.json"), \
                    mock.patch("app.save_jobs"), \
                    mock.patch("app.add_log"):
                result = app.api_node_instance_stop(
                    "n1",
                    "i-b",
                    current_user={"sub": "admin", "role": "admin"},
                )
            active_status = app.jobs["job-active-b"]["status"]
            active_message = app.jobs["job-active-b"]["message"]
            queued_job_id = app._job_queue.get_nowait()[0]
        finally:
            app._job_queue = old_queue
            app._job_tasks.clear()
            app._job_tasks.update(old_tasks)
            app.jobs.pop("job-active-b", None)
            app.jobs.pop("job-next", None)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(active_status, "error")
        self.assertIn("实例已停止", active_message)
        cancel_task.cancel.assert_called_once()
        self.assertEqual(queued_job_id, "job-next")

    def test_gpu_stall_detection_is_per_stage_after_one_minute(self):
        job = {
            "id": "job-gpu-stall",
            "status": "generating",
            "instance": "B",
            "progress": {"pct": 12, "current_node": "CLIPTextEncode"},
        }
        app._job_gpu_activity_watch.clear()
        idle_stats = {"vram_used_mb": 42000, "util_pct": 0, "vram_total_mb": 122565}
        active_stats = {"vram_used_mb": 42000, "util_pct": 12, "vram_total_mb": 122565}

        try:
            self.assertFalse(app._job_gpu_activity_stalled("job-gpu-stall", job, idle_stats, now=100.0))
            self.assertFalse(app._job_gpu_activity_stalled("job-gpu-stall", job, idle_stats, now=150.0))
            self.assertTrue(app._job_gpu_activity_stalled("job-gpu-stall", job, idle_stats, now=160.0))

            self.assertFalse(app._job_gpu_activity_stalled("job-gpu-stall", job, active_stats, now=161.0))
            self.assertEqual(app._job_gpu_activity_watch["job-gpu-stall"]["idle_since"], 0)

            job["status"] = "downloading"
            self.assertFalse(app._job_gpu_activity_stalled("job-gpu-stall", job, idle_stats, now=162.0))
            self.assertEqual(app._job_gpu_activity_watch["job-gpu-stall"]["status"], "downloading")
            self.assertEqual(app._job_gpu_activity_watch["job-gpu-stall"]["idle_since"], 162.0)
        finally:
            app._job_gpu_activity_watch.clear()

    def test_gpu_stall_detection_requires_no_fluctuation_during_full_window(self):
        job = {
            "id": "job-gpu-window",
            "status": "generating",
            "instance": "B",
            "progress": {"pct": 12, "current_node": "CLIPTextEncode"},
        }
        app._job_gpu_activity_watch.clear()

        try:
            self.assertFalse(app._job_gpu_activity_stalled(
                "job-gpu-window",
                job,
                {"vram_used_mb": 42000, "util_pct": 0, "vram_total_mb": 122565},
                now=100.0,
            ))
            self.assertFalse(app._job_gpu_activity_stalled(
                "job-gpu-window",
                job,
                {"vram_used_mb": 42100, "util_pct": 0, "vram_total_mb": 122565},
                now=120.0,
            ))
            self.assertFalse(app._job_gpu_activity_stalled(
                "job-gpu-window",
                job,
                {"vram_used_mb": 42000, "util_pct": 0, "vram_total_mb": 122565},
                now=160.0,
            ))
            self.assertEqual(app._job_gpu_activity_watch["job-gpu-window"]["idle_since"], 160.0)
            self.assertFalse(app._job_gpu_activity_stalled(
                "job-gpu-window",
                job,
                {"vram_used_mb": 42000, "util_pct": 0, "vram_total_mb": 122565},
                now=219.0,
            ))
            self.assertTrue(app._job_gpu_activity_stalled(
                "job-gpu-window",
                job,
                {"vram_used_mb": 42000, "util_pct": 0, "vram_total_mb": 122565},
                now=220.0,
            ))
        finally:
            app._job_gpu_activity_watch.clear()

    def test_gpu_stall_detection_records_progress_vram_and_gpu_each_sample(self):
        job = {
            "id": "job-gpu-sample",
            "status": "generating",
            "instance": "B",
            "progress": {"pct": 24, "current_node": "LTXVLatentUpsampler"},
        }
        app._job_gpu_activity_watch.clear()
        stats = {"vram_used_mb": 43001, "util_pct": 0, "vram_total_mb": 122565}

        try:
            self.assertFalse(app._job_gpu_activity_stalled("job-gpu-sample", job, stats, now=200.0))
            sample = app._job_gpu_activity_watch["job-gpu-sample"]
            self.assertEqual(sample["status"], "generating")
            self.assertEqual(sample["progress_pct"], 24)
            self.assertEqual(sample["current_node"], "LTXVLatentUpsampler")
            self.assertEqual(sample["vram_used_mb"], 43001)
            self.assertEqual(sample["util_pct"], 0)
            self.assertEqual(sample["idle_since"], 200.0)
            self.assertEqual(len(sample["samples"]), 1)

            job["progress"] = {"pct": 25, "current_node": "LTXVLatentUpsampler"}
            self.assertFalse(app._job_gpu_activity_stalled("job-gpu-sample", job, stats, now=230.0))
            sample = app._job_gpu_activity_watch["job-gpu-sample"]
            self.assertEqual(sample["progress_pct"], 25)
            self.assertEqual(sample["idle_since"], 230.0)
        finally:
            app._job_gpu_activity_watch.clear()

    def test_gpu_stall_detection_requires_stable_vram(self):
        job = {
            "id": "job-gpu-vram",
            "status": "generating",
            "instance": "B",
            "progress": {"pct": 12, "current_node": "KSampler"},
        }
        app._job_gpu_activity_watch.clear()

        try:
            self.assertFalse(app._job_gpu_activity_stalled(
                "job-gpu-vram",
                job,
                {"vram_used_mb": 42000, "util_pct": 0, "vram_total_mb": 122565},
                now=100.0,
            ))
            self.assertFalse(app._job_gpu_activity_stalled(
                "job-gpu-vram",
                job,
                {"vram_used_mb": 42512, "util_pct": 0, "vram_total_mb": 122565},
                now=160.0,
            ))
            self.assertEqual(app._job_gpu_activity_watch["job-gpu-vram"]["idle_since"], 160.0)
            self.assertFalse(app._job_gpu_activity_stalled(
                "job-gpu-vram",
                job,
                {"vram_used_mb": 42512, "util_pct": 0, "vram_total_mb": 122565},
                now=219.0,
            ))
            self.assertTrue(app._job_gpu_activity_stalled(
                "job-gpu-vram",
                job,
                {"vram_used_mb": 42512, "util_pct": 0, "vram_total_mb": 122565},
                now=220.0,
            ))
        finally:
            app._job_gpu_activity_watch.clear()

    def test_gpu_stalled_job_restarts_instance_and_requeues_same_job(self):
        old_queue = app._job_queue
        old_tasks = dict(app._job_tasks)
        app._job_queue = asyncio.Queue()
        cancel_task = mock.Mock()
        cancel_task.done.return_value = False
        app.jobs["job-gpu-stall"] = {
            "id": "job-gpu-stall",
            "status": "generating",
            "instance": "B",
            "workflow": "i2v_ltx23_10eros.json",
            "fields": {"1::text": "hello"},
            "seed": "123",
            "width": 720,
            "height": 1280,
            "user_id": "u1",
            "prompt_id": "prompt-123",
            "client_id": "client-123",
            "submitted_at": 100.0,
            "generating_at": 101.0,
        }
        app._job_tasks["job-gpu-stall"] = cancel_task
        inst = {"name": "B", "url": "http://b", "_node_id": "n1"}
        node = {"id": "n1", "connection": "remote-ssh"}

        async def run_case():
            with mock.patch("app._resolve_workflow", return_value="/tmp/i2v_ltx23_10eros.json"), \
                    mock.patch("app._get_node_by_id", return_value=node), \
                    mock.patch("app._run_instance_action", return_value=True) as run_action, \
                    mock.patch("app.comfyui_post"), \
                    mock.patch("app.save_jobs"), \
                    mock.patch("app.broadcast", new=mock.AsyncMock()), \
                    mock.patch("app.add_log"):
                restarted = await app._restart_gpu_stalled_job("job-gpu-stall", app.jobs["job-gpu-stall"], inst, now=200.0)
            self.assertTrue(restarted)
            run_action.assert_called_once_with(node, inst, "restart")

        try:
            asyncio.run(run_case())
            job = app.jobs["job-gpu-stall"]
            queued = app._job_queue.get_nowait()
        finally:
            app._job_queue = old_queue
            app._job_tasks.clear()
            app._job_tasks.update(old_tasks)
            app.jobs.pop("job-gpu-stall", None)

        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["message"], "检测到 GPU 60 秒窗口无波动，正在重启任务...")
        self.assertEqual(job["gpu_stall_retry_count"], 1)
        self.assertNotIn("prompt_id", job)
        cancel_task.cancel.assert_called_once()
        self.assertEqual(queued[0], "job-gpu-stall")


if __name__ == "__main__":
    unittest.main()
