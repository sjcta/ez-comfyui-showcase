"""
modules/instance_picker.py — 实例选择路由。

Ez ComfyUI v4.0 重构。
纯选择函数，根据工作流类型 + 实例状态，返回最佳实例。
不执行 cold-start，不检查 health（由调用方负责）。
不引用 app.py 的任何内容。

依赖: config.py (ModelGroup)
"""

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
    1. 硬路由: T2I→A, I2I→B（仅偏好，不可用时回退）
    2. 模型组亲和: 同组优先
    3. 空闲亲和: 空闲 + 同组 > 空闲 + 无组 > 最短队列

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

    # ── Phase 0: T2I → A, I2I → B（硬路由偏好） ─────────────────────
    if workflow_name:
        lower = workflow_name.lower()
        inst_a = _find_instance(available, "A")
        inst_b = _find_instance(available, "B")

        is_t2i = lower.startswith("t2i") or "_t2i" in lower or "-t2i" in lower
        is_i2i = lower.startswith("i2i") or "_i2i" in lower or "-i2i" in lower

        if is_t2i and inst_a:
            return inst_a
        if is_t2i and inst_b:
            return inst_b
        if is_i2i and inst_b:
            return inst_b
        if is_i2i and inst_a:
            return inst_a

    # ── Phase 1: 亲和性匹配 ──────────────────────────────────────────
    if workflow_name:
        affinity_name = affinity_getter(workflow_name)
        if affinity_name:
            match = _find_instance(available, affinity_name)
            if match:
                return match

    # ── Phase 2: 空闲亲和行 ──────────────────────────────────────────
    # 最优：空闲 + 同模型组
    for inst in available:
        sz = queue_sizes.get(inst["name"], 0)
        ig = _get_instance_group(inst["name"], group_getter)
        if sz == 0 and ig == wf_group:
            return inst

    # 次优：空闲 + 无加载组
    for inst in available:
        sz = queue_sizes.get(inst["name"], 0)
        ig = _get_instance_group(inst["name"], group_getter)
        if sz == 0 and not ig:
            return inst

    # ── Phase 3: 最短队列 ────────────────────────────────────────────
    best: dict | None = None
    best_load = 999

    # 优先选同组或空组
    for inst in available:
        load = queue_sizes.get(inst["name"], 0)
        if load >= best_load:
            continue
        ig = _get_instance_group(inst["name"], group_getter)
        if ig in (wf_group, ""):
            best, best_load = inst, load

    # 没有同组/空组匹配 → 选最短队列
    if not best:
        for inst in available:
            load = queue_sizes.get(inst["name"], 0)
            if load < best_load:
                best, best_load = inst, load

    return best or available[0]


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
