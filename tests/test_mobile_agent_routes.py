import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.mobile_agent_routes import register_mobile_agent_routes


class MobileAgentRoutesTests(unittest.TestCase):
    def setUp(self):
        self.workflow_name = "t2i-test.json"
        self.settings = {"mobile_creator": {"default_text_to_image_workflow": self.workflow_name}}
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
            "add_log": lambda *args, **kwargs: None,
            "user_id": lambda user: user.get("sub", ""),
        })
        self.client = TestClient(api)

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


if __name__ == "__main__":
    unittest.main()
