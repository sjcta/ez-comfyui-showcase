from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HistoryLazyLoadingUiContractTests(unittest.TestCase):
    def test_history_renderers_keep_visible_count_batched(self):
        source = (ROOT / "static/js/modules/history.js").read_text()
        card_manager = (ROOT / "static/js/modules/card_manager.js").read_text()
        self.assertNotIn("_histVisibleCount = displayArr.length", source)
        self.assertIn(
            "_histVisibleCount = Math.min(Math.max(_histVisibleCount, _batchSize()), displayArr.length);",
            source,
        )
        self.assertIn("masonry-sentinel", source)
        self.assertIn("IntersectionObserver", source)
        self.assertNotIn("IntersectionObserver", card_manager)

    def test_history_module_has_no_leftover_gallery_debug_logs(self):
        source = (ROOT / "static/js/modules/history.js").read_text()

        self.assertNotIn('console.log("[DEBUG]', source)
        self.assertNotIn('console.log("[GALLERY DEBUG]', source)
        self.assertNotIn("console.log('[HIST]", source)

    def test_filtered_empty_lazy_load_has_auto_cap_without_continue_button(self):
        source = (ROOT / "static/js/modules/history.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn("HISTORY_FILTER_AUTO_LOAD_PAGE_LIMIT = 3", source)
        self.assertIn("var _historyFilterAutoLoads = 0;", source)
        self.assertIn("function _canAutoLoadMoreHistory()", source)
        self.assertIn("data-auto-load-disabled=\"1\"", source)
        self.assertIn("CW.loadMoreHistory", source)
        self.assertIn("正在加载历史", source)
        self.assertIn("历史加载失败", source)
        self.assertIn("可调整筛选条件", source)
        self.assertNotIn("继续查找", source)
        self.assertNotIn("masonry-sentinel is-paused", source)
        self.assertIn(".masonry-sentinel.is-loading", css)
        self.assertNotIn(".masonry-sentinel.is-paused", css)
        self.assertIn(".gallery-load-more-btn", css)

    def test_type_filter_uses_server_pagination_and_discards_stale_loads(self):
        source = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("var _historyFilterToken = 0;", source)
        self.assertIn("function _bumpHistoryFilterToken()", source)
        self.assertIn("HISTORY_FILTERED_PAGE_SIZE = 5000", source)
        self.assertIn("params.set('workflow_type', _galleryFilters.type)", source)
        self.assertIn("_reloadHistoryWindow(false, filterToken)", source)
        self.assertIn("if (filterToken !== _historyFilterToken) return;", source)

    def test_loaded_type_window_still_lazy_appends_local_cards(self):
        source = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("function _hasUndisplayedHistoryItems()", source)
        self.assertIn("return _histVisibleCount < activeItems.length;", source)
        can_start = source.index("function _canAutoLoadMoreHistory()")
        can_end = source.index("function _sentinelHtml()", can_start)
        can_body = source[can_start:can_end]
        self.assertIn("if (_hasUndisplayedHistoryItems()) return true;", can_body)
        self.assertLess(
            can_body.index("if (_hasUndisplayedHistoryItems()) return true;"),
            can_body.index("if (_historyLoadedAll) return false;"),
        )

    def test_lazy_append_keeps_lightbox_items_in_sync(self):
        source = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("function _syncLightboxHistoryItems(items)", source)
        self.assertIn("function _lightboxKeyFromSource(sourceEl)", source)

        append_start = source.index("function _appendNewHistoryCards()")
        append_end = source.index("function _histCardHTML", append_start)
        append_body = source[append_start:append_end]
        self.assertIn("const filteredArr2 = _groupHistoryForGallery", append_body)
        self.assertIn("_syncLightboxHistoryItems(filteredArr2);", append_body)
        self.assertLess(
            append_body.index("_syncLightboxHistoryItems(filteredArr2);"),
            append_body.index("const prevCount = _nextUnrenderedHistoryIndex(filteredArr2);"),
        )

        open_start = source.index("function openLB(idx, sourceEl, key)")
        open_end = source.index("function openBatchLB(batchId", open_start)
        open_body = source[open_start:open_end]
        self.assertIn("var sourceKey = _lightboxKeyFromSource(sourceEl);", open_body)
        self.assertIn("var keyText = String(sourceKey || key || '');", open_body)
        self.assertIn("_syncLightboxHistoryItems();", open_body)
        self.assertIn("_galleryEntryKey(entry) === keyText", open_body)

    def test_returning_from_type_filter_reloads_unfiltered_window(self):
        source = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("var _historyWindowType = '';", source)
        self.assertIn("_historyWindowType = _galleryFilters.type || '';", source)
        self.assertIn("var mustReloadWindow = !!_galleryFilters.type || !!_historyWindowType;", source)
        apply_start = source.index("function applyFilters()")
        apply_end = source.index("function clearFilters()", apply_start)
        apply_body = source[apply_start:apply_end]
        self.assertIn("if (mustReloadWindow)", apply_body)
        self.assertIn("_reloadHistoryWindow(false, filterToken)", apply_body)

    def test_type_filter_options_are_not_limited_to_current_history_window(self):
        source = (ROOT / "static/js/modules/history.js").read_text()

        start = source.index("function _historyTypeOptions()")
        end = source.index("function _sortTypeOptions", start)
        body = source[start:end]
        self.assertIn("Object.keys(A._wfMeta || {}).forEach", body)
        self.assertNotIn("return _sortTypeOptions(Array.from(fromHistory));", body)

    def test_history_update_ws_refreshes_open_gallery_pages(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()
        poll_js = (ROOT / "static/js/modules/poll_manager.js").read_text()

        self.assertIn("d.type === 'history_update'", poll_js)
        self.assertIn("self.onHistoryUpdate(d);", poll_js)
        self.assertIn("PollManager.prototype.onHistoryUpdate", poll_js)
        self.assertIn("typeof window.CW.onHistoryUpdate === 'function'", poll_js)
        self.assertIn("function onHistoryUpdate(update)", history_js)
        self.assertIn("window.CW.onHistoryUpdate = onHistoryUpdate;", history_js)
        self.assertIn("_renderGalleryAfterHistoryRemoval(deletedEntryKeys);", history_js)
        self.assertIn("Promise.resolve(loadHistory()).catch", history_js)


if __name__ == "__main__":
    unittest.main()
