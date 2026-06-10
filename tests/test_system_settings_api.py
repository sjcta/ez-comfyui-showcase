import os
import tempfile
import unittest

from PIL import Image
from fastapi import HTTPException

import app
from modules.llm_client import configure_llm_client, get_llm_client_settings
from modules.image_protection import ImageProtectionWorker, configure_image_protection


class SystemSettingsApiTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_settings_file = app.SYSTEM_SETTINGS_FILE
        self._old_runtime_settings = app.get_image_protection_settings()
        self._old_llm_settings = get_llm_client_settings()
        app.SYSTEM_SETTINGS_FILE = os.path.join(self._tmp.name, "system_settings.json")
        configure_image_protection(self._old_runtime_settings)
        configure_llm_client(self._old_llm_settings)

    def tearDown(self):
        app.SYSTEM_SETTINGS_FILE = self._old_settings_file
        configure_image_protection(self._old_runtime_settings)
        configure_llm_client(self._old_llm_settings)
        self._tmp.cleanup()

    def test_admin_can_read_and_update_image_protection_settings(self):
        result = app.api_system_settings_put(
            {
                "image_protection": {
                    "enabled": False,
                    "llm_vision_enabled": True,
                    "prompt_signals_enabled": True,
                    "prompt_context_enabled": False,
                    "detector_threshold": 0.33,
                    "paired_breast_threshold": 0.62,
                    "buttocks_threshold": 0.77,
                    "weak_breast_prompt_threshold": 0.54,
                    "prompt_patterns": {"strong_nude": "全裸|裸体|bare", "violence": "血腥|gore"},
                }
            },
            current_user={"sub": "admin", "role": "admin"},
        )

        self.assertTrue(result["ok"])
        settings = result["data"]["image_protection"]
        self.assertFalse(settings["enabled"])
        self.assertTrue(settings["llm_vision_enabled"])
        self.assertTrue(settings["prompt_signals_enabled"])
        self.assertFalse(settings["prompt_context_enabled"])
        self.assertAlmostEqual(settings["detector_threshold"], 0.33)
        self.assertAlmostEqual(settings["paired_breast_threshold"], 0.62)
        self.assertAlmostEqual(settings["buttocks_threshold"], 0.77)
        self.assertAlmostEqual(settings["weak_breast_prompt_threshold"], 0.54)
        self.assertEqual(settings["prompt_patterns"]["strong_nude"], "全裸|裸体|bare")
        self.assertEqual(settings["prompt_patterns"]["violence"], "血腥|gore")

        loaded = app.api_system_settings_get(current_user={"sub": "admin", "role": "admin"})
        self.assertEqual(loaded["data"]["image_protection"]["prompt_patterns"]["strong_nude"], "全裸|裸体|bare")
        self.assertEqual(loaded["data"]["image_protection"]["prompt_patterns"]["violence"], "血腥|gore")

    def test_admin_can_manage_llm_api_settings(self):
        result = app.api_system_settings_put(
            {
                "llm_api": {
                    "enabled": True,
                    "base_url": "http://10.10.10.75:8080",
                    "model": "HauhauCS/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive:Q5_K_P",
                    "api_key": "secret-token",
                    "timeout": 240,
                }
            },
            current_user={"sub": "admin", "role": "admin"},
        )

        settings = result["data"]["llm_api"]
        self.assertTrue(settings["enabled"])
        self.assertEqual(settings["base_url"], "http://10.10.10.75:8080")
        self.assertEqual(settings["model"], "HauhauCS/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive:Q5_K_P")
        self.assertEqual(settings["api_key"], "secr...oken")
        self.assertEqual(settings["timeout"], 240)
        self.assertEqual(get_llm_client_settings()["base_url"], "http://10.10.10.75:8080")
        self.assertEqual(get_llm_client_settings(include_api_key=True)["api_key"], "secret-token")

        loaded = app.api_system_settings_get(current_user={"sub": "admin", "role": "admin"})
        self.assertEqual(loaded["data"]["llm_api"]["model"], settings["model"])

    def test_llm_api_test_uses_submitted_connection_values(self):
        calls = []
        old_chat_completion = app.chat_completion
        try:
            def fake_chat_completion(messages, **kwargs):
                calls.append({"messages": messages, **kwargs})
                return {
                    "model": kwargs.get("model"),
                    "choices": [{"message": {"content": "pong"}}],
                }

            app.chat_completion = fake_chat_completion
            result = app.api_llm_api_test(
                {
                    "llm_api": {
                        "base_url": "http://10.10.10.75:8080",
                        "model": "gemma-q5",
                        "api_key": "secret",
                        "timeout": 12,
                    }
                },
                current_user={"sub": "admin", "role": "admin"},
            )
        finally:
            app.chat_completion = old_chat_completion

        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "llm-gemma-q5")
        self.assertEqual(calls[0]["base_url"], "http://10.10.10.75:8080")
        self.assertEqual(calls[0]["model"], "gemma-q5")
        self.assertEqual(calls[0]["api_key"], "secret")
        self.assertEqual(calls[0]["timeout"], 12)

    def test_admin_can_store_and_activate_llm_api_profiles(self):
        result = app.api_system_settings_put(
            {
                "llm_api_profiles": [
                    {
                        "id": "dgx-q5-vision",
                        "name": "DGX Q5 Vision",
                        "enabled": True,
                        "base_url": "http://10.10.10.75:8080",
                        "model": "dgx-model",
                        "timeout": 240,
                        "capabilities": ["text", "vision"],
                    },
                    {
                        "id": "mac-gemma-q4-text",
                        "name": "Mac Gemma Q4",
                        "enabled": True,
                        "base_url": "http://127.0.0.1:18080",
                        "model": "mac-gemma-4-e4b-it-uncensored-q4",
                        "timeout": 180,
                        "capabilities": ["text"],
                    },
                ],
                "active_llm_api_profile": "mac-gemma-q4-text",
            },
            current_user={"sub": "admin", "role": "admin"},
        )

        self.assertEqual(result["data"]["active_llm_api_profile"], "mac-gemma-q4-text")
        self.assertEqual(result["data"]["llm_api"]["base_url"], "http://127.0.0.1:18080")
        self.assertEqual(result["data"]["llm_api"]["model"], "mac-gemma-4-e4b-it-uncensored-q4")
        self.assertEqual(len(result["data"]["llm_api_profiles"]), 2)
        self.assertEqual(get_llm_client_settings()["base_url"], "http://127.0.0.1:18080")

    def test_non_admin_cannot_read_system_settings(self):
        with self.assertRaises(HTTPException) as ctx:
            app.api_system_settings_get(current_user=app.require_admin({"sub": "user1", "role": "user"}))

        self.assertEqual(ctx.exception.status_code, 403)

    def test_saved_thresholds_apply_to_resident_image_protection_worker(self):
        app.api_system_settings_put(
            {"image_protection": {"enabled": True, "detector_enabled": True, "paired_breast_threshold": 0.60}},
            current_user={"sub": "admin", "role": "admin"},
        )

        def load_detector():
            return lambda _path: [
                {"label": "EXPOSED_BREAST_F", "score": 0.65},
                {"label": "EXPOSED_BREAST_F", "score": 0.61},
            ]

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "paired.jpg")
            Image.new("RGB", (48, 48), (230, 180, 160)).save(path)
            result = ImageProtectionWorker(load_detector=load_detector, load_classifier=lambda: None).check(path)

        self.assertEqual(result.status, "protected")
        self.assertIn("paired EXPOSED_BREAST_F", result.reason)


if __name__ == "__main__":
    unittest.main()
