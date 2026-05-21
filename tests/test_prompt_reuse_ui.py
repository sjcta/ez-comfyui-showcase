from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PromptReuseUiContractTests(unittest.TestCase):
    def test_reused_prompt_updates_prompt_action_state(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()

        self.assertIn("function _setPromptInputValue", generate_js)
        self.assertIn("pi.dispatchEvent(new Event('input', { bubbles: true }))", generate_js)
        self.assertIn("CW.syncClearPromptButton", generate_js)
        self.assertIn("_setPromptInputValue(h.prompt)", generate_js)
        self.assertIn("_setPromptInputValue(snap.prompt)", generate_js)
        self.assertIn("_setPromptInputValue(j.prompt_preview)", generate_js)
        self.assertNotIn("if (pi) pi.value = h.prompt", generate_js)
        self.assertNotIn("if (pi) pi.value = j.prompt_preview", generate_js)


if __name__ == "__main__":
    unittest.main()
