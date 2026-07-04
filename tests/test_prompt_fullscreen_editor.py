from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PromptFullscreenEditorTests(unittest.TestCase):
    def test_quick_prompt_can_open_fullscreen_editor(self):
        generate_js = (ROOT / "static/js/modules/generate.js").read_text()
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn('id="promptFullscreenBtn"', generate_js)
        self.assertIn('onclick="CW.openPromptFullscreenEditor()"', generate_js)
        self.assertIn("function openPromptFullscreenEditor()", generate_js)
        self.assertIn("function closePromptFullscreenEditor()", generate_js)
        self.assertIn("prompt-fullscreen-editor", generate_js)
        self.assertIn("_setPromptInputValue(editor.value)", generate_js)
        self.assertIn("window.CW.openPromptFullscreenEditor = openPromptFullscreenEditor", generate_js)
        self.assertIn("window.CW.closePromptFullscreenEditor = closePromptFullscreenEditor", generate_js)

        self.assertIn(".prompt-fullscreen-btn", css)
        self.assertIn(".prompt-fullscreen-editor", css)
        self.assertIn(".prompt-fullscreen-panel", css)
        self.assertIn(".prompt-fullscreen-textarea", css)
        self.assertIn("height: 100dvh;", css)
        self.assertIn("body.prompt-fullscreen-open", css)


if __name__ == "__main__":
    unittest.main()
