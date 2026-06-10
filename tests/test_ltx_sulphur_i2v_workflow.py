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
SULPHUR_DISTIL_NVFP4 = "ltx/sulphur_distil_nvfp4mixed.safetensors"


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

    def test_fast_variant_uses_verified_sulphur_distil_model(self):
        workflow = json.loads(FAST_WORKFLOW.read_text())

        self.assertEqual(workflow["320:279"]["inputs"]["ckpt_name"], SULPHUR_DISTIL_NVFP4)
        self.assertEqual(workflow["320:316"]["inputs"]["ckpt_name"], SULPHUR_DISTIL_NVFP4)
        self.assertEqual(workflow["320:317"]["inputs"]["ckpt_name"], SULPHUR_DISTIL_NVFP4)
        self.assertEqual(workflow["75"]["inputs"]["filename_prefix"], "video/LTX_2.3_i2v")

    def test_default_negative_prompt_suppresses_audio_rumble(self):
        workflow = json.loads(WORKFLOW.read_text())
        negative = workflow["320:313"]["inputs"]["text"]

        self.assertIn("low frequency hum", negative)
        self.assertIn("sub-bass rumble", negative)
        self.assertIn("noisy room tone", negative)

    def test_sulphur_variants_use_standard_tiled_decode(self):
        for path in (WORKFLOW, FAST_WORKFLOW):
            with self.subTest(path=path.name):
                workflow = json.loads(path.read_text())
                decode = workflow["320:315"]

                self.assertEqual(decode["class_type"], "VAEDecodeTiled")
                self.assertEqual(decode["inputs"]["samples"], ["320:309", 0])
                self.assertEqual(decode["inputs"]["vae"], ["320:316", 2])
                if path == FAST_WORKFLOW:
                    self.assertEqual(decode["inputs"]["tile_size"], 768)
                    self.assertEqual(decode["inputs"]["overlap"], 64)
                    self.assertEqual(decode["inputs"]["temporal_size"], 4096)
                    self.assertEqual(decode["inputs"]["temporal_overlap"], 4)
                else:
                    self.assertEqual(decode["inputs"]["tile_size"], 512)
                    self.assertEqual(decode["inputs"]["overlap"], 64)
                    self.assertEqual(decode["inputs"]["temporal_size"], 64)
                    self.assertEqual(decode["inputs"]["temporal_overlap"], 8)

    def test_normalization_preserves_tiled_decode_chunk_parameters(self):
        try:
            import app as app_module
        except ModuleNotFoundError as exc:
            if exc.name == "fastapi":
                self.skipTest("FastAPI dependency is not installed in this Python environment")
            raise
        workflow = json.loads(FAST_WORKFLOW.read_text())
        fields = {
            "320:300::value": 25,
            "320:301::value": 10,
            "320:315::tile_size": 768,
            "320:315::overlap": 64,
            "320:315::temporal_size": 4096,
            "320:315::temporal_overlap": 4,
        }

        normalized = app_module._normalize_workflow_field_values(workflow, fields)

        self.assertEqual(normalized["320:315::tile_size"], 768)
        self.assertEqual(normalized["320:315::temporal_size"], 4096)
        self.assertEqual(normalized["320:315::temporal_overlap"], 4)

    def test_dist_normalization_locks_quality_params_but_keeps_timing_edits(self):
        try:
            import app as app_module
        except ModuleNotFoundError as exc:
            if exc.name == "fastapi":
                self.skipTest("FastAPI dependency is not installed in this Python environment")
            raise
        workflow = json.loads(FAST_WORKFLOW.read_text())
        fields = {
            "320:300::value": 24,
            "320:301::value": 15,
            "320:279::ckpt_name": SULPHUR_DEV_FP8,
            "320:316::ckpt_name": SULPHUR_DEV_FP8,
            "320:317::ckpt_name": SULPHUR_DEV_FP8,
            "320:281::sigmas": "bad",
            "320:282::cfg": 9,
            "320:285::strength_model": 0.1,
            "320:315::tile_size": 256,
            "320:315::temporal_size": ["320:323", 1],
            "320:315::temporal_overlap": 99,
        }

        normalized = app_module._normalize_workflow_field_values(
            workflow,
            fields,
            "i2v_ltx23_sulphur_fp8.json",
        )

        self.assertEqual(normalized["320:300::value"], 24)
        self.assertEqual(normalized["320:301::value"], 15)
        self.assertEqual(normalized["320:279::ckpt_name"], SULPHUR_DISTIL_NVFP4)
        self.assertEqual(normalized["320:316::ckpt_name"], SULPHUR_DISTIL_NVFP4)
        self.assertEqual(normalized["320:317::ckpt_name"], SULPHUR_DISTIL_NVFP4)
        self.assertEqual(normalized["320:281::sigmas"], "0.85, 0.7250, 0.4219, 0.0")
        self.assertEqual(normalized["320:282::cfg"], 1)
        self.assertEqual(normalized["320:285::strength_model"], 0.5)
        self.assertEqual(normalized["320:315::tile_size"], 768)
        self.assertEqual(normalized["320:315::temporal_size"], 4096)
        self.assertEqual(normalized["320:315::temporal_overlap"], 4)

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
        self.assertEqual(fields["320:301::value"]["zone"], "user_input")
        self.assertTrue(fields["320:301::value"]["visible"])
        self.assertEqual(fields["320:300::value"]["zone"], "user_input")
        self.assertTrue(fields["320:300::value"]["visible"])
        self.assertEqual(fields["320:279::ckpt_name"]["label"], "Sulphur distil 模型")
        self.assertEqual(fields["320:279::ckpt_name"]["zone"], "hidden")
        self.assertFalse(fields["320:279::ckpt_name"]["visible"])
        self.assertEqual(fields["320:315::tile_size"]["label"], "VAE 分块尺寸")
        self.assertEqual(fields["320:315::tile_size"]["zone"], "hidden")
        self.assertFalse(fields["320:315::tile_size"]["visible"])
        self.assertEqual(fields["320:315::temporal_size"]["label"], "VAE 时间分块")
        self.assertEqual(fields["320:315::temporal_size"]["zone"], "hidden")
        self.assertFalse(fields["320:315::temporal_size"]["visible"])
        self.assertEqual(entry["name"], "LTX2.3 Sulphur dist版")
        self.assertEqual(entry["source_path"], str(FAST_WORKFLOW))
        self.assertTrue(entry["shared"])


if __name__ == "__main__":
    unittest.main()
