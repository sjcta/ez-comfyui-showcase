import io
import os
import tempfile
import unittest

from fastapi import HTTPException, UploadFile

import app


class UploadImageApiTests(unittest.TestCase):
    def _upload(self, filename: str, content: bytes):
        upload = UploadFile(io.BytesIO(content), filename=filename)
        return app.asyncio.run(
            app.api_upload_image(upload, current_user={"sub": "u1", "role": "user"})
        )

    def _upload_video(self, filename: str, content: bytes):
        upload = UploadFile(io.BytesIO(content), filename=filename)
        return app.asyncio.run(
            app.api_upload_video(upload, current_user={"sub": "u1", "role": "user"})
        )

    def test_tiff_upload_is_converted_to_png_for_browser_and_comfyui(self):
        from PIL import Image

        old_input = app.COMFYUI_INPUT
        try:
            with tempfile.TemporaryDirectory() as tmp:
                app.COMFYUI_INPUT = tmp
                buf = io.BytesIO()
                Image.new("RGB", (16, 12), (20, 30, 40)).save(buf, format="TIFF")

                result = self._upload("source.tiff", buf.getvalue())

                self.assertTrue(result["filename"].endswith(".png"))
                self.assertTrue(os.path.isfile(result["path"]))
                with Image.open(result["path"]) as saved:
                    self.assertEqual(saved.format, "PNG")
                    self.assertEqual(saved.size, (16, 12))
        finally:
            app.COMFYUI_INPUT = old_input

    def test_gif_upload_uses_first_frame_as_png(self):
        from PIL import Image

        old_input = app.COMFYUI_INPUT
        try:
            with tempfile.TemporaryDirectory() as tmp:
                app.COMFYUI_INPUT = tmp
                buf = io.BytesIO()
                first = Image.new("RGB", (10, 8), (255, 0, 0))
                second = Image.new("RGB", (10, 8), (0, 255, 0))
                first.save(buf, format="GIF", save_all=True, append_images=[second], loop=0)

                result = self._upload("animated.gif", buf.getvalue())

                self.assertTrue(result["filename"].endswith(".png"))
                with Image.open(result["path"]) as saved:
                    self.assertEqual(saved.format, "PNG")
                    self.assertEqual(saved.size, (10, 8))
        finally:
            app.COMFYUI_INPUT = old_input

    def test_cmyk_jpeg_upload_is_normalized_to_png(self):
        from PIL import Image

        old_input = app.COMFYUI_INPUT
        try:
            with tempfile.TemporaryDirectory() as tmp:
                app.COMFYUI_INPUT = tmp
                buf = io.BytesIO()
                Image.new("CMYK", (9, 7), (0, 128, 128, 0)).save(buf, format="JPEG")

                result = self._upload("print-export.jpg", buf.getvalue())

                self.assertTrue(result["filename"].endswith(".png"))
                with Image.open(result["path"]) as saved:
                    self.assertEqual(saved.format, "PNG")
                    self.assertEqual(saved.mode, "RGB")
        finally:
            app.COMFYUI_INPUT = old_input

    def test_extensionless_image_upload_is_detected_and_converted(self):
        from PIL import Image

        old_input = app.COMFYUI_INPUT
        try:
            with tempfile.TemporaryDirectory() as tmp:
                app.COMFYUI_INPUT = tmp
                buf = io.BytesIO()
                Image.new("RGB", (11, 5), (1, 2, 3)).save(buf, format="JPEG")

                result = self._upload("clipboard", buf.getvalue())

                self.assertTrue(result["filename"].endswith(".png"))
                with Image.open(result["path"]) as saved:
                    self.assertEqual(saved.format, "PNG")
                    self.assertEqual(saved.size, (11, 5))
        finally:
            app.COMFYUI_INPUT = old_input

    def test_unknown_upload_extension_is_rejected(self):
        old_input = app.COMFYUI_INPUT
        try:
            with tempfile.TemporaryDirectory() as tmp:
                app.COMFYUI_INPUT = tmp
                with self.assertRaises(HTTPException) as ctx:
                    self._upload("note.txt", b"not an image")
        finally:
            app.COMFYUI_INPUT = old_input

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Unsupported image format", str(ctx.exception.detail))

    def test_mp4_upload_is_stored_for_load_video(self):
        old_input = app.COMFYUI_INPUT
        try:
            with tempfile.TemporaryDirectory() as tmp:
                app.COMFYUI_INPUT = tmp
                result = self._upload_video("clip.mp4", b"\x00\x00\x00\x18ftypmp42")
                self.assertTrue(result["filename"].endswith(".mp4"))
                self.assertTrue(os.path.isfile(result["path"]))
        finally:
            app.COMFYUI_INPUT = old_input

    def test_unknown_video_extension_is_rejected(self):
        old_input = app.COMFYUI_INPUT
        try:
            with tempfile.TemporaryDirectory() as tmp:
                app.COMFYUI_INPUT = tmp
                with self.assertRaises(HTTPException) as ctx:
                    self._upload_video("clip.txt", b"not a video")
        finally:
            app.COMFYUI_INPUT = old_input

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Unsupported video format", str(ctx.exception.detail))


if __name__ == "__main__":
    unittest.main()
