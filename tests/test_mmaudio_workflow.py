import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "data" / "workflows" / "DGX Spark" / "video_sfx_mmaudio.json"
CONFIG = ROOT / "data" / "wf_configs" / "video_sfx_mmaudio.json"
META = ROOT / "data" / "wf_meta.json"


class MMAudioWorkflowTest(unittest.TestCase):
    def test_workflow_uses_video_conditioned_mmaudio_chain(self):
        workflow = json.loads(WORKFLOW.read_text())

        self.assertEqual(workflow["91"]["class_type"], "VHS_LoadVideo")
        self.assertEqual(workflow["92"]["class_type"], "MMAudioSampler")
        self.assertEqual(workflow["106"]["class_type"], "PrimitiveBoolean")
        self.assertEqual(workflow["107"]["class_type"], "AudioMerge")
        self.assertEqual(workflow["108"]["class_type"], "ComfySwitchNode")
        self.assertEqual(workflow["97"]["class_type"], "VHS_VideoCombine")
        self.assertEqual(workflow["92"]["inputs"]["images"], ["91", 0])
        self.assertEqual(workflow["106"]["inputs"]["value"], False)
        self.assertEqual(workflow["107"]["inputs"]["audio1"], ["91", 2])
        self.assertEqual(workflow["107"]["inputs"]["audio2"], ["92", 0])
        self.assertEqual(workflow["107"]["inputs"]["merge_method"], "mean")
        self.assertEqual(workflow["108"]["inputs"]["switch"], ["106", 0])
        self.assertEqual(workflow["108"]["inputs"]["on_false"], ["92", 0])
        self.assertEqual(workflow["108"]["inputs"]["on_true"], ["107", 0])
        self.assertEqual(workflow["97"]["inputs"]["audio"], ["108", 0])
        self.assertEqual(workflow["97"]["inputs"]["save_output"], True)
        self.assertEqual(workflow["85"]["inputs"]["base_precision"], "fp16")
        self.assertIn("fp16", workflow["85"]["inputs"]["mmaudio_model"])
        self.assertEqual(workflow["91"]["inputs"]["custom_width"], 0)
        self.assertEqual(workflow["91"]["inputs"]["custom_height"], 0)

    def test_config_exposes_video_prompt_and_generation_controls(self):
        config = json.loads(CONFIG.read_text())
        fields = {field["key"]: field for field in config["fields"]}

        self.assertEqual(fields["91::video"]["type"], "video")
        self.assertEqual(fields["92::prompt"]["zone"], "user_input")
        self.assertEqual(fields["106::value"]["zone"], "user_input")
        self.assertEqual(fields["106::value"]["type"], "toggle")
        self.assertEqual(fields["106::value"]["label"], "保留原声")
        self.assertEqual(fields["92::negative_prompt"]["zone"], "advanced")
        self.assertEqual(fields["92::seed"]["type"], "seed")
        self.assertEqual(fields["97::filename_prefix"]["zone"], "output")

    def test_meta_keeps_mmaudio_workflow_admin_only(self):
        meta = json.loads(META.read_text())
        entry = meta["video_sfx_mmaudio.json"]

        self.assertEqual(entry["source"], "DGX Spark")
        self.assertFalse(entry["shared"])
        self.assertEqual(entry["tags"][0], "测试")


if __name__ == "__main__":
    unittest.main()
