"""Small OpenAI-compatible client for the resident local LLM service."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request
from typing import Any


DEFAULT_LLM_BASE_URL = os.environ.get("EZ_LLM_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
DEFAULT_LLM_MODEL = os.environ.get("EZ_LLM_MODEL", "gemma-4-e2b")
DEFAULT_LLM_TIMEOUT = float(os.environ.get("EZ_LLM_TIMEOUT", "180") or 180)
DIRECT_FINAL_SYSTEM_PROMPT = (
    "Do not reason. Do not think. Return only the final answer. "
    "Do not reveal chain-of-thought, analysis, scratchpad, or hidden reasoning."
)
_runtime_settings: dict[str, Any] = {
    "enabled": True,
    "base_url": DEFAULT_LLM_BASE_URL,
    "model": DEFAULT_LLM_MODEL,
    "api_key": os.environ.get("EZ_LLM_API_KEY", "").strip(),
    "timeout": DEFAULT_LLM_TIMEOUT,
    "disable_thinking": True,
}


class LLMClientError(RuntimeError):
    """Raised when the local LLM endpoint cannot complete a request."""


class LLMVisionUnsupportedError(LLMClientError):
    """Raised when the endpoint is reachable but was started without vision support."""


def llm_provider_name(model: str | None = None, *, vision: bool = False) -> str:
    suffix = "-vision" if vision else ""
    return f"llm-{model or _runtime_settings.get('model') or DEFAULT_LLM_MODEL}{suffix}"


def _redact_api_key(value: str) -> str:
    value = str(value or "")
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def configure_llm_client(settings: dict[str, Any] | None = None, *, include_api_key: bool = False) -> dict[str, Any]:
    """Apply runtime LLM API settings used by prompt helpers."""
    raw = settings if isinstance(settings, dict) else {}
    enabled = raw.get("enabled", _runtime_settings.get("enabled", True))
    base_url = str(raw.get("base_url") or DEFAULT_LLM_BASE_URL).strip().rstrip("/")
    model = str(raw.get("model") or DEFAULT_LLM_MODEL).strip()
    api_key = str(raw.get("api_key") if raw.get("api_key") is not None else _runtime_settings.get("api_key", "")).strip()
    try:
        timeout = float(raw.get("timeout", _runtime_settings.get("timeout", DEFAULT_LLM_TIMEOUT)) or DEFAULT_LLM_TIMEOUT)
    except (TypeError, ValueError):
        timeout = DEFAULT_LLM_TIMEOUT
    timeout = max(1.0, min(timeout, 1800.0))
    disable_thinking = raw.get("disable_thinking", _runtime_settings.get("disable_thinking", True))
    _runtime_settings.update(
        {
            "enabled": bool(enabled),
            "base_url": base_url or DEFAULT_LLM_BASE_URL,
            "model": model or DEFAULT_LLM_MODEL,
            "api_key": api_key,
            "timeout": timeout,
            "disable_thinking": bool(disable_thinking),
        }
    )
    return get_llm_client_settings(include_api_key=include_api_key)


def get_llm_client_settings(*, include_api_key: bool = False) -> dict[str, Any]:
    settings = dict(_runtime_settings)
    if not include_api_key:
        settings["api_key"] = _redact_api_key(str(settings.get("api_key") or ""))
    return settings


def image_to_data_url(path: str) -> str:
    media_type = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def chat_completion(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.15,
    max_tokens: int = 384,
    timeout: float | None = None,
    response_format: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call /v1/chat/completions on a llama.cpp/vLLM/OpenAI-compatible server."""
    if not _runtime_settings.get("enabled", True) and base_url is None:
        raise LLMClientError("LLM API is disabled")
    effective_base_url = (base_url or str(_runtime_settings.get("base_url") or DEFAULT_LLM_BASE_URL)).rstrip("/")
    endpoint = f"{effective_base_url}/v1/chat/completions"
    payload = {
        "model": model or str(_runtime_settings.get("model") or DEFAULT_LLM_MODEL),
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens or 384),
    }
    if isinstance(response_format, dict) and response_format:
        payload["response_format"] = response_format
    if _runtime_settings.get("disable_thinking", True):
        # llama.cpp/vLLM-style servers can otherwise spend the whole output
        # budget in reasoning_content, leaving the final assistant content empty.
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    return _post_chat_completion_payload(
        endpoint,
        payload,
        api_key=api_key,
        timeout=timeout,
        allow_disable_thinking_retry=True,
        allow_response_format_retry=True,
    )


def _post_chat_completion_payload(
    endpoint: str,
    payload: dict[str, Any],
    *,
    api_key: str | None,
    timeout: float | None,
    allow_disable_thinking_retry: bool = False,
    allow_response_format_retry: bool = False,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    effective_api_key = str(api_key if api_key is not None else _runtime_settings.get("api_key", "")).strip()
    if effective_api_key:
        headers["Authorization"] = f"Bearer {effective_api_key}"
    req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=float(timeout or _runtime_settings.get("timeout") or DEFAULT_LLM_TIMEOUT)) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            e.close()
        except Exception:
            pass
        message = _error_message(raw) or str(e)
        if (
            allow_disable_thinking_retry
            and "chat_template_kwargs" in payload
            and _looks_like_unknown_parameter_error(message)
        ):
            fallback_payload = dict(payload)
            fallback_payload.pop("chat_template_kwargs", None)
            return _post_chat_completion_payload(
                endpoint,
                fallback_payload,
                api_key=api_key,
                timeout=timeout,
                allow_disable_thinking_retry=False,
                allow_response_format_retry=allow_response_format_retry,
            )
        if (
            allow_response_format_retry
            and "response_format" in payload
            and (
                _looks_like_unknown_parameter_error(message)
                or _looks_like_response_format_error(message)
            )
        ):
            fallback_payload = dict(payload)
            fallback_payload.pop("response_format", None)
            return _post_chat_completion_payload(
                endpoint,
                fallback_payload,
                api_key=api_key,
                timeout=timeout,
                allow_disable_thinking_retry=allow_disable_thinking_retry,
                allow_response_format_retry=False,
            )
        if "image input is not supported" in message.lower() or "mmproj" in message.lower():
            raise LLMVisionUnsupportedError(message) from e
        raise LLMClientError(message) from e
    except Exception as e:
        raise LLMClientError(str(e)) from e
    try:
        parsed = json.loads(raw)
    except Exception as e:
        raise LLMClientError(f"Invalid LLM response: {raw[:300]}") from e
    return parsed


def chat_text(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.15,
    max_tokens: int = 384,
    timeout: float | None = None,
    response_format: dict[str, Any] | None = None,
) -> str:
    response = chat_completion(
        messages,
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        response_format=response_format,
    )
    try:
        message = response["choices"][0]["message"]
        content = message["content"]
    except Exception as e:
        raise LLMClientError(f"LLM response missing message content: {response}") from e
    reasoning_content = str(message.get("reasoning_content") or "").strip()
    if not str(content or "").strip() and isinstance(response_format, dict) and response_format.get("type") == "json_object":
        # Some local OpenAI-compatible servers put JSON-mode output in reasoning_content.
        # Accept only a JSON-looking object; never expose arbitrary hidden reasoning.
        if reasoning_content.startswith("{"):
            return reasoning_content
    if not str(content or "").strip() and reasoning_content:
        raise LLMClientError("LLM returned reasoning_content without final content")
    return str(content or "").strip()


def _error_message(raw: str) -> str:
    try:
        parsed = json.loads(raw)
    except Exception:
        return str(raw or "").strip()
    error = parsed.get("error") if isinstance(parsed, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or parsed).strip()
    return str(parsed).strip()


def _looks_like_unknown_parameter_error(message: str) -> bool:
    lower = str(message or "").lower()
    if "chat_template_kwargs" not in lower:
        return False
    return any(token in lower for token in ("unknown", "unrecognized", "unexpected", "extra", "not permitted"))


def _looks_like_response_format_error(message: str) -> bool:
    lower = str(message or "").lower()
    if "response_format" not in lower:
        return False
    return any(
        token in lower
        for token in (
            "json_object",
            "json_schema",
            "must be",
            "not supported",
            "unsupported",
            "invalid",
            "not permitted",
        )
    )
