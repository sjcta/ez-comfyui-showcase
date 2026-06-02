from __future__ import annotations

from typing import Any, Callable

from modules.llm_client import chat_text

from .pipelines import run_expert_reverse, run_expert_team_reverse, run_standard_reverse


def run_llm_image_interrogator(
    image_path: str,
    *,
    chat_fn: Callable[..., str] = chat_text,
    timeout: float = 180.0,
    max_new_tokens: int = 3072,
    model: str | None = None,
    compact: bool = False,
    include_quality: bool = False,
) -> dict[str, Any]:
    return run_standard_reverse(
        image_path,
        chat_fn=chat_fn,
        timeout=timeout,
        max_new_tokens=max_new_tokens,
        model=model,
    )


def run_llm_expert_image_interrogator(
    image_path: str,
    *,
    chat_fn: Callable[..., str] = chat_text,
    timeout: float = 300.0,
    max_new_tokens: int = 6144,
    model: str | None = None,
    single_pass: bool = False,
    stage: str = "full",
    review_enabled: bool = True,
    include_quality: bool = False,
    expert_team: bool = False,
) -> dict[str, Any]:
    if expert_team:
        return run_expert_team_reverse(
            image_path,
            chat_fn=chat_fn,
            timeout=timeout,
            max_new_tokens=max_new_tokens,
            model=model,
            review_enabled=review_enabled,
        )
    return run_expert_reverse(
        image_path,
        chat_fn=chat_fn,
        timeout=timeout,
        max_new_tokens=max_new_tokens,
        model=model,
    )
