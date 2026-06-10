from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class JobCardBadgeUiContractTests(unittest.TestCase):
    def test_job_cards_use_centered_workflow_type_badge_only(self):
        history_js = (ROOT / "static" / "js" / "modules" / "history.js").read_text("utf-8")
        css = (ROOT / "static" / "css" / "style.css").read_text("utf-8")

        self.assertIn('const tagHtml = wfTag ? `<div class="gi-type-badge ${wfTag.cls}">${wfTag.text}</div>` : \'\';', history_js)
        self.assertIn("${tagHtml}", history_js)
        self.assertNotIn("instBadge", history_js)
        self.assertNotIn("gi-inst-badge", history_js)
        self.assertNotIn("gi-tags-row", history_js)
        self.assertIn("left: 50%", css)
        self.assertIn("transform: translateX(-50%)", css)
        self.assertNotIn(".gi-tags-row", css)
        self.assertNotIn(".gi-inst-badge", css)


if __name__ == "__main__":
    unittest.main()
