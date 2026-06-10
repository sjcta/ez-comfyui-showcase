import os
import tempfile
import unittest
from unittest import mock

import app


class _FakeResponse:
    status = 200

    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._payload


class RemoteOutputDownloadTests(unittest.TestCase):
    def test_download_does_not_reuse_stale_local_file_with_same_name(self):
        prompt_id = "prompt-abc"
        filename = "i2i-output_00001_.png"
        history = {
            prompt_id: {
                "prompt": [
                    1,
                    prompt_id,
                    {"9": {"class_type": "SaveImage"}},
                    {"client_id": "client"},
                    ["9"],
                ],
                "outputs": {
                    "9": {
                        "images": [
                            {"filename": filename, "subfolder": "", "type": "output"},
                        ],
                    },
                },
            }
        }

        with tempfile.TemporaryDirectory() as tmp:
            stale = os.path.join(tmp, filename)
            with open(stale, "wb") as f:
                f.write(b"stale")

            with mock.patch.object(app, "comfyui_get", return_value=history), \
                    mock.patch("urllib.request.urlopen", return_value=_FakeResponse(b"fresh")):
                downloaded = app._download_remote_images_sync(
                    "job-test",
                    prompt_id,
                    "http://comfy.test",
                    tmp,
                )

            self.assertEqual(len(downloaded), 1)
            self.assertNotEqual(downloaded[0], stale)
            self.assertIn(os.path.join(".remote_downloads", prompt_id), downloaded[0])
            with open(downloaded[0], "rb") as f:
                self.assertEqual(f.read(), b"fresh")
            with open(stale, "rb") as f:
                self.assertEqual(f.read(), b"stale")


if __name__ == "__main__":
    unittest.main()
