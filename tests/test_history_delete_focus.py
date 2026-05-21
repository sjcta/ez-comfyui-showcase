from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class HistoryDeleteFocusContractTests(unittest.TestCase):
    def test_delete_history_clears_delete_button_focus_after_rerender(self):
        history_js = (ROOT / "static/js/modules/history.js").read_text()

        self.assertIn("function _clearHistoryDeleteFocus", history_js)
        self.assertIn("classList.contains('gi-del')", history_js)

        del_start = history_js.index("async function delHist")
        render_call = history_js.index("renderGallery();", del_start)
        focus_clear_before = history_js.index("_clearHistoryDeleteFocus();", del_start)
        focus_clear_after = history_js.index("_clearHistoryDeleteFocus();", render_call)

        self.assertLess(focus_clear_before, render_call)
        self.assertGreater(focus_clear_after, render_call)


if __name__ == "__main__":
    unittest.main()
