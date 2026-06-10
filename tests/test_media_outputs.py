import unittest

from modules.media_outputs import collect_preferred_history_outputs, collect_preferred_outputs, output_media_type, output_ref_rel_path


class MediaOutputsTest(unittest.TestCase):
    def test_video_outputs_are_preferred_over_preview_frames(self):
        outputs = {
            "18": {
                "images": [
                    {"filename": "sulphur2_q4_preview_00001_.png", "subfolder": "", "type": "output"},
                    {"filename": "sulphur2_q4_preview_00002_.png", "subfolder": "", "type": "output"},
                ],
            },
            "21": {
                "videos": [
                    {"filename": "sulphur2_q4_00001.mp4", "subfolder": "video", "type": "output"},
                ],
            },
        }

        selected = collect_preferred_outputs(outputs)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["filename"], "sulphur2_q4_00001.mp4")
        self.assertEqual(output_media_type(selected[0]["filename"]), "video")
        self.assertEqual(output_ref_rel_path(selected[0]), "video/sulphur2_q4_00001.mp4")

    def test_save_video_mp4_returned_under_images_is_collected_as_video(self):
        outputs = {
            "4823": {
                "images": [
                    {"filename": "t2v_ltx23_tattoo_00001_.mp4", "subfolder": "video", "type": "output"},
                ],
                "animated": [True],
            },
        }

        selected = collect_preferred_outputs(outputs)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["filename"], "t2v_ltx23_tattoo_00001_.mp4")
        self.assertEqual(output_media_type(selected[0]["filename"]), "video")
        self.assertEqual(output_ref_rel_path(selected[0]), "video/t2v_ltx23_tattoo_00001_.mp4")

    def test_save_image_output_is_preferred_over_reference_or_preview_images(self):
        workflow = {
            "40": {"class_type": "LoadImage"},
            "41": {"class_type": "PreviewImage"},
            "9": {"class_type": "SaveImage"},
        }
        outputs = {
            "40": {
                "images": [
                    {"filename": "uploaded-reference.png", "subfolder": "", "type": "input"},
                ],
            },
            "41": {
                "images": [
                    {"filename": "preview-or-intermediate.png", "subfolder": "", "type": "temp"},
                ],
            },
            "9": {
                "images": [
                    {"filename": "i2i-final-output.png", "subfolder": "", "type": "output"},
                ],
            },
        }

        selected = collect_preferred_outputs(outputs, workflow=workflow)

        self.assertEqual([item["filename"] for item in selected], ["i2i-final-output.png"])
        self.assertEqual(selected[0]["_node_id"], "9")

    def test_history_prompt_graph_is_used_to_prefer_save_node_outputs(self):
        entry = {
            "prompt": [
                1,
                "prompt-id",
                {
                    "40": {"class_type": "LoadImage"},
                    "9": {"class_type": "SaveImage"},
                },
                {},
                ["9"],
            ],
            "outputs": {
                "40": {
                    "images": [
                        {"filename": "reference.png", "subfolder": "", "type": "input"},
                    ],
                },
                "9": {
                    "images": [
                        {"filename": "final.png", "subfolder": "", "type": "output"},
                    ],
                },
            },
        }

        selected = collect_preferred_history_outputs(entry)

        self.assertEqual([item["filename"] for item in selected], ["final.png"])

    def test_history_prompt_graph_detection_skips_extra_data_dicts(self):
        entry = {
            "prompt": [
                7,
                "prompt-id",
                {
                    "40": {"class_type": "LoadImage"},
                    "41": {"class_type": "PreviewImage"},
                    "9": {"class_type": "SaveImage"},
                },
                {"client_id": "abc123"},
                ["9"],
            ],
            "outputs": {
                "40": {
                    "images": [
                        {"filename": "reference.png", "subfolder": "", "type": "input"},
                    ],
                },
                "41": {
                    "images": [
                        {"filename": "preview.png", "subfolder": "", "type": "temp"},
                    ],
                },
                "9": {
                    "images": [
                        {"filename": "saved-output.png", "subfolder": "", "type": "output"},
                    ],
                },
            },
        }

        selected = collect_preferred_history_outputs(entry)

        self.assertEqual([item["filename"] for item in selected], ["saved-output.png"])


if __name__ == "__main__":
    unittest.main()
