import unittest
import os
import tempfile

from modules.comfyui_upload import _local_input_path, workflow_load_images


class ComfyUIUploadTest(unittest.TestCase):
    def test_collects_nested_load_image_paths(self):
        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "u1/2026-05-19/a.png"}},
            "2": {"class_type": "LoadImage", "inputs": {"image": "u1/2026-05-19/a.png"}},
            "3": {"class_type": "KSampler", "inputs": {"seed": 1}},
        }

        self.assertEqual(workflow_load_images(workflow), ["u1/2026-05-19/a.png"])

    def test_resolves_only_canonical_input_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = os.path.join(tmp, "input")
            uploads_dir = os.path.join(tmp, "uploads")
            os.makedirs(input_dir)
            os.makedirs(uploads_dir)
            legacy_path = os.path.join(uploads_dir, "old-ref.png")
            with open(legacy_path, "wb") as f:
                f.write(b"img")

            self.assertEqual(
                _local_input_path(input_dir, "u1/2026-05-19/old-ref.png"),
                os.path.join(input_dir, "u1", "2026-05-19", "old-ref.png"),
            )


if __name__ == "__main__":
    unittest.main()
