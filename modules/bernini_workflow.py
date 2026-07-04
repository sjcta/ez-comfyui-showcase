"""Bernini mixed-mode workflow helpers.

The active Bernini entry now targets RH's full Bernini-Diffusers wrapper.  The
UI stores a small virtual control surface, then these helpers rebuild the real
ComfyUI API graph for the chosen task before validation/submission.
"""

from __future__ import annotations

import json
import os
from typing import Any


BERNINI_WORKFLOW_NAMES = {"t2i_bernini_fp8.json"}
BERNINI_CONDITIONING_CLASS = "BerniniConditioning"
BERNINI_FULL_CLASS_PREFIX = "RHBerniniFull"

FULL_NODE_ID = "1"
SAVE_NODE_ID = "2"
VIDEO_LOADER_NODE_ID = "900"
REF_IMAGE_NODE_START = 910
IMAGE_BATCH_NODE_START = 950
MAX_REFERENCE_IMAGES = 8

MODE_FIELD = f"{FULL_NODE_ID}::__bernini_mode"
REFS_FIELD = f"{FULL_NODE_ID}::__bernini_refs"
FRAMES_FIELD = f"{FULL_NODE_ID}::__bernini_frames"
FPS_FIELD = f"{FULL_NODE_ID}::__bernini_fps"
VIDEO_FIELD = f"{VIDEO_LOADER_NODE_ID}::video"
FULL_VIDEO_FIELD = f"{VIDEO_LOADER_NODE_ID}::file"

LEGACY_MODE_FIELD = "50::__bernini_mode"
LEGACY_REFS_FIELD = "50::__bernini_refs"
LEGACY_FRAMES_FIELD = "50::__bernini_frames"
LEGACY_FPS_FIELD = "50::__bernini_fps"

LEGACY_COND_NODE_ID = "50"
LEGACY_SAVE_IMAGE_NODE_ID = "100"
SAVE_VIDEO_NODE_ID = "920"
LEGACY_SOURCE_IMAGE_NODE_ID = "910"
LEGACY_REF_IMAGE_NODE_START = 911

IMAGE_MODES = {"t2i", "i2i"}
VIDEO_MODES = {"t2v", "v2v", "i2v", "r2v", "rv2v"}
REFERENCE_IMAGE_MODES = {"i2i", "i2v", "r2v", "rv2v"}
SOURCE_VIDEO_MODES = {"v2v", "rv2v"}
VALID_MODES = IMAGE_MODES | VIDEO_MODES

FULL_NODE_CLASS_BY_MODE = {
    "t2i": "RHBerniniFullTextToImage",
    "i2i": "RHBerniniFullImageToImage",
    "t2v": "RHBerniniFullTextToVideo",
    "v2v": "RHBerniniFullVideoToVideo",
    "i2v": "RHBerniniFullReferenceToVideo",
    "r2v": "RHBerniniFullReferenceToVideo",
    "rv2v": "RHBerniniFullReferenceVideoToVideo",
}

DEFAULT_NEGATIVE_PROMPT = "low quality, blurry, distorted, text, watermark"
DEFAULT_PROMPT = "A cinematic portrait with rich detail, natural light, and expressive motion"

VIRTUAL_INPUTS = {
    "__bernini_mode",
    "__bernini_refs",
    "__bernini_frames",
    "__bernini_fps",
}


def _basename(workflow_name: str = "") -> str:
    return os.path.basename(str(workflow_name or ""))


def _has_full_node(workflow: dict[str, Any]) -> bool:
    return any(
        isinstance(node, dict) and str(node.get("class_type") or "").startswith(BERNINI_FULL_CLASS_PREFIX)
        for node in (workflow or {}).values()
    )


def _has_legacy_node(workflow: dict[str, Any]) -> bool:
    return any(
        isinstance(node, dict) and node.get("class_type") == BERNINI_CONDITIONING_CLASS
        for node in (workflow or {}).values()
    )


def is_bernini_workflow(workflow: dict[str, Any], workflow_name: str = "") -> bool:
    if _basename(workflow_name) in BERNINI_WORKFLOW_NAMES:
        return True
    return _has_full_node(workflow) or _has_legacy_node(workflow)


def _uses_full_workflow(workflow: dict[str, Any], workflow_name: str = "") -> bool:
    if _has_full_node(workflow):
        return True
    return _basename(workflow_name) in BERNINI_WORKFLOW_NAMES and not _has_legacy_node(workflow)


def _field_value(field_values: dict[str, Any] | None, *keys: str, default: Any = None) -> Any:
    values = field_values or {}
    for key in keys:
        if key in values and values[key] not in (None, ""):
            return values[key]
    return default


def bernini_mode(field_values: dict[str, Any] | None) -> str:
    raw = str(
        _field_value(
            field_values,
            MODE_FIELD,
            LEGACY_MODE_FIELD,
            "__bernini_mode",
            default="t2i",
        )
        or "t2i"
    ).strip().lower()
    aliases = {
        "txt2img": "t2i",
        "text2image": "t2i",
        "text-to-image": "t2i",
        "img2img": "i2i",
        "image2image": "i2i",
        "image-to-image": "i2i",
        "txt2video": "t2v",
        "text2video": "t2v",
        "text-to-video": "t2v",
        "video2video": "v2v",
        "video-to-video": "v2v",
        "img2video": "i2v",
        "image2video": "i2v",
        "image-to-video": "i2v",
        "ref2video": "r2v",
        "reference2video": "r2v",
        "reference-to-video": "r2v",
        "reference-video-to-video": "rv2v",
        "ref-video-to-video": "rv2v",
    }
    mode = aliases.get(raw, raw)
    if mode not in VALID_MODES:
        raise ValueError(f"不支持的 Bernini 模式: {raw}")
    return mode


def bernini_reference_images(field_values: dict[str, Any] | None) -> list[str]:
    raw = _field_value(field_values, REFS_FIELD, LEGACY_REFS_FIELD, "__bernini_refs", default=[])
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            items: list[Any] = []
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


def bernini_source_video(field_values: dict[str, Any] | None) -> str:
    return str(_field_value(field_values, VIDEO_FIELD, FULL_VIDEO_FIELD, "__bernini_video", default="") or "").strip()


def _int_value(value: Any, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        result = int(float(value))
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _legal_video_frame_count(value: Any) -> int:
    frames = _int_value(value, 81, minimum=5, maximum=129)
    if (frames - 1) % 4 == 0:
        return frames
    snapped = ((frames - 1 + 3) // 4) * 4 + 1
    return min(129, max(5, snapped))


def bernini_video_fps(field_values: dict[str, Any] | None) -> int:
    return _int_value(
        _field_value(field_values, FPS_FIELD, LEGACY_FPS_FIELD, f"{FULL_NODE_ID}::fps", "__bernini_fps", default=16),
        16,
        1,
        60,
    )


def normalize_bernini_field_values(
    workflow: dict[str, Any],
    field_values: dict[str, Any],
    workflow_name: str = "",
) -> dict[str, Any]:
    if not is_bernini_workflow(workflow, workflow_name):
        return field_values

    mode = bernini_mode(field_values)
    refs = bernini_reference_images(field_values)
    raw_frames = _field_value(
        field_values,
        FRAMES_FIELD,
        LEGACY_FRAMES_FIELD,
        f"{FULL_NODE_ID}::num_frames",
        "__bernini_frames",
        default=81,
    )
    frames = 1 if mode in IMAGE_MODES else _legal_video_frame_count(raw_frames)
    fps = bernini_video_fps(field_values)
    refs_json = json.dumps(refs, ensure_ascii=False, separators=(",", ":"))

    if _uses_full_workflow(workflow, workflow_name):
        field_values[MODE_FIELD] = mode
        field_values[REFS_FIELD] = refs_json
        field_values[FRAMES_FIELD] = frames
        field_values[FPS_FIELD] = fps
        field_values[f"{FULL_NODE_ID}::num_frames"] = frames
        field_values[f"{FULL_NODE_ID}::fps"] = fps
        field_values.setdefault(f"{FULL_NODE_ID}::steps", 4)
        field_values.setdefault(f"{FULL_NODE_ID}::quality_preset", "standard")
        field_values.setdefault(f"{FULL_NODE_ID}::acceleration", "wan2.2_lightx2v_4step")
        field_values.setdefault(f"{FULL_NODE_ID}::memory_mode", "keep_loaded_batch")
        field_values.setdefault(f"{SAVE_NODE_ID}::filename_prefix", f"bernini_full/Bernini_{mode}")
        if mode in SOURCE_VIDEO_MODES:
            field_values[FULL_VIDEO_FIELD] = bernini_source_video(field_values)
            field_values[f"{FULL_NODE_ID}::width"] = 0
            field_values[f"{FULL_NODE_ID}::height"] = 0
        return field_values

    field_values[LEGACY_MODE_FIELD] = mode
    field_values[LEGACY_REFS_FIELD] = refs_json
    field_values[LEGACY_FRAMES_FIELD] = frames
    field_values[LEGACY_FPS_FIELD] = fps
    field_values["50::length"] = frames
    field_values[VIDEO_FIELD] = bernini_source_video(field_values)
    if "19::noise_seed" in field_values:
        field_values["15::noise_seed"] = field_values["19::noise_seed"]
    field_values.setdefault("100::filename_prefix", f"bernini_q4/Bernini_{mode}")
    field_values.setdefault(f"{SAVE_VIDEO_NODE_ID}::filename_prefix", f"bernini_q4/Bernini_{mode}")
    return field_values


def _string_value(field_values: dict[str, Any] | None, key: str, default: str = "") -> str:
    value = _field_value(field_values, key, default=default)
    return str(value if value is not None else default)


def _full_prompt_inputs(field_values: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "prompt": _string_value(field_values, f"{FULL_NODE_ID}::prompt", DEFAULT_PROMPT).strip() or DEFAULT_PROMPT,
        "negative_prompt": _string_value(field_values, f"{FULL_NODE_ID}::negative_prompt", DEFAULT_NEGATIVE_PROMPT),
        "steps": _int_value(_field_value(field_values, f"{FULL_NODE_ID}::steps", default=4), 4, 1, 100),
        "seed": _int_value(_field_value(field_values, f"{FULL_NODE_ID}::seed", default=42), 42, 0, 0xFFFFFFFF),
        "quality_preset": _string_value(field_values, f"{FULL_NODE_ID}::quality_preset", "standard") or "standard",
        "acceleration": _string_value(field_values, f"{FULL_NODE_ID}::acceleration", "wan2.2_lightx2v_4step")
        or "wan2.2_lightx2v_4step",
        "memory_mode": _string_value(field_values, f"{FULL_NODE_ID}::memory_mode", "keep_loaded_batch")
        or "keep_loaded_batch",
    }


def _full_dimensions(field_values: dict[str, Any] | None, mode: str) -> tuple[int, int]:
    if mode in SOURCE_VIDEO_MODES:
        return 0, 0
    width = _int_value(_field_value(field_values, f"{FULL_NODE_ID}::width", default=512), 512, 64, 2048)
    height = _int_value(_field_value(field_values, f"{FULL_NODE_ID}::height", default=512), 512, 64, 2048)
    return width, height


def _full_frames(field_values: dict[str, Any] | None, mode: str) -> int:
    if mode in IMAGE_MODES:
        return 1
    raw = _field_value(field_values, FRAMES_FIELD, f"{FULL_NODE_ID}::num_frames", "__bernini_frames", default=81)
    return _legal_video_frame_count(raw)


def _output_prefix(field_values: dict[str, Any] | None, mode: str, default_root: str = "bernini_full") -> str:
    return (
        _string_value(field_values, f"{SAVE_NODE_ID}::filename_prefix", "")
        or _string_value(field_values, "100::filename_prefix", "")
        or _string_value(field_values, f"{SAVE_VIDEO_NODE_ID}::filename_prefix", "")
        or f"{default_root}/Bernini_{mode}"
    )


def _load_image_node(filename: str, title: str) -> dict[str, Any]:
    return {
        "class_type": "LoadImage",
        "inputs": {"image": filename},
        "_meta": {"title": title},
    }


def _load_video_node(filename: str) -> dict[str, Any]:
    return {
        "class_type": "LoadVideo",
        "inputs": {"file": filename},
        "_meta": {"title": "Bernini 源视频"},
    }


def _vhs_load_video_node(filename: str, frames: int, fps: int) -> dict[str, Any]:
    return {
        "class_type": "VHS_LoadVideo",
        "inputs": {
            "video": filename,
            "force_rate": fps,
            "custom_width": 0,
            "custom_height": 0,
            "frame_load_cap": frames,
            "skip_first_frames": 0,
            "select_every_nth": 1,
            "format": "Wan",
            "force_size": "Disabled",
        },
        "_meta": {"title": "Bernini 源视频"},
    }


def _image_batch_node(image1: list[Any], image2: list[Any], title: str) -> dict[str, Any]:
    return {
        "class_type": "ImageBatch",
        "inputs": {"image1": image1, "image2": image2},
        "_meta": {"title": title},
    }


def _batched_reference_image_link(workflow: dict[str, Any], refs: list[str]) -> list[Any]:
    image_links: list[list[Any]] = []
    for index, filename in enumerate(refs[:MAX_REFERENCE_IMAGES]):
        node_id = str(REF_IMAGE_NODE_START + index)
        workflow[node_id] = _load_image_node(filename, f"Bernini 参考图 {index + 1}")
        image_links.append([node_id, 0])

    if not image_links:
        raise RuntimeError("Bernini 当前模式需要至少 1 张参考图")
    if len(image_links) == 1:
        return image_links[0]

    current = image_links[0]
    for index, image_link in enumerate(image_links[1:], start=1):
        batch_id = str(IMAGE_BATCH_NODE_START + index)
        workflow[batch_id] = _image_batch_node(current, image_link, f"Bernini 参考图合批 {index}")
        current = [batch_id, 0]
    return current


def _full_save_node(mode: str, prefix: str) -> dict[str, Any]:
    if mode in IMAGE_MODES:
        return {
            "class_type": "SaveImage",
            "inputs": {"images": [FULL_NODE_ID, 0], "filename_prefix": prefix},
            "_meta": {"title": "Bernini Full 图片输出"},
        }
    return {
        "class_type": "SaveVideo",
        "inputs": {
            "video": [FULL_NODE_ID, 0],
            "filename_prefix": prefix,
            "format": "mp4",
            "codec": "h264",
        },
        "_meta": {"title": "Bernini Full 视频输出"},
    }


def _apply_bernini_full_mode_to_workflow(
    workflow: dict[str, Any],
    field_values: dict[str, Any] | None,
) -> dict[str, Any]:
    mode = bernini_mode(field_values)
    refs = bernini_reference_images(field_values)
    video_name = bernini_source_video(field_values)

    if mode in REFERENCE_IMAGE_MODES and not refs:
        raise RuntimeError("Bernini 当前模式需要至少 1 张参考图")
    if mode in SOURCE_VIDEO_MODES and not video_name:
        raise RuntimeError("Bernini 当前模式需要先上传源视频")

    width, height = _full_dimensions(field_values, mode)
    inputs = _full_prompt_inputs(field_values)
    inputs["width"] = width
    inputs["height"] = height
    if mode in VIDEO_MODES:
        inputs["num_frames"] = _full_frames(field_values, mode)
        inputs["fps"] = bernini_video_fps(field_values)

    workflow.clear()
    workflow[FULL_NODE_ID] = {
        "class_type": FULL_NODE_CLASS_BY_MODE[mode],
        "inputs": inputs,
        "_meta": {"title": f"Bernini Full {mode.upper()}"},
    }

    if mode == "i2i":
        workflow[str(REF_IMAGE_NODE_START)] = _load_image_node(refs[0], "Bernini 源图")
        workflow[FULL_NODE_ID]["inputs"]["image"] = [str(REF_IMAGE_NODE_START), 0]
    elif mode in {"i2v", "r2v", "rv2v"}:
        limit = 1 if mode == "i2v" else MAX_REFERENCE_IMAGES
        workflow[FULL_NODE_ID]["inputs"]["reference_image"] = _batched_reference_image_link(workflow, refs[:limit])

    if mode in SOURCE_VIDEO_MODES:
        workflow[VIDEO_LOADER_NODE_ID] = _load_video_node(video_name)
        workflow[FULL_NODE_ID]["inputs"]["video"] = [VIDEO_LOADER_NODE_ID, 0]

    workflow[SAVE_NODE_ID] = _full_save_node(mode, _output_prefix(field_values, mode))
    return workflow


def _legacy_conditioning_node(workflow: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    node = workflow.get(LEGACY_COND_NODE_ID)
    if isinstance(node, dict) and node.get("class_type") == BERNINI_CONDITIONING_CLASS:
        return LEGACY_COND_NODE_ID, node
    for node_id, candidate in workflow.items():
        if isinstance(candidate, dict) and candidate.get("class_type") == BERNINI_CONDITIONING_CLASS:
            return str(node_id), candidate
    raise RuntimeError("当前 Bernini 工作流缺少 BerniniConditioning 节点")


def _clean_legacy_conditioning_inputs(inputs: dict[str, Any]) -> None:
    for key in ("source_video", "reference_video", "reference_images"):
        inputs.pop(key, None)
    for key in VIRTUAL_INPUTS:
        inputs.pop(key, None)


def _ensure_legacy_save_image_node(workflow: dict[str, Any], prefix: str) -> None:
    workflow[LEGACY_SAVE_IMAGE_NODE_ID] = {
        "class_type": "SaveImage",
        "inputs": {"images": ["16", 0], "filename_prefix": prefix},
        "_meta": {"title": "Bernini 图片输出"},
    }


def _ensure_legacy_save_video_node(workflow: dict[str, Any], prefix: str, fps: int) -> None:
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


def _apply_legacy_bernini_mode_to_workflow(
    workflow: dict[str, Any],
    field_values: dict[str, Any] | None,
) -> dict[str, Any]:
    mode = bernini_mode(field_values)
    refs = bernini_reference_images(field_values)
    raw_frames = _field_value(field_values, FRAMES_FIELD, LEGACY_FRAMES_FIELD, "50::length", "__bernini_frames", default=81)
    frames = 1 if mode in IMAGE_MODES else _legal_video_frame_count(raw_frames)
    fps = bernini_video_fps(field_values)
    source_video = bernini_source_video(field_values)

    _cond_id, cond_node = _legacy_conditioning_node(workflow)
    cond_inputs = cond_node.setdefault("inputs", {})
    _clean_legacy_conditioning_inputs(cond_inputs)
    cond_inputs["length"] = frames

    workflow.pop(LEGACY_SOURCE_IMAGE_NODE_ID, None)
    for index in range(MAX_REFERENCE_IMAGES):
        workflow.pop(str(LEGACY_REF_IMAGE_NODE_START + index), None)
    workflow.pop(VIDEO_LOADER_NODE_ID, None)

    if mode in REFERENCE_IMAGE_MODES and not refs:
        raise RuntimeError("Bernini 当前模式需要至少 1 张参考图")
    if mode in SOURCE_VIDEO_MODES and not source_video:
        raise RuntimeError("Bernini 当前模式需要先上传源视频")

    if mode in IMAGE_MODES:
        workflow.pop(SAVE_VIDEO_NODE_ID, None)
        _ensure_legacy_save_image_node(workflow, f"bernini_q4/Bernini_{mode}")
    else:
        workflow.pop(LEGACY_SAVE_IMAGE_NODE_ID, None)
        _ensure_legacy_save_video_node(workflow, f"bernini_q4/Bernini_{mode}", fps)

    if mode == "i2i":
        workflow[LEGACY_SOURCE_IMAGE_NODE_ID] = _load_image_node(refs[0], "Bernini 源图")
        cond_inputs["source_video"] = [LEGACY_SOURCE_IMAGE_NODE_ID, 0]
    if mode in SOURCE_VIDEO_MODES:
        workflow[VIDEO_LOADER_NODE_ID] = _vhs_load_video_node(source_video, frames, fps)
        cond_inputs["source_video"] = [VIDEO_LOADER_NODE_ID, 0]
    if mode in {"i2v", "r2v", "rv2v"}:
        ref_links: dict[str, list[Any]] = {}
        limit = 1 if mode == "i2v" else MAX_REFERENCE_IMAGES
        for index, filename in enumerate(refs[:limit]):
            node_id = str(LEGACY_REF_IMAGE_NODE_START + index)
            workflow[node_id] = _load_image_node(filename, f"Bernini 参考图 {index + 1}")
            ref_links[f"reference_image_{index}"] = [node_id, 0]
        cond_inputs["reference_images"] = ref_links

    return workflow


def apply_bernini_mixed_mode_to_workflow(
    workflow: dict[str, Any],
    field_values: dict[str, Any] | None,
    workflow_name: str = "",
) -> dict[str, Any]:
    if not is_bernini_workflow(workflow, workflow_name):
        return workflow
    if _uses_full_workflow(workflow, workflow_name):
        return _apply_bernini_full_mode_to_workflow(workflow, field_values)
    return _apply_legacy_bernini_mode_to_workflow(workflow, field_values)
