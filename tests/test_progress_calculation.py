import asyncio
import unittest

from modules.step_calculator import StepCalculator
from modules.time_estimator import TimeEstimator
from modules.ws_tracker import WSTracker, PromptStartTimeout


class ProgressCalculationTests(unittest.TestCase):
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
