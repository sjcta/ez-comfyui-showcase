import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_NAME = "t2v_sulphur2_q4.json"
WORKFLOW = ROOT / "data/workflows/DGX Spark" / WORKFLOW_NAME
CONFIG = ROOT / "data/wf_configs" / WORKFLOW_NAME
META = ROOT / "data/wf_meta.json"


class LtxTattooVideoWorkflowTests(unittest.TestCase):
    def test_workflow_keeps_official_t2v_i2v_conditioning_switch(self):
        workflow = json.loads(WORKFLOW.read_text())

        self.assertEqual(workflow["2004"]["class_type"], "LoadImage")
        self.assertEqual(workflow["4977"]["class_type"], "PrimitiveBoolean")
        self.assertEqual(workflow["4977"]["_meta"]["title"], "bypass_i2v")
        self.assertIs(workflow["4977"]["inputs"]["value"], True)
        self.assertEqual(workflow["3159"]["class_type"], "LTXVImgToVideoConditionOnly")
        self.assertEqual(workflow["3159"]["inputs"]["vae"], ["3940", 2])
        self.assertEqual(workflow["3159"]["inputs"]["image"], ["2004", 0])
        self.assertEqual(workflow["3159"]["inputs"]["latent"], ["3059", 0])
        self.assertEqual(workflow["3159"]["inputs"]["bypass"], ["4977", 0])
        self.assertEqual(workflow["4528"]["inputs"]["video_latent"], ["3159", 0])
        self.assertEqual(workflow["4528"]["inputs"]["audio_latent"], ["3980", 0])
        self.assertEqual(workflow["4802"]["inputs"]["latent_image"], ["4528", 0])
        self.assertEqual(workflow["4983"]["inputs"]["latents"], ["4824", 0])
        self.assertEqual(workflow["4983"]["inputs"]["horizontal_tiles"], 1)
        self.assertEqual(workflow["4983"]["inputs"]["vertical_tiles"], 1)
        self.assertEqual(workflow["4983"]["inputs"]["overlap"], 1)
        self.assertNotIn("audio", workflow["4819"]["inputs"])
        self.assertNotIn("4818", workflow)

    def test_config_exposes_mode_and_conditional_reference_image(self):
        config = json.loads(CONFIG.read_text())
        fields = {item["key"]: item for item in config["fields"]}

        self.assertEqual(config["workflow"], WORKFLOW_NAME)
        self.assertEqual(fields["4977::value"]["type"], "video_mode")
        self.assertEqual(fields["4977::value"]["zone"], "user_input")
        self.assertEqual(fields["4977::value"]["label"], "生成模式")
        self.assertEqual(fields["2004::image"]["type"], "image")
        self.assertEqual(fields["2004::image"]["zone"], "user_input")
        self.assertEqual(fields["2004::image"]["required_when"], {"4977::value": False})
        self.assertLess(fields["4977::value"]["order"], fields["2004::image"]["order"])

    def test_meta_marks_workflow_as_dual_mode_video(self):
        meta = json.loads(META.read_text())
        entry = meta[WORKFLOW_NAME]

        self.assertEqual(entry["name"], "LTX 2.3 文/图生视频（纹身/无音频）")
        self.assertIn("文生视频", entry["tags"])
        self.assertIn("图生视频", entry["tags"])
        self.assertIn("Video", entry["tags"])
        self.assertNotIn("Audio", entry["tags"])


if __name__ == "__main__":
    unittest.main()
