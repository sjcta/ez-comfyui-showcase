from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SystemSettingsUiTests(unittest.TestCase):
    def test_admin_dropdown_exposes_system_settings(self):
        auth_js = (ROOT / "static/js/modules/auth.js").read_text("utf-8")
        self.assertIn("系统设置", auth_js)
        self.assertIn("CW.auth.showSystemSettings()", auth_js)
        self.assertIn("apiFetch(_withCacheBust(API + '/api/system-settings')", auth_js)
        self.assertIn("apiFetch(API + '/api/system-settings'", auth_js)

    def test_system_settings_modal_has_protection_controls(self):
        auth_js = (ROOT / "static/js/modules/auth.js").read_text("utf-8")
        for token in (
            "sysImageProtectionEnabled",
            "sysDetectorEnabled",
            "sysPromptSignalsEnabled",
            "sysPromptContextEnabled",
            "sysDetectorThreshold",
            "sysPairedBreastThreshold",
            "sysButtocksThreshold",
            "sysWeakBreastPromptThreshold",
            "sysPromptPatternStrongNude",
            "sysPromptPatternObsceneGesture",
        ):
            self.assertIn(token, auth_js)

        css = (ROOT / "static/css/style.css").read_text("utf-8")
        self.assertIn(".system-settings-modal", css)
        self.assertIn(".system-settings-grid", css)
        self.assertIn(".system-settings-switch", css)

    def test_system_settings_modal_has_mobile_llm_api_controls(self):
        auth_js = (ROOT / "static/js/modules/auth.js").read_text("utf-8")
        for token in (
            "移动端对话模型",
            "sysMobileLlmEnabled",
            "sysMobileLlmProvider",
            "sysMobileLlmBaseUrl",
            "sysMobileLlmModel",
            "sysMobileLlmApiKey",
            "sysMobileLlmGgufModel",
            "sysMobileLlmMmprojModel",
            "llm_base_url",
            "llm_model",
        ):
            self.assertIn(token, auth_js)


if __name__ == "__main__":
    unittest.main()
