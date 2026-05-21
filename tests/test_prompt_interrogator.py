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

    def test_extract_interrogate_result_prefers_promptgen_and_keeps_wd14_metadata(self):
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

    def test_extract_interrogate_result_removes_duplicate_caption_and_wrong_tag_tail(self):
        caption = (
            "A photograph of a futuristic sports car driving on a winding mountain road during sunrise or sunset. "
            "The car is positioned in the center of the image, with its sleek aerodynamic design highlighted by warm golden light."
        )
        duplicate = (
            "In this image, the car is positioned at the center of the frame, with its sleek and aerodynamic design "
            "highlighted by the warm, golden light of the sunrise or sunset."
        )
        wrong_tags = "1girl, solo, wings, outdoors, sky, wheel, no people, driving, mountain, road, fog"
        entry = {
            "outputs": {
                "3": {"text": [wrong_tags]},
                "7": {"text": [caption + "\n\n" + duplicate + "\n\n" + wrong_tags]},
            }
        }

        result = extract_interrogate_result(entry)

        self.assertEqual(result["prompt"], caption)
        self.assertNotIn("1girl", result["prompt"])
        self.assertNotIn("wings", result["prompt"])
        self.assertEqual(result["wd14_tags"], wrong_tags)

    def test_extract_interrogate_result_does_not_use_wd14_tag_line_as_prompt(self):
        entry = {
            "outputs": {
                "3": {"text": ["1girl, solo, wings, outdoors, sky, wheel, no people, driving, mountain, road, fog"]},
                "7": {"text": [""]},
            }
        }

        result = extract_interrogate_result(entry)

        self.assertEqual(result["prompt"], "")
        self.assertEqual(result["promptgen"], "")
        self.assertIn("1girl", result["wd14_tags"])

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
