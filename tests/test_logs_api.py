import unittest
import tempfile
import time

import app


class LogsApiTest(unittest.TestCase):
    def setUp(self):
        self._old_logs = list(app._log_buffer)
        self._old_jobs = dict(app.jobs)
        self._old_log_file = app._LOG_FILE
        self._tmp = tempfile.NamedTemporaryFile(delete=True)
        app._LOG_FILE = self._tmp.name
        app._log_buffer[:] = []
        app.jobs.clear()

    def tearDown(self):
        app._log_buffer[:] = self._old_logs
        app.jobs.clear()
        app.jobs.update(self._old_jobs)
        app._LOG_FILE = self._old_log_file
        self._tmp.close()

    def test_user_logs_are_limited_to_accessible_jobs(self):
        own_job = "job-own-abcdefghijkl"
        other_job = "job-other-zyxwvutsrqpo"
        app.jobs[own_job] = {"id": own_job, "user_id": "u1"}
        app.jobs[other_job] = {"id": other_job, "user_id": "u2"}
        app.add_log("info", "generate", "own", own_job)
        app.add_log("info", "generate", "other", other_job)

        entries = app.api_logs(current_user={"sub": "u1", "role": "user"})

        self.assertEqual([entry["msg"] for entry in entries], ["own"])

    def test_job_logs_include_workflow_classification(self):
        job_id = "job-own-abcdefghijkl"
        app.jobs[job_id] = {"id": job_id, "user_id": "u1", "workflow": "i2i-Qwen-Edit-v2511.json"}

        app.add_log("info", "generate", "own", job_id)
        entries = app.api_logs(current_user={"sub": "u1", "role": "user"})

        self.assertEqual(entries[0]["workflow"], "i2i-Qwen-Edit-v2511.json")
        self.assertEqual(entries[0]["workflow_type"], "图生图")

    def test_workflow_primary_type_prefers_custom_metadata_tag(self):
        old_loader = app._load_wf_meta
        try:
            app._load_wf_meta = lambda: {"i2v-custom.json": {"tags": ["视频制作", "图生视频"]}}
            self.assertEqual(app._workflow_primary_type("i2v-custom.json"), "视频制作")
        finally:
            app._load_wf_meta = old_loader

    def test_stop_log_is_ignored_and_messages_are_localized(self):
        app.add_log("info", "stop", "stop", "")
        app.add_log("info", "generate", "Starting generation", "job-1")
        app.add_log("info", "step", "Sampling 4/20", "job-1")

        self.assertEqual(len(app._log_buffer), 2)
        self.assertEqual(app._log_buffer[0]["phase"], "生成")
        self.assertEqual(app._log_buffer[0]["msg"], "开始生成")
        self.assertEqual(app._log_buffer[1]["msg"], "采样 4/20")

    def test_recent_logs_survive_reload_and_expired_logs_are_pruned(self):
        now = time.time()
        recent = {
            "ts": now - 120,
            "level": "info",
            "phase": "生成",
            "msg": "recent",
            "job_id": "recent-job",
            "details": "",
            "user_id": "u1",
        }
        expired = dict(recent, ts=now - 7200, msg="expired")
        with open(app._LOG_FILE, "w", encoding="utf-8") as fh:
            fh.write(app.json.dumps(expired, ensure_ascii=False) + "\n")
            fh.write(app.json.dumps(recent, ensure_ascii=False) + "\n")

        app._load_recent_logs()
        entries = app.api_logs(current_user={"id": "u1", "sub": "u1", "role": "user"})

        self.assertEqual([entry["msg"] for entry in entries], ["recent"])

    def test_recent_log_reload_drops_non_actionable_thumbnail_noise(self):
        now = time.time()
        thumbnail_noise = {
            "ts": now - 120,
            "level": "warn",
            "phase": "thumbnail",
            "msg": "pillow thumbnail failed: cannot identify image file '/var/folders/x/tmpabc/outputs/hist-1.png'",
            "job_id": "hist-1.png",
            "details": "",
        }
        ffmpeg_noise = dict(
            thumbnail_noise,
            msg="project ffmpeg not configured; thumbnail skipped",
        )
        real_log = dict(
            thumbnail_noise,
            level="info",
            phase="生成",
            msg="recent",
            job_id="recent-job",
            user_id="u1",
        )
        with open(app._LOG_FILE, "w", encoding="utf-8") as fh:
            fh.write(app.json.dumps(thumbnail_noise, ensure_ascii=False) + "\n")
            fh.write(app.json.dumps(ffmpeg_noise, ensure_ascii=False) + "\n")
            fh.write(app.json.dumps(real_log, ensure_ascii=False) + "\n")

        app._load_recent_logs()
        entries = app.api_logs(current_user={"id": "u1", "sub": "u1", "role": "user"})

        self.assertEqual([entry["msg"] for entry in entries], ["recent"])
        with open(app._LOG_FILE, encoding="utf-8") as fh:
            persisted = fh.read()
        self.assertNotIn("pillow thumbnail failed", persisted)
        self.assertNotIn("project ffmpeg not configured", persisted)


if __name__ == "__main__":
    unittest.main()
