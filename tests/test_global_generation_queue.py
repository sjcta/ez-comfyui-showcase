import asyncio
import unittest

import app


def _queue_item(job_id, workflow):
    return (job_id, workflow, {}, 1, False, 1024, 1024, "u1", "", "")


class _BlockingRunner:
    def __init__(self):
        self.started = []
        self.first_started = asyncio.Event()
        self.first_release = asyncio.Event()
        self.second_started = asyncio.Event()
        self.second_release = asyncio.Event()

    async def run(self, job_id, *_args, **_kwargs):
        self.started.append(job_id)
        if job_id == "job-one":
            self.first_started.set()
            await self.first_release.wait()
        if job_id == "job-two":
            self.second_started.set()
            await self.second_release.wait()


class GlobalGenerationQueueTest(unittest.TestCase):
    def test_queue_workers_serialize_generation_jobs_globally(self):
        async def run_case():
            old_queue = app._job_queue
            old_runner = app._job_runner
            old_tasks = dict(app._job_tasks)
            app._job_queue = asyncio.Queue()
            app._job_tasks.clear()
            app.jobs["job-one"] = {"id": "job-one", "status": "queued"}
            app.jobs["job-two"] = {"id": "job-two", "status": "queued"}
            runner = _BlockingRunner()
            app._job_runner = runner
            workers = [asyncio.create_task(app._queue_worker()) for _ in range(2)]
            try:
                app._job_queue.put_nowait(_queue_item("job-one", "t2i_flux2_klein.json"))
                app._job_queue.put_nowait(_queue_item("job-two", "i2i_flux2_klein.json"))

                await asyncio.wait_for(runner.first_started.wait(), timeout=3)
                await asyncio.sleep(0.05)
                self.assertEqual(runner.started, ["job-one"])

                runner.first_release.set()
                await asyncio.wait_for(runner.second_started.wait(), timeout=1)
                self.assertEqual(runner.started, ["job-one", "job-two"])
                runner.second_release.set()
                await asyncio.wait_for(app._job_queue.join(), timeout=1)
            finally:
                runner.first_release.set()
                runner.second_release.set()
                for worker in workers:
                    worker.cancel()
                for worker in workers:
                    try:
                        await worker
                    except asyncio.CancelledError:
                        pass
                for task in list(app._job_tasks.values()):
                    if not task.done():
                        task.cancel()
                app._job_queue = old_queue
                app._job_runner = old_runner
                app.jobs.pop("job-one", None)
                app.jobs.pop("job-two", None)
                app._job_tasks.clear()
                app._job_tasks.update(old_tasks)

        asyncio.run(run_case())

    def test_queue_worker_skips_job_cancelled_before_dispatch(self):
        async def run_case():
            old_queue = app._job_queue
            old_runner = app._job_runner
            old_tasks = dict(app._job_tasks)
            app._job_queue = asyncio.Queue()
            app._job_tasks.clear()
            runner = _BlockingRunner()
            app._job_runner = runner
            worker = asyncio.create_task(app._queue_worker())
            try:
                app._job_queue.put_nowait(_queue_item("job-cancelled", "t2i_flux2_klein.json"))
                await asyncio.wait_for(app._job_queue.join(), timeout=1)

                self.assertEqual(runner.started, [])
                self.assertNotIn("job-cancelled", app._job_tasks)
            finally:
                worker.cancel()
                try:
                    await worker
                except asyncio.CancelledError:
                    pass
                app._job_queue = old_queue
                app._job_runner = old_runner
                app._job_tasks.clear()
                app._job_tasks.update(old_tasks)

        asyncio.run(run_case())

    def test_queue_worker_skips_paused_job_and_runs_next(self):
        async def run_case():
            old_queue = app._job_queue
            old_runner = app._job_runner
            old_tasks = dict(app._job_tasks)
            app._job_queue = asyncio.Queue()
            app._job_tasks.clear()
            app.jobs["job-paused"] = {"id": "job-paused", "status": "paused"}
            app.jobs["job-two"] = {"id": "job-two", "status": "queued"}
            runner = _BlockingRunner()
            app._job_runner = runner
            worker = asyncio.create_task(app._queue_worker())
            try:
                app._job_queue.put_nowait(_queue_item("job-paused", "t2i_flux2_klein.json"))
                app._job_queue.put_nowait(_queue_item("job-two", "i2i_flux2_klein.json"))

                await asyncio.wait_for(runner.second_started.wait(), timeout=3)
                self.assertEqual(runner.started, ["job-two"])
                self.assertEqual(app.jobs["job-paused"]["status"], "paused")

                runner.second_release.set()
                await asyncio.wait_for(app._job_queue.join(), timeout=1)
            finally:
                runner.second_release.set()
                worker.cancel()
                try:
                    await worker
                except asyncio.CancelledError:
                    pass
                for task in list(app._job_tasks.values()):
                    if not task.done():
                        task.cancel()
                app._job_queue = old_queue
                app._job_runner = old_runner
                app.jobs.pop("job-paused", None)
                app.jobs.pop("job-two", None)
                app._job_tasks.clear()
                app._job_tasks.update(old_tasks)

        asyncio.run(run_case())

    def test_stale_dispatch_epoch_is_skipped_after_pause_resume_race(self):
        app.jobs["job-epoch"] = {"id": "job-epoch", "status": "queued", "pause_epoch": 2}
        try:
            self.assertTrue(app._job_dispatch_stale_or_paused("job-epoch", 1))
            self.assertFalse(app._job_dispatch_stale_or_paused("job-epoch", 2))
            app.jobs["job-epoch"]["status"] = "paused"
            self.assertTrue(app._job_dispatch_stale_or_paused("job-epoch", 2))
        finally:
            app.jobs.pop("job-epoch", None)

    def test_external_resource_lock_holds_comfyui_jobs_in_queue(self):
        async def run_case():
            old_queue = app._job_queue
            old_runner = app._job_runner
            old_tasks = dict(app._job_tasks)
            old_lock = dict(app._external_resource_lock)
            old_save_jobs = app.save_jobs
            old_broadcast = app.broadcast
            old_add_log = app.add_log
            app._job_queue = asyncio.Queue()
            app._job_tasks.clear()
            app.jobs["job-one"] = {"id": "job-one", "status": "queued"}
            app._external_resource_lock = {
                "project": "JoyAI-Echo",
                "reason": "unit test lock",
                "holder": "tester",
                "created_at": "2026-06-04 00:00:00",
                "expires_at": 9999999999,
                "ttl_sec": 3600,
            }
            app.save_jobs = lambda: None

            async def fake_broadcast(_payload):
                return None

            app.broadcast = fake_broadcast
            app.add_log = lambda *_args, **_kwargs: None
            runner = _BlockingRunner()
            app._job_runner = runner
            worker = asyncio.create_task(app._queue_worker())
            try:
                app._job_queue.put_nowait(_queue_item("job-one", "t2i_flux2_klein.json"))
                await asyncio.sleep(0.08)
                self.assertEqual(runner.started, [])
                self.assertEqual(app.jobs["job-one"]["status"], "queued")
                self.assertIn("resource_lock", app.jobs["job-one"])

                app._external_resource_lock = {}
                await asyncio.wait_for(runner.first_started.wait(), timeout=3)
                self.assertEqual(runner.started, ["job-one"])
                runner.first_release.set()
                await asyncio.wait_for(app._job_queue.join(), timeout=1)
            finally:
                runner.first_release.set()
                worker.cancel()
                try:
                    await worker
                except asyncio.CancelledError:
                    pass
                for task in list(app._job_tasks.values()):
                    if not task.done():
                        task.cancel()
                app._job_queue = old_queue
                app._job_runner = old_runner
                app._job_tasks.clear()
                app._job_tasks.update(old_tasks)
                app.jobs.pop("job-one", None)
                app._external_resource_lock = old_lock
                app.save_jobs = old_save_jobs
                app.broadcast = old_broadcast
                app.add_log = old_add_log

        asyncio.run(run_case())


if __name__ == "__main__":
    unittest.main()
