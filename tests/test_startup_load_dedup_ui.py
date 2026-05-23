from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class StartupLoadDedupUiTests(unittest.TestCase):
    def test_restore_session_does_not_refresh_main_data_before_loader_bootstrap(self):
        auth_js = (ROOT / "static/js/modules/auth.js").read_text()
        restore_start = auth_js.index("function restoreSession()")
        update_ui_after_auth = auth_js.index("_updateUI();", restore_start)
        schedule_after_auth = auth_js.index("_scheduleSiteNotifications();", update_ui_after_auth)
        restore_success_block = auth_js[update_ui_after_auth:schedule_after_auth]

        self.assertNotIn("refreshForAuthChange", restore_success_block)

    def test_main_loaders_dedupe_concurrent_startup_requests(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()
        workflows_js = (ROOT / "static/js/modules/workflows.js").read_text()

        self.assertIn("var _loadHistoryPromise = null;", history_js)
        self.assertIn("if (_loadHistoryPromise) return _loadHistoryPromise;", history_js)
        self.assertIn("_loadHistoryPromise.finally(function()", history_js)

        self.assertIn("var _loadWorkflowsPromise = null;", workflows_js)
        self.assertIn("if (_loadWorkflowsPromise) return _loadWorkflowsPromise;", workflows_js)
        self.assertIn("_loadWorkflowsPromise.finally(function()", workflows_js)


if __name__ == "__main__":
    unittest.main()
