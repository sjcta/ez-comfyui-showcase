from __future__ import annotations

import json
import time
from typing import Any, Callable

from modules.llm_client import DIRECT_FINAL_SYSTEM_PROMPT, chat_text, image_to_data_url, llm_provider_name

from .contracts import REVERSE_MODE_EXPERT, REVERSE_MODE_EXPERT_TEAM, REVERSE_MODE_STANDARD, mode_token_budget
from .parser import extract_json_object, parse_reverse_json
from .prompts import (
    build_expert_prompt,
    build_expert_team_global_prompt,
    build_expert_team_review_prompt,
    build_expert_team_subject_prompt,
    build_standard_prompt,
)


ChatFn = Callable[..., str]


def _vision_messages(prompt: str, image_path: str) -> list[dict[str, Any]]:
    data_url = image_to_data_url(image_path)
    return [
        {
            "role": "system",
            "content": DIRECT_FINAL_SYSTEM_PROMPT + " Return only one valid JSON object. Do not output markdown.",
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]


def _call_vision_json(
    image_path: str,
    prompt: str,
    *,
    chat_fn: ChatFn,
    model: str | None,
    timeout: float,
    max_tokens: int,
    temperature: float,
) -> str:
    return chat_fn(
        _vision_messages(prompt, image_path),
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        response_format={"type": "json_object"},
    )


def _has_review_final_content(review: dict[str, Any]) -> bool:
    if not isinstance(review, dict):
        return False
    for key in ("final_prompt", "最终提示词", "最终规格", "final_spec", "主体细节", "专家观点", "构图光色", "物体背景"):
        value = review.get(key)
        if value not in ("", None, [], {}):
            return True
    return False


def _merge_review_into_subject(subject: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    merged = dict(subject or {})
    for key, value in (review or {}).items():
        if value not in ("", None, [], {}):
            merged[key] = value
    if not merged.get("主体细节") and review.get("最终规格"):
        merged["主体细节"] = review.get("最终规格")
    return merged


def run_standard_reverse(
    image_path: str,
    *,
    chat_fn: ChatFn = chat_text,
    timeout: float = 180.0,
    max_new_tokens: int | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    started_at = time.monotonic()
    provider = llm_provider_name(model, vision=True)
    raw = _call_vision_json(
        image_path,
        build_standard_prompt(),
        chat_fn=chat_fn,
        model=model,
        timeout=timeout,
        max_tokens=max(512, min(int(max_new_tokens or mode_token_budget(REVERSE_MODE_STANDARD)), 4096)),
        temperature=0.12,
    )
    output = parse_reverse_json(
        raw,
        mode=REVERSE_MODE_STANDARD,
        provider=provider,
        elapsed_seconds=round(time.monotonic() - started_at, 3),
    )
    return output.to_api_payload()


def run_expert_reverse(
    image_path: str,
    *,
    chat_fn: ChatFn = chat_text,
    timeout: float = 300.0,
    max_new_tokens: int | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    started_at = time.monotonic()
    provider = llm_provider_name(model, vision=True)
    raw = _call_vision_json(
        image_path,
        build_expert_prompt(),
        chat_fn=chat_fn,
        model=model,
        timeout=timeout,
        max_tokens=max(1024, min(int(max_new_tokens or mode_token_budget(REVERSE_MODE_EXPERT)), 8192)),
        temperature=0.08,
    )
    output = parse_reverse_json(
        raw,
        mode=REVERSE_MODE_EXPERT,
        provider=provider,
        elapsed_seconds=round(time.monotonic() - started_at, 3),
    )
    return output.to_api_payload()


def run_expert_team_reverse(
    image_path: str,
    *,
    chat_fn: ChatFn = chat_text,
    timeout: float = 480.0,
    max_new_tokens: int | None = None,
    model: str | None = None,
    review_enabled: bool = True,
) -> dict[str, Any]:
    started_at = time.monotonic()
    provider = llm_provider_name(model, vision=True)
    total_timeout = max(60.0, float(timeout or 480.0))
    global_raw = _call_vision_json(
        image_path,
        build_expert_team_global_prompt(),
        chat_fn=chat_fn,
        model=model,
        timeout=max(30.0, total_timeout * 0.25),
        max_tokens=max(768, min(int((max_new_tokens or mode_token_budget(REVERSE_MODE_EXPERT_TEAM)) * 0.35), 4096)),
        temperature=0.06,
    )
    global_scan = extract_json_object(global_raw)
    subject_raw = _call_vision_json(
        image_path,
        build_expert_team_subject_prompt(global_scan),
        chat_fn=chat_fn,
        model=model,
        timeout=max(45.0, total_timeout * 0.45),
        max_tokens=max(1536, min(int(max_new_tokens or mode_token_budget(REVERSE_MODE_EXPERT_TEAM)), 8192)),
        temperature=0.06,
    )
    subject_spec = extract_json_object(subject_raw)
    review_raw = ""
    final_raw = subject_raw
    review_json: dict[str, Any] = {}
    if review_enabled:
        review_raw = _call_vision_json(
            image_path,
            build_expert_team_review_prompt(subject_spec),
            chat_fn=chat_fn,
            model=model,
            timeout=max(45.0, total_timeout * 0.30),
            max_tokens=max(1536, min(int(max_new_tokens or mode_token_budget(REVERSE_MODE_EXPERT_TEAM)), 8192)),
            temperature=0.04,
        )
        review_json = extract_json_object(review_raw)
        if _has_review_final_content(review_json):
            final_raw = json.dumps(_merge_review_into_subject(subject_spec, review_json), ensure_ascii=False)
    output = parse_reverse_json(
        final_raw,
        mode=REVERSE_MODE_EXPERT_TEAM,
        provider=provider,
        elapsed_seconds=round(time.monotonic() - started_at, 3),
    )
    payload = output.to_api_payload()
    expert = payload.setdefault("expert_interrogate", {})
    expert["enabled"] = True
    expert["provider"] = provider
    expert["mode"] = "multi_pass_team"
    expert["global_raw"] = global_raw
    expert["subject_raw"] = subject_raw
    expert["review_raw"] = review_raw
    if review_json:
        expert["review"] = review_json.get("复核结论") or review_json.get("问题修正") or review_json
    expert["second_review_enabled"] = bool(review_enabled)
    return payload
