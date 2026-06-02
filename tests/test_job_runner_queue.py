import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from modules.job_runner import JobRunner, TrackResult, PromptStartTimeout


class _FakeInstanceManager:
    def __init__(self):
        self.ensure_started = asyncio.Event()
        self.ensure_calls = 0

    async def ensure_running(self, _instance, timeout=300):
        self.ensure_calls += 1
        self.ensure_started.set()
        return True


class _FakeTracker:
    def __init__(self, *args, **kwargs):
        self.prompt_id = "prompt-next"

    async def track(self, timeout=900):
        return TrackResult(ok=True, prompt_id=self.prompt_id, elapsed=1.0)


class JobRunnerQueueTest(unittest.TestCase):
    def test_submit_stall_retry_does_not_recursively_restart_vllm(self):
        async def run_case():
            jobs = {
                "job-retry": {
                    "id": "job-retry",
                    "status": "queued",
                    "workflow": "retry.json",
                    "fields": {},
                    "seed": "1",
                },
            }
            fake_mgr = _FakeInstanceManager()
            semas = {"A": asyncio.Semaphore(1)}
            calls = {"track": 0, "stop_vllm": 0, "start_vllm": 0, "recover": 0}

            class RetryTracker:
                def __init__(self, *args, **kwargs):
                    pass

                async def track(self, timeout=900):
                    calls["track"] += 1
                    if calls["track"] == 1:
                        raise PromptStartTimeout("prompt-stalled", 45)
                    return TrackResult(ok=True, prompt_id="prompt-ok", elapsed=1.0)

            async def fake_recover(*_args):
                calls["recover"] += 1

            with tempfile.TemporaryDirectory() as tmp:
                workflow_path = Path(tmp) / "retry.json"
                workflow_path.write_text(
                    json.dumps({"1": {"class_type": "SaveImage", "inputs": {}}}),
                    encoding="utf-8",
                )

                runner = JobRunner(
                    inst_mgr=fake_mgr,
                    jobs=jobs,
                    history=[],
                    broadcast_fn=lambda _payload: asyncio.sleep(0),
                    add_log_fn=lambda *_args, **_kwargs: None,
                    save_jobs_fn=lambda: None,
                    save_history_fn=lambda: None,
                    make_thumbnail_fn=lambda _path: "",
                    get_image_size_fn=lambda _path: (0, 0),
                    comfyui_up_fn=lambda _url: True,
                    comfyui_get_fn=lambda _path, _url: {"queue_running": [], "queue_pending": []},
                    download_images_fn=lambda *_args: [],
                    vllm_running_fn=lambda: True,
                    stop_vllm_fn=lambda: calls.__setitem__("stop_vllm", calls["stop_vllm"] + 1),
                    start_vllm_fn=lambda: calls.__setitem__("start_vllm", calls["start_vllm"] + 1),
                    get_node_by_id_fn=lambda _node_id: None,
                    run_instance_action_fn=lambda *_args: True,
                    instance_semas=semas,
                    instance_group={},
                    instance_last_active={},
                    output_dir=tmp,
                    history_dir=tmp,
                    input_dir=tmp,
                    get_enabled_instances_fn=lambda: [{"name": "A", "id": "i-a", "url": "http://a"}],
                )
                runner._recover_submit_stall = fake_recover

                async def fake_save_output(**_kwargs):
                    jobs["job-retry"]["status"] = "done"

                runner._save_output = fake_save_output

                with mock.patch("modules.job_runner.validate_api_prompt", return_value=[]), \
                        mock.patch("modules.job_runner.ensure_workflow_images_available"), \
                        mock.patch("modules.job_runner.WSTracker", RetryTracker):
                    await runner.run("job-retry", str(workflow_path), {}, 1, True)

            self.assertEqual(calls["track"], 2)
            self.assertEqual(calls["recover"], 1)
            self.assertEqual(calls["stop_vllm"], 2)
            self.assertEqual(calls["start_vllm"], 1)
            self.assertFalse(semas["A"].locked())
            self.assertEqual(jobs["job-retry"]["status"], "done")
            self.assertEqual(jobs["job-retry"].get("failed_instances"), ["A"])

        asyncio.run(run_case())

    def test_running_job_blocks_next_job_before_cold_start(self):
        async def run_case():
            jobs = {
                "job-running": {
                    "id": "job-running",
                    "status": "generating",
                    "instance": "B",
                    "prompt_id": "prompt-running",
                    "last_update": 100.0,
                },
                "job-next": {
                    "id": "job-next",
                    "status": "queued",
                    "workflow": "resume.json",
                    "fields": {},
                    "seed": "1",
                },
            }
            broadcasts = []
            fake_mgr = _FakeInstanceManager()
            semas = {"B": asyncio.Semaphore(1)}

            async def fake_broadcast(payload):
                broadcasts.append(payload)

            with tempfile.TemporaryDirectory() as tmp:
                workflow_path = Path(tmp) / "resume.json"
                workflow_path.write_text(
                    json.dumps({"1": {"class_type": "SaveImage", "inputs": {}}}),
                    encoding="utf-8",
                )

                runner = JobRunner(
                    inst_mgr=fake_mgr,
                    jobs=jobs,
                    history=[],
                    broadcast_fn=fake_broadcast,
                    add_log_fn=lambda *_args, **_kwargs: None,
                    save_jobs_fn=lambda: None,
                    save_history_fn=lambda: None,
                    make_thumbnail_fn=lambda _path: "",
                    get_image_size_fn=lambda _path: (0, 0),
                    comfyui_up_fn=lambda _url: True,
                    comfyui_get_fn=lambda _path, _url: {"queue_running": [], "queue_pending": []},
                    download_images_fn=lambda *_args: [],
                    vllm_running_fn=lambda: False,
                    stop_vllm_fn=lambda: None,
                    start_vllm_fn=lambda: None,
                    get_node_by_id_fn=lambda _node_id: None,
                    run_instance_action_fn=lambda *_args: True,
                    instance_semas=semas,
                    instance_group={},
                    instance_last_active={},
                    output_dir=tmp,
                    history_dir=tmp,
                    input_dir=tmp,
                    get_enabled_instances_fn=lambda: [{"name": "B", "id": "i-b", "url": "http://b"}],
                )

                async def fake_save_output(**_kwargs):
                    jobs["job-next"]["status"] = "done"

                runner._save_output = fake_save_output

                with mock.patch("modules.job_runner.validate_api_prompt", return_value=[]), \
                        mock.patch("modules.job_runner.ensure_workflow_images_available"), \
                        mock.patch("modules.job_runner.WSTracker", _FakeTracker):
                    task = asyncio.create_task(
                        runner.run(
                            "job-next",
                            str(workflow_path),
                            {},
                            1,
                            False,
                            preferred_instance="B",
                        )
                    )
                    await asyncio.sleep(0.05)
                    self.assertEqual(fake_mgr.ensure_calls, 0)
                    self.assertEqual(jobs["job-next"]["status"], "queued")
                    self.assertIn("排队等待 B 当前任务完成", jobs["job-next"]["message"])

                    jobs["job-running"]["status"] = "done"
                    await asyncio.wait_for(fake_mgr.ensure_started.wait(), timeout=3)
                    await asyncio.wait_for(task, timeout=3)

            self.assertEqual(fake_mgr.ensure_calls, 1)
            self.assertEqual(jobs["job-next"]["status"], "done")

        asyncio.run(run_case())


if __name__ == "__main__":
    unittest.main()
