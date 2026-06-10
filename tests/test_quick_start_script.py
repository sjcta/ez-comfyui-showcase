from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class QuickStartScriptTests(unittest.TestCase):
    def test_restart_uses_kickstart_without_stop_start_chain(self):
        script = (ROOT / "quick-start.sh").read_text()

        self.assertIn("restart_service()", script)
        self.assertIn('launchctl kickstart -k "$DOMAIN/$LABEL"', script)
        restart_case = re.search(r"\n\s*restart\)\n(?P<body>.*?)\n\s*;;", script, re.S)
        self.assertIsNotNone(restart_case)
        self.assertIn("restart_service", restart_case.group("body"))
        self.assertNotIn("stop_service || true", restart_case.group("body"))
        self.assertNotIn("start_service\n", restart_case.group("body"))

    def test_stop_only_reports_stopped_after_successful_bootout(self):
        script = (ROOT / "quick-start.sh").read_text()

        stop_fn = re.search(r"\nstop_service\(\) \{\n(?P<body>.*?)\n\}", script, re.S)
        self.assertIsNotNone(stop_fn)
        self.assertIn('if launchctl bootout "$DOMAIN/$LABEL"; then', stop_fn.group("body"))
        self.assertIn('echo "$APP_NAME stopped."', stop_fn.group("body"))
        self.assertIn("return 1", stop_fn.group("body"))


if __name__ == "__main__":
    unittest.main()
