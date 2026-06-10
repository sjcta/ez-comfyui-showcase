import json
import os
import tempfile
import unittest

from fastapi import HTTPException

import app


class WorkflowMetaApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_gen_db = app.GEN_DB
        self._old_auth_db = app.AUTH_DB
        self._old_wf_dir = app.WORKFLOW_DIR
        self._old_wf_meta = app.WF_META_FILE
        self._old_wf_dirs = app.WF_DIRS_FILE
        app.GEN_DB = os.path.join(self._tmp.name, "generation.db")
        app.AUTH_DB = os.path.join(self._tmp.name, "auth.db")
        app.WORKFLOW_DIR = os.path.join(self._tmp.name, "workflows")
        app.WF_META_FILE = os.path.join(self._tmp.name, "wf_meta.json")
        app.WF_DIRS_FILE = os.path.join(self._tmp.name, "wf_dirs.json")
        os.makedirs(app.WORKFLOW_DIR, exist_ok=True)
        with open(app.WF_DIRS_FILE, "w") as f:
            json.dump([app.WORKFLOW_DIR], f)
        app._init_gen_db()
        app._init_auth_db()
        for filename in ("a.json", "b.json", "c.json"):
            with open(os.path.join(app.WORKFLOW_DIR, filename), "w") as f:
                json.dump({}, f)
        app._save_wf_meta(
            {
                "a.json": {"owner_id": "admin", "sort_order": 0},
                "b.json": {"owner_id": "admin", "sort_order": 1},
                "c.json": {"owner_id": "u1", "sort_order": 2},
            }
        )

    def tearDown(self):
        app.GEN_DB = self._old_gen_db
        app.AUTH_DB = self._old_auth_db
        app.WORKFLOW_DIR = self._old_wf_dir
        app.WF_META_FILE = self._old_wf_meta
        app.WF_DIRS_FILE = self._old_wf_dirs
        self._tmp.cleanup()

    def test_sort_workflows_persists_order(self):
        result = app.api_sort_wf_meta(
            {"b.json": 0, "a.json": 1, "c.json": 2},
            current_user={"sub": "admin", "role": "admin"},
        )

        self.assertTrue(result["ok"])
        meta = app._load_wf_meta()
        self.assertEqual(meta["b.json"]["sort_order"], 0)
        self.assertEqual(meta["a.json"]["sort_order"], 1)
        self.assertEqual(meta["c.json"]["sort_order"], 2)

    def test_sort_workflows_rejects_unmanaged_workflow(self):
        with self.assertRaises(HTTPException) as ctx:
            app.api_sort_wf_meta(
                {"c.json": 0},
                current_user={"sub": "u2", "role": "user"},
            )

        self.assertEqual(ctx.exception.status_code, 403)

    def test_db_connect_uses_current_gen_db(self):
        conn = app._db_connect()
        db_path = conn.execute("PRAGMA database_list").fetchone()["file"]
        conn.close()

        self.assertEqual(os.path.realpath(db_path), os.path.realpath(app.GEN_DB))

    def test_workflow_thumbnail_response_disables_cache(self):
        thumb_path = os.path.join(app.WORKFLOW_DIR, "a.png")
        with open(thumb_path, "wb") as f:
            f.write(b"png")

        response = app.api_get_wf_thumbnail("a.png")

        self.assertEqual(response.headers.get("cache-control"), "no-store, max-age=0")


if __name__ == "__main__":
    unittest.main()
