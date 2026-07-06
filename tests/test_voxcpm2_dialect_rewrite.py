import unittest

import app


class VoxCPM2DialectRewriteTests(unittest.TestCase):
    def test_voxcpm2_dialect_rewrites_standard_mandarin_before_generation(self):
        calls = []

        def fake_chat(messages, **kwargs):
            calls.append((messages, kwargs))
            self.assertIn("东北话", messages[1]["content"])
            self.assertIn("你在这里做什么？", messages[1]["content"])
            return "你搁这整啥玩意儿呢？"

        fields = {
            "1::language": "东北话",
            "1::text": "你在这里做什么？",
            "1::voice_input_mode": "文字描述音色（0样本）",
        }

        app._normalize_voxcpm2_dialect_text(
            "tts_voxcpm2.json",
            fields,
            allow_llm=True,
            chat_fn=fake_chat,
        )

        self.assertEqual(fields["1::text"], "你搁这整啥玩意儿呢？")
        self.assertEqual(fields["__voxcpm2_dialect_original_text"], "你在这里做什么？")
        self.assertEqual(fields["__voxcpm2_dialect_rewritten_text"], "你搁这整啥玩意儿呢？")
        self.assertEqual(fields["__voxcpm2_dialect_language"], "东北话")
        self.assertEqual(fields["__voxcpm2_dialect_rewrite_engine"], "llm")
        self.assertEqual(len(calls), 1)

    def test_voxcpm2_regular_chinese_does_not_rewrite(self):
        fields = {
            "1::language": "Chinese",
            "1::text": "你在这里做什么？",
        }

        app._normalize_voxcpm2_dialect_text(
            "tts_voxcpm2.json",
            fields,
            allow_llm=True,
            chat_fn=lambda *_args, **_kwargs: "should not be called",
        )

        self.assertEqual(fields["1::text"], "你在这里做什么？")
        self.assertNotIn("__voxcpm2_dialect_original_text", fields)

    def test_voxcpm2_rewritten_text_is_not_rewritten_again_on_restore(self):
        fields = {
            "1::language": "吴语",
            "1::text": "侬勒海做啥啦？",
            "__voxcpm2_dialect_language": "吴语",
            "__voxcpm2_dialect_original_text": "你在这里做什么？",
            "__voxcpm2_dialect_rewritten_text": "侬勒海做啥啦？",
        }

        app._normalize_voxcpm2_dialect_text(
            "tts_voxcpm2.json",
            fields,
            allow_llm=True,
            chat_fn=lambda *_args, **_kwargs: "should not be called",
        )

        self.assertEqual(fields["1::text"], "侬勒海做啥啦？")
        self.assertEqual(fields["__voxcpm2_dialect_original_text"], "你在这里做什么？")


if __name__ == "__main__":
    unittest.main()
