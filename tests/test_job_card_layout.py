from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _css_block(css, selector):
    pattern = re.compile(r"%s\s*\{([^}]*)\}" % re.escape(selector), re.MULTILINE)
    return "\n".join(match.group(1) for match in pattern.finditer(css))


class JobCardLayoutContractTests(unittest.TestCase):
    def test_job_cards_share_history_card_height(self):
        css = (ROOT / "static/css/style.css").read_text()

        history_block = _css_block(css, ".gi:not(.job-card)")
        job_block = _css_block(css, ".gi.job-card")

        self.assertIn("height: 280px", history_block)
        self.assertIn("height: 280px", job_block)
        self.assertIn("overflow: hidden", job_block)

    def test_job_placeholders_do_not_use_content_height(self):
        css = (ROOT / "static/css/style.css").read_text()

        masonry_img_block = _css_block(css, ".masonry .gi.job-card .gi-img")
        placeholder_block = _css_block(css, ".gi.job-card .gi-img.job-placeholder")
        error_placeholder_block = _css_block(css, ".gi.job-card.error .gi-img.job-placeholder")
        info_block = _css_block(css, ".gi.job-card .gi-info")

        self.assertIn("min-height: 0", masonry_img_block)
        self.assertIn("aspect-ratio: auto", placeholder_block)
        self.assertIn("box-sizing: border-box", placeholder_block)
        self.assertIn("padding: 36px 10px 92px", placeholder_block)
        self.assertIn("padding-bottom: 104px", error_placeholder_block)
        self.assertIn("position: absolute", info_block)
        self.assertIn("bottom: 0", info_block)

    def test_status_text_wraps_long_recovery_failures(self):
        css = (ROOT / "static/css/style.css").read_text()

        base_block = _css_block(css, ".job-status-text")
        error_block = _css_block(css, ".job-status-text.error")
        preparing_block = _css_block(css, ".job-status-text.preparing")
        submitting_block = _css_block(css, ".job-status-text.submitting")

        self.assertIn("white-space: nowrap", base_block)
        self.assertIn("white-space: normal", error_block)
        self.assertIn("overflow-wrap: anywhere", error_block)
        self.assertIn("text-overflow: clip", error_block)
        self.assertIn("white-space: normal", preparing_block)
        self.assertIn("overflow-wrap: anywhere", preparing_block)
        self.assertIn("text-overflow: clip", preparing_block)
        self.assertIn("white-space: normal", submitting_block)
        self.assertIn("overflow-wrap: anywhere", submitting_block)
        self.assertIn("text-overflow: clip", submitting_block)


if __name__ == "__main__":
    unittest.main()
