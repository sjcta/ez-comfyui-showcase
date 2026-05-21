from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SensitivePreviewKeywordTests(unittest.TestCase):
    def test_bare_exposed_word_does_not_trigger_preview_blur(self):
        for rel_path in ("static/js/modules/history.js", "static/js/modules/card_manager.js", "static/js/modules/workflows.js"):
            source = (ROOT / rel_path).read_text()

            self.assertRegex(source, r"function _isSensitive(?:Workflow)?Preview")
            self.assertNotIn("裸露", source)
            self.assertIn("裸体", source)
            self.assertIn("nsfw", source)
            self.assertIn(r"\bnude\b", source)


if __name__ == "__main__":
    unittest.main()
