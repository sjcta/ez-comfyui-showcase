import json
import pathlib
import tempfile
import unittest

import app


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / "data/workflows/DGX Spark"
CONFIG_DIR = ROOT / "data/wf_configs"


class ErnieWorkflowsTest(unittest.TestCase):
    def test_text_to_image_workflows_use_ernie_models(self):
        cases = {
            "t2i_ernie_image.json": ("ernie-image.safetensors", 20, 4),
            "t2i_ernie_image_turbo.json": ("ernie-image-turbo.safetensors", 8, 1),
        }
        for filename, (model_name, steps, cfg) in cases.items():
            with self.subTest(filename=filename):
                workflow = json.loads((WORKFLOW_DIR / filename).read_text())
                config = json.loads((CONFIG_DIR / filename).read_text())
                fields = {item["key"]: item for item in config["fields"]}

                self.assertEqual(workflow["66"]["class_type"], "UNETLoader")
                self.assertEqual(workflow["66"]["inputs"]["unet_name"], model_name)
                self.assertEqual(workflow["62"]["inputs"]["clip_name"], "ministral-3-3b.safetensors")
                self.assertEqual(workflow["62"]["inputs"]["type"], "flux2")
                self.assertEqual(workflow["63"]["inputs"]["vae_name"], "flux2-vae.safetensors")
                self.assertEqual(workflow["71"]["class_type"], "EmptyFlux2LatentImage")
                self.assertEqual(workflow["70"]["inputs"]["latent_image"], ["71", 0])
                self.assertEqual(workflow["70"]["inputs"]["steps"], steps)
                self.assertEqual(workflow["70"]["inputs"]["cfg"], cfg)
                prompt_key = "94::value" if "94::value" in fields else "6::text"
                self.assertEqual(fields[prompt_key]["zone"], "user_input")
                width_key = "80::value" if "80::value" in fields else "71::width"
                height_key = "81::value" if "81::value" in fields else "71::height"
                self.assertEqual(fields[width_key]["step"], 16)
                self.assertEqual(fields[height_key]["step"], 16)
                self.assertEqual(fields[width_key]["max"], 1376)
                self.assertEqual(fields[height_key]["max"], 1376)
                self.assertEqual(workflow["9"]["inputs"]["images"], ["110", 0])
                self.assertIn("seedvr2-2k", workflow["9"]["inputs"]["filename_prefix"])
                self.assertEqual(workflow["110"]["class_type"], "SeedVR2VideoUpscaler")
                self.assertEqual(workflow["110"]["inputs"]["image"], ["8", 0])
                self.assertEqual(workflow["110"]["inputs"]["dit"], ["112", 0])
                self.assertEqual(workflow["110"]["inputs"]["vae"], ["111", 0])
                self.assertEqual(workflow["110"]["inputs"]["resolution"], 2048)
                self.assertEqual(workflow["110"]["inputs"]["max_resolution"], 4096)
                self.assertEqual(workflow["111"]["inputs"]["model"], "ema_vae_fp16.safetensors")
                self.assertEqual(workflow["112"]["inputs"]["model"], "seedvr2_ema_7b_sharp-Q4_K_M.gguf")
                self.assertEqual(fields["110::resolution"]["label"], "SeedVR2 目标分辨率")
                self.assertEqual(fields["110::resolution"]["zone"], "advanced")
                self.assertEqual(fields["110::batch_size"]["zone"], "hidden")
                self.assertFalse(fields["110::uniform_batch_size"]["visible"])

    def test_turbo_text_to_image_uses_official_prompt_enhancer_path(self):
        workflow = json.loads((WORKFLOW_DIR / "t2i_ernie_image_turbo.json").read_text())
        config = json.loads((CONFIG_DIR / "t2i_ernie_image_turbo.json").read_text())
        fields = {item["key"]: item for item in config["fields"]}

        self.assertEqual(workflow["6"]["inputs"]["text"], ["97", 0])
        self.assertEqual(workflow["71"]["inputs"]["width"], ["80", 0])
        self.assertEqual(workflow["71"]["inputs"]["height"], ["81", 0])
        self.assertEqual(workflow["93"]["class_type"], "StringReplace")
        self.assertIn("Prompt 增强助手", workflow["93"]["inputs"]["string"])
        self.assertEqual(workflow["94"]["class_type"], "PrimitiveStringMultiline")
        self.assertEqual(workflow["95"]["class_type"], "TextGenerate")
        self.assertEqual(workflow["95"]["inputs"]["clip"], ["98", 0])
        self.assertEqual(workflow["95"]["inputs"]["prompt"], ["102", 0])
        self.assertEqual(workflow["95"]["inputs"]["sampling_mode.temperature"], 0.6)
        self.assertEqual(workflow["95"]["inputs"]["sampling_mode.seed"], 0)
        self.assertEqual(workflow["96"]["inputs"]["value"], True)
        self.assertEqual(workflow["97"]["inputs"]["switch"], ["96", 0])
        self.assertEqual(workflow["97"]["inputs"]["on_false"], ["94", 0])
        self.assertEqual(workflow["97"]["inputs"]["on_true"], ["95", 0])
        self.assertEqual(workflow["98"]["inputs"]["clip_name"], "ernie-image-prompt-enhancer.safetensors")
        self.assertEqual(workflow["98"]["inputs"]["type"], "flux2")
        self.assertEqual(fields["94::value"]["zone"], "user_input")
        self.assertEqual(fields["80::value"]["label"], "宽度")
        self.assertEqual(fields["80::value"]["role"], "width")
        self.assertEqual(fields["81::value"]["label"], "高度")
        self.assertEqual(fields["81::value"]["role"], "height")
        self.assertEqual(fields["96::value"]["type"], "toggle")

    def test_image_to_image_workflows_encode_reference_image(self):
        cases = {
            "i2i_ernie_image.json": ("ernie-image.safetensors", 0.55),
            "i2i_ernie_image_turbo.json": ("ernie-image-turbo.safetensors", 0.45),
        }
        for filename, (model_name, denoise) in cases.items():
            with self.subTest(filename=filename):
                workflow = json.loads((WORKFLOW_DIR / filename).read_text())
                config = json.loads((CONFIG_DIR / filename).read_text())
                fields = {item["key"]: item for item in config["fields"]}

                self.assertEqual(workflow["40"]["class_type"], "LoadImage")
                self.assertEqual(workflow["41"]["class_type"], "ImageScale")
                self.assertEqual(workflow["42"]["class_type"], "VAEEncode")
                self.assertEqual(workflow["42"]["inputs"]["pixels"], ["41", 0])
                self.assertEqual(workflow["70"]["inputs"]["latent_image"], ["42", 0])
                self.assertEqual(workflow["70"]["inputs"]["denoise"], denoise)
                self.assertEqual(workflow["66"]["inputs"]["unet_name"], model_name)
                self.assertEqual(fields["40::image"]["type"], "image")
                self.assertEqual(fields["41::width"]["zone"], "hidden")
                self.assertFalse(fields["41::width"]["visible"])
                self.assertEqual(fields["41::width"]["max"], 1376)
                self.assertEqual(fields["41::height"]["zone"], "hidden")
                self.assertFalse(fields["41::height"]["visible"])
                self.assertEqual(fields["41::height"]["max"], 1376)
                self.assertEqual(fields["70::denoise"]["label"], "重绘强度")

    def test_i2i_reference_image_auto_selects_official_ernie_size(self):
        try:
            from PIL import Image
        except Exception as exc:
            self.skipTest(f"Pillow unavailable: {exc}")
        workflow = json.loads((WORKFLOW_DIR / "i2i_ernie_image_turbo.json").read_text())
        old_input = app.COMFYUI_INPUT
        with tempfile.TemporaryDirectory() as tmp:
            try:
                app.COMFYUI_INPUT = tmp
                image_path = pathlib.Path(tmp) / "u1" / "portrait.png"
                image_path.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (1600, 2400), "white").save(image_path)
                fields = {
                    "40::image": "u1/portrait.png",
                    "41::width": 1024,
                    "41::height": 1024,
                }

                size = app._sync_ernie_i2i_reference_dimensions(
                    "i2i_ernie_image_turbo.json",
                    workflow,
                    fields,
                )
            finally:
                app.COMFYUI_INPUT = old_input

        self.assertEqual(size, (848, 1264))
        self.assertEqual(fields["41::width"], 848)
        self.assertEqual(fields["41::height"], 1264)
        self.assertEqual(fields["__ernie_i2i_source_size"], "1600x2400")
        self.assertEqual(fields["__ernie_i2i_auto_size"], "848x1264")

    def test_ernie_workflows_are_admin_test_only(self):
        meta = json.loads((ROOT / "data/wf_meta.json").read_text())
        for filename in (
            "t2i_ernie_image.json",
            "t2i_ernie_image_turbo.json",
            "i2i_ernie_image.json",
            "i2i_ernie_image_turbo.json",
        ):
            with self.subTest(filename=filename):
                self.assertIn(filename, meta)
                self.assertFalse(meta[filename]["shared"])
                self.assertEqual(meta[filename]["source"], "DGX Spark")


if __name__ == "__main__":
    unittest.main()
