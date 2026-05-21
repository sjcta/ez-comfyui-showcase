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

    def test_prompt_optimization_variant_tabs_live_in_prompt_title_row(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn("promptGroup.querySelector('.prompt-label-row')", generate_js)
        self.assertIn("labelRow.appendChild(panel)", generate_js)
        self.assertNotIn("actions.appendChild(panel)", generate_js)
        self.assertIn(".prompt-label-row label", css)
        self.assertIn("text-overflow: ellipsis", css)
        self.assertIn("margin-left: auto", css)
        self.assertIn("gap: 0", css)
        self.assertIn("border-radius: 999px", css)

    def test_seed_random_button_mode_governs_generate_payload_and_reuse(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn("function _isSeedRandomEnabled", generate_js)
        self.assertIn("function _getManualSeedValue", generate_js)
        self.assertIn("if (!_isSeedRandomEnabled()) requestBody.seed = manualSeed", generate_js)
        self.assertIn("data-seed-random", generate_js)
        self.assertIn("aria-pressed=\"true\"", generate_js)
        self.assertIn("title=\"随机种子\"", generate_js)
        self.assertIn("oninput=\"CW.setSeedRandomEnabled(false)\"", generate_js)
        self.assertIn("if (seedInput) seedInput.value = h.seed;\n      _setSeedRandomEnabled(true);", generate_js)
        self.assertIn("if (seedEl) seedEl.value = j.seed;\n      _setSeedRandomEnabled(true);", generate_js)
        self.assertNotIn("_setSeedRandomEnabled(false);\n      return;", generate_js)
        self.assertIn("body: JSON.stringify(requestBody)", generate_js)
        self.assertIn(".seed-group .btn-dice.is-active", css)


if __name__ == "__main__":
    unittest.main()
