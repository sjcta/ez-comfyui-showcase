import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.mobile_agent_routes import register_mobile_agent_routes


class MobileAgentRoutesTests(unittest.TestCase):
    def setUp(self):
        self.workflow_name = "t2i-test.json"
        self.settings = {"mobile_creator": {"default_text_to_image_workflow": self.workflow_name}}
        self.logs = []
        self.transcriber_result = {"ok": True, "provider": "stub", "transcript": "hello", "duration_ms": 12, "error_code": ""}
        self.transcriber_calls = []
        api = FastAPI()
        register_mobile_agent_routes(api, {
            "get_current_user": lambda: {"sub": "user1", "role": "user"},
            "load_system_settings": lambda: self.settings,
            "load_wf_meta": lambda: {self.workflow_name: {}},
            "normalize_wf_meta_entry": lambda filename, entry: entry or {},
            "resolve_workflow": lambda filename, entry=None: f"/tmp/{filename}" if filename == self.workflow_name else None,
            "can_view_workflow": lambda filename, entry, user: filename == self.workflow_name,
            "analyze_workflow": lambda path: {"fields": [
                {"node_id": "1", "field": "text", "label": "提示词", "class_type": "Text Multiline", "zone": "user_input"}
            ]},
            "add_log": lambda *args, **kwargs: self.logs.append((args, kwargs)),
            "user_id": lambda user: user.get("sub", ""),
            "speech_transcriber_factory": self._speech_transcriber_factory,
        })
        self.client = TestClient(api)

    def _speech_transcriber_factory(self):
        test = self

        class StubTranscriber:
            def transcribe_bytes(self, content, filename="voice.webm", timeout_ms=5000):
                test.transcriber_calls.append({
                    "content": content,
                    "filename": filename,
                    "timeout_ms": timeout_ms,
                })
                return dict(test.transcriber_result)

        return StubTranscriber()

    def test_understand_returns_structured_mobile_agent_payload(self):
        response = self.client.post("/api/mobile-agent/understand", json={"text": "帮我出一张未来城市雨夜的照片"})

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["ok"])
        data = result["data"]
        self.assertEqual(data["intent"], "text_to_image")
        self.assertEqual(data["workflow"], "default_text_to_image")
        self.assertEqual(data["resolved_workflow"], self.workflow_name)
        self.assertIn("compiled_prompt", data)
        self.assertEqual(data["field_values"], {"1::text": data["compiled_prompt"]})

    def test_understand_reports_unavailable_default_workflow(self):
        self.settings = {"mobile_creator": {"default_text_to_image_workflow": "missing.json"}}

        response = self.client.post("/api/mobile-agent/understand", json={"text": "帮我出一张未来城市雨夜的照片"})

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["error_code"], "workflow_unavailable")
        self.assertTrue(result["data"]["needs_confirmation"])

    def test_understand_analysis_failure_requires_confirmation(self):
        api = FastAPI()
        register_mobile_agent_routes(api, {
            "get_current_user": lambda: {"sub": "user1", "role": "user"},
            "load_system_settings": lambda: self.settings,
            "load_wf_meta": lambda: {self.workflow_name: {}},
            "normalize_wf_meta_entry": lambda filename, entry: entry or {},
            "resolve_workflow": lambda filename, entry=None: f"/tmp/{filename}",
            "can_view_workflow": lambda filename, entry, user: True,
            "analyze_workflow": lambda path: (_ for _ in ()).throw(RuntimeError("bad workflow")),
            "add_log": lambda *args, **kwargs: self.logs.append((args, kwargs)),
            "user_id": lambda user: user.get("sub", ""),
            "speech_transcriber_factory": self._speech_transcriber_factory,
        })

        response = TestClient(api).post("/api/mobile-agent/understand", json={"text": "帮我出一张未来城市雨夜的照片"})

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["field_values"], {})
        self.assertTrue(data["needs_confirmation"])
        self.assertEqual(data["error_code"], "workflow_analysis_failed")
        self.assertTrue(data["question"])

    def test_transcribe_uses_injected_transcriber_success(self):
        response = self.client.post(
            "/api/mobile-agent/transcribe",
            files={"file": ("voice.webm", b"audio-bytes", "audio/webm")},
            data={"timeout_ms": "1234"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["transcript"], "hello")
        self.assertEqual(self.transcriber_calls, [{
            "content": b"audio-bytes",
            "filename": "voice.webm",
            "timeout_ms": 1234,
        }])

    def test_transcribe_uses_injected_transcriber_failure(self):
        self.transcriber_result = {
            "ok": False,
            "provider": "stub",
            "transcript": "",
            "duration_ms": 0,
            "error_code": "speech_backend_unavailable",
        }

        response = self.client.post(
            "/api/mobile-agent/transcribe",
            files={"file": ("voice.webm", b"audio-bytes", "audio/webm")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(response.json()["error_code"], "speech_backend_unavailable")


if __name__ == "__main__":
    unittest.main()
