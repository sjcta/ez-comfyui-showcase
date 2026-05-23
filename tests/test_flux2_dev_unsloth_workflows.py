import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / "data/workflows/DGX Spark"
CONFIG_DIR = ROOT / "data/wf_configs"
META = ROOT / "data/wf_meta.json"


VARIANTS = {
    "q5km": "gguf/flux2-dev-Q5_K_M.gguf",
    "q6k": "gguf/flux2-dev-Q6_K.gguf",
}


class Flux2DevUnslothWorkflowsTest(unittest.TestCase):
    def test_t2i_variants_use_unsloth_model_defaults(self):
        for suffix, model_name in VARIANTS.items():
            with self.subTest(suffix=suffix):
                workflow = json.loads((WORKFLOW_DIR / f"t2i_flux2_dev_{suffix}.json").read_text())

                self.assertEqual(workflow["12"]["inputs"]["unet_name"], model_name)
                self.assertEqual(workflow["38"]["inputs"]["clip_name"], "mistral_3_small_flux2_bf16.safetensors")
                self.assertEqual(workflow["48"]["inputs"]["steps"], 28)
                self.assertEqual(workflow["26"]["inputs"]["guidance"], 4.0)
                self.assertEqual(workflow["9"]["inputs"]["filename_prefix"], f"flux2-dev-{suffix}")

    def test_i2i_variants_keep_reference_chain(self):
        for suffix, model_name in VARIANTS.items():
            with self.subTest(suffix=suffix):
                workflow = json.loads((WORKFLOW_DIR / f"i2i_flux2_dev_{suffix}.json").read_text())

                self.assertEqual(workflow["12"]["inputs"]["unet_name"], model_name)
                self.assertEqual(workflow["40"]["class_type"], "LoadImage")
                self.assertEqual(workflow["41"]["class_type"], "ImageScaleToTotalPixels")
                self.assertEqual(workflow["41"]["inputs"]["image"], ["40", 0])
                self.assertEqual(workflow["41"]["inputs"]["megapixels"], 1.0)
                self.assertEqual(workflow["42"]["inputs"]["pixels"], ["41", 0])
                self.assertEqual(workflow["48"]["inputs"]["steps"], 28)
                self.assertEqual(workflow["26"]["inputs"]["guidance"], 4.0)
                self.assertEqual(workflow["9"]["inputs"]["filename_prefix"], f"i2i-flux2-dev-{suffix}")

    def test_configs_and_meta_are_visible(self):
        meta = json.loads(META.read_text())
        for prefix in ("t2i", "i2i"):
            for suffix in VARIANTS:
                with self.subTest(prefix=prefix, suffix=suffix):
                    filename = f"{prefix}_flux2_dev_{suffix}.json"
                    config = json.loads((CONFIG_DIR / filename).read_text())
                    fields = {item["key"]: item for item in config["fields"]}
                    entry = meta[filename]

                    self.assertEqual(config["workflow"], filename)
                    self.assertEqual(fields["48::steps"]["max"], 50)
                    self.assertFalse(entry["shared"])
                    self.assertEqual(entry["source"], "DGX Spark")
                    self.assertEqual(entry["source_path"], str(WORKFLOW_DIR / filename))
                    if prefix == "i2i":
                        self.assertEqual(fields["40::image"]["type"], "image")
                        self.assertIn("图生图", entry["tags"])
                    else:
                        self.assertIn("文生图", entry["tags"])


if __name__ == "__main__":
    unittest.main()
