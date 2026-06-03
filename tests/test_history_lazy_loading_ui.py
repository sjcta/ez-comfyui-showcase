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


if __name__ == "__main__":
    unittest.main()
