import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LTX23_AUDIO_VAE = "LTX23_audio_vae_bf16.safetensors"
SULPHUR_DISTIL_NVFP4 = "ltx/sulphur_distil_nvfp4mixed.safetensors"
SINGULARITY_BASE_MODEL = "ltx-2.3-22b-distilled-1.1_transformer_only_fp8_scaled.safetensors"

WORKFLOWS = [
    ROOT / "data/workflows/DGX Spark/i2v_ltx23_singularity_omnicine.json",
    ROOT / "data/workflows/DGX Spark/i2v_ltx23_sulphur_fp8.json",
    ROOT / "data/workflows/DGX Spark/i2v_ltx23_sulphur.json",
    ROOT / "data/workflows/DGX Spark/i2v_ltx23_10eros.json",
    ROOT / "data/workflows/DGX Spark/i2v_ltx23_10eros_director.json",
    ROOT / "data/workflows/ez-comfy/I2V_10eros_v3_TiledSampler.json",
]

MAIN_LTX_WORKFLOWS = [
    path for path in WORKFLOWS if "I2V_10eros_v3_TiledSampler" not in path.name
]


def _nodes_by_type(workflow, class_type):
    return {
        node_id: node
        for node_id, node in workflow.items()
        if node.get("class_type") == class_type
    }


class LtxAudioVaeWorkflowTests(unittest.TestCase):
    def test_ltx_video_workflows_default_to_8s_at_24fps(self):
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                workflow = json.loads(path.read_text())

                if "I2V_10eros_v3_TiledSampler" in path.name:
                    self.assertEqual(workflow["542"]["inputs"]["value"], 24)
                    self.assertEqual(workflow["796"]["inputs"]["Xi"], 192)
                    self.assertEqual(workflow["796"]["inputs"]["Xf"], 192)
                    self.assertEqual(workflow["798"]["inputs"]["expression"], "a + 1")
                    continue

                if path.name == "i2v_ltx23_sulphur_fp8.json":
                    self.assertEqual(workflow["320:300"]["inputs"]["value"], 25)
                    self.assertEqual(workflow["320:301"]["inputs"]["value"], 10)
                else:
                    self.assertEqual(workflow["320:300"]["inputs"]["value"], 24)
                    self.assertEqual(workflow["320:301"]["inputs"]["value"], 8)
                self.assertEqual(workflow["320:323"]["inputs"]["expression"], "a * b + 1")

    def test_main_ltx_workflows_use_low_lora_audio_clean_first_pass(self):
        for path in MAIN_LTX_WORKFLOWS:
            with self.subTest(workflow=path.name):
                workflow = json.loads(path.read_text())

                if path.name == "i2v_ltx23_sulphur_fp8.json":
                    self.assertEqual(workflow["320:314"]["inputs"]["model"], ["320:285", 0])
                    self.assertEqual(workflow["320:314"]["inputs"]["cfg"], 1)
                    self.assertNotIn("320:325", workflow)
                    continue

                self.assertEqual(workflow["320:325"]["class_type"], "LoraLoaderModelOnly")
                self.assertEqual(
                    workflow["320:325"]["inputs"]["lora_name"],
                    workflow["320:285"]["inputs"]["lora_name"],
                )
                if path.name == "i2v_ltx23_singularity_omnicine.json":
                    self.assertEqual(workflow["320:325"]["inputs"]["strength_model"], 1)
                    self.assertEqual(workflow["320:314"]["inputs"]["cfg"], 1)
                else:
                    self.assertEqual(workflow["320:325"]["inputs"]["strength_model"], 0.28)
                    self.assertEqual(workflow["320:314"]["inputs"]["cfg"], 3)
                self.assertEqual(workflow["320:325"]["inputs"]["model"], ["320:316", 0])
                self.assertEqual(workflow["320:314"]["inputs"]["model"], ["320:325", 0])
                self.assertEqual(workflow["320:282"]["inputs"]["model"], ["320:285", 0])
                self.assertEqual(workflow["320:282"]["inputs"]["cfg"], 1)

    def test_audio_vae_loader_matches_checkpoint_or_ltx23_standalone_vae(self):
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                workflow = json.loads(path.read_text())
                audio_loaders = _nodes_by_type(workflow, "LTXVAudioVAELoader")
                kj_vae_loaders = _nodes_by_type(workflow, "VAELoaderKJ")

                if path.name == "i2v_ltx23_singularity_omnicine.json":
                    self.assertEqual(workflow["320:316"]["class_type"], "UNETLoader")
                    self.assertEqual(workflow["320:316"]["inputs"]["unet_name"], SINGULARITY_BASE_MODEL)
                    self.assertFalse(audio_loaders)
                    self.assertTrue(
                        any(
                            node["inputs"].get("vae_name") == LTX23_AUDIO_VAE
                            for node in kj_vae_loaders.values()
                        ),
                        f"{path.name} must use standalone LTX23 audio VAE",
                    )
                    continue

                checkpoints = _nodes_by_type(workflow, "CheckpointLoaderSimple")
                main_ckpt = next(iter(checkpoints.values()))["inputs"]["ckpt_name"]
                if "transformer_only" in main_ckpt:
                    self.assertFalse(audio_loaders)
                    self.assertTrue(
                        any(
                            node["inputs"].get("vae_name") == LTX23_AUDIO_VAE
                            for node in kj_vae_loaders.values()
                        ),
                        f"{path.name} must use standalone LTX23 audio VAE",
                    )
                    continue

                self.assertTrue(audio_loaders)
                for node in audio_loaders.values():
                    if path.name == "i2v_ltx23_sulphur_fp8.json":
                        self.assertEqual(node["inputs"]["ckpt_name"], SULPHUR_DISTIL_NVFP4)
                    else:
                        self.assertEqual(node["inputs"]["ckpt_name"], main_ckpt)

    def test_singularity_audio_latents_and_decode_use_ltx23_audio_vae(self):
        workflow = json.loads(
            (
                ROOT
                / "data/workflows/DGX Spark/i2v_ltx23_singularity_omnicine.json"
            ).read_text()
        )
        config = json.loads(
            (
                ROOT / "data/wf_configs/i2v_ltx23_singularity_omnicine.json"
            ).read_text()
        )
        fields = {item["key"]: item for item in config["fields"]}

        self.assertEqual(workflow["320:279"]["class_type"], "VAELoaderKJ")
        self.assertEqual(workflow["320:279"]["inputs"]["vae_name"], LTX23_AUDIO_VAE)
        self.assertEqual(workflow["320:305"]["inputs"]["audio_vae"], ["320:279", 0])
        self.assertEqual(workflow["320:297"]["inputs"]["audio_vae"], ["320:279", 0])
        self.assertEqual(workflow["320:317"]["class_type"], "DualCLIPLoader")
        self.assertEqual(workflow["320:317"]["inputs"]["clip_name1"], "gemma_3_12B_it_fp8_scaled.safetensors")
        self.assertEqual(workflow["320:317"]["inputs"]["clip_name2"], "ltx-2.3_text_projection_bf16.safetensors")
        self.assertEqual(workflow["320:317"]["inputs"]["type"], "ltxv")
        self.assertEqual(fields["320:279::vae_name"]["label"], "LTX23 音频 VAE")
        self.assertNotIn("320:279::ckpt_name", fields)

    def test_singularity_normalization_locks_remote_available_model(self):
        try:
            import app as app_module
        except ModuleNotFoundError as exc:
            if exc.name == "fastapi":
                self.skipTest("FastAPI dependency is not installed in this Python environment")
            raise
        workflow = json.loads(
            (
                ROOT
                / "data/workflows/DGX Spark/i2v_ltx23_singularity_omnicine.json"
            ).read_text()
        )
        fields = {
            "320:316::ckpt_name": "ltx/sulphur_dev_fp8mixed.safetensors",
            "320:316::unet_name": "ltx/sulphur_dev_fp8mixed.safetensors",
            "320:317::ckpt_name": "ltx/sulphur_dev_fp8mixed.safetensors",
            "320:317::clip_name1": "gemma_3_12B_it_fp4_mixed.safetensors",
            "320:317::clip_name2": "bad_projection.safetensors",
            "320:317::type": "sdxl",
            "320:314::cfg": 3,
            "320:325::strength_model": 0.2,
            "320:279::vae_name": "bad.safetensors",
        }

        normalized = app_module._normalize_workflow_field_values(
            workflow,
            fields,
            "i2v_ltx23_singularity_omnicine.json",
        )

        self.assertEqual(normalized["320:316::unet_name"], SINGULARITY_BASE_MODEL)
        self.assertEqual(normalized["320:316::weight_dtype"], "default")
        self.assertEqual(normalized["320:317::clip_name1"], "gemma_3_12B_it_fp8_scaled.safetensors")
        self.assertEqual(normalized["320:317::clip_name2"], "ltx-2.3_text_projection_bf16.safetensors")
        self.assertEqual(normalized["320:317::type"], "ltxv")
        self.assertEqual(normalized["320:314::cfg"], 1)
        self.assertEqual(normalized["320:325::strength_model"], 1)
        self.assertEqual(normalized["320:279::vae_name"], LTX23_AUDIO_VAE)


if __name__ == "__main__":
    unittest.main()
