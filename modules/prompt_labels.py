"""Helpers for generation card/history display labels."""

from __future__ import annotations

import os
import json
import re
from typing import Any


STYLE_PRESET_LABELS = {
    "hyperrealistic": "超写实",
    "realistic_photo": "写实摄影",
    "influencer_glam": "网红",
    "beauty_portrait": "美颜",
    "cinematic": "电影感",
    "game_concept": "游戏",
    "film_noir": "黑色电影",
    "vintage_film": "胶片复古",
    "cyberpunk_neon": "赛博霓虹",
    "aaa_game_asset": "AAA游戏资产",
    "low_poly_game": "低多边形游戏",
    "pixel_game": "像素游戏",
    "isometric_game": "等距游戏场景",
    "card_game_illustration": "卡牌游戏立绘",
    "anime": "动漫",
    "premium_3d": "3D",
    "guochao_illustration": "国潮",
    "commercial_product": "商业产品",
}

STYLE_PROMPT_RE = re.compile(
    r"^\s*\[Style Preset:\s*(?P<label>[^/\]\n\r]+?)"
    r"(?:\s*/[^\]\n\r]+)?\]\s*[\s\S]*?"
    r"\[\s*User Prompt\s*\]\s*",
    re.IGNORECASE,
)


def _style_label_from_fields(values: dict[str, Any], prompt: str = "") -> str:
    preset_id = str(values.get("__style_preset_id") or "").strip()
    if preset_id and preset_id in STYLE_PRESET_LABELS:
        return STYLE_PRESET_LABELS[preset_id]

    match = STYLE_PROMPT_RE.match(str(prompt or ""))
    if match:
        return match.group("label").strip()
    return ""


def _strip_style_prompt_block(prompt: str) -> str:
    return STYLE_PROMPT_RE.sub("", str(prompt or ""), count=1).strip()


def _prompt_label_text(prompt: str) -> str:
    text = _strip_style_prompt_block(prompt)
    if not text:
        return ""
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        data = json.loads(raw)
    except Exception:
        return text
    if not isinstance(data, dict):
        return text
    prompt_value = data.get("prompt")
    if isinstance(prompt_value, str) and prompt_value.strip():
        return prompt_value.strip()
    if isinstance(prompt_value, dict):
        for key in ("high_level_description", "description", "subject", "prompt"):
            value = prompt_value.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    for key in ("high_level_description", "description", "subject"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return text


def _with_style_label(values: dict[str, Any], prompt: str) -> str:
    user_prompt = _prompt_label_text(prompt)
    style_label = _style_label_from_fields(values, prompt)
    if style_label and user_prompt:
        return f"{style_label}｜{user_prompt}"
    if user_prompt:
        return user_prompt
    return style_label


def text_prompt_from_fields(field_values: dict[str, Any] | None) -> str:
    """Return the main positive prompt from submitted workflow values."""
    values = field_values or {}

    def _clean_prompt_value(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return value.strip()

    user_prompt = _clean_prompt_value(values.get("__user_prompt"))
    if user_prompt:
        return _with_style_label(values, user_prompt)

    def _first_matching(predicate) -> str:
        for key, value in values.items():
            if str(key).startswith("__"):
                continue
            field = str(key).split("::")[-1].lower()
            if not predicate(field):
                continue
            content = _clean_prompt_value(value)
            if content:
                return _with_style_label(values, content)
        return ""

    for predicate in (
        lambda field: "prompt" in field or "positive" in field,
        lambda field: field == "value",
        lambda field: field == "text",
    ):
        content = _first_matching(predicate)
        if content:
            return content
    return ""


def upscale_resolution_from_fields(field_values: dict[str, Any] | None) -> int:
    """Extract an upscale resolution hint from workflow field values."""
    for key, value in (field_values or {}).items():
        if str(key) != "__video_upscale_long_edge":
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue
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
