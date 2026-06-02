import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


class JobResumeTest(unittest.TestCase):
    def setUp(self):
        self._old_jobs = dict(app.jobs)
        self._old_job_tasks = dict(app._job_tasks)
        self._old_logs = list(app._log_buffer)
        self._old_jobs_file = app.JOBS_FILE
        self._old_cancelled_file = app.CANCELLED_PROMPTS_FILE
        self._old_cancelled_prompts = dict(app._cancelled_remote_prompts)
        self._tmp = tempfile.TemporaryDirectory()
        app.jobs.clear()
        app._job_tasks.clear()
        app.JOBS_FILE = os.path.join(self._tmp.name, "jobs.json")
        app.CANCELLED_PROMPTS_FILE = os.path.join(self._tmp.name, "cancelled_prompts.json")
        app._cancelled_remote_prompts.clear()

    def tearDown(self):
        app.jobs.clear()
        app.jobs.update(self._old_jobs)
        app._job_tasks.clear()
        app._job_tasks.update(self._old_job_tasks)
        app._log_buffer[:] = self._old_logs
        app.JOBS_FILE = self._old_jobs_file
        app.CANCELLED_PROMPTS_FILE = self._old_cancelled_file
        app._cancelled_remote_prompts.clear()
        app._cancelled_remote_prompts.update(self._old_cancelled_prompts)
        self._tmp.cleanup()

    def test_load_jobs_restores_active_prompt_jobs_instead_of_deleting_file(self):
        persisted = [
            {
                "id": "job-running",
                "status": "generating",
                "workflow": "i2v_ltx23_sulphur.json",
                "instance": "B",
                "prompt_id": "prompt-123",
                "fields": {"1::text": "hello"},
            },
            {"id": "job-done", "status": "done", "workflow": "x.json"},
        ]
        with open(app.JOBS_FILE, "w", encoding="utf-8") as fh:
            json.dump(persisted, fh)

        app.load_jobs()

        self.assertIn("job-running", app.jobs)
        self.assertNotIn("job-done", app.jobs)
        self.assertTrue(os.path.isfile(app.JOBS_FILE))
        self.assertEqual(app.jobs["job-running"]["prompt_id"], "prompt-123")

    def test_save_and_load_jobs_preserves_error_and_cancelled_cards(self):
        app.jobs["job-error"] = {
            "id": "job-error",
            "status": "error",
            "workflow": "x.json",
            "message": "失败",
            "user_id": "u1",
        }
        app.jobs["job-cancelled"] = {
            "id": "job-cancelled",
            "status": "cancelled",
            "workflow": "x.json",
            "message": "任务已取消",
            "user_id": "u1",
        }
        app.jobs["job-done"] = {
            "id": "job-done",
            "status": "done",
            "workflow": "x.json",
            "user_id": "u1",
        }

        app.save_jobs()
        app.jobs.clear()
        app.load_jobs()

        self.assertIn("job-error", app.jobs)
        self.assertIn("job-cancelled", app.jobs)
        self.assertNotIn("job-done", app.jobs)

    def test_error_prompt_job_is_not_scheduled_for_resume(self):
        app.jobs["job-error"] = {
            "id": "job-error",
            "status": "error",
            "workflow": "x.json",
            "instance": "B",
            "prompt_id": "prompt-failed",
        }

        with mock.patch("app.asyncio.create_task") as create_task, \
                mock.patch("app._kick_queued_generation_jobs", return_value=[]):
            app._resume_persisted_generation_jobs()

        create_task.assert_not_called()

    def test_loaded_prompt_id_prevents_remote_prompt_cleanup(self):
        app.jobs["job-running"] = {
            "id": "job-running",
            "status": "generating",
            "instance": "B",
            "prompt_id": "prompt-123",
        }

        untracked = app._untracked_remote_prompt_ids(
            "B",
            {"running_prompt_ids": ["prompt-123"], "pending_prompt_ids": []},
        )

        self.assertEqual(untracked, [])

    def test_resume_persisted_generation_jobs_schedules_prompt_tracker(self):
        app.jobs["job-running"] = {
            "id": "job-running",
            "status": "generating",
            "workflow": "i2v_ltx23_sulphur.json",
            "instance": "B",
            "prompt_id": "prompt-123",
            "fields": {},
            "seed": "123",
        }

        created = []

        async def fake_resume(job_id):
            return job_id

        def fake_create_task(coro):
            created.append(coro)
            return "task"

        with mock.patch("app._resume_persisted_generation_job", new=fake_resume):
            with mock.patch("app.asyncio.create_task", side_effect=fake_create_task):
                app._resume_persisted_generation_jobs()

        self.assertEqual(list(app._job_tasks.keys()), ["job-running"])
        self.assertEqual(created[0].cr_code.co_name, "fake_resume")
        created[0].close()

    def test_missing_in_memory_queued_job_is_requeued(self):
        old_queue = app._job_queue
        app._job_queue = asyncio.Queue()
        app.jobs["job-queued"] = {
            "id": "job-queued",
            "status": "queued",
            "workflow": "i2v_ltx23_sulphur.json",
            "fields": {"1::text": "hello"},
            "seed": "123",
            "width": 1280,
            "height": 720,
            "user_id": "u1",
        }

        try:
            with mock.patch("app._resolve_workflow", return_value="/tmp/i2v_ltx23_sulphur.json"), \
                    mock.patch("app.add_log"):
                requeued = app._kick_queued_generation_jobs("test")
        finally:
            app._job_queue = old_queue

        self.assertEqual(requeued, ["job-queued"])

    def test_prompt_id_can_be_recovered_from_recent_submit_log_tail(self):
        job_id = "job_1234567890_running"
        app._log_buffer.append({
            "job_id": job_id[-12:],
            "msg": "任务已提交: abcdef123456",
        })
        inst = {"name": "B", "url": "http://comfy"}

        with mock.patch("app._get_instance_queue_counts", return_value={
            "running_prompt_ids": ["full-prompt-abcdef123456"],
            "pending_prompt_ids": [],
        }):
            prompt_id = app._recover_prompt_id_from_recent_logs(
                {"id": job_id, "instance": "B"},
                inst,
            )

        self.assertEqual(prompt_id, "full-prompt-abcdef123456")

    def test_untracked_remote_prompt_is_adopted_from_submit_log(self):
        prompt_id = "a2a2604a-f3d1-406e-a655-5fcd50ae35f4"
        app._log_buffer.append({
            "ts": 1234.5,
            "job_id": "0772082_1374",
            "msg": "任务已提交: 5fcd50ae35f4",
            "workflow": "i2v_ltx23_sulphur.json",
            "workflow_type": "图生视频",
            "user_id": "u1",
        })
        inst = {"name": "B", "url": "http://comfy", "_node_id": "n1"}
        created = []

        async def fake_resume(job_id):
            return job_id

        def fake_create_task(coro):
            created.append(coro)
            return "task"

        with mock.patch("app._resolve_workflow", return_value="/tmp/i2v_ltx23_sulphur.json"):
            with mock.patch("app._resume_persisted_generation_job", new=fake_resume):
                with mock.patch("app._job_runner", object()):
                    with mock.patch("app.add_log"):
                        with mock.patch("app.asyncio.create_task", side_effect=fake_create_task):
                            adopted = app._adopt_untracked_remote_prompts(inst, {
                                "running_prompt_ids": [prompt_id],
                                "pending_prompt_ids": [],
                            })

        self.assertEqual(adopted, [prompt_id])
        self.assertIn("job_recovered_0772082_1374", app.jobs)
        recovered = app.jobs["job_recovered_0772082_1374"]
        self.assertEqual(recovered["prompt_id"], prompt_id)
        self.assertEqual(recovered["workflow"], "i2v_ltx23_sulphur.json")
        self.assertEqual(recovered["user_id"], "u1")
        self.assertEqual(recovered["instance"], "B")
        self.assertEqual(list(app._job_tasks.keys()), ["job_recovered_0772082_1374"])
        self.assertEqual(created[0].cr_code.co_name, "fake_resume")
        created[0].close()

    def test_cancelled_remote_prompt_is_not_adopted_again(self):
        prompt_id = "a2a2604a-f3d1-406e-a655-5fcd50ae35f4"
        app._mark_remote_prompt_cancelled("B", prompt_id)
        app._log_buffer.append({
            "ts": 1234.5,
            "job_id": "0772082_1374",
            "msg": "任务已提交: 5fcd50ae35f4",
            "workflow": "i2v_ltx23_sulphur.json",
            "workflow_type": "图生视频",
            "user_id": "u1",
        })

        with mock.patch("app._resolve_workflow", return_value="/tmp/i2v_ltx23_sulphur.json"):
            adopted = app._adopt_untracked_remote_prompts(
                {"name": "B", "url": "http://comfy"},
                {"running_prompt_ids": [prompt_id], "pending_prompt_ids": []},
            )

        self.assertEqual(adopted, [])
        self.assertNotIn("job_recovered_0772082_1374", app.jobs)

    def test_cancel_job_deletes_remote_prompt_and_marks_cancelled(self):
        prompt_id = "prompt-cancel-me"
        app.jobs["job-cancel"] = {
            "id": "job-cancel",
            "status": "generating",
            "instance": "B",
            "prompt_id": prompt_id,
            "user_id": "u1",
        }

        with mock.patch("app._get_enabled_instances", return_value=[{"name": "B", "url": "http://b"}]):
            with mock.patch("app.comfyui_post", return_value={}) as comfyui_post:
                asyncio.run(app.api_cancel_job("job-cancel", current_user={"sub": "u1", "role": "user"}))

        self.assertIn("job-cancel", app.jobs)
        self.assertEqual(app.jobs["job-cancel"]["status"], "cancelled")
        self.assertEqual(app.jobs["job-cancel"]["message"], "任务已取消")
        self.assertTrue(app._remote_prompt_was_cancelled("B", prompt_id))
        comfyui_post.assert_any_call("/queue", {"delete": [prompt_id]}, base_url="http://b")
        comfyui_post.assert_any_call("/interrupt", {}, base_url="http://b")

    def test_dismiss_job_removes_failed_or_cancelled_record(self):
        app.jobs["job-error"] = {
            "id": "job-error",
            "status": "error",
            "workflow": "x.json",
            "user_id": "u1",
        }
        app.jobs["job-active"] = {
            "id": "job-active",
            "status": "generating",
            "workflow": "x.json",
            "user_id": "u1",
        }

        self.assertEqual(app.api_dismiss_job("job-error", current_user={"sub": "u1", "role": "user"}), {"ok": True})
        self.assertNotIn("job-error", app.jobs)
        with self.assertRaises(app.HTTPException) as ctx:
            app.api_dismiss_job("job-active", current_user={"sub": "u1", "role": "user"})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_retry_marks_old_job_retrying_until_new_job_finishes(self):
        workflow_path = os.path.join(self._tmp.name, "retry.json")
        with open(workflow_path, "w", encoding="utf-8") as fh:
            json.dump({"1": {"class_type": "SaveImage", "inputs": {}}}, fh)
        app.jobs["job-error"] = {
            "id": "job-error",
            "status": "error",
            "workflow": "retry.json",
            "fields": {},
            "user_id": "u1",
        }
        old_queue = app._job_queue
        app._job_queue = asyncio.Queue()

        try:
            with mock.patch("app._load_wf_meta", return_value={}), \
                    mock.patch("app._can_view_workflow", return_value=True), \
                    mock.patch("app._resolve_workflow", return_value=workflow_path):
                result = app.api_retry_job("job-error", bg=mock.Mock(), current_user={"sub": "u1", "role": "user"})
        finally:
            app._job_queue = old_queue

        new_id = result["job_id"]
        self.assertEqual(app.jobs["job-error"]["status"], "retrying")
        self.assertEqual(app.jobs["job-error"]["retried_by"], new_id)
        self.assertEqual(app.jobs[new_id]["retry_of"], "job-error")

    def test_queue_prompt_client_id_extracts_comfyui_metadata(self):
        self.assertEqual(
            app._queue_prompt_client_id([1, "prompt-123", {}, {"client_id": "client-list"}]),
            "client-list",
        )
        self.assertEqual(
            app._queue_prompt_client_id({"prompt_id": "prompt-123", "extra_data": {"client_id": "client-dict"}}),
            "client-dict",
        )
        self.assertEqual(app._queue_prompt_client_id(["bad"]), "")

    def test_resume_recovers_client_id_and_starts_ws_progress(self):
        prompt_id = "prompt-resume"
        graph = {"1": {"class_type": "SaveImage", "inputs": {}}}
        app.jobs["job-running"] = {
            "id": "job-running",
            "status": "generating",
            "workflow": "resume.json",
            "instance": "B",
            "prompt_id": prompt_id,
            "fields": {},
            "seed": "123",
        }

        async def fake_save_output(**_kwargs):
            app.jobs["job-running"]["status"] = "done"

        fake_runner = mock.Mock()
        fake_runner._save_output = mock.AsyncMock(side_effect=fake_save_output)

        async def fake_broadcast(_payload):
            return None

        def fake_get(path, base_url=None):
            if path.startswith("/history/"):
                return {prompt_id: {"status": {"completed": True}, "outputs": {}}}
            return {}

        with mock.patch("app._instance_for_job", return_value={"name": "B", "url": "http://comfy"}):
            with mock.patch("app._resolve_workflow", return_value="/tmp/resume.json"):
                with mock.patch("app._remote_queue_prompt_graph", return_value=graph):
                    with mock.patch("app._remote_queue_prompt_client_id", return_value="client-recovered"):
                        with mock.patch("app._start_resume_ws_progress", return_value=None) as start_ws:
                            with mock.patch("app.comfyui_get", side_effect=fake_get):
                                with mock.patch("app.broadcast", side_effect=fake_broadcast):
                                    with mock.patch.object(app, "_job_runner", fake_runner):
                                        asyncio.run(app._resume_persisted_generation_job("job-running"))

        self.assertEqual(app.jobs["job-running"]["client_id"], "client-recovered")
        start_ws.assert_called_once()
        args = start_ws.call_args.args
        self.assertEqual(args[0], "job-running")
        self.assertEqual(args[2], graph)
        self.assertEqual(args[3], prompt_id)
        self.assertEqual(args[4], "client-recovered")

    def test_resume_reserves_instance_before_starting_ws_progress(self):
        prompt_id = "prompt-resume"
        graph = {"1": {"class_type": "SaveImage", "inputs": {}}}
        app.jobs["job-running"] = {
            "id": "job-running",
            "status": "generating",
            "workflow": "resume.json",
            "instance": "B",
            "prompt_id": prompt_id,
            "client_id": "client-resume",
            "fields": {},
            "seed": "123",
        }

        fake_runner = mock.Mock()
        fake_runner._save_output = mock.AsyncMock(side_effect=lambda **_kwargs: app.jobs["job-running"].update(status="done"))
        old_semas = dict(app._instance_semas)
        sem = asyncio.Semaphore(1)

        async def fake_broadcast(_payload):
            return None

        def fake_get(path, base_url=None):
            if path.startswith("/history/"):
                return {prompt_id: {"status": {"completed": True}, "outputs": {}}}
            return {}

        async def run_case():
            await sem.acquire()
            app._instance_semas.clear()
            app._instance_semas["B"] = sem
            with mock.patch("app._instance_for_job", return_value={"name": "B", "url": "http://comfy"}), \
                    mock.patch("app._resolve_workflow", return_value="/tmp/resume.json"), \
                    mock.patch("app._remote_queue_prompt_graph", return_value=graph), \
                    mock.patch("app._start_resume_ws_progress", return_value=None) as start_ws, \
                    mock.patch("app.comfyui_get", side_effect=fake_get), \
                    mock.patch("app.broadcast", side_effect=fake_broadcast), \
                    mock.patch.object(app, "_job_runner", fake_runner):
                task = asyncio.create_task(app._resume_persisted_generation_job("job-running"))
                await asyncio.sleep(0.05)
                self.assertFalse(start_ws.called)
                sem.release()
                await asyncio.wait_for(task, timeout=1)
                self.assertTrue(start_ws.called)

        try:
            asyncio.run(run_case())
        finally:
            app._instance_semas.clear()
            app._instance_semas.update(old_semas)

    def test_job_runner_persists_client_id_before_ws_submit(self):
        src = (Path(__file__).resolve().parents[1] / "modules/job_runner.py").read_text()

        self.assertIn('self._jobs[job_id]["client_id"] = client_id', src)
        self.assertIn("client_id=client_id", src)


if __name__ == "__main__":
    unittest.main()
