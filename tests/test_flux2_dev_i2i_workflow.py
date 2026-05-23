import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "data/workflows/DGX Spark/i2i_flux2_dev_turbo_q4km.json"
T2I_WORKFLOW = ROOT / "data/workflows/DGX Spark/t2i_flux2_dev_turbo_q4km.json"
CONFIG = ROOT / "data/wf_configs/i2i_flux2_dev_turbo_q4km.json"
META = ROOT / "data/wf_meta.json"


class Flux2DevI2IWorkflowTest(unittest.TestCase):
    def test_t2i_turbo_uses_official_dev_turbo_defaults_with_gguf_loader(self):
        workflow = json.loads(T2I_WORKFLOW.read_text())

        self.assertEqual(
            workflow["12"]["inputs"]["unet_name"],
            "gguf/flux2-dev-city96-Q4_K_M.gguf",
        )
        self.assertEqual(workflow["89"]["class_type"], "LoraLoaderModelOnly")
        self.assertEqual(workflow["89"]["inputs"]["model"], ["12", 0])
        self.assertEqual(
            workflow["89"]["inputs"]["lora_name"],
            "Flux_2-Turbo-LoRA_comfyui.safetensors",
        )
        self.assertEqual(workflow["89"]["inputs"]["strength_model"], 1.0)
        self.assertEqual(
            workflow["10"]["inputs"]["vae_name"],
            "full_encoder_small_decoder.safetensors",
        )
        self.assertEqual(
            workflow["38"]["inputs"]["clip_name"],
            "mistral_3_small_flux2_bf16.safetensors",
        )
        self.assertEqual(workflow["16"]["inputs"]["sampler_name"], "euler")
        self.assertEqual(workflow["48"]["inputs"]["steps"], 8)
        self.assertEqual(workflow["26"]["inputs"]["guidance"], 4.0)
        self.assertEqual(workflow["22"]["class_type"], "BasicGuider")
        self.assertEqual(workflow["22"]["inputs"]["model"], ["89", 0])
        self.assertEqual(workflow["22"]["inputs"]["conditioning"], ["26", 0])

    def test_workflow_uses_dev_model_and_i2i_reference_chain(self):
        workflow = json.loads(WORKFLOW.read_text())

        self.assertEqual(
            workflow["12"]["inputs"]["unet_name"],
            "gguf/flux2-dev-city96-Q4_K_M.gguf",
        )
        self.assertEqual(workflow["89"]["class_type"], "LoraLoaderModelOnly")
        self.assertEqual(workflow["89"]["inputs"]["model"], ["12", 0])
        self.assertEqual(
            workflow["89"]["inputs"]["lora_name"],
            "Flux_2-Turbo-LoRA_comfyui.safetensors",
        )
        self.assertEqual(workflow["89"]["inputs"]["strength_model"], 1.0)
        self.assertEqual(workflow["20"]["inputs"]["model"], ["89", 0])
        self.assertEqual(
            workflow["38"]["inputs"]["clip_name"],
            "mistral_3_small_flux2_bf16.safetensors",
        )
        self.assertEqual(workflow["40"]["class_type"], "LoadImage")
        self.assertEqual(workflow["41"]["class_type"], "ImageScaleToTotalPixels")
        self.assertEqual(workflow["41"]["inputs"]["image"], ["40", 0])
        self.assertEqual(workflow["41"]["inputs"]["upscale_method"], "lanczos")
        self.assertEqual(workflow["41"]["inputs"]["megapixels"], 1.0)
        self.assertEqual(workflow["42"]["class_type"], "VAEEncode")
        self.assertEqual(workflow["42"]["inputs"]["pixels"], ["41", 0])
        self.assertEqual(workflow["26"]["inputs"]["guidance"], 4.0)
        self.assertEqual(
            workflow["9"]["inputs"]["filename_prefix"],
            "i2i-flux2-dev-turbo-q4km",
        )

    def test_config_exposes_i2i_input_and_dev_workflow(self):
        config = json.loads(CONFIG.read_text())
        fields = {item["key"]: item for item in config["fields"]}

        self.assertEqual(config["workflow"], "i2i_flux2_dev_turbo_q4km.json")
        self.assertEqual(fields["40::image"]["type"], "image")
        self.assertEqual(fields["40::image"]["label"], "参考图片")
        self.assertEqual(fields["48::steps"]["min"], 1)
        self.assertEqual(fields["48::steps"]["max"], 32)

    def test_workflow_meta_makes_dev_i2i_visible(self):
        meta = json.loads(META.read_text())
        entry = meta["i2i_flux2_dev_turbo_q4km.json"]

        self.assertEqual(entry["name"], "Flux2 Dev Turbo Q4 图生图")
        self.assertIn("图生图", entry["tags"])
        self.assertIn("Flux2", entry["tags"])
        self.assertTrue(entry["shared"])
        self.assertEqual(entry["source"], "DGX Spark")
        self.assertEqual(
            entry["source_path"],
            str(WORKFLOW),
        )


if __name__ == "__main__":
    unittest.main()
