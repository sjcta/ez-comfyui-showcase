from __future__ import annotations

import json
import re
from typing import Any

from .contracts import REVERSE_MODE_EXPERT, REVERSE_MODE_EXPERT_TEAM, ReverseOutput, normalize_reverse_mode
from .schemas import compact_two_level_dict


def _clean_visual_text(text: str) -> str:
    return str(text or "").strip()


def _clean_final_prompt_text(text: str) -> str:
    return _clean_visual_text(text)


def _clean_negative_text(text: str) -> str:
    return _clean_visual_text(text).strip(" ，,；;。")


def _append_core_text(core: dict[str, Any], key: str, text: str) -> None:
    cleaned = _clean_visual_text(text)
    if not cleaned:
        return
    existing = core.get(key)
    if existing in ("", None, [], {}):
        core[key] = cleaned
    elif isinstance(existing, list):
        if cleaned not in existing:
            existing.append(cleaned)
    elif cleaned not in str(existing):
        core[key] = f"{existing}；{cleaned}"


def _dimension_for_expert_sentence(text: str) -> str:
    raw = str(text or "").strip()
    prefix = raw.split("：", 1)[0].split(":", 1)[0]
    if any(word in prefix for word in ("姿态", "人体", "躯干", "肢体")):
        return "姿态结构"
    if any(word in prefix for word in ("外貌", "族裔", "人种", "肤色", "面部", "表情", "头发", "发型", "发色", "染发", "妆容")):
        return "头部面部"
    if any(word in prefix for word in ("关节", "角度", "肩肘腕", "髋膝踝", "手指", "脚尖")):
        return "关节角度"
    if any(word in prefix for word in ("服装", "衣物", "鞋", "妆造")):
        return "服装材质"
    if any(word in prefix for word in ("道具", "物体", "文字", "Logo", "水印")):
        return "道具文字"
    if any(word in prefix for word in ("光影", "色彩", "摄影", "光线")):
        return "光影色彩"
    if any(word in prefix for word in ("构图", "镜头", "空间", "俯仰", "roll", "倾斜")):
        return "构图镜头"
    if any(word in prefix for word in ("材质", "纹理")):
        return "材质纹理"
    if any(word in prefix for word in ("暴露", "NSFW")):
        return "暴露内容"
    return "补充细节"


def _expert_observation_items(value: Any) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    if value in ("", None, [], {}):
        return items
    if isinstance(value, str):
        cleaned = _clean_visual_text(value)
        if cleaned:
            items.append((_dimension_for_expert_sentence(value), cleaned))
        return items
    if isinstance(value, list):
        for item in value:
            items.extend(_expert_observation_items(item))
        return items
    if isinstance(value, dict):
        for key, item in value.items():
            for _, cleaned in _expert_observation_items(item):
                items.append((_dimension_for_expert_sentence(f"{key}：{cleaned}"), cleaned))
        return items
    cleaned = _clean_visual_text(str(value))
    if cleaned:
        items.append((_dimension_for_expert_sentence(str(value)), cleaned))
    return items


def _looks_like_coarser_pose_summary(subject: Any, sentence: str) -> bool:
    subject_text = "；".join(_sentence_values(subject))
    sentence_text = _clean_visual_text(sentence)
    if not subject_text or not sentence_text:
        return False
    pose_terms = ("头部", "视线", "胸腔", "骨盆", "肩线", "胯线", "脊柱", "左臂", "右臂", "左腿", "右腿", "肘", "膝", "手", "脚")
    subject_score = sum(1 for term in pose_terms if term in subject_text)
    sentence_score = sum(1 for term in pose_terms if term in sentence_text)
    if sentence_text in subject_text:
        return True
    if subject_score >= 5 and sentence_score <= 3:
        return True
    return len(subject_text) >= 120 and len(sentence_text) <= max(80, int(len(subject_text) * 0.55))


def _clean_value(value: Any) -> Any:
    if isinstance(value, str):
        return _clean_visual_text(value)
    if isinstance(value, list):
        return [_clean_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key or "").strip(): _clean_value(item) for key, item in value.items()}
    return value


def _clean_public_raw(value: Any, *, key_hint: str = "") -> Any:
    if isinstance(value, str):
        return _clean_value(value)
    if isinstance(value, list):
        cleaned_list = [_clean_public_raw(item) for item in value]
        return [item for item in cleaned_list if item not in ("", None, [], {})]
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key or "").strip()
            cleaned_item = _clean_public_raw(item, key_hint=key_text)
            if cleaned_item not in ("", None, [], {}):
                cleaned[key_text] = cleaned_item
        return cleaned
    return value


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = str(text or "").strip()
    if not stripped:
        return {}
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.I).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{.*\}", stripped, flags=re.S)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _negative_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [cleaned for item in re.split(r"[,，;；\n]+", value) if (cleaned := _clean_negative_text(item))]
    if isinstance(value, list):
        return [cleaned for item in value if (cleaned := _clean_negative_text(str(item)))]
    return []


def _first_present(parsed: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = parsed.get(key)
        if value not in ("", None, [], {}):
            return value
    return ""


def _sentence_values(value: Any) -> list[str]:
    if value in ("", None, [], {}):
        return []
    if isinstance(value, str):
        cleaned = _clean_visual_text(value)
        return [cleaned] if cleaned else []
    if isinstance(value, list):
        return [_clean_visual_text(str(item)) for item in value if _clean_visual_text(str(item))]
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(_sentence_values(item))
        return out
    return [str(value).strip()]


def _abc_visual_spec(parsed: dict[str, Any]) -> Any:
    return _first_present(
        parsed,
        "结构化视觉规格书",
        "A_结构化视觉规格书",
        "A 结构化视觉规格书",
        "A部分结构化视觉规格书",
        "A. 结构化视觉规格书",
        "A",
    )


def _final_prompt(parsed: dict[str, Any]) -> str:
    prompt = _clean_final_prompt_text(str(_first_present(
        parsed,
        "final_prompt",
        "最终提示词",
        "B_最终提示词",
        "B 最终提示词",
        "B部分最终提示词",
        "B. 最终可用于图像生成模型的完整提示词",
        "B",
    )).strip())
    if prompt:
        return prompt
    ordered_keys = (
        "画面主题",
        "基本概述",
        "主体判定",
        "画面比例与主体占比",
        "主体细节",
        "人物外貌",
        "关节角度",
        "构图镜头",
        "构图光色",
        "镜头倾斜角度",
        "物体空间",
        "物体背景",
        "光影色彩风格",
        "最终规格",
        "专家观点",
    )
    parts: list[str] = []
    subject_value = parsed.get("主体细节") or parsed.get("主体描述") or ""
    for key in ordered_keys:
        if key == "专家观点":
            for dimension, sentence in _expert_observation_items(parsed.get(key)):
                parts.append(sentence)
            continue
        parts.extend(_sentence_values(parsed.get(key)))
    return _clean_final_prompt_text("，".join(parts))


def _visual_spec(parsed: dict[str, Any], mode: str) -> dict[str, Any]:
    abc_spec = _abc_visual_spec(parsed)
    if isinstance(abc_spec, dict) and abc_spec:
        return {"画面描述": _clean_value(abc_spec)}
    core = {
        "基本概述": _clean_value(parsed.get("基本概述") or parsed.get("画面主题") or parsed.get("主体判定") or ""),
        "画面比例与主体占比": _clean_value(parsed.get("画面比例与主体占比") or ""),
        "主体": _clean_value(parsed.get("主体细节") or parsed.get("主体描述") or ""),
        "人物外貌": _clean_value(parsed.get("人物外貌") or ""),
        "关节角度": _clean_value(parsed.get("关节角度") or ""),
        "构图镜头": _clean_value(parsed.get("构图镜头") or parsed.get("构图光色") or ""),
        "镜头倾斜角度": _clean_value(parsed.get("镜头倾斜角度") or ""),
        "空间物体": _clean_value(parsed.get("物体空间") or parsed.get("物体背景") or parsed.get("空间关系") or ""),
        "光影色彩风格": _clean_value(parsed.get("光影色彩风格") or parsed.get("光色材质") or ""),
        "最终规格": _clean_value(parsed.get("最终规格") or parsed.get("final_spec") or ""),
        "可见文字": _clean_value(parsed.get("可见文字") or ""),
    }
    for dimension, sentence in _expert_observation_items(parsed.get("专家观点")):
        if dimension == "姿态结构" and core.get("主体"):
            _append_core_text(core, "主体", sentence)
            continue
        _append_core_text(core, dimension, sentence)
    compacted = compact_two_level_dict(core)
    return {"画面描述": compacted}


def parse_reverse_json(raw_text: str, *, mode: str, provider: str, elapsed_seconds: float | None = None) -> ReverseOutput:
    mode = normalize_reverse_mode(mode)
    parsed = extract_json_object(raw_text)
    prompt = _final_prompt(parsed)
    if not prompt:
        prompt = str(raw_text or "").strip()
    expert_interrogate = None
    if mode in {REVERSE_MODE_EXPERT, REVERSE_MODE_EXPERT_TEAM}:
        expert_interrogate = {
            "enabled": True,
            "provider": provider,
            "mode": "multi_pass_team" if mode == REVERSE_MODE_EXPERT_TEAM else "single_pass",
            "experts": parsed.get("专家观点") if isinstance(parsed.get("专家观点"), list) else [],
            "review": parsed.get("复核结论") or parsed.get("问题修正"),
            "raw": parsed,
        }
    negative_prompt = _negative_list(_first_present(
        parsed,
        "negative_prompt",
        "负面约束",
        "C_负面约束禁止项",
        "C 负面约束 / 禁止项",
        "C部分负面约束",
        "C. 负面约束 / 禁止项",
        "负面约束 / 禁止项",
        "C",
    ))
    return ReverseOutput(
        mode=mode,
        provider=provider,
        prompt=prompt,
        negative_prompt=negative_prompt,
        visual_spec=_visual_spec(parsed, mode),
        raw=parsed,
        expert_interrogate=expert_interrogate,
        elapsed_seconds=elapsed_seconds,
    )
