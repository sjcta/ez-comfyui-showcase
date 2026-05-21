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
        self.assertIn("function _hasRestorableSeedFieldValues", generate_js)
        self.assertIn("if (h.seed && !_hasRestorableSeedFieldValues(h.field_values || {}))", generate_js)
        self.assertIn("if (j.seed && !_hasRestorableSeedFieldValues(j.fields || {}))", generate_js)
        self.assertIn("_numberAttr('max', f.max)", generate_js)
        self.assertNotIn("_setSeedRandomEnabled(false);\n      return;", generate_js)
        self.assertIn("body: JSON.stringify(requestBody)", generate_js)
        self.assertIn(".seed-group .btn-dice.is-active", css)

    def test_generate_uses_cached_workflow_fields_and_blocks_missing_prompt_field(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()
        workflows_js = (ROOT / "static/js/modules/workflows.js").read_text()

        self.assertIn("function _getSubmitFieldsMeta", generate_js)
        self.assertIn("function _isPromptSubmitField", generate_js)
        self.assertIn("if (_hasCurrentFieldCache()) return A._wfFieldMeta", generate_js)
        self.assertIn("promptFieldCount += 1", generate_js)
        self.assertIn("未找到可提交的提示词字段", generate_js)
        self.assertIn("window.__APP__._wfFieldWorkflow = name", workflows_js)
        self.assertIn("zone: f.zone,", workflows_js)
        self.assertNotIn("zone: f.zone || 'advanced'", generate_js)
        self.assertNotIn("zone: f.zone || 'advanced'", workflows_js)

    def test_generate_waits_for_pending_reference_image_upload(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()

        self.assertIn("var _refImageUploadPromise = null", generate_js)
        self.assertIn("await _waitForRefImageUpload()", generate_js)
        self.assertIn("valueInput.value = ''", generate_js)
        self.assertIn("data-uploading", generate_js)
        self.assertIn("参考图仍在上传", generate_js)

    def test_image_file_inputs_accept_extended_formats(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()

        self.assertIn("image/*,.tif,.tiff,.gif,.jfif,.jpe,.avif,.heic,.heif", generate_js)

    def test_generate_does_not_send_manual_instance_target(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()

        self.assertIn("preferred_instance: ''", generate_js)
        self.assertIn("preferred_node_id: ''", generate_js)
        self.assertNotIn("A.manualTargetInstance ? (A.currentTargetInstance || '') : ''", generate_js)


if __name__ == "__main__":
    unittest.main()
