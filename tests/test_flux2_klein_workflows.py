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

        self.assertEqual(workflow["22"]["class_type"], "BasicGuider")
        self.assertEqual(workflow["22"]["inputs"]["model"], ["20", 0])
        self.assertEqual(workflow["22"]["inputs"]["conditioning"], ["26", 0])
        self.assertEqual(workflow["26"]["class_type"], "FluxGuidance")
        self.assertEqual(workflow["26"]["inputs"]["conditioning"], ["6", 0])
        self.assertEqual(workflow["26"]["inputs"]["guidance"], 4.0)
        self.assertEqual(workflow["48"]["inputs"]["steps"], 4)
        self.assertEqual(fields["26::guidance"]["label"], "Flux 引导")
        self.assertNotIn("22::cfg", fields)

    def test_image_to_image_uses_official_distilled_reference_cfg_chain(self):
        workflow = json.loads((WORKFLOW_DIR / "i2i_flux2_klein.json").read_text())
        config = json.loads((CONFIG_DIR / "i2i_flux2_klein.json").read_text())
        fields = {item["key"]: item for item in config["fields"]}

        self.assertEqual(workflow["22"]["class_type"], "BasicGuider")
        self.assertEqual(workflow["22"]["inputs"]["model"], ["20", 0])
        self.assertEqual(workflow["22"]["inputs"]["conditioning"], ["44", 0])
        self.assertEqual(workflow["26"]["class_type"], "FluxGuidance")
        self.assertEqual(workflow["26"]["inputs"]["conditioning"], ["6", 0])
        self.assertEqual(workflow["26"]["inputs"]["guidance"], 4.0)
        self.assertEqual(workflow["41"]["class_type"], "FluxKontextImageScale")
        self.assertEqual(workflow["41"]["inputs"]["image"], ["40", 0])
        self.assertEqual(workflow["43"]["class_type"], "FluxKontextMultiReferenceLatentMethod")
        self.assertEqual(workflow["43"]["inputs"]["conditioning"], ["26", 0])
        self.assertEqual(workflow["43"]["inputs"]["reference_latents_method"], "index")
        self.assertEqual(workflow["44"]["class_type"], "ReferenceLatent")
        self.assertEqual(workflow["44"]["inputs"]["conditioning"], ["43", 0])
        self.assertEqual(workflow["44"]["inputs"]["latent"], ["42", 0])
        self.assertEqual(workflow["48"]["inputs"]["steps"], 4)
        self.assertEqual(fields["26::guidance"]["label"], "Flux 引导")
        self.assertNotIn("22::cfg", fields)
        self.assertNotIn("43::reference_latents_method", fields)


if __name__ == "__main__":
    unittest.main()
