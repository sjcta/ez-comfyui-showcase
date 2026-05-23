from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BatchGalleryUiContractTests(unittest.TestCase):
    def test_batch_badge_lives_above_info_with_reuse_action(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()
        card_manager_js = (ROOT / "static/js/modules/card_manager.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()

        for src in (history_js, card_manager_js):
            self.assertIn("gi-info-actions", src)
            self.assertIn("batchBadge", src)
            self.assertIn("gi-reuse", src)
            self.assertNotIn("${batchBadge}\n      ${canDelete", src)
            self.assertNotIn("batchBadge +\n\t      (canDelete", src)

        self.assertIn(".gi-info-actions", css)
        self.assertIn(".gi:not(.job-card) .gi-info-actions .gi-reuse", css)
        self.assertIn(".gi:hover .gi-info-actions .gi-reuse", css)
        self.assertIn("pointer-events: none;", css)
        self.assertIn("translateY(calc(-100% - 5px))", css)
        self.assertNotIn("bottom: 8px;\n  min-width: 30px", css)

    def test_batch_stack_uses_real_extra_thumbnails_not_empty_frames(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()
        card_manager_js = (ROOT / "static/js/modules/card_manager.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()

        for src in (history_js, card_manager_js):
            self.assertIn("function _batchStackImages", src)
            self.assertTrue(
                "gi-batch-layer-${idx + 1}" in src
                or "gi-batch-layer-' + (idx + 1)" in src
            )

        self.assertIn(".gi-batch-layer", css)
        self.assertIn(".gi-batch-layer-1", css)
        self.assertIn(".gi-batch-layer-2", css)
        self.assertNotIn(".gi-batch-stack .gi-img::before", css)
        self.assertNotIn(".gi-batch-stack .gi-img::after", css)

    def test_batch_card_delete_targets_whole_batch(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()
        card_manager_js = (ROOT / "static/js/modules/card_manager.js").read_text()

        self.assertIn("function _batchCanDelete", history_js)
        self.assertIn("function _batchDeleteTargetId", history_js)
        self.assertIn("/api/history/batch-delete", history_js)
        self.assertIn("确认将这个批次的 ${deleteIds.length} 张图片移入回收站", history_js)
        self.assertIn("已将 ${deleteIds.length} 张图片移入回收站", history_js)

        for src in (history_js, card_manager_js):
            self.assertIn("删除本批次", src)
            self.assertIn("CW.delHist", src)
            self.assertIn("_batchCanDelete(entry, h)", src)
            self.assertIn("_batchDeleteTargetId(entry, h)", src)


if __name__ == "__main__":
    unittest.main()
