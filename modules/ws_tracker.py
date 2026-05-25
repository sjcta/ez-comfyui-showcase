"""
modules/ws_tracker.py — WebSocket 通信 + 实时进度追踪 + HTTP fallback + 断线重连。

Ez ComfyUI v4.0 重构。
从 app.py 的 comfyui_ws_track() 提取并重构。

依赖: step_calculator.py (StepInfo), time_estimator.py (TimeEstimator)
"""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import websockets.client

from modules.config import NODE_STATUS_MAP
from modules.step_calculator import StepInfo
from modules.time_estimator import TimeEstimator


# ── 返回类型 ────────────────────────────────────────────────────────────

@dataclass
class TrackResult:
    """WebSocket 追踪的最终结果。

    Attributes:
        ok: 出图是否成功。
        prompt_id: ComfyUI 返回的 prompt_id。
        elapsed: 总耗时（秒）。
    """
    ok: bool
    prompt_id: str
    elapsed: float


class PromptStartTimeout(TimeoutError):
    """Raised when ComfyUI accepts a prompt but does not begin executing it soon."""

    def __init__(self, prompt_id: str, timeout: float) -> None:
        super().__init__(f"Prompt {prompt_id[-12:]} 启动超时 ({timeout:.0f}s)")
        self.prompt_id = prompt_id
        self.timeout = timeout


class PromptSubmitError(RuntimeError):
    """Raised when ComfyUI rejects the prompt before it enters the queue."""


def _is_transient_http_error(err: Exception) -> bool:
    """Return True for transport errors that should not stop polling."""
    text = str(err)
    transient_markers = (
        "Connection refused",
        "Errno 61",
        "Errno 111",
        "timed out",
        "Temporary failure",
        "Connection reset",
        "Remote end closed connection",
    )
    return any(marker in text for marker in transient_markers)


# ── HTTP 辅助函数（纯同步，通过 asyncio.to_thread 调用） ────────────────

import urllib.request
import urllib.error


def _http_post(url: str, data: dict) -> dict:
    """同步 HTTP POST 请求。

    Args:
        url: 完整 URL。
        data: JSON 可序列化的请求体。

    Returns:
        响应 JSON dict。

    Raises:
        RuntimeError: 请求失败或非 200 响应。
    """
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace").strip()
        except Exception:
            body = ""
        detail = f"HTTP Error {e.code}: {e.reason}"
        if body:
            detail = f"{detail}; {body[:500]}"
        raise RuntimeError(f"HTTP POST {url} 失败: {detail}") from e
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"HTTP POST {url} 失败: {e}") from e


def _http_get(url: str, timeout: int = 15) -> dict | list:
    """同步 HTTP GET 请求。

    Args:
        url: 完整 URL。
        timeout: 超时秒数。

    Returns:
        响应 JSON。

    Raises:
        RuntimeError: 请求失败。
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"HTTP GET {url} 失败: {e}") from e


def _build_ws_url(instance_url: str, client_id: str) -> str:
    """将 HTTP URL 转换为 WebSocket URL。

    Args:
        instance_url: ComfyUI 实例的 HTTP URL（如 http://127.0.0.1:8190）。
        client_id: 客户端 ID。

    Returns:
        WebSocket URL（如 ws://127.0.0.1:8190/ws?clientId=xxx）。
    """
    ws_base = instance_url.replace("http://", "ws://").replace("https://", "wss://")
    return f"{ws_base}/ws?clientId={client_id}"


# ── WSTracker ───────────────────────────────────────────────────────────

class WSTracker:
    """WebSocket 通信追踪器。

    负责：
    - WebSocket 连接（3 次重试）
    - 提交 workflow 到 ComfyUI
    - 实时进度追踪（通过 StepInfo 驱动）
    - 断线退化 HTTP polling
    - 超时检测

    用法:
        tracker = WSTracker(job_id, workflow, step_info, instance_url, node_types)
        tracker.set_progress_callback(my_async_callback)
        result = await tracker.track(timeout=900)
    """

    # ── 常量 ────────────────────────────────────────────────────────────
    WS_RETRY_COUNT: int = 3
    """WebSocket 连接重试次数"""
    WS_RETRY_DELAY: float = 2.0
    """重试间隔（秒）"""
    WS_SILENT_TIMEOUT: float = 300.0
    """WS 无消息超时（秒），退化 HTTP"""
    PROMPT_START_TIMEOUT: float = 45.0
    """POST /prompt 后等待 ComfyUI 开始执行的最长时间（秒）"""
    HTTP_POLL_INTERVAL: float = 3.0
    """HTTP polling 间隔（秒）"""
    PROGRESS_REFRESH_INTERVAL: float = 5.0
    """时长推算节点刷新间隔（秒）"""

    def __init__(
        self,
        job_id: str,
        workflow: dict,
        step_info: StepInfo,
        instance_url: str,
        node_types: dict[str, str],
        progress_callback: Callable[[dict], Awaitable[None]] | None = None,
        log_callback: Callable[[str, str, str, str], None] | None = None,
        client_id: str | None = None,
    ) -> None:
        """初始化 WSTracker。

        Args:
            job_id: 任务 ID。
            workflow: ComfyUI prompt 格式的工作流。
            step_info: StepCalculator 计算出的进度信息。
            instance_url: ComfyUI 实例 URL。
            node_types: {node_id: class_type} 映射。
            progress_callback: 进度更新的异步回调，参数为进度 dict。
            log_callback: 日志回调，参数为 (level, phase, msg, job_id)。
            client_id: 可复用的 ComfyUI client_id，用于服务重启后重连同一 WS 客户端。
        """
        self._job_id: str = job_id
        self._workflow: dict = workflow
        self._step_info: StepInfo = step_info
        self._instance_url: str = instance_url
        self._node_types: dict[str, str] = node_types
        self._node_titles: dict[str, str] = {}

        # 从 workflow 提取节点标题
        for nid, v in workflow.items():
            if isinstance(v, dict):
                title = v.get("_meta", {}).get("title", "")
                if title:
                    self._node_titles[str(nid)] = title

        self._progress_callback: Callable[[dict], Awaitable[None]] | None = progress_callback
        self._log_callback: Callable[[str, str, str, str], None] | None = log_callback

        # 运行时状态
        self._client_id: str = str(client_id or uuid.uuid4().hex[:12])
        self._prompt_id: str = ""
        self._reset_runtime_state(clear_prompt_id=False)

    def _reset_runtime_state(self, clear_prompt_id: bool) -> None:
        if clear_prompt_id:
            self._prompt_id = ""
        self._completed_units: float = 0.0
        self._last_prog: int = 0
        self._current_node_id: str = ""
        self._current_node_cls: str = ""
        self._sampler_cur: int = 0
        self._sampler_total: int = 0
        self._completed_node_ids: set[str] = set()
        self._node_entered_at: dict[str, float] = {}  # time-estimated node → entry time
        self._time_node_units: dict[str, float] = {}  # time-estimated node → contributed units
        self._start_time: float = 0.0
        self._cancelled: bool = False
        self._workflow_done: bool = False
        self._last_pct: float = 0.0
        self._prompt_started: bool = False

    @property
    def client_id(self) -> str:
        return self._client_id

    # ── 注入 ────────────────────────────────────────────────────────────

    def set_progress_callback(self, callback: Callable[[dict], Awaitable[None]]) -> None:
        """设置进度更新回调。

        Args:
            callback: 异步回调，参数为 {pct, message, current_node} 等。
        """
        self._progress_callback = callback

    def set_log_callback(self, callback: Callable[[str, str, str, str], None]) -> None:
        """设置日志回调。

        Args:
            callback: 日志回调，参数为 (level, phase, msg, job_id)。
        """
        self._log_callback = callback

    # ── 主入口 ──────────────────────────────────────────────────────────

    async def track(self, timeout: int = 900) -> TrackResult:
        """执行 WebSocket 追踪主流程。

        步骤:
        1. WS 连接（最多 3 次重试）
        2. POST /prompt 提交 workflow
        3. WS 收消息直到完成或超时
        4. WS 断连 → 退化 HTTP polling
        5. 返回 TrackResult

        Args:
            timeout: 总超时秒数。

        Returns:
            TrackResult 包含是否成功、prompt_id、耗时。
        """
        self._start_time = time.time()
        self._reset_runtime_state(clear_prompt_id=True)

        total_units = self._step_info.total_units
        node_weights = self._step_info.node_weights

        ws_ok = False
        ws = None

        # ── Phase 1: WS 连接（3 次重试） ──────────────────────────────
        ws_url = _build_ws_url(self._instance_url, self._client_id)
        for attempt in range(self.WS_RETRY_COUNT):
            if self._cancelled:
                break
            try:
                ws = await websockets.client.connect(ws_url, open_timeout=10)
                ws_ok = True
                break
            except (ConnectionRefusedError, OSError, asyncio.TimeoutError,
                    websockets.exceptions.WebSocketException) as e:
                self._log("warn", "ws", f"WS 连接尝试 {attempt + 1}/{self.WS_RETRY_COUNT} 失败: {e}",
                          self._job_id)
                if attempt < self.WS_RETRY_COUNT - 1:
                    await asyncio.sleep(self.WS_RETRY_DELAY)

        if not ws_ok:
            self._log("warn", "ws", "WS 连接全部失败，退化 HTTP", self._job_id)
            return await self._http_fallback_track(timeout)

        # ── Phase 2: 提交 prompt ──────────────────────────────────────
        await self._report_progress({
            "pct": 0, "message": "提交工作流...", "current_node": ""
        })
        try:
            resp = await asyncio.to_thread(
                _http_post,
                f"{self._instance_url.rstrip('/')}/prompt",
                {"prompt": self._workflow, "client_id": self._client_id},
            )
            self._prompt_id = resp.get("prompt_id", "")
            if not self._prompt_id:
                raise RuntimeError(
                    f"ComfyUI 返回无 prompt_id: {json.dumps(resp)[:200]}"
                )
            await self._report_progress({
                "pct": 0, "message": "等待实例开始执行...", "current_node": ""
            })
        except Exception as e:
            if ws:
                await ws.close()
            self._log("error", "ws", f"提交 prompt 失败: {e}", self._job_id)
            raise PromptSubmitError(str(e)) from e

        self._log("info", "ws", f"Prompt 已提交: {self._prompt_id[-12:]}", self._job_id)

        # ── Phase 3: WS 追踪循环 ─────────────────────────────────────
        try:
            result = await self._ws_track_loop(ws, timeout)
            elapsed = time.time() - self._start_time
            await ws.close()
            return result
        except Exception as e:
            await ws.close()
            if isinstance(e, PromptStartTimeout):
                raise
            # 退化 HTTP polling
            self._log("warn", "ws", f"WS 异常: {e}，退化 HTTP", self._job_id)
            return await self._http_fallback_track(timeout)

    async def resume(self, prompt_id: str, timeout: int = 900) -> TrackResult:
        """重连已有 ComfyUI prompt 的 WebSocket，仅恢复实时事件，不重新提交。

        Args:
            prompt_id: 已提交到 ComfyUI 的 prompt_id。
            timeout: WS 重连追踪最长等待秒数。

        Returns:
            TrackResult。未收到完成事件时返回 ok=False，让上层继续 queue/history 兜底。
        """
        self._start_time = time.time()
        self._reset_runtime_state(clear_prompt_id=True)
        self._prompt_id = str(prompt_id or "")
        if not self._prompt_id:
            return TrackResult(ok=False, prompt_id="", elapsed=0.0)
        self._prompt_started = True
        ws_url = _build_ws_url(self._instance_url, self._client_id)
        try:
            ws = await websockets.client.connect(ws_url, open_timeout=10)
        except (ConnectionRefusedError, OSError, asyncio.TimeoutError,
                websockets.exceptions.WebSocketException) as e:
            self._log("warn", "ws", f"恢复 WS 连接失败: {e}", self._job_id)
            return TrackResult(ok=False, prompt_id=self._prompt_id, elapsed=time.time() - self._start_time)
        try:
            return await self._ws_track_loop(
                ws,
                timeout,
                allow_http_fallback=False,
                enforce_prompt_start_timeout=False,
            )
        finally:
            try:
                await ws.close()
            except Exception:
                pass

    def cancel(self) -> None:
        """取消追踪。设置取消标志，下次迭代将停止。"""
        self._cancelled = True

    def get_current_progress(self) -> dict:
        """获取当前进度快照。

        Returns:
            {pct: float, message: str, current_node: str, prompt_id: str}
        """
        pct = self._calc_pct()
        msg = self._build_status_message(pct)
        return {
            "pct": pct,
            "message": msg,
            "current_node": self._current_node_cls,
            "prompt_id": self._prompt_id,
        }

    # ── WS 追踪循环 ─────────────────────────────────────────────────────

    async def _ws_track_loop(
        self,
        ws: Any,
        timeout: int,
        allow_http_fallback: bool = True,
        enforce_prompt_start_timeout: bool = True,
    ) -> TrackResult:
        """WS 消息接收循环。

        处理 executing/progress/executed/execution_error/execution_start 消息。
        超时 300s 无消息时退化 HTTP polling。

        Args:
            ws: WebSocket 连接对象。
            timeout: 总超时秒数。

        Returns:
            TrackResult。

        Raises:
            RuntimeError: execution_error 时抛出。
        """
        start = time.time()
        total_units = self._step_info.total_units
        node_weights = self._step_info.node_weights
        last_ws_msg = time.time()
        prompt_wait_started = time.time()

        # 启动定时进度刷新（处理 weight=0 的时长推算节点）
        refresh_task = asyncio.create_task(self._refresh_delayed_node_loop())

        try:
            while time.time() - start < timeout and not self._workflow_done:
                if self._cancelled:
                    return TrackResult(
                        ok=False, prompt_id=self._prompt_id,
                        elapsed=time.time() - self._start_time,
                    )

                # 检查 WS 静默超时
                if time.time() - last_ws_msg > self.WS_SILENT_TIMEOUT:
                    self._log("warn", "ws", f"WS 无消息 {self.WS_SILENT_TIMEOUT:.0f}s，退化 HTTP",
                              self._job_id)
                    break

                now = time.time()
                if (
                    enforce_prompt_start_timeout
                    and
                    self._prompt_id
                    and not self._prompt_started
                    and now - prompt_wait_started > self.PROMPT_START_TIMEOUT
                ):
                    self._log(
                        "warn", "ws",
                        f"Prompt {self._prompt_id[-12:]} {self.PROMPT_START_TIMEOUT:.0f}s 未开始执行",
                        self._job_id,
                    )
                    raise PromptStartTimeout(self._prompt_id, self.PROMPT_START_TIMEOUT)

                recv_timeout = min(300.0, max(0.1, self.WS_SILENT_TIMEOUT - (now - last_ws_msg)))
                if enforce_prompt_start_timeout and self._prompt_id and not self._prompt_started:
                    recv_timeout = min(
                        recv_timeout,
                        max(0.1, self.PROMPT_START_TIMEOUT - (now - prompt_wait_started)),
                    )

                try:
                    async with asyncio.timeout(recv_timeout):
                        raw = await ws.recv()
                    last_ws_msg = time.time()
                except asyncio.TimeoutError:
                    if enforce_prompt_start_timeout and self._prompt_id and not self._prompt_started:
                        self._log(
                            "warn", "ws",
                            f"Prompt {self._prompt_id[-12:]} {self.PROMPT_START_TIMEOUT:.0f}s 未开始执行",
                            self._job_id,
                        )
                        raise PromptStartTimeout(self._prompt_id, self.PROMPT_START_TIMEOUT)
                    self._log("warn", "ws", "WS recv 超时，退化 HTTP", self._job_id)
                    break
                except websockets.exceptions.ConnectionClosed:
                    self._log("warn", "ws", "WS 连接断开，退化 HTTP", self._job_id)
                    break

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type", "")
                data = msg.get("data", {})

                # 过滤其他 prompt_id 的消息（多 job 共存的 ComfyUI 实例）
                msg_pid = data.get("prompt_id", "")
                if msg_pid and self._prompt_id and msg_pid != self._prompt_id:
                    continue

                if msg_type == "executing":
                    self._prompt_started = True
                    await self._handle_executing(data, total_units, node_weights)

                elif msg_type == "progress":
                    self._prompt_started = True
                    await self._handle_progress(data, total_units, node_weights)

                elif msg_type == "executed":
                    self._prompt_started = True
                    await self._handle_executed(data)

                elif msg_type == "execution_error":
                    self._handle_error(data)
                    break

                elif msg_type == "execution_start":
                    self._prompt_started = True
                    self._log("info", "start", "Workflow execution started", self._job_id)

            # ── WS 循环结束 → 检查是否已完成 ──────────────────────────
            if self._completed_units >= total_units and total_units > 0:
                elapsed = time.time() - self._start_time
                return TrackResult(ok=True, prompt_id=self._prompt_id, elapsed=elapsed)

        except RuntimeError:
            raise
        finally:
            refresh_task.cancel()
            try:
                await refresh_task
            except asyncio.CancelledError:
                pass

        # ── 退化 HTTP polling ─────────────────────────────────────────
        if not allow_http_fallback:
            return TrackResult(
                ok=False,
                prompt_id=self._prompt_id,
                elapsed=time.time() - self._start_time,
            )
        return await self._http_poll_track(timeout - (time.time() - start))

    async def _http_fallback_track(self, timeout: int) -> TrackResult:
        """纯 HTTP fallback：通过 POST /prompt 提交后 polling /history。

        Args:
            timeout: 剩余超时秒数。

        Returns:
            TrackResult。
        """
        if not self._prompt_id:
            try:
                resp = await asyncio.to_thread(
                    _http_post,
                    f"{self._instance_url.rstrip('/')}/prompt",
                    {"prompt": self._workflow, "client_id": self._client_id},
                )
                self._prompt_id = resp.get("prompt_id", "")
            except Exception as e:
                self._log("error", "http", f"HTTP fallback prompt 提交失败: {e}", self._job_id)
                raise PromptSubmitError(str(e)) from e

        return await self._http_poll_track(timeout)

    async def _http_poll_track(self, timeout: int) -> TrackResult:
        """HTTP polling 追踪：轮询 /history/{prompt_id}。

        Args:
            timeout: 剩余超时秒数。

        Returns:
            TrackResult。
        """
        start_remaining = time.time()
        while time.time() - start_remaining < timeout:
            if self._cancelled:
                return TrackResult(
                    ok=False, prompt_id=self._prompt_id,
                    elapsed=time.time() - self._start_time,
                )
            await asyncio.sleep(self.HTTP_POLL_INTERVAL)
            try:
                hist = await asyncio.to_thread(
                    _http_get,
                    f"{self._instance_url.rstrip('/')}/history/{self._prompt_id}",
                )
                if isinstance(hist, dict) and self._prompt_id in hist:
                    entry = hist[self._prompt_id]
                    status = entry.get("status", {})
                    if status.get("completed", False):
                        elapsed = time.time() - self._start_time
                        self._completed_units = self._step_info.total_units
                        await self._report_progress({
                            "pct": 100, "message": "完成",
                            "current_node": "",
                        })
                        return TrackResult(ok=True, prompt_id=self._prompt_id, elapsed=elapsed)
                    if status.get("status_str") == "error":
                        msgs = status.get("messages", [])
                        raise RuntimeError(str(msgs)[:300] if msgs else "ComfyUI 执行出错")
            except RuntimeError as e:
                if _is_transient_http_error(e):
                    continue
                raise
            except Exception:
                pass

        raise TimeoutError(f"出图超时 ({timeout}s)")

    # ── 消息处理 ─────────────────────────────────────────────────────────

    async def _handle_executing(
        self, data: dict, total_units: int, node_weights: dict[str, float]
    ) -> None:
        """处理 executing 消息。

        Args:
            data: 消息 data 字段。
            total_units: 总进度单元数。
            node_weights: 节点权重映射。
        """
        node_id = data.get("node")
        if node_id is None:
            # executing:null → 完成
            self._completed_units = total_units
            pct = self._calc_pct()
            await self._report_progress({
                "pct": pct, "message": "完成", "current_node": "",
            })
            self._log("info", "complete", "Workflow finished", self._job_id)
            self._workflow_done = True  # 标记完成，让主循环退出
            return

        nid = str(node_id)
        if self._current_node_id and self._current_node_id != nid:
            self._mark_node_completed(self._current_node_id)
        cls = self._node_types.get(nid, "")
        self._current_node_id = nid
        self._current_node_cls = cls
        title = self._node_titles.get(nid, cls or nid)
        weight = node_weights.get(nid, 1.0)
        cum_pct = self._calc_pct()
        self._log("info", "node", f"[{cls}] {title} ({cum_pct:.0f}%)", self._job_id)

        # 采样器/超分器：不在此加 weight（由 progress 事件逐 step 累加）。
        # 普通节点也必须等 executed 事件才计入完成；否则 VAEDecode/SaveImage
        # 一开始执行就会把整体进度推到 100%。
        if cls in NodeCategoryDict.SAMPLER or cls in NodeCategoryDict.UPSCALE:
            self._last_prog = 0
            self._sampler_cur = 0
            self._sampler_total = 0
            if nid in self._step_info.time_estimates:
                self._node_entered_at[nid] = time.time()
                self._time_node_units.setdefault(nid, 0.0)
        elif weight <= 0:
            # weight=0 节点 → 记录进入时间，供时长推算
            self._node_entered_at[nid] = time.time()

        pct = self._calc_pct()
        await self._report_progress({
            "pct": pct,
            "message": self._build_status_message(pct),
            "current_node": cls,
        })

    async def _handle_progress(
        self, data: dict, total_units: int, node_weights: dict[str, float]
    ) -> None:
        """处理 progress 消息。

        Args:
            data: 消息 data 字段。
            total_units: 总进度单元数。
            node_weights: 节点权重映射。
        """
        cur = data.get("value", 0)
        total = data.get("max", 1)
        self._sampler_cur = cur
        self._sampler_total = total

        node_id = str(data.get("node", "")) if data.get("node") is not None else self._current_node_id
        if cur > self._last_prog:
            weight = node_weights.get(node_id, 1.0)
            if node_id in self._step_info.time_estimates and weight > 0:
                contribution = min(max(cur / max(total, 1), 0.0), 0.98) * weight
                previous = self._time_node_units.get(node_id, 0.0)
                if contribution > previous:
                    self._completed_units += contribution - previous
                    self._time_node_units[node_id] = contribution
            elif weight > 0:
                delta = (cur - self._last_prog) / total * weight
                self._completed_units += delta
            else:
                delta = (cur - self._last_prog) / total * 1.0
                self._completed_units += delta
            self._last_prog = cur

        # 更新 current_node_cls
        prog_node = data.get("node")
        if prog_node is not None:
            self._current_node_id = str(prog_node)
            cls = self._node_types.get(str(prog_node), "")
            if cls:
                self._current_node_cls = cls

        pct = self._calc_pct()
        await self._report_progress({
            "pct": pct,
            "message": self._build_status_message(pct),
            "current_node": self._current_node_cls,
            "sampler_cur": self._sampler_cur,
            "sampler_total": self._sampler_total,
        })

    async def _handle_executed(self, data: dict) -> None:
        """处理 executed 消息。

        Args:
            data: 消息 data 字段。
        """
        enode = data.get("node")
        if enode is not None:
            node_id = str(enode)
            cls = self._node_types.get(node_id, "")
            if cls:
                self._current_node_id = node_id
                self._current_node_cls = cls
                self._mark_node_completed(node_id)
                self._log("info", "done", f"[{cls}] Completed ({self._calc_pct():.0f}%)", self._job_id)

        pct = self._calc_pct()
        await self._report_progress({
            "pct": pct,
            "message": self._build_status_message(pct),
            "current_node": self._current_node_cls,
        })

    def _mark_node_completed(self, node_id: str) -> None:
        """Mark a non-progress-reporting node done once ComfyUI moves past it."""
        node_id = str(node_id or "")
        if not node_id or node_id in self._completed_node_ids:
            return
        cls = self._node_types.get(node_id, "")
        if (
            not cls
            or cls in NodeCategoryDict.SAMPLER
            or (cls in NodeCategoryDict.UPSCALE and node_id not in self._step_info.time_estimates)
        ):
            return
        weight = self._step_info.node_weights.get(node_id, 1.0)
        if weight > 0:
            previous = self._time_node_units.get(node_id, 0.0)
            self._completed_units += max(0.0, weight - previous)
            self._time_node_units[node_id] = weight
        self._completed_node_ids.add(node_id)
        entered = self._node_entered_at.pop(node_id, None)
        if entered and node_id in self._step_info.time_estimates:
            TimeEstimator.record(cls, max(0.0, time.time() - entered))

    def _handle_error(self, data: dict) -> None:
        """处理 execution_error 消息。

        Args:
            data: 消息 data 字段。

        Raises:
            RuntimeError: 始终抛出，包含错误信息。
        """
        err = data.get("exception_message", str(data)[:300])
        self._log("error", "error", f"ComfyUI execution error: {err[:100]}", self._job_id)
        raise RuntimeError(f"ComfyUI: {err}")

    # ── 时长推算节点刷新循环 ─────────────────────────────────────────────

    async def _refresh_delayed_node_loop(self) -> None:
        """定时刷新 weight=0 的时长推算节点的进度。

        每 PROGRESS_REFRESH_INTERVAL 秒检查一次，
        通过 TimeEstimator.progress() 计算已进入节点的时间占比，
        并更新 completed_units。
        """
        while True:
            await asyncio.sleep(self.PROGRESS_REFRESH_INTERVAL)
            await self._refresh_delayed_node_loop_once_for_test()

    async def _refresh_delayed_node_loop_once_for_test(self) -> None:
        """Refresh time-estimated nodes once. Used by the loop and unit tests."""
        if not self._node_entered_at:
            return

        now = time.time()
        for node_id, entered in list(self._node_entered_at.items()):
            cls = self._node_types.get(node_id, "")
            if not cls:
                continue
            elapsed = now - entered
            weight = self._step_info.node_weights.get(node_id, 0.0)
            expected = self._step_info.time_estimates.get(node_id, 0.0)
            if weight > 0.0 and expected > 0:
                contribution = min(elapsed / expected, 0.95) * weight
                previous = self._time_node_units.get(node_id, 0.0)
                if contribution > previous:
                    self._completed_units += contribution - previous
                    self._time_node_units[node_id] = contribution
                    pct = self._calc_pct()
                    await self._report_progress({
                        "pct": pct,
                        "message": self._build_status_message(pct),
                        "current_node": cls,
                    })

    # ── 工具方法 ────────────────────────────────────────────────────────

    def _calc_pct(self) -> float:
        """计算当前进度百分比。

        Returns:
            0~100 的浮点数。
        """
        total = self._step_info.total_units
        if total <= 0:
            raw = 0.0
        else:
            raw = min(1.0, max(0.0, self._completed_units / total))
        if self._workflow_done or raw >= 1.0:
            pct = 100.0
        else:
            pct = raw * 100.0
        self._last_pct = max(self._last_pct, pct)
        return self._last_pct

    def _build_status_message(self, pct: float) -> str:
        """构造可读的状态消息。

        Args:
            pct: 当前进度百分比。

        Returns:
            状态字符串。
        """
        cls = self._current_node_cls
        label = NODE_STATUS_MAP.get(cls, cls) if cls else ""

        if not label and self._completed_units == 0:
            return "准备中..."

        if label and self._sampler_total > 0:
            if "采样" in label and "准备" not in label:
                return f"{label} {self._sampler_cur}/{self._sampler_total}"
            if "超分" in label and "准备" not in label:
                return f"{label} {self._sampler_cur}/{self._sampler_total}"

        if label and "采样" in label:
            return "采样准备中"
        if label and "超分" in label:
            return "超分准备中"

        if label:
            return label

        return f"{pct:.0f}%..."

    async def _report_progress(self, progress: dict) -> None:
        """报告进度更新，自动注入 prompt_id。

        Args:
            progress: 进度 dict，含 pct/message/current_node 等。
        """
        if self._progress_callback:
            try:
                full = dict(progress)
                if self._prompt_id:
                    full["prompt_id"] = self._prompt_id
                await self._progress_callback(full)
            except Exception:
                pass

    def _log(self, level: str, phase: str, msg: str, job_id: str = "") -> None:
        """记录日志。

        Args:
            level: 日志级别（info/warn/error）。
            phase: 阶段名（ws/http/node）。
            msg: 日志消息。
            job_id: 关联的 job ID。
        """
        if self._log_callback:
            try:
                self._log_callback(level, phase, msg, job_id)
            except Exception:
                pass


# ── 轻量节点分类字典（避免直接引用 NodeCategory 类型注释） ──────────────

class NodeCategoryDict:
    """运行时节点分类快速查找（避免循环依赖）。"""
    SAMPLER = {
        "KSampler",
        "KSamplerAdvanced",
        "SamplerCustom",
        "SamplerCustomAdvanced",
        "FluxSampler",
    }
    UPSCALE = {"ImageUpscaleWithModel", "SeedVR2VideoUpscaler"}
