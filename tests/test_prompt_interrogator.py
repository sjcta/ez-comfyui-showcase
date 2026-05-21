import unittest
import tempfile
from pathlib import Path

from modules.prompt_interrogator import (
    build_image_interrogate_workflow,
    extract_interrogate_result,
    prepare_interrogate_image,
)


class PromptInterrogatorTests(unittest.TestCase):
    def test_build_image_interrogate_workflow_replaces_image_filename(self):
        workflow = build_image_interrogate_workflow("u1/2026-05-20/ref.png")

        self.assertEqual(workflow["1"]["class_type"], "LoadImage")
        self.assertEqual(workflow["1"]["inputs"]["image"], "u1/2026-05-20/ref.png")
        self.assertEqual(workflow["2"]["class_type"], "WD14Tagger|pysssss")
        self.assertEqual(workflow["6"]["class_type"], "Florence2Run")

    def test_extract_interrogate_result_prefers_promptgen_with_wd14_fallback(self):
        entry = {
            "outputs": {
                "3": {"text": ["tag one, tag two"]},
                "7": {"text": ["a detailed prompt generated from image"]},
            }
        }

        result = extract_interrogate_result(entry)

        self.assertEqual(result["prompt"], "a detailed prompt generated from image")
        self.assertEqual(result["wd14_tags"], "tag one, tag two")
        self.assertEqual(result["promptgen"], "a detailed prompt generated from image")

    def test_prepare_interrogate_image_downscales_large_upload(self):
        try:
            from PIL import Image
        except Exception:
            self.skipTest("Pillow is not available")

        with tempfile.TemporaryDirectory() as td:
            input_dir = Path(td)
            src = input_dir / "u1" / "2026-05-21" / "large.png"
            src.parent.mkdir(parents=True)
            Image.new("RGB", (3200, 2400), (40, 80, 120)).save(src)

            result = prepare_interrogate_image("u1/2026-05-21/large.png", str(input_dir), max_side=1280)

            self.assertTrue(result["optimized"])
            self.assertEqual(result["original_width"], 3200)
            self.assertEqual(result["original_height"], 2400)
            self.assertLessEqual(max(result["width"], result["height"]), 1280)
            self.assertTrue((input_dir / result["filename"]).is_file())
            self.assertIn("/_interrogate/", result["filename"])

    def test_prepare_interrogate_image_keeps_small_upload(self):
        try:
            from PIL import Image
        except Exception:
            self.skipTest("Pillow is not available")

        with tempfile.TemporaryDirectory() as td:
            input_dir = Path(td)
            src = input_dir / "u1" / "2026-05-21" / "small.png"
            src.parent.mkdir(parents=True)
            Image.new("RGB", (512, 384), (40, 80, 120)).save(src)

            result = prepare_interrogate_image("u1/2026-05-21/small.png", str(input_dir), max_side=1280)

            self.assertFalse(result["optimized"])
            self.assertEqual(result["filename"], "u1/2026-05-21/small.png")
            self.assertEqual(result["width"], 512)
            self.assertEqual(result["height"], 384)


if __name__ == "__main__":
    unittest.main()
