"""Helpers for syncing local input media to remote ComfyUI instances."""

from __future__ import annotations

import json
import math
import mimetypes
import os
import ssl
import uuid
import urllib.request
import urllib.error
from typing import Any


def workflow_load_images(workflow: dict[str, Any]) -> list[str]:
    """Return unique input media filenames referenced by a workflow."""
    media: list[str] = []
    seen: set[str] = set()

    def add_media(value: Any) -> None:
        if not isinstance(value, str) or not value.strip():
            return
        name = value.strip()
        if name not in seen:
            seen.add(name)
            media.append(name)

    def add_director_timeline(value: Any) -> None:
        if not isinstance(value, str) or not value.strip():
            return
        try:
            data = json.loads(value)
        except Exception:
            return
        if not isinstance(data, dict):
            return
        for segment in data.get("segments", []) or []:
            if isinstance(segment, dict):
                add_media(segment.get("imageFile"))
        for segment in data.get("audioSegments", []) or []:
            if isinstance(segment, dict):
                add_media(segment.get("audioFile"))

    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type")
        inputs = node.get("inputs", {})
        input_name = (
            "image" if class_type == "LoadImage"
            else "file" if class_type == "LoadVideo"
            else "video" if class_type == "VHS_LoadVideo"
            else "audio" if class_type == "LoadAudio"
            else ""
        )
        if input_name:
            add_media(inputs.get(input_name))
        if class_type == "LTXDirector":
            add_director_timeline(inputs.get("timeline_data"))
    return media


def _local_input_path(input_dir: str, image_name: str) -> str:
    normalized = image_name.replace("\\", "/").lstrip("/")
    candidate = os.path.abspath(os.path.join(input_dir, normalized))
    input_root = os.path.abspath(input_dir)
    if os.path.commonpath([input_root, candidate]) != input_root:
        raise RuntimeError(f"非法参考图片路径: {image_name}")
    return candidate


def _local_reference_path(input_dir: str, image_name: str) -> str:
    input_path = _local_input_path(input_dir, image_name)
    if os.path.isfile(input_path):
        return input_path

    normalized = image_name.replace("\\", "/").lstrip("/")
    data_root = os.path.dirname(os.path.abspath(input_dir))
    output_root = os.path.abspath(os.path.join(data_root, "outputs"))
    output_path = os.path.abspath(os.path.join(output_root, normalized))
    if os.path.commonpath([output_root, output_path]) != output_root:
        raise RuntimeError(f"非法参考图片路径: {image_name}")
    return output_path


def _qwen_frame_roll_degrees(field_values: dict[str, Any] | None) -> float:
    if not isinstance(field_values, dict):
        return 0.0
    try:
        value = float(field_values.get("__qwen_frame_roll") or 0)
    except (TypeError, ValueError):
        return 0.0
    if abs(value) < 0.5:
        return 0.0
    return max(-45.0, min(45.0, value))


def _workflow_has_qwen_multiangle(workflow: dict[str, Any]) -> bool:
    return any(
        isinstance(node, dict) and node.get("class_type") == "QwenMultiangleCameraNode"
        for node in workflow.values()
    )


def _rolled_image_name(image_name: str, degrees: float, max_size: int = 0) -> str:
    normalized = image_name.replace("\\", "/").lstrip("/")
    folder = os.path.dirname(normalized)
    stem = os.path.splitext(os.path.basename(normalized))[0] or "image"
    safe_stem = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stem)[:80]
    sign = "p" if degrees >= 0 else "m"
    token = f"{sign}{abs(int(round(degrees * 10))):03d}"
    size_token = f"_m{int(max_size)}" if max_size else ""
    filename = f"{safe_stem}_qwen_context_cover_roll_{token}{size_token}.png"
    return f"{folder}/{filename}" if folder else filename


def _resize_to_max_dimension(img, max_size: int):
    from PIL import Image

    max_size = int(max_size or 0)
    width, height = img.size
    if max_size <= 0 or max(width, height) <= max_size:
        return img
    scale = max_size / max(width, height)
    size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    return img.resize(size, Image.Resampling.LANCZOS)


def _qwen_roll_geometry(width: int, height: int, degrees: float) -> dict[str, float | int]:
    angle = abs(math.radians(degrees))
    cos_a = abs(math.cos(angle))
    sin_a = abs(math.sin(angle))
    rotated_w = width * cos_a + height * sin_a
    rotated_h = width * sin_a + height * cos_a
    content_scale = min(1.0, width / rotated_w if rotated_w else 1.0, height / rotated_h if rotated_h else 1.0)
    content_scale = max(0.2, content_scale * 0.995)
    overscan = 1.025
    work_w = max(width, int(math.ceil(rotated_w * overscan)))
    work_h = max(height, int(math.ceil(rotated_h * overscan)))
    expanded_w = max(width, int(math.ceil(work_w / content_scale)))
    expanded_h = max(height, int(math.ceil(work_h / content_scale)))
    if expanded_w % 2 != width % 2:
        expanded_w += 1
    if expanded_h % 2 != height % 2:
        expanded_h += 1
    return {
        "content_scale": content_scale,
        "work_w": work_w,
        "work_h": work_h,
        "expanded_w": expanded_w,
        "expanded_h": expanded_h,
    }


def _paste_resized_patch(canvas, patch, box: tuple[int, int, int, int]) -> None:
    from PIL import Image

    left, top, right, bottom = box
    width = max(0, right - left)
    height = max(0, bottom - top)
    if width <= 0 or height <= 0:
        return
    canvas.paste(patch.resize((width, height), Image.Resampling.BICUBIC), (left, top))


def _context_cover_background(source, expanded_w: int, expanded_h: int):
    from PIL import Image, ImageFilter

    width, height = source.size
    scale = max(expanded_w / width if width else 1.0, expanded_h / height if height else 1.0)
    cover_size = (max(1, int(math.ceil(width * scale))), max(1, int(math.ceil(height * scale))))
    cover = source.resize(cover_size, Image.Resampling.LANCZOS)
    left = max(0, (cover.width - expanded_w) // 2)
    top = max(0, (cover.height - expanded_h) // 2)
    cover = cover.crop((left, top, left + expanded_w, top + expanded_h))
    blur_radius = max(12, min(expanded_w, expanded_h) // 18)
    return cover.filter(ImageFilter.GaussianBlur(radius=blur_radius))


def _edge_stretch_background(source, expanded_w: int, expanded_h: int, pad_x: int, pad_y: int):
    from PIL import Image, ImageFilter

    width, height = source.size
    canvas = Image.new("RGB", (expanded_w, expanded_h))
    strip_x = max(1, min(width, max(8, width // 8)))
    strip_y = max(1, min(height, max(8, height // 8)))
    if pad_x:
        left = source.crop((0, 0, strip_x, height))
        right = source.crop((width - strip_x, 0, width, height))
        _paste_resized_patch(canvas, left, (0, pad_y, pad_x, pad_y + height))
        _paste_resized_patch(canvas, right, (pad_x + width, pad_y, expanded_w, pad_y + height))
    if pad_y:
        top = source.crop((0, 0, width, strip_y))
        bottom = source.crop((0, height - strip_y, width, height))
        _paste_resized_patch(canvas, top, (pad_x, 0, pad_x + width, pad_y))
        _paste_resized_patch(canvas, bottom, (pad_x, pad_y + height, pad_x + width, expanded_h))
    if pad_x and pad_y:
        corners = [
            (source.crop((0, 0, strip_x, strip_y)), (0, 0, pad_x, pad_y)),
            (source.crop((width - strip_x, 0, width, strip_y)), (pad_x + width, 0, expanded_w, pad_y)),
            (source.crop((0, height - strip_y, strip_x, height)), (0, pad_y + height, pad_x, expanded_h)),
            (
                source.crop((width - strip_x, height - strip_y, width, height)),
                (pad_x + width, pad_y + height, expanded_w, expanded_h),
            ),
        ]
        for patch, box in corners:
            _paste_resized_patch(canvas, patch, box)
    canvas.paste(source, (pad_x, pad_y))
    return canvas.filter(ImageFilter.GaussianBlur(radius=max(4, min(expanded_w, expanded_h) // 96)))


def _expand_image_for_roll(img, expanded_w: int, expanded_h: int):
    from PIL import Image, ImageDraw, ImageFilter

    source = img.convert("RGB")
    width, height = source.size
    expanded_w = max(width, int(expanded_w or width))
    expanded_h = max(height, int(expanded_h or height))
    pad_x = max(0, (expanded_w - width) // 2)
    pad_y = max(0, (expanded_h - height) // 2)

    cover = _context_cover_background(source, expanded_w, expanded_h)
    stretched = _edge_stretch_background(source, expanded_w, expanded_h, pad_x, pad_y)
    canvas = Image.blend(cover, stretched, 0.45)

    mask = Image.new("L", (expanded_w, expanded_h), 0)
    ImageDraw.Draw(mask).rectangle((pad_x, pad_y, pad_x + width - 1, pad_y + height - 1), fill=255)
    feather = max(6, min(width, height, max(pad_x, pad_y)) // 16)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=feather))
    canvas.paste(source, (pad_x, pad_y), mask.crop((pad_x, pad_y, pad_x + width, pad_y + height)))
    return canvas


def _frame_roll_image(img, degrees: float, mode: str = "contain", max_size: int = 0):
    from PIL import Image

    img = _resize_to_max_dimension(img, max_size)
    width, height = img.size
    if img.mode != "RGB":
        img = img.convert("RGB")
    angle = abs(math.radians(degrees))
    if width > 0 and height > 0 and angle > 0:
        geo = _qwen_roll_geometry(width, height, degrees)
        expanded = _expand_image_for_roll(img, int(geo["expanded_w"]), int(geo["expanded_h"]))
        work = expanded.resize((int(geo["work_w"]), int(geo["work_h"])), Image.Resampling.LANCZOS)
        rotated = work.rotate(-degrees, resample=Image.Resampling.BICUBIC, expand=False)
        left = max(0, (rotated.width - width) // 2)
        top = max(0, (rotated.height - height) // 2)
        return rotated.crop((left, top, left + width, top + height))
    rotated = img.rotate(-degrees, resample=Image.Resampling.BICUBIC, expand=False)
    left = max(0, (rotated.width - width) // 2)
    top = max(0, (rotated.height - height) // 2)
    return rotated.crop((left, top, left + width, top + height))


def _save_rolled_input_image(input_dir: str, image_name: str, degrees: float, max_size: int = 0) -> str:
    from PIL import Image, ImageOps

    source_path = _local_reference_path(input_dir, image_name)
    if not os.path.isfile(source_path):
        raise RuntimeError(f"参考图片不存在，无法应用构图倾斜: {image_name}")

    rolled_name = _rolled_image_name(image_name, degrees, max_size)
    dest_path = _local_input_path(input_dir, rolled_name)
    if os.path.isfile(dest_path):
        return rolled_name

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with Image.open(source_path) as img:
        img = ImageOps.exif_transpose(img)
        rotated = _frame_roll_image(img, degrees, mode="contain", max_size=max_size)
        rotated.save(dest_path, "PNG")
    return rolled_name


def _load_image_max_size(workflow: dict[str, Any], field_values: dict[str, Any] | None, load_node_id: str) -> int:
    for node_id, node in list(workflow.items()):
        if not isinstance(node, dict) or node.get("class_type") != "ImageScaleToMaxDimension":
            continue
        inputs = node.get("inputs") or {}
        if inputs.get("image") != [load_node_id, 0]:
            continue
        raw = (field_values or {}).get(f"{node_id}::largest_size", inputs.get("largest_size", 0))
        try:
            return max(0, int(float(raw or 0)))
        except (TypeError, ValueError):
            return 0
    return 0


def apply_qwen_frame_roll_to_workflow(
    workflow: dict[str, Any],
    field_values: dict[str, Any] | None,
    input_dir: str,
) -> list[dict[str, str]]:
    """Keep Qwen roll prompt-only.

    The UI now expresses Z-roll as diagonal composition text. Do not rotate,
    expand, mask, or replace LoadImage inputs here; otherwise the model sees a
    physically tilted reference instead of being asked to change composition.
    """
    return []


def upload_image_to_comfyui(base_url: str, image_path: str, image_name: str) -> dict:
    """Upload one input media file to ComfyUI's input folder via /upload/image."""
    boundary = f"----ez-comfyui-{uuid.uuid4().hex}"
    mime = mimetypes.guess_type(image_name)[0] or "application/octet-stream"
    with open(image_path, "rb") as fh:
        content = fh.read()

    parts: list[bytes] = []

    def add_field(name: str, value: str) -> None:
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(str(value).encode())
        parts.append(b"\r\n")

    add_field("type", "input")
    add_field("overwrite", "true")
    subfolder = os.path.dirname(image_name.replace("\\", "/")).strip("/")
    if subfolder:
        add_field("subfolder", subfolder)
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        (
            f'Content-Disposition: form-data; name="image"; filename="{os.path.basename(image_name)}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode()
    )
    parts.append(content)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())

    req = urllib.request.Request(
        base_url.rstrip("/") + "/upload/image",
        data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with _urlopen_upload(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"HTTP {e.code}: {body[:300] or e.reason}") from e
    except Exception as e:
        raise RuntimeError(str(e)) from e


def _urlopen_upload(req: urllib.request.Request, timeout: int = 60):
    if str(req.full_url).lower().startswith("https://"):
        return urllib.request.urlopen(req, timeout=timeout, context=ssl._create_unverified_context())
    return urllib.request.urlopen(req, timeout=timeout)


def ensure_workflow_images_available(workflow: dict[str, Any], input_dir: str, base_url: str) -> None:
    """Upload local LoadImage/LoadVideo files to the selected remote ComfyUI instance."""
    for image_name in workflow_load_images(workflow):
        image_path = _local_reference_path(input_dir, image_name)
        if not os.path.isfile(image_path):
            continue
        try:
            upload_image_to_comfyui(base_url, image_path, image_name)
        except Exception as e:
            raise RuntimeError(f"参考媒体同步到 ComfyUI 失败: {image_name}: {e}") from e
