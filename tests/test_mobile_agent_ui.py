from pathlib import Path
import subprocess
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

        self.assertIn('<main class="mobile-agent hidden" id="mobileAgentRoot" aria-label="移动端智能创作入口"></main>', html)

    def test_mobile_agent_module_renders_core_states(self):
        js = (ROOT / "static/js/modules/mobile_agent/mobile-agent.js").read_text()

        self.assertIn("function renderHome", js)
        self.assertIn("function renderVoice", js)
        self.assertIn("function renderConfirm", js)
        self.assertIn("function renderGenerating", js)
        self.assertIn("function renderConversation", js)
        self.assertIn("function submitUnderstand", js)
        self.assertIn("function openMobileAgent", js)
        self.assertIn("mobile-agent-chat", js)
        self.assertIn("mobile-agent-confirm-card", js)
        self.assertIn("mobile-agent-result-card", js)
        self.assertIn("mobile-agent-confirm-main", js)
        self.assertIn("mobile-agent-option-block", js)
        self.assertIn("mobile-agent-workflow-status", js)
        self.assertIn("/api/mobile-agent/understand", js)
        self.assertIn("/api/mobile-agent/transcribe", js)
        self.assertIn("CW.mobileAgent", js)
        self.assertIn("function icon", js)
        self.assertIn("icon('send'", js)
        self.assertIn("icon('mic'", js)
        self.assertNotIn("CW.icon('send'", js)
        self.assertNotIn("CW.icon('mic'", js)

    def test_generate_handoff_calls_existing_generate_api(self):
        js = (ROOT / "static/js/modules/mobile_agent/mobile-agent.js").read_text()

        self.assertIn("function submitGenerate", js)
        self.assertIn("/api/generate", js)
        self.assertIn("resolved_workflow", js)
        self.assertIn("field_values", js)
        self.assertIn("width", js)
        self.assertIn("height", js)
        self.assertIn("handleJobUpdate", js)
        self.assertIn("getConversationContext", js)

    def test_mobile_agent_executable_behavior(self):
        result = subprocess.run(
            ["node", "tests/js/mobile_agent_shell.test.js"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_mobile_agent_css_is_mobile_first_and_scoped(self):
        css = (ROOT / "static/css/mobile-agent.css").read_text()

        self.assertIn(".mobile-agent", css)
        self.assertIn(".mobile-agent-panel", css)
        self.assertIn(".mobile-agent-chat", css)
        self.assertIn(".mobile-agent-message-user", css)
        self.assertIn(".mobile-agent-result-card", css)
        self.assertIn(".mobile-agent-input-row", css)
        self.assertIn("--mobile-motion-duration: 300ms", css)
        self.assertIn("grid-template-columns var(--mobile-motion-duration) ease", css)
        self.assertIn("transform var(--mobile-motion-duration) ease", css)
        self.assertIn("@media (max-width: 700px)", css)
        self.assertIn("height: calc(var(--vh, 1vh) * 100", css)
        self.assertIn("overflow-x: hidden", css)
        self.assertIn("position: fixed", css)


if __name__ == "__main__":
    unittest.main()
