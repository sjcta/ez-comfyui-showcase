from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PromptVoiceInputTests(unittest.TestCase):
    def test_prompt_voice_button_and_api_are_wired(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()
        app_py = (ROOT / "app.py").read_text()
        css = (ROOT / "static/css/style.css").read_text()
        sprite = (ROOT / "static/icons/sprite.svg").read_text()

        self.assertIn('id="promptVoiceBtn"', generate_js)
        self.assertIn('onclick="CW.togglePromptVoiceInput()"', generate_js)
        self.assertIn("'</label>' + promptVoiceBtnHtml + promptFullscreenBtnHtml", generate_js)
        self.assertIn("function togglePromptVoiceInput()", generate_js)
        self.assertIn("MediaRecorder", generate_js)
        self.assertIn("/api/speech/transcribe", generate_js)
        self.assertIn("window.CW.togglePromptVoiceInput = togglePromptVoiceInput", generate_js)
        self.assertIn("@app.post(\"/api/speech/transcribe\")", app_py)
        self.assertIn("EZ_ASR_SERVICE_URL", app_py)
        self.assertIn(".prompt-tool-btn-voice", css)
        self.assertIn(".prompt-label-row .prompt-tool-btn-voice", css)
        self.assertIn("icon-mic", sprite)

    def test_optional_tts_reference_audio_is_supported(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()
        app_py = (ROOT / "app.py").read_text()
        config = (ROOT / "data/wf_configs/tts_qwen_tts.json").read_text()

        self.assertIn("required: f.required", generate_js)
        self.assertIn("if (!refVal && f.required !== false)", generate_js)
        self.assertIn('"key": "1::reference_audio"', config)
        self.assertIn('"required": false', config)
        self.assertIn('"key": "1::voice_preset"', config)
        self.assertIn('"Serena / 温暖温柔女声（中文）"', config)
        self.assertIn('"本地预设 Speaker（CustomVoice）"', config)
        self.assertIn('"本地参考音频克隆（Base）"', config)
        self.assertNotIn('"官方发音人（DashScope）"', config)
        self.assertIn('"key": "1::voice_input_mode"', config)
        self.assertIn('for k in ("options", "step", "min", "max", "role", "required")', app_py)


if __name__ == "__main__":
    unittest.main()
