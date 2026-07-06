import unittest
import os
import sys
import tempfile
import types
from pathlib import Path

sys.modules.setdefault("soundfile", types.SimpleNamespace(write=lambda *args, **kwargs: None))
from deploy.services import ez_tts_service


class VoxCPM2DialectControlTests(unittest.TestCase):
    def test_wu_dialect_is_compiled_into_voxcpm2_control_text(self):
        text = ez_tts_service._voxcpm2_generation_text(
            {
                "language": "吴语",
                "text": "背景墙面由深灰色混凝土构成。",
            },
            "A young woman, gentle and sweet voice",
        )

        self.assertTrue(text.startswith("("), text)
        self.assertIn("A young woman, gentle and sweet voice", text)
        self.assertIn("吴语", text)
        self.assertNotIn("speak in", text)
        self.assertIn("背景墙面由深灰色混凝土构成。", text)

    def test_wu_dialect_is_applied_without_voice_description(self):
        text = ez_tts_service._voxcpm2_generation_text(
            {
                "language": "吴语",
                "text": "你好，欢迎使用本地语音合成。",
            },
            None,
        )

        self.assertEqual(
            text,
            "(吴语)你好，欢迎使用本地语音合成。",
        )

    def test_northeast_dialect_uses_simple_official_control_style(self):
        text = ez_tts_service._voxcpm2_generation_text(
            {
                "language": "东北话",
                "text": "你搁这整啥玩意儿呢？",
            },
            None,
        )

        self.assertEqual(text, "(东北话)你搁这整啥玩意儿呢？")

    def test_regular_chinese_does_not_add_dialect_control(self):
        text = ez_tts_service._voxcpm2_generation_text(
            {
                "language": "Chinese",
                "text": "你好，欢迎使用本地语音合成。",
            },
            None,
        )

        self.assertEqual(text, "你好，欢迎使用本地语音合成。")

    def test_reference_mode_reference_text_does_not_enable_hifi_prompt_mode(self):
        self.assertFalse(
            ez_tts_service._voxcpm2_should_use_hifi_prompt(
                {"language": "吴语", "voice_input_mode": "可控克隆（参考音频+控制指令）"},
                "参考音频逐字稿",
            )
        )

    def test_ultimate_mode_reference_text_uses_hifi_prompt_mode(self):
        self.assertTrue(
            ez_tts_service._voxcpm2_should_use_hifi_prompt(
                {"language": "Chinese", "voice_input_mode": "极致克隆（参考音频+逐字稿）"},
                "参考音频逐字稿",
            )
        )

    def test_hifi_generation_text_omits_control_instruction(self):
        text = ez_tts_service._voxcpm2_generation_text(
            {
                "language": "东北话",
                "text": "你搁这儿干啥呢？",
            },
            "年轻女性，声音自然清晰",
            include_control=False,
        )

        self.assertEqual(text, "你搁这儿干啥呢？")

    def test_reference_mode_missing_upload_does_not_fallback_to_default_voice(self):
        with self.assertRaises(FileNotFoundError) as ctx:
            ez_tts_service._resolve_voice_reference(
                {
                    "voice_input_mode": "上传参考音频克隆",
                    "voice_preset": "VoxCPM2文字描述音色（0样本）",
                    "reference_audio": "u1/2026-07-06/missing.wav",
                    "language": "Chinese",
                },
                "voxcpm2",
            )

        self.assertIn("uploaded reference audio not found or not synced", str(ctx.exception))
        self.assertIn("u1/2026-07-06/missing.wav", str(ctx.exception))

    def test_voxcpm2_controllable_clone_requires_uploaded_reference_audio(self):
        with self.assertRaises(ValueError) as ctx:
            ez_tts_service._resolve_voice_reference(
                {
                    "voice_input_mode": "可控克隆（参考音频+控制指令）",
                    "reference_audio": "",
                    "language": "Chinese",
                },
                "voxcpm2",
            )

        self.assertIn("需要上传参考音频", str(ctx.exception))

    def test_voxcpm2_ultimate_clone_requires_reference_transcript(self):
        old_input_dir = os.environ.get("EZ_COMFYUI_INPUT_DIR")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["EZ_COMFYUI_INPUT_DIR"] = tmp
                ref_rel = "u1/2026-07-06/ref.wav"
                ref_path = Path(tmp) / ref_rel
                ref_path.parent.mkdir(parents=True, exist_ok=True)
                ref_path.write_bytes(b"RIFF" + b"\0" * 2048)

                with self.assertRaises(ValueError) as ctx:
                    ez_tts_service._resolve_voice_reference(
                        {
                            "voice_input_mode": "极致克隆（参考音频+逐字稿）",
                            "reference_audio": ref_rel,
                            "reference_text": "",
                            "language": "Chinese",
                        },
                        "voxcpm2",
                    )
        finally:
            if old_input_dir is None:
                os.environ.pop("EZ_COMFYUI_INPUT_DIR", None)
            else:
                os.environ["EZ_COMFYUI_INPUT_DIR"] = old_input_dir

        self.assertIn("需要填写参考音频逐字稿", str(ctx.exception))

    def test_reference_mode_uses_uploaded_audio_when_synced(self):
        old_input_dir = os.environ.get("EZ_COMFYUI_INPUT_DIR")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.environ["EZ_COMFYUI_INPUT_DIR"] = tmp
                ref_rel = "u1/2026-07-06/ref.wav"
                ref_path = Path(tmp) / ref_rel
                ref_path.parent.mkdir(parents=True, exist_ok=True)
                ref_path.write_bytes(b"RIFF" + b"\0" * 2048)

                ref_audio, ref_text, preset, x_vector_only, description = ez_tts_service._resolve_voice_reference(
                    {
                        "voice_input_mode": "可控克隆（参考音频+控制指令）",
                        "voice_preset": "VoxCPM2文字描述音色（0样本）",
                        "reference_audio": ref_rel,
                        "reference_text": "",
                        "language": "Chinese",
                    },
                    "voxcpm2",
                )
        finally:
            if old_input_dir is None:
                os.environ.pop("EZ_COMFYUI_INPUT_DIR", None)
            else:
                os.environ["EZ_COMFYUI_INPUT_DIR"] = old_input_dir

        self.assertEqual(ref_audio, ref_path.resolve())
        self.assertIsNone(ref_text)
        self.assertEqual(preset, "custom_reference")
        self.assertTrue(x_vector_only)
        self.assertIsNone(description)


if __name__ == "__main__":
    unittest.main()
