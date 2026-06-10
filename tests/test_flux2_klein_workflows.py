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

    def test_realistic_lora_t2i_uses_klein_base_and_exposes_strength(self):
        workflow = json.loads((WORKFLOW_DIR / "Flux2-Klein-Realistic.json").read_text())
        config = json.loads((CONFIG_DIR / "Flux2-Klein-Realistic.json").read_text())
        fields = {item["key"]: item for item in config["fields"]}

        self.assertIn("srx_detail", workflow["6"]["inputs"]["text"])
        self.assertEqual(
            workflow["12"]["inputs"]["unet_name"],
            "gguf/Flux-2-Klein-9B-KV-Q4_K_M.gguf",
        )
        self.assertEqual(workflow["89"]["class_type"], "LoraLoaderModelOnly")
        self.assertEqual(workflow["89"]["inputs"]["model"], ["12", 0])
        self.assertEqual(
            workflow["89"]["inputs"]["lora_name"],
            "Flux2 Klein 9B Realistic Detail LoRA.safetensors",
        )
        self.assertEqual(workflow["89"]["inputs"]["strength_model"], 0.8)
        self.assertEqual(workflow["20"]["inputs"]["model"], ["89", 0])
        self.assertEqual(fields["89::strength_model"]["zone"], "advanced")
        self.assertEqual(fields["89::strength_model"]["label"], "Realistic Detail LoRA 强度")
        self.assertEqual(fields["89::lora_name"]["zone"], "hidden")

    def test_realistic_lora_i2i_keeps_reference_chain(self):
        workflow = json.loads((WORKFLOW_DIR / "i2i-Flux2-Klein-Realistic.json").read_text())
        config = json.loads((CONFIG_DIR / "i2i-Flux2-Klein-Realistic.json").read_text())
        fields = {item["key"]: item for item in config["fields"]}

        self.assertIn("srx_detail", workflow["6"]["inputs"]["text"])
        self.assertEqual(workflow["89"]["class_type"], "LoraLoaderModelOnly")
        self.assertEqual(workflow["89"]["inputs"]["model"], ["12", 0])
        self.assertEqual(workflow["20"]["inputs"]["model"], ["89", 0])
        self.assertEqual(workflow["22"]["inputs"]["conditioning"], ["44", 0])
        self.assertEqual(workflow["40"]["class_type"], "LoadImage")
        self.assertEqual(workflow["41"]["class_type"], "FluxKontextImageScale")
        self.assertEqual(workflow["42"]["inputs"]["pixels"], ["41", 0])
        self.assertEqual(workflow["43"]["inputs"]["conditioning"], ["26", 0])
        self.assertEqual(workflow["44"]["inputs"]["latent"], ["42", 0])
        self.assertEqual(fields["40::image"]["type"], "image")
        self.assertEqual(fields["89::strength_model"]["zone"], "advanced")
        self.assertEqual(fields["89::lora_name"]["zone"], "hidden")

    def test_realistic_lora_meta_visible(self):
        meta = json.loads((ROOT / "data/wf_meta.json").read_text())

        t2i_entry = meta["Flux2-Klein-Realistic.json"]
        self.assertEqual(t2i_entry["name"], "Flux2 Klein Realistic")
        self.assertIn("文生图", t2i_entry["tags"])
        self.assertIn("LoRA", t2i_entry["tags"])
        self.assertTrue(t2i_entry["shared"])
        self.assertEqual(t2i_entry["source"], "DGX Spark")

        i2i_entry = meta["i2i-Flux2-Klein-Realistic.json"]
        self.assertEqual(i2i_entry["name"], "Flux2 Klein Realistic 图生图")
        self.assertIn("图生图", i2i_entry["tags"])
        self.assertIn("LoRA", i2i_entry["tags"])
        self.assertTrue(i2i_entry["shared"])
        self.assertEqual(i2i_entry["source"], "DGX Spark")

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
