from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HistoryLazyLoadingUiContractTests(unittest.TestCase):
    def test_history_renderers_keep_visible_count_batched(self):
        for rel in ("static/js/modules/history.js", "static/js/modules/card_manager.js"):
            source = (ROOT / rel).read_text()
            self.assertNotIn("_histVisibleCount = displayArr.length", source, rel)
            self.assertIn(
                "_histVisibleCount = Math.min(Math.max(_histVisibleCount, _batchSize()), displayArr.length);",
                source,
                rel,
            )
            self.assertIn("masonry-sentinel", source, rel)
            self.assertIn("IntersectionObserver", source, rel)

    def test_history_module_has_no_leftover_gallery_debug_logs(self):
        source = (ROOT / "static/js/modules/history.js").read_text()

        self.assertNotIn('console.log("[DEBUG]', source)
        self.assertNotIn('console.log("[GALLERY DEBUG]', source)
        self.assertNotIn("console.log('[HIST]", source)


if __name__ == "__main__":
    unittest.main()
