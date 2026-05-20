"""Helpers for syncing local input images to remote ComfyUI instances."""

from __future__ import annotations

import json
import mimetypes
import os
import uuid
import urllib.request
import urllib.error
from typing import Any


def workflow_load_images(workflow: dict[str, Any]) -> list[str]:
    """Return unique LoadImage filenames referenced by a workflow."""
    images: list[str] = []
    seen: set[str] = set()
    for node in workflow.values():
        if not isinstance(node, dict) or node.get("class_type") != "LoadImage":
            continue
        image = node.get("inputs", {}).get("image")
        if not isinstance(image, str) or not image.strip():
            continue
        name = image.strip()
        if name not in seen:
            seen.add(name)
            images.append(name)
    return images


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


def upload_image_to_comfyui(base_url: str, image_path: str, image_name: str) -> dict:
    """Upload one image to ComfyUI's input folder via /upload/image."""
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
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"HTTP {e.code}: {body[:300] or e.reason}") from e
    except Exception as e:
        raise RuntimeError(str(e)) from e


def ensure_workflow_images_available(workflow: dict[str, Any], input_dir: str, base_url: str) -> None:
    """Upload local LoadImage files to the selected remote ComfyUI instance."""
    for image_name in workflow_load_images(workflow):
        image_path = _local_reference_path(input_dir, image_name)
        if not os.path.isfile(image_path):
            continue
        try:
            upload_image_to_comfyui(base_url, image_path, image_name)
        except Exception as e:
            raise RuntimeError(f"参考图片同步到 ComfyUI 失败: {image_name}: {e}") from e
