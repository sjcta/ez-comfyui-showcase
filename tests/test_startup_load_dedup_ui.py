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

    def test_logged_in_modules_do_not_block_primary_startup_data(self):
        loader_js = (ROOT / "static/js/module_loader.js").read_text()
        auth_ready_start = loader_js.index("authReady.then(function(user)")
        load_workflows_pos = loader_js.index("window.CW.loadWorkflows", auth_ready_start)
        load_logged_modules_pos = loader_js.index("loadLoggedInModules(user)", auth_ready_start)

        self.assertLess(load_workflows_pos, load_logged_modules_pos)

    def test_workflow_preview_uses_lightweight_preview_endpoint_with_history_fallback(self):
        workflows_js = (ROOT / "static/js/modules/workflows.js").read_text()
        preview_start = workflows_js.index("async function _loadWorkflowPreviewItems()")
        preview_end = workflows_js.index("function _workflowManagerThumbUrl", preview_start)
        preview_block = workflows_js[preview_start:preview_end]

        self.assertIn("/api/workflows/previews", preview_block)
        self.assertIn("return historyItems.slice();", preview_block)
        self.assertNotIn("/api/history?scope=mine&limit=300", preview_block)

    def test_main_history_initial_fetch_is_bounded(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("var HISTORY_PAGE_SIZE = 80;", history_js)
        self.assertIn("/api/history/summary", history_js)


if __name__ == "__main__":
    unittest.main()
