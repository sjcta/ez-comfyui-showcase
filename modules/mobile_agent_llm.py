"""Optional LLM decision layer for the V5 mobile creator agent."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from modules.mobile_agent import DEFAULT_MOBILE_CREATOR_SETTINGS, ratio_to_dimensions
from modules.prompt_optimizer import clean_user_prompt


_DEFAULT_GGUF_NAME = "gemma-4-E2B-it-Q4_K_M.gguf"
_ALLOWED_ACTIONS = {"chat", "ask_more", "propose_generation"}


class MobileAgentLlmProvider:
    """Small adapter around any chat callable that returns model text."""

    def __init__(self, chat_callable: Callable[[list[dict[str, str]], int], str], provider: str = "custom"):
        self.chat_callable = chat_callable
        self.provider = provider

    def decide(
        self,
        text: str,
        context: dict[str, Any] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        merged_settings = {**DEFAULT_MOBILE_CREATOR_SETTINGS, **(settings or {})}
        timeout_ms = int(merged_settings.get("llm_timeout_ms") or 8000)
        try:
            raw = self.chat_callable(_build_messages(text, context), timeout_ms)
            decision = try_parse_llm_decision(raw)
            if not decision:
                return {
                    "ok": False,
                    "provider": self.provider,
                    "error_code": "llm_invalid_decision",
                    "message": "LLM response did not contain a valid decision object.",
                    "raw": str(raw or "")[:1000],
                    "duration_ms": _elapsed_ms(started),
                }
            return {
                "ok": True,
                "provider": self.provider,
                "decision": decision,
                "raw": str(raw or "")[:1000],
                "duration_ms": _elapsed_ms(started),
            }
        except Exception as exc:
            return {
                "ok": False,
                "provider": self.provider,
                "error_code": "llm_request_failed",
                "message": str(exc),
                "duration_ms": _elapsed_ms(started),
            }


class DisabledMobileAgentLlmProvider:
    def __init__(self, reason: str, provider: str = "none"):
        self.reason = reason
        self.provider = provider

    def decide(self, text: str, context: dict[str, Any] | None = None, settings: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "ok": False,
            "provider": self.provider,
            "error_code": "llm_unavailable",
            "message": self.reason,
            "duration_ms": 0,
        }


class OpenAICompatibleMobileAgentProvider(MobileAgentLlmProvider):
    """Call a local OpenAI-compatible chat server such as llama-server."""

    def __init__(self, base_url: str, model: str, api_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        super().__init__(self._chat, provider="openai_compatible")

    def _chat(self, messages: list[dict[str, str]], timeout_ms: int = 8000) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 360,
            "stream": False,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=max(1, timeout_ms / 1000)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        choices = data.get("choices") if isinstance(data, dict) else []
        first = choices[0] if choices else {}
        message = first.get("message") if isinstance(first, dict) else {}
        return str(message.get("content") or "")


class LlamaCppGgufMobileAgentProvider(MobileAgentLlmProvider):
    """Lazy-load a local GGUF model through llama-cpp-python when available."""

    def __init__(self, model_path: str, n_ctx: int = 4096, n_threads: int | None = None):
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self._llm = None
        super().__init__(self._chat, provider="llama_cpp_gguf")

    def _load(self):
        if self._llm is not None:
            return self._llm
        try:
            from llama_cpp import Llama
        except Exception as exc:
            raise RuntimeError("llama-cpp-python is not installed") from exc
        kwargs: dict[str, Any] = {
            "model_path": self.model_path,
            "n_ctx": self.n_ctx,
            "verbose": False,
        }
        if self.n_threads:
            kwargs["n_threads"] = self.n_threads
        self._llm = Llama(**kwargs)
        return self._llm

    def _chat(self, messages: list[dict[str, str]], timeout_ms: int = 8000) -> str:
        llm = self._load()
        result = llm.create_chat_completion(
            messages=messages,
            temperature=0.2,
            max_tokens=360,
        )
        choices = result.get("choices") if isinstance(result, dict) else []
        first = choices[0] if choices else {}
        message = first.get("message") if isinstance(first, dict) else {}
        return str(message.get("content") or "")


def build_mobile_agent_llm_provider(app_root: str | Path, settings: dict[str, Any] | None = None) -> Any:
    """Build the default provider without making startup depend on LLM availability."""
    settings = settings if isinstance(settings, dict) else {}
    if settings.get("llm_enabled") is False:
        return DisabledMobileAgentLlmProvider("mobile LLM is disabled by system settings")

    configured_provider = str(settings.get("llm_provider") or "").strip()
    base_url = (
        str(settings.get("llm_base_url") or "").strip()
        or os.environ.get("EZ_MOBILE_AGENT_LLM_BASE_URL", "").strip()
    )
    if base_url and configured_provider in ("", "openai_compatible"):
        model = (
            str(settings.get("llm_model") or "").strip()
            or os.environ.get("EZ_MOBILE_AGENT_LLM_MODEL", "").strip()
            or "gemma-4-e2b"
        )
        api_key = str(settings.get("llm_api_key") or "").strip() or os.environ.get("EZ_MOBILE_AGENT_LLM_API_KEY", "").strip()
        return OpenAICompatibleMobileAgentProvider(base_url, model, api_key=api_key)

    model_path = (
        str(settings.get("llm_gguf_model") or "").strip()
        or os.environ.get("EZ_MOBILE_AGENT_GGUF_MODEL", "").strip()
        or build_default_model_path(app_root)
    )
    if not model_path or not os.path.isfile(model_path):
        return DisabledMobileAgentLlmProvider(f"GGUF model not found: {model_path or _DEFAULT_GGUF_NAME}")

    try:
        import llama_cpp  # noqa: F401
    except Exception:
        return DisabledMobileAgentLlmProvider("llama-cpp-python is not installed", provider="llama_cpp_gguf")

    return LlamaCppGgufMobileAgentProvider(
        model_path,
        n_ctx=int(os.environ.get("EZ_MOBILE_AGENT_LLM_CTX", "4096") or 4096),
    )


def build_default_model_path(app_root: str | Path) -> str:
    root = Path(app_root).resolve()
    candidates = [
        root / "model" / _DEFAULT_GGUF_NAME,
        root.parent.parent / "model" / _DEFAULT_GGUF_NAME,
        Path("/Users/ai/projects/ez-comfyui-showcase/model") / _DEFAULT_GGUF_NAME,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return str(candidates[0])


def try_parse_llm_decision(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    for candidate in _json_object_candidates(raw):
        try:
            value = json.loads(candidate)
        except Exception:
            continue
        if not isinstance(value, dict):
            continue
        action = str(value.get("action") or "").strip()
        if action not in _ALLOWED_ACTIONS:
            continue
        value["action"] = action
        value["reply"] = str(value.get("reply") or "").strip()
        value["prompt"] = str(value.get("prompt") or value.get("compiled_prompt") or "").strip()
        value["style"] = str(value.get("style") or "").strip()
        value["aspect_ratio"] = str(value.get("aspect_ratio") or value.get("ratio") or "").strip()
        value["ready"] = bool(value.get("ready") or action == "propose_generation")
        return value
    partial = _parse_partial_json_decision(raw)
    if partial:
        return partial
    loose = _parse_loose_decision(raw)
    if loose:
        return loose
    return None


def response_from_llm_decision(
    llm_result: dict[str, Any],
    text: str,
    settings: dict[str, Any] | None,
    workflow_available: bool = True,
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(llm_result, dict) or not llm_result.get("ok"):
        return None
    decision = llm_result.get("decision")
    if not isinstance(decision, dict):
        return None
    merged_settings = {**DEFAULT_MOBILE_CREATOR_SETTINGS, **(settings or {})}
    context = context if isinstance(context, dict) else {}
    action = str(decision.get("action") or "")
    reply = str(decision.get("reply") or "").strip()
    if action in ("chat", "ask_more"):
        return _chat_response(action, reply, text, merged_settings, llm_result, context)
    if action == "propose_generation":
        return _generation_response(decision, reply, text, merged_settings, workflow_available, llm_result, context)
    return None


def _chat_response(
    action: str,
    reply: str,
    text: str,
    settings: dict[str, Any],
    llm_result: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    selected_style = _normalize_choice("", settings.get("allowed_styles"), "cinematic")
    selected_ratio = _normalize_choice("", settings.get("allowed_ratios"), "1:1")
    dimensions = ratio_to_dimensions(selected_ratio)
    message = reply or "可以，我们先继续聊清楚需求。"
    return {
        "response_type": "chat",
        "intent": "llm_chat" if action == "chat" else "llm_clarify",
        "confidence": 0.82,
        "reason": "llm_decision",
        "question": message,
        "assistant_message": message,
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
        "workflow": "default_text_to_image",
        "resolved_workflow": "",
        "source_result": _source_result(context),
        "needs_confirmation": True,
        "error_code": "",
        "llm_provider": str(llm_result.get("provider") or ""),
        "llm_duration_ms": int(llm_result.get("duration_ms") or 0),
        "options": _options(selected_style, selected_ratio, settings),
        "option_requirements": {"style": False, "aspect_ratio": False},
    }


def _generation_response(
    decision: dict[str, Any],
    reply: str,
    text: str,
    settings: dict[str, Any],
    workflow_available: bool,
    llm_result: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    selected_style = _normalize_choice(decision.get("style"), settings.get("allowed_styles"), "cinematic")
    selected_ratio = _normalize_choice(decision.get("aspect_ratio"), settings.get("allowed_ratios"), "1:1")
    dimensions = ratio_to_dimensions(selected_ratio)
    source_result = _source_result(context)
    is_image_to_image = bool(source_result) and _looks_like_followup_edit(text)
    active_brief = context.get("active_brief") if isinstance(context.get("active_brief"), dict) else {}
    creative_brief = _creative_brief_from_decision(
        decision,
        text,
        selected_style,
        selected_ratio,
        active_brief=active_brief,
        source_result=source_result,
        is_image_to_image=is_image_to_image,
    )
    prompt = creative_brief["final_prompt"]
    workflow_setting = "default_image_to_image_workflow" if is_image_to_image else "default_text_to_image_workflow"
    workflow_name = str(settings.get(workflow_setting) or "").strip()
    workflow_alias = "default_image_to_image" if is_image_to_image else "default_text_to_image"
    error_code = "" if workflow_available else "workflow_unavailable"
    message = reply or "我整理好了，确认后开始生成。"
    return {
        "response_type": "confirm" if not error_code else "chat",
        "intent": "image_to_image" if is_image_to_image else "text_to_image",
        "confidence": 0.88,
        "reason": "llm_decision",
        "question": message if error_code else "",
        "assistant_message": message,
        "missing_slots": [],
        "draft_requirement": {
            "subject": prompt,
            "scene": "",
            "style": selected_style,
            "aspect_ratio": selected_ratio,
            "prompt_text": prompt,
            "ready": True,
        },
        "raw_text": str(text or ""),
        "display_summary": prompt,
        "compiled_prompt": prompt,
        "creative_brief": creative_brief,
        "style": selected_style,
        "aspect_ratio": selected_ratio,
        "width": dimensions["width"],
        "height": dimensions["height"],
        "workflow": workflow_alias,
        "resolved_workflow": workflow_name if not error_code else "",
        "source_result": source_result,
        "needs_confirmation": True,
        "error_code": error_code,
        "llm_provider": str(llm_result.get("provider") or ""),
        "llm_duration_ms": int(llm_result.get("duration_ms") or 0),
        "options": _options(selected_style, selected_ratio, settings),
        "option_requirements": {"style": False, "aspect_ratio": False},
    }


def _clean_generation_prompt(value: Any, active_brief: dict[str, Any] | None = None, edit_text: Any = "") -> str:
    raw = str(value or "").strip()
    cleaned = clean_user_prompt(raw).strip()
    cleaned = _strip_request_prefix(cleaned)
    cleaned = re.sub(r"[，,、\s]+$", "", cleaned).strip()
    active = active_brief if isinstance(active_brief, dict) else {}
    previous_prompt = str(active.get("compiled_prompt") or active.get("display_summary") or "").strip()
    edit = clean_user_prompt(str(edit_text or "")).strip()
    if previous_prompt and edit and _looks_like_followup_edit(edit):
        edit_clean = _strip_edit_prefix(edit)
        if edit_clean and edit_clean not in previous_prompt:
            return f"{previous_prompt}，{edit_clean}"
    return cleaned or previous_prompt or raw


def _creative_brief_from_decision(
    decision: dict[str, Any],
    text: str,
    style: str,
    aspect_ratio: str,
    active_brief: dict[str, Any] | None = None,
    source_result: dict[str, Any] | None = None,
    is_image_to_image: bool = False,
) -> dict[str, Any]:
    source = source_result if isinstance(source_result, dict) else {}
    active = active_brief if isinstance(active_brief, dict) else {}
    prompt = _clean_generation_prompt(
        decision.get("final_prompt") or decision.get("prompt") or text,
        active_brief=active,
        edit_text=text if is_image_to_image else "",
    )
    edit_instruction = _strip_edit_prefix(text) if is_image_to_image else str(decision.get("edit_instruction") or "").strip()
    source_image = str(source.get("image") or source.get("thumb") or source.get("filename") or "").strip()
    return {
        "task_type": "image_to_image" if is_image_to_image else "text_to_image",
        "subject": _brief_value(decision, "subject", prompt),
        "scene": _brief_value(decision, "scene", ""),
        "style": style,
        "lighting": _brief_value(decision, "lighting", ""),
        "composition": _brief_value(decision, "composition", ""),
        "mood": _brief_value(decision, "mood", ""),
        "negative": _brief_value(decision, "negative", ""),
        "edit_instruction": edit_instruction,
        "source_image": source_image,
        "final_prompt": prompt,
        "aspect_ratio": aspect_ratio,
    }


def _brief_value(decision: dict[str, Any], key: str, fallback: str = "") -> str:
    value = decision.get(key)
    if isinstance(value, (list, tuple)):
        value = "，".join(str(item).strip() for item in value if str(item).strip())
    return str(value or fallback or "").strip()


def _strip_request_prefix(text: str) -> str:
    value = str(text or "").strip()
    prefixes = (
        r"^(?:请|麻烦)?(?:帮我|给我|替我)?(?:我想要?|我希望|我要|想要)?",
        r"^(?:请|麻烦)?(?:帮我|给我|替我)?(?:生成|出|做|画|绘制|制作)(?:一张|一个|一下)?(?:图片|照片|图像|图|画面)?",
        r"^(?:请|麻烦)?(?:帮我|给我|替我)?(?:一张|一个)(?:图片|照片|图像|图|画面)?",
    )
    previous = None
    while previous != value:
        previous = value
        for pattern in prefixes:
            value = re.sub(pattern, "", value).strip(" ，,、")
    return _strip_edit_prefix(value)


def _strip_edit_prefix(text: Any) -> str:
    value = clean_user_prompt(str(text or "")).strip()
    value = re.sub(
        r"^(?:请|麻烦)?(?:帮我|给我|替我)?(?:把|将)?(?:这张|这幅|这个|刚才的|上一张)?(?:图片|照片|图|画面)?",
        "",
        value,
    ).strip(" ，,、")
    value = re.sub(r"^(?:改成|改为|变成|换成|调整为|修改为|改|换)", "", value).strip(" ，,、")
    return value


def _looks_like_followup_edit(text: Any) -> bool:
    raw = str(text or "").lower()
    return any(token in raw for token in ("改", "换", "变成", "调整", "修改", "更", "亮", "暗", "背景", "风格"))


def _build_messages(text: str, context: dict[str, Any] | None) -> list[dict[str, str]]:
    context = context if isinstance(context, dict) else {}
    history = []
    for msg in context.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        role = "assistant" if msg.get("role") == "assistant" else "user"
        value = str(msg.get("text") or "").strip()
        if value:
            history.append({"role": role, "content": value})
    current_text = str(text or "").strip()
    if history and history[-1]["role"] == "user" and history[-1]["content"].strip() == current_text:
        history = history[:-1]
    memory_block = _context_memory_block(context)
    system = (
        "你是 Ez ComfyUI V5 手机端创作助手。先自然聊天并理解用户需求，只有当画面需求已经足够明确时，"
        "才把 action 设为 propose_generation。不要把普通问候、常识问题、泛泛聊天强行转成出图。"
        "你必须结合上下文记忆理解省略指代，例如“改成雨夜”“继续刚才那个”“再来一张”通常指上一版创作方案或上一张生成结果。"
        "如果用户是在追问普通问题，就自然回答，不要因为历史里有画面方案就强行出图。"
        "输出必须是单个 JSON 对象，不要 markdown。字段："
        "action=chat|ask_more|propose_generation, reply, ready, prompt, subject, scene, lighting, composition, mood, negative, edit_instruction, style, aspect_ratio。"
        "prompt 必须是可直接给出图模型的画面描述，不要包含“我想要、帮我、请生成、出一张图”等对话式措辞。"
        "style 只能偏向 cinematic/anime/realistic；aspect_ratio 只能偏向 1:1/3:4/9:16。"
    )
    messages = [{"role": "system", "content": system}]
    if memory_block:
        messages.append({"role": "system", "content": memory_block})
    return [*messages, *history[-12:], {"role": "user", "content": current_text}]


def _context_memory_block(context: dict[str, Any]) -> str:
    parts: list[str] = []
    summary = _clip_text(context.get("memory_summary"), 1600)
    if summary:
        parts.append(f"上下文记忆摘要：\n{summary}")
    active = context.get("active_brief") if isinstance(context.get("active_brief"), dict) else {}
    if active:
        brief = {
            "intent": _clip_text(active.get("intent"), 80),
            "display_summary": _clip_text(active.get("display_summary"), 500),
            "compiled_prompt": _clip_text(active.get("compiled_prompt"), 700),
            "style": _clip_text(active.get("style"), 40),
            "aspect_ratio": _clip_text(active.get("aspect_ratio"), 20),
            "workflow": _clip_text(active.get("workflow"), 160),
        }
        parts.append("上一版创作方案 JSON：" + json.dumps({k: v for k, v in brief.items() if v}, ensure_ascii=False))
    source = _source_result(context)
    if source:
        result = {
            "id": _clip_text(source.get("id"), 120),
            "image": _clip_text(source.get("image"), 240),
            "thumb": _clip_text(source.get("thumb"), 240),
            "media_type": _clip_text(source.get("media_type"), 40),
            "workflow": _clip_text(source.get("workflow"), 160),
            "prompt": _clip_text(source.get("prompt"), 500),
        }
        parts.append("上一张生成结果 JSON：" + json.dumps({k: v for k, v in result.items() if v}, ensure_ascii=False))
    attachments = context.get("attachments") if isinstance(context.get("attachments"), list) else []
    if attachments:
        safe_attachments = []
        for item in attachments[:4]:
            if not isinstance(item, dict):
                continue
            safe_attachments.append({
                "id": _clip_text(item.get("id"), 120),
                "name": _clip_text(item.get("name"), 160),
                "mime_type": _clip_text(item.get("mime_type"), 80),
                "media_type": _clip_text(item.get("media_type"), 40),
                "url": _clip_text(item.get("url"), 240),
            })
        if safe_attachments:
            parts.append("本轮用户附件 JSON：" + json.dumps(safe_attachments, ensure_ascii=False))
    if not parts:
        return ""
    return (
        "下面是当前对话的长期/短期记忆，只用于理解用户当前意图，不要原样复述给用户。\n"
        + "\n".join(parts)
    )


def _clip_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text[: max(0, limit)]


def _json_object_candidates(text: str) -> list[str]:
    values = [text]
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    values.extend(fenced)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        values.append(text[start : end + 1])
    return values


def _parse_loose_decision(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    match = re.match(r"^(chat|ask_more|propose_generation)\b\s*,?\s*(.*)$", raw, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    action = match.group(1).lower()
    rest = match.group(2).strip()
    values: dict[str, str] = {}
    for key in ("reply", "prompt", "style", "aspect_ratio"):
        key_match = re.search(rf"{key}\s*=\s*(.+?)(?=\s*,\s*(?:reply|prompt|style|aspect_ratio)\s*=|$)", rest, flags=re.DOTALL)
        if key_match:
            values[key] = key_match.group(1).strip().strip('"')
    reply = values.get("reply") or values.get("prompt") or rest
    return {
        "action": action,
        "reply": reply.strip(),
        "prompt": values.get("prompt", "").strip() if action == "propose_generation" else "",
        "style": values.get("style", "").strip(),
        "aspect_ratio": values.get("aspect_ratio", "").strip(),
        "ready": action == "propose_generation",
    }


def _parse_partial_json_decision(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    action_match = re.search(r'"action"\s*:\s*"(chat|ask_more|propose_generation)"', raw, flags=re.IGNORECASE)
    if not action_match:
        return None
    action = action_match.group(1).lower()

    def find_string(key: str) -> str:
        match = re.search(rf'"{key}"\s*:\s*"([^"]*)', raw, flags=re.DOTALL)
        return match.group(1).strip() if match else ""

    return {
        "action": action,
        "reply": find_string("reply"),
        "prompt": find_string("prompt") if action == "propose_generation" else "",
        "style": find_string("style"),
        "aspect_ratio": find_string("aspect_ratio"),
        "ready": action == "propose_generation",
    }


def _normalize_choice(value: Any, allowed: Any, fallback: str) -> str:
    allowed_values = [str(item).strip() for item in (allowed or []) if str(item).strip()]
    if fallback not in allowed_values:
        allowed_values.insert(0, fallback)
    raw = str(value or "").strip()
    return raw if raw in allowed_values else allowed_values[0]


def _options(style: str, ratio: str, settings: dict[str, Any]) -> dict[str, Any]:
    dimensions = ratio_to_dimensions(ratio)
    return {
        "style": style,
        "aspect_ratio": ratio,
        "width": dimensions["width"],
        "height": dimensions["height"],
        "allowed_styles": [str(item).strip() for item in (settings.get("allowed_styles") or []) if str(item).strip()],
        "allowed_ratios": [str(item).strip() for item in (settings.get("allowed_ratios") or []) if str(item).strip()],
    }


def _source_result(context: dict[str, Any]) -> dict[str, Any]:
    value = context.get("last_result") if isinstance(context, dict) else {}
    return value if isinstance(value, dict) else {}


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))
