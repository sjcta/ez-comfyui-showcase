import os
import tempfile
import textwrap
import unittest

from modules.mobile_agent import (
    DEFAULT_MOBILE_CREATOR_SETTINGS,
    IntentRouter,
    PromptCompiler,
    build_generate_fields,
    ratio_to_dimensions,
    build_agent_response,
)
from modules.speech_transcriber import SpeechTranscriber


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

    def test_followup_edit_after_result_routes_to_image_to_image(self):
        result = IntentRouter().classify(
            "改成赛博朋克风格",
            context={"last_result": {"image": "user1/2026-05-25/cat.png", "id": "job1"}},
        )

        self.assertEqual(result["intent"], "image_to_image")
        self.assertEqual(result["reason"], "followup_edit_last_result")
        self.assertGreaterEqual(result["confidence"], 0.8)

    def test_followup_edit_without_result_asks_for_context(self):
        result = IntentRouter().classify("改成赛博朋克风格")

        self.assertEqual(result["intent"], "clarify")
        self.assertEqual(result["reason"], "missing_edit_context")
        self.assertIn("上一张", result["question"])

    def test_prompt_compiler_removes_request_words_and_detects_ratio(self):
        compiled = PromptCompiler().compile("帮我出一张手机壁纸，未来城市雨夜，电影感")

        self.assertIn("未来城市雨夜", compiled["compiled_prompt"])
        self.assertNotIn("帮我", compiled["compiled_prompt"])
        self.assertEqual(compiled["aspect_ratio"], "9:16")
        self.assertEqual(compiled["style"], "cinematic")

    def test_prompt_compiler_invalid_explicit_ratio_falls_back_consistently(self):
        compiled = PromptCompiler().compile("帮我出一张未来城市雨夜", aspect_ratio="16:9")

        self.assertEqual(compiled["aspect_ratio"], "1:1")
        self.assertEqual(compiled["width"], 1024)
        self.assertEqual(compiled["height"], 1024)

    def test_ratio_to_dimensions_uses_mobile_creator_defaults(self):
        self.assertEqual(ratio_to_dimensions("9:16"), {"width": 720, "height": 1280})
        self.assertEqual(ratio_to_dimensions("1:1"), {"width": 1024, "height": 1024})

    def test_build_agent_response_uses_internal_workflow_alias(self):
        allowed_styles = ["realistic"]
        allowed_ratios = ["1:1", "3:4"]
        response = build_agent_response(
            text="帮我出一张手机壁纸，切成片的西瓜，电影感",
            settings={
                **DEFAULT_MOBILE_CREATOR_SETTINGS,
                "default_text_to_image_workflow": "t2i-z-image.json",
                "allowed_styles": allowed_styles,
                "allowed_ratios": allowed_ratios,
            },
            workflow_available=True,
        )

        self.assertEqual(response["intent"], "text_to_image")
        self.assertEqual(response["workflow"], "default_text_to_image")
        self.assertEqual(response["resolved_workflow"], "t2i-z-image.json")
        self.assertFalse(response["needs_confirmation"])
        self.assertIn("compiled_prompt", response)
        self.assertEqual(response["style"], "")
        self.assertEqual(response["aspect_ratio"], "1:1")
        self.assertEqual(response["options"]["style"], "")
        self.assertEqual(response["options"]["aspect_ratio"], "1:1")
        self.assertEqual(response["options"]["allowed_styles"], allowed_styles)
        self.assertEqual(response["options"]["allowed_ratios"], allowed_ratios)

    def test_default_mobile_creator_workflow_is_text_to_image(self):
        self.assertEqual(DEFAULT_MOBILE_CREATOR_SETTINGS["default_text_to_image_workflow"], "t2i-z-image.json")
        self.assertIn("default_image_to_image_workflow", DEFAULT_MOBILE_CREATOR_SETTINGS)

    def test_build_agent_response_uses_image_to_image_workflow_for_result_followup(self):
        response = build_agent_response(
            text="改成赛博朋克风格",
            settings={
                **DEFAULT_MOBILE_CREATOR_SETTINGS,
                "default_image_to_image_workflow": "i2i-test.json",
            },
            workflow_available=True,
            context={"last_result": {"image": "user1/2026-05-25/cat.png", "id": "job1"}},
        )

        self.assertEqual(response["intent"], "image_to_image")
        self.assertEqual(response["workflow"], "default_image_to_image")
        self.assertEqual(response["resolved_workflow"], "i2i-test.json")
        self.assertEqual(response["source_result"]["image"], "user1/2026-05-25/cat.png")
        self.assertFalse(response["needs_confirmation"])

    def test_image_to_image_followup_without_workflow_explains_configuration(self):
        response = build_agent_response(
            text="改成赛博朋克风格",
            settings=DEFAULT_MOBILE_CREATOR_SETTINGS,
            workflow_available=False,
            context={"last_result": {"image": "user1/2026-05-25/cat.png", "id": "job1"}},
        )

        self.assertEqual(response["intent"], "image_to_image")
        self.assertEqual(response["error_code"], "workflow_unavailable")
        self.assertIn("图生图工作流", response["question"])

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


class SpeechTranscriberTests(unittest.TestCase):
    def _fake_command(self, body: str) -> str:
        fd, path = tempfile.mkstemp(prefix="fake-whisper-", suffix=".py")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("#!/usr/bin/env python3\n")
            f.write(textwrap.dedent(body).lstrip())
        os.chmod(path, 0o755)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        return path

    def _speech_temp_dirs(self) -> list[str]:
        temp_root = tempfile.gettempdir()
        return [
            os.path.join(temp_root, name)
            for name in os.listdir(temp_root)
            if name.startswith("ez-speech-")
        ]

    def test_missing_speech_backend_returns_editable_failure(self):
        result = SpeechTranscriber(command="definitely-missing-whisper").transcribe_bytes(
            b"fake audio",
            filename="voice.webm",
            timeout_ms=200,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["provider"], "none")
        self.assertEqual(result["transcript"], "")
        self.assertEqual(result["error_code"], "speech_backend_unavailable")

    def test_empty_audio_returns_validation_failure(self):
        result = SpeechTranscriber(command="whisper").transcribe_bytes(b"", filename="voice.webm")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "empty_audio")

    def test_successful_transcription_reads_backend_txt(self):
        command = self._fake_command(
            """
            import pathlib
            import sys

            audio_path = pathlib.Path(sys.argv[1])
            output_dir = pathlib.Path(sys.argv[sys.argv.index("--output_dir") + 1])
            (output_dir / f"{audio_path.stem}.txt").write_text("hello mobile creator\\n", encoding="utf-8")
            """
        )

        result = SpeechTranscriber(command=command).transcribe_bytes(
            b"fake audio",
            filename="voice.webm",
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], command)
        self.assertEqual(result["transcript"], "hello mobile creator")
        self.assertEqual(result["error_code"], "")
        self.assertEqual(self._speech_temp_dirs(), [])

    def test_nonzero_backend_returns_transcribe_failed(self):
        command = self._fake_command(
            """
            import sys

            print("backend failed badly", file=sys.stderr)
            sys.exit(3)
            """
        )

        result = SpeechTranscriber(command=command).transcribe_bytes(
            b"fake audio",
            filename="voice.webm",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "speech_transcribe_failed")
        self.assertIn("backend failed badly", result["message"])
        self.assertEqual(self._speech_temp_dirs(), [])

    def test_backend_timeout_returns_speech_timeout(self):
        command = self._fake_command(
            """
            import time

            time.sleep(1)
            """
        )

        result = SpeechTranscriber(command=command).transcribe_bytes(
            b"fake audio",
            filename="voice.webm",
            timeout_ms=100,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "speech_timeout")
        self.assertEqual(self._speech_temp_dirs(), [])

    def test_malformed_long_filename_suffix_uses_safe_fallback(self):
        command = self._fake_command(
            """
            import pathlib
            import sys

            audio_path = pathlib.Path(sys.argv[1])
            if audio_path.suffix != ".webm":
                print(f"unsafe suffix: {audio_path.suffix}", file=sys.stderr)
                sys.exit(4)
            output_dir = pathlib.Path(sys.argv[sys.argv.index("--output_dir") + 1])
            (output_dir / f"{audio_path.stem}.txt").write_text("safe suffix", encoding="utf-8")
            """
        )

        result = SpeechTranscriber(command=command).transcribe_bytes(
            b"fake audio",
            filename="voice." + ("a" * 300),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["transcript"], "safe suffix")
        self.assertEqual(self._speech_temp_dirs(), [])


if __name__ == "__main__":
    unittest.main()
