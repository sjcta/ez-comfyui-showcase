"""Pure backend orchestration helpers for the mobile creator agent."""

from __future__ import annotations

import re
from typing import Any

from modules.prompt_optimizer import clean_user_prompt


DEFAULT_MOBILE_CREATOR_SETTINGS = {
    "enabled": True,
    "default_text_to_image_workflow": "t2i-z-image.json",
    "default_image_to_image_workflow": "",
    "allowed_styles": ["cinematic", "anime", "realistic"],
    "allowed_ratios": ["1:1", "3:4", "9:16"],
    "llm_enabled": True,
    "llm_provider": "openai_compatible",
    "llm_base_url": "",
    "llm_model": "gemma-4-e2b",
    "llm_api_key": "",
    "llm_gguf_model": "",
    "llm_mmproj_model": "",
    "llm_timeout_ms": 8000,
    "speech_timeout_ms": 6000,
}

_RATIO_DIMENSIONS = {
    "1:1": {"width": 1024, "height": 1024},
    "3:4": {"width": 960, "height": 1280},
    "9:16": {"width": 720, "height": 1280},
}

_VIDEO_WORDS = ("视频", "动起来", "动画", "短片", "影片", "movie", "video", "animate")
_GREETING_WORDS = ("你好", "您好", "hello", "hi", "嗨")
_CAPABILITY_QUESTION_WORDS = ("你会", "你能", "你可以", "能做什么", "可以做什么", "会干嘛", "有什么用")
_GENERAL_QUESTION_WORDS = (
    "吗",
    "么",
    "嘛",
    "什么",
    "为什么",
    "怎么",
    "如何",
    "可不可以",
    "能不能",
    "会不会",
    "以后",
    "未来",
)
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
_IMAGE_ANALYSIS_WORDS = ("分析", "识别", "看看", "看一下", "内容", "这张图", "图片里", "图里", "描述")
_GENERIC_IMAGE_REQUESTS = (
    "我想出一张图",
    "我想要出一张图",
    "我想做一张图",
    "我要出图",
    "帮我出图",
    "帮我生成图片",
    "生成一张图",
    "出一张图",
)
_SUBJECT_WORDS = (
    "人",
    "女孩",
    "男孩",
    "猫",
    "狗",
    "城市",
    "建筑",
    "产品",
    "车",
    "花",
    "风景",
    "海",
    "山",
    "森林",
    "机器人",
    "人物",
)
_SCENE_WORDS = (
    "在",
    "场景",
    "背景",
    "咖啡馆",
    "城市",
    "海边",
    "森林",
    "雨夜",
    "街道",
    "室内",
    "户外",
    "日落",
    "夜景",
)
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

    def classify(
        self,
        text: str,
        has_image: bool = False,
        has_video: bool = False,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raw_text = str(text or "").strip()
        normalized = raw_text.lower()
        context = context if isinstance(context, dict) else {}
        last_result = context.get("last_result") if isinstance(context.get("last_result"), dict) else {}

        if normalized in _GREETING_WORDS:
            return {
                "intent": "clarify",
                "confidence": 0.7,
                "reason": "greeting",
                "question": "你好，我可以先和你聊清楚画面需求，再帮你整理成出图方案。你想做什么内容？",
            }

        if _looks_like_capability_question(raw_text) or _looks_like_general_question(raw_text):
            return {
                "intent": "general_chat",
                "confidence": 0.78,
                "reason": "general_question",
                "question": _general_chat_answer(raw_text),
            }

        if has_video or _contains_any(normalized, _VIDEO_WORDS):
            return {
                "intent": "unsupported_video",
                "confidence": 0.55,
                "reason": "video_not_supported",
                "question": "当前移动创作助手暂不支持视频生成，请先使用图片生成能力。",
            }

        if has_image and _looks_like_image_analysis(normalized):
            return {
                "intent": "general_chat",
                "confidence": 0.74,
                "reason": "image_analysis_request",
                "question": "我已经收到图片。可以先结合你的文字说明进行分析；如果要进一步生成或修改图片，我会继续整理成创作方案。",
            }

        if has_image or _looks_like_image_edit(normalized):
            return {
                "intent": "unsupported_image_edit",
                "confidence": 0.6,
                "reason": "image_edit_not_supported",
                "question": "当前移动创作助手暂不支持图片编辑，请先描述要生成的新图片。",
            }

        if _looks_like_followup_edit(normalized):
            if last_result:
                return {
                    "intent": "image_to_image",
                    "confidence": 0.86,
                    "reason": "followup_edit_last_result",
                    "question": "",
                }
            return {
                "intent": "clarify",
                "confidence": 0.5,
                "reason": "missing_edit_context",
                "question": "我还没有可修改的上一张结果，请先生成一张图，或上传一张要修改的图片。",
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
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the constrained response contract for the mobile creator agent."""
    merged_settings = {**DEFAULT_MOBILE_CREATOR_SETTINGS, **(settings or {})}
    context = context if isinstance(context, dict) else {}
    route = IntentRouter().classify(text, has_image=has_image, has_video=has_video, context=context)
    brief = build_requirement_draft(text, context)
    compile_text = brief.get("prompt_text") or text
    compiled = PromptCompiler().compile(compile_text, style=str(brief.get("style") or ""))
    all_user_text = str(brief.get("all_user_text") or text)
    explicit_style = bool(_detect_style(all_user_text))
    explicit_ratio = bool(_detect_aspect_ratio_explicit(all_user_text))
    allowed_styles = _normalize_allowed_styles(merged_settings.get("allowed_styles"))
    allowed_ratios = _normalize_allowed_ratios(merged_settings.get("allowed_ratios"))
    selected_style = _normalize_style(compiled["style"], allowed_styles)
    selected_ratio = _normalize_ratio(compiled["aspect_ratio"], allowed_ratios)
    dimensions = ratio_to_dimensions(selected_ratio)
    is_image_to_image = route["intent"] == "image_to_image"
    workflow_alias = "default_image_to_image" if is_image_to_image else "default_text_to_image"
    workflow_setting = "default_image_to_image_workflow" if is_image_to_image else "default_text_to_image_workflow"
    resolved_workflow = merged_settings.get(workflow_setting, "")
    source_result = context.get("last_result") if isinstance(context.get("last_result"), dict) else {}

    if route["intent"] == "general_chat":
        return {
            "response_type": "chat",
            "intent": "general_chat",
            "confidence": route["confidence"],
            "reason": route["reason"],
            "question": route["question"],
            "assistant_message": route["question"],
            "missing_slots": [],
            "draft_requirement": {
                "subject": "",
                "scene": "",
                "style": "",
                "aspect_ratio": "",
                "prompt_text": "",
                "ready": False,
            },
            "raw_text": str(text or ""),
            "display_summary": "自然对话",
            "compiled_prompt": "",
            "style": selected_style,
            "aspect_ratio": selected_ratio,
            "width": dimensions["width"],
            "height": dimensions["height"],
            "workflow": workflow_alias,
            "resolved_workflow": "",
            "source_result": source_result,
            "needs_confirmation": True,
            "error_code": "",
            "options": {
                "style": selected_style,
                "aspect_ratio": selected_ratio,
                "width": dimensions["width"],
                "height": dimensions["height"],
                "allowed_styles": allowed_styles,
                "allowed_ratios": allowed_ratios,
            },
            "option_requirements": {
                "style": False,
                "aspect_ratio": False,
            },
        }

    if route["intent"] == "text_to_image" and not brief.get("ready"):
        assistant_message = _assistant_message_for_missing_slots(brief)
        return {
            "response_type": "chat",
            "intent": "clarify",
            "confidence": 0.72,
            "reason": "needs_creative_brief",
            "question": assistant_message,
            "assistant_message": assistant_message,
            "missing_slots": list(brief.get("missing_slots") or []),
            "draft_requirement": _public_brief(brief),
            "raw_text": str(text or ""),
            "display_summary": "继续补充创作需求",
            "compiled_prompt": str(brief.get("prompt_text") or ""),
            "style": selected_style,
            "aspect_ratio": selected_ratio,
            "width": dimensions["width"],
            "height": dimensions["height"],
            "workflow": workflow_alias,
            "resolved_workflow": "",
            "source_result": source_result,
            "needs_confirmation": True,
            "error_code": "",
            "options": {
                "style": selected_style,
                "aspect_ratio": selected_ratio,
                "width": dimensions["width"],
                "height": dimensions["height"],
                "allowed_styles": allowed_styles,
                "allowed_ratios": allowed_ratios,
            },
            "option_requirements": {
                "style": True,
                "aspect_ratio": not explicit_ratio,
            },
        }

    needs_confirmation = route["intent"] not in ("text_to_image", "image_to_image") or not workflow_available
    error_code = ""
    if route["intent"] not in ("text_to_image", "image_to_image"):
        error_code = route["reason"]
    elif not workflow_available:
        error_code = "workflow_unavailable"
        if route["intent"] == "image_to_image" and not route.get("question"):
            route["question"] = "当前未配置图生图工作流，请先在移动端创作设置中配置默认图生图工作流。"

    return {
        "response_type": "confirm" if route["intent"] in ("text_to_image", "image_to_image") and not error_code else "chat",
        "intent": route["intent"],
        "confidence": route["confidence"],
        "reason": route["reason"],
        "question": route["question"],
        "assistant_message": route["question"],
        "missing_slots": list(brief.get("missing_slots") or []),
        "draft_requirement": _public_brief(brief),
        "raw_text": str(text or ""),
        "display_summary": _build_display_summary(route["intent"], compiled["compiled_prompt"]),
        "compiled_prompt": compiled["compiled_prompt"],
        "creative_brief": {
            "task_type": "image_to_image" if route["intent"] == "image_to_image" else "text_to_image",
            "subject": str(brief.get("subject") or compiled["compiled_prompt"]),
            "scene": str(brief.get("scene") or ""),
            "style": selected_style,
            "lighting": "",
            "composition": "",
            "mood": "",
            "negative": "",
            "edit_instruction": _meaningful_requirement_part(text) if route["intent"] == "image_to_image" else "",
            "source_image": _source_result_image(source_result),
            "final_prompt": compiled["compiled_prompt"],
            "aspect_ratio": selected_ratio,
        },
        "style": selected_style,
        "aspect_ratio": selected_ratio,
        "width": dimensions["width"],
        "height": dimensions["height"],
        "workflow": workflow_alias,
        "resolved_workflow": resolved_workflow if route["intent"] in ("text_to_image", "image_to_image") and not error_code else "",
        "source_result": source_result,
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
        "option_requirements": {
            "style": not explicit_style,
            "aspect_ratio": not explicit_ratio,
        },
    }


def build_generate_fields(
    workflow_fields: list[dict[str, Any]],
    compiled_prompt: str,
    source_result: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Place mobile agent values into workflow fields."""
    values: dict[str, str] = {}
    for field in workflow_fields or []:
        if _is_prompt_like_field(field):
            node_id = str(field.get("node_id", ""))
            field_name = str(field.get("field", ""))
            if node_id and field_name:
                values[f"{node_id}::{field_name}"] = compiled_prompt
                break

    source_image = _source_result_image(source_result)
    if source_image:
        for field in workflow_fields or []:
            if _is_load_image_field(field):
                node_id = str(field.get("node_id", ""))
                field_name = str(field.get("field", ""))
                if node_id and field_name:
                    values[f"{node_id}::{field_name}"] = source_image
                    break
    return values


def build_requirement_draft(text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a provider-neutral creative brief from the current turn and chat history."""
    user_texts = _conversation_user_texts(text, context)
    current_text = str(text or "").strip()
    if current_text and _contains_any(current_text.lower(), _IMAGE_REQUEST_WORDS):
        user_texts = [
            item for item in user_texts
            if item == current_text or (not _looks_like_general_question(item) and not _is_greeting_text(item))
        ]
    all_text = "，".join(user_texts)
    meaningful_parts = [_meaningful_requirement_part(item) for item in user_texts]
    meaningful_parts = [item for item in meaningful_parts if item]
    prompt_text = _normalize_prompt_separators("，".join(meaningful_parts))
    style = _detect_style(all_text)
    ratio = _detect_aspect_ratio_explicit(all_text)
    subject = _extract_subject(meaningful_parts)
    scene = _extract_scene(meaningful_parts)
    missing_slots: list[str] = []
    if not subject:
        missing_slots.append("subject")
    if subject and not scene and not _requirement_is_specific_enough(subject, style, prompt_text):
        missing_slots.append("scene")
    ready = bool(subject) and not missing_slots
    return {
        "all_user_text": all_text,
        "prompt_text": prompt_text,
        "subject": subject,
        "scene": scene,
        "style": style,
        "aspect_ratio": ratio,
        "missing_slots": missing_slots,
        "ready": ready,
    }


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word.lower() in text for word in words)


def _looks_like_capability_question(text: str) -> bool:
    normalized = str(text or "").lower()
    return _contains_any(normalized, _CAPABILITY_QUESTION_WORDS)


def _is_greeting_text(text: str) -> bool:
    return str(text or "").strip().lower() in _GREETING_WORDS


def _looks_like_general_question(text: str) -> bool:
    raw = str(text or "").strip()
    normalized = raw.lower()
    if not raw:
        return False
    if _contains_any(normalized, _IMAGE_REQUEST_WORDS):
        return False
    has_question_mark = raw.endswith(("?", "？"))
    has_question_word = _contains_any(normalized, _GENERAL_QUESTION_WORDS)
    if not (has_question_mark or has_question_word):
        return False
    return not _looks_like_image_edit(normalized) and not _looks_like_followup_edit(normalized)


def _general_chat_answer(text: str) -> str:
    raw = str(text or "").strip()
    normalized = raw.lower()
    if _looks_like_capability_question(raw):
        return (
            "我现在主要帮你把创作想法聊清楚，再整理成可确认的出图方案。"
            "你也可以先随便问我问题；当你说“帮我出一张……”时，我会切到出图流程。"
        )
    if "机器人" in raw and ("老人" in raw or "养老" in raw or "照顾" in raw):
        return (
            "可以，而且会先从陪伴、提醒吃药、跌倒告警、简单搬运和远程看护这些场景开始。"
            "真正照顾老人还需要安全、隐私、医疗责任和情感陪伴一起设计。"
            "如果你想把这个想法做成画面，我可以继续帮你整理成“养老陪护机器人”的出图方案。"
        )
    if "以后" in raw or "未来" in raw:
        return "有可能，但要看技术成熟度、成本和真实场景约束。你也可以把这个问题继续延展成一个概念图方向。"
    if "什么" in raw or "为什么" in raw or "怎么" in raw or "如何" in raw:
        return "可以聊。你可以继续问，我会先按普通对话回答；当内容变成明确画面需求时，我再整理成出图方案。"
    return "可以，我先按普通对话回答。你也可以继续补充想法，我会判断它是聊天问题还是创作需求。"


def _looks_like_image_edit(text: str) -> bool:
    return _contains_any(text, _IMAGE_EDIT_WORDS) and ("图" in text or "image" in text or "photo" in text)


def _looks_like_image_analysis(text: str) -> bool:
    return _contains_any(text, _IMAGE_ANALYSIS_WORDS)


def _looks_like_followup_edit(text: str) -> bool:
    stripped = str(text or "").strip()
    return bool(stripped) and _contains_any(stripped, _IMAGE_EDIT_WORDS)


def _conversation_user_texts(text: str, context: dict[str, Any] | None) -> list[str]:
    values: list[str] = []
    messages = context.get("messages") if isinstance(context, dict) else []
    if isinstance(messages, list):
        for msg in messages[-12:]:
            if isinstance(msg, dict) and msg.get("role") == "user":
                value = str(msg.get("text") or "").strip()
                if value:
                    values.append(value)
    current = str(text or "").strip()
    if current and (not values or values[-1] != current):
        values.append(current)
    return values or ([current] if current else [])


def _meaningful_requirement_part(text: str) -> str:
    value = clean_user_prompt(text)
    value = _strip_ratio_and_style_words(value)
    for phrase in _GENERIC_IMAGE_REQUESTS:
        value = re.sub(re.escape(phrase), "", value, flags=re.IGNORECASE)
    value = re.sub(r"^(帮我|请|想要|我想要|我想|我要|做|生成|出|画|一张|一个|的)+", "", value)
    value = re.sub(r"(图片|照片|图像|图)$", "", value)
    return _normalize_prompt_separators(value)


def _extract_subject(parts: list[str]) -> str:
    for part in parts:
        if not part:
            continue
        if _contains_any(part, _SUBJECT_WORDS) or len(part) >= 2:
            return part
    return ""


def _extract_scene(parts: list[str]) -> str:
    for part in reversed(parts):
        if _contains_any(part, _SCENE_WORDS):
            return part
    return ""


def _requirement_is_specific_enough(subject: str, style: str, prompt_text: str) -> bool:
    if len(subject) >= 5:
        return True
    if style and _extract_scene([prompt_text]):
        return True
    return False


def _assistant_message_for_missing_slots(brief: dict[str, Any]) -> str:
    missing = set(brief.get("missing_slots") or [])
    subject = str(brief.get("subject") or "").strip()
    if "subject" in missing:
        return "可以。你想做什么主体的图？比如人物、产品、风景、动物，或者直接告诉我画面里最重要的东西。"
    if "scene" in missing:
        style = str(brief.get("style") or "").strip()
        if style:
            return f"我先记下：{subject}，风格偏 {style}。你希望它出现在什么场景或背景里？"
        return f"我先记下：{subject}。你想要什么风格、场景或氛围？可以继续用几句话补充。"
    return "我先帮你整理这些信息。你还可以补充风格、场景、画幅或想要的氛围。"


def _public_brief(brief: dict[str, Any]) -> dict[str, Any]:
    return {
        "subject": str(brief.get("subject") or ""),
        "scene": str(brief.get("scene") or ""),
        "style": str(brief.get("style") or ""),
        "aspect_ratio": str(brief.get("aspect_ratio") or ""),
        "prompt_text": str(brief.get("prompt_text") or ""),
        "ready": bool(brief.get("ready")),
    }


def _has_visual_subject(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]{4,}", text or ""))


def _detect_aspect_ratio(text: str) -> str:
    detected = _detect_aspect_ratio_explicit(text)
    if detected:
        return detected
    return "1:1"


def _detect_aspect_ratio_explicit(text: str) -> str:
    normalized = str(text or "").lower()
    if _contains_any(normalized, _PHONE_RATIO_WORDS):
        return "9:16"
    if _contains_any(normalized, _THREE_FOUR_WORDS):
        return "3:4"
    if _contains_any(normalized, _SQUARE_WORDS):
        return "1:1"
    if re.search(r"\b(9\s*[:x×]\s*16|720\s*[:x×]\s*1280)\b", normalized):
        return "9:16"
    if re.search(r"\b(3\s*[:x×]\s*4|960\s*[:x×]\s*1280)\b", normalized):
        return "3:4"
    if re.search(r"\b(1\s*[:x×]\s*1|1024\s*[:x×]\s*1024)\b", normalized):
        return "1:1"
    return ""


def _detect_style(text: str) -> str:
    normalized = str(text or "").lower()
    if any(word in normalized for word in ("电影感", "电影", "cinematic", "film")):
        return "cinematic"
    if any(word in normalized for word in ("动漫", "漫画", "动画风", "二次元", "anime", "manga")):
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


def _is_load_image_field(field: dict[str, Any]) -> bool:
    field_name = str(field.get("field", "")).lower()
    class_type = str(field.get("class_type", "")).lower()
    field_type = str(field.get("type", "")).lower()
    zone = str(field.get("zone", "")).lower()
    if zone and zone not in {"user_input", "advanced"}:
        return False
    return (
        field_name == "image"
        and (
            class_type in {"loadimage", "loadimagefrompath"}
            or field_type == "image"
        )
    )


def _source_result_image(source_result: dict[str, Any] | None) -> str:
    if not isinstance(source_result, dict):
        return ""
    return str(source_result.get("image") or source_result.get("filename") or "").strip()
