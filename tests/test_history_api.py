import asyncio
import builtins
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

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

    def test_compact_history_omits_heavy_reuse_fields_until_detail_fetch(self):
        long_prompt = "portrait details " * 80
        heavy_fields = {
            "1::prompt": "复刻参数" * 800,
            "2::image": "u1/ref.png",
        }
        app._insert_generation(
            {
                "id": "hist-compact",
                "workflow": "i2i-test.json",
                "filename": "hist-compact.png",
                "prompt": long_prompt,
                "field_values": heavy_fields,
                "time": "2026-05-18 12:00:00",
            },
            elapsed=3,
            user_id="u1",
        )

        compact = app.api_history(limit=10, scope="mine", compact=True, current_user={"sub": "u1", "role": "user"})
        compact_item = compact["data"][0]

        self.assertTrue(compact_item["__compact"])
        self.assertNotIn("field_values", compact_item)
        self.assertEqual(compact_item["prompt"], "")
        self.assertLess(len(compact_item["prompt_preview"]), len(long_prompt))

        full = app.api_history(limit=10, scope="mine", current_user={"sub": "u1", "role": "user"})
        self.assertEqual(full["data"][0]["field_values"], heavy_fields)
        self.assertEqual(full["data"][0]["prompt"], long_prompt)

        detail = app.api_history_detail("hist-compact", current_user={"sub": "u1", "role": "user"})
        self.assertEqual(detail["data"]["field_values"], heavy_fields)
        self.assertEqual(detail["data"]["prompt"], long_prompt)

    def test_compact_history_collapses_style_prompt_block_in_preview(self):
        styled_prompt = (
            "[Style Preset: 动漫 / anime@v2]\n"
            "[Style Lock]\nSTYLE LOCK: final image must be rendered as finished anime character artwork.\n"
            "[General Style]\nAnime illustration style with clean linework.\n"
            "[User Prompt]\n美女洗澡"
        )
        app._insert_generation(
            {
                "id": "hist-style",
                "workflow": "t2i_ernie_image_turbo.json",
                "filename": "hist-style.png",
                "prompt": styled_prompt,
                "field_values": {
                    "__style_preset_id": "anime",
                    "94::value": styled_prompt,
                },
                "time": "2026-05-18 12:00:00",
            },
            elapsed=3,
            user_id="u1",
        )

        compact = app.api_history(limit=10, scope="mine", compact=True, current_user={"sub": "u1", "role": "user"})
        compact_item = compact["data"][0]

        self.assertEqual(compact_item["prompt_preview"], "动漫｜美女洗澡")
        self.assertNotIn("Style Lock", compact_item["prompt_preview"])

    def test_history_user_counts_returns_lightweight_admin_counts(self):
        for item_id, user_id in (("hist-u1-a", "u1"), ("hist-u1-b", "u1"), ("hist-u2", "u2")):
            app._insert_generation(
                {
                    "id": item_id,
                    "workflow": "t2i-test.json",
                    "filename": item_id + ".png",
                    "prompt": item_id,
                    "time": "2026-05-18 12:00:00",
                },
                elapsed=3,
                user_id=user_id,
            )

        result = app.api_history_user_counts(current_user={"sub": "admin", "role": "admin"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["counts"], {"u1": 2, "u2": 1})

    def test_history_after_id_cursor_is_stable_across_newer_inserts(self):
        for item_id, created_at in (
            ("hist-old", "2026-05-18 10:00:00"),
            ("hist-mid", "2026-05-18 11:00:00"),
            ("hist-new", "2026-05-18 12:00:00"),
        ):
            app._insert_generation(
                {
                    "id": item_id,
                    "workflow": "t2i-test.json",
                    "filename": item_id + ".png",
                    "prompt": item_id,
                    "time": created_at,
                },
                elapsed=3,
                user_id="u1",
            )

        first_page = app.api_history(limit=2, scope="mine", current_user={"sub": "u1", "role": "user"})
        first_ids = [item["id"] for item in first_page["data"]]
        self.assertEqual(first_ids, ["hist-new", "hist-mid"])

        app._insert_generation(
            {
                "id": "hist-newer",
                "workflow": "t2i-test.json",
                "filename": "hist-newer.png",
                "prompt": "newer",
                "time": "2026-05-18 13:00:00",
            },
            elapsed=3,
            user_id="u1",
        )

        next_page = app.api_history(
            limit=10,
            after_id="hist-mid",
            scope="mine",
            current_user={"sub": "u1", "role": "user"},
        )
        next_ids = [item["id"] for item in next_page["data"]]

        self.assertEqual(next_ids, ["hist-old"])
        self.assertNotIn("hist-newer", next_ids)
        self.assertNotIn("hist-new", next_ids)
        self.assertNotIn("hist-mid", next_ids)

    def test_history_can_filter_by_workflow_type_before_pagination(self):
        old_loader = app._load_wf_meta
        try:
            app._load_wf_meta = lambda: {
                "video-a.json": {"tags": ["视频制作", "图生视频"]},
                "image-a.json": {"tags": ["文生图"]},
            }
            for item_id, workflow, created_at in (
                ("image-new", "image-a.json", "2026-05-18 13:00:00"),
                ("video-new", "video-a.json", "2026-05-18 12:00:00"),
                ("video-old", "video-a.json", "2026-05-18 11:00:00"),
            ):
                app._insert_generation(
                    {
                        "id": item_id,
                        "workflow": workflow,
                        "filename": item_id + ".png",
                        "prompt": item_id,
                        "time": created_at,
                    },
                    elapsed=3,
                    user_id="u1",
                )

            result = app.api_history(
                limit=10,
                scope="mine",
                workflow_type="视频制作",
                current_user={"sub": "u1", "role": "user"},
            )
            self.assertEqual(result["total"], 2)
            self.assertEqual([item["id"] for item in result["data"]], ["video-new", "video-old"])

            summary = app.api_history_summary(
                limit=10,
                scope="mine",
                workflow_type="视频制作",
                current_user={"sub": "u1", "role": "user"},
            )
            self.assertEqual(summary["total"], 2)
            self.assertEqual(summary["count"], 2)
        finally:
            app._load_wf_meta = old_loader

    def test_video_frame_endpoint_sets_cover_and_exports_input_frame(self):
        video_rel = "video/sample.mp4"
        video_path = os.path.join(app.OUTPUT_DIR, video_rel)
        os.makedirs(os.path.dirname(video_path), exist_ok=True)
        with open(video_path, "wb") as f:
            f.write(b"fake video")
        app._insert_generation(
            {
                "id": "vid-1",
                "workflow": "i2v-test.json",
                "filename": video_rel,
                "media_type": "video",
                "thumb": "",
                "prompt": "hello",
                "time": "2026-05-18 12:00:00",
            },
            elapsed=3,
            user_id="u1",
        )

        def fake_run(cmd, **kwargs):
            with open(cmd[-1], "wb") as out:
                out.write(b"jpg")
            return SimpleNamespace(returncode=0, stderr=b"")

        with mock.patch.object(app, "_project_ffmpeg_bin", return_value="/bin/ffmpeg"), \
                mock.patch.object(app.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(app, "_check_image_protection_candidates", return_value=app.ImageProtectionResult("safe", 0.98, "checked frame", "unit-test")) as protection_check, \
                mock.patch.object(app.random, "randint", return_value=1234):
            result = app.api_history_video_frame(
                "vid-1",
                {"time": 1.25, "set_cover": True, "import_input": True},
                current_user={"sub": "u1", "role": "user"},
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["frame"], "video/sample_frame_00001250.jpg")
        self.assertEqual(result["thumb"], result["frame"])
        self.assertEqual(result["protection_status"], "safe")
        self.assertEqual(result["protection_source"], "unit-test")
        self.assertGreater(result["protection_checked_at"], "")
        protection_check.assert_called_once()
        protection_record = protection_check.call_args.args[1]
        self.assertEqual(protection_record["thumb"], result["frame"])
        self.assertEqual(protection_record["image_path"], result["frame"])
        self.assertTrue(result["input_filename"].startswith("u1/"))
        self.assertTrue(result["input_filename"].endswith("/sample_frame_00001250_1234.jpg"))
        self.assertTrue(os.path.isfile(os.path.join(app.OUTPUT_DIR, result["frame"])))
        self.assertTrue(os.path.isfile(os.path.join(app.COMFYUI_INPUT, result["input_filename"])))
        conn = sqlite3.connect(app.GEN_DB)
        thumb, protection_status, protection_reason = conn.execute(
            "SELECT thumb_path, protection_status, protection_reason FROM generations WHERE id='vid-1'"
        ).fetchone()
        conn.close()
        self.assertEqual(thumb, result["frame"])
        self.assertEqual(protection_status, "safe")
        self.assertEqual(protection_reason, "checked frame")

    def test_video_frame_endpoint_retries_before_end_boundary(self):
        video_rel = "video/end-boundary.mp4"
        video_path = os.path.join(app.OUTPUT_DIR, video_rel)
        os.makedirs(os.path.dirname(video_path), exist_ok=True)
        with open(video_path, "wb") as f:
            f.write(b"fake video")
        app._insert_generation(
            {
                "id": "vid-end",
                "workflow": "i2v-test.json",
                "filename": video_rel,
                "media_type": "video",
                "thumb": "",
                "prompt": "hello",
                "time": "2026-05-18 12:00:00",
            },
            elapsed=3,
            user_id="u1",
        )
        attempts = []

        def fake_run(cmd, **kwargs):
            pos = float(cmd[cmd.index("-ss") + 1])
            attempts.append(pos)
            if pos > 9.9:
                return SimpleNamespace(returncode=1, stderr=b"conversion failed")
            with open(cmd[-1], "wb") as out:
                out.write(b"jpg")
            return SimpleNamespace(returncode=0, stderr=b"")

        with mock.patch.object(app, "_project_ffmpeg_bin", return_value="/bin/ffmpeg"), \
                mock.patch.object(app, "_probe_video_timing", return_value=(10.0, 24.0)), \
                mock.patch.object(app.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(app.random, "randint", return_value=1234):
            result = app.api_history_video_frame(
                "vid-end",
                {"time": 10.0, "import_input": True},
                current_user={"sub": "u1", "role": "user"},
            )

        self.assertTrue(result["ok"])
        self.assertLess(result["time"], 9.9)
        self.assertGreaterEqual(len(attempts), 2)
        self.assertTrue(os.path.isfile(os.path.join(app.OUTPUT_DIR, result["frame"])))
        self.assertTrue(os.path.isfile(os.path.join(app.COMFYUI_INPUT, result["input_filename"])))

    def test_safe_video_frame_time_clamps_duration_boundary(self):
        self.assertAlmostEqual(app._safe_video_frame_time(10.0, 10.0, 25.0), 9.96, places=3)
        self.assertEqual(app._safe_video_frame_time(99.0, 0.0, 0.0), 99.0)
        self.assertLess(app._safe_video_frame_time(0.2, 0.3, 24.0), 0.3)

    def test_history_summary_returns_lightweight_signature(self):
        for idx in range(3):
            app._insert_generation(
                {
                    "id": f"hist-{idx}",
                    "workflow": "t2i-test.json",
                    "filename": f"hist-{idx}.png",
                    "prompt": "hello",
                    "time": f"2026-05-18 12:00:0{idx}",
                },
                elapsed=3,
                user_id="u1",
            )

        result = app.api_history_summary(limit=2, scope="mine", current_user={"sub": "u1", "role": "user"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["count"], 2)
        self.assertIn("total:3", result["signature"])
        self.assertFalse([entry for entry in app._log_buffer if entry.get("phase") == "thumbnail"])

    def test_workflow_previews_use_current_user_latest_item(self):
        rows = [
            ("u1-old", "wf-a.json", "u1", "u1-old.png", "2026-05-18 12:00:00"),
            ("u2-newer", "wf-a.json", "u2", "u2-newer.png", "2026-05-18 12:05:00"),
            ("u1-newest", "wf-a.json", "u1", "u1-newest.png", "2026-05-18 12:02:00"),
            ("u1-wfb", "wf-b.json", "u1", "u1-wfb.png", "2026-05-18 12:03:00"),
        ]
        for item_id, workflow, uid, filename, created_at in rows:
            app._insert_generation(
                {
                    "id": item_id,
                    "workflow": workflow,
                    "filename": filename,
                    "prompt": item_id,
                    "time": created_at,
                },
                elapsed=3,
                user_id=uid,
            )

        result = app.api_workflow_previews(current_user={"sub": "u1", "role": "user"})

        by_workflow = {item["workflow"]: item for item in result["data"]}
        self.assertEqual(by_workflow["wf-a.json"]["id"], "u1-newest")
        self.assertEqual(by_workflow["wf-a.json"]["workflow_count"], 2)
        self.assertEqual(by_workflow["wf-b.json"]["id"], "u1-wfb")
        self.assertNotIn("u2-newer", [item["id"] for item in result["data"]])

    def test_hidden_history_is_excluded_from_gallery_and_listed_in_hidden_scope(self):
        for item_id in ("visible", "hidden"):
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

        hidden = app.api_history_hide("hidden", {"is_hidden": True}, current_user={"sub": "u1", "role": "user"})
        gallery = app.api_history(limit=10, scope="mine", current_user={"sub": "u1", "role": "user"})
        hidden_scope = app.api_history(limit=10, scope="hidden", current_user={"sub": "u1", "role": "user"})

        self.assertTrue(hidden["is_hidden"])
        self.assertEqual([item["id"] for item in gallery["data"]], ["visible"])
        self.assertEqual([item["id"] for item in hidden_scope["data"]], ["hidden"])
        self.assertTrue(hidden_scope["data"][0]["is_hidden"])

    def test_workflow_previews_skip_hidden_items(self):
        rows = [
            ("visible-old", "wf-a.json", "visible-old.png", "2026-05-18 12:00:00"),
            ("hidden-new", "wf-a.json", "hidden-new.png", "2026-05-18 12:05:00"),
        ]
        for item_id, workflow, filename, created_at in rows:
            app._insert_generation(
                {
                    "id": item_id,
                    "workflow": workflow,
                    "filename": filename,
                    "prompt": item_id,
                    "time": created_at,
                },
                elapsed=3,
                user_id="u1",
            )
        app.api_history_hide("hidden-new", {"is_hidden": True}, current_user={"sub": "u1", "role": "user"})

        result = app.api_workflow_previews(current_user={"sub": "u1", "role": "user"})

        self.assertEqual(result["data"][0]["id"], "visible-old")
        self.assertEqual(result["counts"]["wf-a.json"], 1)

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

    def test_missing_pillow_does_not_abort_thumbnail_generation(self):
        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "PIL" or name.startswith("PIL."):
                raise ModuleNotFoundError("No module named 'PIL'")
            return original_import(name, *args, **kwargs)

        try:
            builtins.__import__ = fake_import
            result = app._make_thumbnail_with_pillow(
                os.path.join(app.OUTPUT_DIR, "missing.png"),
                os.path.join(app.OUTPUT_DIR, "missing_thumb.jpg"),
            )
        finally:
            builtins.__import__ = original_import

        self.assertFalse(result)
        self.assertTrue([
            entry for entry in app._log_buffer
            if entry.get("phase") == "thumbnail" and "pillow unavailable" in entry.get("msg", "")
        ])

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

    def test_admin_can_manually_toggle_history_protection(self):
        app._insert_generation(
            {
                "id": "hist-protect",
                "workflow": "t2i-test.json",
                "filename": "hist-protect.png",
                "prompt": "hello",
                "time": "2026-05-18 12:00:00",
                "protection_status": "protected",
                "protection_score": 0.92,
                "protection_reason": "old detector",
                "protection_source": "detector",
            },
            elapsed=3,
            user_id="u1",
        )

        with mock.patch("app._schedule_broadcast") as schedule:
            result = app.api_history_protection(
                "hist-protect",
                {"protection_status": "safe"},
                current_user={"sub": "admin", "role": "admin"},
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["protection_status"], "safe")
        self.assertEqual(result["protection_source"], "manual-admin")
        history_result = app.api_history(limit=10, scope="all", current_user={"sub": "admin", "role": "admin"})
        self.assertEqual(history_result["data"][0]["protection_status"], "safe")
        self.assertEqual(history_result["data"][0]["protection_source"], "manual-admin")
        schedule.assert_called_once()
        payload = schedule.call_args.args[0]
        self.assertEqual(payload["type"], "history_update")
        self.assertEqual(payload["action"], "protection")
        self.assertEqual(payload["ids"], ["hist-protect"])
        self.assertEqual(payload["protection_status"], "safe")
        self.assertEqual(payload["protection_score"], 0.0)
        self.assertEqual(payload["protection_reason"], "admin manual safe")
        self.assertEqual(payload["protection_source"], "manual-admin")
        self.assertGreater(payload["protection_checked_at"], "")

    def test_non_admin_cannot_manually_toggle_history_protection(self):
        app._insert_generation(
            {
                "id": "hist-protect",
                "workflow": "t2i-test.json",
                "filename": "hist-protect.png",
                "prompt": "hello",
                "time": "2026-05-18 12:00:00",
            },
            elapsed=3,
            user_id="u1",
        )

        with self.assertRaises(HTTPException) as ctx:
            app.api_history_protection(
                "hist-protect",
                {"protection_status": "protected"},
                current_user={"sub": "u1", "role": "user"},
            )

        self.assertEqual(ctx.exception.status_code, 403)

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

    def test_deleted_safe_heuristic_strong_nude_rows_are_rechecked_when_prompt_protection_is_on(self):
        old_settings = app.get_image_protection_settings()
        app.configure_image_protection({"prompt_signals_enabled": True})
        try:
            rel_path = "u1/2026-05-25/deleted-nude-risk.png"
            abs_path = os.path.join(app.OUTPUT_DIR, rel_path)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            Image.new("RGB", (48, 48), (8, 10, 12)).save(abs_path)
            app._insert_generation(
                {
                    "id": "hist-deleted-nude-safe",
                    "workflow": "t2i-test.json",
                    "filename": rel_path,
                    "prompt": "保持画面任务一致，让人物保持裸体",
                    "time": "2026-05-25 22:18:15",
                    "protection_status": "safe",
                    "protection_score": 0.95,
                    "protection_source": "heuristic",
                    "protection_reason": "local heuristic skin_ratio=0.046",
                    "protection_checked_at": "2026-05-25 22:18:16",
                },
                elapsed=3,
                user_id="u1",
            )
            conn = sqlite3.connect(app.GEN_DB)
            conn.execute(
                "UPDATE generations SET deleted_at='2026-05-25 22:38:28' WHERE id='hist-deleted-nude-safe'"
            )
            conn.commit()
            conn.close()

            app._recheck_safe_heuristic_nsfw_risk_rows()

            conn = sqlite3.connect(app.GEN_DB)
            row = conn.execute(
                "SELECT protection_status, protection_reason FROM generations WHERE id='hist-deleted-nude-safe'"
            ).fetchone()
            conn.close()
        finally:
            app.configure_image_protection(old_settings)

        self.assertEqual(row[0], "protected")
        self.assertEqual(row[1], "strong nude prompt")

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

    def test_delete_broadcasts_history_update_for_open_pages(self):
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

        with mock.patch("app._schedule_broadcast") as schedule:
            result = app.api_history_delete("hist-1", current_user=user)

        self.assertTrue(result["ok"])
        schedule.assert_called_once()
        payload = schedule.call_args.args[0]
        self.assertEqual(payload["type"], "history_update")
        self.assertEqual(payload["action"], "delete")
        self.assertEqual(payload["ids"], ["hist-1"])
        self.assertEqual(payload["user_id"], "u1")
        self.assertTrue(payload["deleted_at"])

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
        app._insert_generation(
            {
                "id": "hist-1",
                "workflow": "t2i-test.json",
                "filename": "u1/2026-05-18/hist-1.png",
                "prompt": "hello",
                "time": "2026-05-18 12:00:00",
                "is_public": True,
            },
            elapsed=3,
            user_id="u1",
        )

        ok = app.api_image("u1/2026-05-18/hist-1.png", current_user=None)
        self.assertEqual(ok.path, output_image)
        download = app.api_image("u1/2026-05-18/hist-1.png", download=True, current_user=None)
        self.assertEqual(download.path, output_image)
        self.assertIn("attachment", download.headers["content-disposition"])
        self.assertIn("hist-1.png", download.headers["content-disposition"])
        with self.assertRaises(HTTPException):
            app.api_image("u1/2026-05-18/hist-2.png", current_user=None)

    def test_public_history_media_is_readable_without_login(self):
        output_image = os.path.join(app.OUTPUT_DIR, "u1", "2026-05-18", "public.png")
        thumb_image = os.path.join(app.OUTPUT_DIR, "u1", "2026-05-18", "public_thumb.jpg")
        os.makedirs(os.path.dirname(output_image), exist_ok=True)
        with open(output_image, "wb") as f:
            f.write(b"image")
        with open(thumb_image, "wb") as f:
            f.write(b"thumb")
        app._insert_generation(
            {
                "id": "public-media",
                "workflow": "t2i-test.json",
                "filename": "u1/2026-05-18/public.png",
                "thumb": "u1/2026-05-18/public_thumb.jpg",
                "prompt": "hello",
                "time": "2026-05-18 12:00:00",
                "is_public": True,
            },
            elapsed=3,
            user_id="u1",
        )

        image = app.api_image("u1/2026-05-18/public.png", current_user=None)
        thumb = app.api_thumb("u1/2026-05-18/public_thumb.jpg", current_user=None)

        self.assertEqual(image.path, output_image)
        self.assertEqual(thumb.path, thumb_image)

    def test_private_history_media_requires_owner_or_admin(self):
        output_image = os.path.join(app.OUTPUT_DIR, "u1", "private.png")
        os.makedirs(os.path.dirname(output_image), exist_ok=True)
        with open(output_image, "wb") as f:
            f.write(b"image")
        app._insert_generation(
            {
                "id": "private-media",
                "workflow": "t2i-test.json",
                "filename": "u1/private.png",
                "prompt": "hello",
                "time": "2026-05-18 12:00:00",
                "is_public": False,
            },
            elapsed=3,
            user_id="u1",
        )

        with self.assertRaises(HTTPException):
            app.api_image("u1/private.png", current_user=None)
        owner = app.api_image("u1/private.png", current_user={"sub": "u1", "role": "user"})

        self.assertEqual(owner.path, output_image)


if __name__ == "__main__":
    unittest.main()
