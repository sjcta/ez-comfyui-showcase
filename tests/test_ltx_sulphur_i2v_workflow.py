import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "data/workflows/DGX Spark/i2v_ltx23_sulphur.json"
FAST_WORKFLOW = ROOT / "data/workflows/DGX Spark/i2v_ltx23_sulphur_fp8.json"
CONFIG = ROOT / "data/wf_configs/i2v_ltx23_sulphur.json"
FAST_CONFIG = ROOT / "data/wf_configs/i2v_ltx23_sulphur_fp8.json"
META = ROOT / "data/wf_meta.json"
SULPHUR_DEV_BF16 = "ltx/sulphur_dev_bf16.safetensors"
SULPHUR_DEV_FP8 = "ltx/sulphur_dev_fp8mixed.safetensors"


class LtxSulphurI2VWorkflowTests(unittest.TestCase):
    def test_high_res_reference_injection_is_not_overconstrained(self):
        workflow = json.loads(WORKFLOW.read_text())

        self.assertEqual(workflow["320:288"]["class_type"], "LTXVImgToVideoInplace")
        self.assertEqual(workflow["320:288"]["inputs"]["strength"], 1)
        self.assertEqual(workflow["320:296"]["inputs"]["strength"], 0.7)

    def test_uses_sulphur_bf16_dev_model_for_video_and_audio(self):
        workflow = json.loads(WORKFLOW.read_text())

        self.assertEqual(workflow["320:279"]["inputs"]["ckpt_name"], SULPHUR_DEV_BF16)
        self.assertEqual(workflow["320:316"]["inputs"]["ckpt_name"], SULPHUR_DEV_BF16)
        self.assertEqual(workflow["320:317"]["inputs"]["ckpt_name"], SULPHUR_DEV_BF16)

    def test_fast_variant_uses_sulphur_fp8_model_for_video_and_audio(self):
        workflow = json.loads(FAST_WORKFLOW.read_text())

        self.assertEqual(workflow["320:279"]["inputs"]["ckpt_name"], SULPHUR_DEV_FP8)
        self.assertEqual(workflow["320:316"]["inputs"]["ckpt_name"], SULPHUR_DEV_FP8)
        self.assertEqual(workflow["320:317"]["inputs"]["ckpt_name"], SULPHUR_DEV_FP8)
        self.assertEqual(workflow["75"]["inputs"]["filename_prefix"], "video/LTX_2.3_sulphur_fp8_i2v")

    def test_default_negative_prompt_suppresses_audio_rumble(self):
        workflow = json.loads(WORKFLOW.read_text())
        negative = workflow["320:313"]["inputs"]["text"]

        self.assertIn("low frequency hum", negative)
        self.assertIn("sub-bass rumble", negative)
        self.assertIn("noisy room tone", negative)

    def test_sulphur_variants_use_single_tile_ltx_decode_for_speed(self):
        for path in (WORKFLOW, FAST_WORKFLOW):
            with self.subTest(path=path.name):
                workflow = json.loads(path.read_text())
                decode = workflow["320:315"]

                self.assertEqual(decode["class_type"], "LTXVTiledVAEDecode")
                self.assertEqual(decode["inputs"]["latents"], ["320:309", 0])
                self.assertEqual(decode["inputs"]["vae"], ["320:316", 2])
                self.assertEqual(decode["inputs"]["horizontal_tiles"], 1)
                self.assertEqual(decode["inputs"]["vertical_tiles"], 1)
                self.assertEqual(decode["inputs"]["overlap"], 1)
                self.assertTrue(decode["inputs"]["last_frame_fix"])

    def test_negative_prompt_field_is_labeled_explicitly(self):
        config = json.loads(CONFIG.read_text())
        fields = {item["key"]: item for item in config["fields"]}

        self.assertEqual(fields["320:319::value"]["label"], "提示词")
        self.assertEqual(fields["320:319::value"]["zone"], "user_input")
        self.assertEqual(fields["320:313::text"]["label"], "负面提示词")
        self.assertEqual(fields["320:313::text"]["zone"], "advanced")
        self.assertEqual(fields["320:288::strength"]["label"], "高清参考图强度")
        self.assertEqual(fields["320:288::strength"]["zone"], "advanced")
        self.assertEqual(fields["320:296::strength"]["label"], "初始参考图强度")
        self.assertEqual(fields["320:296::strength"]["zone"], "advanced")
        self.assertEqual(fields["320:285::strength_model"]["label"], "蒸馏 LoRA 强度")
        self.assertEqual(fields["320:285::strength_model"]["zone"], "advanced")

    def test_fast_variant_has_own_config_and_metadata(self):
        config = json.loads(FAST_CONFIG.read_text())
        fields = {item["key"]: item for item in config["fields"]}
        meta = json.loads(META.read_text())
        entry = meta["i2v_ltx23_sulphur_fp8.json"]

        self.assertEqual(config["workflow"], "i2v_ltx23_sulphur_fp8.json")
        self.assertEqual(fields["320:279::ckpt_name"]["label"], "Sulphur fp8 模型")
        self.assertEqual(fields["320:315::horizontal_tiles"]["label"], "VAE 横向分块数")
        self.assertEqual(entry["name"], "LTX2.3 Sulphur 快速版（fp8）")
        self.assertEqual(entry["source_path"], str(FAST_WORKFLOW))
        self.assertTrue(entry["shared"])


if __name__ == "__main__":
    unittest.main()
