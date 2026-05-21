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


if __name__ == "__main__":
    unittest.main()
