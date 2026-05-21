import unittest
from unittest import mock

import app


class StatusGpuMessageTests(unittest.TestCase):
    def test_empty_gpu_stats_keeps_raw_detail_out_of_message(self):
        stats = app._empty_gpu_stats("VRAM 暂不可用", "Connection closed by 10.10.10.75 port 22")

        self.assertEqual(stats["message"], "VRAM 暂不可用")
        self.assertIn("Connection closed", stats["detail"])
        self.assertNotIn("Connection closed", stats["message"])

    def test_remote_ssh_error_is_not_used_as_status_message(self):
        class Result:
            returncode = 255
            stdout = ""
            stderr = "Connection closed by 10.10.10.75 port 22"

        node = {
            "id": "dgx",
            "host": "10.10.10.75",
            "connection": "remote-ssh",
            "ssh_config": {"user": "root", "port": 22},
        }

        with mock.patch("app.subprocess.run", return_value=Result()):
            stats = app._run_remote_gpu_query(node)

        self.assertEqual(stats["message"], "VRAM 暂不可用")
        self.assertIn("Connection closed", stats["detail"])
        self.assertNotIn("10.10.10.75", stats["message"])

    def test_status_gpu_query_targets_one_selected_device(self):
        instances = [
            {"name": "A", "_node_id": "dgx", "url": "http://10.10.10.75:8190"},
            {"name": "B", "_node_id": "dgx", "url": "http://10.10.10.75:8189"},
            {"name": "C", "_node_id": "other", "url": "http://10.10.10.99:8188"},
        ]

        with mock.patch("app._get_node_by_id", side_effect=lambda node_id: {"id": node_id}), \
             mock.patch("app.get_node_gpu_stats", return_value={"vram_total_mb": 1}) as gpu_stats:
            stats_by_node = app._gpu_stats_for_status_node(instances, target_node_id="dgx", target_instance="B")

        self.assertEqual(list(stats_by_node.keys()), ["dgx"])
        gpu_stats.assert_called_once()
        self.assertEqual(gpu_stats.call_args.args[0]["id"], "dgx")

    def test_status_uses_remote_queue_counts_for_prompt_aux_instance(self):
        instances = [
            {"name": "A", "url": "http://a", "_node_id": "n1"},
            {"name": "Prompt", "url": "http://prompt", "_node_id": "n1", "roles": ["prompt_aux"]},
        ]

        with mock.patch("app._get_enabled_instances_for_user", return_value=instances), \
             mock.patch("app._gpu_stats_for_status_node", return_value={}), \
             mock.patch("app.comfyui_up", return_value=True), \
             mock.patch("app.comfyui_get") as comfyui_get:
            comfyui_get.side_effect = lambda path, base_url=None: (
                {"queue_running": [["1", "prompt-id"]], "queue_pending": []}
                if base_url == "http://prompt"
                else {"queue_running": [], "queue_pending": []}
            )

            status = app.api_status(current_user={"sub": "admin", "role": "admin"})

        prompt = next(item for item in status["instances"] if item["name"] == "Prompt")
        self.assertEqual(prompt["queue"], 1)
        self.assertEqual(prompt["queue_running"], 1)
        self.assertEqual(prompt["queue_pending"], 0)

    def test_status_includes_active_instance_progress(self):
        instances = [
            {"name": "A", "url": "http://a", "_node_id": "n1"},
            {"name": "B", "url": "http://b", "_node_id": "n1"},
        ]
        original_jobs = dict(app.jobs)
        app.jobs.clear()
        app.jobs["job-b"] = {
            "id": "job-b",
            "instance": "B",
            "status": "generating",
            "workflow": "i2i-Qwen-Edit-v2511.json",
            "prompt_preview": "portrait edit prompt",
            "progress": {"pct": 47},
            "last_update": 100.0,
        }

        try:
            with mock.patch("app._get_enabled_instances_for_user", return_value=instances), \
                 mock.patch("app._gpu_stats_for_status_node", return_value={}), \
                 mock.patch("app.comfyui_up", return_value=True), \
                 mock.patch("app.comfyui_get", return_value={"queue_running": [], "queue_pending": []}):
                status = app.api_status(current_user={"sub": "admin", "role": "admin"})
        finally:
            app.jobs.clear()
            app.jobs.update(original_jobs)

        inst_b = next(item for item in status["instances"] if item["name"] == "B")
        self.assertEqual(inst_b["queue_running"], 1)
        self.assertEqual(inst_b["progress"], 47)
        self.assertEqual(inst_b["current_workflow"], "i2i-Qwen-Edit-v2511")
        self.assertEqual(inst_b["current_prompt"], "portrait edit prompt")

    def test_status_marks_remote_running_without_local_job_as_untracked(self):
        instances = [
            {"name": "A", "url": "http://a", "_node_id": "n1"},
            {"name": "B", "url": "http://b", "_node_id": "n1"},
        ]
        original_jobs = dict(app.jobs)
        app.jobs.clear()
        app._untracked_remote_cleanup_at.clear()

        try:
            with mock.patch("app._get_enabled_instances_for_user", return_value=instances), \
                 mock.patch("app._gpu_stats_for_status_node", return_value={}), \
                 mock.patch("app.comfyui_up", return_value=True), \
                 mock.patch("app.comfyui_post", return_value={}) as comfyui_post, \
                 mock.patch("app.comfyui_get") as comfyui_get:
                comfyui_get.side_effect = lambda path, base_url=None: (
                    {"queue_running": [[0, "remote-prompt-id", {}, {}]], "queue_pending": []}
                    if base_url == "http://a"
                    else {"queue_running": [], "queue_pending": []}
                )
                status = app.api_status(current_user={"sub": "admin", "role": "admin"})
        finally:
            app.jobs.clear()
            app.jobs.update(original_jobs)

        inst_a = next(item for item in status["instances"] if item["name"] == "A")
        self.assertEqual(inst_a["queue_running"], 1)
        self.assertEqual(inst_a["progress"], 0)
        self.assertFalse(inst_a["progress_known"])
        self.assertTrue(inst_a["remote_untracked_running"])
        self.assertEqual(inst_a["remote_running_prompt_ids"], ["remote-prompt-id"])
        comfyui_post.assert_any_call("/queue", {"delete": ["remote-prompt-id"]}, base_url="http://a")
        comfyui_post.assert_any_call("/interrupt", {}, base_url="http://a")

    def test_comfyui_status_uses_remote_queue_counts_for_prompt_aux_instance(self):
        instances = [
            {"name": "A", "url": "http://a", "_node_id": "n1"},
            {"name": "Prompt", "url": "http://prompt", "_node_id": "n1", "roles": ["prompt_aux"]},
        ]

        with mock.patch("app._get_enabled_instances_for_user", return_value=instances), \
             mock.patch("app._gpu_stats_for_status_node", return_value={}), \
             mock.patch("app.comfyui_up", return_value=True), \
             mock.patch("app.comfyui_get") as comfyui_get:
            comfyui_get.side_effect = lambda path, base_url=None: (
                {"queue_running": [], "queue_pending": [["2", "prompt-id"]]}
                if base_url == "http://prompt"
                else {"queue_running": [], "queue_pending": []}
            )

            status = app.api_comfyui_status(current_user={"sub": "admin", "role": "admin"})

        prompt = next(item for item in status["instances"] if item["name"] == "Prompt")
        self.assertEqual(prompt["queue"], 1)
        self.assertEqual(prompt["queue_running"], 0)
        self.assertEqual(prompt["queue_pending"], 1)


if __name__ == "__main__":
    unittest.main()
