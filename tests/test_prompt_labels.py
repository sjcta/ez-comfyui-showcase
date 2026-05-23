import unittest

from modules.prompt_labels import infer_generation_label


class PromptLabelTests(unittest.TestCase):
    def test_prompt_text_wins_over_upscale_label(self):
        label = infer_generation_label(
            "SeedVR2_upscale_2k.json",
            {"10::resolution": 2048, "20::positive_prompt": "sharp portrait"},
            "放大",
        )
        self.assertEqual(label, "sharp portrait")

    def test_i2v_value_prompt_wins_over_negative_text_field(self):
        label = infer_generation_label(
            "i2v_ltx23_sulphur.json",
            {
                "320:313::text": "text, subtitles, watermarks, logos, jpeg artifacts",
                "320:319::value": "A close-up portrait video with soft camera movement",
            },
            "图生视频",
        )
        self.assertEqual(label, "A close-up portrait video with soft camera movement")

    def test_seedvr_resolution_gets_2k_upscale_label(self):
        label = infer_generation_label(
            "SeedVR2_upscale_2k.json",
            {"10::resolution": 2048},
        )
        self.assertEqual(label, "2K 放大")

    def test_video_upscale_long_edge_hint_keeps_2k_label(self):
        label = infer_generation_label(
            "SeedVR2_video_upscale_2k.json",
            {"10::resolution": 1120, "__video_upscale_long_edge": 2048},
            "放大",
        )
        self.assertEqual(label, "2K 放大")

    def test_workflow_type_gets_4k_upscale_label(self):
        label = infer_generation_label(
            "custom.json",
            {"10::resolution": 4096},
            "放大",
        )
        self.assertEqual(label, "4K 放大")


if __name__ == "__main__":
    unittest.main()
