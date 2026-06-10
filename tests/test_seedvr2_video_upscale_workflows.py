import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / "data/workflows/DGX Spark"
CONFIG_DIR = ROOT / "data/wf_configs"
META = ROOT / "data/wf_meta.json"


class SeedVR2VideoUpscaleWorkflowTests(unittest.TestCase):
    def _load(self, name):
        return json.loads((WORKFLOW_DIR / name).read_text())

    def test_video_workflows_use_official_video_chain(self):
        for name, resolution in {
            "SeedVR2_video_upscale_2k.json": 2048,
            "SeedVR2_video_upscale_4k.json": 4096,
        }.items():
            workflow = self._load(name)
            self.assertEqual(workflow["21"]["class_type"], "LoadVideo")
            self.assertEqual(workflow["22"]["class_type"], "GetVideoComponents")
            self.assertEqual(workflow["10"]["class_type"], "SeedVR2VideoUpscaler")
            self.assertEqual(workflow["24"]["class_type"], "CreateVideo")
            self.assertEqual(workflow["23"]["class_type"], "SaveVideo")
            self.assertEqual(workflow["10"]["inputs"]["image"], ["22", 0])
            self.assertEqual(workflow["24"]["inputs"]["images"], ["10", 0])
            self.assertEqual(workflow["24"]["inputs"]["audio"], ["22", 1])
            self.assertEqual(workflow["24"]["inputs"]["fps"], ["22", 2])
            self.assertEqual(workflow["23"]["inputs"]["video"], ["24", 0])
            self.assertEqual(workflow["10"]["inputs"]["resolution"], resolution)

    def test_video_configs_expose_video_upload(self):
        for name in ("SeedVR2_video_upscale_2k.json", "SeedVR2_video_upscale_4k.json"):
            config = json.loads((CONFIG_DIR / name).read_text())
            fields = {item["key"]: item for item in config["fields"]}
            self.assertEqual(config["workflow"], name)
            self.assertEqual(fields["21::file"]["type"], "video")
            self.assertEqual(fields["21::file"]["zone"], "user_input")
            self.assertEqual(fields["10::resolution"]["type"], "number")
            self.assertEqual(fields["10::batch_size"]["label"], "批处理帧数")
            self.assertTrue(fields["10::batch_size"]["visible"])

    def test_image_seedvr2_internal_batch_fields_are_hidden(self):
        expectations = {
            "SeedVR2_upscale_2k.json": ("10::batch_size", "10::uniform_batch_size"),
            "SeedVR2_upscale_4k.json": ("10::batch_size", "10::uniform_batch_size"),
            "i2i-Qwen-Rapid-seedVR2-4k.json": ("92::batch_size", "92::uniform_batch_size"),
            "i2i-Qwen-SeedVR2.json": ("92::batch_size", "92::uniform_batch_size"),
            "t2i-z-image-seedvr4k.json": ("73::batch_size", "73::uniform_batch_size"),
            "t2i_nunchaku_seedvr4k.json": ("59::batch_size", "59::uniform_batch_size"),
        }
        for name, keys in expectations.items():
            with self.subTest(config=name):
                config = json.loads((CONFIG_DIR / name).read_text())
                fields = {item["key"]: item for item in config["fields"]}
                for key in keys:
                    self.assertEqual(fields[key]["zone"], "hidden")
                    self.assertFalse(fields[key]["visible"])
                    self.assertTrue(fields[key]["label"].startswith("SeedVR2 内部批量"))

    def test_meta_registers_video_upscale_entries(self):
        meta = json.loads(META.read_text())
        for name in ("SeedVR2_video_upscale_2k.json", "SeedVR2_video_upscale_4k.json"):
            entry = meta[name]
            self.assertIn("视频放大", entry["tags"])
            self.assertTrue(entry["shared"])
            self.assertEqual(entry["source"], "DGX Spark")


if __name__ == "__main__":
    unittest.main()
