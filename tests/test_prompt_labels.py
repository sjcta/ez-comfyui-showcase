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

    def test_internal_style_prompt_metadata_prefixes_only_style_title(self):
        label = infer_generation_label(
            "t2i_ernie_image.json",
            {
                "__style_prompt_text": "[Style Preset: 超写实]",
                "__style_preset_id": "hyperrealistic",
                "20::positive_prompt": "portrait in a rain-lit alley",
            },
        )
        self.assertEqual(label, "超写实｜portrait in a rain-lit alley")

    def test_user_prompt_metadata_wins_over_normalized_ideogram_caption(self):
        label = infer_generation_label(
            "t2i_ideogram4_official_nvfp4.json",
            {
                "__user_prompt": '{"prompt":"橙色猫形机器人在雨夜霓虹街道中央撑透明雨伞","style":{"label":"3D"}}',
                "__style_preset_id": "premium_3d",
                "24::text": (
                    '{"high_level_description":"橙色猫形机器人在雨夜霓虹街道中央撑透明雨伞",'
                    '"style_description":{"aesthetics":"clean high-quality image; 3D; '
                    'High-end 3D render aesthetic; High-end 3D render aesthetic"},'
                    '"compositional_deconstruction":{"background":"橙色猫形机器人在雨夜霓虹街道中央撑透明雨伞","elements":[]}}'
                ),
            },
        )

        self.assertEqual(label, "3D｜橙色猫形机器人在雨夜霓虹街道中央撑透明雨伞")
        self.assertNotIn("High-end 3D", label)
        self.assertNotIn("style_description", label)

    def test_style_prompt_block_is_collapsed_to_style_title_for_cards(self):
        label = infer_generation_label(
            "t2i_ernie_image_turbo.json",
            {
                "__style_preset_id": "anime",
                "__style_prompt_text": "[Style Preset: 动漫 / anime@v2]\n[Style Lock]\n...",
                "94::value": (
                    "[Style Preset: 动漫 / anime@v2]\n"
                    "[Style Lock]\nSTYLE LOCK: final image must be rendered as finished anime character artwork.\n"
                    "[General Style]\nAnime illustration style with clean linework.\n"
                    "[Model Family Tuning: ERNIE]\n画风锁定。\n"
                    "[User Prompt]\n美女洗澡"
                ),
            },
        )
        self.assertEqual(label, "动漫｜美女洗澡")
        self.assertNotIn("Style Lock", label)
        self.assertNotIn("General Style", label)

    def test_style_prompt_title_can_be_read_from_prompt_block_without_metadata(self):
        label = infer_generation_label(
            "t2i_ernie_image_turbo.json",
            {
                "94::value": (
                    "[Style Preset: 3D / premium_3d@v2]\n"
                    "[Style Lock]\nSTYLE LOCK: final image must become a high-end 3D production render.\n"
                    "[User Prompt]\n美女洗澡"
                ),
            },
        )
        self.assertEqual(label, "3D｜美女洗澡")

    def test_new_high_distance_style_ids_prefix_card_labels(self):
        cases = {
            "pixel_game": "像素游戏｜orange cat robot",
            "aaa_game_asset": "AAA游戏资产｜orange cat robot",
            "film_noir": "黑色电影｜orange cat robot",
        }
        for style_id, expected in cases.items():
            with self.subTest(style_id=style_id):
                label = infer_generation_label(
                    "t2i_ernie_image_turbo.json",
                    {
                        "__style_preset_id": style_id,
                        "94::value": "orange cat robot",
                    },
                )
                self.assertEqual(label, expected)

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
