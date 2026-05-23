import unittest
import os
import tempfile

import modules.comfyui_upload as comfyui_upload
from modules.comfyui_upload import _local_input_path, ensure_workflow_images_available, workflow_load_images


class ComfyUIUploadTest(unittest.TestCase):
    def test_collects_nested_load_image_paths(self):
        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "u1/2026-05-19/a.png"}},
            "2": {"class_type": "LoadImage", "inputs": {"image": "u1/2026-05-19/a.png"}},
            "4": {"class_type": "LoadVideo", "inputs": {"file": "u1/2026-05-19/a.mp4"}},
            "3": {"class_type": "KSampler", "inputs": {"seed": 1}},
        }

        self.assertEqual(workflow_load_images(workflow), ["u1/2026-05-19/a.png", "u1/2026-05-19/a.mp4"])

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

    def test_syncs_history_output_image_reused_as_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = os.path.join(tmp, "input")
            output_dir = os.path.join(tmp, "outputs", "u1", "2026-05-20")
            os.makedirs(input_dir)
            os.makedirs(output_dir)
            image_name = "u1/2026-05-20/i2i-Qwen-Rapid-seedVR2-4k_0001.png"
            output_path = os.path.join(tmp, "outputs", "u1", "2026-05-20", "i2i-Qwen-Rapid-seedVR2-4k_0001.png")
            with open(output_path, "wb") as f:
                f.write(b"img")
            workflow = {"78": {"class_type": "LoadImage", "inputs": {"image": image_name}}}
            uploads = []
            old_upload = comfyui_upload.upload_image_to_comfyui
            try:
                comfyui_upload.upload_image_to_comfyui = lambda base_url, image_path, image_name: uploads.append((base_url, image_path, image_name))
                ensure_workflow_images_available(workflow, input_dir, "http://comfy")
            finally:
                comfyui_upload.upload_image_to_comfyui = old_upload

            self.assertEqual(uploads, [("http://comfy", output_path, image_name)])


if __name__ == "__main__":
    unittest.main()
