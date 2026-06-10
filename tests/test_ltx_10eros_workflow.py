import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "data/workflows/DGX Spark/i2v_ltx23_10eros.json"
CONFIG = ROOT / "data/wf_configs/i2v_ltx23_10eros.json"
DIRECTOR_WORKFLOW = ROOT / "data/workflows/DGX Spark/i2v_ltx23_10eros_director.json"
DIRECTOR_CONFIG = ROOT / "data/wf_configs/i2v_ltx23_10eros_director.json"
ANTIFLICKER_WORKFLOW = ROOT / "data/workflows/DGX Spark/i2v_ltx23_10eros_antiflicker.json"
ANTIFLICKER_CONFIG = ROOT / "data/wf_configs/i2v_ltx23_10eros_antiflicker.json"
AUDIO_CLEAN_WORKFLOW = ROOT / "data/workflows/DGX Spark/i2v_ltx23_10eros_antiflicker_audio_clean_test.json"
AUDIO_CLEAN_CONFIG = ROOT / "data/wf_configs/i2v_ltx23_10eros_antiflicker_audio_clean_test.json"
TILED_WORKFLOW = ROOT / "data/workflows/ez-comfy/I2V_10eros_v3_TiledSampler.json"
TILED_CONFIG = ROOT / "data/wf_configs/I2V_10eros_v3_TiledSampler.json"
META = ROOT / "data/wf_meta.json"


TEN_EROS_CKPT = "ltx/10Eros_v1-fp8mixed_learned.safetensors"


class Ltx10ErosWorkflowTests(unittest.TestCase):
    def test_uses_10eros_model_with_matching_audio_support_components(self):
        workflow = json.loads(WORKFLOW.read_text())

        self.assertNotIn("320:330", workflow)
        self.assertEqual(workflow["320:316"]["class_type"], "CheckpointLoaderSimple")
        self.assertEqual(workflow["320:285"]["inputs"]["model"], ["320:316", 0])
        self.assertEqual(workflow["320:279"]["inputs"]["ckpt_name"], TEN_EROS_CKPT)
        self.assertEqual(
            workflow["320:316"]["inputs"]["ckpt_name"],
            TEN_EROS_CKPT,
        )
        self.assertEqual(
            workflow["320:317"]["inputs"]["ckpt_name"],
            TEN_EROS_CKPT,
        )

    def test_default_negative_prompt_suppresses_audio_rumble(self):
        workflow = json.loads(WORKFLOW.read_text())
        negative = workflow["320:313"]["inputs"]["text"]

        self.assertIn("low frequency hum", negative)
        self.assertIn("sub-bass rumble", negative)
        self.assertIn("noisy room tone", negative)

    def test_uses_10s_tiled_sampler_for_second_pass(self):
        workflow = json.loads(WORKFLOW.read_text())
        sampler = workflow["320:308"]

        self.assertEqual(sampler["class_type"], "LTXTiledSampler")
        self.assertEqual(sampler["inputs"]["tile_axis"], "auto")
        self.assertEqual(sampler["inputs"]["n_tiles"], 2)
        self.assertEqual(sampler["inputs"]["tile_overlap"], 8)
        self.assertEqual(sampler["inputs"]["audio_pass"], "tile_carrying")
        self.assertEqual(sampler["inputs"]["audio_carrier_tile"], "first")
        self.assertEqual(workflow["320:309"]["inputs"]["av_latent"], ["320:308", 1])

    def test_uses_standard_tiled_decode(self):
        workflow = json.loads(WORKFLOW.read_text())
        decode = workflow["320:315"]

        self.assertEqual(decode["class_type"], "VAEDecodeTiled")
        self.assertEqual(decode["inputs"]["samples"], ["320:309", 0])
        self.assertEqual(decode["inputs"]["vae"], ["320:316", 2])
        self.assertEqual(decode["inputs"]["tile_size"], 512)
        self.assertEqual(decode["inputs"]["overlap"], 64)
        self.assertEqual(decode["inputs"]["temporal_size"], 64)
        self.assertEqual(decode["inputs"]["temporal_overlap"], 8)

    def test_editor_config_exposes_10eros_model_choice(self):
        config = json.loads(CONFIG.read_text())
        fields = {item["key"]: item for item in config["fields"]}

        self.assertEqual(config["workflow"], "i2v_ltx23_10eros.json")
        self.assertEqual(fields["320:316::ckpt_name"]["label"], "10Eros fp8mixed 主模型")
        self.assertEqual(fields["320:316::ckpt_name"]["zone"], "advanced")
        self.assertTrue(fields["320:316::ckpt_name"]["visible"])
        self.assertTrue(fields["320:308::n_tiles"]["visible"])
        self.assertEqual(fields["320:308::n_tiles"]["label"], "分块数量")
        self.assertTrue(fields["320:308::tile_overlap"]["visible"])
        self.assertEqual(fields["320:279::ckpt_name"]["zone"], "hidden")

    def test_final_video_output_decodes_audio(self):
        workflow = json.loads(WORKFLOW.read_text())

        self.assertEqual(workflow["320:297"]["class_type"], "LTXVAudioVAEDecode")
        self.assertEqual(workflow["320:297"]["inputs"]["samples"], ["320:309", 1])
        self.assertEqual(workflow["320:297"]["inputs"]["audio_vae"], ["320:279", 0])
        self.assertEqual(workflow["320:310"]["inputs"]["audio"], ["320:297", 0])

    def test_antiflicker_variant_aligns_available_official_settings(self):
        workflow = json.loads(ANTIFLICKER_WORKFLOW.read_text())
        config = json.loads(ANTIFLICKER_CONFIG.read_text())
        fields = {item["key"]: item for item in config["fields"]}
        meta = json.loads(META.read_text())

        self.assertEqual(config["workflow"], "i2v_ltx23_10eros_antiflicker.json")
        self.assertEqual(workflow["320:291"]["inputs"]["sampler_name"], "euler_ancestral")
        self.assertIn("0.1206", workflow["320:306"]["inputs"]["sigmas"])
        self.assertEqual(workflow["320:314"]["inputs"]["cfg"], 3)
        self.assertEqual(workflow["320:325"]["inputs"]["strength_model"], 0.28)
        self.assertEqual(workflow["320:280"]["inputs"]["sampler_name"], "euler_ancestral_cfg_pp")
        self.assertEqual(workflow["320:281"]["inputs"]["sigmas"], "0.715, 0.4824, 0.2412, 0.0")
        self.assertEqual(workflow["320:315"]["class_type"], "VAEDecode")
        self.assertEqual(workflow["320:315"]["inputs"]["samples"], ["320:309", 0])
        self.assertEqual(workflow["320:310"]["inputs"]["images"], ["320:315", 0])
        self.assertEqual(workflow["75"]["inputs"]["filename_prefix"], "video/LTX_2.3_10Eros_i2v_antiflicker")
        self.assertIn("269::image", fields)
        self.assertNotIn("320:315::horizontal_tiles", fields)
        self.assertTrue(fields["320:308::bypass_tiling"]["visible"])
        self.assertTrue(meta["i2v_ltx23_10eros_antiflicker.json"]["shared"])

    def test_antiflicker_audio_clean_test_variant_is_registered(self):
        workflow = json.loads(AUDIO_CLEAN_WORKFLOW.read_text())
        config = json.loads(AUDIO_CLEAN_CONFIG.read_text())
        meta = json.loads(META.read_text())
        entry = meta["i2v_ltx23_10eros_antiflicker_audio_clean_test.json"]

        self.assertEqual(config["workflow"], "i2v_ltx23_10eros_antiflicker_audio_clean_test.json")
        self.assertEqual(workflow["320:314"]["inputs"]["cfg"], 3)
        self.assertEqual(workflow["320:325"]["inputs"]["strength_model"], 0.28)
        self.assertEqual(workflow["320:325"]["inputs"]["model"], ["320:316", 0])
        self.assertEqual(workflow["320:314"]["inputs"]["model"], ["320:325", 0])
        self.assertEqual(
            workflow["75"]["inputs"]["filename_prefix"],
            "video/LTX_2.3_10Eros_i2v_antiflicker_audio_clean_test",
        )
        self.assertEqual(entry["name"], "LTX2.3 10Eros 抗闪降噪测试版")
        self.assertFalse(entry["shared"])

    def test_metadata_registers_workflow(self):
        meta = json.loads(META.read_text())
        entry = meta["i2v_ltx23_10eros.json"]

        self.assertEqual(entry["name"], "LTX2.3 10Eros")
        self.assertTrue(entry["shared"])
        self.assertIn("视频制作", entry["tags"])

    def test_director_variant_uses_ltx_director_nodes(self):
        workflow = json.loads(DIRECTOR_WORKFLOW.read_text())

        self.assertEqual(workflow["320:340"]["class_type"], "LTXDirector")
        self.assertEqual(workflow["320:340"]["inputs"]["model"], ["320:285", 0])
        self.assertEqual(workflow["320:340"]["inputs"]["clip"], ["320:317", 0])
        self.assertEqual(workflow["320:340"]["inputs"]["audio_vae"], ["320:279", 0])
        self.assertEqual(workflow["320:340"]["inputs"]["duration_seconds"], ["320:344", 0])
        self.assertEqual(workflow["320:340"]["inputs"]["frame_rate"], ["320:298", 0])
        self.assertEqual(workflow["320:304"]["inputs"]["positive"], ["320:340", 1])
        self.assertEqual(workflow["320:304"]["inputs"]["frame_rate"], ["320:340", 5])
        self.assertEqual(workflow["320:344"]["class_type"], "ComfyMathExpression")
        self.assertEqual(workflow["320:342"]["class_type"], "LTXDirectorGuide")
        self.assertEqual(workflow["320:343"]["class_type"], "LTXDirectorGuide")
        self.assertEqual(workflow["320:318"]["inputs"]["video_latent"], ["320:342", 2])
        self.assertEqual(workflow["320:318"]["inputs"]["audio_latent"], ["320:340", 3])
        self.assertEqual(workflow["320:314"]["inputs"]["positive"], ["320:342", 0])
        self.assertEqual(workflow["320:314"]["inputs"]["negative"], ["320:342", 1])
        self.assertEqual(workflow["320:284"]["inputs"]["positive"], ["320:342", 0])
        self.assertEqual(workflow["320:284"]["inputs"]["negative"], ["320:342", 1])
        self.assertEqual(workflow["320:343"]["inputs"]["positive"], ["320:284", 0])
        self.assertEqual(workflow["320:343"]["inputs"]["latent"], ["320:287", 0])
        self.assertEqual(workflow["320:278"]["inputs"]["video_latent"], ["320:343", 2])
        self.assertEqual(workflow["320:278"]["inputs"]["audio_latent"], ["320:307", 1])
        self.assertEqual(workflow["320:316"]["inputs"]["ckpt_name"], TEN_EROS_CKPT)

    def test_director_variant_quick_form_exposes_director_fields(self):
        config = json.loads(DIRECTOR_CONFIG.read_text())
        fields = {item["key"]: item for item in config["fields"]}
        meta = json.loads(META.read_text())

        self.assertEqual(config["workflow"], "i2v_ltx23_10eros_director.json")
        self.assertEqual(fields["320:340::global_prompt"]["zone"], "user_input")
        self.assertEqual(fields["320:340::global_prompt"]["label"], "导演全局提示词")
        self.assertEqual(fields["320:340::timeline_data"]["zone"], "hidden")
        self.assertEqual(fields["320:340::local_prompts"]["zone"], "hidden")
        self.assertEqual(fields["320:340::segment_lengths"]["zone"], "hidden")
        entry = meta["i2v_ltx23_10eros_director.json"]
        self.assertEqual(entry["name"], "LTX2.3 10Eros 导演版")
        self.assertTrue(entry["shared"])
        self.assertIn("视频制作", entry["tags"])

    def test_legacy_tiled_sampler_uses_stable_resize_path(self):
        workflow = json.loads(TILED_WORKFLOW.read_text())
        config = json.loads(TILED_CONFIG.read_text())
        config_fields = {item["key"] for item in config["fields"]}

        self.assertEqual(workflow["531"]["class_type"], "ResizeImageMaskNode")
        self.assertEqual(workflow["531"]["inputs"]["resize_type"], "scale dimensions")
        self.assertEqual(workflow["531"]["inputs"]["resize_type.width"], ["791", 0])
        self.assertEqual(workflow["531"]["inputs"]["resize_type.height"], ["792", 0])
        self.assertEqual(workflow["791"]["inputs"]["Xi"], 720)
        self.assertEqual(workflow["792"]["inputs"]["Xi"], 1280)
        self.assertEqual(workflow["532"]["inputs"]["resize_type.multiplier"], 0.5)
        self.assertNotIn("531::upscale_method", config_fields)
        self.assertIn("531::resize_type.width", config_fields)


if __name__ == "__main__":
    unittest.main()
