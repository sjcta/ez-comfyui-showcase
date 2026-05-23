"""
modules/instance_picker.py — 实例选择路由。

Ez ComfyUI v4.0 重构。
纯选择函数，根据工作流类型 + 实例状态，返回最佳实例。
不执行 cold-start，不检查 health（由调用方负责）。
不引用 app.py 的任何内容。

依赖: config.py (ModelGroup)
"""

import re
from typing import Callable

from modules.config import ModelGroup


def extract_model_group(workflow_name: str) -> str:
    """从工作流文件名中提取模型组名。

    代理到 config.ModelGroup.extract_model_group。

    Args:
        workflow_name: 工作流文件名（含路径或纯文件名）。

    Returns:
        模型组名。
    """
    return ModelGroup.extract_model_group(workflow_name)


def strict_preferred_instance_name(workflow_name: str) -> str:
    """Return the fixed routing lane for workflows that must not spill over."""
    profile = _workflow_profile(workflow_name)
    if profile.get("strict_preferred"):
        return str(profile.get("preferred") or "")
    return ""


async def pick_best_instance(
    instances: list[dict],
    workflow_name: str = "",
    affinity_getter: Callable[[str], str] = lambda _: "",
    health_check: Callable[[dict], bool] = lambda _: True,
    queue_size_getter: Callable[[dict], int] | None = None,
    group_getter: Callable[[str], str] | None = None,
) -> dict:
    """从可用实例中选择最佳实例。

    纯选择逻辑，不执行任何 IO（health/queue 查询通过注入的回调完成）。
    调用方负责传入实例列表、健康检查和队列深度查询。

    选择规则:
    1. 工作流类型只作为偏好，不再直接短路返回。
       T2I/放大 固定优先 A，I2I/视频 固定优先 B。
    2. 同时考虑远端 ComfyUI 队列和调用方注入的本地等待队列。
    3. 同模型组/空模型组优先，但忙碌实例会被惩罚，避免所有任务堆到 A。

    Args:
        instances: 实例字典列表，需含 name/url 字段。
        workflow_name: 工作流文件名，用于 T2I/I2I 路由和模型组提取。
        affinity_getter: 亲和性查询函数，参数为 (workflow_name)，返回实例名或空。
        health_check: 健康检查函数，参数为 (instance)，返回 bool。
        queue_size_getter: 队列深度查询函数，参数为 (instance)，返回队列大小。
                           None 表示不查询队列（可能阻塞）。
        group_getter: 实例模型组查询函数，参数为 (instance_name)，返回组名。
                      None 表示通过 extract_model_group 从 workflow_name 推断。

    Returns:
        选中的 instance dict。

    Raises:
        RuntimeError: 所有实例均不可用时抛出。
    """
    if not instances:
        raise RuntimeError("No available instances")

    # ── 过滤不可用实例 ─────────────────────────────────────────────────
    available = [inst for inst in instances if health_check(inst)]
    if not available:
        raise RuntimeError("No healthy instances available")

    # ── 获取队列大小（异步安全：通过回调注入） ──────────────────────────
    queue_sizes: dict[str, int] = {}
    if queue_size_getter:
        for inst in available:
            try:
                queue_sizes[inst["name"]] = queue_size_getter(inst)
            except Exception:
                queue_sizes[inst["name"]] = 999

    # ── 计算亲和信息 ───────────────────────────────────────────────────
    wf_group = extract_model_group(workflow_name) if workflow_name else ""

    # ── Phase 1: 亲和性匹配 ──────────────────────────────────────────
    if workflow_name:
        affinity_name = affinity_getter(workflow_name)
        if affinity_name:
            match = _find_instance(available, affinity_name)
            if match and queue_sizes.get(match["name"], 0) == 0:
                return match

    profile = _workflow_profile(workflow_name)
    strict_preferred = profile.get("strict_preferred")
    preferred = str(profile.get("preferred") or "")
    if strict_preferred and preferred:
        group_match = next(
            (
                inst for inst in available
                if wf_group and _get_instance_group(inst.get("name", ""), group_getter) == wf_group
            ),
            None,
        )
        if group_match:
            return group_match
        match = _find_instance(available, preferred)
        if match:
            return match
    ranked = sorted(
        available,
        key=lambda inst: _instance_score(inst, queue_sizes, wf_group, group_getter, profile),
    )
    return ranked[0]


def _workflow_profile(workflow_name: str) -> dict:
    lower = (workflow_name or "").lower()
    kind = "other"
    preferred = ""
    pressure = 2
    if _has_token(lower, "t2i"):
        kind = "t2i"
        preferred = "A"
        pressure = 1
    elif _has_token(lower, "i2i"):
        kind = "i2i"
        preferred = "B"
        pressure = 3
    elif _has_token(lower, "t2v") or _has_token(lower, "i2v"):
        kind = "video"
        preferred = "B"
        pressure = 3
    elif "upscale" in lower or "seedvr" in lower:
        kind = "upscale"
        preferred = "A"
        pressure = 3
    strict_preferred = kind in {"t2i", "i2i", "upscale", "video"}
    return {"kind": kind, "preferred": preferred, "pressure": pressure, "strict_preferred": strict_preferred}


def _has_token(text: str, token: str) -> bool:
    return bool(re.search(rf"(^|[-_]){re.escape(token)}($|[-_])", text or ""))


def _instance_score(
    inst: dict,
    queue_sizes: dict[str, int],
    workflow_group: str,
    group_getter: Callable[[str], str] | None,
    profile: dict,
) -> tuple[float, int, str]:
    name = inst.get("name", "")
    load = queue_sizes.get(name, 0)
    pressure = int(profile.get("pressure") or 2)
    preferred = str(profile.get("preferred") or "")
    score = float(load * (4 + pressure))

    if preferred and name == preferred:
        score -= 8 if pressure >= 3 else 3
    elif preferred:
        score += 2 if pressure >= 3 else 0

    loaded_group = _get_instance_group(name, group_getter)
    if workflow_group and loaded_group == workflow_group:
        score -= 5
    elif not loaded_group:
        score -= 1
    elif workflow_group:
        score += 2

    try:
        order = int(inst.get("sort_order", 9999))
    except (TypeError, ValueError):
        order = 9999
    return (score, order, name)


def _find_instance(instances: list[dict], name: str) -> dict | None:
    """按名称查找实例。

    Args:
        instances: 实例列表。
        name: 实例名称。

    Returns:
        实例字典或 None。
    """
    for inst in instances:
        if inst.get("name") == name:
            return inst
    return None


def _get_instance_group(
    instance_name: str,
    group_getter: Callable[[str], str] | None,
) -> str:
    """获取实例的当前模型组。

    Args:
        instance_name: 实例名称。
        group_getter: 模型组查询函数。

    Returns:
        模型组名或空字符串。
    """
    if group_getter:
        try:
            return group_getter(instance_name) or ""
        except Exception:
            return ""
    return ""
