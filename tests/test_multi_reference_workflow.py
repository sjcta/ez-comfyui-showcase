import copy
import json
import unittest
from pathlib import Path

from modules.multi_reference_workflow import (
    IMAGE_REFERENCE_MODE_FIELD,
    MULTI_REFERENCE_IMAGES_FIELD,
    apply_multi_reference_image_mode_to_workflow,
)
from modules.workflow_validation import validate_api_prompt


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / "data" / "workflows" / "DGX Spark"
CONFIG_DIR = ROOT / "data" / "wf_configs"


def _load_workflow(name: str) -> dict:
    return json.loads((WORKFLOW_DIR / name).read_text(encoding="utf-8"))


def _multi_fields(primary_node: str) -> dict:
    return {
        f"{primary_node}::{IMAGE_REFERENCE_MODE_FIELD}": "multi",
        f"{primary_node}::{MULTI_REFERENCE_IMAGES_FIELD}": json.dumps(["a.png", "b.png", "c.png"]),
    }


class MultiReferenceWorkflowTests(unittest.TestCase):
    def test_qwen_edit_plus_limits_multi_references_to_two_images(self):
        wf = _load_workflow("i2i-Qwen-Edit-v2511.json")
        fields = _multi_fields("41")

        apply_multi_reference_image_mode_to_workflow(wf, fields, "i2i-Qwen-Edit-v2511.json")

        self.assertEqual(wf["41"]["inputs"]["image"], "a.png")
        self.assertEqual(wf["922"]["inputs"]["image"], "b.png")
        self.assertEqual(wf["170:151"]["inputs"]["image2"], ["932", 0])
        self.assertNotIn("image3", wf["170:151"]["inputs"])
        self.assertNotIn("image2", wf["44"]["inputs"])
        self.assertNotIn("923", wf)
        self.assertEqual(json.loads(fields[MULTI_REFERENCE_IMAGES_FIELD]), ["a.png", "b.png"])
        self.assertEqual(validate_api_prompt(wf), [])

    def test_firered_connects_multi_references_to_positive_and_negative_encoders(self):
        wf = _load_workflow("i2i-FireRed-Edit-8step.json")
        fields = _multi_fields("143")

        apply_multi_reference_image_mode_to_workflow(wf, fields, "i2i-FireRed-Edit-8step.json")

        self.assertEqual(wf["143"]["inputs"]["image"], "a.png")
        for node_id in ("117", "118"):
            self.assertEqual(wf[node_id]["inputs"]["image2"], ["932", 0])
            self.assertEqual(wf[node_id]["inputs"]["image3"], ["933", 0])
        self.assertEqual(validate_api_prompt(wf), [])

    def test_qwen_rapid_limits_multi_references_to_two_images(self):
        wf = _load_workflow("i2i-Qwen-Rapid.json")
        fields = _multi_fields("78")

        apply_multi_reference_image_mode_to_workflow(wf, fields, "i2i-Qwen-Rapid.json")

        self.assertEqual(wf["78"]["inputs"]["image"], "a.png")
        self.assertEqual(wf["922"]["class_type"], "LoadImage")
        self.assertEqual(wf["922"]["inputs"]["image"], "b.png")
        self.assertEqual(wf["115:111"]["inputs"]["image2"], ["922", 0])
        self.assertNotIn("image3", wf["115:111"]["inputs"])
        self.assertNotIn("923", wf)
        self.assertNotIn("932", wf)
        self.assertEqual(json.loads(fields[MULTI_REFERENCE_IMAGES_FIELD]), ["a.png", "b.png"])
        self.assertEqual(validate_api_prompt(wf), [])

    def test_flux2_chains_reference_latents_for_multi_reference_mode(self):
        wf = _load_workflow("i2i_flux2_dev_turbo_q4km.json")
        fields = _multi_fields("40")

        apply_multi_reference_image_mode_to_workflow(wf, fields, "i2i_flux2_dev_turbo_q4km.json")

        self.assertEqual(wf["40"]["inputs"]["image"], "a.png")
        self.assertEqual(wf["140"]["inputs"]["image"], "b.png")
        self.assertEqual(wf["145"]["inputs"]["image"], "c.png")
        self.assertEqual(wf["143"]["inputs"]["conditioning"], ["44", 0])
        self.assertEqual(wf["148"]["inputs"]["conditioning"], ["143", 0])
        self.assertEqual(wf["22"]["inputs"]["conditioning"], ["148", 0])
        self.assertEqual(validate_api_prompt(wf), [])

    def test_flux2_removes_stale_third_reference_nodes_when_only_two_images_are_used(self):
        wf = _load_workflow("i2i_flux2_dev_turbo_q4km.json")
        fields = {
            f"40::{IMAGE_REFERENCE_MODE_FIELD}": "multi",
            f"40::{MULTI_REFERENCE_IMAGES_FIELD}": json.dumps(["a.png", "b.png"]),
        }

        apply_multi_reference_image_mode_to_workflow(wf, fields, "i2i_flux2_dev_turbo_q4km.json")

        self.assertEqual(wf["40"]["inputs"]["image"], "a.png")
        self.assertEqual(wf["140"]["inputs"]["image"], "b.png")
        self.assertEqual(wf["22"]["inputs"]["conditioning"], ["143", 0])
        for node_id in ("145", "146", "147", "148"):
            self.assertNotIn(node_id, wf)
        self.assertEqual(validate_api_prompt(wf), [])

    def test_single_reference_mode_removes_extra_qwen_image_links(self):
        wf = _load_workflow("i2i-Qwen-Edit-v2511.json")
        wf = copy.deepcopy(wf)
        wf["170:151"]["inputs"]["image2"] = ["932", 0]
        fields = {f"41::{IMAGE_REFERENCE_MODE_FIELD}": "single"}

        apply_multi_reference_image_mode_to_workflow(wf, fields, "i2i-Qwen-Edit-v2511.json")

        self.assertNotIn("image2", wf["170:151"]["inputs"])
        for node_id in ("922", "923", "932", "933"):
            self.assertNotIn(node_id, wf)
        self.assertEqual(validate_api_prompt(wf), [])

    def test_multi_reference_mode_requires_at_least_two_images(self):
        wf = _load_workflow("i2i_flux2_dev_turbo_q4km.json")
        fields = {
            f"40::{IMAGE_REFERENCE_MODE_FIELD}": "multi",
            f"40::{MULTI_REFERENCE_IMAGES_FIELD}": json.dumps(["only-one.png"]),
        }

        with self.assertRaises(ValueError):
            apply_multi_reference_image_mode_to_workflow(wf, fields, "i2i_flux2_dev_turbo_q4km.json")

    def test_supported_configs_expose_single_multi_switch_fields(self):
        expected = {
            "i2i-Qwen-Edit-v2511.json": ("41", 2),
            "i2i-FireRed-Edit-8step.json": ("143", 3),
            "i2i_flux2_dev_turbo_q4km.json": ("40", 3),
            "i2i-Qwen-Rapid.json": ("78", 2),
            "i2i-Qwen-Rapid-Q2.json": ("78", 2),
            "i2i-Qwen-Rapid-seedVR2-4k.json": ("78", 2),
        }
        for name, (primary, max_refs) in expected.items():
            with self.subTest(name=name):
                config = json.loads((CONFIG_DIR / name).read_text(encoding="utf-8"))
                fields = config.get("fields", [])
                keys = [item.get("key") for item in fields]
                self.assertIn(f"{primary}::{IMAGE_REFERENCE_MODE_FIELD}", keys)
                self.assertIn(f"{primary}::{MULTI_REFERENCE_IMAGES_FIELD}", keys)
                multi_field = next(item for item in fields if item.get("key") == f"{primary}::{MULTI_REFERENCE_IMAGES_FIELD}")
                self.assertEqual(multi_field.get("max"), max_refs)
