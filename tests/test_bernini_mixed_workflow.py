import copy
import json
import unittest
from pathlib import Path

from modules.bernini_workflow import (
    FPS_FIELD,
    FRAMES_FIELD,
    MODE_FIELD,
    REFS_FIELD,
    SAVE_VIDEO_NODE_ID,
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
            if node_id in wf:
                wf[node_id].setdefault("inputs", {})[field] = value
        apply_bernini_mixed_mode_to_workflow(wf, fields, "t2i_bernini_fp8.json")
        self.assertEqual(validate_api_prompt(wf), [])
        return wf, fields

    def test_config_exposes_mixed_mode_controls(self):
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        keys = [item["key"] for item in config["fields"]]
        self.assertIn(MODE_FIELD, keys)
        self.assertIn(REFS_FIELD, keys)
        self.assertIn(FRAMES_FIELD, keys)
        self.assertIn(FPS_FIELD, keys)

    def test_t2i_uses_no_reference_inputs_and_saves_image(self):
        wf, fields = self._graph({MODE_FIELD: "t2i", FRAMES_FIELD: 81})
        inputs = wf["50"]["inputs"]
        self.assertEqual(fields["50::length"], 1)
        self.assertNotIn("source_video", inputs)
        self.assertNotIn("reference_images", inputs)
        self.assertIn("100", wf)
        self.assertNotIn(SAVE_VIDEO_NODE_ID, wf)

    def test_i2i_connects_source_image_and_saves_image(self):
        wf, fields = self._graph({MODE_FIELD: "i2i", REFS_FIELD: '["demo/source.png"]', FRAMES_FIELD: 81})
        inputs = wf["50"]["inputs"]
        self.assertEqual(fields["50::length"], 1)
        self.assertEqual(inputs["source_video"], ["910", 0])
        self.assertEqual(wf["910"]["inputs"]["image"], "demo/source.png")
        self.assertIn("100", wf)
        self.assertNotIn(SAVE_VIDEO_NODE_ID, wf)

    def test_i2v_connects_one_reference_image_and_saves_video(self):
        wf, fields = self._graph({MODE_FIELD: "i2v", REFS_FIELD: '["demo/ref.png","demo/ignored.png"]', FRAMES_FIELD: 80})
        inputs = wf["50"]["inputs"]
        self.assertEqual(fields["50::length"], 81)
        self.assertNotIn("source_video", inputs)
        self.assertEqual(inputs["reference_images"], {"reference_image_0": ["911", 0]})
        self.assertEqual(wf["911"]["inputs"]["image"], "demo/ref.png")
        self.assertNotIn("100", wf)
        self.assertEqual(wf[SAVE_VIDEO_NODE_ID]["class_type"], "VHS_VideoCombine")
        self.assertEqual(wf[SAVE_VIDEO_NODE_ID]["inputs"]["frame_rate"], 16)

    def test_r2v_keeps_multiple_reference_images(self):
        wf, _fields = self._graph({MODE_FIELD: "r2v", REFS_FIELD: '["a.png","b.png","c.png"]'})
        refs = wf["50"]["inputs"]["reference_images"]
        self.assertEqual(refs["reference_image_0"], ["911", 0])
        self.assertEqual(refs["reference_image_1"], ["912", 0])
        self.assertEqual(refs["reference_image_2"], ["913", 0])
        self.assertEqual(wf["912"]["inputs"]["image"], "b.png")
        self.assertNotIn("100", wf)
        self.assertIn(SAVE_VIDEO_NODE_ID, wf)

    def test_reference_modes_require_an_image(self):
        wf = copy.deepcopy(self.workflow)
        fields = normalize_bernini_field_values(wf, {MODE_FIELD: "i2v"}, "t2i_bernini_fp8.json")
        with self.assertRaisesRegex(RuntimeError, "参考图"):
            apply_bernini_mixed_mode_to_workflow(wf, fields, "t2i_bernini_fp8.json")


if __name__ == "__main__":
    unittest.main()
