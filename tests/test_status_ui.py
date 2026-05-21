from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class StatusUiContractTests(unittest.TestCase):
    def test_vram_status_filters_raw_ssh_errors(self):
        status_js = (ROOT / "static/js/modules/status.js").read_text()

        self.assertIn("function _safeVramMessage", status_js)
        self.assertIn("connection\\s+closed", status_js)
        self.assertIn("port\\s+\\d+", status_js)
        self.assertIn("VRAM 暂不可用", status_js)
        self.assertIn("_safeVramMessage(gpu)", status_js)
        self.assertNotIn("gpu && gpu.message ? gpu.message", status_js)

    def test_status_poll_sends_current_device_target(self):
        status_js = (ROOT / "static/js/modules/status.js").read_text()

        self.assertIn("new URLSearchParams()", status_js)
        self.assertIn("target_node_id", status_js)
        self.assertIn("target_instance", status_js)


if __name__ == "__main__":
    unittest.main()
