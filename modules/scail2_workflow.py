"""SCAIL-2 workflow graph helpers."""

from __future__ import annotations

import os
from typing import Any


SCAIL2_AUDIO_MUX_WORKFLOWS = {"i2v_scail2_vantage_gguf_q4_audio_mux.json"}
SCAIL2_AUDIO_TOGGLE_FIELD = "42::value"
SCAIL2_MODEL_FIELD = "6::__scail2_model_variant"
SCAIL2_LEGACY_MODEL_FIELD = "6::unet_name"
SCAIL2_FP16_MODEL = "wan2.1_14B_SCAIL_2_fp16.safetensors"
SCAIL2_FP8_MODEL = "wan2.1_14B_SCAIL_2_fp8_scaled.safetensors"
SCAIL2_GGUF_MODEL = "gguf/wan2.1_14B_SCAIL_2-Q4_K_M.gguf"
SCAIL2_MXFP8_MODEL = "wan2.1_14B_SCAIL_2_mxfp8.safetensors"
SCAIL2_NVFP4_MODEL = "wan2.1_14B_SCAIL_2_nvfp4_comfy_V2.safetensors"
SCAIL2_MODEL_VARIANTS = {
    "FP16": {
        "class_type": "UNETLoader",
        "unet_name": SCAIL2_FP16_MODEL,
        "title": "Load SCAIL-2 FP16",
    },
    "FP8": {
        "class_type": "UNETLoader",
        "unet_name": SCAIL2_FP8_MODEL,
        "title": "Load SCAIL-2 FP8",
    },
    "Q4 GGUF": {
        "class_type": "UnetLoaderGGUF",
        "unet_name": SCAIL2_GGUF_MODEL,
        "title": "Load SCAIL-2 Q4 GGUF",
    },
    "MXFP8": {
        "class_type": "UNETLoader",
        "unet_name": SCAIL2_MXFP8_MODEL,
        "title": "Load SCAIL-2 MXFP8",
    },
    "NVFP4": {
        "class_type": "UNETLoader",
        "unet_name": SCAIL2_NVFP4_MODEL,
        "title": "Load SCAIL-2 NVFP4",
    },
}
SCAIL2_MODEL_ALIASES = {
    variant: variant for variant in SCAIL2_MODEL_VARIANTS
}
SCAIL2_MODEL_ALIASES.update(
    {
        SCAIL2_FP16_MODEL: "FP16",
        SCAIL2_FP8_MODEL: "FP8",
        SCAIL2_GGUF_MODEL: "Q4 GGUF",
        SCAIL2_MXFP8_MODEL: "MXFP8",
        SCAIL2_NVFP4_MODEL: "NVFP4",
    }
)


def _bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on", "y"}:
            return True
        if text in {"0", "false", "no", "off", "n"}:
            return False
    return default


def _first_node_id(workflow: dict[str, Any], class_type: str) -> str:
    for node_id, node in workflow.items():
        if isinstance(node, dict) and node.get("class_type") == class_type:
            return str(node_id)
    return ""


def is_scail2_audio_mux_workflow(workflow: dict[str, Any], workflow_name: str = "") -> bool:
    basename = os.path.basename(str(workflow_name or ""))
    if basename in SCAIL2_AUDIO_MUX_WORKFLOWS:
        return True
    return (
        isinstance(workflow.get("42"), dict)
        and workflow.get("42", {}).get("class_type") == "PrimitiveBoolean"
        and isinstance(workflow.get("40"), dict)
        and workflow.get("40", {}).get("class_type") == "CreateVideo"
        and any(
            isinstance(node, dict) and node.get("class_type") == "WanSCAILToVideo"
            for node in workflow.values()
        )
    )


def apply_scail2_model_variant_to_workflow(
    workflow: dict[str, Any],
    field_values: dict[str, Any] | None = None,
) -> None:
    """Switch SCAIL-2's base-model loader between GGUF and safetensors variants."""
    if not isinstance(workflow, dict):
        return
    node = workflow.get("6")
    if not isinstance(node, dict):
        return
    values = field_values or {}
    inputs = node.setdefault("inputs", {})
    if not isinstance(inputs, dict):
        return
    selected = str(
        values.get(SCAIL2_MODEL_FIELD)
        or values.get(SCAIL2_LEGACY_MODEL_FIELD)
        or inputs.get("unet_name")
        or ""
    ).strip()
    if not selected:
        return
    variant_name = SCAIL2_MODEL_ALIASES.get(selected)
    if not variant_name:
        return
    variant = SCAIL2_MODEL_VARIANTS[variant_name]
    class_type = str(variant["class_type"])
    unet_name = str(variant["unet_name"])

    if class_type == "UnetLoaderGGUF":
        node["class_type"] = class_type
        node["inputs"] = {"unet_name": unet_name}
    else:
        node["class_type"] = class_type
        node["inputs"] = {
            "unet_name": unet_name,
            "weight_dtype": "default",
        }
        values["6::weight_dtype"] = "default"
    values[SCAIL2_LEGACY_MODEL_FIELD] = unet_name
    meta = node.setdefault("_meta", {})
    if isinstance(meta, dict):
        meta["title"] = str(variant["title"])


def apply_scail2_audio_mux_to_workflow(
    workflow: dict[str, Any],
    field_values: dict[str, Any] | None = None,
    workflow_name: str = "",
) -> None:
    """Use one final CreateVideo node, optionally with the driving video's audio.

    The quick panel exposes a simple toggle, but the prompt sent to ComfyUI
    should not include parallel video-encoding branches. This helper rewires
    the save node to a single CreateVideo and attaches/removes the audio input
    according to the toggle.
    """
    if not isinstance(workflow, dict) or not is_scail2_audio_mux_workflow(workflow, workflow_name):
        return

    values = field_values or {}
    toggle_default = _bool_value(
        ((workflow.get("42") or {}).get("inputs") or {}).get("value"),
        default=True,
    )
    use_audio = _bool_value(values.get(SCAIL2_AUDIO_TOGGLE_FIELD), default=toggle_default)

    create_id = "40" if (workflow.get("40") or {}).get("class_type") == "CreateVideo" else _first_node_id(workflow, "CreateVideo")
    loader_id = "1" if (workflow.get("1") or {}).get("class_type") == "VHS_LoadVideo" else _first_node_id(workflow, "VHS_LoadVideo")
    if not create_id:
        return

    create_inputs = workflow[create_id].setdefault("inputs", {})
    if not isinstance(create_inputs, dict):
        return

    if use_audio and loader_id:
        create_inputs["audio"] = [loader_id, 2]
    else:
        create_inputs.pop("audio", None)

    for node in workflow.values():
        if not isinstance(node, dict) or node.get("class_type") != "SaveVideo":
            continue
        inputs = node.setdefault("inputs", {})
        if isinstance(inputs, dict) and "video" in inputs:
            inputs["video"] = [create_id, 0]

    for unused_id in ("43", "44"):
        workflow.pop(unused_id, None)
