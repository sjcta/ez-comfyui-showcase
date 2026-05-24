import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "data/workflows/DGX Spark/i2v_ltx23_sulphur.json"
CONFIG = ROOT / "data/wf_configs/i2v_ltx23_sulphur.json"


class LtxSulphurI2VWorkflowTests(unittest.TestCase):
    def test_high_res_reference_injection_is_not_overconstrained(self):
        workflow = json.loads(WORKFLOW.read_text())

        self.assertEqual(workflow["320:288"]["class_type"], "LTXVImgToVideoInplace")
        self.assertEqual(workflow["320:288"]["inputs"]["strength"], 0.35)
        self.assertEqual(workflow["320:296"]["inputs"]["strength"], 0.7)

    def test_uses_ltx_video_vae_decode_tail_fix(self):
        workflow = json.loads(WORKFLOW.read_text())
        decode = workflow["320:315"]

        self.assertEqual(decode["class_type"], "LTXVTiledVAEDecode")
        self.assertEqual(decode["inputs"]["latents"], ["320:309", 0])
        self.assertEqual(decode["inputs"]["vae"], ["320:316", 2])
        self.assertTrue(decode["inputs"]["last_frame_fix"])
        self.assertEqual(decode["inputs"]["horizontal_tiles"], 2)
        self.assertEqual(decode["inputs"]["vertical_tiles"], 2)
        self.assertEqual(decode["inputs"]["overlap"], 6)

    def test_negative_prompt_field_is_labeled_explicitly(self):
        config = json.loads(CONFIG.read_text())
        fields = {item["key"]: item for item in config["fields"]}

        self.assertEqual(fields["320:319::value"]["label"], "提示词")
        self.assertEqual(fields["320:319::value"]["zone"], "user_input")
        self.assertEqual(fields["320:313::text"]["label"], "负面提示词")
        self.assertEqual(fields["320:313::text"]["zone"], "advanced")
        self.assertEqual(fields["320:288::strength"]["label"], "高清参考图强度")
        self.assertEqual(fields["320:288::strength"]["zone"], "advanced")
        self.assertEqual(fields["320:296::strength"]["label"], "初始参考图强度")
        self.assertEqual(fields["320:296::strength"]["zone"], "advanced")
        self.assertEqual(fields["320:285::strength_model"]["label"], "蒸馏 LoRA 强度")
        self.assertEqual(fields["320:285::strength_model"]["zone"], "advanced")


if __name__ == "__main__":
    unittest.main()
