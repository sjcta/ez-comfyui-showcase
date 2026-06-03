from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HistoryDeleteFocusContractTests(unittest.TestCase):
    def test_delete_history_clears_delete_button_focus_after_rerender(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("function _clearHistoryDeleteFocus", history_js)
        self.assertIn("classList.contains('gi-del')", history_js)

        del_start = history_js.index("async function delHist")
        del_end = history_js.index("async function _fetchHistoryPage", del_start)
        focus_clear_before = history_js.index("_clearHistoryDeleteFocus();", del_start)
        focus_clear_after = history_js.index("_clearHistoryDeleteFocus();", focus_clear_before + 1)

        self.assertLess(focus_clear_before, del_end)
        self.assertLess(focus_clear_after, del_end)

    def test_delete_history_updates_single_dom_card_without_gallery_reload(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("function _removeDeletedHistoryCardsFromDom(entryKeys)", history_js)
        self.assertIn("function _reorderVisibleHistoryCardsFromData()", history_js)
        self.assertIn("function _syncVisibleHistoryCardIndices()", history_js)
        self.assertIn("function _blockGalleryRenderForAtomicDelete(ms)", history_js)
        self.assertIn("_historyTotal = Math.max(0, _historyTotal - deleted.size)", history_js)
        self.assertIn("_historyNextOffset = Math.max(0, _historyNextOffset - deleted.size)", history_js)
        self.assertIn("visibleAfterDelete === 0", history_js)

        del_start = history_js.index("async function delHist")
        del_end = history_js.index("async function _fetchHistoryPage", del_start)
        del_body = history_js[del_start:del_end]
        remove_call = history_js.index("_removeDeletedHistoryCardsFromDom(deletedEntryKeys);", del_start)
        reorder_call = history_js.index("_reorderVisibleHistoryCardsFromData();", del_start)
        sync_call = history_js.index("_syncVisibleHistoryCardIndices();", del_start)
        workflow_refresh = history_js.index("CW.loadWorkflows", del_start)
        self.assertLess(remove_call, reorder_call)
        self.assertLess(reorder_call, sync_call)
        self.assertLess(sync_call, workflow_refresh)
        self.assertIn("renderGallery();", del_body)
        self.assertNotIn("_reloadHistoryWindow(true)", del_body)
        self.assertIn("_blockGalleryRenderForAtomicDelete(1800);", del_body)

    def test_atomic_delete_reorders_remaining_history_cards_from_data_order(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        fn_start = history_js.index("function _reorderVisibleHistoryCardsFromData()")
        fn_end = history_js.index("function _syncHistoryCountText", fn_start)
        fn_body = history_js[fn_start:fn_end]

        self.assertIn("_groupHistoryForGallery(filteredArr)", fn_body)
        self.assertIn("_galleryEntryKey(entry)", fn_body)
        self.assertIn("var html = _histCardHTML(entry, idx);", fn_body)
        self.assertIn("cursor.insertAdjacentHTML('beforebegin', html);", fn_body)
        self.assertIn("gallery.insertBefore(card, cursor);", fn_body)
        self.assertIn("cursor = card.nextSibling;", fn_body)
        self.assertIn("_lastRenderedHistCount = gallery.querySelectorAll('.gi[data-hist-id]').length;", fn_body)

    def test_render_gallery_is_blocked_during_atomic_delete_window(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        render_start = history_js.index("function renderGallery()")
        render_end = history_js.index("if (!window.CW) window.CW = {};", render_start)
        render_body = history_js[render_start:render_end]

        self.assertIn("_atomicDeleteRenderBlockUntil", render_body)
        self.assertIn("Date.now() < _atomicDeleteRenderBlockUntil", render_body)
        self.assertIn("requestAnimationFrame(function()", render_body)

    def test_delete_history_preserves_current_scroll_position(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("function _historyScrollRoot()", history_js)
        self.assertIn("document.querySelector('.workspace')", history_js)
        self.assertIn("function _isScrollableHistoryRoot(el)", history_js)
        self.assertIn("window.getComputedStyle(el)", history_js)
        self.assertIn("el && el.scrollTop > 0", history_js)
        self.assertIn("function _captureHistoryScroll()", history_js)
        self.assertIn("function _restoreHistoryScroll(snapshot)", history_js)

        del_start = history_js.index("async function delHist")
        capture_call = history_js.index("var scrollSnapshot = _captureHistoryScroll();", del_start)
        sync_call = history_js.index("_syncVisibleHistoryCardIndices();", del_start)
        restore_call = history_js.index("_restoreHistoryScroll(scrollSnapshot);", sync_call)

        self.assertLess(capture_call, sync_call)
        self.assertGreater(restore_call, sync_call)

    def test_deleted_history_ids_are_tombstoned_against_stale_lazy_loads(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("var _deletedHistoryIds = {};", history_js)
        self.assertIn("HISTORY_DELETE_TOMBSTONE_TTL_MS", history_js)
        self.assertIn("function _markHistoryIdsDeleted(ids)", history_js)
        self.assertIn("function _filterDeletedHistoryItems(items)", history_js)
        self.assertIn("function _removeOptimisticHistoryIds(ids)", history_js)
        self.assertIn("var items = _filterDeletedHistoryItems(d.data || []);", history_js)
        self.assertIn("raw_count: Array.isArray(d.data) ? d.data.length : items.length", history_js)

        del_start = history_js.index("async function delHist")
        del_end = history_js.index("async function _fetchHistoryPage", del_start)
        del_body = history_js[del_start:del_end]
        self.assertIn("_markHistoryIdsDeleted(deleteIds);", del_body)
        self.assertIn("_removeOptimisticHistoryIds(deleteIds);", del_body)
        self.assertIn("_unmarkHistoryIdsDeleted(deleteIds);", del_body)


if __name__ == "__main__":
    unittest.main()
