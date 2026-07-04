"""Mutators for still-image workflows that support multiple reference images."""

from __future__ import annotations

import json
import os
from typing import Any


IMAGE_REFERENCE_MODE_FIELD = "__image_reference_mode"
MULTI_REFERENCE_IMAGES_FIELD = "__multi_reference_images"
MAX_MULTI_REFERENCE_IMAGES = 3

QWEN_EDIT_PLUS_WORKFLOWS = {
    "i2i-Qwen-Edit-v2511.json",
    "i2i-FireRed-Edit-8step.json",
}

QWEN_RAPID_MULTI_REFERENCE_WORKFLOWS = {
    "i2i-Qwen-Rapid.json",
    "i2i-Qwen-Rapid-Q2.json",
    "i2i-Qwen-Rapid-seedVR2-4k.json",
}

FLUX2_MULTI_REFERENCE_WORKFLOWS = {
    "i2i_flux2_dev_turbo_q4km.json",
}

MULTI_REFERENCE_IMAGE_WORKFLOWS = (
    QWEN_EDIT_PLUS_WORKFLOWS
    | QWEN_RAPID_MULTI_REFERENCE_WORKFLOWS
    | FLUX2_MULTI_REFERENCE_WORKFLOWS
)


def _base_name(workflow_name: str | os.PathLike[str] | None) -> str:
    return os.path.basename(str(workflow_name or ""))


def _field_value(field_values: dict[str, Any] | None, field_name: str, default: Any = "") -> Any:
    values = field_values or {}
    if field_name in values:
        return values.get(field_name, default)
    suffix = "::" + field_name
    for key, value in values.items():
        if str(key).endswith(suffix):
            return value
    return default


def _parse_reference_images(value: Any) -> list[str]:
    if value is None:
        return []
    raw = value
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            raw = parsed
        except Exception:
            raw = text.split(",")
    if not isinstance(raw, (list, tuple)):
        return []
    refs: list[str] = []
    for item in raw:
        ref = str(item or "").strip()
        if ref and ref not in refs:
            refs.append(ref)
    return refs[:MAX_MULTI_REFERENCE_IMAGES]


def _reference_mode(field_values: dict[str, Any] | None, refs: list[str]) -> str:
    raw = str(_field_value(field_values, IMAGE_REFERENCE_MODE_FIELD, "") or "").strip().lower()
    if raw in {"multi", "multiple", "multi_image", "multi-reference", "多图"}:
        return "multi"
    if raw in {"single", "single_image", "单图"}:
        return "single"
    return "multi" if len(refs) >= 2 else "single"


def _load_image_node_ids(workflow: dict[str, Any]) -> list[str]:
    return [
        str(node_id)
        for node_id, node in (workflow or {}).items()
        if isinstance(node, dict) and str(node.get("class_type") or "") == "LoadImage"
    ]


def _set_primary_reference_image(workflow: dict[str, Any], field_values: dict[str, Any], image_name: str) -> str:
    load_ids = _load_image_node_ids(workflow)
    if not load_ids:
        return ""
    primary_id = load_ids[0]
    workflow[primary_id].setdefault("inputs", {})["image"] = image_name
    field_values[f"{primary_id}::image"] = image_name
    return primary_id


def _ensure_node(workflow: dict[str, Any], node_id: str, class_type: str, inputs: dict[str, Any], title: str) -> None:
    node = workflow.get(node_id)
    if not isinstance(node, dict) or str(node.get("class_type") or "") != class_type:
        workflow[node_id] = {
            "class_type": class_type,
            "inputs": dict(inputs),
            "_meta": {"title": title},
        }
        return
    node.setdefault("inputs", {}).update(inputs)
    node.setdefault("_meta", {}).setdefault("title", title)


def _apply_qwen_edit_plus_references(
    workflow: dict[str, Any],
    field_values: dict[str, Any],
    refs: list[str],
    mode: str,
) -> None:
    for node in (workflow or {}).values():
        if not isinstance(node, dict) or str(node.get("class_type") or "") != "TextEncodeQwenImageEditPlus":
            continue
        inputs = node.setdefault("inputs", {})
        for field in ("image2", "image3"):
            inputs.pop(field, None)

    if mode != "multi":
        return
    if len(refs) < 2:
        raise ValueError("多图模式至少需要 2 张参考图")

    for idx, image_name in enumerate(refs[1:MAX_MULTI_REFERENCE_IMAGES], start=2):
        load_id = str(920 + idx)
        scale_id = str(930 + idx)
        _ensure_node(
            workflow,
            load_id,
            "LoadImage",
            {"image": image_name},
            f"Multi Reference Image {idx}",
        )
        _ensure_node(
            workflow,
            scale_id,
            "FluxKontextImageScale",
            {"image": [load_id, 0]},
            f"Scale Multi Reference {idx}",
        )
        field_values[f"{load_id}::image"] = image_name

        image_field = f"image{idx}"
        for node in workflow.values():
            if not isinstance(node, dict) or str(node.get("class_type") or "") != "TextEncodeQwenImageEditPlus":
                continue
            inputs = node.setdefault("inputs", {})
            if "image1" not in inputs:
                continue
            inputs[image_field] = [scale_id, 0]


def _apply_qwen_rapid_references(
    workflow: dict[str, Any],
    field_values: dict[str, Any],
    refs: list[str],
    mode: str,
) -> None:
    for node in (workflow or {}).values():
        if not isinstance(node, dict) or str(node.get("class_type") or "") != "TextEncodeQwenImageEditPlus":
            continue
        inputs = node.setdefault("inputs", {})
        for field in ("image2", "image3"):
            inputs.pop(field, None)

    if mode != "multi":
        return
    if len(refs) < 2:
        raise ValueError("多图模式至少需要 2 张参考图")

    for idx, image_name in enumerate(refs[1:MAX_MULTI_REFERENCE_IMAGES], start=2):
        load_id = str(920 + idx)
        _ensure_node(
            workflow,
            load_id,
            "LoadImage",
            {"image": image_name},
            f"Rapid Multi Reference Image {idx}",
        )
        field_values[f"{load_id}::image"] = image_name

        image_field = f"image{idx}"
        for node in workflow.values():
            if not isinstance(node, dict) or str(node.get("class_type") or "") != "TextEncodeQwenImageEditPlus":
                continue
            inputs = node.setdefault("inputs", {})
            if "image1" not in inputs:
                continue
            inputs[image_field] = [load_id, 0]


def _find_first_node_by_class(workflow: dict[str, Any], class_type: str) -> str:
    for node_id, node in (workflow or {}).items():
        if isinstance(node, dict) and str(node.get("class_type") or "") == class_type:
            return str(node_id)
    return ""


def _apply_flux2_multi_references(
    workflow: dict[str, Any],
    field_values: dict[str, Any],
    refs: list[str],
    mode: str,
) -> None:
    guider_id = _find_first_node_by_class(workflow, "BasicGuider")
    vae_id = _find_first_node_by_class(workflow, "VAELoader")
    base_ref_id = _find_first_node_by_class(workflow, "ReferenceLatent")
    if not guider_id or not base_ref_id:
        return

    workflow[guider_id].setdefault("inputs", {})["conditioning"] = [base_ref_id, 0]
    if mode != "multi":
        return
    if len(refs) < 2:
        raise ValueError("多图模式至少需要 2 张参考图")

    tail_id = base_ref_id
    for idx, image_name in enumerate(refs[1:MAX_MULTI_REFERENCE_IMAGES], start=2):
        base = 140 + (idx - 2) * 5
        load_id = str(base)
        scale_id = str(base + 1)
        vae_encode_id = str(base + 2)
        reference_id = str(base + 3)
        _ensure_node(
            workflow,
            load_id,
            "LoadImage",
            {"image": image_name},
            f"Multi Reference Image {idx}",
        )
        _ensure_node(
            workflow,
            scale_id,
            "ImageScaleToTotalPixels",
            {
                "image": [load_id, 0],
                "upscale_method": "lanczos",
                "megapixels": 1.0,
                "resolution_steps": 1,
            },
            f"Scale Multi Reference {idx}",
        )
        _ensure_node(
            workflow,
            vae_encode_id,
            "VAEEncode",
            {"pixels": [scale_id, 0], "vae": [vae_id, 0] if vae_id else None},
            f"Encode Multi Reference {idx}",
        )
        if not vae_id:
            workflow[vae_encode_id].setdefault("inputs", {}).pop("vae", None)
        _ensure_node(
            workflow,
            reference_id,
            "ReferenceLatent",
            {"conditioning": [tail_id, 0], "latent": [vae_encode_id, 0]},
            f"Apply Multi Reference {idx}",
        )
        field_values[f"{load_id}::image"] = image_name
        tail_id = reference_id

    workflow[guider_id].setdefault("inputs", {})["conditioning"] = [tail_id, 0]


def apply_multi_reference_image_mode_to_workflow(
    workflow: dict[str, Any],
    field_values: dict[str, Any],
    workflow_name: str | os.PathLike[str] | None,
) -> None:
    """Apply single/multi reference image wiring for supported image-edit workflows."""
    base = _base_name(workflow_name)
    if base not in MULTI_REFERENCE_IMAGE_WORKFLOWS:
        return
    if not isinstance(workflow, dict) or not isinstance(field_values, dict):
        return

    refs = _parse_reference_images(_field_value(field_values, MULTI_REFERENCE_IMAGES_FIELD, ""))
    mode = _reference_mode(field_values, refs)
    field_values[IMAGE_REFERENCE_MODE_FIELD] = mode
    field_values[MULTI_REFERENCE_IMAGES_FIELD] = json.dumps(refs, ensure_ascii=False)
    if refs:
        _set_primary_reference_image(workflow, field_values, refs[0])

    if base in QWEN_EDIT_PLUS_WORKFLOWS:
        _apply_qwen_edit_plus_references(workflow, field_values, refs, mode)
    elif base in QWEN_RAPID_MULTI_REFERENCE_WORKFLOWS:
        _apply_qwen_rapid_references(workflow, field_values, refs, mode)
    elif base in FLUX2_MULTI_REFERENCE_WORKFLOWS:
        _apply_flux2_multi_references(workflow, field_values, refs, mode)
