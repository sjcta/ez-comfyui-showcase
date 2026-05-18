import asyncio
import unittest

from modules.step_calculator import StepCalculator
from modules.ws_tracker import WSTracker


class ProgressCalculationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
