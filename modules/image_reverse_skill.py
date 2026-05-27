"""Reusable image reverse-prompt skill guidance and quality validation."""

from __future__ import annotations

import re
from typing import Any


SKILL_VERSION = "image_reverse_skill_v0.1"
REPLICATION_TARGET_SCORE = 95

REVERSE_PROMPT_SKILL_GUIDE = (
    "反推闭环技能：先做可见证据抽取，再生成复刻提示词。禁止一开始自由发挥成氛围描述。"
    "第一层证据必须覆盖：原图画幅比例、主体可见范围、人物支撑点、身体朝向、手部端点、脚部承重、"
    "服装款式与材质、文字可信度、场景区域、光线色温、NSFW 可见事实。"
    "第二层才把证据合并成正向提示词、负面提示词和复刻约束。"
    "每个正向字段必须能回答“图里哪里看见的”；看不见、不确定、猜测和二选一不能进入正向提示词。"
    "如果证据互相冲突，以图像几何和实际可见物体优先，例如竖版图不能写 1:1，鞋子入镜不能写裁切到大腿。"
    "复刻成功率目标为 95 分；低于 95 分必须输出扣分原因并把原因转成下一轮 skill 约束。"
)

VISUAL_EVIDENCE_GUIDE = (
    "visual_evidence 是内部证据表，必须先于最终提示词生成；它不会展示给用户。"
    "每个证据项必须包含 value、evidence、confidence、allow_positive。"
    "value 是候选事实，evidence 写图中依据，例如画面位置、接触点、遮挡边界、可见纹理；"
    "confidence 低于 0.75 或 allow_positive=false 的内容禁止进入 structured_prompt.画面描述。"
    "证据表必须覆盖 aspect_ratio, visible_body_range, support_points, hand_endpoints, foot_or_shoe_contact, "
    "clothing_materials, visible_text_confidence, nsfw_visible_evidence, foreground_background_regions。"
    "最终 structured_prompt 只能复述 visual_evidence 中 allow_positive=true 的事实。"
)

REQUIRED_EVIDENCE_KEYS = (
    "aspect_ratio",
    "visible_body_range",
    "support_points",
    "hand_endpoints",
    "foot_or_shoe_contact",
    "clothing_materials",
    "visible_text_confidence",
    "nsfw_visible_evidence",
    "foreground_background_regions",
)

REQUIRED_EXPERT_IDS = (
    "composition",
    "photography_parameters",
    "color_light",
    "mood_style",
    "body_pose",
    "expression_language",
    "sexual_boundary",
    "clothing_makeup",
    "materials_texture",
)


def _iter_strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        items: list[str] = []
        for key, nested in value.items():
            items.append(str(key))
            items.extend(_iter_strings(nested))
        return items
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for nested in value:
            items.extend(_iter_strings(nested))
        return items
    text = str(value or "").strip()
    return [text] if text else []


def _joined_text(value: Any) -> str:
    return "，".join(_iter_strings(value))


def _add_issue(
    issues: list[dict[str, str]],
    code: str,
    severity: str,
    message: str,
    suggestion: str,
) -> None:
    issues.append(
        {
            "code": code,
            "severity": severity,
            "message": message,
            "suggestion": suggestion,
        }
    )


def _issue_penalty(severity: str) -> int:
    return {
        "critical": 12,
        "major": 8,
        "minor": 4,
    }.get(severity, 4)


def _nested_negative_prompt_issue(structured_prompt: Any) -> bool:
    if not isinstance(structured_prompt, dict):
        return False
    description = structured_prompt.get("画面描述")
    return isinstance(description, dict) and "负面提示词" in description


def _description_section(structured_prompt: Any) -> Any:
    if not isinstance(structured_prompt, dict):
        return {}
    return structured_prompt.get("画面描述") or structured_prompt.get("image_description") or {}


def _negative_section(structured_prompt: Any) -> Any:
    if not isinstance(structured_prompt, dict):
        return {}
    return structured_prompt.get("负面提示词") or structured_prompt.get("negative_prompt") or {}


def _positive_text(structured_prompt: Any) -> str:
    description = _description_section(structured_prompt)
    return _joined_text(description) if description else _joined_text(structured_prompt)


def _has_sparse_fallback_shape(structured_prompt: Any) -> bool:
    description = _description_section(structured_prompt)
    if not isinstance(description, dict):
        return False
    keys = [str(key) for key in description.keys()]
    return "合并提示词" in keys and len(keys) <= 2


def _sexual_boundary_text(structured_prompt: Any) -> str:
    description = _description_section(structured_prompt)
    if not isinstance(description, dict):
        return ""
    return _joined_text(description.get("性内容边界") or description.get("sexual_boundary") or "")


def validate_reverse_prompt_quality(
    structured_prompt: Any,
    *,
    image_size: tuple[int, int] | None = None,
    expert_results: list[dict[str, Any]] | None = None,
    visual_evidence: dict[str, Any] | None = None,
    require_visual_evidence: bool = False,
) -> dict[str, Any]:
    """Score reverse prompt output as a replication-spec regression check."""
    text = _joined_text(structured_prompt)
    positive_text = _positive_text(structured_prompt)
    issues: list[dict[str, str]] = []

    if require_visual_evidence:
        if not isinstance(visual_evidence, dict) or not visual_evidence:
            _add_issue(
                issues,
                "missing_visual_evidence",
                "critical",
                "专家反推没有先输出内部 visual_evidence 证据表，模型仍在直接写最终提示词。",
                "先输出证据表，再从 allow_positive=true 的证据生成 structured_prompt。",
            )
        else:
            missing_evidence = [key for key in REQUIRED_EVIDENCE_KEYS if key not in visual_evidence]
            if missing_evidence:
                _add_issue(
                    issues,
                    "incomplete_visual_evidence",
                    "major",
                    "visual_evidence 缺少关键证据项：" + ", ".join(missing_evidence),
                    "补齐画幅、可见范围、支撑点、手部端点、脚部承重、服装材质、文字可信度、NSFW 证据和区域扫描。",
                )

    if image_size:
        width, height = image_size
        if width > 0 and height > 0:
            aspect = height / width
            if aspect >= 1.25 and re.search(r"1\s*:\s*1|正方形", text, flags=re.IGNORECASE):
                _add_issue(
                    issues,
                    "aspect_ratio_conflict",
                    "critical",
                    "原图是竖版画幅，但输出写成 1:1/正方形。",
                    "按原图宽高写 9:16、2:3 或竖幅手机图。",
                )
            if aspect < 0.85 and re.search(r"竖版|竖幅|9\s*:\s*16", text, flags=re.IGNORECASE):
                _add_issue(
                    issues,
                    "aspect_ratio_conflict",
                    "critical",
                    "原图是横向画幅，但输出写成竖版。",
                    "按原图宽高写横幅或具体横向比例。",
                )

    if _nested_negative_prompt_issue(structured_prompt):
        _add_issue(
            issues,
            "nested_negative_prompt",
            "critical",
            "负面提示词被嵌入画面描述内部，JSON 结构会污染正向提示词。",
            "负面提示词必须与画面描述同级。",
        )
    if _has_sparse_fallback_shape(structured_prompt):
        _add_issue(
            issues,
            "sparse_fallback_structured_prompt",
            "critical",
            "结构化结果退化成单段“合并提示词”，专家分组没有成功落入 JSON。",
            "必须保留场景、人物、构图镜头、肢体动作、服装妆容、材质纹理、性内容边界等分组。",
        )

    if re.search(r"半蹲坐姿\s*\(Half-crouching Sit\)|Half-crouching Sit", text):
        _add_issue(
            issues,
            "pose_taxonomy_drift",
            "major",
            "输出使用了不稳定的混合姿态词“半蹲坐姿 (Half-crouching Sit)”。",
            "根据支撑点改写为蹲姿、下蹲、蹲坐、跪坐或坐姿中的一种。",
        )
    if re.search(r"双膝和小腿接触.*岩石|膝盖.*支撑.*岩石|膝盖.*支撑.*地面", text):
        _add_issue(
            issues,
            "support_point_conflict",
            "critical",
            "膝盖弯曲被误写成膝盖/小腿支撑在地面。",
            "只有真实压地时才写膝盖支撑；鞋底落地时写鞋底承重。",
        )
    if "小腿和脚踝区域被黑色丝袜包裹" in text or "小腿和脚踝区域被丝袜包裹" in text:
        _add_issue(
            issues,
            "occluded_ankle_overwrite",
            "major",
            "鞋口遮挡脚踝时，输出把脚踝补写成被丝袜包裹。",
            "只描述可见小腿/膝上腿部丝袜覆盖和鞋口遮挡边界。",
        )
    if "头部左上方发梢" in text:
        _add_issue(
            issues,
            "hand_endpoint_side_error",
            "major",
            "手部端点使用了不可靠的人物左右或头部左上方描述。",
            "按画面坐标写手靠近画面左/右侧太阳穴、发丝或头部边缘。",
        )
    if re.search(r"鞋子|运动鞋|脚|鞋底", positive_text) and re.search(r"上半身至大腿|上半身到大腿|头部到大腿", positive_text):
        _add_issue(
            issues,
            "crop_visibility_conflict",
            "critical",
            "鞋子/脚部信息与“裁切到大腿”的可见范围冲突。",
            "鞋子入镜时写近全身、头部到鞋子或全身入镜。",
        )
    if re.search(r"DMEE|DMME|DME", text) and re.search(r"褶皱|遮挡|字母|印花", text):
        _add_issue(
            issues,
            "unreliable_visible_text",
            "minor",
            "衣物文字在遮挡/褶皱条件下被强行识别为具体字母。",
            "看不准时写大号白色英文字母印花，不写具体字母。",
        )
    sexual_text = _sexual_boundary_text(structured_prompt) or positive_text
    if re.search(r"NSFW|adult_nudity|Adult_Nudity", sexual_text) and not re.search(
        r"全裸|裸体|裸露胸部|裸露乳房|性器官|生殖器|乳头|乳晕|外阴|阴道|阴茎|睾丸|肛门|性行为|插入|性液体|精液",
        sexual_text,
    ):
        _add_issue(
            issues,
            "nsfw_label_without_visible_evidence",
            "critical",
            "输出包含 NSFW/adult_nudity 标签，但缺少可见成人裸露或明确性内容证据。",
            "普通短裤、露腿、丝袜、日常服装不能标为 adult_nudity。",
        )
    if re.search(r"卧室|床|床品|窗帘", positive_text) and re.search(r"双臂自然垂", positive_text) and re.search(
        r"手.*抬|抬.*手|胸前|前景.*手|手.*模糊",
        positive_text,
    ):
        _add_issue(
            issues,
            "hand_action_conflict",
            "major",
            "卧室坐姿图中同时出现“双臂自然垂落”和手部抬起/前景手部描述。",
            "按画面坐标拆分两侧手臂，前景模糊手不能合并成双臂自然垂落。",
        )
    if re.search(r"卧室|床|床品|窗帘", positive_text) and re.search(r"过膝袜|长筒袜|丝袜|膝盖", positive_text) and re.search(
        r"头部到大腿中部|裁切.*大腿中部|上半身至大腿|上半身到大腿",
        positive_text,
    ):
        _add_issue(
            issues,
            "bedroom_crop_underdescribed",
            "major",
            "卧室坐姿图包含膝部/袜口信息，但裁切边界写成到大腿中部。",
            "可见膝部或长筒袜时，应写坐姿半身至膝部/大腿下方区域。",
        )
    if re.search(r"汽车|车内|方向盘|前排座椅|车窗", positive_text) and re.search(r"红色|百褶|短裙|黑色过膝丝袜", positive_text) and not re.search(
        r"跪坐|半跪坐|膝盖.*座椅|小腿.*座椅",
        positive_text,
    ):
        _add_issue(
            issues,
            "car_front_pose_missing",
            "major",
            "车内前排座椅图缺少跪坐/半跪坐和膝盖小腿支撑关系。",
            "车内前排人物姿态必须写面部朝镜头、躯干转向座椅靠背、膝盖/小腿支撑在座椅上。",
        )

    if expert_results is not None:
        seen = {str(item.get("id") or "").strip() for item in expert_results if isinstance(item, dict)}
        missing = [expert_id for expert_id in REQUIRED_EXPERT_IDS if expert_id not in seen]
        empty = [
            str(item.get("id") or "").strip()
            for item in expert_results
            if isinstance(item, dict)
            and item.get("missing")
        ]
        if missing:
            _add_issue(
                issues,
                "missing_expert_observations",
                "major",
                "专家观察缺少维度：" + ", ".join(missing),
                "每次专家反推必须保留 9 个专家维度。",
            )
        if empty:
            _add_issue(
                issues,
                "empty_expert_observations",
                "critical",
                "专家席位存在但缺少真实观察：" + ", ".join(empty),
                "缺失专家必须触发二次补问或降分，不能按满分通过。",
            )

    score = max(0, 100 - sum(_issue_penalty(issue["severity"]) for issue in issues))
    return {
        "skill_version": SKILL_VERSION,
        "score": score,
        "target_score": REPLICATION_TARGET_SCORE,
        "passed": score >= REPLICATION_TARGET_SCORE,
        "issues": issues,
        "issue_count": len(issues),
    }
