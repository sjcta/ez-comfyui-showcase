import os
import sqlite3
import tempfile
import unittest

from fastapi import HTTPException

import app


class HistoryApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_gen_db = app.GEN_DB
        self._old_auth_db = app.AUTH_DB
        self._old_output_dir = app.OUTPUT_DIR
        self._old_history_dir = app.HISTORY_DIR
        self._old_comfyui_input = app.COMFYUI_INPUT
        self._old_history = list(app.history)
        self._old_logs = list(app._log_buffer)
        app.GEN_DB = os.path.join(self._tmp.name, "generation.db")
        app.AUTH_DB = os.path.join(self._tmp.name, "auth.db")
        app.OUTPUT_DIR = os.path.join(self._tmp.name, "outputs")
        app.HISTORY_DIR = os.path.join(self._tmp.name, "history")
        app.COMFYUI_INPUT = os.path.join(self._tmp.name, "input")
        os.makedirs(app.OUTPUT_DIR, exist_ok=True)
        os.makedirs(app.HISTORY_DIR, exist_ok=True)
        os.makedirs(app.COMFYUI_INPUT, exist_ok=True)
        app.history = []
        app._log_buffer[:] = []
        app._init_gen_db()

    def tearDown(self):
        app.GEN_DB = self._old_gen_db
        app.AUTH_DB = self._old_auth_db
        app.OUTPUT_DIR = self._old_output_dir
        app.HISTORY_DIR = self._old_history_dir
        app.COMFYUI_INPUT = self._old_comfyui_input
        app.history = self._old_history
        app._log_buffer[:] = self._old_logs
        self._tmp.cleanup()

    def test_history_enriches_username_without_joining_generation_db(self):
        conn = sqlite3.connect(app.AUTH_DB)
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, disabled) VALUES (?, ?, ?, ?, 0)",
            ("u1", "alice", "hash", "user"),
        )
        conn.commit()
        conn.close()
        app._insert_generation(
            {
                "id": "hist-1",
                "workflow": "t2i-test.json",
                "filename": "hist-1.png",
                "prompt": "hello",
                "time": "2026-05-18 12:00:00",
            },
            elapsed=3,
            user_id="u1",
        )

        result = app.api_history(limit=10, scope="all", current_user={"sub": "admin", "role": "admin"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["data"][0]["username"], "alice")

    def test_history_orders_same_second_by_newer_insert_first(self):
        for item_id in ("job_1000_0001", "job_1002_0001", "job_1001_0001"):
            app._insert_generation(
                {
                    "id": item_id,
                    "workflow": "t2i-test.json",
                    "filename": item_id + ".png",
                    "prompt": item_id,
                    "time": "2026-05-18 12:00:00",
                },
                elapsed=3,
                user_id="u1",
            )

        result = app.api_history(limit=10, scope="mine", current_user={"sub": "u1", "role": "user"})

        self.assertEqual([item["id"] for item in result["data"]], [
            "job_1001_0001",
            "job_1002_0001",
            "job_1000_0001",
        ])
        self.assertEqual(
            [item["sort_index"] for item in result["data"]],
            sorted([item["sort_index"] for item in result["data"]], reverse=True),
        )

    def test_delete_moves_record_to_trash_without_removing_files(self):
        image_path = os.path.join(app.OUTPUT_DIR, "hist-1.png")
        with open(image_path, "wb") as f:
            f.write(b"image")
        app._insert_generation(
            {
                "id": "hist-1",
                "workflow": "t2i-test.json",
                "filename": "hist-1.png",
                "prompt": "hello",
                "time": "2026-05-18 12:00:00",
            },
            elapsed=3,
            user_id="u1",
        )

        result = app.api_history_delete("hist-1", current_user={"sub": "u1", "role": "user"})

        self.assertTrue(result["ok"])
        self.assertTrue(os.path.exists(image_path))
        normal = app.api_history(limit=10, scope="mine", current_user={"sub": "u1", "role": "user"})
        trash = app.api_history(limit=10, scope="trash", current_user={"sub": "u1", "role": "user"})
        self.assertEqual(normal["total"], 0)
        self.assertEqual(trash["total"], 1)
        self.assertTrue(trash["data"][0]["is_deleted"])
        self.assertTrue(trash["data"][0]["deleted_at"])

    def test_restore_makes_soft_deleted_record_visible_again(self):
        app._insert_generation(
            {
                "id": "hist-1",
                "workflow": "t2i-test.json",
                "filename": "hist-1.png",
                "time": "2026-05-18 12:00:00",
            },
            elapsed=3,
            user_id="u1",
        )
        user = {"sub": "u1", "role": "user"}
        app.api_history_delete("hist-1", current_user=user)

        result = app.api_history_restore("hist-1", current_user=user)

        self.assertTrue(result["ok"])
        normal = app.api_history(limit=10, scope="mine", current_user=user)
        trash = app.api_history(limit=10, scope="trash", current_user=user)
        self.assertEqual(normal["total"], 1)
        self.assertFalse(normal["data"][0]["is_deleted"])
        self.assertEqual(trash["total"], 0)

    def test_permanent_delete_removes_record_and_files(self):
        image_path = os.path.join(app.OUTPUT_DIR, "hist-1.png")
        with open(image_path, "wb") as f:
            f.write(b"image")
        app._insert_generation(
            {
                "id": "hist-1",
                "workflow": "t2i-test.json",
                "filename": "hist-1.png",
                "time": "2026-05-18 12:00:00",
            },
            elapsed=3,
            user_id="u1",
        )
        user = {"sub": "u1", "role": "user"}
        app.api_history_delete("hist-1", current_user=user)

        result = app.api_history_permanent_delete("hist-1", current_user=user)

        self.assertTrue(result["ok"])
        self.assertFalse(os.path.exists(image_path))
        trash = app.api_history(limit=10, scope="trash", current_user=user)
        self.assertEqual(trash["total"], 0)

    def test_permanent_delete_removes_uploaded_source_image_when_unreferenced(self):
        image_path = os.path.join(app.OUTPUT_DIR, "hist-1.png")
        source_rel = "u1/2026-05-18/uploaded.png"
        source_path = os.path.join(app.COMFYUI_INPUT, source_rel)
        os.makedirs(os.path.dirname(source_path), exist_ok=True)
        with open(image_path, "wb") as f:
            f.write(b"image")
        with open(source_path, "wb") as f:
            f.write(b"source")
        app._insert_generation(
            {
                "id": "hist-1",
                "workflow": "i2i-test.json",
                "filename": "hist-1.png",
                "time": "2026-05-18 12:00:00",
                "field_values": {"41::image": source_rel},
            },
            elapsed=3,
            user_id="u1",
        )
        user = {"sub": "u1", "role": "user"}
        app.api_history_delete("hist-1", current_user=user)

        result = app.api_history_permanent_delete("hist-1", current_user=user)

        self.assertTrue(result["ok"])
        self.assertFalse(os.path.exists(image_path))
        self.assertFalse(os.path.exists(source_path))

    def test_permanent_delete_keeps_uploaded_source_image_used_by_other_history(self):
        source_rel = "u1/2026-05-18/shared.png"
        source_path = os.path.join(app.COMFYUI_INPUT, source_rel)
        os.makedirs(os.path.dirname(source_path), exist_ok=True)
        with open(source_path, "wb") as f:
            f.write(b"source")
        for item_id in ("hist-1", "hist-2"):
            image_path = os.path.join(app.OUTPUT_DIR, item_id + ".png")
            with open(image_path, "wb") as f:
                f.write(b"image")
            app._insert_generation(
                {
                    "id": item_id,
                    "workflow": "i2i-test.json",
                    "filename": item_id + ".png",
                    "time": "2026-05-18 12:00:00",
                    "field_values": {"41::image": source_rel},
                },
                elapsed=3,
                user_id="u1",
            )
        user = {"sub": "u1", "role": "user"}
        app.api_history_delete("hist-1", current_user=user)

        result = app.api_history_permanent_delete("hist-1", current_user=user)

        self.assertTrue(result["ok"])
        self.assertTrue(os.path.exists(source_path))

    def test_image_routes_read_only_from_output_dir(self):
        output_image = os.path.join(app.OUTPUT_DIR, "u1", "2026-05-18", "hist-1.png")
        history_image = os.path.join(app.HISTORY_DIR, "u1", "2026-05-18", "hist-2.png")
        os.makedirs(os.path.dirname(output_image), exist_ok=True)
        os.makedirs(os.path.dirname(history_image), exist_ok=True)
        with open(output_image, "wb") as f:
            f.write(b"image")
        with open(history_image, "wb") as f:
            f.write(b"legacy")

        ok = app.api_image("u1/2026-05-18/hist-1.png")
        self.assertEqual(ok.path, output_image)
        with self.assertRaises(HTTPException):
            app.api_image("u1/2026-05-18/hist-2.png")


if __name__ == "__main__":
    unittest.main()
