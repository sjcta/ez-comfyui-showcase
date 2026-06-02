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

    def test_poll_manager_starts_after_auth_restore(self):
        loader_js = (ROOT / "static/js/module_loader.js").read_text()
        auth_ready_pos = loader_js.index("var authReady = window.CW.authReady")
        poll_start_pos = loader_js.index("window.CW.pollManager.start()", auth_ready_pos)
        load_workflows_pos = loader_js.index("window.CW.loadWorkflows", auth_ready_pos)

        self.assertLess(auth_ready_pos, poll_start_pos)
        self.assertLess(poll_start_pos, load_workflows_pos)

    def test_poll_manager_is_only_job_data_source(self):
        app_js = (ROOT / "static/js/app.js").read_text()
        poll_js = (ROOT / "static/js/modules/poll_manager.js").read_text()
        loader_js = (ROOT / "static/js/module_loader.js").read_text()

        for legacy in (
            "function pollJobs",
            "function connectWS",
            "function onJobUpdate",
            "function _pollActiveJobs",
            "function _isProtectedLocalSubmit",
            "let ws = null",
            "new WebSocket",
            "window.CW.onJobUpdate",
        ):
            self.assertNotIn(legacy, app_js)

        self.assertIn("new WebSocket", poll_js)
        self.assertIn("window.CW.onJobUpdate = function(job)", poll_js)
        self.assertIn("function _isProtectedLocalSubmit(job)", poll_js)

        init_poll_pos = loader_js.index("window.CW.initPollManager")
        boot_app_pos = loader_js.index("window.CW._bootApp")
        self.assertLess(init_poll_pos, boot_app_pos)

    def test_card_manager_is_thin_history_adapter(self):
        card_manager_js = (ROOT / "static/js/modules/card_manager.js").read_text()
        loader_js = (ROOT / "static/js/module_loader.js").read_text()

        self.assertIn("CardManager thin adapter", card_manager_js)
        self.assertIn("window.CW._patchJobCard(job)", card_manager_js)
        self.assertIn("window.CW._onJobDone(job)", card_manager_js)
        self.assertIn("window.CW._onJobError(job)", card_manager_js)
        self.assertIn("window.CW.forceGalleryRerender()", card_manager_js)

        for legacy in (
            "function _renderHistCard",
            "function _renderJobCard",
            "function _patchGalleryHTML",
            "function _groupHistoryForGallery",
            "function _isJobVisibleToCurrentUser",
            "function _neutralJobStatusMessage",
            "function _videoPreviewHtml",
            "IntersectionObserver",
            "ResizeObserver",
        ):
            self.assertNotIn(legacy, card_manager_js)

        history_pos = loader_js.index("base + '/modules/history.js")
        card_manager_pos = loader_js.index("base + '/modules/card_manager.js")
        self.assertLess(history_pos, card_manager_pos)

    def test_app_init_is_idempotent(self):
        app_js = (ROOT / "static/js/app.js").read_text()

        self.assertIn("if (window.CW.__appInitDone) return;", app_js)
        self.assertIn("window.CW.__appInitDone = true;", app_js)

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
        self.assertIn("&compact=1", history_js)

    def test_auth_uses_cookie_session_instead_of_browser_token_storage(self):
        auth_js = (ROOT / "static/js/modules/auth.js").read_text()
        workflows_js = (ROOT / "static/js/modules/workflows.js").read_text()
        poll_js = (ROOT / "static/js/modules/poll_manager.js").read_text()
        app_py = (ROOT / "app.py").read_text()

        self.assertNotIn("localStorage.getItem('v4_token')", auth_js)
        self.assertNotIn("localStorage.setItem('v4_token'", auth_js)
        self.assertNotIn("localStorage.getItem('v4_token')", workflows_js)
        self.assertNotIn("localStorage.getItem('v4_token')", poll_js)
        self.assertNotIn("'token=' + encodeURIComponent", poll_js)
        self.assertIn("credentials: 'include'", auth_js)
        self.assertIn("ws.cookies.get(AUTH_COOKIE_NAME)", app_py)

    def test_cookie_session_write_requests_attach_csrf_header(self):
        auth_js = (ROOT / "static/js/modules/auth.js").read_text()
        app_py = (ROOT / "app.py").read_text()

        self.assertIn("function _attachCsrfHeader(opts)", auth_js)
        self.assertIn("_readCookie('ez_comfyui_csrf')", auth_js)
        self.assertIn("'X-CSRF-Token': csrf", auth_js)
        self.assertIn("opts = _attachCsrfHeader(opts);", auth_js)
        self.assertIn("_CSRF_HEADER_NAME = \"X-CSRF-Token\"", app_py)
        self.assertIn("CSRF_COOKIE_NAME = \"ez_comfyui_csrf\"", app_py)

    def test_history_cards_lazy_load_full_reuse_details(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("function getHistoryDetail(itemOrId)", history_js)
        self.assertIn("window.CW.getHistoryDetail = getHistoryDetail", history_js)
        self.assertIn("`${API}/api/history/${encodeURIComponent(id)}`", history_js)
        self.assertIn("var _historyDetailCache = {};", history_js)
        self.assertIn("var HISTORY_DETAIL_CACHE_LIMIT = 24;", history_js)
        self.assertIn("function _compactHistoryRecord(item)", history_js)
        self.assertIn("delete record.field_values;", history_js)
        self.assertIn("return fullDetail;", history_js)
        self.assertIn("_cacheHistoryDetail(item);", history_js)
        self.assertIn("function _clampHistoryVisibleCount(count, total)", history_js)
        self.assertIn("var HISTORY_WINDOW_MAX_ITEMS = HISTORY_PAGE_SIZE * 4;", history_js)
        self.assertIn("function _historyRefreshWindowLimit()", history_js)
        self.assertIn("_clampHistoryVisibleCount(Math.max(prevVisibleCount, _lastRenderedHistCount || 0), filteredArr.length)", history_js)


if __name__ == "__main__":
    unittest.main()
