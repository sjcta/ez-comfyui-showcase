from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class MobileAgentUiContractTests(unittest.TestCase):
    def test_mobile_agent_module_is_loaded(self):
        loader = (ROOT / "static/js/module_loader.js").read_text()

        self.assertIn("/modules/mobile_agent/mobile-agent.js?v=", loader)
        self.assertIn("static/css/mobile-agent.css?v=", loader)
        self.assertLess(loader.index("/modules/generate.js?v="), loader.index("/modules/mobile_agent/mobile-agent.js?v="))

    def test_mobile_agent_root_exists(self):
        html = (ROOT / "static/index.html").read_text()

        self.assertIn('id="mobileAgentRoot"', html)
        self.assertIn('class="mobile-agent"', html)

    def test_mobile_agent_module_renders_core_states(self):
        js = (ROOT / "static/js/modules/mobile_agent/mobile-agent.js").read_text()

        self.assertIn("function renderHome", js)
        self.assertIn("function renderVoice", js)
        self.assertIn("function renderConfirm", js)
        self.assertIn("function renderGenerating", js)
        self.assertIn("function submitUnderstand", js)
        self.assertIn("/api/mobile-agent/understand", js)
        self.assertIn("/api/mobile-agent/transcribe", js)
        self.assertIn("CW.mobileAgent", js)
        self.assertIn("CW.icon('send'", js)
        self.assertIn("CW.icon('mic'", js)

    def test_mobile_agent_css_is_mobile_first_and_scoped(self):
        css = (ROOT / "static/css/mobile-agent.css").read_text()

        self.assertIn(".mobile-agent", css)
        self.assertIn(".mobile-agent-panel", css)
        self.assertIn(".mobile-agent-input-row", css)
        self.assertIn("@media (max-width: 700px)", css)
        self.assertIn("height: calc(var(--vh, 1vh) * 100", css)
        self.assertIn("overflow-x: hidden", css)


if __name__ == "__main__":
    unittest.main()
