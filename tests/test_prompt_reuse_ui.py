from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PromptReuseUiContractTests(unittest.TestCase):
    def test_reused_prompt_updates_prompt_action_state(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()

        self.assertIn("function _setPromptInputValue", generate_js)
        self.assertIn("pi.dispatchEvent(new Event('input', { bubbles: true }))", generate_js)
        self.assertIn("CW.syncClearPromptButton", generate_js)
        self.assertIn("function _promptFromReusableFields", generate_js)
        self.assertIn("var reusedPrompt = _promptFromReusableFields(h.field_values || {}, reuseFieldsMeta)", generate_js)
        self.assertIn("_setPromptInputValue(reusedPrompt || h.prompt)", generate_js)
        self.assertIn("_setPromptInputValue(snap.prompt)", generate_js)
        self.assertIn("_setPromptInputValue(j.prompt_preview)", generate_js)
        self.assertNotIn("_setPromptInputValue(h.prompt)", generate_js)
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

    def test_generate_syncs_flux2_scheduler_dimensions(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()

        self.assertIn("function _isFlux2SchedulerSizeField", generate_js)
        self.assertIn("_isFlux2SchedulerSizeField(f, 'width')", generate_js)
        self.assertIn("_isFlux2SchedulerSizeField(f, 'height')", generate_js)

    def test_flux2_ratio_presets_are_limited_by_total_pixels(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()

        self.assertIn("var FLUX2_MAX_PIXELS = 2048 * 2048", generate_js)
        self.assertIn("class_type === 'Flux2Scheduler'", generate_js)
        self.assertIn("maxPixels: FLUX2_MAX_PIXELS", generate_js)
        self.assertIn("[2160, 3840, '9:16'", generate_js)
        self.assertIn("_applyCurrentSizeLimit()", generate_js)
        self.assertIn("width * height > limits.maxPixels", generate_js)

    def test_model_family_ratio_presets_use_recommended_dimensions(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()

        self.assertIn("var QWEN_IMAGE_RATIO_PRESETS", generate_js)
        self.assertIn("[1328, 1328, '1:1'", generate_js)
        self.assertIn("[1664, 928, '16:9'", generate_js)
        self.assertIn("[928, 1664, '9:16'", generate_js)
        self.assertIn("var Z_IMAGE_RATIO_PRESETS", generate_js)
        self.assertIn("[1024, 1024, '1:1'", generate_js)
        self.assertIn("[1280, 720, '16:9'", generate_js)
        self.assertIn("[720, 1280, '9:16'", generate_js)
        self.assertIn("_ratioPresetsForLimits(limits)", generate_js)

    def test_generate_waits_for_pending_reference_image_upload(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()

        self.assertIn("var _refImageUploadPromise = null", generate_js)
        self.assertIn("await _waitForRefImageUpload()", generate_js)
        self.assertIn("valueInput.value = ''", generate_js)
        self.assertIn("data-uploading", generate_js)
        self.assertIn("参考图仍在上传", generate_js)

    def test_video_mode_controls_reference_image_requirement(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn("function _isVideoI2VMode", generate_js)
        self.assertIn("function setVideoMode", generate_js)
        self.assertIn("function _isLatentDimensionField", generate_js)
        self.assertIn("cls.indexOf('LatentVideo') >= 0", generate_js)
        self.assertIn("name: 'ltx-video'", generate_js)
        self.assertIn("minWidth: 256", generate_js)
        self.assertIn("minHeight: 192", generate_js)
        self.assertIn("data-type=\"video_mode\"", generate_js)
        self.assertIn("文生视频", generate_js)
        self.assertIn("图生视频", generate_js)
        self.assertIn("图生视频需要先上传参考图", generate_js)
        self.assertIn("$$('#quickFormFields [data-key]')", generate_js)
        self.assertIn("class=\"fg quick-number-fg\"", generate_js)
        self.assertIn("_numberAttr('step', f.step || 1)", generate_js)
        self.assertIn("window.CW.setVideoMode = setVideoMode", generate_js)
        self.assertIn(".video-mode-control", css)
        self.assertIn(".ref-image-section.is-required label::after", css)

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
