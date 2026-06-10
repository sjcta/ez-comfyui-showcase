"""
modules/time_estimator.py — 为不发 WS progress 事件的节点做时长推算。

Ez ComfyUI v4.0 重构。
提供历史耗时记录、中位数估算和进度推算功能。
线程安全（类级别锁保护共享历史数据）。
"""

import threading
import statistics
from typing import ClassVar


class TimeEstimator:
    """时长推算器 — 为不发 WS progress 事件的节点（如 SeedVR2VideoUpscaler）提供进度估计。

    使用已完成任务的历史真实耗时（中位数法，抗 outliers）做估算。
    新节点在没有历史数据时按分辨率硬编码默认值。
    """

    _history: ClassVar[dict[str, list[float]]] = {}
    """node_class → [elapsed_seconds] 历史记录"""
    _max_samples: ClassVar[int] = 20
    """每类节点最多保留 20 条历史记录，FIFO 淘汰"""
    _lock: ClassVar[threading.Lock] = threading.Lock()
    """线程安全锁"""

    # ── 分辨率硬编码默认值（秒） ──────────────────────────────────────────
    _DEFAULT_ESTIMATES: ClassVar[dict[str, dict[int, float]]] = {
        # node_class → {resolution_hint_threshold: seconds}
        "SeedVR2VideoUpscaler": {
            4096: 120.0,  # 4K → 120s
            2048: 60.0,   # 2K → 60s
            0: 30.0,      # <2K → 30s
        },
    }
    """当无历史数据时，按节点类型和分辨率返回硬编码默认值。"""

    # ── 公共 API ─────────────────────────────────────────────────────────

    @classmethod
    def record(cls, node_class: str, elapsed: float) -> None:
        """记录一次节点完成耗时。

        Args:
            node_class: 节点类型（如 "SeedVR2VideoUpscaler"）。
            elapsed: 实际耗时秒数。
        """
        with cls._lock:
            if node_class not in cls._history:
                cls._history[node_class] = []
            hist = cls._history[node_class]
            hist.append(elapsed)
            if len(hist) > cls._max_samples:
                cls._history[node_class] = hist[-cls._max_samples:]

    @classmethod
    def estimate(cls, node_class: str, resolution_hint: int = 0) -> float:
        """估算某类节点的预期耗时（秒）。

        优先使用历史中位数；无历史时使用分辨率硬编码默认值；
        全无匹配则返回 30.0 秒保底。

        Args:
            node_class: 节点类型。
            resolution_hint: 分辨率提示（高度像素，如 4096/2048/0）。

        Returns:
            预期耗时（秒）。
        """
        with cls._lock:
            hist = cls._history.get(node_class, [])
            if hist:
                return statistics.median(hist)

        # 无历史 → 硬编码默认值
        defaults = cls._DEFAULT_ESTIMATES.get(node_class, {})
        if defaults:
            # 按分辨率最接近匹配
            sorted_thresholds = sorted(defaults.keys(), reverse=True)
            for threshold in sorted_thresholds:
                if resolution_hint >= threshold:
                    return defaults[threshold]
            return defaults.get(0, 30.0)

        return 30.0  # 通用保底

    @classmethod
    def progress(cls, node_class: str, elapsed: float,
                 resolution_hint: int = 0) -> tuple[float, float]:
        """计算节点当前进度百分比和预期耗时。

        Args:
            node_class: 节点类型。
            elapsed: 已耗时秒数。
            resolution_hint: 分辨率提示。

        Returns:
            (pct_in_node: float, expected_seconds: float)
            pct 被 clamp 在 [0, 95] 之间，保留 5% 给 completing 状态。
        """
        expected = cls.estimate(node_class, resolution_hint)
        if expected <= 0:
            return (0.0, 0.0)
        pct = min(elapsed / expected * 100.0, 95.0)
        return (pct, expected)
