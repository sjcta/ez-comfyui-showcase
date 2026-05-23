import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / "data/workflows/DGX Spark"
CONFIG_DIR = ROOT / "data/wf_configs"


class Flux2KleinWorkflowsTest(unittest.TestCase):
    def test_text_to_image_uses_official_distilled_cfg_chain(self):
        workflow = json.loads((WORKFLOW_DIR / "t2i_flux2_klein.json").read_text())
        config = json.loads((CONFIG_DIR / "t2i_flux2_klein.json").read_text())
        fields = {item["key"]: item for item in config["fields"]}

        self.assertEqual(workflow["22"]["class_type"], "CFGGuider")
        self.assertEqual(workflow["22"]["inputs"]["positive"], ["6", 0])
        self.assertEqual(workflow["22"]["inputs"]["negative"], ["26", 0])
        self.assertEqual(workflow["22"]["inputs"]["cfg"], 1.0)
        self.assertEqual(workflow["26"]["class_type"], "CLIPTextEncode")
        self.assertEqual(workflow["26"]["inputs"]["text"], "")
        self.assertEqual(workflow["48"]["inputs"]["steps"], 4)
        self.assertEqual(fields["22::cfg"]["label"], "CFG")

    def test_image_to_image_uses_official_distilled_reference_cfg_chain(self):
        workflow = json.loads((WORKFLOW_DIR / "i2i_flux2_klein.json").read_text())
        config = json.loads((CONFIG_DIR / "i2i_flux2_klein.json").read_text())
        fields = {item["key"]: item for item in config["fields"]}

        self.assertEqual(workflow["22"]["class_type"], "CFGGuider")
        self.assertEqual(workflow["22"]["inputs"]["positive"], ["43", 0])
        self.assertEqual(workflow["22"]["inputs"]["negative"], ["44", 0])
        self.assertEqual(workflow["22"]["inputs"]["cfg"], 1.0)
        self.assertEqual(workflow["26"]["class_type"], "ConditioningZeroOut")
        self.assertEqual(workflow["41"]["class_type"], "ImageScaleToTotalPixels")
        self.assertEqual(workflow["41"]["inputs"]["megapixels"], 1.0)
        self.assertEqual(workflow["43"]["class_type"], "ReferenceLatent")
        self.assertEqual(workflow["43"]["inputs"]["conditioning"], ["6", 0])
        self.assertEqual(workflow["43"]["inputs"]["latent"], ["42", 0])
        self.assertEqual(workflow["44"]["class_type"], "ReferenceLatent")
        self.assertEqual(workflow["44"]["inputs"]["conditioning"], ["26", 0])
        self.assertEqual(workflow["44"]["inputs"]["latent"], ["42", 0])
        self.assertEqual(workflow["48"]["inputs"]["steps"], 4)
        self.assertEqual(fields["22::cfg"]["label"], "CFG")
        self.assertNotIn("43::reference_latents_method", fields)


if __name__ == "__main__":
    unittest.main()
