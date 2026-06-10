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
            "sysLlmVisionEnabled",
            "sysDetectorEnabled",
            "sysPromptSignalsEnabled",
            "sysPromptContextEnabled",
            "sysDetectorThreshold",
            "sysPairedBreastThreshold",
            "sysButtocksThreshold",
            "sysWeakBreastPromptThreshold",
            "三路组合：人工审查最高优先级",
            "LLM 视觉或提示词任一路命中即保护",
            "manual-admin",
            "sysPromptPatternStrongNude",
            "sysPromptPatternViolence",
            "sysPromptPatternObsceneGesture",
        ):
            self.assertIn(token, auth_js)

        css = (ROOT / "static/css/style.css").read_text("utf-8")
        self.assertIn(".system-settings-modal", css)
        self.assertIn(".system-settings-grid", css)
        self.assertIn(".system-settings-switch", css)
        self.assertIn(".system-settings-note", css)

    def test_system_settings_modal_has_llm_api_controls(self):
        auth_js = (ROOT / "static/js/modules/auth.js").read_text("utf-8")
        for token in (
            "sysLlmApiEnabled",
            "sysLlmApiBaseUrl",
            "sysLlmApiModel",
            "sysLlmApiKey",
            "sysLlmApiTimeout",
            "sysLlmApiProfile",
            "applySystemLlmProfile",
            "system-settings-profile-row",
            "testLlmApiSettings",
            "/api/system-settings/llm/test",
            "LLM / 图片反推 API",
        ):
            self.assertIn(token, auth_js)

    def test_system_settings_modal_uses_tabs_and_stable_llm_test_status(self):
        auth_js = (ROOT / "static/js/modules/auth.js").read_text("utf-8")
        css = (ROOT / "static/css/style.css").read_text("utf-8")

        for token in (
            "system-settings-tabs",
            "data-system-settings-tab=\"llm\"",
            "data-system-settings-tab=\"protection\"",
            "data-system-settings-tab=\"patterns\"",
            "data-system-settings-panel=\"llm\"",
            "setSystemSettingsTab",
            "system-settings-test-row",
            "system-settings-test-status",
            "system-settings-profile-hint",
            "CW.icon('server')",
        ):
            self.assertIn(token, auth_js)

        self.assertNotIn("CW.icon('activity')", auth_js)
        self.assertIn(".system-settings-tabs", css)
        self.assertIn(".system-settings-panel", css)
        self.assertIn(".system-settings-profile-row", css)
        self.assertIn(".system-settings-test-status", css)


if __name__ == "__main__":
    unittest.main()
