from pathlib import Path
import inspect
import unittest

import app
from starlette.requests import Request


ROOT = Path(__file__).resolve().parents[1]


class LabsUiContractTests(unittest.TestCase):
    def test_main_page_links_to_labs_without_workflow_card_integration(self):
        index_html = (ROOT / "static/index.html").read_text()
        css = (ROOT / "static/css/style.css").read_text()
        auth_js = (ROOT / "static/js/modules/auth.js").read_text()

        self.assertIn('id="labEntryRow" data-admin-only="true"', index_html)
        self.assertIn('class="lab-entry-btn" href="labs"', index_html)
        self.assertIn("测试实验室", index_html)
        self.assertIn(".lab-entry-btn", css)
        self.assertIn("querySelectorAll('[data-admin-only=\"true\"]')", auth_js)
        self.assertIn("_currentUser && _currentUser.role === 'admin'", auth_js)
        self.assertNotIn("JoyAI-Echo.json", index_html)

    def test_labs_page_uses_independent_api_and_resource_lock(self):
        labs_html = (ROOT / "static/labs/index.html").read_text()
        labs_js = (ROOT / "static/labs/lab.js").read_text()

        self.assertIn("../static/labs/lab.css", labs_html)
        self.assertIn("../static/icons/ez-site-logo-64.png", labs_html)
        self.assertIn("../labs/bernini", labs_html)
        self.assertIn("../labs/hyworld2", labs_html)
        self.assertIn('class="lab-back" href="../"', labs_html)
        self.assertIn("var APP_BASE = location.pathname.replace", labs_js)
        self.assertIn("appUrl('/api/labs/projects')", labs_js)
        self.assertIn("appUrl('/api/resource-lock/acquire')", labs_js)
        self.assertIn("appUrl('/api/resource-lock/release')", labs_js)
        self.assertIn("appUrl('/api/labs/playground/start')", labs_js)
        self.assertIn("appUrl('/api/labs/playground/runs/'", labs_js)
        self.assertIn('class="playground-form"', labs_html)
        self.assertIn('name="image_files"', labs_html)
        self.assertIn('name="video_files"', labs_html)
        self.assertIn("启动测试", labs_html)
        self.assertIn("projectTemplate", labs_html)
        self.assertNotIn("/api/generate", labs_js)

    def test_labs_html_routes_render_shell_with_optional_auth(self):
        self.assertEqual(
            inspect.signature(app.labs_index).parameters["current_user"].default.dependency,
            app.get_current_user_optional,
        )
        self.assertEqual(
            inspect.signature(app.labs_project).parameters["current_user"].default.dependency,
            app.get_current_user_optional,
        )

    def test_labs_html_rewrites_static_urls_for_proxy_prefix(self):
        request = Request({
            "type": "http",
            "method": "GET",
            "path": "/dgx/18000/labs",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "scheme": "http",
        })
        html = app._render_labs_html(request).body.decode()
        self.assertIn('href="/dgx/18000/static/labs/lab.css', html)
        self.assertIn('src="/dgx/18000/static/icons/ez-site-logo-64.png"', html)
        self.assertIn('href="/dgx/18000/labs/hyworld2"', html)

        forwarded = Request({
            "type": "http",
            "method": "GET",
            "path": "/labs",
            "headers": [(b"x-forwarded-prefix", b"/dgx/18000")],
            "query_string": b"",
            "server": ("testserver", 80),
            "scheme": "http",
        })
        forwarded_html = app._render_labs_html(forwarded).body.decode()
        self.assertIn('href="/dgx/18000/static/labs/lab.css', forwarded_html)

    def test_labs_html_uses_relative_urls_when_proxy_strips_prefix(self):
        index_request = Request({
            "type": "http",
            "method": "GET",
            "path": "/labs",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "scheme": "http",
        })
        index_html = app._render_labs_html(index_request).body.decode()
        self.assertIn('href="static/labs/lab.css', index_html)
        self.assertIn('src="static/icons/ez-site-logo-64.png"', index_html)
        self.assertIn('href="labs/hyworld2"', index_html)

        project_request = Request({
            "type": "http",
            "method": "GET",
            "path": "/labs/hyworld2",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "scheme": "http",
        })
        project_html = app._render_labs_html(project_request).body.decode()
        self.assertIn('href="../static/labs/lab.css', project_html)
        self.assertIn('href="../labs/hyworld2"', project_html)

    def test_manifests_track_official_sources_and_cases(self):
        bernini = (ROOT / "data/labs/manifests/bernini.json").read_text()
        joyai = (ROOT / "data/labs/manifests/joyai_echo.json").read_text()
        hyworld2 = (ROOT / "data/labs/manifests/hyworld2.json").read_text()

        self.assertIn("https://github.com/bytedance/Bernini", bernini)
        self.assertIn("assets/testcases/t2i/t2i.json", bernini)
        self.assertIn('"id": "rv2v"', bernini)
        self.assertIn("https://github.com/jd-opensource/JoyAI-Echo", joyai)
        self.assertIn("prompts/test_001.json", joyai)
        self.assertIn('"id": "multishot"', joyai)
        self.assertIn("https://github.com/Tencent-Hunyuan/HY-World-2.0", hyworld2)
        self.assertIn("HY-WorldMirror-2.0/model.safetensors", hyworld2)
        self.assertIn('"id": "worldrecon-images"', hyworld2)
        self.assertIn("resource_lock", bernini)
        self.assertIn("resource_lock", joyai)
        self.assertIn("resource_lock", hyworld2)


if __name__ == "__main__":
    unittest.main()
