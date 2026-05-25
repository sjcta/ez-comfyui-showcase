from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


STATUS_SOURCE_FILES = [
    ROOT / "app.py",
    ROOT / "modules" / "job_runner.py",
    ROOT / "modules" / "config.py",
    ROOT / "static" / "js" / "modules" / "card_manager.js",
    ROOT / "static" / "js" / "modules" / "history.js",
    ROOT / "static" / "js" / "modules" / "poll_manager.js",
    ROOT / "static" / "js" / "modules" / "ui.js",
]


MEDIA_SPECIFIC_STATUS_TEXT = [
    "正在拉取图片",
    "图片校验中",
    "拉取图片超时",
    "解码图像",
    "编码图像",
    "图像缩放",
    "合成图像",
    "保存图像",
    "图片保存中",
    "保存图片",
]


class JobCardMediaNeutralStatusTests(unittest.TestCase):
    def test_job_card_status_copy_is_media_neutral(self):
        hits = []
        for source in STATUS_SOURCE_FILES:
            text = source.read_text(encoding="utf-8")
            for phrase in MEDIA_SPECIFIC_STATUS_TEXT:
                if phrase in text:
                    hits.append(f"{source.relative_to(ROOT)}: {phrase}")

        self.assertEqual([], hits)

    def test_media_neutral_status_copy_is_available(self):
        combined = "\n".join(
            source.read_text(encoding="utf-8") for source in STATUS_SOURCE_FILES
        )

        for phrase in ["正在保存结果...", "内容校验中", "保存结果超时", "保存结果..."]:
            self.assertIn(phrase, combined)

    def test_job_card_renderers_normalize_legacy_status_messages(self):
        for source in [
            ROOT / "static" / "js" / "modules" / "card_manager.js",
            ROOT / "static" / "js" / "modules" / "history.js",
        ]:
            text = source.read_text(encoding="utf-8")

            self.assertIn("function _neutralJobStatusMessage", text)
            self.assertIn("_neutralJobStatusMessage(j.message || j.status)", text)


if __name__ == "__main__":
    unittest.main()
