"""
modules/instance_manager.py — 实例生命周期管理。

Ez ComfyUI v4.0 重构。
集中管理 ComfyUI 实例的冷启动、健康检查、空闲回收、死实例检测。
"实例能不能用"的唯一权威。

依赖: config.py（仅限 ModelGroup 等常量引用）
"""

import asyncio
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable


# ── 健康快照 ────────────────────────────────────────────────────────────

@dataclass
class InstanceHealth:
    """单实例的健康状态快照。

    Attributes:
        name: 实例名称。
        up: 是否可访问（/system_stats 可达）。
        checked_at: 最后检查时间戳。
        model_group: 实例当前加载的模型组。
        pid: 实例进程 PID（0 表示未知）。
    """
    name: str
    up: bool
    checked_at: float
    model_group: str = ""
    pid: int = 0


# ── 实例管理器 ──────────────────────────────────────────────────────────

class InstanceManager:
    """实例生命周期管理器。

    单例模式。由 FastAPI lifespan 初始化一个模块级实例。
    nodes_provider 是返回 _get_enabled_instances() 的闭包，
    避免直接引用 app.py 的函数。
    """

    # ── 常量 ─────────────────────────────────────────────────────────────
    START_TIMEOUT: int = 300          # 冷启动超时（秒）
    HEALTH_CACHE_SECS: float = 15.0   # health() 缓存有效期
    GRACE_SECS: float = 90.0          # 启动后防御期（不死检测）
    IDLE_TIMEOUT: float = 900.0       # 空闲超时（秒，15 分钟）
    DEAD_CHECK_INTERVAL: float = 60.0  # 死实例检测间隔
    IDLE_REAP_INTERVAL: float = 60.0   # 空闲回收间隔
    HEALTH_TIMEOUT: float = 5.0        # 健康检查 HTTP 超时

    def __init__(self, nodes_provider: Callable[[], list[dict]]) -> None:
        """初始化实例管理器。

        Args:
            nodes_provider: 返回已启用实例列表的可调用对象。
                           通常是 _get_enabled_instances() 的闭包。
        """
        self._nodes_provider: Callable[[], list[dict]] = nodes_provider

        # 冷启动去重锁: {instance_name: asyncio.Lock}
        self._start_locks: dict[str, asyncio.Lock] = {}

        # 启动时间戳: {instance_name: start_time}
        self._start_grace: dict[str, float] = {}

        # 最后活跃时间戳: {instance_name: time}
        self._last_active: dict[str, float] = {}

        # 健康缓存: {instance_name: InstanceHealth}
        self._health_cache: dict[str, InstanceHealth] = {}

        # 后台任务（防止 GC）
        self._dead_check_task: asyncio.Task | None = None
        self._idle_reap_task: asyncio.Task | None = None

    # ── 公共 API ─────────────────────────────────────────────────────────

    async def ensure_running(self, instance: dict, timeout: int = 300) -> bool:
        """确保实例正在运行。如果未运行则启动它。

        幂等：同实例的并发调用共享同一个启动锁，仅启动一次。

        Args:
            instance: 实例字典（含 url/name/service/_node_id 等字段）。
            timeout: 等待就绪的超时秒数。

        Returns:
            True 表示实例已就绪。

        Raises:
            TimeoutError: 在超时内实例仍不可用。
        """
        name = instance.get("name", "unknown")
        url = instance.get("url", "")

        # 快速路径：已经 running
        if await self.health(instance):
            return True

        # 冷启动去重锁
        if name not in self._start_locks:
            self._start_locks[name] = asyncio.Lock()

        async with self._start_locks[name]:
            # 双重检查：拿到锁后可能已经被其他协程启动
            if await self.health(instance):
                return True

            # 记录开始时间
            self._start_grace[name] = time.time()

            # 执行启动
            started = await self.start(instance)
            if not started:
                raise TimeoutError(f"实例 {name} 启动命令失败")

            # 等待实例就绪
            deadline = time.time() + timeout
            while time.time() < deadline:
                await asyncio.sleep(2)
                if await self.health(instance, force=True):
                    self._last_active[name] = time.time()
                    return True

            # 更新最后的 health 尝试
            await self.health(instance, force=True)
            raise TimeoutError(f"实例 {name} 启动超时 ({timeout}s)")

    async def health(self, instance: dict, force: bool = False) -> bool:
        """检查实例是否健康（/system_stats 可达）。

        Results are cached for HEALTH_CACHE_SECS unless force=True.

        Args:
            instance: 实例字典。
            force: 是否强制刷新缓存。

        Returns:
            True 表示实例健康可访问。
        """
        name = instance.get("name", "unknown")
        url = instance.get("url", "")

        # 缓存命中
        if not force and name in self._health_cache:
            cached = self._health_cache[name]
            if time.time() - cached.checked_at < self.HEALTH_CACHE_SECS:
                return cached.up

        # 实时检查
        up = self._check_health(url)
        self._health_cache[name] = InstanceHealth(
            name=name,
            up=up,
            checked_at=time.time(),
            model_group=self._get_instance_group(name),
            pid=self._get_pid(name),
        )
        return up

    def mark_active(self, name: str) -> None:
        """标记实例为活跃状态（更新 last_active 时间戳）。

        由 job_runner 在出图完成后调用。

        Args:
            name: 实例名称。
        """
        self._last_active[name] = time.time()

    def is_grace(self, name: str) -> bool:
        """检查实例是否在防御期内（刚启动 90s 内）。

        防御期内死实例检测不触发误判。

        Args:
            name: 实例名称。

        Returns:
            True 表示仍在防御期内。
        """
        start_time = self._start_grace.get(name, 0)
        return start_time > 0 and (time.time() - start_time) < self.GRACE_SECS

    def get_health_summary(self) -> dict[str, InstanceHealth]:
        """获取全量健康快照。

        Returns:
            {instance_name: InstanceHealth} 字典。
        """
        return dict(self._health_cache)

    async def start(self, instance: dict) -> bool:
        """启动实例（调用 systemctl --user start）。

        Args:
            instance: 实例字典，需含 name/service/_node_id 等字段。

        Returns:
            True 表示启动命令已成功发出（不保证就绪）。
        """
        name = instance.get("name", "unknown")
        node = self._get_node_by_id(instance.get("_node_id", ""))

        if node:
            return self._run_instance_action(node, instance, "start")
        else:
            svc = f"comfyui-{name.lower()}"
            result = subprocess.run(
                ["systemctl", "--user", "start", svc],
                capture_output=True,
                timeout=10,
                env={
                    **os.environ,
                    "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
                    "XDG_RUNTIME_DIR": "/run/user/1000",
                },
            )
            return result.returncode == 0

    async def stop(self, instance: dict) -> bool:
        """停止实例（调用 systemctl --user stop）。

        Args:
            instance: 实例字典。

        Returns:
            True 表示停止命令已成功发出。
        """
        name = instance.get("name", "unknown")
        node = self._get_node_by_id(instance.get("_node_id", ""))

        if node:
            return self._run_instance_action(node, instance, "stop")
        else:
            svc = f"comfyui-{name.lower()}"
            result = subprocess.run(
                ["systemctl", "--user", "stop", svc],
                capture_output=True,
                timeout=10,
                env={
                    **os.environ,
                    "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
                    "XDG_RUNTIME_DIR": "/run/user/1000",
                },
            )
            return result.returncode == 0

    async def restart(self, instance: dict) -> bool:
        """重启实例。

        Args:
            instance: 实例字典。

        Returns:
            True 表示重启命令已成功发出。
        """
        await self.stop(instance)
        await asyncio.sleep(1)
        return await self.start(instance)

    # ── 后台协程 ─────────────────────────────────────────────────────────

    def start_background_tasks(self) -> None:
        """启动后台监控协程。由 lifespan 调用。"""
        self._dead_check_task = asyncio.create_task(self._dead_check_loop())
        self._idle_reap_task = asyncio.create_task(self._idle_reap_loop())

    async def stop_background_tasks(self) -> None:
        """停止后台监控协程。由 lifespan 关闭时调用。"""
        if self._dead_check_task:
            self._dead_check_task.cancel()
        if self._idle_reap_task:
            self._idle_reap_task.cancel()

    async def _dead_check_loop(self) -> None:
        """死实例检测循环（60s 间隔）。

        检查 systemd 服务 active 但 health() 返回 False 的实例。
        跳过防御期内的实例和已显式停止的实例。
        """
        while True:
            await asyncio.sleep(self.DEAD_CHECK_INTERVAL)
            for inst in self._nodes_provider():
                name = inst.get("name", "")
                if self.is_grace(name):
                    continue
                try:
                    up = await self.health(inst, force=True)
                    if not up:
                        svc_active = self._check_service_active(name)
                        if svc_active:
                            # 服务 active 但 health 失败 → 重启
                            await self.restart(inst)
                except Exception:
                    pass

    async def _idle_reap_loop(self) -> None:
        """空闲实例回收循环（60s 间隔）。

        检查 last_active > IDLE_TIMEOUT 的实例并停止。
        跳过正在执行 job 的实例。
        """
        while True:
            await asyncio.sleep(self.IDLE_REAP_INTERVAL)
            now = time.time()
            for inst in self._nodes_provider():
                name = inst.get("name", "")
                last_active = self._last_active.get(name, 0)
                if last_active > 0 and (now - last_active) > self.IDLE_TIMEOUT:
                    # 检查是否有活跃 job（通过系统负载判断）
                    if not self._has_active_jobs(name):
                        await self.stop(inst)

    # ── 内部辅助方法 ─────────────────────────────────────────────────────

    @staticmethod
    def _check_health(url: str) -> bool:
        """通过 /system_stats 端点检查 ComfyUI 实例存活。

        Args:
            url: 实例基础 URL。

        Returns:
            True 表示端点可达。
        """
        if not url:
            return False
        try:
            req = urllib.request.Request(f"{url.rstrip('/')}/system_stats")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError, ValueError):
            curl = shutil.which("curl")
            if not curl:
                return False
            try:
                result = subprocess.run(
                    [curl, "-sS", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "5", f"{url.rstrip('/')}/system_stats"],
                    capture_output=True,
                    text=True,
                    timeout=7,
                )
                return result.returncode == 0 and result.stdout.strip() == "200"
            except Exception:
                return False

    @staticmethod
    def _check_service_active(name: str) -> bool:
        """通过 systemctl --user is-active 检查 systemd 服务状态。

        Args:
            name: 实例名称。

        Returns:
            True 表示服务 active。
        """
        svc = f"comfyui-{name.lower()}"
        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", svc],
                capture_output=True,
                timeout=5,
                env={
                    **os.environ,
                    "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
                    "XDG_RUNTIME_DIR": "/run/user/1000",
                },
            )
            return result.stdout.decode().strip() == "active"
        except (subprocess.TimeoutExpired, OSError):
            return False

    @staticmethod
    def _get_pid(name: str) -> int:
        """获取实例进程 PID（通过 systemctl show）。

        Args:
            name: 实例名称。

        Returns:
            PID 或 0（未知）。
        """
        svc = f"comfyui-{name.lower()}"
        try:
            result = subprocess.run(
                ["systemctl", "--user", "show", "--property=MainPID", svc],
                capture_output=True,
                timeout=5,
            )
            pid_str = result.stdout.decode().strip()
            if "=" in pid_str:
                return int(pid_str.split("=", 1)[1])
            return 0
        except (subprocess.TimeoutExpired, OSError, ValueError):
            return 0

    def _get_instance_group(self, name: str) -> str:
        """获取实例当前模型组。

        Args:
            name: 实例名称。

        Returns:
            模型组名或空字符串。
        """
        # 通过 nodes_provider 查找实例的 group 信息
        for inst in self._nodes_provider():
            if inst.get("name") == name:
                return inst.get("group", "")
        return ""

    def _get_node_by_id(self, node_id: str) -> dict | None:
        """根据 _node_id 查找节点配置。

        Args:
            node_id: 节点 ID。

        Returns:
            节点字典或 None。
        """
        if not node_id:
            return None
        # nodes_provider 返回的是实例列表，节点信息在配置中
        # 这里简单返回 None 让调用方走 systemctl 路径
        return None

    @staticmethod
    def _run_instance_action(node: dict, instance: dict, action: str) -> bool:
        """执行节点 action（start/stop/restart）。

        Args:
            node: 节点配置字典。
            instance: 实例字典。
            action: 操作名称（start/stop/restart）。

        Returns:
            True 表示命令成功。
        """
        # 预留扩展：远程节点通过 SSH 执行
        name = instance.get("name", "unknown")
        svc = f"comfyui-{name.lower()}"
        try:
            result = subprocess.run(
                ["systemctl", "--user", action, svc],
                capture_output=True,
                timeout=10,
                env={
                    **os.environ,
                    "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
                    "XDG_RUNTIME_DIR": "/run/user/1000",
                },
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    @staticmethod
    def _has_active_jobs(name: str) -> bool:
        """检查实例是否有活跃 job（预留扩展）。

        Args:
            name: 实例名称。

        Returns:
            目前始终返回 False（由外部 JobRunner 维护活跃状态）。
        """
        # TODO: 后续通过 JobRunner 回调或 API 查询实际 job 状态
        return False
