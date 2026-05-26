import os
import tempfile
import unittest

from PIL import Image
from fastapi import HTTPException

import app
from modules.image_protection import ImageProtectionWorker, configure_image_protection


class SystemSettingsApiTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_settings_file = app.SYSTEM_SETTINGS_FILE
        self._old_runtime_settings = app.get_image_protection_settings()
        app.SYSTEM_SETTINGS_FILE = os.path.join(self._tmp.name, "system_settings.json")
        configure_image_protection(self._old_runtime_settings)

    def tearDown(self):
        app.SYSTEM_SETTINGS_FILE = self._old_settings_file
        configure_image_protection(self._old_runtime_settings)
        self._tmp.cleanup()

    def test_admin_can_read_and_update_image_protection_settings(self):
        result = app.api_system_settings_put(
            {
                "image_protection": {
                    "enabled": False,
                    "prompt_signals_enabled": True,
                    "prompt_context_enabled": False,
                    "detector_threshold": 0.33,
                    "paired_breast_threshold": 0.62,
                    "buttocks_threshold": 0.77,
                    "weak_breast_prompt_threshold": 0.54,
                    "prompt_patterns": {"strong_nude": "全裸|裸体|bare"},
                }
            },
            current_user={"sub": "admin", "role": "admin"},
        )

        self.assertTrue(result["ok"])
        settings = result["data"]["image_protection"]
        self.assertFalse(settings["enabled"])
        self.assertTrue(settings["prompt_signals_enabled"])
        self.assertFalse(settings["prompt_context_enabled"])
        self.assertAlmostEqual(settings["detector_threshold"], 0.33)
        self.assertAlmostEqual(settings["paired_breast_threshold"], 0.62)
        self.assertAlmostEqual(settings["buttocks_threshold"], 0.77)
        self.assertAlmostEqual(settings["weak_breast_prompt_threshold"], 0.54)
        self.assertEqual(settings["prompt_patterns"]["strong_nude"], "全裸|裸体|bare")

        loaded = app.api_system_settings_get(current_user={"sub": "admin", "role": "admin"})
        self.assertEqual(loaded["data"]["image_protection"]["prompt_patterns"]["strong_nude"], "全裸|裸体|bare")

    def test_admin_can_read_and_update_mobile_creator_settings(self):
        result = app.api_system_settings_put(
            {
                "mobile_creator": {
                    "enabled": True,
                    "default_text_to_image_workflow": "t2i-test.json",
                    "allowed_styles": ["cinematic", "realistic"],
                    "allowed_ratios": ["1:1", "9:16"],
                    "llm_enabled": True,
                    "llm_provider": "openai_compatible",
                    "llm_base_url": "http://127.0.0.1:8080/v1",
                    "llm_model": "gemma-4-e2b",
                    "llm_api_key": "local-key",
                    "llm_gguf_model": "/Users/ai/projects/ez-comfyui-showcase/model/gemma-4-E2B-it-Q4_K_M.gguf",
                    "llm_mmproj_model": "/Users/ai/projects/ez-comfyui-showcase/model/mmproj-Gemma-4-E2B-f16.gguf",
                    "speech_timeout_ms": 4321,
                }
            },
            current_user={"sub": "admin", "role": "admin"},
        )

        self.assertTrue(result["ok"])
        settings = result["data"]["mobile_creator"]
        self.assertTrue(settings["enabled"])
        self.assertEqual(settings["default_text_to_image_workflow"], "t2i-test.json")
        self.assertEqual(settings["allowed_styles"], ["cinematic", "realistic"])
        self.assertEqual(settings["allowed_ratios"], ["1:1", "9:16"])
        self.assertTrue(settings["llm_enabled"])
        self.assertEqual(settings["llm_provider"], "openai_compatible")
        self.assertEqual(settings["llm_base_url"], "http://127.0.0.1:8080/v1")
        self.assertEqual(settings["llm_model"], "gemma-4-e2b")
        self.assertEqual(settings["llm_api_key"], "local-key")
        self.assertTrue(settings["llm_gguf_model"].endswith("gemma-4-E2B-it-Q4_K_M.gguf"))
        self.assertTrue(settings["llm_mmproj_model"].endswith("mmproj-Gemma-4-E2B-f16.gguf"))
        self.assertEqual(settings["speech_timeout_ms"], 4321)

        loaded = app.api_system_settings_get(current_user={"sub": "admin", "role": "admin"})
        self.assertEqual(loaded["data"]["mobile_creator"]["default_text_to_image_workflow"], "t2i-test.json")
        self.assertEqual(loaded["data"]["mobile_creator"]["llm_base_url"], "http://127.0.0.1:8080/v1")
        self.assertEqual(loaded["data"]["mobile_creator"]["speech_timeout_ms"], 4321)

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
