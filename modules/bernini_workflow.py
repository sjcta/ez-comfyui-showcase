"""Bernini mixed-mode workflow helpers.

The ComfyUI Bernini node infers its task from connected optional inputs.  The
web UI keeps a small virtual control surface, then these helpers turn it into a
real prompt graph before validation/submission.
"""

from __future__ import annotations

import json
import os
from typing import Any


BERNINI_WORKFLOW_NAMES = {"t2i_bernini_fp8.json"}
BERNINI_CONDITIONING_CLASS = "BerniniConditioning"

MODE_FIELD = "50::__bernini_mode"
REFS_FIELD = "50::__bernini_refs"
FRAMES_FIELD = "50::__bernini_frames"
FPS_FIELD = "50::__bernini_fps"

COND_NODE_ID = "50"
SAVE_IMAGE_NODE_ID = "100"
SAVE_VIDEO_NODE_ID = "920"
SOURCE_IMAGE_NODE_ID = "910"
REF_IMAGE_NODE_START = 911
MAX_REFERENCE_IMAGES = 8

IMAGE_MODES = {"t2i", "i2i"}
VIDEO_MODES = {"i2v", "r2v"}
VALID_MODES = IMAGE_MODES | VIDEO_MODES

VIRTUAL_INPUTS = {
    "__bernini_mode",
    "__bernini_refs",
    "__bernini_frames",
    "__bernini_fps",
}


def is_bernini_workflow(workflow: dict[str, Any], workflow_name: str = "") -> bool:
    basename = os.path.basename(str(workflow_name or ""))
    if basename in BERNINI_WORKFLOW_NAMES:
        return True
    return any(
        isinstance(node, dict) and node.get("class_type") == BERNINI_CONDITIONING_CLASS
        for node in (workflow or {}).values()
    )


def _field_value(field_values: dict[str, Any] | None, *keys: str, default: Any = None) -> Any:
    values = field_values or {}
    for key in keys:
        if key in values and values[key] not in (None, ""):
            return values[key]
    return default


def bernini_mode(field_values: dict[str, Any] | None) -> str:
    raw = str(_field_value(field_values, MODE_FIELD, "__bernini_mode", default="t2i") or "t2i").strip().lower()
    aliases = {
        "txt2img": "t2i",
        "text2image": "t2i",
        "text-to-image": "t2i",
        "img2img": "i2i",
        "image2image": "i2i",
        "image-to-image": "i2i",
        "img2video": "i2v",
        "image2video": "i2v",
        "image-to-video": "i2v",
        "ref2video": "r2v",
        "reference-to-video": "r2v",
    }
    mode = aliases.get(raw, raw)
    if mode not in VALID_MODES:
        raise ValueError(f"不支持的 Bernini 模式: {raw}")
    return mode


def bernini_reference_images(field_values: dict[str, Any] | None) -> list[str]:
    raw = _field_value(field_values, REFS_FIELD, "__bernini_refs", default=[])
    items: list[Any]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            items = []
        else:
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = [part.strip() for part in text.split(",")]
            items = parsed if isinstance(parsed, list) else [parsed]
    elif isinstance(raw, list):
        items = raw
    else:
        items = []

    refs: list[str] = []
    seen: set[str] = set()
    for item in items:
        name = str(item or "").strip()
        if not name or name in seen:
            continue
        refs.append(name)
        seen.add(name)
    return refs[:MAX_REFERENCE_IMAGES]


def _int_value(value: Any, default: int, minimum: int = 0, maximum: int = 0) -> int:
    try:
        result = int(float(value))
    except (TypeError, ValueError):
        result = default
    if minimum:
        result = max(minimum, result)
    if maximum:
        result = min(maximum, result)
    return result


def _legal_video_frame_count(value: Any) -> int:
    frames = _int_value(value, 81, minimum=5, maximum=145)
    if (frames - 1) % 4 == 0:
        return frames
    snapped = ((frames - 1 + 3) // 4) * 4 + 1
    return min(145, max(5, snapped))


def bernini_video_fps(field_values: dict[str, Any] | None) -> int:
    return _int_value(_field_value(field_values, FPS_FIELD, "101::frame_rate", "__bernini_fps", default=16), 16, 1, 60)


def normalize_bernini_field_values(
    workflow: dict[str, Any],
    field_values: dict[str, Any],
    workflow_name: str = "",
) -> dict[str, Any]:
    if not is_bernini_workflow(workflow, workflow_name):
        return field_values

    mode = bernini_mode(field_values)
    refs = bernini_reference_images(field_values)
    raw_frames = _field_value(field_values, FRAMES_FIELD, "50::length", "__bernini_frames", default=81)
    frames = 1 if mode in IMAGE_MODES else _legal_video_frame_count(raw_frames)
    fps = bernini_video_fps(field_values)

    field_values[MODE_FIELD] = mode
    field_values[REFS_FIELD] = json.dumps(refs, ensure_ascii=False, separators=(",", ":"))
    field_values[FRAMES_FIELD] = frames
    field_values[FPS_FIELD] = fps
    field_values["50::length"] = frames

    image_prefix = f"bernini_fp8/Bernini_{mode}"
    video_prefix = f"bernini_fp8/Bernini_{mode}"
    field_values.setdefault("100::filename_prefix", image_prefix)
    field_values.setdefault(f"{SAVE_VIDEO_NODE_ID}::filename_prefix", video_prefix)
    return field_values


def _conditioning_node(workflow: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    node = workflow.get(COND_NODE_ID)
    if isinstance(node, dict) and node.get("class_type") == BERNINI_CONDITIONING_CLASS:
        return COND_NODE_ID, node
    for node_id, candidate in workflow.items():
        if isinstance(candidate, dict) and candidate.get("class_type") == BERNINI_CONDITIONING_CLASS:
            return str(node_id), candidate
    raise RuntimeError("当前 Bernini 工作流缺少 BerniniConditioning 节点")


def _remove_runtime_reference_nodes(workflow: dict[str, Any]) -> None:
    workflow.pop(SOURCE_IMAGE_NODE_ID, None)
    for index in range(MAX_REFERENCE_IMAGES):
        workflow.pop(str(REF_IMAGE_NODE_START + index), None)


def _load_image_node(filename: str, title: str) -> dict[str, Any]:
    return {
        "class_type": "LoadImage",
        "inputs": {"image": filename},
        "_meta": {"title": title},
    }


def _ensure_save_image_node(workflow: dict[str, Any], prefix: str) -> None:
    node = workflow.get(SAVE_IMAGE_NODE_ID)
    if not isinstance(node, dict) or node.get("class_type") != "SaveImage":
        workflow[SAVE_IMAGE_NODE_ID] = {
            "class_type": "SaveImage",
            "inputs": {"images": ["16", 0], "filename_prefix": prefix},
            "_meta": {"title": "Bernini 图片输出"},
        }
        return
    node.setdefault("inputs", {})["filename_prefix"] = prefix


def _ensure_save_video_node(workflow: dict[str, Any], prefix: str, fps: int) -> None:
    workflow[SAVE_VIDEO_NODE_ID] = {
        "class_type": "VHS_VideoCombine",
        "inputs": {
            "images": ["16", 0],
            "frame_rate": fps,
            "loop_count": 0,
            "filename_prefix": prefix,
            "format": "video/h264-mp4",
            "pix_fmt": "yuv420p",
            "crf": 19,
            "save_metadata": True,
            "pingpong": False,
            "save_output": True,
        },
        "_meta": {"title": "Bernini MP4 输出"},
    }


def _clean_conditioning_inputs(inputs: dict[str, Any]) -> None:
    for key in ("source_video", "reference_video", "reference_images"):
        inputs.pop(key, None)
    for key in VIRTUAL_INPUTS:
        inputs.pop(key, None)


def apply_bernini_mixed_mode_to_workflow(
    workflow: dict[str, Any],
    field_values: dict[str, Any] | None,
    workflow_name: str = "",
) -> dict[str, Any]:
    if not is_bernini_workflow(workflow, workflow_name):
        return workflow

    mode = bernini_mode(field_values)
    refs = bernini_reference_images(field_values)
    raw_frames = _field_value(field_values, FRAMES_FIELD, "50::length", "__bernini_frames", default=81)
    frames = 1 if mode in IMAGE_MODES else _legal_video_frame_count(raw_frames)
    fps = bernini_video_fps(field_values)

    _cond_id, cond_node = _conditioning_node(workflow)
    cond_inputs = cond_node.setdefault("inputs", {})
    _clean_conditioning_inputs(cond_inputs)
    cond_inputs["length"] = frames

    _remove_runtime_reference_nodes(workflow)

    if mode != "t2i" and not refs:
        raise RuntimeError("Bernini 的 i2i / i2v / r2v 模式需要至少 1 张参考图")

    if mode in IMAGE_MODES:
        workflow.pop(SAVE_VIDEO_NODE_ID, None)
        _ensure_save_image_node(workflow, f"bernini_fp8/Bernini_{mode}")
    else:
        workflow.pop(SAVE_IMAGE_NODE_ID, None)
        _ensure_save_video_node(workflow, f"bernini_fp8/Bernini_{mode}", fps)

    if mode == "i2i":
        workflow[SOURCE_IMAGE_NODE_ID] = _load_image_node(refs[0], "Bernini 源图")
        cond_inputs["source_video"] = [SOURCE_IMAGE_NODE_ID, 0]
    elif mode in VIDEO_MODES:
        ref_links: dict[str, list[Any]] = {}
        limit = 1 if mode == "i2v" else MAX_REFERENCE_IMAGES
        for index, filename in enumerate(refs[:limit]):
            node_id = str(REF_IMAGE_NODE_START + index)
            workflow[node_id] = _load_image_node(filename, f"Bernini 参考图 {index + 1}")
            ref_links[f"reference_image_{index}"] = [node_id, 0]
        cond_inputs["reference_images"] = ref_links

    return workflow
