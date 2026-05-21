"""Prompt optimization helpers backed by lightweight ComfyUI text workflows."""

from __future__ import annotations

import copy
import ast
import json
import re
import time
import uuid
from typing import Any, Callable


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
    "tag soup, and do not invent major new concepts. The plain-text variant should be "
    "one fluent generation prompt in the user's language, with no markdown, headings, "
    "bullets, or explanation."
)

STRUCTURED_PROMPT_JSON_SCHEMA = (
    "Return only a valid JSON object with this exact top-level shape: "
    '{"keyword_prompt":"...",'
    '"structured_prompt":{"subject":"...","action":"...","scene":"...",'
    '"composition":"...","lighting":"...","style":"...","color_palette":"...",'
    '"materials_textures":[],"important_details":[],"visible_text":[],"constraints":[],'
    '"negative_prompt":[]}}. '
    "The keyword_prompt is the compact plain prompt. The structured_prompt is the JSON prompt "
    "that can be copied directly to an image model. Do not include metadata keys such as "
    "version, language, or intent. Do not repeat the full keyword_prompt inside structured_prompt "
    "when subject/action/scene/composition fields already describe the image. Omit fields that are "
    "unknown, empty strings, or empty arrays. Keep the user's language unless the user explicitly asks otherwise."
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
    cleaned = clean_user_prompt(prompt)
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
) -> dict[str, dict[str, Any]]:
    """Build a Qwen3-VL text-only workflow for Chinese-aware prompt cleanup."""
    cleaned = clean_user_prompt(prompt)
    tokens = max(128, min(int(max_new_tokens or 128), 4096))
    reference_context = _known_reference_context(cleaned)
    return {
        "1": {
            "inputs": {
                "text": QWEN_OPTIMIZER_TEMPLATE.format(
                    prompt=cleaned,
                    reference_context=reference_context,
                    optimization_guide=IMAGE_PROMPT_OPTIMIZATION_GUIDE,
                    json_schema=STRUCTURED_PROMPT_JSON_SCHEMA,
                ),
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
            "_meta": {"title": "Qwen Prompt Optimizer"},
        },
        "2": {
            "inputs": {"text": ["1", 0]},
            "class_type": "ShowText|pysssss",
            "_meta": {"title": "Optimized Prompt"},
        },
    }


def build_qwen_prompt_translator_workflow(
    prompt: str,
    max_new_tokens: int = 192,
    keep_model_loaded: bool = True,
) -> dict[str, dict[str, Any]]:
    """Build a Qwen3-VL text-only workflow that translates image prompts to Chinese."""
    text = str(prompt or "").strip()
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
    text = str(prompt or "").strip()
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
        "subject": str(source.get("subject") or cleaned).strip(),
        "action": str(source.get("action") or "").strip(),
        "scene": str(source.get("scene") or source.get("context") or source.get("setting") or "").strip(),
        "composition": str(source.get("composition") or source.get("framing") or "").strip(),
        "lighting": str(source.get("lighting") or source.get("atmosphere") or "").strip(),
        "style": str(source.get("style") or "").strip(),
        "color_palette": str(source.get("color_palette") or source.get("colors") or "").strip(),
        "materials_textures": _coerce_text_list(source.get("materials_textures") or source.get("textures")),
        "important_details": _coerce_text_list(source.get("important_details") or source.get("details")),
        "visible_text": _coerce_text_list(source.get("visible_text") or source.get("text")),
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
        return value.strip()
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
        "action",
        "scene",
        "composition",
        "lighting",
        "style",
        "color_palette",
        "materials_textures",
        "important_details",
        "visible_text",
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


def _field_to_prompt_fragments(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = [str(item) for item in value]
    else:
        raw_items = [str(value or "")]
    fragments: list[str] = []
    for item in raw_items:
        for part in re.split(r"[，,；;、\n]+", item):
            part = part.strip()
            if part:
                fragments.append(part)
    return fragments


def _plain_prompt_from_structured(structured: dict[str, Any]) -> str:
    """Build the plain keyword prompt from the same cleaned JSON fields."""
    compact = _structured_prompt_for_image_model(structured)
    order = (
        "subject",
        "action",
        "scene",
        "composition",
        "lighting",
        "style",
        "color_palette",
        "materials_textures",
        "important_details",
        "visible_text",
        "constraints",
    )
    fragments: list[str] = []
    keys: list[str] = []
    for key in order:
        for fragment in _field_to_prompt_fragments(compact.get(key)):
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
        if structured_plain and _prompt_richness_score(structured_plain) >= _prompt_richness_score(optimized) + 3:
            optimized = structured_plain
    else:
        optimized = normalized
        structured = _normalize_structured_prompt({}, cleaned_prompt, optimized)
    return {
        "optimized_prompt": optimized,
        "structured_prompt": structured,
        "structured_prompt_json": json.dumps(_structured_prompt_for_image_model(structured), ensure_ascii=False, indent=2),
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


def run_qwen_prompt_optimizer(
    prompt: str,
    base_url: str,
    comfyui_post: Callable[[str, dict, str | None], dict[str, Any]],
    comfyui_get: Callable[[str, str | None], dict[str, Any]],
    timeout: float = 120.0,
    poll_interval: float = 1.0,
    max_new_tokens: int = 384,
) -> dict[str, Any]:
    """Submit the Qwen3 4B text optimizer workflow to ComfyUI."""
    cleaned = clean_user_prompt(prompt)
    workflow = build_qwen_prompt_optimizer_workflow(cleaned, max_new_tokens=max_new_tokens)
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
                parsed = parse_prompt_optimizer_output(extract_show_text(entry, "2"), cleaned)
                if parsed["optimized_prompt"]:
                    return {
                        "ok": True,
                        "provider": "comfyui-qwen3-vl-4b-4bit",
                        "prompt_id": prompt_id,
                        "original_prompt": str(prompt or ""),
                        "cleaned_prompt": cleaned,
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
    text = str(prompt or "").strip()
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
    text = str(prompt or "").strip()
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
    cleaned = clean_user_prompt(prompt)
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
