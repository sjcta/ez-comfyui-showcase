from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


REVERSE_MODE_STANDARD = "standard"
REVERSE_MODE_ADVANCED = "advanced"
REVERSE_MODE_EXPERT = REVERSE_MODE_ADVANCED
REVERSE_MODE_EXPERT_TEAM = "expert"
REVERSE_MODE_LEGACY_EXPERT_TEAM = "expert_team"
REVERSE_LEVELS = {
    REVERSE_MODE_STANDARD: 0,
    REVERSE_MODE_ADVANCED: 1,
    REVERSE_MODE_EXPERT_TEAM: 2,
    REVERSE_MODE_LEGACY_EXPERT_TEAM: 2,
}
REVERSE_MODE_LABELS = {
    REVERSE_MODE_STANDARD: "标准",
    REVERSE_MODE_ADVANCED: "加强",
    REVERSE_MODE_EXPERT_TEAM: "专家",
    REVERSE_MODE_LEGACY_EXPERT_TEAM: "专家",
}

MODE_TOKEN_BUDGETS = {
    REVERSE_MODE_STANDARD: 1536,
    REVERSE_MODE_ADVANCED: 4096,
    REVERSE_MODE_EXPERT_TEAM: 6144,
    REVERSE_MODE_LEGACY_EXPERT_TEAM: 6144,
}


def normalize_reverse_mode(mode: str) -> str:
    raw = str(mode or "").strip().lower()
    if raw in {"enhanced", "advance"}:
        return REVERSE_MODE_ADVANCED
    if raw == REVERSE_MODE_LEGACY_EXPERT_TEAM:
        return REVERSE_MODE_EXPERT_TEAM
    if raw in {REVERSE_MODE_STANDARD, REVERSE_MODE_ADVANCED, REVERSE_MODE_EXPERT_TEAM}:
        return raw
    return REVERSE_MODE_STANDARD


def mode_token_budget(mode: str) -> int:
    return MODE_TOKEN_BUDGETS.get(normalize_reverse_mode(mode), MODE_TOKEN_BUDGETS[REVERSE_MODE_STANDARD])


def mode_display_label(mode: str) -> str:
    normalized = normalize_reverse_mode(mode)
    return REVERSE_MODE_LABELS.get(normalized, normalized)


def mode_level(mode: str) -> int:
    return REVERSE_LEVELS.get(normalize_reverse_mode(mode), 0)


@dataclass(slots=True)
class ReverseOutput:
    mode: str
    provider: str
    prompt: str
    negative_prompt: list[str] = field(default_factory=list)
    visual_spec: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    expert_interrogate: dict[str, Any] | None = None
    elapsed_seconds: float | None = None

    def to_api_payload(self) -> dict[str, Any]:
        negative_text = ", ".join(item for item in self.negative_prompt if str(item).strip())
        structured_json = json.dumps(self.visual_spec, ensure_ascii=False, indent=2)
        raw_json = json.dumps(self.raw, ensure_ascii=False)
        payload: dict[str, Any] = {
            "ok": True,
            "provider": self.provider,
            "reverse_mode": normalize_reverse_mode(self.mode),
            "reverse_level": mode_level(self.mode),
            "reverse_mode_label": mode_display_label(self.mode),
            "prompt_id": "",
            "prompt": self.prompt,
            "promptgen": self.prompt,
            "prompt_zh": self.prompt,
            "wd14_tags": "",
            "structured_raw": raw_json,
            "structured_prompt": self.visual_spec,
            "structured_prompt_json": structured_json,
        }
        if negative_text:
            payload["negative_prompt"] = negative_text
        if self.expert_interrogate is not None:
            payload["expert_interrogate"] = self.expert_interrogate
        if self.elapsed_seconds is not None:
            payload["interrogate_elapsed_seconds"] = self.elapsed_seconds
        return payload
