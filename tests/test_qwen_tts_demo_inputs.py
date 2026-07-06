import json
from pathlib import Path
import sys
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
QWEN_CUSTOM_VOICES = [
    "Vivian / 明亮年轻女声（中文）",
    "Serena / 温暖温柔女声（中文）",
    "Uncle_Fu / 低沉成熟男声（中文）",
    "Dylan / 北京青年男声（中文北京话）",
    "Eric / 成都男声（四川话）",
    "Ryan / 节奏感男声（英文）",
    "Aiden / 美式阳光男声（英文）",
    "Ono_Anna / 轻快日语女声（日语）",
    "Sohee / 温暖韩语女声（韩语）",
]
QWEN_STYLE_PRESETS = [
    "默认自然朗读（无额外风格）",
    "温柔亲切，语速适中。",
    "活泼轻快，有感染力。",
    "沉稳专业，适合知识讲解。",
    "新闻播报，清晰坚定。",
    "旁白解说，冷静克制。",
    "宣传介绍，热情自信。",
    "口语聊天，轻松自然。",
    "睡前故事，柔和慢速。",
    "角色对白，情绪自然，有表演感。",
    "紧张悬疑，压低声线，节奏稍慢。",
    "开心愉悦，语调上扬。",
    "安抚疗愈，声音柔和稳定。",
]


class QwenTtsDemoInputTests(unittest.TestCase):
    def test_qwen_tts_form_matches_demo_language_shape(self):
        workflow = json.loads((ROOT / "data/workflows/DGX Spark/tts_qwen_tts.json").read_text())
        config = json.loads((ROOT / "data/wf_configs/tts_qwen_tts.json").read_text())
        fields = {item["key"]: item for item in config["fields"]}

        self.assertEqual(workflow["1"]["inputs"]["text"], "你好，我是通义千问，很高兴认识你。")
        self.assertEqual(workflow["1"]["inputs"]["language"], "Auto / 自动")
        self.assertEqual(workflow["1"]["inputs"]["voice_input_mode"], "本地预设 Speaker（CustomVoice）")
        self.assertEqual(workflow["1"]["inputs"]["voice_preset"], "Serena / 温暖温柔女声（中文）")
        self.assertEqual(workflow["1"]["inputs"]["voice_description"], "默认自然朗读（无额外风格）")
        self.assertEqual(workflow["1"]["inputs"]["voice_style_custom"], "")
        self.assertEqual(fields["1::text"]["label"], "Input Text / 输入文本")
        self.assertEqual(fields["1::language"]["label"], "Select Text Language / 选择文本语言")
        self.assertEqual(
            fields["1::language"]["options"],
            [
                "Auto / 自动",
                "English / 英文",
                "Chinese / 中文",
                "German / 德语",
                "Italian / 意大利语",
                "Portuguese / 葡萄牙语",
                "Spanish / 西班牙语",
                "Japanese / 日语",
                "Korean / 韩语",
                "French / 法语",
                "Russian / 俄语",
            ],
        )
        self.assertEqual(fields["1::voice_input_mode"]["label"], "音色来源")
        self.assertEqual(fields["1::voice_input_mode"]["options"], ["本地预设 Speaker（CustomVoice）", "本地参考音频克隆（Base）"])
        self.assertEqual(fields["1::voice_preset"]["label"], "Speaker / 预设发音人（本地 CustomVoice）")
        self.assertEqual(fields["1::voice_preset"]["options"], QWEN_CUSTOM_VOICES)
        self.assertEqual(fields["1::voice_description"]["label"], "风格/语气预设（CustomVoice）")
        self.assertEqual(fields["1::voice_description"]["type"], "select")
        self.assertEqual(fields["1::voice_description"]["options"], QWEN_STYLE_PRESETS)
        self.assertEqual(fields["1::voice_style_custom"]["label"], "自定义语气补充（可选）")
        self.assertEqual(fields["1::voice_style_custom"]["type"], "textarea")
        self.assertFalse(fields["1::temperature"]["visible"])
        self.assertFalse(fields["1::top_p"]["visible"])
        self.assertFalse(fields["1::speed"]["visible"])
        self.assertTrue(fields["1::seed"]["visible"])
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()
        self.assertIn("return 'voice';", generate_js)
        self.assertIn('[data-key-wrap$="::voice_preset"]', generate_js)
        self.assertIn('[data-key-wrap$="::voice_style_custom"]', generate_js)

    def test_qwen_tts_service_accepts_demo_style_aliases(self):
        sys.modules.setdefault("soundfile", types.SimpleNamespace(write=lambda *args, **kwargs: None))
        from deploy.services import ez_tts_service

        self.assertEqual(ez_tts_service._language_for_qwen("Japanese / 日语"), "Japanese")
        self.assertEqual(ez_tts_service._language_for_qwen("Auto / 自动"), "Chinese")
        self.assertTrue(ez_tts_service._qwen_uses_custom_voice({"voice_input_mode": "本地预设 Speaker（CustomVoice）"}))
        self.assertTrue(ez_tts_service._qwen_uses_custom_voice({"voice_input_mode": "官方发音人（DashScope）"}))
        self.assertFalse(ez_tts_service._qwen_uses_custom_voice({"voice_input_mode": "本地参考音频克隆（Base）"}))
        self.assertEqual(ez_tts_service._qwen_custom_voice_speaker_for_payload({"voice_preset": "Dylan / 北京-晓东"}), ("Dylan / 北京-晓东", "Dylan"))
        self.assertEqual(ez_tts_service._qwen_custom_voice_speaker_for_payload({"voice_preset": "Cherry / 芊悦"}), ("Cherry / 芊悦", "Serena"))
        self.assertIsNone(
            ez_tts_service._qwen_custom_voice_instruct(
                {"voice_description": "默认自然朗读（无额外风格）", "voice_style_custom": ""}
            )
        )
        self.assertEqual(
            ez_tts_service._qwen_custom_voice_instruct(
                {"voice_description": "新闻播报，清晰坚定。", "voice_style_custom": "语速稍快一点。"}
            ),
            "新闻播报，清晰坚定。 语速稍快一点。",
        )
        self.assertEqual(
            ez_tts_service._voice_preset_for_payload(
                {"voice_preset": "Chinese Reference / 中文默认参考样本"},
                "qwen_tts",
            ),
            "qwen_reference_zh",
        )
        self.assertEqual(
            ez_tts_service._voice_preset_for_payload(
                {"voice_preset": "Custom Reference Audio / 自定义参考音频"},
                "qwen_tts",
            ),
            "custom_reference",
        )
        with self.assertRaisesRegex(ValueError, "需要上传参考音频"):
            ez_tts_service._resolve_voice_reference(
                {
                    "voice_input_mode": "上传参考音频克隆（本地）",
                    "voice_preset": "Custom Reference Audio / 自定义参考音频",
                    "reference_audio": "",
                },
                "qwen_tts",
            )
        self.assertEqual(
            ez_tts_service._header_safe_value("Serena / 温暖温柔女声（中文）"),
            "Serena / %E6%B8%A9%E6%9A%96%E6%B8%A9%E6%9F%94%E5%A5%B3%E5%A3%B0%EF%BC%88%E4%B8%AD%E6%96%87%EF%BC%89",
        )


if __name__ == "__main__":
    unittest.main()
