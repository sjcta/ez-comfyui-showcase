import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / "data/workflows/DGX Spark"
CONFIG_DIR = ROOT / "data/wf_configs"
META = ROOT / "data/wf_meta.json"


class Krea2WorkflowsTest(unittest.TestCase):
    def test_turbo_mxfp8_uses_native_krea2_contract(self):
        workflow = json.loads((WORKFLOW_DIR / "t2i_krea2_turbo_mxfp8.json").read_text())
        config = json.loads((CONFIG_DIR / "t2i_krea2_turbo_mxfp8.json").read_text())
        fields = {item["key"]: item for item in config["fields"]}

        self.assertEqual(workflow["1"]["inputs"]["unet_name"], "krea2_turbo_mxfp8.safetensors")
        self.assertEqual(workflow["13"]["inputs"]["clip_name"], "qwen3vl_4b_fp8_scaled.safetensors")
        self.assertEqual(workflow["13"]["inputs"]["type"], "krea2")
        self.assertEqual(workflow["4"]["inputs"]["vae_name"], "qwen_image_vae.safetensors")
        self.assertEqual(workflow["8"]["class_type"], "CLIPTextEncode")
        self.assertEqual(workflow["8"]["inputs"]["text"], "")
        self.assertEqual(workflow["2"]["inputs"]["steps"], 8)
        self.assertEqual(workflow["2"]["inputs"]["cfg"], 1)
        self.assertEqual(workflow["2"]["inputs"]["sampler_name"], "euler")
        self.assertEqual(workflow["2"]["inputs"]["scheduler"], "simple")
        self.assertFalse(fields["2::cfg"]["visible"])
        self.assertFalse(fields["8::text"]["visible"])
        self.assertIn("cfg=1, not cfg=0", config["notes"])
        self.assertEqual(fields["10::width"]["role"], "width")
        self.assertEqual(fields["10::height"]["role"], "height")
        self.assertEqual(fields["10::width"]["max"], 2048)
        self.assertEqual(config["required_models"], [
            "diffusion_models/krea2_turbo_mxfp8.safetensors",
            "text_encoders/qwen3vl_4b_fp8_scaled.safetensors",
            "vae/qwen_image_vae.safetensors",
        ])

    def test_base_fallback_is_scaled_fp8_when_mxfp8_is_absent(self):
        workflow = json.loads((WORKFLOW_DIR / "t2i_krea2_base_fp8_scaled.json").read_text())
        config = json.loads((CONFIG_DIR / "t2i_krea2_base_fp8_scaled.json").read_text())
        fields = {item["key"]: item for item in config["fields"]}

        self.assertEqual(workflow["1"]["inputs"]["unet_name"], "krea2_raw_fp8_scaled.safetensors")
        self.assertEqual(workflow["13"]["inputs"]["clip_name"], "qwen3vl_4b_fp8_scaled.safetensors")
        self.assertEqual(workflow["13"]["inputs"]["type"], "krea2")
        self.assertEqual(workflow["4"]["inputs"]["vae_name"], "qwen_image_vae.safetensors")
        self.assertEqual(workflow["8"]["class_type"], "CLIPTextEncode")
        self.assertEqual(workflow["8"]["inputs"]["text"], "")
        self.assertEqual(workflow["2"]["inputs"]["steps"], 52)
        self.assertEqual(workflow["2"]["inputs"]["cfg"], 3.5)
        self.assertEqual(workflow["2"]["inputs"]["sampler_name"], "euler")
        self.assertEqual(fields["10::width"]["max"], 1024)
        self.assertIn("no krea2_raw_mxfp8.safetensors", config["notes"])
        self.assertEqual(config["required_models"], [
            "diffusion_models/krea2_raw_fp8_scaled.safetensors",
            "text_encoders/qwen3vl_4b_fp8_scaled.safetensors",
            "vae/qwen_image_vae.safetensors",
        ])

    def test_meta_entries_are_registered_as_test_workflows(self):
        meta = json.loads(META.read_text())
        base = meta["t2i_krea2_base_fp8_scaled.json"]
        turbo = meta["t2i_krea2_turbo_mxfp8.json"]

        self.assertFalse(base["shared"])
        self.assertFalse(turbo["shared"])
        self.assertIn("Krea2", base["tags"])
        self.assertIn("MXFP8", turbo["tags"])
        self.assertIn("FP8 Scaled", base["tags"])
        self.assertEqual(base["sort_order"], 47)
        self.assertEqual(turbo["sort_order"], 48)


if __name__ == "__main__":
    unittest.main()
