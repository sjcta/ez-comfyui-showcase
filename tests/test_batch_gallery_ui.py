from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BatchGalleryUiContractTests(unittest.TestCase):
    def test_batch_badge_lives_above_info_with_reuse_action(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn("gi-info-actions", history_js)
        self.assertIn("batchBadge", history_js)
        self.assertIn("gi-reuse", history_js)
        self.assertNotIn("${batchBadge}\n      ${canDelete", history_js)
        self.assertNotIn("batchBadge +\n\t      (canDelete", history_js)

        self.assertIn(".gi-info-actions", css)
        self.assertIn(".gi:not(.job-card) .gi-info-actions .gi-reuse", css)
        self.assertIn(".gi:hover .gi-info-actions .gi-reuse", css)
        self.assertIn("pointer-events: none;", css)
        self.assertIn("translateY(calc(-100% - 5px))", css)
        self.assertNotIn("bottom: 8px;\n  min-width: 30px", css)

    def test_batch_stack_uses_real_extra_thumbnails_not_empty_frames(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn("function _batchStackImages", history_js)
        self.assertTrue(
            "gi-batch-layer-${idx + 1}" in history_js
            or "gi-batch-layer-' + (idx + 1)" in history_js
        )

        self.assertIn(".gi-batch-layer", css)
        self.assertIn(".gi-batch-layer-1", css)
        self.assertIn(".gi-batch-layer-2", css)
        self.assertNotIn(".gi-batch-stack .gi-img::before", css)
        self.assertNotIn(".gi-batch-stack .gi-img::after", css)

    def test_batch_card_delete_targets_whole_batch(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("function _batchCanDelete", history_js)
        self.assertIn("function _batchDeleteTargetId", history_js)
        self.assertIn("/api/history/batch-delete", history_js)
        self.assertIn("确认将这个批次的 ${deleteIds.length} 张图片移入回收站", history_js)
        self.assertIn("已将 ${deleteIds.length} 张图片移入回收站", history_js)

        self.assertIn("删除本批次", history_js)
        self.assertIn("CW.delHist", history_js)
        self.assertIn("_batchCanDelete(entry, h)", history_js)
        self.assertIn("_batchDeleteTargetId(entry, h)", history_js)
        self.assertIn("entry.items.find(function(item) { return _canDeleteHistoryItem(item); })", history_js)
        self.assertIn("CW.delHist('${escA(deleteTargetId)}', event)", history_js)


if __name__ == "__main__":
    unittest.main()
