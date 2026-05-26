import os
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.mobile_agent_routes import register_mobile_agent_routes
from modules.mobile_agent_threads import MobileAgentThreadStore


class MobileAgentThreadStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "auth.db")
        self.store = MobileAgentThreadStore(self.db_path)
        self.store.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def test_threads_are_persisted_per_user(self):
        thread = {
            "id": "thread_1",
            "title": "猫咪玩耍的照片",
            "preview": "排队中",
            "updatedAt": 123,
            "messages": [{"role": "user", "text": "猫咪玩耍的照片"}],
            "pendingJobId": "job_1",
        }

        saved = self.store.upsert_thread("user-a", thread)

        self.assertEqual(saved["id"], "thread_1")
        self.assertEqual(self.store.list_threads("user-a")[0]["pendingJobId"], "job_1")
        self.assertEqual(self.store.list_threads("user-b"), [])

    def test_deleting_thread_is_scoped_to_owner(self):
        self.store.upsert_thread("user-a", {"id": "thread_1", "title": "A"})
        self.store.upsert_thread("user-b", {"id": "thread_1", "title": "B"})

        self.store.delete_thread("user-a", "thread_1")

        self.assertEqual(self.store.list_threads("user-a"), [])
        self.assertEqual(self.store.list_threads("user-b")[0]["title"], "B")


class MobileAgentThreadRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = MobileAgentThreadStore(os.path.join(self.tmp.name, "auth.db"))
        self.store.init_db()
        app = FastAPI()
        register_mobile_agent_routes(app, {
            "get_current_user": lambda: {"sub": "user-a", "role": "user"},
            "load_system_settings": lambda: {"mobile_creator": {"default_text_to_image_workflow": "t2i-test.json"}},
            "load_wf_meta": lambda: {"t2i-test.json": {}},
            "normalize_wf_meta_entry": lambda filename, entry: entry or {},
            "resolve_workflow": lambda filename, entry=None: f"/tmp/{filename}",
            "can_view_workflow": lambda filename, entry, user: True,
            "analyze_workflow": lambda path: {"fields": []},
            "add_log": lambda *args, **kwargs: None,
            "user_id": lambda user: user.get("sub", ""),
            "speech_transcriber_factory": lambda: None,
            "mobile_thread_store": self.store,
        })
        self.client = TestClient(app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_thread_routes_round_trip_pending_job_state(self):
        payload = {
            "id": "thread_1",
            "title": "猫咪玩耍的照片",
            "preview": "正在生成",
            "updatedAt": 123,
            "messages": [{"role": "assistant", "type": "task", "job_id": "job_1"}],
            "pendingMessageId": "msg_1",
            "pendingJobId": "job_1",
        }

        put_result = self.client.put("/api/mobile-agent/threads/thread_1", json=payload)
        self.assertEqual(put_result.status_code, 200)

        list_result = self.client.get("/api/mobile-agent/threads")
        self.assertEqual(list_result.status_code, 200)
        thread = list_result.json()["data"][0]
        self.assertEqual(thread["id"], "thread_1")
        self.assertEqual(thread["pendingJobId"], "job_1")

        delete_result = self.client.delete("/api/mobile-agent/threads/thread_1")
        self.assertEqual(delete_result.status_code, 200)
        self.assertEqual(self.client.get("/api/mobile-agent/threads").json()["data"], [])
