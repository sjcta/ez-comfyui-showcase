from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SensitivePreviewKeywordTests(unittest.TestCase):
    def test_backend_protection_status_is_primary_preview_blur_source(self):
        for rel_path in ("static/js/modules/history.js", "static/js/modules/card_manager.js", "static/js/modules/workflows.js"):
            source = (ROOT / rel_path).read_text()

            self.assertRegex(source, r"function _isSensitive(?:Workflow)?Preview")
            self.assertIn("protection_status", source)
            self.assertIn("protected", source)
            self.assertIn("pending", source)

    def test_bare_exposed_word_does_not_trigger_preview_blur(self):
        for rel_path in ("static/js/modules/history.js", "static/js/modules/card_manager.js", "static/js/modules/workflows.js"):
            source = (ROOT / rel_path).read_text()

            self.assertNotIn("裸露", source)
            self.assertIn("裸体", source)
            self.assertIn("nsfw", source)
            self.assertIn(r"\bnude\b", source)

    def test_protected_done_job_preview_uses_same_blur_treatment(self):
        css = (ROOT / "static/css/style.css").read_text()

        self.assertIn(".gi.job-card.done .gi-img.gi-sensitive img", css)
        self.assertIn(".gi.job-card.completing .gi-img.gi-sensitive img", css)

    def test_checking_job_uses_pending_image_as_blurred_protected_preview(self):
        for rel_path in ("static/js/modules/history.js", "static/js/modules/card_manager.js"):
            source = (ROOT / rel_path).read_text()

            self.assertIn("pending_image", source)
            self.assertIn("pending_thumb", source)
            self.assertIn("j.status === 'checking'", source)
            self.assertIn("checkingSensitiveCls", source)

    def test_legacy_generate_task_schedules_protection_before_done(self):
        app_py = (ROOT / "app.py").read_text()
        start = app_py.index("async def generate_task")
        end = app_py.index("# ══════════════════════════════════════════════════════════════════════════\n#  Jobs persistence", start)
        generate_task = app_py[start:end]

        self.assertIn('"protection_status": IMAGE_PROTECTION_PENDING', generate_task)
        self.assertIn('status="checking"', generate_task)
        self.assertIn('pending_media_type=cover.get("media_type", "image") or "image"', generate_task)
        self.assertIn("_schedule_image_protection(job_id, records", generate_task)

    def test_safe_heuristic_video_rows_are_rechecked_after_visual_tuning(self):
        app_py = (ROOT / "app.py").read_text()

        self.assertIn("def _recheck_safe_heuristic_video_rows", app_py)
        self.assertIn("_recheck_safe_heuristic_video_rows(conn)", app_py)
        self.assertIn("COALESCE(media_type, '') = 'video'", app_py)
        self.assertIn("lower(COALESCE(image_path, '')) LIKE '%.mp4'", app_py)


if __name__ == "__main__":
    unittest.main()
