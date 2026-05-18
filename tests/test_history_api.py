import os
import sqlite3
import tempfile
import unittest

import app


class HistoryApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_gen_db = app.GEN_DB
        self._old_auth_db = app.AUTH_DB
        self._old_logs = list(app._log_buffer)
        app.GEN_DB = os.path.join(self._tmp.name, "generation.db")
        app.AUTH_DB = os.path.join(self._tmp.name, "auth.db")
        app._log_buffer[:] = []
        app._init_gen_db()

    def tearDown(self):
        app.GEN_DB = self._old_gen_db
        app.AUTH_DB = self._old_auth_db
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


if __name__ == "__main__":
    unittest.main()
