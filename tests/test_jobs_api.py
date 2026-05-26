import unittest
import tempfile
from pathlib import Path
from unittest import mock

from fastapi import BackgroundTasks

import app

ROOT = Path(__file__).resolve().parents[1]


class JobsApiTest(unittest.TestCase):
    def setUp(self):
        self._old_jobs = dict(app.jobs)
        app.jobs.clear()

    def tearDown(self):
        app.jobs.clear()
        app.jobs.update(self._old_jobs)

    def test_admin_can_see_all_active_jobs(self):
        app.jobs["job-user"] = {"id": "job-user", "user_id": "u1", "status": "generating"}
        app.jobs["job-admin"] = {"id": "job-admin", "user_id": "admin", "status": "queued"}

        result = app.api_all_jobs(current_user={"sub": "admin", "role": "admin"})

        self.assertEqual({job["id"] for job in result}, {"job-user", "job-admin"})

    def test_user_only_sees_own_active_jobs(self):
        app.jobs["job-user"] = {"id": "job-user", "user_id": "u1", "status": "generating"}
        app.jobs["job-other"] = {"id": "job-other", "user_id": "u2", "status": "queued"}

        result = app.api_all_jobs(current_user={"sub": "u1", "role": "user"})

        self.assertEqual([job["id"] for job in result], ["job-user"])

    def test_generate_queues_broadcast_for_shared_desktop_mobile_state(self):
        source = (ROOT / "app.py").read_text()

        self.assertIn('bg.add_task(broadcast, {"type": "job_update", "job": jobs[job_id]})', source)

    def test_starting_comfyui_stage_refreshes_last_update(self):
        source = (ROOT / "modules" / "job_runner.py").read_text()

        self.assertIn('self._jobs[job_id]["status"] = "starting_comfyui"', source)
        self.assertIn('self._jobs[job_id]["last_update"] = time.time()', source)
        self.assertIn('首次启动未就绪，正在重试', source)

    def test_retry_failed_job_recovers_stuck_instance_before_requeue(self):
        with tempfile.TemporaryDirectory() as tmp:
            wf_path = Path(tmp) / "t2i-test.json"
            wf_path.write_text('{"1":{"class_type":"CLIPTextEncode","inputs":{"text":""}}}', encoding="utf-8")
            app.jobs["job-old"] = {
                "id": "job-old",
                "status": "error",
                "message": "出图失败",
                "workflow": "t2i-test.json",
                "workflow_type": "文生图",
                "fields": {"1::text": "cinematic cat"},
                "prompt_id": "prompt-stuck-1",
                "instance": "B",
                "target_node_id": "node-b",
                "target_url": "http://b",
                "user_id": "u1",
                "width": 1024,
                "height": 1024,
                "creative_brief": {"subject": "cat", "final_prompt": "cinematic cat"},
            }
            queued = []
            node = {"id": "node-b", "name": "DGX", "connection": "remote-ssh"}
            inst = {"id": "inst-b", "name": "B", "url": "http://b", "_node_id": "node-b"}

            with mock.patch("app._load_wf_meta", return_value={"t2i-test.json": {}}), \
                 mock.patch("app._can_view_workflow", return_value=True), \
                 mock.patch("app._resolve_workflow", return_value=str(wf_path)), \
                 mock.patch("app._normalize_workflow_field_values", side_effect=lambda _wf, fields: dict(fields)), \
                 mock.patch("app._get_enabled_instances", return_value=[inst]), \
                 mock.patch("app._get_node_by_id", return_value=node), \
                 mock.patch("app.comfyui_post") as comfyui_post, \
                 mock.patch("app._run_instance_action", return_value=True) as instance_action, \
                 mock.patch("app.vllm_running", return_value=False), \
                 mock.patch("app.save_jobs"), \
                 mock.patch.object(app._job_queue, "put_nowait", side_effect=queued.append):
                result = app.api_retry_job(
                    "job-old",
                    BackgroundTasks(),
                    current_user={"sub": "u1", "role": "user"},
                )

            self.assertNotIn("job-old", app.jobs)
            new_job = app.jobs[result["job_id"]]
            self.assertEqual(new_job["status"], "queued")
            self.assertEqual(new_job["creative_brief"]["subject"], "cat")
            self.assertEqual(new_job["retry_of"], "job-old")
            self.assertEqual(new_job["retry_recovery"]["instance"], "B")
            self.assertTrue(new_job["retry_recovery"]["force_restarted"])
            comfyui_post.assert_any_call("/queue", {"delete": ["prompt-stuck-1"]}, base_url="http://b")
            comfyui_post.assert_any_call("/interrupt", {}, base_url="http://b")
            instance_action.assert_called_once_with(node, inst, "force-restart")
            self.assertEqual(len(queued), 1)

    def test_job_status_falls_back_to_completed_history_after_active_job_is_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_gen_db = app.GEN_DB
            app.GEN_DB = str(Path(tmp) / "generation.db")
            try:
                app._init_gen_db()
                app._insert_generation(
                    {
                        "id": "hist-1",
                        "workflow": "t2i-test.json",
                        "filename": "done.png",
                        "thumb": "done_thumb.jpg",
                        "prompt": "cinematic cat",
                        "width": 1024,
                        "height": 1024,
                        "seed": 123,
                        "field_values": {"1::text": "cinematic cat"},
                        "user_id": "u1",
                        "is_public": False,
                        "batch_id": "job-finished",
                        "batch_index": 0,
                        "batch_count": 1,
                    },
                    elapsed=8,
                    user_id="u1",
                )

                result = app.api_job_status("job-finished", current_user={"sub": "u1", "role": "user"})

                self.assertEqual(result["status"], "done")
                self.assertEqual(result["id"], "job-finished")
                self.assertEqual(result["image"], "done.png")
                self.assertEqual(result["thumb"], "done_thumb.jpg")
                self.assertEqual(result["prompt_preview"], "cinematic cat")
            finally:
                app.GEN_DB = old_gen_db


if __name__ == "__main__":
    unittest.main()
