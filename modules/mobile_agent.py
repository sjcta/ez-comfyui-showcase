"""Pure backend orchestration helpers for the mobile creator agent."""

from __future__ import annotations

import re
from typing import Any

from modules.prompt_optimizer import clean_user_prompt


DEFAULT_MOBILE_CREATOR_SETTINGS = {
    "enabled": True,
    "default_text_to_image_workflow": "t2i-z-image.json",
    "allowed_styles": ["cinematic", "anime", "realistic"],
    "allowed_ratios": ["1:1", "3:4", "9:16"],
    "llm_timeout_ms": 8000,
    "speech_timeout_ms": 6000,
}

_RATIO_DIMENSIONS = {
    "1:1": {"width": 1024, "height": 1024},
    "3:4": {"width": 960, "height": 1280},
    "9:16": {"width": 720, "height": 1280},
}

_VIDEO_WORDS = ("视频", "动起来", "动画", "短片", "影片", "movie", "video", "animate")
_IMAGE_REQUEST_WORDS = (
    "出一张",
    "生成",
    "画",
    "绘制",
    "照片",
    "图片",
    "图像",
    "插画",
    "壁纸",
    "海报",
    "image",
    "photo",
    "picture",
)
_IMAGE_EDIT_WORDS = ("换", "改", "编辑", "修", "去掉", "添加", "背景", "变成", "替换")
_PHONE_RATIO_WORDS = ("手机壁纸", "手机", "竖版", "竖屏", "纵向", "vertical", "portrait", "9:16")
_THREE_FOUR_WORDS = ("3:4", "四比三", "竖构图")
_SQUARE_WORDS = ("1:1", "方图", "正方形", "头像")

_STYLE_HINTS = {
    "cinematic": "电影感光影，富有层次的镜头氛围",
    "anime": "精致动漫风格，清晰线条和明快色彩",
    "realistic": "真实摄影质感，自然光影和细节",
}


def ratio_to_dimensions(ratio: str) -> dict[str, int]:
    """Return the mobile creator default dimensions for a known aspect ratio."""
    return dict(_RATIO_DIMENSIONS.get(ratio) or _RATIO_DIMENSIONS["1:1"])


class IntentRouter:
    """Classify a mobile creator request without side effects."""

    def classify(self, text: str, has_image: bool = False, has_video: bool = False) -> dict[str, Any]:
        raw_text = str(text or "").strip()
        normalized = raw_text.lower()

        if has_video or _contains_any(normalized, _VIDEO_WORDS):
            return {
                "intent": "unsupported_video",
                "confidence": 0.55,
                "reason": "video_not_supported",
                "question": "当前移动创作助手暂不支持视频生成，请先使用图片生成能力。",
            }

        if has_image or _looks_like_image_edit(normalized):
            return {
                "intent": "unsupported_image_edit",
                "confidence": 0.6,
                "reason": "image_edit_not_supported",
                "question": "当前移动创作助手暂不支持图片编辑，请先描述要生成的新图片。",
            }

        if len(clean_user_prompt(raw_text)) < 4:
            return {
                "intent": "clarify",
                "confidence": 0.3,
                "reason": "text_too_short",
                "question": "请补充想生成的主体、场景或风格。",
            }

        if _contains_any(normalized, _IMAGE_REQUEST_WORDS) or _has_visual_subject(raw_text):
            return {
                "intent": "text_to_image",
                "confidence": 0.88,
                "reason": "text_only_image_request",
                "question": "",
            }

        return {
            "intent": "clarify",
            "confidence": 0.45,
            "reason": "unclear_request",
            "question": "请描述你想生成的图片内容。",
        }


class PromptCompiler:
    """Compile a natural mobile request into constrained generation options."""

    def compile(self, text: str, style: str = "", aspect_ratio: str = "") -> dict[str, Any]:
        cleaned = clean_user_prompt(text)
        selected_ratio = _normalize_ratio(aspect_ratio or _detect_aspect_ratio(text))
        selected_style = _normalize_style(style or _detect_style(text))
        prompt = _strip_ratio_and_style_words(cleaned)
        prompt = _normalize_prompt_separators(prompt)

        hint = _STYLE_HINTS.get(selected_style, "")
        if hint and hint not in prompt:
            prompt = f"{prompt}，{hint}" if prompt else hint

        dimensions = ratio_to_dimensions(selected_ratio)
        return {
            "compiled_prompt": prompt,
            "style": selected_style,
            "aspect_ratio": selected_ratio,
            "width": dimensions["width"],
            "height": dimensions["height"],
        }


def build_agent_response(
    text: str,
    settings: dict[str, Any] | None = None,
    workflow_available: bool = True,
    has_image: bool = False,
    has_video: bool = False,
) -> dict[str, Any]:
    """Build the constrained response contract for the mobile creator agent."""
    merged_settings = {**DEFAULT_MOBILE_CREATOR_SETTINGS, **(settings or {})}
    route = IntentRouter().classify(text, has_image=has_image, has_video=has_video)
    compiled = PromptCompiler().compile(text)
    allowed_styles = _normalize_allowed_styles(merged_settings.get("allowed_styles"))
    allowed_ratios = _normalize_allowed_ratios(merged_settings.get("allowed_ratios"))
    selected_style = _normalize_style(compiled["style"], allowed_styles)
    selected_ratio = _normalize_ratio(compiled["aspect_ratio"], allowed_ratios)
    dimensions = ratio_to_dimensions(selected_ratio)
    resolved_workflow = merged_settings.get("default_text_to_image_workflow", "")

    needs_confirmation = route["intent"] != "text_to_image" or not workflow_available
    error_code = ""
    if route["intent"] != "text_to_image":
        error_code = route["reason"]
    elif not workflow_available:
        error_code = "workflow_unavailable"

    return {
        "intent": route["intent"],
        "confidence": route["confidence"],
        "reason": route["reason"],
        "question": route["question"],
        "raw_text": str(text or ""),
        "display_summary": _build_display_summary(route["intent"], compiled["compiled_prompt"]),
        "compiled_prompt": compiled["compiled_prompt"],
        "style": selected_style,
        "aspect_ratio": selected_ratio,
        "width": dimensions["width"],
        "height": dimensions["height"],
        "workflow": "default_text_to_image",
        "resolved_workflow": resolved_workflow,
        "needs_confirmation": needs_confirmation,
        "error_code": error_code,
        "options": {
            "style": selected_style,
            "aspect_ratio": selected_ratio,
            "width": dimensions["width"],
            "height": dimensions["height"],
            "allowed_styles": allowed_styles,
            "allowed_ratios": allowed_ratios,
        },
    }


def build_generate_fields(workflow_fields: list[dict[str, Any]], compiled_prompt: str) -> dict[str, str]:
    """Place the compiled prompt into the first prompt-like workflow field."""
    for field in workflow_fields or []:
        if _is_prompt_like_field(field):
            node_id = str(field.get("node_id", ""))
            field_name = str(field.get("field", ""))
            if node_id and field_name:
                return {f"{node_id}::{field_name}": compiled_prompt}
    return {}


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word.lower() in text for word in words)


def _looks_like_image_edit(text: str) -> bool:
    return _contains_any(text, _IMAGE_EDIT_WORDS) and ("图" in text or "image" in text or "photo" in text)


def _has_visual_subject(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]{4,}", text or ""))


def _detect_aspect_ratio(text: str) -> str:
    normalized = str(text or "").lower()
    if _contains_any(normalized, _PHONE_RATIO_WORDS):
        return "9:16"
    if _contains_any(normalized, _THREE_FOUR_WORDS):
        return "3:4"
    if _contains_any(normalized, _SQUARE_WORDS):
        return "1:1"
    return "1:1"


def _detect_style(text: str) -> str:
    normalized = str(text or "").lower()
    if any(word in normalized for word in ("电影感", "电影", "cinematic", "film")):
        return "cinematic"
    if any(word in normalized for word in ("动漫", "动画风", "二次元", "anime", "manga")):
        return "anime"
    if any(word in normalized for word in ("真实", "写实", "摄影", "照片", "realistic", "photoreal")):
        return "realistic"
    return ""


def _normalize_style(style: str, allowed_styles: list[str] | None = None) -> str:
    selected = str(style or "").strip()
    allowed = allowed_styles if allowed_styles is not None else DEFAULT_MOBILE_CREATOR_SETTINGS["allowed_styles"]
    return selected if selected in allowed else ""


def _normalize_ratio(ratio: str, allowed_ratios: list[str] | None = None) -> str:
    selected = str(ratio or "").strip()
    allowed = allowed_ratios if allowed_ratios is not None else DEFAULT_MOBILE_CREATOR_SETTINGS["allowed_ratios"]
    if selected in _RATIO_DIMENSIONS and selected in allowed:
        return selected
    if "1:1" in allowed:
        return "1:1"
    for candidate in allowed:
        if candidate in _RATIO_DIMENSIONS:
            return candidate
    return "1:1"


def _normalize_allowed_styles(styles: Any) -> list[str]:
    if not isinstance(styles, list):
        return list(DEFAULT_MOBILE_CREATOR_SETTINGS["allowed_styles"])
    return [style for style in styles if style in _STYLE_HINTS]


def _normalize_allowed_ratios(ratios: Any) -> list[str]:
    if not isinstance(ratios, list):
        return list(DEFAULT_MOBILE_CREATOR_SETTINGS["allowed_ratios"])
    normalized = [ratio for ratio in ratios if ratio in _RATIO_DIMENSIONS]
    return normalized or ["1:1"]


def _strip_ratio_and_style_words(text: str) -> str:
    result = str(text or "")
    for word in _PHONE_RATIO_WORDS + _THREE_FOUR_WORDS + _SQUARE_WORDS:
        result = re.sub(re.escape(word), "", result, flags=re.IGNORECASE)
    for word in ("电影感", "电影风格", "cinematic", "动漫风格", "动漫", "二次元", "anime", "真实风格", "写实", "realistic"):
        result = re.sub(re.escape(word), "", result, flags=re.IGNORECASE)
    return result


def _normalize_prompt_separators(text: str) -> str:
    result = re.sub(r"^[，,、\s]+|[，,、\s]+$", "", str(text or ""))
    result = re.sub(r"[，,、\s]+$", "", result)
    result = re.sub(r"\s+", " ", result)
    result = re.sub(r"[，,、]{2,}", "，", result)
    return result.strip()


def _build_display_summary(intent: str, compiled_prompt: str) -> str:
    if intent == "text_to_image" and compiled_prompt:
        return compiled_prompt[:48]
    if intent == "unsupported_video":
        return "暂不支持视频生成"
    if intent == "unsupported_image_edit":
        return "暂不支持图片编辑"
    return "需要补充创作描述"


def _is_prompt_like_field(field: dict[str, Any]) -> bool:
    label = str(field.get("label", "")).lower()
    field_name = str(field.get("field", "")).lower()
    class_type = str(field.get("class_type", "")).lower()
    zone = str(field.get("zone", "")).lower()

    label_match = any(token in label for token in ("提示词", "正向", "描述", "prompt", "positive"))
    field_match = field_name in {"text", "prompt", "positive_prompt", "caption"} or "prompt" in field_name
    class_match = any(token in class_type for token in ("text", "string", "multiline", "primitive"))
    user_zone = zone in {"", "user_input", "prompt", "positive"}

    return user_zone and class_match and (label_match or field_match)
