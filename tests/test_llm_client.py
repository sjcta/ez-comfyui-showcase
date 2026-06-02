import io
import json
import unittest
import urllib.error

from modules import llm_client


class LlmClientTests(unittest.TestCase):
    def test_chat_completion_retries_when_json_object_response_format_is_rejected(self):
        calls = []
        old_urlopen = llm_client.urllib.request.urlopen
        try:
            def fake_urlopen(req, timeout=0):
                payload = json.loads(req.data.decode("utf-8"))
                calls.append(payload)
                if len(calls) == 1:
                    body = json.dumps(
                        {"error": "'response_format.type' must be 'json_schema' or 'text'"},
                        ensure_ascii=False,
                    ).encode("utf-8")
                    raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, io.BytesIO(body))
                return io.BytesIO(
                    json.dumps({"choices": [{"message": {"content": "{\"ok\": true}"}}]}).encode("utf-8")
                )

            llm_client.urllib.request.urlopen = fake_urlopen
            result = llm_client.chat_completion(
                [{"role": "user", "content": "Return JSON"}],
                base_url="http://llm",
                model="test-model",
                response_format={"type": "json_object"},
            )
        finally:
            llm_client.urllib.request.urlopen = old_urlopen

        self.assertEqual(result["choices"][0]["message"]["content"], "{\"ok\": true}")
        self.assertEqual(calls[0]["response_format"], {"type": "json_object"})
        self.assertNotIn("response_format", calls[1])


if __name__ == "__main__":
    unittest.main()
