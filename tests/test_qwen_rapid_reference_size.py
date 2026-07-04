from pathlib import Path
import json
import tempfile
import unittest

import app


ROOT = Path(__file__).resolve().parents[1]


class QwenRapidReferenceSizeTests(unittest.TestCase):
    def test_qwen_rapid_reference_size_uses_uploaded_image_long_edge(self):
        try:
            from PIL import Image
        except Exception as exc:
            self.skipTest(f"Pillow unavailable: {exc}")

        workflow = json.loads((ROOT / "data/workflows/DGX Spark/i2i-Qwen-Rapid.json").read_text())
        old_input = app.COMFYUI_INPUT
        with tempfile.TemporaryDirectory() as tmp:
            try:
                app.COMFYUI_INPUT = tmp
                image_path = Path(tmp) / "u1" / "portrait.png"
                image_path.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (832, 1248), "white").save(image_path)
                fields = {
                    "78::image": "u1/portrait.png",
                    "88::largest_size": 1024,
                }

                size = app._sync_i2i_reference_dimensions(
                    "i2i-Qwen-Rapid.json",
                    workflow,
                    fields,
                )
            finally:
                app.COMFYUI_INPUT = old_input

        self.assertEqual(size, (832, 1248))
        self.assertEqual(fields["88::largest_size"], 1248)
        self.assertEqual(fields["__qwen_rapid_i2i_source_size"], "832x1248")
        self.assertEqual(fields["__qwen_rapid_i2i_auto_size"], "832x1248")
        self.assertEqual(fields["__qwen_rapid_i2i_largest_size"], 1248)

    def test_qwen_rapid_reference_size_respects_manual_largest_size(self):
        try:
            from PIL import Image
        except Exception as exc:
            self.skipTest(f"Pillow unavailable: {exc}")

        workflow = json.loads((ROOT / "data/workflows/DGX Spark/i2i-Qwen-Rapid.json").read_text())
        old_input = app.COMFYUI_INPUT
        with tempfile.TemporaryDirectory() as tmp:
            try:
                app.COMFYUI_INPUT = tmp
                image_path = Path(tmp) / "u1" / "portrait.png"
                image_path.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (832, 1248), "white").save(image_path)
                fields = {
                    "78::image": "u1/portrait.png",
                    "88::largest_size": 768,
                }

                size = app._sync_i2i_reference_dimensions(
                    "i2i-Qwen-Rapid.json",
                    workflow,
                    fields,
                )
            finally:
                app.COMFYUI_INPUT = old_input

        self.assertEqual(size, (512, 768))
        self.assertEqual(fields["88::largest_size"], 768)


if __name__ == "__main__":
    unittest.main()
