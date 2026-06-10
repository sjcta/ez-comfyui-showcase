"""Helpers for selecting ComfyUI image/video outputs."""

from __future__ import annotations

import os
from typing import Any


IMAGE_OUTPUT_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_OUTPUT_EXTS = {".mp4", ".webm", ".mov", ".m4v"}
MEDIA_OUTPUT_EXTS = IMAGE_OUTPUT_EXTS | VIDEO_OUTPUT_EXTS
VIDEO_OUTPUT_KEYS = ("videos", "gifs", "animated")
SAVE_OUTPUT_CLASSES = (
    "SaveImage",
    "SaveVideo",
    "VHS_VideoCombine",
    "VHS_SaveVideo",
)


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
    for node_id, node_out in (outputs or {}).items():
        if not isinstance(node_out, dict):
            continue
        for key in keys:
            for ref in node_out.get(key, []) or []:
                if isinstance(ref, dict) and is_media_output(ref.get("filename", "")):
                    item = dict(ref)
                    item.setdefault("_node_id", str(node_id))
                    yield item


def _workflow_node_class(workflow: dict[str, Any] | None, node_id: str) -> str:
    node = (workflow or {}).get(str(node_id), {})
    if not isinstance(node, dict):
        return ""
    return str(node.get("class_type") or "")


def _save_output_node_ids(workflow: dict[str, Any] | None) -> set[str]:
    node_ids: set[str] = set()
    for node_id, node in (workflow or {}).items():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type") or "")
        if class_type in SAVE_OUTPUT_CLASSES or class_type.startswith("Save"):
            node_ids.add(str(node_id))
    return node_ids


def _history_prompt_workflow(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    prompt = (entry or {}).get("prompt")
    if isinstance(prompt, dict):
        return prompt
    if isinstance(prompt, (list, tuple)):
        for item in prompt:
            if not isinstance(item, dict):
                continue
            if any(
                isinstance(node, dict) and "class_type" in node
                for node in item.values()
            ):
                return item
    return None


def _prefer_media(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    videos = [ref for ref in refs if is_video_output(ref.get("filename", ""))]
    if videos:
        return videos
    return [ref for ref in refs if is_image_output(ref.get("filename", ""))]


def collect_preferred_outputs(
    outputs: dict[str, Any],
    workflow: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return saved output media first, then fall back to video/image preference."""
    all_media = [
        ref for ref in _iter_refs(outputs, VIDEO_OUTPUT_KEYS + ("images",))
        if is_media_output(ref.get("filename", ""))
    ]
    save_node_ids = _save_output_node_ids(workflow)
    if save_node_ids:
        saved_media = [
            ref for ref in all_media
            if str(ref.get("_node_id", "")) in save_node_ids
        ]
        if saved_media:
            return _prefer_media(saved_media)

    return _prefer_media(all_media)


def collect_preferred_history_outputs(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Select preferred outputs from a ComfyUI history entry."""
    return collect_preferred_outputs(
        (entry or {}).get("outputs", {}),
        workflow=_history_prompt_workflow(entry),
    )


def collect_legacy_preferred_outputs(outputs: dict[str, Any]) -> list[dict[str, Any]]:
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
