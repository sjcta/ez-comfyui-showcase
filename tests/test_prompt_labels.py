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

    def test_seedvr_resolution_gets_2k_upscale_label(self):
        label = infer_generation_label(
            "SeedVR2_upscale_2k.json",
            {"10::resolution": 2048},
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
