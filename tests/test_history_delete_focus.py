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
        self.assertIn("function _syncVisibleHistoryCardIndices()", history_js)
        self.assertIn("function _blockGalleryRenderForAtomicDelete(ms)", history_js)
        self.assertIn("_historyTotal = Math.max(0, _historyTotal - deleted.size)", history_js)
        self.assertIn("_historyNextOffset = Math.max(0, _historyNextOffset - deleted.size)", history_js)

        del_start = history_js.index("async function delHist")
        del_end = history_js.index("async function _fetchHistoryPage", del_start)
        del_body = history_js[del_start:del_end]
        remove_call = history_js.index("_removeDeletedHistoryCardsFromDom(deletedEntryKeys);", del_start)
        sync_call = history_js.index("_syncVisibleHistoryCardIndices();", del_start)
        workflow_refresh = history_js.index("CW.loadWorkflows", del_start)
        self.assertLess(remove_call, sync_call)
        self.assertLess(sync_call, workflow_refresh)
        self.assertNotIn("renderGallery();", del_body)
        self.assertNotIn("_reloadHistoryWindow(true)", del_body)
        self.assertIn("_blockGalleryRenderForAtomicDelete(1800);", del_body)

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


if __name__ == "__main__":
    unittest.main()
