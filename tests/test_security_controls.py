import asyncio
import unittest
from types import SimpleNamespace

from fastapi import HTTPException

import app


class SecurityControlTests(unittest.TestCase):
    def tearDown(self):
        app._auth_rate_attempts.clear()

    def test_csrf_token_validates_cookie_and_header_pair(self):
        req = SimpleNamespace(
            cookies={app.CSRF_COOKIE_NAME: "csrf-token"},
            headers={app._CSRF_HEADER_NAME: "csrf-token"},
        )

        self.assertTrue(app._csrf_token_valid(req))

        req.headers[app._CSRF_HEADER_NAME] = "different"
        self.assertFalse(app._csrf_token_valid(req))

    def test_auth_rate_limit_blocks_repeated_attempts(self):
        req = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
        for _ in range(app._AUTH_RATE_LIMIT_MAX_ATTEMPTS):
            app._check_auth_rate_limit(req, "login", "alice")

        with self.assertRaises(HTTPException) as ctx:
            app._check_auth_rate_limit(req, "login", "alice")

        self.assertEqual(ctx.exception.status_code, 429)

    def test_upload_reader_rejects_files_over_limit(self):
        class FakeUpload:
            def __init__(self):
                self._chunks = [b"abc", b"def"]

            async def read(self, size):
                return self._chunks.pop(0) if self._chunks else b""

        async def run():
            with self.assertRaises(HTTPException) as ctx:
                await app._read_upload_limited(FakeUpload(), 5, "Image")
            self.assertEqual(ctx.exception.status_code, 413)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
