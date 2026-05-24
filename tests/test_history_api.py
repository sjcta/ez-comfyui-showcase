import asyncio
import os
import sqlite3
import tempfile
import unittest

from fastapi import HTTPException
from PIL import Image

import app


class HistoryApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_gen_db = app.GEN_DB
        self._old_auth_db = app.AUTH_DB
        self._old_output_dir = app.OUTPUT_DIR
        self._old_history_dir = app.HISTORY_DIR
        self._old_comfyui_input = app.COMFYUI_INPUT
        self._old_history = list(app.history)
        self._old_logs = list(app._log_buffer)
        app.GEN_DB = os.path.join(self._tmp.name, "generation.db")
        app.AUTH_DB = os.path.join(self._tmp.name, "auth.db")
        app.OUTPUT_DIR = os.path.join(self._tmp.name, "outputs")
        app.HISTORY_DIR = os.path.join(self._tmp.name, "history")
        app.COMFYUI_INPUT = os.path.join(self._tmp.name, "input")
        os.makedirs(app.OUTPUT_DIR, exist_ok=True)
        os.makedirs(app.HISTORY_DIR, exist_ok=True)
        os.makedirs(app.COMFYUI_INPUT, exist_ok=True)
        app.history = []
        app._log_buffer[:] = []
        app._init_gen_db()

    def tearDown(self):
        app.GEN_DB = self._old_gen_db
        app.AUTH_DB = self._old_auth_db
        app.OUTPUT_DIR = self._old_output_dir
        app.HISTORY_DIR = self._old_history_dir
        app.COMFYUI_INPUT = self._old_comfyui_input
        app.history = self._old_history
        app._log_buffer[:] = self._old_logs
        self._tmp.cleanup()

    def test_history_enriches_username_without_joining_generation_db(self):
        conn = sqlite3.connect(app.AUTH_DB)
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, disabled) VALUES (?, ?, ?, ?, 0)",
            ("u1", "alice", "hash", "user"),
        )
        conn.commit()
        conn.close()
        app._insert_generation(
            {
                "id": "hist-1",
                "workflow": "t2i-test.json",
                "filename": "hist-1.png",
                "prompt": "hello",
                "time": "2026-05-18 12:00:00",
            },
            elapsed=3,
            user_id="u1",
        )

        result = app.api_history(limit=10, scope="all", current_user={"sub": "admin", "role": "admin"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["data"][0]["username"], "alice")

    def test_invalid_output_file_does_not_pollute_user_logs_with_thumbnail_warnings(self):
        image_path = os.path.join(app.OUTPUT_DIR, "hist-1.png")
        with open(image_path, "wb") as f:
            f.write(b"image")
        app._insert_generation(
            {
                "id": "hist-1",
                "workflow": "t2i-test.json",
                "filename": "hist-1.png",
                "prompt": "hello",
                "time": "2026-05-18 12:00:00",
            },
            elapsed=3,
            user_id="u1",
        )

        result = app.api_history(limit=10, scope="mine", current_user={"sub": "u1", "role": "user"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"][0]["thumb"], "")
        self.assertFalse([entry for entry in app._log_buffer if entry.get("phase") == "thumbnail"])

    def test_history_orders_same_second_by_newer_insert_first(self):
        for item_id in ("job_1000_0001", "job_1002_0001", "job_1001_0001"):
            app._insert_generation(
                {
                    "id": item_id,
                    "workflow": "t2i-test.json",
                    "filename": item_id + ".png",
                    "prompt": item_id,
                    "time": "2026-05-18 12:00:00",
                },
                elapsed=3,
                user_id="u1",
            )

        result = app.api_history(limit=10, scope="mine", current_user={"sub": "u1", "role": "user"})

        self.assertEqual([item["id"] for item in result["data"]], [
            "job_1001_0001",
            "job_1002_0001",
            "job_1000_0001",
        ])
        self.assertEqual(
            [item["sort_index"] for item in result["data"]],
            sorted([item["sort_index"] for item in result["data"]], reverse=True),
        )

    def test_history_api_preserves_video_media_type(self):
        video_path = os.path.join(app.OUTPUT_DIR, "clip.mp4")
        with open(video_path, "wb") as f:
            f.write(b"video")
        app._insert_generation(
            {
                "id": "hist-video",
                "workflow": "t2v-test.json",
                "filename": "clip.mp4",
                "media_type": "video",
                "prompt": "video prompt",
                "time": "2026-05-18 12:00:00",
                "protection_status": "safe",
            },
            elapsed=3,
            user_id="u1",
        )

        result = app.api_history(limit=10, scope="mine", current_user={"sub": "u1", "role": "user"})

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["data"][0]["filename"], "clip.mp4")
        self.assertEqual(result["data"][0]["media_type"], "video")

    def test_video_records_fill_dimensions_from_thumbnail_when_probe_unavailable(self):
        video_path = os.path.join(app.OUTPUT_DIR, "clip.mp4")
        thumb_path = os.path.join(app.OUTPUT_DIR, "clip_thumb.jpg")
        with open(video_path, "wb") as f:
            f.write(b"video")
        Image.new("RGB", (96, 54), (12, 32, 72)).save(thumb_path)

        app._insert_generation(
            {
                "id": "hist-video",
                "workflow": "t2v-test.json",
                "filename": "clip.mp4",
                "thumb": "clip_thumb.jpg",
                "media_type": "video",
                "prompt": "video prompt",
                "time": "2026-05-18 12:00:00",
                "protection_status": "safe",
            },
            elapsed=3,
            user_id="u1",
        )

        result = app.api_history(limit=10, scope="mine", current_user={"sub": "u1", "role": "user"})

        self.assertEqual(result["data"][0]["width"], 96)
        self.assertEqual(result["data"][0]["height"], 54)

    def test_history_api_replaces_thumbnail_dimensions_with_video_stream_dimensions(self):
        video_path = os.path.join(app.OUTPUT_DIR, "clip.mp4")
        thumb_path = os.path.join(app.OUTPUT_DIR, "clip_thumb.jpg")
        with open(video_path, "wb") as f:
            f.write(b"video")
        Image.new("RGB", (220, 400), (12, 32, 72)).save(thumb_path)
        old_get_video_size = app.get_video_size
        app.get_video_size = lambda _rel: (0, 0)
        app._insert_generation(
            {
                "id": "hist-video",
                "workflow": "t2v-test.json",
                "filename": "clip.mp4",
                "thumb": "clip_thumb.jpg",
                "media_type": "video",
                "prompt": "video prompt",
                "width": 220,
                "height": 400,
                "time": "2026-05-18 12:00:00",
                "protection_status": "safe",
            },
            elapsed=3,
            user_id="u1",
        )
        try:
            app.get_video_size = lambda _rel: (704, 1280)
            result = app.api_history(limit=10, scope="mine", current_user={"sub": "u1", "role": "user"})
        finally:
            app.get_video_size = old_get_video_size

        self.assertEqual(result["data"][0]["width"], 704)
        self.assertEqual(result["data"][0]["height"], 1280)

    def test_video_records_skip_image_protection(self):
        video_path = os.path.join(app.OUTPUT_DIR, "clip.mp4")
        with open(video_path, "wb") as f:
            f.write(b"video")
        record = {
            "id": "hist-video",
            "workflow": "t2v-test.json",
            "filename": "clip.mp4",
            "media_type": "video",
            "prompt": "video prompt",
            "time": "2026-05-18 12:00:00",
            "protection_status": "pending",
        }
        app._insert_generation(record, elapsed=3, user_id="u1")

        asyncio.run(app._complete_image_protection_job("", [record], 3))
        result = app.api_history(limit=10, scope="mine", current_user={"sub": "u1", "role": "user"})

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["data"][0]["media_type"], "video")
        self.assertEqual(result["data"][0]["protection_status"], "safe")
        self.assertEqual(result["data"][0]["protection_source"], "media-type")

    def test_video_records_with_thumbnail_run_preview_protection(self):
        from modules.image_protection import ImageProtectionWorker

        video_path = os.path.join(app.OUTPUT_DIR, "clip.mp4")
        thumb_path = os.path.join(app.OUTPUT_DIR, "clip_thumb.jpg")
        with open(video_path, "wb") as f:
            f.write(b"video")
        Image.new("RGB", (48, 48), (230, 180, 160)).save(thumb_path)
        old_worker = app._image_protection_worker

        def load_detector():
            return lambda _path: [{"label": "EXPOSED_GENITALIA_F", "score": 0.88}]

        app._image_protection_worker = ImageProtectionWorker(load_detector=load_detector, load_classifier=lambda: None)
        try:
            record = {
                "id": "hist-video",
                "workflow": "t2v-test.json",
                "filename": "clip.mp4",
                "thumb": "clip_thumb.jpg",
                "media_type": "video",
                "prompt": "video prompt",
                "time": "2026-05-18 12:00:00",
                "protection_status": "pending",
            }
            app._insert_generation(record, elapsed=3, user_id="u1")

            asyncio.run(app._complete_image_protection_job("", [record], 3))
            result = app.api_history(limit=10, scope="mine", current_user={"sub": "u1", "role": "user"})
        finally:
            app._image_protection_worker = old_worker

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["data"][0]["media_type"], "video")
        self.assertEqual(result["data"][0]["protection_status"], "protected")
        self.assertEqual(result["data"][0]["protection_source"], "detector")

    def test_video_records_generate_thumbnail_before_preview_protection(self):
        from modules.image_protection import ImageProtectionWorker

        video_path = os.path.join(app.OUTPUT_DIR, "clip.mp4")
        thumb_path = os.path.join(app.OUTPUT_DIR, "clip_thumb.jpg")
        with open(video_path, "wb") as f:
            f.write(b"video")
        Image.new("RGB", (48, 48), (230, 180, 160)).save(thumb_path)
        old_worker = app._image_protection_worker
        old_make_thumbnail = app.make_thumbnail

        def load_detector():
            return lambda _path: [{"label": "EXPOSED_GENITALIA_F", "score": 0.88}]

        app._image_protection_worker = ImageProtectionWorker(load_detector=load_detector, load_classifier=lambda: None)
        try:
            record = {
                "id": "hist-video",
                "workflow": "t2v-test.json",
                "filename": "clip.mp4",
                "media_type": "video",
                "prompt": "video prompt",
                "time": "2026-05-18 12:00:00",
                "protection_status": "pending",
            }
            app._insert_generation(record, elapsed=3, user_id="u1")
            record["thumb"] = ""
            app.make_thumbnail = lambda _rel: "clip_thumb.jpg"

            asyncio.run(app._complete_image_protection_job("", [record], 3))
            result = app.api_history(limit=10, scope="mine", current_user={"sub": "u1", "role": "user"})
        finally:
            app._image_protection_worker = old_worker
            app.make_thumbnail = old_make_thumbnail

        self.assertEqual(result["data"][0]["thumb"], "clip_thumb.jpg")
        self.assertEqual(result["data"][0]["protection_status"], "protected")
        self.assertEqual(result["data"][0]["protection_source"], "detector")

    def test_pending_protection_records_are_hidden_until_checked(self):
        app._insert_generation(
            {
                "id": "hist-pending",
                "workflow": "t2i-test.json",
                "filename": "pending.png",
                "prompt": "ambiguous prompt",
                "time": "2026-05-18 12:00:00",
                "protection_status": "pending",
            },
            elapsed=3,
            user_id="u1",
        )
        app._insert_generation(
            {
                "id": "hist-safe",
                "workflow": "t2i-test.json",
                "filename": "safe.png",
                "prompt": "plain prompt",
                "time": "2026-05-18 12:01:00",
                "protection_status": "safe",
                "protection_score": 0.02,
                "protection_source": "classifier",
                "protection_reason": "safe content",
                "protection_checked_at": "2026-05-18 12:01:03",
            },
            elapsed=3,
            user_id="u1",
        )

        result = app.api_history(limit=10, scope="mine", current_user={"sub": "u1", "role": "user"})

        self.assertEqual([item["id"] for item in result["data"]], ["hist-safe"])
        self.assertEqual(result["data"][0]["protection_status"], "safe")
        self.assertEqual(result["data"][0]["protection_source"], "classifier")
        self.assertAlmostEqual(result["data"][0]["protection_score"], 0.02)

    def test_update_generation_protection_persists_result(self):
        app._insert_generation(
            {
                "id": "hist-1",
                "workflow": "t2i-test.json",
                "filename": "hist-1.png",
                "prompt": "hello",
                "time": "2026-05-18 12:00:00",
            },
            elapsed=3,
            user_id="u1",
        )

        app._update_generation_protection(
            "hist-1",
            status="protected",
            score=0.87,
            reason="classifier matched unsafe label",
            source="classifier",
        )

        result = app.api_history(limit=10, scope="mine", current_user={"sub": "u1", "role": "user"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["data"][0]["protection_status"], "protected")
        self.assertEqual(result["data"][0]["protection_source"], "classifier")
        self.assertEqual(result["data"][0]["protection_reason"], "classifier matched unsafe label")
        self.assertGreater(result["data"][0]["protection_checked_at"], "")

    def test_legacy_prompt_rows_are_not_backfilled_when_prompt_protection_is_off(self):
        image_path = os.path.join(app.OUTPUT_DIR, "legacy.png")
        Image.new("RGB", (48, 48), (230, 180, 160)).save(image_path)
        app._insert_generation(
            {
                "id": "hist-legacy",
                "workflow": "t2i-test.json",
                "filename": "legacy.png",
                "prompt": "nsfw portrait",
                "time": "2026-05-18 12:00:00",
                "protection_status": "safe",
            },
            elapsed=3,
            user_id="u1",
        )

        app._backfill_legacy_prompt_protection()

        result = app.api_history(limit=10, scope="mine", current_user={"sub": "u1", "role": "user"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["data"][0]["protection_status"], "safe")
        self.assertEqual(result["data"][0]["protection_source"], "")

    def test_legacy_prompt_backfill_disables_detector_during_startup_migration(self):
        image_path = os.path.join(app.OUTPUT_DIR, "legacy-detector.png")
        Image.new("RGB", (48, 48), (230, 180, 160)).save(image_path)
        app._insert_generation(
            {
                "id": "hist-legacy-detector",
                "workflow": "t2i-test.json",
                "filename": "legacy-detector.png",
                "prompt": "nsfw portrait",
                "time": "2026-05-18 12:00:00",
                "protection_status": "safe",
            },
            elapsed=3,
            user_id="u1",
        )
        old_worker = app.ImageProtectionWorker
        created = []

        class FakeWorker:
            def __init__(self, **kwargs):
                created.append(kwargs)

            def check(self, _image_path, _prompt=""):
                return app.ImageProtectionResult("safe", 1.0, "fake", "test")

        app.ImageProtectionWorker = FakeWorker
        try:
            app._backfill_legacy_prompt_protection()
        finally:
            app.ImageProtectionWorker = old_worker

        self.assertEqual(len(created), 1)
        self.assertIsNone(created[0]["load_detector"]())
        self.assertIsNone(created[0]["load_classifier"]())

    def test_init_gen_db_does_not_block_on_protection_backfills(self):
        old_backfill = app._backfill_legacy_prompt_protection
        old_recheck_nsfw = app._recheck_safe_heuristic_nsfw_risk_rows
        old_recheck_video = app._recheck_safe_heuristic_video_rows

        def fail_if_called(_conn=None):
            raise AssertionError("protection backfill should not run during _init_gen_db")

        app._backfill_legacy_prompt_protection = fail_if_called
        app._recheck_safe_heuristic_nsfw_risk_rows = fail_if_called
        app._recheck_safe_heuristic_video_rows = fail_if_called
        try:
            app._init_gen_db()
        finally:
            app._backfill_legacy_prompt_protection = old_backfill
            app._recheck_safe_heuristic_nsfw_risk_rows = old_recheck_nsfw
            app._recheck_safe_heuristic_video_rows = old_recheck_video

    def test_legacy_prompt_backfill_does_not_override_checked_safe_rows(self):
        app._insert_generation(
            {
                "id": "hist-checked",
                "workflow": "t2i-test.json",
                "filename": "checked.png",
                "prompt": "nsfw word in prompt but classifier passed",
                "time": "2026-05-18 12:00:00",
                "protection_status": "safe",
                "protection_score": 0.98,
                "protection_source": "classifier",
                "protection_reason": "classifier safe",
                "protection_checked_at": "2026-05-18 12:00:03",
            },
            elapsed=3,
            user_id="u1",
        )

        app._backfill_legacy_prompt_protection()

        result = app.api_history(limit=10, scope="mine", current_user={"sub": "u1", "role": "user"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["data"][0]["protection_status"], "safe")
        self.assertEqual(result["data"][0]["protection_source"], "classifier")

    def test_safe_heuristic_soft_nude_prompt_rows_stay_safe_when_detector_is_safe(self):
        rel_path = "u1/2026-05-22/nsfw-risk.png"
        abs_path = os.path.join(app.OUTPUT_DIR, rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        img = Image.new("RGB", (48, 48), (8, 10, 12))
        for x in range(24):
            for y in range(48):
                img.putpixel((x, y), (230, 180, 160))
        img.save(abs_path)
        app._insert_generation(
            {
                "id": "hist-heuristic-safe",
                "workflow": "t2i-test.json",
                "filename": rel_path,
                "prompt": "人物没穿任何衣服，双手举起露出胸部，写实肖像",
                "time": "2026-05-18 12:00:00",
                "protection_status": "safe",
                "protection_score": 0.46,
                "protection_source": "heuristic",
                "protection_reason": "local heuristic skin_ratio=0.540",
                "protection_checked_at": "2026-05-18 12:00:03",
            },
            elapsed=3,
            user_id="u1",
        )

        app._recheck_safe_heuristic_nsfw_risk_rows()

        result = app.api_history(limit=10, scope="mine", current_user={"sub": "u1", "role": "user"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["data"][0]["protection_status"], "safe")
        self.assertEqual(result["data"][0]["protection_source"], "heuristic")
        self.assertIn("skin_ratio", result["data"][0]["protection_reason"])

    def test_safe_heuristic_full_nude_prompt_rows_stay_safe_when_prompt_protection_is_off(self):
        rel_path = "u1/2026-05-22/full-nude-risk.png"
        abs_path = os.path.join(app.OUTPUT_DIR, rel_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        img = Image.new("RGB", (48, 48), (8, 10, 12))
        for x in range(10, 30):
            for y in range(48):
                img.putpixel((x, y), (230, 180, 160))
        img.save(abs_path)
        app._insert_generation(
            {
                "id": "hist-full-nude-safe",
                "workflow": "t2i-test.json",
                "filename": rel_path,
                "prompt": "人物全裸，裸体，全身裸体，写实肖像",
                "time": "2026-05-18 12:00:00",
                "protection_status": "safe",
                "protection_score": 0.58,
                "protection_source": "heuristic",
                "protection_reason": "local heuristic skin_ratio=0.420",
                "protection_checked_at": "2026-05-18 12:00:03",
            },
            elapsed=3,
            user_id="u1",
        )

        app._recheck_safe_heuristic_nsfw_risk_rows()

        result = app.api_history(limit=10, scope="mine", current_user={"sub": "u1", "role": "user"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["data"][0]["protection_status"], "safe")
        self.assertEqual(result["data"][0]["protection_source"], "heuristic")
        self.assertIn("skin_ratio", result["data"][0]["protection_reason"])

    def test_delete_moves_record_to_trash_without_removing_files(self):
        image_path = os.path.join(app.OUTPUT_DIR, "hist-1.png")
        with open(image_path, "wb") as f:
            f.write(b"image")
        app._insert_generation(
            {
                "id": "hist-1",
                "workflow": "t2i-test.json",
                "filename": "hist-1.png",
                "prompt": "hello",
                "time": "2026-05-18 12:00:00",
            },
            elapsed=3,
            user_id="u1",
        )

        result = app.api_history_delete("hist-1", current_user={"sub": "u1", "role": "user"})

        self.assertTrue(result["ok"])
        self.assertTrue(os.path.exists(image_path))
        normal = app.api_history(limit=10, scope="mine", current_user={"sub": "u1", "role": "user"})
        trash = app.api_history(limit=10, scope="trash", current_user={"sub": "u1", "role": "user"})
        self.assertEqual(normal["total"], 0)
        self.assertEqual(trash["total"], 1)
        self.assertTrue(trash["data"][0]["is_deleted"])
        self.assertTrue(trash["data"][0]["deleted_at"])

    def test_restore_makes_soft_deleted_record_visible_again(self):
        app._insert_generation(
            {
                "id": "hist-1",
                "workflow": "t2i-test.json",
                "filename": "hist-1.png",
                "time": "2026-05-18 12:00:00",
            },
            elapsed=3,
            user_id="u1",
        )
        user = {"sub": "u1", "role": "user"}
        app.api_history_delete("hist-1", current_user=user)

        result = app.api_history_restore("hist-1", current_user=user)

        self.assertTrue(result["ok"])
        normal = app.api_history(limit=10, scope="mine", current_user=user)
        trash = app.api_history(limit=10, scope="trash", current_user=user)
        self.assertEqual(normal["total"], 1)
        self.assertFalse(normal["data"][0]["is_deleted"])
        self.assertEqual(trash["total"], 0)

    def test_permanent_delete_removes_record_and_files(self):
        image_path = os.path.join(app.OUTPUT_DIR, "hist-1.png")
        with open(image_path, "wb") as f:
            f.write(b"image")
        app._insert_generation(
            {
                "id": "hist-1",
                "workflow": "t2i-test.json",
                "filename": "hist-1.png",
                "time": "2026-05-18 12:00:00",
            },
            elapsed=3,
            user_id="u1",
        )
        user = {"sub": "u1", "role": "user"}
        app.api_history_delete("hist-1", current_user=user)

        result = app.api_history_permanent_delete("hist-1", current_user=user)

        self.assertTrue(result["ok"])
        self.assertFalse(os.path.exists(image_path))
        trash = app.api_history(limit=10, scope="trash", current_user=user)
        self.assertEqual(trash["total"], 0)

    def test_permanent_delete_removes_uploaded_source_image_when_unreferenced(self):
        image_path = os.path.join(app.OUTPUT_DIR, "hist-1.png")
        source_rel = "u1/2026-05-18/uploaded.png"
        source_path = os.path.join(app.COMFYUI_INPUT, source_rel)
        os.makedirs(os.path.dirname(source_path), exist_ok=True)
        with open(image_path, "wb") as f:
            f.write(b"image")
        with open(source_path, "wb") as f:
            f.write(b"source")
        app._insert_generation(
            {
                "id": "hist-1",
                "workflow": "i2i-test.json",
                "filename": "hist-1.png",
                "time": "2026-05-18 12:00:00",
                "field_values": {"41::image": source_rel},
            },
            elapsed=3,
            user_id="u1",
        )
        user = {"sub": "u1", "role": "user"}
        app.api_history_delete("hist-1", current_user=user)

        result = app.api_history_permanent_delete("hist-1", current_user=user)

        self.assertTrue(result["ok"])
        self.assertFalse(os.path.exists(image_path))
        self.assertFalse(os.path.exists(source_path))

    def test_permanent_delete_keeps_uploaded_source_image_used_by_other_history(self):
        source_rel = "u1/2026-05-18/shared.png"
        source_path = os.path.join(app.COMFYUI_INPUT, source_rel)
        os.makedirs(os.path.dirname(source_path), exist_ok=True)
        with open(source_path, "wb") as f:
            f.write(b"source")
        for item_id in ("hist-1", "hist-2"):
            image_path = os.path.join(app.OUTPUT_DIR, item_id + ".png")
            with open(image_path, "wb") as f:
                f.write(b"image")
            app._insert_generation(
                {
                    "id": item_id,
                    "workflow": "i2i-test.json",
                    "filename": item_id + ".png",
                    "time": "2026-05-18 12:00:00",
                    "field_values": {"41::image": source_rel},
                },
                elapsed=3,
                user_id="u1",
            )
        user = {"sub": "u1", "role": "user"}
        app.api_history_delete("hist-1", current_user=user)

        result = app.api_history_permanent_delete("hist-1", current_user=user)

        self.assertTrue(result["ok"])
        self.assertTrue(os.path.exists(source_path))

    def test_image_routes_read_only_from_output_dir(self):
        output_image = os.path.join(app.OUTPUT_DIR, "u1", "2026-05-18", "hist-1.png")
        history_image = os.path.join(app.HISTORY_DIR, "u1", "2026-05-18", "hist-2.png")
        os.makedirs(os.path.dirname(output_image), exist_ok=True)
        os.makedirs(os.path.dirname(history_image), exist_ok=True)
        with open(output_image, "wb") as f:
            f.write(b"image")
        with open(history_image, "wb") as f:
            f.write(b"legacy")

        ok = app.api_image("u1/2026-05-18/hist-1.png")
        self.assertEqual(ok.path, output_image)
        with self.assertRaises(HTTPException):
            app.api_image("u1/2026-05-18/hist-2.png")


if __name__ == "__main__":
    unittest.main()
