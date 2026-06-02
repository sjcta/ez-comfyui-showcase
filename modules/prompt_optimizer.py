"""Prompt optimization helpers backed by lightweight ComfyUI text workflows."""

from __future__ import annotations

import copy
import ast
import json
import re
import time
import uuid
from typing import Any, Callable

from modules.llm_client import DIRECT_FINAL_SYSTEM_PROMPT, chat_text, llm_provider_name


MAX_USER_PROMPT_CHARS = 10_000


def _bounded_user_prompt(prompt: str, *, field: str = "prompt") -> str:
    text = str(prompt or "")
    if len(text) > MAX_USER_PROMPT_CHARS:
        raise ValueError(f"{field} is too long; maximum is {MAX_USER_PROMPT_CHARS} characters")
    return text


HIGH_SUCCESS_PROMPT_SPEC_GUIDE = (
    "High-success image prompt spec: treat the prompt as an executable image specification, "
    "not a loose tag list. Organize the visual plan by 任务目标、保真要求、主体、动作姿态、场景、"
    "构图镜头、光线色彩、材质细节、风格媒介、文字版式、负向限制. For image-to-image or "
    "reference-based work, lock identity first: face proportions, hairstyle, body shape, clothing, "
    "head direction, key colors, and signature details. Subject and pose must be actionable: "
    "describe facial expression, gaze, hands, feet, contact points, occlusion, crop boundaries, "
    "and spatial direction with clear references. Scene should name the concrete place, time, "
    "weather, background objects, and how the subject fits into the environment. Composition and "
    "camera should specify aspect/framing, shot scale, camera angle, focal feel, subject ratio, "
    "foreground/midground/background, and for grid or contact-sheet prompts, each cell's image "
    "content and layout role. Lighting and color should bind each object to exact color names, "
    "approximate HEX values when useful, color temperature, key-light direction, shadow softness, "
    "and contrast. Materials and details should name texture, weave, transparency, gloss, roughness, "
    "grain, reflection, and surface condition for skin, fabric, metal, glass, paper, water, and props. "
    "Style mixing should be layered: the realistic layer controls environment and photography, "
    "while stylized layers control illustration, character treatment, typography, or special material "
    "effects. Text/layout prompts must include only text that should appear, its placement, hierarchy, "
    "and font mood; avoid extra unreadable text. The positive prompt is the main control surface, "
    "especially for FLUX.2 and Z-Image Turbo; negative prompts should be pure short phrases/tags "
    "such as watermark, extra fingers, wrong text, style drift, face, crossed legs, never command sentences."
)

IMAGE_PROMPT_OPTIMIZATION_GUIDE = (
    "Use a Nano Banana / GPT Image style prompt-improvement checklist internally, "
    "but do not output the checklist or labels. Preserve the user's intent and all "
    "specified subjects, quantities, colors, text, names, style references, aspect "
    "ratio hints, and constraints. First remove request boilerplate, then enrich only "
    "missing visual information. Cover these elements when relevant: subject/action, "
    "context/setting, composition/framing, lighting/atmosphere, materials/textures, "
    "color palette, mood, intended use, and constraints. For GPT Image-like needs "
    "such as UI mockups, brand assets, posters, slides, product images, or readable "
    "text, think in Scene / Subject / Important Details / Use Case / Constraints and "
    "quote exact visible text. For Nano Banana-like needs, prefer natural prose with "
    "explicit real-world or cultural anchors, spatial relationships, and reference "
    "roles; avoid unnecessary camera-number jargon. Use positive framing instead of "
    "negative wording, avoid vague praise such as stunning/epic/masterpiece, avoid "
    "tag soup, and do not invent major new concepts. For model-aware output, Qwen Image "
    "can use concise negative tag phrases; FLUX.2 and Z-Image Turbo should treat the "
    "positive prompt as the control surface because traditional negative prompts are not "
    "reliable there. "
    + HIGH_SUCCESS_PROMPT_SPEC_GUIDE
    + " The plain-text variant should be "
    "one fluent generation prompt in the user's language, with no markdown, headings, "
    "bullets, or explanation."
)

VIDEO_SCRIPT_OPTIMIZATION_GUIDE = (
    "Use a video-generation script prompt checklist internally, blending LTX-style concise visual "
    "direction with Seedance 2.0-style Chinese script structure. Preserve the user's core concept, "
    "subject identity, visual style, and intended action, but default to the app's single uploaded image "
    "as the only visual reference. Rewrite the request as a production-ready Chinese video script prompt, not an image prompt. Include only "
    "details that improve video adherence, separated clearly by 人物、场景、氛围、动作、表情、镜头、光影 when relevant: "
    "shot scale, scene and atmosphere, subject action as a clear beginning-to-end motion sequence, "
    "camera movement relative to the subject, lighting and color, and visual continuity. For LTX/Sulphur, "
    "keep the motion instructions concrete and avoid overloading one shot with conflicting actions; "
    "state motion intensity when relevant. Do not invent @图片, @视频, or @音频 reference placeholders; "
    "if the user mentions the current reference, describe it naturally as the single uploaded image "
    "or first-frame reference. Do not add audio, music, ambient sound, or sound-reference instructions "
    "unless the workflow explicitly supports audio and the user asks for it. Do not include duration "
    "or aspect-ratio settings such as 时长10秒 or 16:9; those are controlled by the user interface. "
    "Preserve user-provided second or frame timeline labels such as 0-3秒, 3-6秒, or 第24帧 as action-content structure, "
    "because timeline descriptions are not the same as duration settings. "
    "Avoid negative prompt phrasing such as 禁止文字、字幕、LOGO、水印、风格漂移、角色变脸 in the positive script; "
    "instead use positive visual continuity wording only when useful. Prefer compact Chinese clauses such as "
    "人物：...；场景：...；氛围：...；动作：...；表情：...；镜头：...；光影：..., or keep a user-provided timeline. "
    "Avoid markdown, JSON, checklist labels, tag soup, and generic praise such as masterpiece."
)

STRUCTURED_PROMPT_JSON_SCHEMA = (
    "Return only a valid JSON object with this exact top-level shape: "
    '{"keyword_prompt":"...",'
    '"structured_prompt":{"intent":"...","identity_lock":"...","subject":"...","action":"...","pose_details":"...",'
    '"hand_details":"...","foot_details":"...","joint_body_mechanics":"...",'
    '"facial_expression_details":"...","occlusion_crop_details":"...","exposed_body_details":"...",'
    '"intimate_body_details":"...","sexual_act_details":"...","genital_details":"...",'
    '"fluid_contact_details":"...","nsfw_content_details":"...","content_safety_labels":[],'
    '"scene":"...",'
    '"composition":"...","lighting":"...","style":"...","color_palette":"...",'
    '"materials_textures":[],"important_details":[],"visible_text":[],"text_layout":"...","constraints":[],'
    '"negative_prompt":[]}}. '
    "The keyword_prompt is the compact plain prompt. The structured_prompt is the JSON prompt "
    "that can be copied directly to an image model. Do not include metadata keys such as "
    "version or language. Do not repeat the full keyword_prompt inside structured_prompt "
    "when subject/action/scene/composition fields already describe the image. Omit fields that are "
    "unknown, empty strings, or empty arrays. negative_prompt must contain only comma/tag-style "
    "phrases such as blurry, watermark, face, crossed legs; never include imperative wording such "
    "as no, avoid, do not, 不要, 避免, 禁止. Keep the user's language unless the user explicitly asks otherwise."
)

DEFAULT_OPTIMIZER_INSTRUCTION = (
    "Rewrite the user request into a concise, accurate text-to-image prompt. "
    "Remove assistant/request wording, keep the real visual subject and constraints, "
    "prefer concrete visual details, and output only the final prompt. "
    + IMAGE_PROMPT_OPTIMIZATION_GUIDE
)

QWEN_OPTIMIZER_TEMPLATE = (
    "You are a text-to-image prompt optimizer. Convert the user request into one concise "
    "image generation prompt. Remove request words such as help me, generate, draw, please, "
    "image, picture. Preserve the visual subject, style, composition, quantities, colors, and "
    "constraints. Preserve proper nouns, cultural titles, IP names, character names, brand names, "
    "and place names in their original language. Do not literally translate cultural references; "
    "add short explanatory visual descriptors after the original name when useful. Apply this "
    "model-aware image prompt guide: {optimization_guide} Do not describe "
    "the user request itself. {json_schema} Do not output markdown or explanation."
    "{reference_context}\n\nUser request: {prompt}"
)

QWEN_VIDEO_SCRIPT_OPTIMIZER_TEMPLATE = (
    "You are a professional video script prompt optimizer for LTX / Sulphur and Seedance 2.0 video "
    "generation workflows. Convert the user request into one Chinese video-generation script prompt. "
    "Remove request wording such as help me, generate, please, video, prompt, and optimize, but preserve "
    "the real scene, subject, action, and style. Assume the current workflow has a single uploaded image "
    "reference by default. Do not invent @图片, @视频, or @音频 reference placeholders. Do not include duration "
    "or aspect-ratio settings; the user interface controls those values. Preserve user-provided second or frame timeline labels. "
    "Separate the script into compact Chinese clauses for 人物、场景、氛围、动作、表情、镜头、光影 when useful. "
    "{timing_context}"
    "Apply this model-aware video script guide: {optimization_guide} Do not output markdown, JSON, "
    "checklist labels, or explanation. Output only the final video script prompt.\n\nUser request: {prompt}"
)

QWEN_TRANSLATE_TEMPLATE = (
    "Translate the following image-generation prompt into concise, natural Chinese. "
    "Keep artist names, brand names, character names, model names, and technical camera/style terms "
    "when direct translation would lose meaning. Do not include the original English prompt, bilingual "
    "labels, or alternate-language explanations. Do not add new visual content. "
    "Output only the Chinese prompt, with no markdown and no explanation.\n\nPrompt: {prompt}"
)

QWEN_LANGUAGE_SWITCH_TEMPLATE = (
    "Translate the following image-generation prompt into {target_language_name}. "
    "Keep it as a concise, natural text-to-image prompt, not an explanation. Preserve visual details, "
    "style references, quantities, colors, composition, visible text, and constraints. Preserve proper nouns, "
    "artist names, brand names, character names, model names, and culturally specific titles in their original "
    "language when direct translation would lose meaning; add a short explanatory visual descriptor only when useful. "
    "If the prompt is a JSON object, keep a valid JSON object with the same keys and structure; translate only "
    "human-facing string values and string-array items, preserve every key and every array item, and do not convert JSON into prose or keywords. "
    "Do not add new major concepts. Output only the translated prompt, with no markdown, labels, quotes, or explanation.\n\n"
    "Prompt: {prompt}"
)

KNOWN_REFERENCE_CONTEXT = {
    "黑猫警长": "黑猫警长 is a classic Chinese animated police cat character, heroic, upright, smart, nostalgic Chinese animation style.",
}


def _context_number(context: dict[str, Any] | None, *keys: str) -> float:
    data = context or {}
    for key in keys:
        try:
            value = data.get(key)
        except AttributeError:
            return 0.0
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return 0.0


def _format_context_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _video_script_timing_context_text(context: dict[str, Any] | None) -> str:
    duration = _context_number(context, "duration_seconds", "duration_sec", "seconds", "duration")
    fps = _context_number(context, "fps", "frame_rate", "frameRate")
    frames = _context_number(context, "frame_count", "frames", "length", "frames_number")
    if duration <= 0 and frames > 0 and fps > 0:
        duration = frames / fps
    if frames <= 0 and duration > 0 and fps > 0:
        frames = round(duration * fps)
    fragments: list[str] = []
    if duration > 0:
        fragments.append(f"{_format_context_number(duration)} seconds")
    if fps > 0:
        fragments.append(f"{_format_context_number(fps)} fps")
    if frames > 0:
        fragments.append(f"{_format_context_number(frames)} frames")
    if not fragments:
        return ""
    ranges: list[str] = []
    if duration > 0:
        ranges.append(f"0-{_format_context_number(duration)} seconds")
    if frames > 0:
        ranges.append(f"frame 1-{_format_context_number(frames)}")
    range_text = f" Suggested usable timeline range: {' / '.join(ranges)}." if ranges else ""
    return (
        "Current workflow timing: "
        + ", ".join(fragments)
        + ". Arrange the action as a beginning-to-end timeline that fits the full clip."
        + range_text
        + " Keep timeline segments within this duration or frame range, and do not output it as a standalone duration parameter. "
    )


REQUEST_PREFIX_RE = re.compile(
    r"^\s*(?:请\s*)?(?:帮我|给我|为我|替我)?\s*"
    r"(?:生成|画|绘制|制作|做|出|创作|设计|来)\s*"
    r"(?:一张|一幅|一个|一份|一组|些|点)?\s*",
    re.IGNORECASE,
)

REQUEST_SUFFIX_RE = re.compile(
    r"\s*(?:图片|图像|照片|插画|作品|效果图)?\s*(?:谢谢|谢谢你)?[。！？!?.\s]*$",
    re.IGNORECASE,
)

QUOTE_RE = re.compile(r"^[\"'“”‘’\s]+|[\"'“”‘’\s]+$")
CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
ENGLISH_SENTENCE_RE = re.compile(
    r"(?:^|[\s。！？；;，,、])"
    r"[A-Za-z][A-Za-z'’.-]*"
    r"(?:\s+[A-Za-z][A-Za-z'’.-]*){5,}"
)
BILINGUAL_LABEL_RE = re.compile(
    r"\s*(?:英文|英语|English|Original(?:\s+prompt)?|Prompt|Source|原文|原始提示词)\s*[:：].*$",
    re.IGNORECASE | re.DOTALL,
)
ENGLISH_FRAGMENT_RE = re.compile(r"[A-Za-z][A-Za-z0-9'’._+/-]*")
TRAILING_ENGLISH_AFTER_SENTENCE_RE = re.compile(
    r"([。！？!?])\s*[A-Za-z0-9][A-Za-z0-9'’._+/-]*"
    r"(?:[\s,，、；;]+[A-Za-z0-9][A-Za-z0-9'’._+/-]*)+\s*$"
)
TRAILING_INLINE_ENGLISH_RE = re.compile(
    r"\s+[A-Za-z0-9][A-Za-z0-9'’._+/-]*(?:\s+[A-Za-z0-9][A-Za-z0-9'’._+/-]*){0,4}\s*$"
)


def clean_user_prompt(prompt: str) -> str:
    """Remove high-confidence request boilerplate before the LLM enhancer runs."""
    text = str(prompt or "").strip()
    if not text:
        return ""
    previous = None
    while previous != text:
        previous = text
        text = REQUEST_PREFIX_RE.sub("", text, count=1).strip()
    text = REQUEST_SUFFIX_RE.sub("", text).strip()
    text = QUOTE_RE.sub("", text).strip()
    return text or str(prompt or "").strip()


def build_superprompt_workflow(
    prompt: str,
    instruction: str | None = None,
    max_new_tokens: int = 192,
) -> dict[str, dict[str, Any]]:
    """Build a small ComfyUI API prompt for KJNodes Superprompt."""
    cleaned = clean_user_prompt(_bounded_user_prompt(prompt))
    tokens = max(1, min(int(max_new_tokens or 192), 4096))
    return {
        "1": {
            "inputs": {"text": cleaned},
            "class_type": "Text Multiline",
            "_meta": {"title": "User Prompt"},
        },
        "2": {
            "inputs": {
                "instruction_prompt": instruction or DEFAULT_OPTIMIZER_INSTRUCTION,
                "prompt": ["1", 0],
                "max_new_tokens": tokens,
            },
            "class_type": "Superprompt",
            "_meta": {"title": "Lightweight Prompt Optimizer"},
        },
        "3": {
            "inputs": {"text": ["2", 0]},
            "class_type": "ShowText|pysssss",
            "_meta": {"title": "Optimized Prompt"},
        },
    }


def build_qwen_prompt_optimizer_workflow(
    prompt: str,
    max_new_tokens: int = 384,
    keep_model_loaded: bool = True,
    prompt_mode: str = "image",
    prompt_context: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build a Qwen3-VL text-only workflow for Chinese-aware prompt cleanup."""
    cleaned = clean_user_prompt(_bounded_user_prompt(prompt))
    tokens = max(128, min(int(max_new_tokens or 128), 4096))
    reference_context = _known_reference_context(cleaned)
    mode = "video_script" if str(prompt_mode or "").lower() in {"video", "video_script", "script"} else "image"
    if mode == "video_script":
        optimizer_text = QWEN_VIDEO_SCRIPT_OPTIMIZER_TEMPLATE.format(
            prompt=cleaned,
            optimization_guide=VIDEO_SCRIPT_OPTIMIZATION_GUIDE,
            timing_context=_video_script_timing_context_text(prompt_context),
        )
    else:
        optimizer_text = QWEN_OPTIMIZER_TEMPLATE.format(
            prompt=cleaned,
            reference_context=reference_context,
            optimization_guide=IMAGE_PROMPT_OPTIMIZATION_GUIDE,
            json_schema=STRUCTURED_PROMPT_JSON_SCHEMA,
        )
    return {
        "1": {
            "inputs": {
                "text": optimizer_text,
                "model": "Qwen3-VL-4B-Instruct",
                "quantization": "4bit",
                "keep_model_loaded": bool(keep_model_loaded),
                "temperature": 0.2,
                "max_new_tokens": tokens,
                "min_pixels": 3136,
                "max_pixels": 200704,
                "seed": 1,
                "attention": "sdpa",
            },
            "class_type": "Qwen3_VQA",
            "_meta": {"title": "Qwen Video Script Optimizer" if mode == "video_script" else "Qwen Prompt Optimizer"},
        },
        "2": {
            "inputs": {"text": ["1", 0]},
            "class_type": "ShowText|pysssss",
            "_meta": {"title": "Optimized Video Script" if mode == "video_script" else "Optimized Prompt"},
        },
    }


def build_qwen_prompt_translator_workflow(
    prompt: str,
    max_new_tokens: int = 192,
    keep_model_loaded: bool = True,
) -> dict[str, dict[str, Any]]:
    """Build a Qwen3-VL text-only workflow that translates image prompts to Chinese."""
    text = _bounded_user_prompt(prompt).strip()
    tokens = max(96, min(int(max_new_tokens or 192), 4096))
    return {
        "1": {
            "inputs": {
                "text": QWEN_TRANSLATE_TEMPLATE.format(prompt=text),
                "model": "Qwen3-VL-4B-Instruct",
                "quantization": "4bit",
                "keep_model_loaded": bool(keep_model_loaded),
                "temperature": 0.15,
                "max_new_tokens": tokens,
                "min_pixels": 3136,
                "max_pixels": 200704,
                "seed": 1,
                "attention": "sdpa",
            },
            "class_type": "Qwen3_VQA",
            "_meta": {"title": "Qwen Prompt Translator"},
        },
        "2": {
            "inputs": {"text": ["1", 0]},
            "class_type": "ShowText|pysssss",
            "_meta": {"title": "Chinese Prompt"},
        },
    }


def build_qwen_prompt_language_switch_workflow(
    prompt: str,
    target_language: str,
    max_new_tokens: int = 256,
    keep_model_loaded: bool = True,
) -> dict[str, dict[str, Any]]:
    """Build a Qwen3-VL text-only workflow that switches a prompt between Chinese and English."""
    text = _bounded_user_prompt(prompt).strip()
    target = "en" if str(target_language or "").lower().startswith("en") else "zh"
    target_name = "English" if target == "en" else "Chinese"
    requested_tokens = int(max_new_tokens or 256)
    if isinstance(_extract_json_object(text), dict):
        requested_tokens = max(requested_tokens, min(4096, max(1024, int(len(text) * 0.75) + 384)))
    tokens = max(96, min(requested_tokens, 4096))
    return {
        "1": {
            "inputs": {
                "text": QWEN_LANGUAGE_SWITCH_TEMPLATE.format(
                    prompt=text,
                    target_language_name=target_name,
                ),
                "model": "Qwen3-VL-4B-Instruct",
                "quantization": "4bit",
                "keep_model_loaded": bool(keep_model_loaded),
                "temperature": 0.15,
                "max_new_tokens": tokens,
                "min_pixels": 3136,
                "max_pixels": 200704,
                "seed": 1,
                "attention": "sdpa",
            },
            "class_type": "Qwen3_VQA",
            "_meta": {"title": "Qwen Prompt Language Switch"},
        },
        "2": {
            "inputs": {"text": ["1", 0]},
            "class_type": "ShowText|pysssss",
            "_meta": {"title": "Translated Prompt"},
        },
    }


def _known_reference_context(prompt: str) -> str:
    hits = [desc for key, desc in KNOWN_REFERENCE_CONTEXT.items() if key in str(prompt or "")]
    if not hits:
        return ""
    return "\n\nKnown cultural reference notes: " + " ".join(hits)


def extract_show_text(history_entry: dict[str, Any], node_id: str = "3") -> str:
    """Extract text from a ComfyUI history entry output node."""
    outputs = history_entry.get("outputs", {}) if isinstance(history_entry, dict) else {}
    node_out = outputs.get(str(node_id), {})
    text = node_out.get("text")
    if isinstance(text, list) and text:
        return str(text[0]).strip()
    if isinstance(text, str):
        return text.strip()
    for candidate in outputs.values():
        text = candidate.get("text") if isinstance(candidate, dict) else None
        if isinstance(text, list) and text:
            return str(text[0]).strip()
        if isinstance(text, str):
            return text.strip()
    return ""


def _normalize_optimized_text(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"^```(?:text|markdown|json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    if cleaned.startswith("[") and cleaned.endswith("]"):
        try:
            parsed = ast.literal_eval(cleaned)
            if isinstance(parsed, list) and parsed:
                cleaned = str(parsed[0]).strip()
        except Exception:
            pass
    cleaned = QUOTE_RE.sub("", cleaned).strip()
    return cleaned


def _extract_json_object(text: str) -> dict[str, Any] | None:
    cleaned = str(text or "").strip()
    if not cleaned:
        return None
    candidates = [cleaned]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        candidates.append(cleaned[start : end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            try:
                parsed = ast.literal_eval(candidate)
            except Exception:
                continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _coerce_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _coerce_text_value(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "，".join(_coerce_text_list(value))
    return str(value or "").strip()


def _detect_prompt_language(*values: str) -> str:
    text = " ".join(str(value or "") for value in values)
    return "zh" if CHINESE_RE.search(text) else "en"


def _normalize_structured_prompt(value: Any, cleaned_prompt: str, optimized_prompt: str) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    optimized = str(optimized_prompt or cleaned_prompt or "").strip()
    cleaned = str(cleaned_prompt or "").strip()
    structured = {
        "version": "ez-prompt-json-v1",
        "language": str(source.get("language") or _detect_prompt_language(cleaned, optimized)).strip() or "en",
        "intent": str(source.get("intent") or cleaned).strip(),
        "prompt": str(source.get("prompt") or optimized).strip(),
        "subject": _coerce_text_value(source.get("subject") or cleaned),
        "subject_attributes": _coerce_text_value(source.get("subject_attributes") or source.get("character_details") or source.get("appearance") or ""),
        "action": _coerce_text_value(source.get("action") or ""),
        "pose_details": _coerce_text_value(source.get("pose_details") or source.get("pose") or source.get("body_pose") or ""),
        "hand_details": _coerce_text_value(source.get("hand_details") or source.get("hands") or source.get("hand_pose") or ""),
        "foot_details": _coerce_text_value(source.get("foot_details") or source.get("feet_details") or source.get("feet") or source.get("foot_pose") or ""),
        "joint_body_mechanics": _coerce_text_value(source.get("joint_body_mechanics") or source.get("joint_details") or source.get("body_mechanics") or source.get("weight_distribution") or ""),
        "facial_expression_details": _coerce_text_value(source.get("facial_expression_details") or source.get("face_details") or source.get("expression_details") or source.get("facial_expression") or ""),
        "occlusion_crop_details": _coerce_text_value(source.get("occlusion_crop_details") or source.get("occlusion_details") or source.get("crop_details") or source.get("visibility_details") or ""),
        "exposed_body_details": _coerce_text_value(source.get("exposed_body_details") or source.get("body_exposure") or source.get("skin_exposure") or source.get("nudity_details") or ""),
        "intimate_body_details": _coerce_text_value(source.get("intimate_body_details") or source.get("private_body_details") or source.get("genital_details") or source.get("intimate_parts") or ""),
        "sexual_act_details": _coerce_text_value(source.get("sexual_act_details") or source.get("sex_act_details") or source.get("sexual_action_details") or source.get("explicit_action_details") or ""),
        "genital_details": _coerce_text_value(source.get("genital_details") or source.get("visible_genitals") or source.get("genitals") or source.get("sex_organ_details") or ""),
        "fluid_contact_details": _coerce_text_value(source.get("fluid_contact_details") or source.get("fluid_details") or source.get("sexual_fluid_details") or source.get("body_fluid_details") or ""),
        "nsfw_content_details": _coerce_text_value(
            source.get("nsfw_content_details")
            or source.get("nsfw_details")
            or source.get("adult_content_details")
            or source.get("explicit_content_details")
            or source.get("sexual_content_details")
            or ""
        ),
        "content_safety_labels": _coerce_text_list(source.get("content_safety_labels") or source.get("safety_labels") or source.get("nsfw_labels")),
        "scene": _coerce_text_value(source.get("scene") or source.get("context") or source.get("setting") or ""),
        "foreground": _coerce_text_value(source.get("foreground") or ""),
        "midground": _coerce_text_value(source.get("midground") or ""),
        "background": _coerce_text_value(source.get("background") or ""),
        "composition": _coerce_text_value(source.get("composition") or source.get("framing") or ""),
        "camera_lens": _coerce_text_value(source.get("camera_lens") or source.get("camera") or source.get("lens") or source.get("viewpoint") or ""),
        "lighting": _coerce_text_value(source.get("lighting") or source.get("atmosphere") or ""),
        "style": _coerce_text_value(source.get("style") or ""),
        "color_palette": _coerce_text_value(source.get("color_palette") or source.get("colors") or ""),
        "mood_atmosphere": _coerce_text_value(source.get("mood_atmosphere") or source.get("mood") or source.get("atmosphere") or ""),
        "materials_textures": _coerce_text_list(source.get("materials_textures") or source.get("textures")),
        "clothing_accessories": _coerce_text_list(source.get("clothing_accessories") or source.get("clothing") or source.get("accessories")),
        "environment_objects": _coerce_text_list(source.get("environment_objects") or source.get("objects") or source.get("props")),
        "important_details": _coerce_text_list(source.get("important_details") or source.get("details")),
        "visible_text": _coerce_text_list(source.get("visible_text") or source.get("text")),
        "quality_notes": _coerce_text_list(source.get("quality_notes") or source.get("rendering_details") or source.get("technical_details")),
        "constraints": _coerce_text_list(source.get("constraints")),
        "negative_prompt": _coerce_text_list(source.get("negative_prompt") or source.get("avoid")),
    }
    if structured["prompt"] and structured["prompt"] not in structured["important_details"]:
        structured["important_details"].insert(0, structured["prompt"])
    return structured


def _prune_empty_prompt_value(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if key in {"version", "language", "intent"}:
                continue
            pruned = _prune_empty_prompt_value(item)
            if pruned in ("", None, [], {}):
                continue
            cleaned[key] = pruned
        return cleaned
    if isinstance(value, list):
        cleaned_items = []
        for item in value:
            pruned = _prune_empty_prompt_value(item)
            if pruned in ("", None, [], {}):
                continue
            cleaned_items.append(pruned)
        return cleaned_items
    if isinstance(value, str):
        cleaned = value.strip()
        if _is_generic_absence_fragment(cleaned):
            return ""
        return cleaned
    return value


def _structured_prompt_for_image_model(structured: dict[str, Any]) -> dict[str, Any]:
    """Return the compact JSON variant shown to users and copied into prompt fields."""
    output = copy.deepcopy(structured or {})
    prompt = str(output.get("prompt") or "").strip()
    if prompt:
        prompt_key = re.sub(r"[\s，,。.;；:：]+", "", prompt).lower()
        details = _coerce_text_list(output.get("important_details"))
        output["important_details"] = [
            item
            for item in details
            if re.sub(r"[\s，,。.;；:：]+", "", item).lower() != prompt_key
        ]
    visual_keys = (
        "subject",
        "subject_attributes",
        "action",
        "pose_details",
        "hand_details",
        "foot_details",
        "joint_body_mechanics",
        "facial_expression_details",
        "occlusion_crop_details",
        "exposed_body_details",
        "intimate_body_details",
        "sexual_act_details",
        "genital_details",
        "fluid_contact_details",
        "nsfw_content_details",
        "content_safety_labels",
        "scene",
        "foreground",
        "midground",
        "background",
        "composition",
        "camera_lens",
        "lighting",
        "style",
        "color_palette",
        "mood_atmosphere",
        "materials_textures",
        "clothing_accessories",
        "environment_objects",
        "important_details",
        "visible_text",
        "quality_notes",
        "constraints",
        "negative_prompt",
    )
    visual_field_count = 0
    for key in visual_keys:
        value = output.get(key)
        if isinstance(value, str) and value.strip():
            visual_field_count += 1
        elif isinstance(value, list) and any(str(item).strip() for item in value):
            visual_field_count += 1
    if visual_field_count >= 2:
        output.pop("prompt", None)
    return _prune_empty_prompt_value(output)


def _prompt_fragment_key(text: str) -> str:
    return re.sub(r"[\s，,。.;；:：、/|()（）【】\\[\\]{}\"'“”‘’]+", "", str(text or "")).lower()


def _add_prompt_fragment(fragments: list[str], keys: list[str], fragment: str) -> None:
    cleaned = str(fragment or "").strip(" \t\r\n，,。.;；:：、")
    if len(cleaned) < 2:
        return
    key = _prompt_fragment_key(cleaned)
    if not key:
        return
    for idx, existing_key in enumerate(keys):
        if key == existing_key or key in existing_key:
            return
        if existing_key in key:
            fragments[idx] = cleaned
            keys[idx] = key
            return
    fragments.append(cleaned)
    keys.append(key)


def _field_to_prompt_fragments(value: Any, *, split: bool = True) -> list[str]:
    if isinstance(value, list):
        raw_items = [str(item) for item in value]
    else:
        raw_items = [str(value or "")]
    fragments: list[str] = []
    for item in raw_items:
        if not split:
            part = item.strip()
            if part and not _is_generic_absence_fragment(part):
                fragments.append(part)
            continue
        for part in re.split(r"[，,；;、\n]+", item):
            part = part.strip()
            if part and not _is_generic_absence_fragment(part):
                fragments.append(part)
    return fragments


GENERIC_ABSENCE_KEYS = {
    "无",
    "暂无",
    "没有",
    "不可见",
    "看不见",
    "未可见",
    "未显示",
    "不显示",
    "画面外",
    "被裁切",
    "不清晰",
    "细节不清晰",
    "不可见画面外",
    "不可见不可见",
    "无无",
    "none",
    "na",
    "n/a",
    "notvisible",
    "notshown",
    "outofframe",
    "croppedout",
}


def _is_generic_absence_fragment(text: str) -> bool:
    normalized = _prompt_fragment_key(str(text or "").replace("/", "").replace("|", ""))
    return normalized in GENERIC_ABSENCE_KEYS


NEGATIVE_PROMPT_FRAGMENT_RE = re.compile(
    r"^(?:不要|避免|禁止|不能|不可|别|勿|无|不出现|不得|no\b|avoid\b|without\b|do\s+not\b|don't\b|never\b)",
    re.IGNORECASE,
)

NEGATIVE_PROMPT_DIRECTIVE_RE = re.compile(
    r"^\s*(?:"
    r"不要|避免|禁止|不能|不可|别|勿|请勿|不得|不出现|"
    r"no\b|avoid\b|without\b|do\s+not\b|don't\b|never\b"
    r")\s*(?:"
    r"出现|生成|新增|添加|加入|写成|误写成|误判成|描述成|描述为|写|露出|改变|"
    r"appear(?:ing)?|add(?:ing)?|include|generate|show|describe(?:\s+as)?|depict(?:\s+as)?|change"
    r")?\s*",
    re.IGNORECASE,
)


def _is_negative_prompt_fragment(text: str) -> bool:
    return bool(NEGATIVE_PROMPT_FRAGMENT_RE.search(str(text or "").strip()))


def normalize_negative_prompt_fragment(text: str) -> str:
    """Convert imperative negative instructions into image-model negative tags."""
    cleaned = str(text or "").strip(" \t\r\n，,。.;；:：、")
    if not cleaned:
        return ""
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = NEGATIVE_PROMPT_DIRECTIVE_RE.sub("", cleaned).strip(" \t\r\n，,。.;；:：、")
    cleaned = re.sub(r"^(?:as|成|为)\s*", "", cleaned, flags=re.IGNORECASE).strip(" \t\r\n，,。.;；:：、")
    return cleaned


def _negative_prompt_items_from_structured(structured: dict[str, Any]) -> list[str]:
    items: list[str] = []
    keys: list[str] = []
    compact = _structured_prompt_for_image_model(structured)
    for value in _coerce_text_list(compact.get("negative_prompt")):
        _add_prompt_fragment(items, keys, normalize_negative_prompt_fragment(value))
    for value in _coerce_text_list(compact.get("constraints")):
        if _is_negative_prompt_fragment(value):
            _add_prompt_fragment(items, keys, normalize_negative_prompt_fragment(value))
    return items


def _negative_prompt_from_structured(structured: dict[str, Any]) -> str:
    return "，".join(_negative_prompt_items_from_structured(structured)).strip()


def _plain_prompt_from_structured(structured: dict[str, Any]) -> str:
    """Build the plain keyword prompt from the same cleaned JSON fields."""
    compact = _structured_prompt_for_image_model(structured)
    order = (
        "subject",
        "subject_attributes",
        "action",
        "pose_details",
        "hand_details",
        "foot_details",
        "joint_body_mechanics",
        "facial_expression_details",
        "occlusion_crop_details",
        "exposed_body_details",
        "intimate_body_details",
        "sexual_act_details",
        "genital_details",
        "fluid_contact_details",
        "nsfw_content_details",
        "content_safety_labels",
        "scene",
        "foreground",
        "midground",
        "background",
        "composition",
        "camera_lens",
        "lighting",
        "style",
        "color_palette",
        "mood_atmosphere",
        "materials_textures",
        "clothing_accessories",
        "environment_objects",
        "important_details",
        "visible_text",
        "quality_notes",
        "constraints",
    )
    fragments: list[str] = []
    keys: list[str] = []
    keep_whole_keys = {
        "pose_details",
        "hand_details",
        "foot_details",
        "joint_body_mechanics",
        "facial_expression_details",
        "occlusion_crop_details",
        "exposed_body_details",
        "intimate_body_details",
        "sexual_act_details",
        "genital_details",
        "fluid_contact_details",
        "nsfw_content_details",
    }
    for key in order:
        raw_value = compact.get(key)
        if key == "constraints":
            raw_value = [item for item in _coerce_text_list(raw_value) if not _is_negative_prompt_fragment(item)]
        for fragment in _field_to_prompt_fragments(raw_value, split=key not in keep_whole_keys):
            _add_prompt_fragment(fragments, keys, fragment)
    return "，".join(fragments).strip()


def _prompt_richness_score(prompt: str) -> int:
    fragments = [part.strip() for part in re.split(r"[，,；;、\n]+", str(prompt or "")) if part.strip()]
    return len({_prompt_fragment_key(part) for part in fragments if _prompt_fragment_key(part)})


def parse_prompt_optimizer_output(text: str, cleaned_prompt: str) -> dict[str, Any]:
    """Parse the optimizer result into compatible plain text plus a JSON prompt."""
    normalized = _normalize_optimized_text(text)
    parsed = _extract_json_object(normalized)
    if isinstance(parsed, dict):
        structured_source = parsed.get("structured_prompt")
        if not isinstance(structured_source, dict):
            structured_source = parsed
        optimized = str(
            parsed.get("keyword_prompt")
            or parsed.get("plain_prompt")
            or parsed.get("optimized_prompt")
            or parsed.get("prompt")
            or (structured_source.get("prompt") if isinstance(structured_source, dict) else "")
            or normalized
        ).strip()
        structured = _normalize_structured_prompt(structured_source, cleaned_prompt, optimized)
        structured_plain = _plain_prompt_from_structured(structured)
        if structured_plain and _prompt_richness_score(structured_plain) > _prompt_richness_score(optimized):
            optimized = structured_plain
    else:
        optimized = normalized
        structured = _normalize_structured_prompt({}, cleaned_prompt, optimized)
    return {
        "optimized_prompt": optimized,
        "negative_prompt": _negative_prompt_from_structured(structured),
        "structured_prompt": structured,
        "structured_prompt_json": json.dumps(_structured_prompt_for_image_model(structured), ensure_ascii=False, indent=2),
    }


VIDEO_REFERENCE_CLAUSE_RE = re.compile(r"@[图片图像视频音频素材][\w\d０-９一二三四五六七八九十\-—~～至到、,，]*")
VIDEO_DURATION_PARAM_RE = re.compile(r"(?:^|[，,；;\s])(?:时长\s*)?\d+(?:\.\d+)?\s*(?:秒|s)\s*$", re.IGNORECASE)
VIDEO_ASPECT_PARAM_RE = re.compile(r"^(?:画幅|比例|宽高比|aspect\s*ratio)?\s*\d+\s*[:：]\s*\d+\s*$", re.IGNORECASE)
VIDEO_NEGATIVE_TERMS_RE = re.compile(
    r"(?:文字|字幕|logo|LOGO|水印|风格漂移|角色变脸|变脸|畸变|崩坏)",
    re.IGNORECASE,
)
VIDEO_AUDIO_TERMS_RE = re.compile(r"(?:@音频|音频|环境音|声音|音效|配乐|音乐|钢琴音|爵士|旁白)")


def _sanitize_video_script_prompt(prompt: str) -> str:
    """Remove UI-controlled or unsupported clauses from video script optimizer output."""
    text = str(prompt or "").strip()
    if not text:
        return ""
    parts = [part.strip() for part in re.split(r"[，,；;\n]+", text) if part.strip()]
    kept: list[str] = []
    for part in parts:
        clause = part.strip()
        bare_clause = clause.strip(" 。.，,；;")
        if not clause:
            continue
        if VIDEO_REFERENCE_CLAUSE_RE.search(bare_clause):
            continue
        if VIDEO_AUDIO_TERMS_RE.search(bare_clause):
            continue
        if VIDEO_ASPECT_PARAM_RE.match(bare_clause):
            continue
        if VIDEO_DURATION_PARAM_RE.search("，" + bare_clause):
            continue
        if re.match(r"^(?:禁止|不要|避免|无|不能|不得)", bare_clause) and VIDEO_NEGATIVE_TERMS_RE.search(bare_clause):
            continue
        if "硬性动作冲突" in bare_clause:
            continue
        kept.append(bare_clause)
    if not kept:
        return text
    return "，".join(kept).strip(" ，,；;。.") + "。"


def parse_video_script_optimizer_output(text: str, cleaned_prompt: str) -> dict[str, Any]:
    """Parse the video-script optimizer result without creating image JSON variants."""
    optimized = _normalize_optimized_text(text)
    parsed = _extract_json_object(optimized)
    if isinstance(parsed, dict):
        optimized = str(
            parsed.get("video_script")
            or parsed.get("script")
            or parsed.get("optimized_prompt")
            or parsed.get("prompt")
            or optimized
        ).strip()
    optimized = _sanitize_video_script_prompt(optimized)
    return {
        "optimized_prompt": optimized,
        "cleaned_prompt": cleaned_prompt,
        "prompt_mode": "video_script",
    }


def _remove_inline_english_prompt(text: str) -> str:
    """Drop an accidental full English prompt while preserving short technical terms."""
    cleaned = str(text or "").strip()
    if not cleaned or not CHINESE_RE.search(cleaned):
        return cleaned
    match = ENGLISH_SENTENCE_RE.search(cleaned)
    if not match:
        return cleaned
    return cleaned[: match.start()].rstrip(" ，,；;。") + ("。" if cleaned[: match.start()].strip() else "")


def normalize_translated_prompt(text: str) -> str:
    """Normalize Qwen translation output so the Chinese slot does not become bilingual."""
    cleaned = _normalize_optimized_text(text)
    if not cleaned:
        return ""
    cleaned = BILINGUAL_LABEL_RE.sub("", cleaned).strip()
    lines = []
    for raw_line in re.split(r"[\r\n]+", cleaned):
        line = raw_line.strip()
        if not line:
            continue
        if CHINESE_RE.search(line):
            line = _remove_inline_english_prompt(line).strip()
            if line:
                lines.append(line)
            continue
        if ENGLISH_SENTENCE_RE.search(line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _merge_json_translation_shape(source: Any, translated: Any) -> Any:
    if isinstance(source, dict):
        translated_dict = translated if isinstance(translated, dict) else {}
        merged: dict[str, Any] = {}
        for key, source_value in source.items():
            if key in translated_dict:
                merged[key] = _merge_json_translation_shape(source_value, translated_dict.get(key))
            else:
                merged[key] = source_value
        for key, translated_value in translated_dict.items():
            if key not in merged:
                merged[key] = translated_value
        return merged
    if isinstance(source, list):
        translated_list = translated if isinstance(translated, list) else []
        merged_items: list[Any] = []
        for idx, source_value in enumerate(source):
            if idx < len(translated_list):
                merged_items.append(_merge_json_translation_shape(source_value, translated_list[idx]))
            else:
                merged_items.append(source_value)
        return merged_items
    if isinstance(translated, str):
        return translated.strip() or source
    return translated if translated not in (None, "", [], {}) else source


def _collect_json_string_leaves(value: Any, path: tuple[Any, ...] = ()) -> list[tuple[tuple[Any, ...], str]]:
    leaves: list[tuple[tuple[Any, ...], str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            leaves.extend(_collect_json_string_leaves(item, path + (key,)))
        return leaves
    if isinstance(value, list):
        for idx, item in enumerate(value):
            leaves.extend(_collect_json_string_leaves(item, path + (idx,)))
        return leaves
    if isinstance(value, str) and value.strip():
        leaves.append((path, value.strip()))
    return leaves


def _set_json_path_value(root: Any, path: tuple[Any, ...], value: str) -> None:
    current = root
    for part in path[:-1]:
        current = current[part]
    current[path[-1]] = value


def _json_language_switch_payload(leaves: list[tuple[tuple[Any, ...], str]]) -> str:
    payload = {
        "items": [
            {"id": str(idx), "text": text}
            for idx, (_, text) in enumerate(leaves)
        ]
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _extract_translated_leaf_map(text: str) -> dict[str, str]:
    parsed = _extract_json_object(text)
    if not isinstance(parsed, dict):
        return {}
    items = parsed.get("items")
    if not isinstance(items, list):
        return {}
    translated: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") if item.get("id") is not None else "").strip()
        item_text = str(item.get("text") or "").strip()
        if item_id and item_text:
            translated[item_id] = item_text
    return translated


def normalize_language_switch_prompt(text: str, target_language: str, source_prompt: str = "") -> str:
    """Normalize a prompt language switch result for direct insertion into the prompt box."""
    target = "en" if str(target_language or "").lower().startswith("en") else "zh"
    parsed_json = _extract_json_object(text)
    source_json = _extract_json_object(source_prompt)
    if isinstance(parsed_json, dict):
        if isinstance(source_json, dict):
            parsed_json = _merge_json_translation_shape(source_json, parsed_json)
        return json.dumps(parsed_json, ensure_ascii=False, indent=2)
    if isinstance(source_json, dict):
        raise RuntimeError("JSON prompt language switch did not return valid JSON")
    if target == "zh":
        return normalize_translated_prompt(text)
    cleaned = _normalize_optimized_text(text)
    if not cleaned:
        return ""
    cleaned = re.sub(r"^\s*(?:English|英文|Translation|Translated prompt)\s*[:：]\s*", "", cleaned, flags=re.IGNORECASE)
    lines = [line.strip() for line in re.split(r"[\r\n]+", cleaned) if line.strip()]
    cleaned = " ".join(lines).strip()
    cleaned = QUOTE_RE.sub("", cleaned).strip()
    return cleaned


def _submit_language_switch_workflow(
    prompt: str,
    target: str,
    base_url: str,
    comfyui_post: Callable[[str, dict, str | None], dict[str, Any]],
    comfyui_get: Callable[[str, str | None], dict[str, Any]],
    timeout: float,
    poll_interval: float,
    max_new_tokens: int | None,
) -> tuple[str, str]:
    workflow = build_qwen_prompt_language_switch_workflow(prompt, target, max_new_tokens=max_new_tokens)
    response = comfyui_post(
        "/prompt",
        {"prompt": copy.deepcopy(workflow), "client_id": f"ez-prompt-lang-{uuid.uuid4().hex}"},
        base_url,
    )
    prompt_id = str(response.get("prompt_id") or "")
    if not prompt_id:
        raise RuntimeError("ComfyUI did not return prompt_id for Qwen prompt language switch")

    deadline = time.time() + float(timeout or 90.0)
    while time.time() < deadline:
        history = comfyui_get(f"/history/{prompt_id}", base_url)
        if isinstance(history, dict) and prompt_id in history:
            entry = history[prompt_id]
            status = entry.get("status", {}) if isinstance(entry, dict) else {}
            if status.get("completed", False):
                return extract_show_text(entry, "2"), prompt_id
            if status.get("status_str") == "error":
                messages = status.get("messages", [])
                raise RuntimeError(str(messages)[:300] if messages else "ComfyUI Qwen prompt language switch failed")
        time.sleep(max(0.1, float(poll_interval or 1.0)))
    raise TimeoutError("Qwen prompt language switch timed out")


def _run_json_prompt_language_switcher(
    source_json: dict[str, Any],
    original_text: str,
    target: str,
    base_url: str,
    comfyui_post: Callable[[str, dict, str | None], dict[str, Any]],
    comfyui_get: Callable[[str, str | None], dict[str, Any]],
    timeout: float,
    poll_interval: float,
    max_new_tokens: int | None,
) -> dict[str, Any]:
    leaves = _collect_json_string_leaves(source_json)
    translated_json = copy.deepcopy(source_json)
    prompt_ids: list[str] = []
    translated_by_id: dict[str, str] = {}

    if leaves:
        payload = _json_language_switch_payload(leaves)
        raw_text, prompt_id = _submit_language_switch_workflow(
            payload,
            target,
            base_url,
            comfyui_post,
            comfyui_get,
            timeout=timeout,
            poll_interval=poll_interval,
            max_new_tokens=max_new_tokens,
        )
        prompt_ids.append(prompt_id)
        translated_by_id = _extract_translated_leaf_map(raw_text)

    for idx, (path, source_text) in enumerate(leaves):
        translated = translated_by_id.get(str(idx), "").strip()
        if not translated:
            raw_text, prompt_id = _submit_language_switch_workflow(
                source_text,
                target,
                base_url,
                comfyui_post,
                comfyui_get,
                timeout=timeout,
                poll_interval=poll_interval,
                max_new_tokens=max_new_tokens,
            )
            prompt_ids.append(prompt_id)
            translated = normalize_language_switch_prompt(raw_text, target, source_prompt=source_text)
        if translated:
            _set_json_path_value(translated_json, path, translated)

    translated_prompt = json.dumps(translated_json, ensure_ascii=False, indent=2)
    return {
        "ok": True,
        "provider": "comfyui-qwen3-vl-4b-4bit",
        "prompt_id": ",".join(prompt_ids),
        "original_prompt": original_text,
        "target_language": target,
        "translated_prompt": translated_prompt,
        "prompt_en": translated_prompt if target == "en" else "",
        "prompt_zh": translated_prompt if target == "zh" else "",
        "format": "json",
    }


def normalize_interrogated_chinese_prompt(text: str) -> str:
    """Keep the image-interrogation Chinese tab from mixing in English tag fragments."""
    cleaned = normalize_translated_prompt(text)
    if not cleaned or not CHINESE_RE.search(cleaned):
        return cleaned
    lines = []
    for raw_line in re.split(r"[\r\n]+", cleaned):
        line = raw_line.strip()
        if not line or not CHINESE_RE.search(line):
            continue
        line = TRAILING_ENGLISH_AFTER_SENTENCE_RE.sub(r"\1", line).strip()
        fragments = []
        for part in re.split(r"[，,、；;]", line):
            fragment = part.strip(" \t\r\n，,、；;")
            if not fragment:
                continue
            if not CHINESE_RE.search(fragment):
                if ENGLISH_FRAGMENT_RE.search(fragment):
                    continue
                fragments.append(fragment)
                continue
            fragment = TRAILING_INLINE_ENGLISH_RE.sub("", fragment).strip()
            fragment = fragment.strip(" \t\r\n，,、；;")
            if fragment:
                fragments.append(fragment)
        if fragments:
            lines.append("，".join(fragments))
    return "\n".join(lines).strip()


def _llm_user_text(
    text: str,
    *,
    chat_fn: Callable[..., str] = chat_text,
    model: str | None = None,
    temperature: float = 0.15,
    max_tokens: int = 384,
    timeout: float | None = None,
) -> str:
    return chat_fn(
        [
            {"role": "system", "content": DIRECT_FINAL_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )


def run_llm_prompt_optimizer(
    prompt: str,
    *,
    chat_fn: Callable[..., str] = chat_text,
    timeout: float = 120.0,
    max_new_tokens: int = 384,
    prompt_mode: str = "image",
    prompt_context: dict[str, Any] | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Optimize image/video prompts with the resident local LLM instead of ComfyUI."""
    cleaned = clean_user_prompt(prompt)
    mode = "video_script" if str(prompt_mode or "").lower() in {"video", "video_script", "script"} else "image"
    tokens = max(96, min(int(max_new_tokens or 384), 4096))
    if mode == "video_script":
        llm_prompt = QWEN_VIDEO_SCRIPT_OPTIMIZER_TEMPLATE.format(
            prompt=cleaned,
            optimization_guide=VIDEO_SCRIPT_OPTIMIZATION_GUIDE,
            timing_context=_video_script_timing_context_text(prompt_context),
        )
    else:
        llm_prompt = QWEN_OPTIMIZER_TEMPLATE.format(
            prompt=cleaned,
            reference_context=_known_reference_context(cleaned),
            optimization_guide=IMAGE_PROMPT_OPTIMIZATION_GUIDE,
            json_schema=STRUCTURED_PROMPT_JSON_SCHEMA,
        )
    raw_text = _llm_user_text(
        llm_prompt,
        chat_fn=chat_fn,
        model=model,
        temperature=0.15 if mode == "video_script" else 0.2,
        max_tokens=tokens,
        timeout=timeout,
    )
    parsed = (
        parse_video_script_optimizer_output(raw_text, cleaned)
        if mode == "video_script"
        else parse_prompt_optimizer_output(raw_text, cleaned)
    )
    if not parsed.get("optimized_prompt"):
        raise RuntimeError("LLM prompt optimization completed without text output")
    return {
        "ok": True,
        "provider": llm_provider_name(model),
        "prompt_id": "",
        "original_prompt": str(prompt or ""),
        "cleaned_prompt": cleaned,
        "prompt_mode": mode,
        **parsed,
    }


def run_llm_prompt_translator(
    prompt: str,
    *,
    chat_fn: Callable[..., str] = chat_text,
    timeout: float = 90.0,
    max_new_tokens: int = 192,
    model: str | None = None,
) -> dict[str, Any]:
    """Translate an image prompt into Chinese with the resident local LLM."""
    text = str(prompt or "").strip()
    if not text:
        return {"ok": False, "provider": llm_provider_name(model), "prompt_zh": ""}
    raw_text = _llm_user_text(
        QWEN_TRANSLATE_TEMPLATE.format(prompt=text),
        chat_fn=chat_fn,
        model=model,
        temperature=0.15,
        max_tokens=max(96, min(int(max_new_tokens or 192), 4096)),
        timeout=timeout,
    )
    translated = normalize_translated_prompt(raw_text)
    if translated:
        return {
            "ok": True,
            "provider": llm_provider_name(model),
            "prompt_id": "",
            "original_prompt": text,
            "prompt_zh": translated,
        }
    raise RuntimeError("LLM prompt translation completed without text output")


def _submit_llm_language_switch(
    prompt: str,
    target: str,
    *,
    chat_fn: Callable[..., str] = chat_text,
    timeout: float = 90.0,
    max_new_tokens: int | None = None,
    model: str | None = None,
) -> str:
    prompt = _bounded_user_prompt(prompt)
    return _llm_user_text(
        QWEN_LANGUAGE_SWITCH_TEMPLATE.format(
            prompt=prompt,
            target_language_name="English" if target == "en" else "Chinese",
        ),
        chat_fn=chat_fn,
        model=model,
        temperature=0.15,
        max_tokens=max(96, min(int(max_new_tokens or 256), 4096)),
        timeout=timeout,
    )


def _run_llm_json_prompt_language_switcher(
    source_json: dict[str, Any],
    original_text: str,
    target: str,
    *,
    chat_fn: Callable[..., str] = chat_text,
    timeout: float = 90.0,
    max_new_tokens: int | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    leaves = _collect_json_string_leaves(source_json)
    translated_json = copy.deepcopy(source_json)
    translated_by_id: dict[str, str] = {}
    if leaves:
        payload = _json_language_switch_payload(leaves)
        target_name = "English" if target == "en" else "Chinese"
        raw_text = _llm_user_text(
            "Translate every items[].text value into "
            f"{target_name}. Return only a valid JSON object with the same shape "
            '{"items":[{"id":"0","text":"..."}]}. Preserve every id. Do not add '
            f"explanations or markdown.\n\n{payload}",
            chat_fn=chat_fn,
            model=model,
            temperature=0.15,
            max_tokens=max(256, min(int(max_new_tokens or 1024), 4096)),
            timeout=timeout,
        )
        translated_by_id = _extract_translated_leaf_map(raw_text)

    for idx, (path, source_text) in enumerate(leaves):
        translated = translated_by_id.get(str(idx), "").strip()
        if not translated:
            raw_text = _submit_llm_language_switch(
                source_text,
                target,
                chat_fn=chat_fn,
                timeout=timeout,
                max_new_tokens=max_new_tokens,
                model=model,
            )
            translated = normalize_language_switch_prompt(raw_text, target, source_prompt=source_text)
        if translated:
            _set_json_path_value(translated_json, path, translated)

    translated_prompt = json.dumps(translated_json, ensure_ascii=False, indent=2)
    return {
        "ok": True,
        "provider": llm_provider_name(model),
        "prompt_id": "",
        "original_prompt": original_text,
        "target_language": target,
        "translated_prompt": translated_prompt,
        "prompt_en": translated_prompt if target == "en" else "",
        "prompt_zh": translated_prompt if target == "zh" else "",
        "format": "json",
    }


def run_llm_prompt_language_switcher(
    prompt: str,
    target_language: str,
    *,
    chat_fn: Callable[..., str] = chat_text,
    timeout: float = 90.0,
    max_new_tokens: int = 256,
    model: str | None = None,
) -> dict[str, Any]:
    """Translate a prompt between Chinese and English with the resident local LLM."""
    text = _bounded_user_prompt(prompt).strip()
    target = "en" if str(target_language or "").lower().startswith("en") else "zh"
    if not text:
        return {"ok": False, "provider": llm_provider_name(model), "translated_prompt": "", "target_language": target}
    source_json = _extract_json_object(text)
    if isinstance(source_json, dict):
        return _run_llm_json_prompt_language_switcher(
            source_json,
            text,
            target,
            chat_fn=chat_fn,
            timeout=timeout,
            max_new_tokens=max_new_tokens,
            model=model,
        )
    raw_text = _submit_llm_language_switch(
        text,
        target,
        chat_fn=chat_fn,
        timeout=timeout,
        max_new_tokens=max_new_tokens,
        model=model,
    )
    translated = normalize_language_switch_prompt(raw_text, target, source_prompt=text)
    if translated:
        return {
            "ok": True,
            "provider": llm_provider_name(model),
            "prompt_id": "",
            "original_prompt": text,
            "target_language": target,
            "translated_prompt": translated,
            "prompt_en": translated if target == "en" else "",
            "prompt_zh": translated if target == "zh" else "",
        }
    raise RuntimeError("LLM prompt language switch completed without text output")


def run_qwen_prompt_optimizer(
    prompt: str,
    base_url: str,
    comfyui_post: Callable[[str, dict, str | None], dict[str, Any]],
    comfyui_get: Callable[[str, str | None], dict[str, Any]],
    timeout: float = 120.0,
    poll_interval: float = 1.0,
    max_new_tokens: int = 384,
    prompt_mode: str = "image",
    prompt_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit the Qwen3 4B text optimizer workflow to ComfyUI."""
    cleaned = clean_user_prompt(_bounded_user_prompt(prompt))
    mode = "video_script" if str(prompt_mode or "").lower() in {"video", "video_script", "script"} else "image"
    workflow = build_qwen_prompt_optimizer_workflow(
        cleaned,
        max_new_tokens=max_new_tokens,
        prompt_mode=mode,
        prompt_context=prompt_context,
    )
    response = comfyui_post(
        "/prompt",
        {"prompt": copy.deepcopy(workflow), "client_id": f"ez-prompt-qwen-{uuid.uuid4().hex}"},
        base_url,
    )
    prompt_id = str(response.get("prompt_id") or "")
    if not prompt_id:
        raise RuntimeError("ComfyUI did not return prompt_id for Qwen prompt optimization")

    deadline = time.time() + float(timeout or 120.0)
    while time.time() < deadline:
        history = comfyui_get(f"/history/{prompt_id}", base_url)
        if isinstance(history, dict) and prompt_id in history:
            entry = history[prompt_id]
            status = entry.get("status", {}) if isinstance(entry, dict) else {}
            if status.get("completed", False):
                raw_text = extract_show_text(entry, "2")
                parsed = (
                    parse_video_script_optimizer_output(raw_text, cleaned)
                    if mode == "video_script"
                    else parse_prompt_optimizer_output(raw_text, cleaned)
                )
                if parsed["optimized_prompt"]:
                    return {
                        "ok": True,
                        "provider": "comfyui-qwen3-vl-4b-4bit",
                        "prompt_id": prompt_id,
                        "original_prompt": str(prompt or ""),
                        "cleaned_prompt": cleaned,
                        "prompt_mode": mode,
                        **parsed,
                    }
                raise RuntimeError("ComfyUI Qwen prompt optimization completed without text output")
            if status.get("status_str") == "error":
                messages = status.get("messages", [])
                raise RuntimeError(str(messages)[:300] if messages else "ComfyUI Qwen prompt optimization failed")
        time.sleep(max(0.1, float(poll_interval or 1.0)))
    raise TimeoutError("Qwen prompt optimization timed out")


def run_prompt_translator(
    prompt: str,
    base_url: str,
    comfyui_post: Callable[[str, dict, str | None], dict[str, Any]],
    comfyui_get: Callable[[str, str | None], dict[str, Any]],
    timeout: float = 90.0,
    poll_interval: float = 1.0,
    max_new_tokens: int = 192,
) -> dict[str, Any]:
    """Translate an image prompt into Chinese with the same lightweight local Qwen workflow."""
    text = _bounded_user_prompt(prompt).strip()
    if not text:
        return {"ok": False, "provider": "comfyui-qwen3-vl-4b-4bit", "prompt_zh": ""}
    workflow = build_qwen_prompt_translator_workflow(text, max_new_tokens=max_new_tokens)
    response = comfyui_post(
        "/prompt",
        {"prompt": copy.deepcopy(workflow), "client_id": f"ez-prompt-zh-{uuid.uuid4().hex}"},
        base_url,
    )
    prompt_id = str(response.get("prompt_id") or "")
    if not prompt_id:
        raise RuntimeError("ComfyUI did not return prompt_id for Qwen prompt translation")

    deadline = time.time() + float(timeout or 90.0)
    while time.time() < deadline:
        history = comfyui_get(f"/history/{prompt_id}", base_url)
        if isinstance(history, dict) and prompt_id in history:
            entry = history[prompt_id]
            status = entry.get("status", {}) if isinstance(entry, dict) else {}
            if status.get("completed", False):
                translated = normalize_translated_prompt(extract_show_text(entry, "2"))
                if translated:
                    return {
                        "ok": True,
                        "provider": "comfyui-qwen3-vl-4b-4bit",
                        "prompt_id": prompt_id,
                        "original_prompt": text,
                        "prompt_zh": translated,
                    }
                raise RuntimeError("ComfyUI Qwen prompt translation completed without text output")
            if status.get("status_str") == "error":
                messages = status.get("messages", [])
                raise RuntimeError(str(messages)[:300] if messages else "ComfyUI Qwen prompt translation failed")
        time.sleep(max(0.1, float(poll_interval or 1.0)))
    raise TimeoutError("Qwen prompt translation timed out")


def run_prompt_language_switcher(
    prompt: str,
    target_language: str,
    base_url: str,
    comfyui_post: Callable[[str, dict, str | None], dict[str, Any]],
    comfyui_get: Callable[[str, str | None], dict[str, Any]],
    timeout: float = 90.0,
    poll_interval: float = 1.0,
    max_new_tokens: int = 256,
) -> dict[str, Any]:
    """Translate a prompt between Chinese and English with the local Qwen prompt instance."""
    text = _bounded_user_prompt(prompt).strip()
    target = "en" if str(target_language or "").lower().startswith("en") else "zh"
    if not text:
        return {"ok": False, "provider": "comfyui-qwen3-vl-4b-4bit", "translated_prompt": "", "target_language": target}
    source_json = _extract_json_object(text)
    if isinstance(source_json, dict):
        return _run_json_prompt_language_switcher(
            source_json,
            text,
            target,
            base_url,
            comfyui_post,
            comfyui_get,
            timeout=timeout,
            poll_interval=poll_interval,
            max_new_tokens=max_new_tokens,
        )

    raw_text, prompt_id = _submit_language_switch_workflow(
        text,
        target,
        base_url,
        comfyui_post,
        comfyui_get,
        timeout=timeout,
        poll_interval=poll_interval,
        max_new_tokens=max_new_tokens,
    )
    translated = normalize_language_switch_prompt(raw_text, target, source_prompt=text)
    if translated:
        return {
            "ok": True,
            "provider": "comfyui-qwen3-vl-4b-4bit",
            "prompt_id": prompt_id,
            "original_prompt": text,
            "target_language": target,
            "translated_prompt": translated,
            "prompt_en": translated if target == "en" else "",
            "prompt_zh": translated if target == "zh" else "",
        }
    raise RuntimeError("ComfyUI Qwen prompt language switch completed without text output")


def run_prompt_optimizer(
    prompt: str,
    base_url: str,
    comfyui_post: Callable[[str, dict, str | None], dict[str, Any]],
    comfyui_get: Callable[[str, str | None], dict[str, Any]],
    timeout: float = 120.0,
    poll_interval: float = 1.0,
    max_new_tokens: int = 384,
    prompt_mode: str = "image",
    prompt_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Default optimizer: Chinese-aware Qwen3 4B workflow."""
    return run_qwen_prompt_optimizer(
        prompt,
        base_url,
        comfyui_post,
        comfyui_get,
        timeout=timeout,
        poll_interval=poll_interval,
        max_new_tokens=max_new_tokens,
        prompt_mode=prompt_mode,
        prompt_context=prompt_context,
    )


def run_superprompt_optimizer(
    prompt: str,
    base_url: str,
    comfyui_post: Callable[[str, dict, str | None], dict[str, Any]],
    comfyui_get: Callable[[str, str | None], dict[str, Any]],
    timeout: float = 120.0,
    poll_interval: float = 1.0,
    max_new_tokens: int = 192,
) -> dict[str, Any]:
    """Submit the lightweight optimizer workflow to ComfyUI and return text results."""
    cleaned = clean_user_prompt(_bounded_user_prompt(prompt))
    workflow = build_superprompt_workflow(cleaned, max_new_tokens=max_new_tokens)
    workflow_for_submit = copy.deepcopy(workflow)
    response = comfyui_post(
        "/prompt",
        {"prompt": workflow_for_submit, "client_id": f"ez-prompt-opt-{uuid.uuid4().hex}"},
        base_url,
    )
    prompt_id = str(response.get("prompt_id") or "")
    if not prompt_id:
        raise RuntimeError("ComfyUI did not return prompt_id for prompt optimization")

    deadline = time.time() + float(timeout or 120.0)
    last_status = ""
    while time.time() < deadline:
        history = comfyui_get(f"/history/{prompt_id}", base_url)
        if isinstance(history, dict) and prompt_id in history:
            entry = history[prompt_id]
            status = entry.get("status", {}) if isinstance(entry, dict) else {}
            if status.get("completed", False):
                parsed = parse_prompt_optimizer_output(extract_show_text(entry, "3"), cleaned)
                if parsed["optimized_prompt"]:
                    return {
                        "ok": True,
                        "provider": "comfyui-superprompt",
                        "prompt_id": prompt_id,
                        "original_prompt": str(prompt or ""),
                        "cleaned_prompt": cleaned,
                        **parsed,
                    }
                raise RuntimeError("ComfyUI prompt optimization completed without text output")
            if status.get("status_str") == "error":
                messages = status.get("messages", [])
                raise RuntimeError(str(messages)[:300] if messages else "ComfyUI prompt optimization failed")
            last_status = str(status.get("status_str") or last_status)
        time.sleep(max(0.1, float(poll_interval or 1.0)))
    raise TimeoutError(f"Prompt optimization timed out ({last_status or 'no history'})")
