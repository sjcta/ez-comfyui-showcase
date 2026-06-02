import unittest
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

import app


class LegacyVllmManagementTests(unittest.TestCase):
    def test_vllm_running_is_disabled_by_default_without_docker_probe(self):
        with mock.patch.dict(app.os.environ, {app.LEGACY_VLLM_MANAGEMENT_ENV: ""}, clear=False):
            with mock.patch.object(app.subprocess, "run") as run:
                self.assertFalse(app.vllm_running())

        run.assert_not_called()

    def test_vllm_start_stop_are_noops_when_legacy_management_disabled(self):
        with mock.patch.dict(app.os.environ, {app.LEGACY_VLLM_MANAGEMENT_ENV: ""}, clear=False):
            with mock.patch.object(app.subprocess, "run") as run:
                with mock.patch.object(app.subprocess, "Popen") as popen:
                    self.assertFalse(app.stop_vllm())
                    self.assertFalse(app.start_vllm())

        run.assert_not_called()
        popen.assert_not_called()

    def test_legacy_vllm_api_is_disabled_by_default(self):
        with mock.patch.dict(app.os.environ, {app.LEGACY_VLLM_MANAGEMENT_ENV: ""}, clear=False):
            with self.assertRaises(HTTPException) as ctx:
                app.api_vllm("start", current_user={"role": "admin"})

        self.assertEqual(ctx.exception.status_code, 410)

    def test_generation_enqueue_does_not_probe_legacy_vllm(self):
        queued = []

        class FakeQueue:
            def put_nowait(self, item):
                queued.append(item)

        with tempfile.TemporaryDirectory() as tmp:
            workflow_path = Path(tmp) / "wf.json"
            workflow_path.write_text(
                json.dumps({"1": {"class_type": "SaveImage", "inputs": {}}}),
                encoding="utf-8",
            )
            old_jobs = app.jobs
            old_queue = app._job_queue
            try:
                app.jobs = {}
                app._job_queue = FakeQueue()
                with mock.patch.object(app, "_load_wf_meta", return_value={"wf.json": {}}), \
                        mock.patch.object(app, "_resolve_workflow", return_value=str(workflow_path)), \
                        mock.patch.object(app, "_can_view_workflow", return_value=True), \
                        mock.patch.object(app, "validate_api_prompt", return_value=[]), \
                        mock.patch.object(app, "save_jobs"), \
                        mock.patch.object(app, "add_log"), \
                        mock.patch.object(app, "vllm_running", side_effect=AssertionError("legacy vLLM should not be probed")):
                    result = app.api_generate(
                        app.GenerateRequest(workflow="wf.json", fields={}, seed=123),
                        bg=SimpleNamespace(),
                        current_user={"sub": "u1", "role": "user"},
                    )
            finally:
                app.jobs = old_jobs
                app._job_queue = old_queue

        self.assertIn("job_id", result)
        self.assertEqual(len(queued), 1)
        self.assertFalse(queued[0][4])


if __name__ == "__main__":
    unittest.main()
