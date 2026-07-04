import copy
import json
import unittest
from pathlib import Path

from modules.bernini_workflow import (
    FPS_FIELD,
    FRAMES_FIELD,
    LEGACY_MODE_FIELD,
    LEGACY_REFS_FIELD,
    SAVE_VIDEO_NODE_ID,
    VIDEO_FIELD,
    apply_bernini_mixed_mode_to_workflow,
    normalize_bernini_field_values,
)
from modules.workflow_validation import validate_api_prompt


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / "data" / "workflows" / "DGX Spark" / "t2i_bernini_fp8.json"
CONFIG_PATH = ROOT / "data" / "wf_configs" / "t2i_bernini_fp8.json"


class BerniniMixedWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))

    def _graph(self, fields):
        wf = copy.deepcopy(self.workflow)
        fields = normalize_bernini_field_values(wf, dict(fields), "t2i_bernini_fp8.json")
        for key, value in fields.items():
            if "::" not in key:
                continue
            node_id, field = key.split("::", 1)
            if field.startswith("__"):
                continue
            if node_id in wf:
                wf[node_id].setdefault("inputs", {})[field] = value
        apply_bernini_mixed_mode_to_workflow(wf, fields, "t2i_bernini_fp8.json")
        self.assertEqual(validate_api_prompt(wf), [])
        return wf, fields

    def test_config_exposes_q4_mixed_mode_controls(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        keys = [item["key"] for item in config["fields"]]
        self.assertIn(LEGACY_MODE_FIELD, keys)
        self.assertIn(LEGACY_REFS_FIELD, keys)
        self.assertIn(FRAMES_FIELD.replace("1::", "50::"), keys)
        self.assertIn(FPS_FIELD.replace("1::", "50::"), keys)
        self.assertIn(VIDEO_FIELD, keys)

    def test_base_workflow_uses_q4_gguf_high_low(self):
        self.assertEqual(self.workflow["5"]["class_type"], "UnetLoaderGGUF")
        self.assertEqual(self.workflow["12"]["class_type"], "UnetLoaderGGUF")
        self.assertEqual(self.workflow["5"]["inputs"]["unet_name"], "gguf/bernini_r_high_noise_14B-Q4_K_M.gguf")
        self.assertEqual(self.workflow["12"]["inputs"]["unet_name"], "gguf/bernini_r_low_noise_14B-Q4_K_M.gguf")

    def test_t2i_uses_no_reference_inputs_and_saves_image(self):
        wf, fields = self._graph({LEGACY_MODE_FIELD: "t2i", "50::__bernini_frames": 81})
        inputs = wf["50"]["inputs"]
        self.assertEqual(fields["50::length"], 1)
        self.assertNotIn("source_video", inputs)
        self.assertNotIn("reference_images", inputs)
        self.assertIn("100", wf)
        self.assertNotIn(SAVE_VIDEO_NODE_ID, wf)

    def test_i2i_connects_source_image_and_saves_image(self):
        wf, fields = self._graph({LEGACY_MODE_FIELD: "i2i", LEGACY_REFS_FIELD: '["demo/source.png"]'})
        inputs = wf["50"]["inputs"]
        self.assertEqual(fields["50::length"], 1)
        self.assertEqual(inputs["source_video"], ["910", 0])
        self.assertEqual(wf["910"]["inputs"]["image"], "demo/source.png")
        self.assertIn("100", wf)
        self.assertNotIn(SAVE_VIDEO_NODE_ID, wf)

    def test_t2v_saves_video_without_reference_media(self):
        wf, fields = self._graph({LEGACY_MODE_FIELD: "t2v", "50::__bernini_frames": 80})
        inputs = wf["50"]["inputs"]
        self.assertEqual(fields["50::length"], 81)
        self.assertNotIn("source_video", inputs)
        self.assertNotIn("reference_images", inputs)
        self.assertNotIn("900", wf)
        self.assertNotIn("100", wf)
        self.assertEqual(wf[SAVE_VIDEO_NODE_ID]["class_type"], "VHS_VideoCombine")

    def test_v2v_connects_vhs_source_video(self):
        wf, fields = self._graph({LEGACY_MODE_FIELD: "v2v", VIDEO_FIELD: "demo/source.mp4", "50::__bernini_frames": 17})
        self.assertEqual(fields["50::length"], 17)
        self.assertEqual(wf["50"]["inputs"]["source_video"], ["900", 0])
        self.assertEqual(wf["900"]["class_type"], "VHS_LoadVideo")
        self.assertEqual(wf["900"]["inputs"]["video"], "demo/source.mp4")
        self.assertEqual(wf["900"]["inputs"]["frame_load_cap"], 17)
        self.assertEqual(wf[SAVE_VIDEO_NODE_ID]["class_type"], "VHS_VideoCombine")

    def test_i2v_connects_one_reference_image_and_saves_video(self):
        wf, fields = self._graph(
            {LEGACY_MODE_FIELD: "i2v", LEGACY_REFS_FIELD: '["demo/ref.png","demo/ignored.png"]', "50::__bernini_frames": 80}
        )
        inputs = wf["50"]["inputs"]
        self.assertEqual(fields["50::length"], 81)
        self.assertNotIn("source_video", inputs)
        self.assertEqual(inputs["reference_images"], {"reference_image_0": ["911", 0]})
        self.assertEqual(wf["911"]["inputs"]["image"], "demo/ref.png")
        self.assertNotIn("912", wf)
        self.assertEqual(wf[SAVE_VIDEO_NODE_ID]["class_type"], "VHS_VideoCombine")

    def test_r2v_keeps_multiple_reference_images(self):
        wf, _fields = self._graph({LEGACY_MODE_FIELD: "r2v", LEGACY_REFS_FIELD: '["a.png","b.png","c.png"]'})
        refs = wf["50"]["inputs"]["reference_images"]
        self.assertEqual(refs["reference_image_0"], ["911", 0])
        self.assertEqual(refs["reference_image_1"], ["912", 0])
        self.assertEqual(refs["reference_image_2"], ["913", 0])
        self.assertEqual(wf["912"]["inputs"]["image"], "b.png")
        self.assertNotIn("100", wf)
        self.assertIn(SAVE_VIDEO_NODE_ID, wf)

    def test_rv2v_connects_video_and_reference_images(self):
        wf, _fields = self._graph(
            {
                LEGACY_MODE_FIELD: "rv2v",
                LEGACY_REFS_FIELD: '["style.png","character.png"]',
                VIDEO_FIELD: "demo/source.mp4",
            }
        )
        self.assertEqual(wf["50"]["inputs"]["source_video"], ["900", 0])
        self.assertEqual(wf["50"]["inputs"]["reference_images"]["reference_image_0"], ["911", 0])
        self.assertEqual(wf["50"]["inputs"]["reference_images"]["reference_image_1"], ["912", 0])
        self.assertEqual(wf[SAVE_VIDEO_NODE_ID]["class_type"], "VHS_VideoCombine")

    def test_reference_modes_require_an_image(self):
        wf = copy.deepcopy(self.workflow)
        fields = normalize_bernini_field_values(wf, {LEGACY_MODE_FIELD: "r2v"}, "t2i_bernini_fp8.json")
        with self.assertRaisesRegex(RuntimeError, "参考图"):
            apply_bernini_mixed_mode_to_workflow(wf, fields, "t2i_bernini_fp8.json")

    def test_source_video_modes_require_video(self):
        wf = copy.deepcopy(self.workflow)
        fields = normalize_bernini_field_values(wf, {LEGACY_MODE_FIELD: "v2v"}, "t2i_bernini_fp8.json")
        with self.assertRaisesRegex(RuntimeError, "源视频"):
            apply_bernini_mixed_mode_to_workflow(wf, fields, "t2i_bernini_fp8.json")

    def test_frontend_uses_descriptive_mode_dropdown(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/style.css").read_text(encoding="utf-8")

        self.assertIn("class=\"bernini-mode-select\"", generate_js)
        self.assertIn("data-type=\"bernini_mode\"", generate_js)
        self.assertIn("T2I', label: '文生图', desc: '用提示词生成图片'", generate_js)
        self.assertIn("RV2V', label: '参考图视频编辑'", generate_js)
        self.assertNotIn("bernini-mode-btn", generate_js)
        self.assertIn(".bernini-mode-select", css)
        self.assertIn(".bernini-mode-summary", css)


if __name__ == "__main__":
    unittest.main()
