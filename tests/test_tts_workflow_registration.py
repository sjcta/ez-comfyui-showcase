import json
from pathlib import Path
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
TTS_WORKFLOWS = {
    "tts_qwen_tts.json": {
        "name": "千问3-TTS",
        "engine": "qwen_tts",
        "service_url": "http://127.0.0.1:18210/tts",
        "language_options": ["Auto / 自动", "English / 英文", "Chinese / 中文", "German / 德语", "Italian / 意大利语", "Portuguese / 葡萄牙语", "Spanish / 西班牙语", "Japanese / 日语", "Korean / 韩语", "French / 法语", "Russian / 俄语"],
        "default_voice_mode": "本地预设 Speaker（CustomVoice）",
        "default_voice": "Serena / 温暖温柔女声（中文）",
        "voice_label": "Speaker / 预设发音人（本地 CustomVoice）",
        "voice_options": QWEN_CUSTOM_VOICES,
        "voice_mode_visible": True,
        "voice_mode_options": ["本地预设 Speaker（CustomVoice）", "本地参考音频克隆（Base）"],
        "voice_preset_visible": True,
        "voice_description_visible": True,
    },
    "tts_voxcpm2.json": {
        "name": "VoxCPM2 TTS",
        "engine": "voxcpm2",
        "service_url": "http://127.0.0.1:18212/tts",
        "language_options": ["auto", "Arabic", "Burmese", "Chinese", "Danish", "Dutch", "English", "Finnish", "French", "German", "Greek", "Hebrew", "Hindi", "Indonesian", "Italian", "Japanese", "Khmer", "Korean", "Lao", "Malay", "Norwegian", "Polish", "Portuguese", "Russian", "Spanish", "Swahili", "Swedish", "Tagalog", "Thai", "Turkish", "Vietnamese", "四川话", "粤语", "吴语", "东北话", "河南话", "陕西话", "山东话", "天津话", "闽南话"],
        "default_voice_mode": "声音设计（无参考音频）",
        "default_voice": "VoxCPM2文字描述音色（0样本）",
        "voice_label": "VoxCPM2 音色来源",
        "voice_options": ["VoxCPM2文字描述音色（0样本）", "VoxCPM2无参考原生生成", "VoxCPM2参考音频克隆（中文样本）", "VoxCPM2参考音频克隆（英文样本）", "自定义参考音频"],
        "voice_mode_visible": True,
        "voice_mode_options": ["声音设计（无参考音频）", "可控克隆（参考音频+控制指令）", "极致克隆（参考音频+逐字稿）"],
        "voice_preset_visible": False,
        "voice_description_visible": True,
        "voxcpm2_demo_aligned": True,
    },
    "tts_indextts2.json": {
        "name": "Index TTS 2",
        "engine": "indextts2",
        "service_url": "http://127.0.0.1:18213/tts",
        "language_options": ["auto", "Chinese", "English"],
        "default_voice_mode": "上传参考音频克隆",
        "default_voice": "IndexTTS2参考音频克隆（中文样本）",
        "voice_label": "IndexTTS2 默认参考样本",
        "voice_options": ["IndexTTS2参考音频克隆（中文样本）", "IndexTTS2参考音频克隆（英文样本）", "自定义参考音频"],
        "voice_mode_visible": False,
        "voice_preset_visible": True,
        "voice_description_visible": False,
    },
    "tts_higgs_audio_v3.json": {
        "name": "Higgs Audio v3 TTS",
        "engine": "higgs_audio_v3",
        "service_url": "http://127.0.0.1:18214/tts",
        "language_options_min_count": 103,
        "language_options_contains": ["Afrikaans", "Chinese", "English", "Welsh"],
        "default_voice_mode": "原生默认",
        "default_voice": "Higgs Zero-shot原生生成",
        "voice_label": "Higgs 音色来源",
        "voice_options": ["Higgs Zero-shot原生生成", "Higgs参考音频克隆（中文样本）", "Higgs参考音频克隆（英文样本）", "自定义参考音频"],
        "voice_mode_visible": True,
        "voice_mode_options": ["原生默认", "上传参考音频克隆"],
        "voice_preset_visible": False,
        "voice_description_visible": False,
    },
}


class TtsWorkflowRegistrationTests(unittest.TestCase):
    def test_tts_workflows_are_registered_with_dedicated_audio_bridge_services(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()
        meta = json.loads((ROOT / "data/wf_meta.json").read_text())

        if "tts_ez_audio_bridge.json" in meta:
            self.assertFalse(meta["tts_ez_audio_bridge.json"]["shared"])

        for filename, spec in TTS_WORKFLOWS.items():
            with self.subTest(filename=filename):
                workflow_path = ROOT / "data/workflows/DGX Spark" / filename
                config_path = ROOT / "data/wf_configs" / filename
                workflow = json.loads(workflow_path.read_text())
                config = json.loads(config_path.read_text())

                self.assertIn(filename, meta)
                self.assertEqual(meta[filename]["name"], spec["name"])
                self.assertIn("语音TTS", meta[filename]["tags"])
                self.assertTrue(meta[filename]["shared"])
                self.assertEqual(workflow["1"]["class_type"], "EZ_TTS_Service")
                self.assertEqual(workflow["1"]["inputs"]["engine"], spec["engine"])
                self.assertEqual(workflow["1"]["inputs"]["service_url"], spec["service_url"])
                self.assertEqual(workflow["1"]["inputs"]["voice_input_mode"], spec["default_voice_mode"])
                self.assertEqual(workflow["1"]["inputs"]["voice_preset"], spec["default_voice"])
                self.assertIn("voice_description", workflow["1"]["inputs"])
                self.assertEqual(workflow["1"]["inputs"]["seed"], 0)
                self.assertEqual(workflow["2"]["class_type"], "SaveAudio")
                self.assertEqual(workflow["2"]["inputs"]["audio"], ["1", 0])

                fields = {item["key"]: item for item in config["fields"]}
                self.assertEqual(fields["1::text"]["zone"], "user_input")
                if "language_options" in spec:
                    self.assertEqual(fields["1::language"]["options"], spec["language_options"])
                else:
                    self.assertGreaterEqual(len(fields["1::language"]["options"]), spec["language_options_min_count"])
                    for option in spec["language_options_contains"]:
                        self.assertIn(option, fields["1::language"]["options"])
                self.assertEqual(fields["1::voice_input_mode"]["visible"], spec["voice_mode_visible"])
                if spec.get("voice_mode_options"):
                    self.assertEqual(fields["1::voice_input_mode"]["options"], spec["voice_mode_options"])
                self.assertEqual(fields["1::voice_preset"]["label"], spec["voice_label"])
                self.assertEqual(fields["1::voice_preset"]["options"], spec["voice_options"])
                self.assertEqual(fields["1::voice_preset"]["visible"], spec["voice_preset_visible"])
                self.assertEqual(fields["1::voice_description"]["visible"], spec["voice_description_visible"])
                if filename == "tts_qwen_tts.json":
                    self.assertEqual(fields["1::text"]["label"], "Input Text / 输入文本")
                    self.assertEqual(fields["1::language"]["label"], "Select Text Language / 选择文本语言")
                    self.assertEqual(fields["1::voice_input_mode"]["label"], "音色来源")
                    self.assertEqual(fields["1::reference_audio"]["label"], "Reference Audio / 参考音频（Base 本地克隆，可选）")
                    self.assertEqual(workflow["1"]["inputs"]["voice_description"], "默认自然朗读（无额外风格）")
                    self.assertEqual(workflow["1"]["inputs"]["voice_style_custom"], "")
                    self.assertEqual(fields["1::voice_description"]["label"], "风格/语气预设（CustomVoice）")
                    self.assertEqual(fields["1::voice_description"]["type"], "select")
                    self.assertEqual(fields["1::voice_description"]["options"], QWEN_STYLE_PRESETS)
                    self.assertEqual(fields["1::voice_style_custom"]["label"], "自定义语气补充（可选）")
                    self.assertEqual(fields["1::voice_style_custom"]["type"], "textarea")
                    self.assertEqual(fields["1::reference_text"]["label"], "Reference Text / 参考音频逐字稿（可选，提升克隆）")
                    self.assertFalse(fields["1::temperature"]["visible"])
                    self.assertFalse(fields["1::top_p"]["visible"])
                    self.assertFalse(fields["1::speed"]["visible"])
                if spec.get("voxcpm2_demo_aligned"):
                    self.assertEqual(fields["1::voice_input_mode"]["label"], "功能模式（官方 Demo 三模式）")
                    self.assertEqual(fields["1::voice_description"]["label"], "Control Instruction（声音/情绪/方言控制）")
                    self.assertEqual(fields["1::reference_text"]["label"], "参考音频逐字稿（极致克隆）")
                    self.assertEqual(workflow["1"]["inputs"]["inference_timesteps"], 30)
                    self.assertEqual(fields["1::inference_timesteps"]["label"], "推理步数（最高音质=30）")
                    self.assertTrue(fields["1::cfg_value"]["visible"])
                    self.assertTrue(fields["1::inference_timesteps"]["visible"])
                    self.assertFalse(fields["1::temperature"]["visible"])
                    self.assertFalse(fields["1::top_p"]["visible"])
                    self.assertFalse(fields["1::speed"]["visible"])
                self.assertFalse(fields["1::reference_audio"]["required"])
                self.assertEqual(fields["1::engine"]["zone"], "hidden")
                self.assertFalse(fields["1::engine"]["visible"])
                self.assertEqual(fields["1::service_url"]["zone"], "hidden")
                self.assertEqual(fields["1::seed"]["type"], "seed")
                self.assertEqual(fields["1::seed"]["max"], 2147483647)

        self.assertIn("function _isTtsPromptWorkflow(fields)", generate_js)
        self.assertIn("function _initTtsVoiceInputModeControl()", generate_js)
        self.assertIn("voice_description", generate_js)
        self.assertIn("voice_style_custom", generate_js)
        self.assertIn("qwen tts|voxcpm2 tts|indextts2 tts|higgs audio", generate_js)
        self.assertIn("return !_isTtsPromptWorkflow(fields);", generate_js)


if __name__ == "__main__":
    unittest.main()
