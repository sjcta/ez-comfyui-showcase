from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TitlebarLayoutTest(unittest.TestCase):
    def test_mobile_logo_is_vertically_centered(self):
        css = (ROOT / "static/css/style.css").read_text()
        mobile = re.search(r"@media \(max-width: 600px\) \{(?P<body>.*?)\n\}", css, re.S)

        self.assertIsNotNone(mobile)
        body = mobile.group("body")
        self.assertIn(".titlebar {", body)
        self.assertIn("align-items: center;", body)
        self.assertNotIn("align-items: flex-start;", body)
        self.assertIn(".titlebar .logo {", body)
        self.assertIn("height: 30px;", body)

    def test_titlebar_shows_dynamic_version_badge(self):
        html = (ROOT / "static/index.html").read_text()
        css = (ROOT / "static/css/style.css").read_text()
        app_js = (ROOT / "static/js/app.js").read_text()

        self.assertIn('id="siteVersionBadge"', html)
        self.assertIn(".site-version-badge", css)
        self.assertIn("function initSiteVersionBadge()", app_js)
        self.assertIn("API + '/api/version'", app_js)
        self.assertIn("initSiteVersionBadge();", app_js)


if __name__ == "__main__":
    unittest.main()
