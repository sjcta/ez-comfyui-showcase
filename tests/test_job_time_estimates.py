import json
import os
import sqlite3
import tempfile
import time
import unittest

import app


class JobTimeEstimatesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_gen_db = app.GEN_DB
        self._old_log_file = app._LOG_FILE
        self._old_log_buffer = list(app._log_buffer)
        app.GEN_DB = os.path.join(self._tmp.name, "generation.db")
        app._LOG_FILE = os.path.join(self._tmp.name, "recent.jsonl")
        app._log_buffer[:] = []
        conn = sqlite3.connect(app.GEN_DB)
        conn.execute(
            "CREATE TABLE generations (workflow TEXT, duration_sec INTEGER, status TEXT DEFAULT 'done')"
        )
        conn.executemany(
            "INSERT INTO generations (workflow, duration_sec, status) VALUES (?, ?, 'done')",
            [
                ("t2i-test.json", 60),
                ("t2i-test.json", 90),
                ("t2i-test.json", 210),
                ("other.json", 600),
            ],
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        app.GEN_DB = self._old_gen_db
        app._LOG_FILE = self._old_log_file
        app._log_buffer[:] = self._old_log_buffer
        self._tmp.cleanup()

    def test_job_estimate_uses_workflow_median_as_minute_label(self):
        job = {"id": "job-1", "workflow": "t2i-test.json", "status": "generating"}

        enriched = app._job_with_time_estimate(job)

        self.assertEqual(enriched["estimated_duration_sec"], 90)
        self.assertEqual(enriched["estimated_duration_label"], "预计1.5分钟")
        self.assertNotIn("estimated_duration_label", job)

    def test_missing_history_has_no_estimate(self):
        job = {"id": "job-1", "workflow": "new-workflow.json", "status": "generating"}

        enriched = app._job_with_time_estimate(job)

        self.assertNotIn("estimated_duration_sec", enriched)
        self.assertNotIn("estimated_duration_label", enriched)

    def test_job_update_payload_is_enriched_for_websocket(self):
        payload = {
            "type": "job_update",
            "job": {"id": "job-1", "workflow": "t2i-test.json", "status": "generating"},
        }

        enriched = app._enrich_broadcast_payload(payload)

        self.assertEqual(enriched["job"]["estimated_duration_label"], "预计1.5分钟")
        self.assertNotIn("estimated_duration_label", payload["job"])

    def test_cold_firered_estimate_uses_conservative_floor(self):
        conn = sqlite3.connect(app.GEN_DB)
        conn.executemany(
            "INSERT INTO generations (workflow, duration_sec, status) VALUES (?, ?, 'done')",
            [
                ("i2i-FireRed-Edit-8step.json", 61),
                ("i2i-FireRed-Edit-8step.json", 78),
                ("i2i-FireRed-Edit-8step.json", 225),
            ],
        )
        conn.commit()
        conn.close()

        job = {
            "id": "job-1",
            "workflow": "i2i-FireRed-Edit-8step.json",
            "status": "starting_comfyui",
        }

        enriched = app._job_with_time_estimate(job)

        self.assertEqual(enriched["estimated_duration_sec"], 300)
        self.assertEqual(enriched["estimated_duration_label"], "预计5分钟")

    def test_node_logs_calibrate_estimate_from_current_node(self):
        conn = sqlite3.connect(app.GEN_DB)
        conn.executemany(
            "INSERT INTO generations (workflow, duration_sec, status) VALUES (?, ?, 'done')",
            [
                ("node-test.json", 60),
                ("node-test.json", 90),
                ("node-test.json", 120),
            ],
        )
        conn.commit()
        conn.close()
        entries = [
            {"ts": 100, "phase": "开始", "msg": "工作流开始执行", "job_id": "sample-a", "workflow": "node-test.json"},
            {"ts": 120, "phase": "节点", "msg": "[CLIPLoader] 加载CLIP (25%)", "job_id": "sample-a", "workflow": "node-test.json"},
            {"ts": 200, "phase": "完成", "msg": "工作流完成", "job_id": "sample-a", "workflow": "node-test.json"},
            {"ts": 300, "phase": "开始", "msg": "工作流开始执行", "job_id": "sample-b", "workflow": "node-test.json"},
            {"ts": 330, "phase": "节点", "msg": "[CLIPLoader] 加载CLIP (25%)", "job_id": "sample-b", "workflow": "node-test.json"},
            {"ts": 450, "phase": "完成", "msg": "工作流完成", "job_id": "sample-b", "workflow": "node-test.json"},
        ]
        with open(app._LOG_FILE, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        job = {
            "id": "job-current",
            "workflow": "node-test.json",
            "status": "generating",
            "submitted_at": time.time() - 30,
            "progress": {"pct": 25, "current_node": "CLIPLoader"},
        }

        enriched = app._job_with_time_estimate(job)

        self.assertGreaterEqual(enriched["estimated_duration_sec"], 125)
        self.assertEqual(enriched["estimated_duration_label"], "预计2分钟")

    def test_existing_low_estimate_is_recomputed_for_cold_job(self):
        conn = sqlite3.connect(app.GEN_DB)
        conn.executemany(
            "INSERT INTO generations (workflow, duration_sec, status) VALUES (?, ?, 'done')",
            [
                ("i2i-FireRed-Edit-8step.json", 61),
                ("i2i-FireRed-Edit-8step.json", 78),
                ("i2i-FireRed-Edit-8step.json", 225),
            ],
        )
        conn.commit()
        conn.close()
        job = {
            "id": "job-1",
            "workflow": "i2i-FireRed-Edit-8step.json",
            "status": "starting_comfyui",
            "estimated_duration_sec": 78,
            "estimated_duration_label": "预计1.5分钟",
        }

        enriched = app._job_with_time_estimate(job)

        self.assertEqual(enriched["estimated_duration_sec"], 300)
        self.assertEqual(enriched["estimated_duration_label"], "预计5分钟")


if __name__ == "__main__":
    unittest.main()
