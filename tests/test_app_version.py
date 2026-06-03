from pathlib import Path
import unittest

import app


ROOT = Path(__file__).resolve().parents[1]


class AppVersionTests(unittest.TestCase):
    def test_version_file_is_project_source(self):
        self.assertEqual((ROOT / "VERSION").read_text("utf-8").strip(), "v4.6.19")

    def test_backend_exposes_project_version(self):
        self.assertEqual(app.APP_VERSION, "v4.6.19")
        self.assertEqual(app.app.version, "v4.6.19")
        self.assertEqual(app.api_version(), {"version": "v4.6.19"})


if __name__ == "__main__":
    unittest.main()
