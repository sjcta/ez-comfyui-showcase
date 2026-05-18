import unittest

from modules.comfyui_upload import workflow_load_images


class ComfyUIUploadTest(unittest.TestCase):
    def test_collects_nested_load_image_paths(self):
        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "u1/2026-05-19/a.png"}},
            "2": {"class_type": "LoadImage", "inputs": {"image": "u1/2026-05-19/a.png"}},
            "3": {"class_type": "KSampler", "inputs": {"seed": 1}},
        }

        self.assertEqual(workflow_load_images(workflow), ["u1/2026-05-19/a.png"])


if __name__ == "__main__":
    unittest.main()
