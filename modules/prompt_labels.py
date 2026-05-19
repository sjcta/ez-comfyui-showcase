"""Helpers for generation card/history display labels."""

from __future__ import annotations

import os
from typing import Any


def text_prompt_from_fields(field_values: dict[str, Any] | None) -> str:
    """Return the first prompt/text field from submitted workflow values."""
    for key, value in (field_values or {}).items():
        field = str(key).split("::")[-1].lower()
        if "text" in field or "prompt" in field:
            content = str(value or "").strip()
            if content:
                return content
    return ""


def upscale_resolution_from_fields(field_values: dict[str, Any] | None) -> int:
    """Extract an upscale resolution hint from workflow field values."""
    for key, value in (field_values or {}).items():
        field = str(key).split("::")[-1].lower()
        if field not in ("resolution", "max_resolution"):
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue
    return 0


def upscale_label(resolution: int) -> str:
    """Build a short Chinese label for upscale outputs."""
    if resolution >= 3840:
        return "4K 放大"
    if resolution >= 1920:
        return "2K 放大"
    if resolution > 0:
        return f"{resolution}P 放大"
    return "放大"


def infer_generation_label(
    workflow: str,
    field_values: dict[str, Any] | None,
    workflow_type: str = "",
) -> str:
    """Return a stable card/history label for a submitted generation."""
    prompt = text_prompt_from_fields(field_values)
    if prompt:
        return prompt

    wf_name = os.path.basename(workflow or "").lower()
    is_upscale = workflow_type == "放大" or "upscale" in wf_name or "seedvr" in wf_name
    if is_upscale:
        return upscale_label(upscale_resolution_from_fields(field_values))

    return ""
