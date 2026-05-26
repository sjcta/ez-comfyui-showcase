import json
import unittest
import urllib.error
from unittest.mock import patch

import app
from modules.instance_manager import InstanceManager
from modules import ws_tracker


class _Completed:
    returncode = 0
    stdout = "{}"
    stderr = ""


class ComfyUIHttpFallbackTests(unittest.TestCase):
    def test_app_comfyui_get_uses_curl_when_python_socket_cannot_route(self):
        with patch("app.urllib.request.urlopen", side_effect=urllib.error.URLError(OSError(65, "No route to host"))), \
             patch("app.shutil.which", return_value="/usr/bin/curl"), \
             patch("app.subprocess.run") as run:
            result = _Completed()
            result.stdout = json.dumps({"ok": True})
            run.return_value = result

            self.assertEqual(app.comfyui_get("/system_stats", base_url="http://10.10.10.75:8190"), {"ok": True})

            self.assertIn("--max-time", run.call_args.args[0])
            self.assertEqual(run.call_args.args[0][-1], "http://10.10.10.75:8190/system_stats")

    def test_ws_tracker_http_post_uses_curl_fallback(self):
        with patch("modules.ws_tracker.urllib.request.urlopen", side_effect=urllib.error.URLError(OSError(65, "No route to host"))), \
             patch("modules.ws_tracker.shutil.which", return_value="/usr/bin/curl"), \
             patch("modules.ws_tracker.subprocess.run") as run:
            result = _Completed()
            result.stdout = json.dumps({"prompt_id": "abc"})
            run.return_value = result

            payload = ws_tracker._http_post("http://10.10.10.75:8190/prompt", {"prompt": {}})

            self.assertEqual(payload, {"prompt_id": "abc"})
            self.assertIn("--data-binary", run.call_args.args[0])

    def test_instance_health_uses_curl_fallback(self):
        with patch("modules.instance_manager.urllib.request.urlopen", side_effect=urllib.error.URLError(OSError(65, "No route to host"))), \
             patch("modules.instance_manager.shutil.which", return_value="/usr/bin/curl"), \
             patch("modules.instance_manager.subprocess.run") as run:
            result = _Completed()
            result.stdout = "200"
            run.return_value = result

            self.assertTrue(InstanceManager._check_health("http://10.10.10.75:8190"))


if __name__ == "__main__":
    unittest.main()
