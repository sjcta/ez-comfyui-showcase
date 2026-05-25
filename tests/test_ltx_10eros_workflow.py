import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "data/workflows/DGX Spark/i2v_ltx23_10eros.json"
CONFIG = ROOT / "data/wf_configs/i2v_ltx23_10eros.json"
META = ROOT / "data/wf_meta.json"


class Ltx10ErosWorkflowTests(unittest.TestCase):
    def test_uses_10eros_fp8mixed_checkpoint_with_sulphur_support_components(self):
        workflow = json.loads(WORKFLOW.read_text())

        self.assertEqual(workflow["320:330"]["class_type"], "CheckpointLoaderSimple")
        self.assertEqual(
            workflow["320:330"]["inputs"]["ckpt_name"],
            "ltx/10Eros_v1-fp8mixed_learned.safetensors",
        )
        self.assertEqual(workflow["320:285"]["inputs"]["model"], ["320:330", 0])
        self.assertEqual(
            workflow["320:316"]["inputs"]["ckpt_name"],
            "ltx/sulphur_dev_fp8mixed.safetensors",
        )
        self.assertEqual(
            workflow["320:317"]["inputs"]["ckpt_name"],
            "ltx/sulphur_dev_fp8mixed.safetensors",
        )

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

    def test_keeps_ltx_tail_decode_fix(self):
        workflow = json.loads(WORKFLOW.read_text())
        decode = workflow["320:315"]

        self.assertEqual(decode["class_type"], "LTXVTiledVAEDecode")
        self.assertTrue(decode["inputs"]["last_frame_fix"])

    def test_editor_config_exposes_10eros_model_choice(self):
        config = json.loads(CONFIG.read_text())
        fields = {item["key"]: item for item in config["fields"]}

        self.assertEqual(config["workflow"], "i2v_ltx23_10eros.json")
        self.assertEqual(fields["320:330::ckpt_name"]["label"], "10Eros Checkpoint模型")
        self.assertEqual(fields["320:330::ckpt_name"]["zone"], "advanced")
        self.assertTrue(fields["320:330::ckpt_name"]["visible"])
        self.assertTrue(fields["320:308::n_tiles"]["visible"])
        self.assertEqual(fields["320:308::n_tiles"]["label"], "分块数量")
        self.assertTrue(fields["320:308::tile_overlap"]["visible"])
        self.assertEqual(fields["320:279::ckpt_name"]["zone"], "hidden")

    def test_final_video_output_does_not_decode_audio(self):
        workflow = json.loads(WORKFLOW.read_text())

        self.assertNotIn("audio", workflow["320:310"]["inputs"])
        self.assertNotIn("320:297", workflow)

    def test_metadata_registers_workflow(self):
        meta = json.loads(META.read_text())
        entry = meta["i2v_ltx23_10eros.json"]

        self.assertEqual(entry["name"], "LTX2.3 10Eros")
        self.assertTrue(entry["shared"])
        self.assertIn("视频制作", entry["tags"])


if __name__ == "__main__":
    unittest.main()
