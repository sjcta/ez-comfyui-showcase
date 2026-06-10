from __future__ import annotations

import json
import re
from typing import Any

from .contracts import REVERSE_MODE_EXPERT, REVERSE_MODE_EXPERT_TEAM, ReverseOutput, normalize_reverse_mode
from .schemas import compact_two_level_dict


_TEMPLATE_ECHO_PHRASES = (
    "用完整句写",
    "仅人物可见时输出",
    "来自第1轮",
    "主体持有/接触物",
    "摄影设备可见迹象",
    "无法确认具体角度时写可见倾向",
    "按以下JSON结构输出",
    "完整正向复刻提示词",
    "不超过600字",
    "头部yaw/pitch/roll、颈肩胸腰骨盆",
    "肩线胯线脊柱、画面左侧肩肘腕",
    "手指和脚尖方向的近似角度",
    "JSON字段白名单",
    "字段说明",
    "不是内容模板",
)

_DIMENSION_PREFIXES = (
    "构图空间",
    "摄影镜头",
    "人物外貌",
    "头颈视线",
    "躯干重心",
    "四肢端点",
    "姿态结构",
    "人体姿态",
    "服装材质",
    "色彩光影",
    "文字标识",
    "暴露与情色内容",
    "光影专家",
    "道具专家",
    "服装专家",
    "面部专家",
    "姿态专家",
)

_VAGUE_FILLER_WORDS = ("微微", "略微", "轻微", "微收")
_NEGATIVE_EXPOSURE_PHRASES = (
    "无过度暴露",
    "没有明显情色",
    "未见性行为",
    "未见性器官",
    "不可见乳头",
    "不可见乳晕",
    "不可见外生殖器",
    "没有外生殖器可见像素",
)
_ROLE_SIDE_LIMB_RE = re.compile(r"(?<!画面)(?:左手|右手|左臂|右臂|左腿|右腿|左脚|右脚|左肘|右肘|左膝|右膝|左腕|右腕|左踝|右踝)")
_SENSITIVE_ANATOMY_TERMS = (
    "乳头",
    "乳晕",
    "外阴",
    "阴阜",
    "阴唇",
    "阴道口",
    "阴蒂",
    "阴茎",
    "龟头",
    "阴囊",
    "睾丸",
    "外生殖器",
)
_NEGATIVE_VISIBILITY_RE = re.compile(r"(?:没有|未见|不可见|看不见|未显示|未露出|被.+?覆盖|被.+?遮挡).{0,16}(?:可见|像素|露出|显示)?")


def _is_negative_sensitive_visibility(text: str) -> bool:
    raw = str(text or "")
    return any(term in raw for term in _SENSITIVE_ANATOMY_TERMS) and bool(_NEGATIVE_VISIBILITY_RE.search(raw))


def _normalize_visual_fragment(text: str) -> str:
    raw = _strip_dimension_prefix(str(text or "").strip())
    if not raw:
        return ""
    for word in _VAGUE_FILLER_WORDS:
        raw = raw.replace(word, "")
    for phrase in _NEGATIVE_EXPOSURE_PHRASES:
        raw = raw.replace(phrase, "")
    return re.sub(r"[，,；;。]*\s*$", "", raw).strip()


def _clean_visual_fragment(text: str) -> str:
    raw = _normalize_visual_fragment(text)
    if not raw or _is_negative_sensitive_visibility(raw):
        return ""
    return raw


def _strip_dimension_prefix(text: str) -> str:
    cleaned = str(text or "").strip()
    prefix, sep, rest = cleaned.partition("：")
    if sep and prefix.strip() in _DIMENSION_PREFIXES:
        return rest.strip()
    prefix, sep, rest = cleaned.partition(":")
    if sep and prefix.strip() in _DIMENSION_PREFIXES:
        return rest.strip()
    return cleaned


def _is_template_echo_text(text: str) -> bool:
    raw = str(text or "")
    return any(phrase in raw for phrase in _TEMPLATE_ECHO_PHRASES)


def _clean_visual_text(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    raw = _normalize_visual_fragment(raw)
    if not raw:
        return ""
    parts = [part.strip(" ，,；;。") for part in re.split(r"[；;\n]+", raw) if part.strip(" ，,；;。")]
    kept: list[str] = []
    for part in parts:
        if _is_template_echo_text(part):
            continue
        clauses = [_clean_visual_fragment(clause) for clause in re.split(r"[，,]+", part)]
        clause_text = "，".join(clause for clause in clauses if clause and not _ROLE_SIDE_LIMB_RE.search(clause))
        if clause_text:
            kept.append(clause_text)
    return "；".join(part for part in kept if part)


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
    if any(word in prefix for word in ("头颈", "视线")):
        return "头部面部"
    if any(word in prefix for word in ("四肢", "端点", "肩肘腕", "髋膝踝", "手指", "脚尖")):
        return "关节角度"
    if any(word in prefix for word in ("姿态", "人体", "躯干", "肢体", "重心")):
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
    if any(word in prefix for word in ("暴露", "情色", "裸露", "性意味", "隐私")):
        return "暴露与情色内容"
    return "补充细节"


def _expert_observation_items(value: Any) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    if value in ("", None, [], {}):
        return items
    if isinstance(value, dict) and ("观点" in value or "内容" in value):
        dimension = _clean_visual_text(str(value.get("维度") or value.get("dimension") or "补充细节"))
        sentence = _clean_visual_text(str(value.get("观点") or value.get("内容") or value.get("observation") or ""))
        if sentence:
            items.append((_dimension_for_expert_sentence(f"{dimension}：{sentence}"), sentence))
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


def _clean_expert_display_items(value: Any) -> list[str]:
    cleaned_items: list[str] = []
    if value in ("", None, [], {}):
        return cleaned_items
    if isinstance(value, str):
        raw = str(value or "").strip()
        prefix, sep, rest = raw.partition("：")
        if not sep:
            prefix, sep, rest = raw.partition(":")
        dimension = prefix.strip() if sep and prefix.strip() else _dimension_for_expert_sentence(raw)
        sentence = rest if sep else raw
        cleaned = _clean_visual_text(sentence)
        if cleaned:
            cleaned_items.append(f"{dimension}：{cleaned}")
        return cleaned_items
    if isinstance(value, list):
        for item in value:
            cleaned_items.extend(_clean_expert_display_items(item))
        return cleaned_items
    if isinstance(value, dict):
        dimension = str(value.get("维度") or value.get("dimension") or "").strip()
        sentence = value.get("观点") or value.get("内容") or value.get("observation")
        if sentence:
            cleaned = _clean_visual_text(str(sentence))
            if cleaned:
                cleaned_items.append(f"{dimension or _dimension_for_expert_sentence(str(sentence))}：{cleaned}")
            return cleaned_items
        for key, item in value.items():
            for cleaned in _clean_expert_display_items(item):
                if "：" in cleaned or ":" in cleaned:
                    cleaned_items.append(cleaned)
                else:
                    cleaned_items.append(f"{key}：{cleaned}")
    return cleaned_items


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


def _prompt_sentence_values(value: Any) -> list[str]:
    sentences: list[str] = []
    for item in _sentence_values(value):
        for part in re.split(r"[。；;\n]+", item):
            clauses = []
            for clause in re.split(r"[，,]+", part):
                cleaned_clause = _clean_visual_fragment(clause).strip(" ，,。；;")
                if cleaned_clause and not _ROLE_SIDE_LIMB_RE.search(cleaned_clause):
                    clauses.append(cleaned_clause)
            cleaned = "，".join(clauses).strip(" ，,。；;")
            if cleaned:
                sentences.append(cleaned)
    return sentences


def _similarity_key(text: str) -> str:
    return re.sub(r"[\s，,。；;：:、（）()“”\"'`]+", "", str(text or "").replace("主体人物", "主体"))


def _char_bigram_similarity(left: str, right: str) -> float:
    a = _similarity_key(left)
    b = _similarity_key(right)
    if len(a) < 18 or len(b) < 18:
        return 0.0
    grams_a = {a[i : i + 2] for i in range(len(a) - 1)}
    grams_b = {b[i : i + 2] for i in range(len(b) - 1)}
    if not grams_a or not grams_b:
        return 0.0
    return len(grams_a & grams_b) / max(1, min(len(grams_a), len(grams_b)))


def _detail_score(text: str) -> int:
    raw = str(text or "")
    detail_terms = (
        "妆容",
        "纹理",
        "材质",
        "拉链",
        "褶皱",
        "荷叶边",
        "鞋带",
        "缝线",
        "拼接",
        "包边",
        "yaw",
        "pitch",
        "roll",
        "约",
        "度",
        "占画面",
        "色值",
        "#",
        "光源",
        "高光",
        "阴影",
        "遮挡",
        "接触",
        "支撑",
    )
    return sum(1 for term in detail_terms if term in raw)


def _add_prompt_sentence(parts: list[str], sentence: str) -> None:
    cleaned = _clean_final_prompt_text(sentence).strip(" ，,。；;")
    if not cleaned:
        return
    for index, existing in enumerate(parts):
        if cleaned == existing or cleaned in existing:
            return
        if existing in cleaned:
            parts[index] = cleaned
            return
        if _char_bigram_similarity(existing, cleaned) >= 0.75:
            if (_detail_score(cleaned) >= _detail_score(existing) and _detail_score(cleaned) > 0) or len(cleaned) > int(len(existing) * 1.2):
                parts[index] = cleaned
            return
    parts.append(cleaned)


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
    ordered_keys = (
        "整体描述",
        "画面主题",
        "基本概述",
        "主体判定",
        "画面比例与主体占比",
        "主体细节",
        "人物外貌",
        "关节角度",
        "暴露与情色内容",
        "构图镜头",
        "构图光色",
        "镜头倾斜角度",
        "物体空间",
        "物体背景",
        "光影色彩风格",
        "专家观点",
    )
    parts: list[str] = []
    for key in ordered_keys:
        if key == "专家观点":
            for dimension, sentence in _expert_observation_items(parsed.get(key)):
                for part in _prompt_sentence_values(sentence):
                    _add_prompt_sentence(parts, part)
            continue
        for part in _prompt_sentence_values(parsed.get(key)):
            _add_prompt_sentence(parts, part)
    assembled = _clean_final_prompt_text("。".join(parts))
    if not prompt:
        return assembled
    if assembled and (len(prompt) < 120 or len(assembled) >= int(len(prompt) * 1.6)):
        return assembled
    return prompt


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
        "暴露与情色内容": _clean_value(parsed.get("暴露与情色内容") or parsed.get("暴露内容") or ""),
        "构图镜头": _clean_value(parsed.get("构图镜头") or parsed.get("构图光色") or ""),
        "镜头倾斜角度": _clean_value(parsed.get("镜头倾斜角度") or ""),
        "空间物体": _clean_value(parsed.get("物体空间") or parsed.get("物体背景") or parsed.get("空间关系") or ""),
        "光影色彩风格": _clean_value(parsed.get("光影色彩风格") or parsed.get("光色材质") or ""),
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
            "experts": _clean_expert_display_items(parsed.get("专家观点")),
            "review": parsed.get("复核结论") or parsed.get("问题修正"),
            "raw": parsed,
        }
    return ReverseOutput(
        mode=mode,
        provider=provider,
        prompt=prompt,
        negative_prompt=[],
        visual_spec=_visual_spec(parsed, mode),
        raw=parsed,
        expert_interrogate=expert_interrogate,
        elapsed_seconds=elapsed_seconds,
    )
