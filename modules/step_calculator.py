"""
modules/step_calculator.py — 进度计算引擎。

Ez ComfyUI v4.0 重构。
从 workflow JSON 解析节点拓扑，正确计算 total_units 和各节点权重。
解决原代码中 VAEDecode 被排除、sampler 初始化 1 unit 未计入 total、
denoise 未考虑、steps 链路解析不完整等系统性缺陷。

依赖: config.py (NodeCategory), time_estimator.py (TimeEstimator)
"""

import json
from dataclasses import dataclass, field
from typing import Any

from modules.config import NodeCategory
from modules.time_estimator import TimeEstimator


@dataclass
class StepInfo:
    """Workflow 进度信息的完整计算结果。

    由 StepCalculator.calculate() 一次性计算生成，
    供 WSTracker 全程引用，不中途修改。

    Attributes:
        total_units: 总单元数（100% 进度对应的分母）。
        node_weights: {node_id: unit_count} — 权重（0 表示仅时长推算）。
        node_labels: {node_id: 可读标签} — 如"采样中..."。
        sampler_steps: {node_id: effective_steps} — 采样器/超分器有效步数。
        node_order: 节点拓扑排序（processing order）。
        time_estimates: {node_id: expected_seconds} — 仅 weight=0 的节点。
    """
    total_units: float = 0.0
    node_weights: dict[str, float] = field(default_factory=dict)
    node_labels: dict[str, str] = field(default_factory=dict)
    sampler_steps: dict[str, int] = field(default_factory=dict)
    node_order: list[str] = field(default_factory=list)
    time_estimates: dict[str, float] = field(default_factory=dict)


class StepCalculator:
    """Workflow 进度计算器。

    输入: ComfyUI prompt 格式的 workflow dict
    输出: StepInfo dataclass

    用法:
        calculator = StepCalculator()
        step_info = calculator.calculate(workflow)
        print(step_info.total_units)
    """

    # ── 进度预算：采样/真超分是主要等待时间，其它节点只占准备/收尾 ──
    LONG_RUNNING_BUDGET: float = 90.0
    OTHER_NODE_BUDGET: float = 10.0

    # ── 主入口 ───────────────────────────────────────────────────────────

    def calculate(self, workflow: dict) -> StepInfo:
        """计算 workflow 的完整进度信息。

        遍历所有节点，逐类分配权重。

        Args:
            workflow: ComfyUI prompt 格式的工作流 JSON dict。

        Returns:
            StepInfo 包含完整的单元数、权重、标签、拓扑顺序等。
        """
        result = StepInfo()

        # 第一步：收集节点元数据
        node_types: dict[str, str] = {}
        node_titles: dict[str, str] = {}
        for nid, v in workflow.items():
            if isinstance(v, dict) and "class_type" in v:
                node_types[str(nid)] = v["class_type"]
                title = v.get("_meta", {}).get("title", "")
                if title:
                    node_titles[str(nid)] = title

        active_nodes: list[str] = []
        normal_node_units: dict[str, float] = {}

        # 第二步：按节点类型收集权重意图
        for nid in self._topological_sort(workflow):
            cls = node_types.get(nid, "")
            if not cls:
                continue

            result.node_order.append(nid)

            # 可读标签
            label = node_titles.get(nid, cls)
            result.node_labels[nid] = label

            # 分类处理
            cat = self.get_category(cls)

            if cls in ("SaveImage", "PreviewImage"):
                normal_node_units[nid] = 1.0

            elif cat == "free":
                # FREE 节点不计入进度
                result.node_weights[nid] = 0.0
                continue

            elif cat == "sampler":
                steps = self._calc_sampler_steps(nid, workflow)
                result.sampler_steps[nid] = steps
                active_nodes.append(nid)

            elif cat == "upscale":
                steps = self._calc_upscale_steps(nid, workflow)
                result.sampler_steps[nid] = steps
                if steps == 0:
                    # 无 steps 参数节点 → 时长推算
                    resolution = self._resolve_resolution_hint(workflow)
                    expected = TimeEstimator.estimate(cls, resolution)
                    result.time_estimates[nid] = expected
                active_nodes.append(nid)

            else:
                # LOADER / WEIGHT_1 / 未归类 → weight=1
                normal_node_units[nid] = 1.0

        # 第三步：把采样/超分固定在 90% 预算里，其它节点共享 10%。
        if active_nodes:
            active_weight = self.LONG_RUNNING_BUDGET / len(active_nodes)
            for nid in active_nodes:
                result.node_weights[nid] = active_weight

            normal_total = sum(normal_node_units.values())
            if normal_total > 0:
                for nid, units in normal_node_units.items():
                    result.node_weights[nid] = self.OTHER_NODE_BUDGET * (units / normal_total)
        else:
            result.node_weights.update(normal_node_units)

        # 第四步：累加 total_units
        result.total_units = float(sum(result.node_weights.values()))

        return result

    # ── 递归链路解析 ─────────────────────────────────────────────────────

    def resolve_steps(self, node_id: str, workflow: dict, depth: int = 0) -> int:
        """递归解析 ComfyUI 节点链路中的 steps 参数。

        支持 PrimitiveInt → inputs.value、ComfySwitchNode → 分支、多层链路。
        至多跟踪 5 层，超限返回 fallback 值 8。

        Args:
            node_id: 节点 ID。
            workflow: 完整工作流字典。
            depth: 当前递归深度（内部使用）。

        Returns:
            解析到的步骤数（int），超限返回 8。
        """
        if depth > 5:
            return 8

        node = workflow.get(node_id)
        if not isinstance(node, dict):
            return 8

        inputs = node.get("inputs", {})
        class_type = node.get("class_type", "")

        if class_type == "PrimitiveInt":
            val = inputs.get("value", 8)
            if isinstance(val, (int, float)):
                return max(1, int(val))
            return 8

        if class_type == "ComfySwitchNode":
            for branch in ("on_true", "on_false"):
                if branch in inputs:
                    val = inputs[branch]
                    if isinstance(val, list) and len(val) >= 1:
                        linked_id = str(val[0])
                        resolved = self.resolve_steps(linked_id, workflow, depth + 1)
                        if resolved:
                            return resolved
            return 8

        # 通用检查：是否有 value 或 INT 字段（PrimitiveNode 简化版）
        for key in ("value", "INT"):
            if key in inputs and isinstance(inputs[key], (int, float)):
                return max(1, int(inputs[key]))

        return 8

    # ── 分类查询 ─────────────────────────────────────────────────────────

    @staticmethod
    def get_category(class_type: str) -> str:
        """返回节点分类名。

        Args:
            class_type: 节点类名（如 "KSampler"）。

        Returns:
            分类名: 'sampler' | 'upscale' | 'free' | 'normal' | 'time_estimate'
        """
        if class_type in NodeCategory.SAMPLER:
            return "sampler"
        if class_type in NodeCategory.UPSCALE:
            return "upscale"
        if class_type in NodeCategory.FREE or class_type in NodeCategory.FREE_RUNTIME:
            return "free"
        if class_type in NodeCategory.LOADER or class_type in NodeCategory.WEIGHT_1:
            return "normal"
        return "normal"

    # ── 内部辅助 ─────────────────────────────────────────────────────────

    def _calc_sampler_steps(self, nid: str, workflow: dict) -> int:
        """计算采样器节点的有效步数。

        Args:
            nid: 节点 ID。
            workflow: 工作流字典。

        Returns:
            effective_steps
        """
        raw_steps = self._resolve_sampler_steps(nid, workflow)
        denoise = self._resolve_float_or_default(nid, "denoise", 1.0, workflow)
        effective = max(1, int(raw_steps * denoise))
        return effective

    def _resolve_sampler_steps(self, nid: str, workflow: dict) -> int:
        """Resolve sampler steps, including custom samplers fed by scheduler nodes."""
        direct_steps = self._resolve_steps_or_default(nid, "steps", 0, workflow)
        if direct_steps > 0:
            return direct_steps

        node = workflow.get(nid, {})
        inputs = node.get("inputs", {}) if isinstance(node, dict) else {}
        for key in ("sigmas", "scheduler"):
            linked = inputs.get(key)
            if isinstance(linked, list) and linked:
                linked_id = str(linked[0])
                linked_steps = self._resolve_steps_or_default(linked_id, "steps", 0, workflow)
                if linked_steps > 0:
                    return linked_steps

        return 8

    def _calc_upscale_steps(self, nid: str, workflow: dict) -> int:
        """计算超分器节点的有效步数。

        有 steps 参数 → 用 steps 拆分内部进度。
        无 steps 参数 → 返回 0，运行时优先使用 Comfy progress，缺失时用时长推算。

        Args:
            nid: 节点 ID。
            workflow: 工作流字典。

        Returns:
            effective_steps
        """
        node = workflow.get(nid, {})
        inputs = node.get("inputs", {}) if isinstance(node, dict) else {}
        raw_steps = inputs.get("steps", None)

        if raw_steps is None:
            return 0

        if isinstance(raw_steps, (int, float)):
            return max(1, int(raw_steps))

        if isinstance(raw_steps, list) and len(raw_steps) >= 1:
            linked_steps = self.resolve_steps(str(raw_steps[0]), workflow)
            return max(1, linked_steps)

        return 0

    def _resolve_steps_or_default(
        self, nid: str, key: str, default: int, workflow: dict
    ) -> int:
        """从节点 inputs 中解析 steps 参数，支持链路追踪。

        Args:
            nid: 节点 ID。
            key: 字段名（通常为 "steps"）。
            default: fallback 默认值。
            workflow: 工作流字典。

        Returns:
            解析到的整数值。
        """
        node = workflow.get(nid, {})
        inputs = node.get("inputs", {}) if isinstance(node, dict) else {}
        v = inputs.get(key, default)

        if isinstance(v, (int, float)):
            return int(v)

        if isinstance(v, list) and len(v) >= 1:
            linked_id = str(v[0])
            resolved = self.resolve_steps(linked_id, workflow)
            return resolved

        return default

    @staticmethod
    def _resolve_float_or_default(
        nid: str, key: str, default: float, workflow: dict
    ) -> float:
        """从节点 inputs 中解析 float 参数（如 denoise）。

        Args:
            nid: 节点 ID。
            key: 字段名（通常为 "denoise"）。
            default: fallback 默认值。
            workflow: 工作流字典。

        Returns:
            解析到的浮点值。链接节点返回 default（不可提前解析）。
        """
        node = workflow.get(nid, {})
        inputs = node.get("inputs", {}) if isinstance(node, dict) else {}
        v = inputs.get(key, default)

        if isinstance(v, (int, float)):
            return float(v)

        # 链接节点 → 不可提前解析，返回默认值
        if isinstance(v, list):
            return default

        return float(default)

    @staticmethod
    def _resolve_linked_number(workflow: dict, value: Any, default: int = 0, depth: int = 0) -> int:
        """Resolve numeric inputs that may be routed through Primitive nodes."""
        if depth > 5:
            return default
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return default
        if isinstance(value, list) and value:
            linked = workflow.get(str(value[0]))
            if not isinstance(linked, dict):
                return default
            inputs = linked.get("inputs", {})
            for key in ("value", "INT", "FLOAT", "resolution", "width", "height"):
                if key in inputs:
                    resolved = StepCalculator._resolve_linked_number(
                        workflow, inputs.get(key), default, depth + 1
                    )
                    if resolved != default:
                        return resolved
            return default
        return default

    @staticmethod
    def _resolve_resolution_hint(workflow: dict) -> int:
        """从 workflow 中尝试获取分辨率提示。

        查找 EmptyLatentImage/EmptySD3LatentImage 的 width/height。

        Args:
            workflow: 工作流字典。

        Returns:
            分辨率高度像素（如 4096/2048/0）。
        """
        max_dim = 0
        for nid, node in workflow.items():
            if not isinstance(node, dict):
                continue
            ct = node.get("class_type", "")
            if ct in ("EmptyLatentImage", "EmptySD3LatentImage", "EmptyFlux2LatentImage"):
                inputs = node.get("inputs", {})
                w = inputs.get("width", 0)
                h = inputs.get("height", 0)
                max_dim = max(
                    max_dim,
                    StepCalculator._resolve_linked_number(workflow, w),
                    StepCalculator._resolve_linked_number(workflow, h),
                )
            if ct in ("SeedVR2VideoUpscaler",):
                inputs = node.get("inputs", {})
                resolution = inputs.get("resolution", 0)
                max_dim = max(max_dim, StepCalculator._resolve_linked_number(workflow, resolution))
        return max_dim

    @staticmethod
    def _topological_sort(workflow: dict) -> list[str]:
        """对 workflow 节点进行拓扑排序。

        基于 ComfyUI 的 inputs 连接关系做简单拓扑排序。
        无法确定顺序时按节点 ID 字符串排序。

        Args:
            workflow: 工作流字典。

        Returns:
            排序后的节点 ID 列表。
        """
        # 收集所有节点 ID
        all_nodes: set[str] = set()
        edges: dict[str, set[str]] = {}  # node_id → {dependencies}

        for nid, node in workflow.items():
            if not isinstance(node, dict) or "class_type" not in node:
                continue
            all_nodes.add(nid)
            edges.setdefault(nid, set())
            inputs = node.get("inputs", {})
            for _key, val in inputs.items():
                if isinstance(val, list) and len(val) >= 1:
                    dep_id = str(val[0])
                    if dep_id in workflow:
                        # 找到对应的 node，检查是否有 class_type
                        if isinstance(workflow.get(dep_id), dict) and "class_type" in workflow[dep_id]:
                            edges[nid].add(dep_id)

        # Kahn 拓扑排序
        in_degree: dict[str, int] = {}
        for nid in all_nodes:
            in_degree[nid] = 0
        for nid, deps in edges.items():
            for dep in deps:
                if dep in in_degree:
                    in_degree[nid] = in_degree.get(nid, 0) + 1

        queue = [nid for nid in all_nodes if in_degree.get(nid, 0) == 0]
        queue.sort()  # 确定性排序
        result: list[str] = []

        while queue:
            nid = queue.pop(0)
            result.append(nid)
            for nid2, deps in edges.items():
                if nid in deps:
                    in_degree[nid2] = in_degree.get(nid2, 0) - 1
                    if in_degree[nid2] == 0:
                        queue.append(nid2)
                        queue.sort()

        # 补上未进入排序的节点
        remaining = all_nodes - set(result)
        result.extend(sorted(remaining))

        return result
