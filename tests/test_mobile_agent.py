import unittest

from modules.mobile_agent import (
    DEFAULT_MOBILE_CREATOR_SETTINGS,
    IntentRouter,
    PromptCompiler,
    build_generate_fields,
    ratio_to_dimensions,
    build_agent_response,
)


class MobileAgentTests(unittest.TestCase):
    def test_text_without_media_routes_to_text_to_image(self):
        result = IntentRouter().classify("帮我出一张未来城市雨夜的照片")

        self.assertEqual(result["intent"], "text_to_image")
        self.assertGreaterEqual(result["confidence"], 0.8)
        self.assertEqual(result["reason"], "text_only_image_request")

    def test_video_words_do_not_route_to_v1_text_to_image(self):
        result = IntentRouter().classify("帮我把这张图动起来做成视频")

        self.assertEqual(result["intent"], "unsupported_video")
        self.assertLess(result["confidence"], 0.8)
        self.assertIn("视频", result["question"])

    def test_image_present_routes_to_deferred_image_edit(self):
        result = IntentRouter().classify("帮我把背景换成雨夜", has_image=True)

        self.assertEqual(result["intent"], "unsupported_image_edit")
        self.assertIn("图片编辑", result["question"])

    def test_prompt_compiler_removes_request_words_and_detects_ratio(self):
        compiled = PromptCompiler().compile("帮我出一张手机壁纸，未来城市雨夜，电影感")

        self.assertIn("未来城市雨夜", compiled["compiled_prompt"])
        self.assertNotIn("帮我", compiled["compiled_prompt"])
        self.assertEqual(compiled["aspect_ratio"], "9:16")
        self.assertEqual(compiled["style"], "cinematic")

    def test_ratio_to_dimensions_uses_mobile_creator_defaults(self):
        self.assertEqual(ratio_to_dimensions("9:16"), {"width": 720, "height": 1280})
        self.assertEqual(ratio_to_dimensions("1:1"), {"width": 1024, "height": 1024})

    def test_build_agent_response_uses_internal_workflow_alias(self):
        response = build_agent_response(
            text="帮我出一张切成片的西瓜",
            settings={**DEFAULT_MOBILE_CREATOR_SETTINGS, "default_text_to_image_workflow": "t2i-z-image.json"},
            workflow_available=True,
        )

        self.assertEqual(response["intent"], "text_to_image")
        self.assertEqual(response["workflow"], "default_text_to_image")
        self.assertEqual(response["resolved_workflow"], "t2i-z-image.json")
        self.assertFalse(response["needs_confirmation"])
        self.assertIn("compiled_prompt", response)
        self.assertIn("style", response["options"])
        self.assertIn("aspect_ratio", response["options"])

    def test_build_agent_response_handles_unavailable_workflow(self):
        response = build_agent_response(
            text="帮我出一张切成片的西瓜",
            settings={**DEFAULT_MOBILE_CREATOR_SETTINGS, "default_text_to_image_workflow": "missing.json"},
            workflow_available=False,
        )

        self.assertEqual(response["intent"], "text_to_image")
        self.assertTrue(response["needs_confirmation"])
        self.assertEqual(response["error_code"], "workflow_unavailable")

    def test_build_generate_fields_puts_prompt_into_prompt_like_field(self):
        fields = [
            {"node_id": "1", "field": "text", "label": "提示词", "class_type": "Text Multiline", "zone": "user_input"},
            {"node_id": "2", "field": "width", "label": "宽度", "class_type": "PrimitiveInt", "zone": "output"},
        ]

        result = build_generate_fields(fields, "未来城市雨夜")

        self.assertEqual(result, {"1::text": "未来城市雨夜"})

    def test_build_generate_fields_returns_empty_when_no_prompt_field_exists(self):
        fields = [{"node_id": "2", "field": "width", "label": "宽度", "class_type": "PrimitiveInt"}]

        self.assertEqual(build_generate_fields(fields, "未来城市雨夜"), {})


if __name__ == "__main__":
    unittest.main()
