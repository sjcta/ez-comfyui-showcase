import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.mobile_agent import DEFAULT_MOBILE_CREATOR_SETTINGS
from modules.mobile_agent_routes import _load_mobile_creator_settings, register_mobile_agent_routes


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
        self.assertEqual(data["workflow_title"], self.workflow_name)
        self.assertIn("compiled_prompt", data)
        self.assertEqual(data["field_values"], {"1::text": data["compiled_prompt"]})

    def test_understand_workflow_title_uses_custom_name(self):
        api = FastAPI()
        register_mobile_agent_routes(api, {
            "get_current_user": lambda: {"sub": "user1", "role": "user"},
            "load_system_settings": lambda: self.settings,
            "load_wf_meta": lambda: {self.workflow_name: {"name": "自定义文生图"}},
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

        response = TestClient(api).post("/api/mobile-agent/understand", json={"text": "帮我出一张未来城市雨夜的照片"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["workflow_title"], "自定义文生图")

    def test_understand_maps_real_workflow_analyze_nodes_to_generate_fields(self):
        api = FastAPI()
        register_mobile_agent_routes(api, {
            "get_current_user": lambda: {"sub": "user1", "role": "user"},
            "load_system_settings": lambda: self.settings,
            "load_wf_meta": lambda: {self.workflow_name: {}},
            "normalize_wf_meta_entry": lambda filename, entry: entry or {},
            "resolve_workflow": lambda filename, entry=None: f"/tmp/{filename}" if filename == self.workflow_name else None,
            "can_view_workflow": lambda filename, entry, user: filename == self.workflow_name,
            "analyze_workflow": lambda path: {"nodes": [{
                "node_id": "1",
                "class_type": "Text Multiline",
                "title": "提示词",
                "fields": [{
                    "key": "1::text",
                    "field": "text",
                    "label": "提示词",
                    "zone": "user_input",
                    "visible": True,
                }],
            }]},
            "add_log": lambda *args, **kwargs: self.logs.append((args, kwargs)),
            "user_id": lambda user: user.get("sub", ""),
            "speech_transcriber_factory": self._speech_transcriber_factory,
        })

        response = TestClient(api).post("/api/mobile-agent/understand", json={"text": "帮我出一张未来城市雨夜的照片"})

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["field_values"], {"1::text": data["compiled_prompt"]})

    def test_anonymous_understand_can_prepare_default_workflow(self):
        api = FastAPI()
        register_mobile_agent_routes(api, {
            "get_current_user": lambda: (_ for _ in ()).throw(AssertionError("required auth should not run")),
            "get_current_user_optional": lambda: None,
            "load_system_settings": lambda: self.settings,
            "load_wf_meta": lambda: {self.workflow_name: {"shared": False}},
            "normalize_wf_meta_entry": lambda filename, entry: entry or {},
            "resolve_workflow": lambda filename, entry=None: f"/tmp/{filename}" if filename == self.workflow_name else None,
            "can_view_workflow": lambda filename, entry, user: False,
            "analyze_workflow": lambda path: {"fields": [
                {"node_id": "1", "field": "text", "label": "提示词", "class_type": "Text Multiline", "zone": "user_input"}
            ]},
            "add_log": lambda *args, **kwargs: self.logs.append((args, kwargs)),
            "user_id": lambda user: user.get("sub", "") if user else "",
            "speech_transcriber_factory": self._speech_transcriber_factory,
        })

        response = TestClient(api).post("/api/mobile-agent/understand", json={"text": "一张海边日落"})

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["response_type"], "confirm")
        self.assertEqual(data["resolved_workflow"], self.workflow_name)
        self.assertEqual(data["field_values"], {"1::text": data["compiled_prompt"]})

    def test_understand_reports_unavailable_default_workflow(self):
        self.settings = {"mobile_creator": {"default_text_to_image_workflow": "missing.json"}}

        response = self.client.post("/api/mobile-agent/understand", json={"text": "帮我出一张未来城市雨夜的照片"})

        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["error_code"], "workflow_unavailable")
        self.assertTrue(result["data"]["needs_confirmation"])

    def test_chat_response_does_not_map_workflow_fields(self):
        response = self.client.post("/api/mobile-agent/understand", json={"text": "你好"})

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["response_type"], "chat")
        self.assertEqual(data["field_values"], {})
        self.assertEqual(data["resolved_workflow"], "")
        self.assertNotIn("workflow_title", data)

    def test_upload_attachment_returns_mobile_attachment_contract(self):
        response = self.client.post(
            "/api/mobile-agent/upload-attachment",
            files={"file": ("face_front.png", b"fake-image-bytes", "image/png")},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        data = payload["data"]
        self.assertEqual(data["name"], "face_front.png")
        self.assertEqual(data["mime_type"], "image/png")
        self.assertEqual(data["media_type"], "image")
        self.assertTrue(data["id"].startswith("att_"))
        self.assertTrue(data["url"].startswith("/api/mobile-agent/attachments/"))

    def test_understand_accepts_attachments_in_context(self):
        response = self.client.post("/api/mobile-agent/understand", json={
            "text": "图片内容分析",
            "has_image": True,
            "attachments": [{
                "id": "att_1",
                "name": "face_front.png",
                "mime_type": "image/png",
                "media_type": "image",
                "url": "/api/mobile-agent/attachments/att_1",
            }],
            "context": {"messages": []},
        })

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["attachments"][0]["id"], "att_1")
        self.assertIn(data["response_type"], ("chat", "confirm"))

    def test_understand_prefers_injected_llm_chat_provider(self):
        api = FastAPI()

        class StubLlm:
            def decide(self, text, context=None, settings=None):
                self.text = text
                return {
                    "ok": True,
                    "provider": "stub-llm",
                    "decision": {"action": "chat", "reply": "这是普通聊天回复。", "ready": False},
                    "duration_ms": 3,
                }

        stub_llm = StubLlm()
        register_mobile_agent_routes(api, {
            "get_current_user": lambda: {"sub": "user1", "role": "user"},
            "get_current_user_optional": lambda: None,
            "load_system_settings": lambda: self.settings,
            "load_wf_meta": lambda: {self.workflow_name: {}},
            "normalize_wf_meta_entry": lambda filename, entry: entry or {},
            "resolve_workflow": lambda filename, entry=None: f"/tmp/{filename}" if filename == self.workflow_name else None,
            "can_view_workflow": lambda filename, entry, user: filename == self.workflow_name,
            "analyze_workflow": lambda path: (_ for _ in ()).throw(AssertionError("chat should not analyze workflow")),
            "add_log": lambda *args, **kwargs: self.logs.append((args, kwargs)),
            "user_id": lambda user: user.get("sub", "") if user else "",
            "speech_transcriber_factory": self._speech_transcriber_factory,
            "mobile_agent_llm": stub_llm,
        })

        response = TestClient(api).post("/api/mobile-agent/understand", json={"text": "机器人以后可以照顾老人么？"})

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(stub_llm.text, "机器人以后可以照顾老人么？")
        self.assertEqual(data["response_type"], "chat")
        self.assertEqual(data["assistant_message"], "这是普通聊天回复。")
        self.assertEqual(data["llm_provider"], "stub-llm")
        self.assertEqual(data["field_values"], {})

    def test_understand_llm_generation_decision_maps_workflow_fields(self):
        api = FastAPI()

        class StubLlm:
            def decide(self, text, context=None, settings=None):
                return {
                    "ok": True,
                    "provider": "stub-llm",
                    "decision": {
                        "action": "propose_generation",
                        "reply": "我整理好了。",
                        "ready": True,
                        "prompt": "雨夜里的赛博朋克猫咪，霓虹灯",
                        "style": "cinematic",
                        "aspect_ratio": "9:16",
                    },
                    "duration_ms": 4,
                }

        register_mobile_agent_routes(api, {
            "get_current_user": lambda: {"sub": "user1", "role": "user"},
            "get_current_user_optional": lambda: None,
            "load_system_settings": lambda: self.settings,
            "load_wf_meta": lambda: {self.workflow_name: {}},
            "normalize_wf_meta_entry": lambda filename, entry: entry or {},
            "resolve_workflow": lambda filename, entry=None: f"/tmp/{filename}" if filename == self.workflow_name else None,
            "can_view_workflow": lambda filename, entry, user: filename == self.workflow_name,
            "analyze_workflow": lambda path: {"fields": [
                {"node_id": "1", "field": "text", "label": "提示词", "class_type": "Text Multiline", "zone": "user_input"}
            ]},
            "add_log": lambda *args, **kwargs: self.logs.append((args, kwargs)),
            "user_id": lambda user: user.get("sub", "") if user else "",
            "speech_transcriber_factory": self._speech_transcriber_factory,
            "mobile_agent_llm": StubLlm(),
        })

        response = TestClient(api).post("/api/mobile-agent/understand", json={"text": "做一张雨夜猫咪"})

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["response_type"], "confirm")
        self.assertEqual(data["field_values"], {"1::text": "雨夜里的赛博朋克猫咪，霓虹灯"})
        self.assertEqual(data["llm_provider"], "stub-llm")

    def test_understand_returns_selectable_workflow_choices_with_fields(self):
        api = FastAPI()
        self.settings = {"mobile_creator": {"default_text_to_image_workflow": "t2i-default.json"}}
        meta = {
            "t2i-default.json": {"name": "默认文生图", "tags": ["文生图"]},
            "t2i-fast.json": {"name": "快速文生图", "tags": ["文生图", "fast"]},
            "i2i-edit.json": {"name": "图生图", "tags": ["图生图"]},
            "video.json": {"name": "视频", "tags": ["视频"]},
        }

        class StubLlm:
            def decide(self, text, context=None, settings=None):
                return {
                    "ok": True,
                    "provider": "stub-llm",
                    "decision": {
                        "action": "propose_generation",
                        "reply": "确认后生成。",
                        "ready": True,
                        "prompt": "雨夜里的赛博朋克猫咪，霓虹灯",
                        "style": "cinematic",
                        "aspect_ratio": "1:1",
                    },
                    "duration_ms": 4,
                }

        register_mobile_agent_routes(api, {
            "get_current_user": lambda: {"sub": "user1", "role": "user"},
            "get_current_user_optional": lambda: None,
            "load_system_settings": lambda: self.settings,
            "load_wf_meta": lambda: meta,
            "normalize_wf_meta_entry": lambda filename, entry: entry or {},
            "resolve_workflow": lambda filename, entry=None: f"/tmp/{filename}" if filename in meta else None,
            "can_view_workflow": lambda filename, entry, user: filename != "video.json",
            "analyze_workflow": lambda path: {"fields": [
                {"node_id": "1", "field": "text", "label": "提示词", "class_type": "Text Multiline", "zone": "user_input"}
            ]},
            "add_log": lambda *args, **kwargs: self.logs.append((args, kwargs)),
            "user_id": lambda user: user.get("sub", "") if user else "",
            "speech_transcriber_factory": self._speech_transcriber_factory,
            "mobile_agent_llm": StubLlm(),
        })

        response = TestClient(api).post("/api/mobile-agent/understand", json={"text": "做一张雨夜猫咪"})

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        choices = data["workflow_choices"]
        self.assertEqual([choice["workflow"] for choice in choices], ["t2i-default.json", "t2i-fast.json"])
        self.assertEqual(choices[0]["title"], "默认文生图")
        self.assertEqual(choices[1]["title"], "快速文生图")
        self.assertEqual(choices[1]["field_values"], {"1::text": data["compiled_prompt"]})
        self.assertNotIn("video.json", [choice["workflow"] for choice in choices])

    def test_understand_falls_back_when_llm_is_unavailable(self):
        api = FastAPI()

        class BrokenLlm:
            def decide(self, text, context=None, settings=None):
                return {"ok": False, "provider": "none", "error_code": "llm_unavailable", "message": "missing runtime"}

        register_mobile_agent_routes(api, {
            "get_current_user": lambda: {"sub": "user1", "role": "user"},
            "get_current_user_optional": lambda: None,
            "load_system_settings": lambda: self.settings,
            "load_wf_meta": lambda: {self.workflow_name: {}},
            "normalize_wf_meta_entry": lambda filename, entry: entry or {},
            "resolve_workflow": lambda filename, entry=None: f"/tmp/{filename}" if filename == self.workflow_name else None,
            "can_view_workflow": lambda filename, entry, user: filename == self.workflow_name,
            "analyze_workflow": lambda path: {"fields": [
                {"node_id": "1", "field": "text", "label": "提示词", "class_type": "Text Multiline", "zone": "user_input"}
            ]},
            "add_log": lambda *args, **kwargs: self.logs.append((args, kwargs)),
            "user_id": lambda user: user.get("sub", "") if user else "",
            "speech_transcriber_factory": self._speech_transcriber_factory,
            "mobile_agent_llm": BrokenLlm(),
        })

        response = TestClient(api).post("/api/mobile-agent/understand", json={"text": "一张海边日落"})

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["response_type"], "confirm")
        self.assertEqual(data["llm_provider"], "rule_fallback")
        self.assertEqual(data["llm_error_code"], "llm_unavailable")

    def test_understand_builds_llm_from_current_admin_settings(self):
        api = FastAPI()
        factory_calls = []

        class StubLlm:
            def decide(self, text, context=None, settings=None):
                return {
                    "ok": True,
                    "provider": "settings-llm",
                    "decision": {"action": "chat", "reply": "来自设置里的模型。", "ready": False},
                    "duration_ms": 2,
                }

        def factory(settings):
            factory_calls.append(dict(settings))
            return StubLlm()

        self.settings = {"mobile_creator": {
            "default_text_to_image_workflow": self.workflow_name,
            "llm_enabled": True,
            "llm_base_url": "http://127.0.0.1:8080/v1",
            "llm_model": "gemma-4-e2b",
        }}
        register_mobile_agent_routes(api, {
            "get_current_user": lambda: {"sub": "user1", "role": "user"},
            "get_current_user_optional": lambda: None,
            "load_system_settings": lambda: self.settings,
            "load_wf_meta": lambda: {self.workflow_name: {}},
            "normalize_wf_meta_entry": lambda filename, entry: entry or {},
            "resolve_workflow": lambda filename, entry=None: f"/tmp/{filename}" if filename == self.workflow_name else None,
            "can_view_workflow": lambda filename, entry, user: filename == self.workflow_name,
            "analyze_workflow": lambda path: (_ for _ in ()).throw(AssertionError("chat should not analyze workflow")),
            "add_log": lambda *args, **kwargs: self.logs.append((args, kwargs)),
            "user_id": lambda user: user.get("sub", "") if user else "",
            "speech_transcriber_factory": self._speech_transcriber_factory,
            "mobile_agent_llm_factory": factory,
        })

        response = TestClient(api).post("/api/mobile-agent/understand", json={"text": "你好"})

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["response_type"], "chat")
        self.assertEqual(data["assistant_message"], "来自设置里的模型。")
        self.assertEqual(data["llm_provider"], "settings-llm")
        self.assertEqual(factory_calls[0]["llm_base_url"], "http://127.0.0.1:8080/v1")

    def test_understand_retries_llm_without_history_when_context_decision_is_invalid(self):
        api = FastAPI()

        class FlakyLlm:
            def __init__(self):
                self.calls = []

            def decide(self, text, context=None, settings=None):
                self.calls.append(context or {})
                if len(self.calls) == 1:
                    return {
                        "ok": False,
                        "provider": "stub-llm",
                        "error_code": "llm_invalid_decision",
                        "message": "bad json",
                    }
                return {
                    "ok": True,
                    "provider": "stub-llm",
                    "decision": {
                        "action": "propose_generation",
                        "reply": "确认后生成。",
                        "ready": True,
                        "prompt": "雨夜赛博朋克猫咪",
                    },
                    "duration_ms": 4,
                }

        llm = FlakyLlm()
        register_mobile_agent_routes(api, {
            "get_current_user": lambda: {"sub": "user1", "role": "user"},
            "get_current_user_optional": lambda: None,
            "load_system_settings": lambda: self.settings,
            "load_wf_meta": lambda: {self.workflow_name: {}},
            "normalize_wf_meta_entry": lambda filename, entry: entry or {},
            "resolve_workflow": lambda filename, entry=None: f"/tmp/{filename}" if filename == self.workflow_name else None,
            "can_view_workflow": lambda filename, entry, user: filename == self.workflow_name,
            "analyze_workflow": lambda path: {"fields": [
                {"node_id": "1", "field": "text", "label": "提示词", "class_type": "Text Multiline", "zone": "user_input"}
            ]},
            "add_log": lambda *args, **kwargs: self.logs.append((args, kwargs)),
            "user_id": lambda user: user.get("sub", "") if user else "",
            "speech_transcriber_factory": self._speech_transcriber_factory,
            "mobile_agent_llm": llm,
        })

        response = TestClient(api).post("/api/mobile-agent/understand", json={
            "text": "帮我出一张雨夜里的赛博朋克猫咪",
            "context": {
                "memory_summary": "上一版创作方案：猫咪",
                "last_result": {"image": "user1/cat.png"},
                "messages": [{"role": "user", "text": "你好"}],
            },
        })

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["response_type"], "confirm")
        self.assertEqual(data["llm_provider"], "stub-llm")
        self.assertEqual(data["compiled_prompt"], "雨夜赛博朋克猫咪")
        self.assertEqual(llm.calls[1], {
            "memory_summary": "上一版创作方案：猫咪",
            "last_result": {"image": "user1/cat.png"},
            "messages": [],
        })

    def test_blank_default_workflow_setting_falls_back_to_mobile_default(self):
        settings = _load_mobile_creator_settings(lambda: {"mobile_creator": {"default_text_to_image_workflow": ""}})

        self.assertEqual(
            settings["default_text_to_image_workflow"],
            DEFAULT_MOBILE_CREATOR_SETTINGS["default_text_to_image_workflow"],
        )

    def test_understand_uses_image_to_image_workflow_for_result_followup(self):
        self.settings = {"mobile_creator": {
            "default_text_to_image_workflow": self.workflow_name,
            "default_image_to_image_workflow": "i2i-test.json",
        }}
        api = FastAPI()
        register_mobile_agent_routes(api, {
            "get_current_user": lambda: {"sub": "user1", "role": "user"},
            "load_system_settings": lambda: self.settings,
            "load_wf_meta": lambda: {"i2i-test.json": {}},
            "normalize_wf_meta_entry": lambda filename, entry: entry or {},
            "resolve_workflow": lambda filename, entry=None: f"/tmp/{filename}" if filename == "i2i-test.json" else None,
            "can_view_workflow": lambda filename, entry, user: filename == "i2i-test.json",
            "analyze_workflow": lambda path: {"fields": [
                {"node_id": "1", "field": "text", "label": "提示词", "class_type": "Text Multiline", "zone": "user_input"},
                {"node_id": "40", "field": "image", "label": "参考图片", "class_type": "LoadImage", "zone": "user_input"},
            ]},
            "add_log": lambda *args, **kwargs: self.logs.append((args, kwargs)),
            "user_id": lambda user: user.get("sub", ""),
            "speech_transcriber_factory": self._speech_transcriber_factory,
        })

        response = TestClient(api).post("/api/mobile-agent/understand", json={
            "text": "改成赛博朋克风格",
            "context": {"last_result": {"image": "user1/2026-05-25/cat.png", "id": "job1"}},
        })

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["intent"], "image_to_image")
        self.assertEqual(data["workflow"], "default_image_to_image")
        self.assertEqual(data["resolved_workflow"], "i2i-test.json")
        self.assertEqual(data["source_result"]["image"], "user1/2026-05-25/cat.png")
        self.assertEqual(data["field_values"], {
            "1::text": data["compiled_prompt"],
            "40::image": "user1/2026-05-25/cat.png",
        })

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
