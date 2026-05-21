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
        self.assertEqual(workflow["5"]["class_type"], "Qwen3_VQA")
        self.assertEqual(workflow["5"]["inputs"]["image"], ["4", 0])
        self.assertEqual(workflow["5"]["inputs"]["model"], "Qwen3-VL-4B-Instruct")
        self.assertEqual(workflow["5"]["inputs"]["quantization"], "4bit")
        self.assertIn("structured_prompt_en", workflow["5"]["inputs"]["text"])
        self.assertIn("必须包含以下四个顶层键", workflow["5"]["inputs"]["text"])
        self.assertTrue(workflow["5"]["inputs"]["keep_model_loaded"])
        self.assertEqual(workflow["6"]["class_type"], "ShowText|pysssss")

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

    def test_extract_interrogate_result_parses_bilingual_qwen_json(self):
        entry = {
            "outputs": {
                "3": {"text": ["car, road, mountain"]},
                "6": {
                    "text": [
                        [
                            """{
                          "keyword_prompt": "未来主义超跑，蜿蜒山路，金色日落，薄雾山峦",
                          "english_prompt": "futuristic hypercar, winding mountain road, golden sunset, misty mountains",
                          "structured_prompt": {
                            "subject": "未来主义超跑",
                            "scene": "蜿蜒山路，薄雾山峦",
                            "lighting": "金色日落光"
                          },
                          "structured_prompt_en": {
                            "subject": "futuristic hypercar",
                            "scene": "winding mountain road, misty mountains",
                            "lighting": "golden sunset light"
                          }
                        }"""
                        ]
                    ]
                },
            }
        }

        result = extract_interrogate_result(entry)

        self.assertEqual(result["prompt"], "未来主义超跑，蜿蜒山路，金色日落，薄雾山峦")
        self.assertEqual(result["prompt_zh"], "未来主义超跑，蜿蜒山路，金色日落，薄雾山峦")
        self.assertEqual(result["prompt_en"], "futuristic hypercar, winding mountain road, golden sunset, misty mountains")
        self.assertIn('"subject": "未来主义超跑"', result["structured_prompt_json"])
        self.assertIn('"subject": "futuristic hypercar"', result["structured_prompt_json_en"])

    def test_extract_interrogate_result_builds_plain_prompt_from_richer_json(self):
        entry = {
            "outputs": {
                "3": {"text": ["1girl, neon, portrait"]},
                "6": {
                    "text": [
                        """{
                          "keyword_prompt": "霓虹灯效女性肖像",
                          "english_prompt": "neon female portrait",
                          "structured_prompt": {
                            "subject": "女性面部特写",
                            "action": "凝视镜头",
                            "scene": "室内",
                            "composition": "正面特写，聚焦面部",
                            "lighting": "粉红色霓虹灯光照射，冷色调背景",
                            "style": "赛博朋克风格",
                            "color_palette": "粉红色与青蓝色调",
                            "important_details": [
                              "发饰为发光珊瑚状装饰",
                              "耳环为发光椭圆形",
                              "颈间缠绕发光灯串"
                            ]
                          },
                          "structured_prompt_en": {
                            "subject": "female facial close-up",
                            "action": "gazing at the camera",
                            "composition": "front-facing close-up, face in sharp focus",
                            "lighting": "pink neon lighting, cool-toned background",
                            "style": "cyberpunk style",
                            "important_details": [
                              "glowing coral-like hair ornament",
                              "glowing oval earrings"
                            ]
                          }
                        }"""
                    ]
                },
            }
        }

        result = extract_interrogate_result(entry)

        self.assertIn("女性面部特写", result["prompt"])
        self.assertIn("粉红色霓虹灯光照射", result["prompt"])
        self.assertIn("发饰为发光珊瑚状装饰", result["prompt"])
        self.assertNotEqual(result["prompt"], "霓虹灯效女性肖像")
        self.assertIn("female facial close-up", result["prompt_en"])
        self.assertIn("pink neon lighting", result["prompt_en"])

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
