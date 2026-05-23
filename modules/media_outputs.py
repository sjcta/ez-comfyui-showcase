"""Helpers for selecting ComfyUI image/video outputs."""

from __future__ import annotations

import os
from typing import Any


IMAGE_OUTPUT_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_OUTPUT_EXTS = {".mp4", ".webm", ".mov", ".m4v"}
MEDIA_OUTPUT_EXTS = IMAGE_OUTPUT_EXTS | VIDEO_OUTPUT_EXTS
VIDEO_OUTPUT_KEYS = ("videos", "gifs", "animated")


def output_media_type(filename: str) -> str:
    ext = os.path.splitext(str(filename or ""))[1].lower()
    if ext in VIDEO_OUTPUT_EXTS:
        return "video"
    return "image"


def is_image_output(filename: str) -> bool:
    return os.path.splitext(str(filename or ""))[1].lower() in IMAGE_OUTPUT_EXTS


def is_video_output(filename: str) -> bool:
    return os.path.splitext(str(filename or ""))[1].lower() in VIDEO_OUTPUT_EXTS


def is_media_output(filename: str) -> bool:
    return os.path.splitext(str(filename or ""))[1].lower() in MEDIA_OUTPUT_EXTS


def output_ref_rel_path(ref: dict[str, Any]) -> str:
    filename = str((ref or {}).get("filename") or "").replace("\\", "/").lstrip("/")
    subfolder = str((ref or {}).get("subfolder") or "").replace("\\", "/").strip("/")
    if subfolder and filename and not filename.startswith(subfolder + "/"):
        return f"{subfolder}/{filename}"
    return filename


def _iter_refs(outputs: dict[str, Any], keys: tuple[str, ...]):
    for node_out in (outputs or {}).values():
        if not isinstance(node_out, dict):
            continue
        for key in keys:
            for ref in node_out.get(key, []) or []:
                if isinstance(ref, dict) and is_media_output(ref.get("filename", "")):
                    yield dict(ref)


def collect_preferred_outputs(outputs: dict[str, Any]) -> list[dict[str, Any]]:
    """Return videos when present; otherwise return image outputs."""
    videos = [
        ref for ref in _iter_refs(outputs, VIDEO_OUTPUT_KEYS)
        if is_video_output(ref.get("filename", ""))
    ]
    if videos:
        return videos

    image_key_media = [
        ref for ref in _iter_refs(outputs, ("images",))
        if is_media_output(ref.get("filename", ""))
    ]
    image_key_videos = [
        ref for ref in image_key_media
        if is_video_output(ref.get("filename", ""))
    ]
    if image_key_videos:
        return image_key_videos

    return [
        ref for ref in image_key_media
        if is_image_output(ref.get("filename", ""))
    ]
