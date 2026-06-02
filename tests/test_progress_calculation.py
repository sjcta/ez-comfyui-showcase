import asyncio
import json
from pathlib import Path
import unittest
from unittest import mock

from modules.step_calculator import StepCalculator
from modules.time_estimator import TimeEstimator
from modules.ws_tracker import WSTracker, PromptStartTimeout, PromptSubmitError


class ProgressCalculationTests(unittest.TestCase):
    def test_tracker_uses_persisted_client_id_for_ws_and_prompt_submit(self):
        workflow = {
            "1": {
                "class_type": "SaveImage",
                "inputs": {},
            },
        }
        step_info = StepCalculator().calculate(workflow)
        captured = {}
        tracker = WSTracker(
            job_id="job-client-id-test",
            workflow=workflow,
            step_info=step_info,
            instance_url="http://127.0.0.1:8190",
            node_types={nid: node["class_type"] for nid, node in workflow.items()},
            client_id="client-persisted",
        )

        class CompleteWS:
            async def recv(self):
                return json.dumps({
                    "type": "executing",
                    "data": {"node": None, "prompt_id": "prompt-client"},
                })

            async def close(self):
                pass

        async def fake_connect(url, **_kwargs):
            captured["ws_url"] = url
            return CompleteWS()

        def fake_post(_url, payload):
            captured["payload"] = payload
            return {"prompt_id": "prompt-client"}

        async def run_track():
            with mock.patch("modules.ws_tracker.websockets.client.connect", side_effect=fake_connect):
                with mock.patch("modules.ws_tracker._http_post", side_effect=fake_post):
                    return await tracker.track(timeout=5)

        result = asyncio.run(run_track())

        self.assertTrue(result.ok)
        self.assertIn("clientId=client-persisted", captured["ws_url"])
        self.assertEqual(captured["payload"]["client_id"], "client-persisted")

    def test_waiting_for_execution_reports_zero_progress_until_nodes_start(self):
        workflow = {
            "1": {
                "class_type": "KSampler",
                "inputs": {"steps": 4},
            },
        }
        step_info = StepCalculator().calculate(workflow)
        progress_events = []
        tracker = WSTracker(
            job_id="job-waiting-progress-test",
            workflow=workflow,
            step_info=step_info,
            instance_url="http://127.0.0.1:8190",
            node_types={nid: node["class_type"] for nid, node in workflow.items()},
            progress_callback=lambda progress: progress_events.append(progress),
        )
        tracker.PROMPT_START_TIMEOUT = 0.01
        tracker.WS_SILENT_TIMEOUT = 10

        class QuietWS:
            async def recv(self):
                await asyncio.sleep(1)

            async def close(self):
                pass

        async def fake_connect(*_args, **_kwargs):
            return QuietWS()

        async def run_timeout():
            with mock.patch("modules.ws_tracker.websockets.client.connect", side_effect=fake_connect):
                with mock.patch("modules.ws_tracker._http_post", return_value={"prompt_id": "prompt-waiting"}):
                    with self.assertRaises(PromptStartTimeout):
                        await tracker.track(timeout=5)

        asyncio.run(run_timeout())

        waiting = [event for event in progress_events if event.get("message") == "等待实例开始执行..."]
        self.assertTrue(waiting)
        self.assertEqual(waiting[-1]["pct"], 0)
        submitting = [event for event in progress_events if event.get("message") == "提交工作流..."]
        self.assertTrue(submitting)
        self.assertEqual(submitting[-1]["pct"], 0)

    def test_flux2_sampler_uses_scheduler_steps_so_setup_nodes_do_not_frontload_progress(self):
        workflow_path = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "workflows"
            / "DGX Spark"
            / "t2i_flux2_dev_turbo_q4km.json"
        )
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        step_info = StepCalculator().calculate(workflow)

        self.assertIn("13", step_info.sampler_steps)
        self.assertEqual(step_info.sampler_steps["13"], 8)
        self.assertGreater(step_info.node_weights["13"], step_info.node_weights["38"] * 10)

        tracker = WSTracker(
            job_id="job-flux2-progress-test",
            workflow=workflow,
            step_info=step_info,
            instance_url="http://127.0.0.1:8190",
            node_types={nid: node["class_type"] for nid, node in workflow.items()},
        )
        tracker._last_pct = 0

        async def run_sequence():
            pct_by_node = {}
            for nid in ("10", "47", "48", "16", "38"):
                await tracker._handle_executing(
                    {"node": nid},
                    step_info.total_units,
                    step_info.node_weights,
                )
                pct_by_node[nid] = tracker._calc_pct()
            return pct_by_node

        pct_by_node = asyncio.run(run_sequence())

        self.assertEqual(pct_by_node["10"], 0)
        self.assertLess(pct_by_node["38"], 10)

    def test_sampler_and_upscale_share_ninety_percent_budget(self):
        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "input.png"}},
            "2": {"class_type": "KSampler", "inputs": {"steps": 8, "denoise": 1.0}},
            "3": {"class_type": "SeedVR2VideoUpscaler", "inputs": {"image": ["1", 0], "resolution": 2048}},
            "4": {"class_type": "SaveImage", "inputs": {"images": ["3", 0]}},
        }
        step_info = StepCalculator().calculate(workflow)

        self.assertAlmostEqual(step_info.total_units, 100.0)
        self.assertAlmostEqual(step_info.node_weights["2"], 45.0)
        self.assertAlmostEqual(step_info.node_weights["3"], 45.0)
        self.assertAlmostEqual(step_info.node_weights["1"], 5.0)
        self.assertAlmostEqual(step_info.node_weights["4"], 5.0)

        tracker = WSTracker(
            job_id="job-budget-progress-test",
            workflow=workflow,
            step_info=step_info,
            instance_url="http://127.0.0.1:8190",
            node_types={nid: node["class_type"] for nid, node in workflow.items()},
        )

        async def run_sequence():
            await tracker._handle_executing({"node": "1"}, step_info.total_units, step_info.node_weights)
            await tracker._handle_executed({"node": "1"})
            after_load = tracker._calc_pct()

            await tracker._handle_executing({"node": "2"}, step_info.total_units, step_info.node_weights)
            await tracker._handle_progress({"node": "2", "value": 1, "max": 8}, step_info.total_units, step_info.node_weights)
            after_one_sampler_step = tracker._calc_pct()
            await tracker._handle_progress({"node": "2", "value": 8, "max": 8}, step_info.total_units, step_info.node_weights)
            after_sampler = tracker._calc_pct()

            await tracker._handle_executing({"node": "3"}, step_info.total_units, step_info.node_weights)
            await tracker._handle_progress({"node": "3", "value": 5, "max": 100}, step_info.total_units, step_info.node_weights)
            after_upscale_five = tracker._calc_pct()
            return after_load, after_one_sampler_step, after_sampler, after_upscale_five

        after_load, after_one_sampler_step, after_sampler, after_upscale_five = asyncio.run(run_sequence())

        self.assertAlmostEqual(after_load, 5.0)
        self.assertAlmostEqual(after_one_sampler_step, 10.625)
        self.assertAlmostEqual(after_sampler, 50.0)
        self.assertAlmostEqual(after_upscale_five, 52.25)

    def test_sampler_and_two_upscales_split_ninety_percent_three_ways(self):
        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "input.png"}},
            "2": {"class_type": "KSampler", "inputs": {"steps": 8, "denoise": 1.0}},
            "3": {"class_type": "ImageUpscaleWithModel", "inputs": {"image": ["1", 0]}},
            "4": {"class_type": "SeedVR2VideoUpscaler", "inputs": {"image": ["3", 0], "resolution": 4096}},
            "5": {"class_type": "SaveImage", "inputs": {"images": ["4", 0]}},
        }
        step_info = StepCalculator().calculate(workflow)

        self.assertAlmostEqual(step_info.total_units, 100.0)
        self.assertAlmostEqual(step_info.node_weights["2"], 30.0)
        self.assertAlmostEqual(step_info.node_weights["3"], 30.0)
        self.assertAlmostEqual(step_info.node_weights["4"], 30.0)
        self.assertAlmostEqual(step_info.node_weights["1"], 5.0)
        self.assertAlmostEqual(step_info.node_weights["5"], 5.0)

    def test_prompt_submit_error_is_raised_with_details(self):
        workflow = {
            "1": {
                "class_type": "SaveImage",
                "inputs": {},
            },
        }
        step_info = StepCalculator().calculate(workflow)
        tracker = WSTracker(
            job_id="job-submit-error-test",
            workflow=workflow,
            step_info=step_info,
            instance_url="http://127.0.0.1:8190",
            node_types={nid: node["class_type"] for nid, node in workflow.items()},
        )

        class FakeWS:
            async def close(self):
                pass

        async def fake_connect(*_args, **_kwargs):
            return FakeWS()

        async def run_submit_error():
            with mock.patch("modules.ws_tracker.websockets.client.connect", side_effect=fake_connect):
                with mock.patch(
                    "modules.ws_tracker._http_post",
                    side_effect=RuntimeError("HTTP Error 400: validation failed"),
                ):
                    with self.assertRaises(PromptSubmitError) as ctx:
                        await tracker.track(timeout=1)
            self.assertIn("validation failed", str(ctx.exception))

        asyncio.run(run_submit_error())

    def test_prompt_start_timeout_raises_before_long_ws_timeout(self):
        workflow = {
            "1": {
                "class_type": "KSampler",
                "inputs": {"steps": 4},
            },
        }
        step_info = StepCalculator().calculate(workflow)
        tracker = WSTracker(
            job_id="job-submit-stall-test",
            workflow=workflow,
            step_info=step_info,
            instance_url="http://127.0.0.1:8190",
            node_types={nid: node["class_type"] for nid, node in workflow.items()},
        )
        tracker.PROMPT_START_TIMEOUT = 0.01
        tracker.WS_SILENT_TIMEOUT = 10
        tracker._start_time = 0
        tracker._prompt_id = "prompt-stalled"
        tracker._prompt_started = False

        class QuietWS:
            async def recv(self):
                await asyncio.sleep(1)

        async def run_timeout():
            with self.assertRaises(PromptStartTimeout):
                await tracker._ws_track_loop(QuietWS(), timeout=5)

        asyncio.run(run_timeout())

    def test_http_polling_keeps_waiting_after_transient_connection_refused(self):
        workflow = {
            "1": {
                "class_type": "SaveVideo",
                "inputs": {},
            },
        }
        step_info = StepCalculator().calculate(workflow)
        tracker = WSTracker(
            job_id="job-http-transient-test",
            workflow=workflow,
            step_info=step_info,
            instance_url="http://127.0.0.1:8190",
            node_types={nid: node["class_type"] for nid, node in workflow.items()},
        )
        tracker.HTTP_POLL_INTERVAL = 0
        tracker._start_time = 0
        tracker._prompt_id = "prompt-video"
        calls = []

        def fake_get(_url):
            calls.append(_url)
            if len(calls) == 1:
                raise RuntimeError(
                    "HTTP GET http://127.0.0.1:8190/history/prompt-video 失败: "
                    "<urlopen error [Errno 61] Connection refused>"
                )
            return {"prompt-video": {"status": {"completed": True}}}

        async def run_poll():
            with mock.patch("modules.ws_tracker._http_get", side_effect=fake_get):
                return await tracker._http_poll_track(timeout=1)

        result = asyncio.run(run_poll())

        self.assertTrue(result.ok)
        self.assertEqual(result.prompt_id, "prompt-video")
        self.assertGreaterEqual(len(calls), 2)

    def test_http_polling_surfaces_comfyui_execution_error_message(self):
        workflow = {
            "1": {
                "class_type": "SaveVideo",
                "inputs": {},
            },
        }
        step_info = StepCalculator().calculate(workflow)
        tracker = WSTracker(
            job_id="job-http-error-test",
            workflow=workflow,
            step_info=step_info,
            instance_url="http://127.0.0.1:8190",
            node_types={nid: node["class_type"] for nid, node in workflow.items()},
        )
        tracker.HTTP_POLL_INTERVAL = 0
        tracker._start_time = 0
        tracker._prompt_id = "prompt-error"

        def fake_get(_url):
            return {
                "prompt-error": {
                    "status": {
                        "status_str": "error",
                        "messages": [
                            ["execution_start", {"prompt_id": "prompt-error"}],
                            [
                                "execution_error",
                                {
                                    "exception_message": "list index out of range",
                                    "exception_type": "IndexError",
                                },
                            ],
                        ],
                    }
                }
            }

        async def run_poll():
            with mock.patch("modules.ws_tracker._http_get", side_effect=fake_get):
                return await tracker._http_poll_track(timeout=1)

        with self.assertRaisesRegex(RuntimeError, "ComfyUI: list index out of range"):
            asyncio.run(run_poll())

    def test_normal_nodes_complete_on_executed_not_executing(self):
        workflow = {
            "1": {
                "class_type": "KSampler",
                "inputs": {"steps": 4, "denoise": 1.0},
                "_meta": {"title": "K采样器"},
            },
            "2": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["1", 0]},
                "_meta": {"title": "VAE解码"},
            },
            "3": {
                "class_type": "SaveImage",
                "inputs": {"images": ["2", 0]},
                "_meta": {"title": "保存图像"},
            },
        }
        step_info = StepCalculator().calculate(workflow)
        tracker = WSTracker(
            job_id="job-progress-test",
            workflow=workflow,
            step_info=step_info,
            instance_url="http://127.0.0.1:8190",
            node_types={nid: node["class_type"] for nid, node in workflow.items()},
        )

        async def run_sequence():
            await tracker._handle_executing({"node": "1"}, step_info.total_units, step_info.node_weights)
            await tracker._handle_progress({"node": "1", "value": 4, "max": 4}, step_info.total_units, step_info.node_weights)
            after_sampler = tracker._calc_pct()

            await tracker._handle_executing({"node": "2"}, step_info.total_units, step_info.node_weights)
            vae_started = tracker._calc_pct()
            await tracker._handle_executed({"node": "2"})
            vae_done = tracker._calc_pct()

            await tracker._handle_executing({"node": "3"}, step_info.total_units, step_info.node_weights)
            save_started = tracker._calc_pct()
            await tracker._handle_executed({"node": "3"})
            save_done = tracker._calc_pct()

            await tracker._handle_executing({"node": None}, step_info.total_units, step_info.node_weights)
            workflow_done = tracker._calc_pct()
            return after_sampler, vae_started, vae_done, save_started, save_done, workflow_done

        after_sampler, vae_started, vae_done, save_started, save_done, workflow_done = asyncio.run(run_sequence())

        self.assertLess(after_sampler, 96)
        self.assertEqual(vae_started, after_sampler)
        self.assertGreater(vae_done, vae_started)
        self.assertEqual(save_started, vae_done)
        self.assertLess(save_started, 100)
        self.assertGreater(save_done, save_started)
        self.assertEqual(workflow_done, 100)

    def test_normal_nodes_are_counted_when_execution_advances_without_executed_event(self):
        workflow = {
            "60": {"class_type": "PrimitiveInt", "inputs": {"value": 2}},
            "30": {"class_type": "EmptyLatentImage", "inputs": {}},
            "64": {"class_type": "VAELoader", "inputs": {}},
            "65": {"class_type": "CLIPLoader", "inputs": {}},
            "67": {"class_type": "UNETLoader", "inputs": {}},
            "68": {"class_type": "CLIPTextEncode", "inputs": {}},
            "29": {"class_type": "ConditioningZeroOut", "inputs": {}},
            "27": {"class_type": "KSampler", "inputs": {"steps": 8, "denoise": 1.0}},
            "31": {"class_type": "VAEDecode", "inputs": {"samples": ["27", 0]}},
            "71": {"class_type": "ImageScaleBy", "inputs": {"image": ["31", 0]}},
            "72": {"class_type": "VAEEncode", "inputs": {"pixels": ["71", 0]}},
            "35": {"class_type": "KSampler", "inputs": {"steps": 2, "denoise": 0.25}},
            "37": {"class_type": "VAEDecode", "inputs": {"samples": ["35", 0]}},
            "40": {"class_type": "ImageScaleBy", "inputs": {"image": ["37", 0]}},
            "61": {"class_type": "SaveImage", "inputs": {"images": ["40", 0]}},
        }
        step_info = StepCalculator().calculate(workflow)
        self.assertEqual(step_info.node_weights["60"], 0.0)
        tracker = WSTracker(
            job_id="job-executing-transition-progress-test",
            workflow=workflow,
            step_info=step_info,
            instance_url="http://127.0.0.1:8190",
            node_types={nid: node["class_type"] for nid, node in workflow.items()},
        )

        async def run_sequence():
            for nid in ("64", "30", "65", "68", "29", "67", "27"):
                await tracker._handle_executing({"node": nid}, step_info.total_units, step_info.node_weights)
            first_sampler_started = tracker._calc_pct()
            await tracker._handle_progress({"node": "27", "value": 8, "max": 8}, step_info.total_units, step_info.node_weights)
            first_sampler_done = tracker._calc_pct()

            for nid in ("31", "71", "72", "35"):
                await tracker._handle_executing({"node": nid}, step_info.total_units, step_info.node_weights)
            second_sampler_started = tracker._calc_pct()
            await tracker._handle_progress({"node": "35", "value": 2, "max": 2}, step_info.total_units, step_info.node_weights)
            second_sampler_done = tracker._calc_pct()

            for nid in ("37", "40", "61"):
                await tracker._handle_executing({"node": nid}, step_info.total_units, step_info.node_weights)
            save_started = tracker._calc_pct()
            await tracker._handle_executing({"node": None}, step_info.total_units, step_info.node_weights)
            workflow_done = tracker._calc_pct()
            return first_sampler_started, first_sampler_done, second_sampler_started, second_sampler_done, save_started, workflow_done

        (
            first_sampler_started,
            first_sampler_done,
            second_sampler_started,
            second_sampler_done,
            save_started,
            workflow_done,
        ) = asyncio.run(run_sequence())

        self.assertGreater(first_sampler_started, 0)
        self.assertLess(first_sampler_started, 10)
        self.assertGreater(first_sampler_done, 49)
        self.assertLess(first_sampler_done, 51)
        self.assertGreater(second_sampler_started, first_sampler_done)
        self.assertGreater(second_sampler_done, 95)
        self.assertGreater(save_started, second_sampler_done)
        self.assertLess(save_started, 100)
        self.assertEqual(workflow_done, 100)

    def test_seedvr_upscale_uses_time_estimated_progress(self):
        workflow = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": "input.png"},
            },
            "2": {
                "class_type": "SeedVR2VideoUpscaler",
                "inputs": {"image": ["1", 0], "resolution": 2048, "seed": 42},
            },
            "3": {
                "class_type": "SaveImage",
                "inputs": {"images": ["2", 0]},
            },
        }
        step_info = StepCalculator().calculate(workflow)

        self.assertIn("2", step_info.time_estimates)
        self.assertEqual(step_info.time_estimates["2"], TimeEstimator.estimate("SeedVR2VideoUpscaler", 2048))
        self.assertGreater(step_info.node_weights["2"], step_info.node_weights["1"])

        tracker = WSTracker(
            job_id="job-upscale-progress-test",
            workflow=workflow,
            step_info=step_info,
            instance_url="http://127.0.0.1:8190",
            node_types={nid: node["class_type"] for nid, node in workflow.items()},
        )

        async def run_sequence():
            await tracker._handle_executing({"node": "1"}, step_info.total_units, step_info.node_weights)
            await tracker._handle_executed({"node": "1"})
            before_upscale = tracker._calc_pct()

            await tracker._handle_executing({"node": "2"}, step_info.total_units, step_info.node_weights)
            upscale_started = tracker._calc_pct()
            entered = tracker._node_entered_at["2"]
            tracker._node_entered_at["2"] = entered - (step_info.time_estimates["2"] / 2)
            await tracker._refresh_delayed_node_loop_once_for_test()
            halfway = tracker._calc_pct()
            await tracker._handle_executed({"node": "2"})
            upscale_done = tracker._calc_pct()

            await tracker._handle_executing({"node": "3"}, step_info.total_units, step_info.node_weights)
            await tracker._handle_executed({"node": "3"})
            save_done = tracker._calc_pct()
            return before_upscale, upscale_started, halfway, upscale_done, save_done

        before_upscale, upscale_started, halfway, upscale_done, save_done = asyncio.run(run_sequence())

        self.assertEqual(upscale_started, before_upscale)
        self.assertGreater(halfway, upscale_started)
        self.assertLess(halfway, 96)
        self.assertGreater(upscale_done, halfway)
        self.assertGreater(save_done, upscale_done)


if __name__ == "__main__":
    unittest.main()
