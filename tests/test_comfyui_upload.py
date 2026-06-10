import unittest
import os
import tempfile
import json

import modules.comfyui_upload as comfyui_upload
from modules.comfyui_upload import (
    _local_input_path,
    apply_qwen_frame_roll_to_workflow,
    ensure_workflow_images_available,
    workflow_load_images,
)


class ComfyUIUploadTest(unittest.TestCase):
    def test_collects_nested_load_image_paths(self):
        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "u1/2026-05-19/a.png"}},
            "2": {"class_type": "LoadImage", "inputs": {"image": "u1/2026-05-19/a.png"}},
            "4": {"class_type": "LoadVideo", "inputs": {"file": "u1/2026-05-19/a.mp4"}},
            "5": {"class_type": "VHS_LoadVideo", "inputs": {"video": "u1/2026-05-19/b.mp4"}},
            "6": {"class_type": "LoadAudio", "inputs": {"audio": "u1/2026-05-19/c.wav"}},
            "3": {"class_type": "KSampler", "inputs": {"seed": 1}},
        }

        self.assertEqual(
            workflow_load_images(workflow),
            [
                "u1/2026-05-19/a.png",
                "u1/2026-05-19/a.mp4",
                "u1/2026-05-19/b.mp4",
                "u1/2026-05-19/c.wav",
            ],
        )

    def test_collects_ltx_director_timeline_media(self):
        workflow = {
            "1": {
                "class_type": "LTXDirector",
                "inputs": {
                    "timeline_data": json.dumps({
                        "segments": [
                            {"imageFile": "u1/2026-06-01/a.png"},
                            {"imageFile": "u1/2026-06-01/b.png"},
                        ],
                        "audioSegments": [
                            {"audioFile": "u1/2026-06-01/a.wav"},
                        ],
                    })
                },
            },
            "2": {"class_type": "LoadImage", "inputs": {"image": "u1/2026-06-01/a.png"}},
        }

        self.assertEqual(
            workflow_load_images(workflow),
            ["u1/2026-06-01/a.png", "u1/2026-06-01/b.png", "u1/2026-06-01/a.wav"],
        )

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

    def test_upload_media_uses_ssl_context_for_https(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
            tmp.write(b"video")
            tmp.flush()
            calls = {}

            class Response:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def read(self):
                    return b'{"name":"ref.mp4"}'

            old_urlopen = comfyui_upload.urllib.request.urlopen
            try:
                def fake_urlopen(req, timeout=0, context=None):
                    calls["url"] = req.full_url
                    calls["timeout"] = timeout
                    calls["context"] = context
                    return Response()

                comfyui_upload.urllib.request.urlopen = fake_urlopen
                result = comfyui_upload.upload_image_to_comfyui(
                    "https://example.invalid/dgx/8190",
                    tmp.name,
                    "u1/2026-06-05/ref.mp4",
                )
            finally:
                comfyui_upload.urllib.request.urlopen = old_urlopen

            self.assertEqual(result, {"name": "ref.mp4"})
            self.assertEqual(calls["url"], "https://example.invalid/dgx/8190/upload/image")
            self.assertEqual(calls["timeout"], 60)
            self.assertIsNotNone(calls["context"])

    def test_qwen_frame_roll_keeps_reference_image_prompt_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = os.path.join(tmp, "input")
            os.makedirs(os.path.join(input_dir, "u1", "2026-06-01"))
            image_name = "u1/2026-06-01/ref.png"
            image_path = os.path.join(input_dir, "u1", "2026-06-01", "ref.png")
            with open(image_path, "wb") as f:
                f.write(b"img")
            workflow = {
                "78": {"class_type": "LoadImage", "inputs": {"image": image_name}},
                "88": {"class_type": "ImageScaleToMaxDimension", "inputs": {"image": ["78", 0], "largest_size": 16, "upscale_method": "area"}},
                "39": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
                "111": {"class_type": "TextEncodeQwenImageEditPlus", "inputs": {"prompt": "x", "image1": ["78", 0], "vae": ["39", 0]}},
                "97": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["111", 0]}},
                "75": {"class_type": "CFGNorm", "inputs": {"model": ["89", 0], "strength": 1}},
                "188": {"class_type": "VAEEncode", "inputs": {"pixels": ["88", 0], "vae": ["39", 0]}},
                "3": {"class_type": "KSampler", "inputs": {"model": ["75", 0], "positive": ["111", 0], "negative": ["97", 0], "latent_image": ["188", 0], "denoise": 0.7}},
                "910": {
                    "class_type": "QwenMultiangleCameraNode",
                    "inputs": {"image": ["78", 0], "horizontal_angle": 0, "vertical_angle": 0, "zoom": 5},
                },
            }

            replacements = apply_qwen_frame_roll_to_workflow(
                workflow,
                {"__qwen_frame_roll": 12},
                input_dir,
            )

            self.assertEqual(replacements, [])
            self.assertEqual(workflow["78"]["inputs"]["image"], image_name)
            inpaint_nodes = [node_id for node_id, node in workflow.items() if isinstance(node, dict) and node.get("class_type") == "InpaintModelConditioning"]
            self.assertEqual(len(inpaint_nodes), 0)
            self.assertEqual(workflow["3"]["inputs"]["positive"], ["111", 0])
            self.assertEqual(workflow["3"]["inputs"]["negative"], ["97", 0])
            self.assertEqual(workflow["3"]["inputs"]["latent_image"], ["188", 0])
            self.assertEqual(workflow["3"]["inputs"]["denoise"], 0.7)
            differential_nodes = [node_id for node_id, node in workflow.items() if isinstance(node, dict) and node.get("class_type") == "DifferentialDiffusion"]
            self.assertEqual(len(differential_nodes), 0)
            self.assertEqual(workflow["3"]["inputs"]["model"], ["75", 0])
            generated = [
                name
                for name in os.listdir(os.path.dirname(image_path))
                if "_qwen_context_cover_roll_" in name
            ]
            self.assertEqual(generated, [])

    def test_qwen_frame_roll_ignores_non_qwen_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = os.path.join(tmp, "input")
            os.makedirs(input_dir)
            workflow = {"78": {"class_type": "LoadImage", "inputs": {"image": "ref.png"}}}

            replacements = apply_qwen_frame_roll_to_workflow(
                workflow,
                {"__qwen_frame_roll": 12},
                input_dir,
            )

            self.assertEqual(replacements, [])
            self.assertEqual(workflow["78"]["inputs"]["image"], "ref.png")


if __name__ == "__main__":
    unittest.main()
