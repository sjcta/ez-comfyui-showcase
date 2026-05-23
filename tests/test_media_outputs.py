import unittest

from modules.media_outputs import collect_preferred_outputs, output_media_type, output_ref_rel_path


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


if __name__ == "__main__":
    unittest.main()
