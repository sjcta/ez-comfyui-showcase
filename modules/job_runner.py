"""
modules/job_runner.py — 出图流程编排。

Ez ComfyUI v4.0 重构。
串联 instance_picker → instance_manager → step_calculator → ws_tracker，
管理实例信号量、vLLM 启停、图片下载和历史记录。

依赖: instance_picker, instance_manager, step_calculator, ws_tracker
不依赖 app.py 的任何内容（所有外部引用通过构造参数注入）。
"""

import asyncio
import glob
import json
import os
import random
import re
import shutil
import subprocess
import time
import urllib.request
import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable

from modules.instance_manager import InstanceManager
from modules.instance_picker import pick_best_instance, strict_preferred_instance_name
from modules.prompt_labels import infer_generation_label
from modules.media_outputs import collect_preferred_outputs, output_media_type, output_ref_rel_path, is_image_output
from modules.step_calculator import StepCalculator
from modules.comfyui_upload import apply_qwen_frame_roll_to_workflow, ensure_workflow_images_available
from modules.workflow_validation import describe_api_prompt_issues, validate_api_prompt
from modules.ws_tracker import WSTracker, TrackResult, PromptStartTimeout, PromptSubmitError


def _is_image_output(filename: str) -> bool:
    return is_image_output(filename)


def _friendly_generation_error(err: Exception) -> str:
    text = str(err)
    if "Connection refused" in text or "Errno 61" in text or "Errno 111" in text:
        return "ComfyUI 连接被拒绝，请检查出图实例是否仍在运行"
    if "timed out" in text or "TimeoutError" in text:
        return "ComfyUI 响应超时，请稍后重试"
    return text[:200]


def _is_transient_comfyui_error(err: Exception) -> bool:
    text = str(err)
    markers = (
        "Connection refused",
        "Errno 61",
        "Errno 111",
        "timed out",
        "Temporary failure",
        "Connection reset",
        "Remote end closed connection",
    )
    return any(marker in text for marker in markers)


def _filter_retry_instances(instances: list[dict], workflow_name: str, failed_instances: set[str]) -> list[dict]:
    if not failed_instances or len(failed_instances) >= len(instances):
        return instances
    strict_preferred = strict_preferred_instance_name(workflow_name)
    if strict_preferred:
        return [
            inst for inst in instances
            if inst.get("name") == strict_preferred or inst.get("name") not in failed_instances
        ]
    return [inst for inst in instances if inst.get("name") not in failed_instances]


DEFAULT_TRACK_TIMEOUT = 900
VIDEO_TRACK_TIMEOUT = 3600
RUNNING_GENERATION_STATUSES = {"starting_comfyui", "preparing", "submitting", "generating", "downloading"}


class _SubmitStallRetry(Exception):
    """Internal signal to retry prompt submission without recursive run() calls."""


def _workflow_track_timeout(job: dict | None, workflow_path: str) -> int:
    job = job or {}
    workflow_type = str(job.get("workflow_type") or "")
    workflow_name = os.path.basename(str(workflow_path or "")).lower()
    if "视频" in workflow_type or any(token in workflow_name for token in ("i2v", "t2v", "video", "ltx", "sulphur")):
        return VIDEO_TRACK_TIMEOUT
    return DEFAULT_TRACK_TIMEOUT


class JobRunner:
    """出图全流程编排器。

    从队列拿到 job 后，串行调用所有下层模块完成一次出图。
    通过依赖注入获取所有 app.py 级别的外部函数（broadcast/save_jobs/vllm 等）。

    生命周期: 由 _queue_worker 协程创建并运行。
    每个 job_id 对应一次 run() 调用。
    """

    def __init__(
        self,
        inst_mgr: InstanceManager,
        jobs: dict,
        history: list,
        # ── App 级别外部函数注入 ─────────────────────────────────────
        broadcast_fn: Callable[[dict], Awaitable[None]],
        add_log_fn: Callable[[str, str, str, str], None],  # level, phase, msg, job_id
        save_jobs_fn: Callable[[], None],
        save_history_fn: Callable[[], None],
        make_thumbnail_fn: Callable[[str], str | None],
        get_image_size_fn: Callable[[str], tuple[int, int]],
        # ── ComfyUI 通信函数 ─────────────────────────────────────────
        comfyui_up_fn: Callable[[str], bool],                         # url -> bool
        comfyui_get_fn: Callable[[str, str], dict | list],            # path, url -> json
        download_images_fn: Callable[[str, str, str, str], list],     # sync: job_id, pid, url, dir -> files
        # ── vLLM 管理函数 ────────────────────────────────────────────
        vllm_running_fn: Callable[[], bool],
        stop_vllm_fn: Callable[[], None],
        start_vllm_fn: Callable[[], None],
        # ── 实例操作函数 ─────────────────────────────────────────────
        get_node_by_id_fn: Callable[[str], dict | None],
        run_instance_action_fn: Callable[[dict, dict, str], bool],    # node, inst, action -> bool
        # ── 实例状态容器 ─────────────────────────────────────────────
        instance_semas: dict[str, asyncio.Semaphore],
        instance_group: dict[str, str],
        instance_last_active: dict[str, float],
        # ── 路径常量 ─────────────────────────────────────────────────
        output_dir: str = "",
        history_dir: str = "",
        input_dir: str = "",
        # ── 实例列表 ─────────────────────────────────────────────────
        get_enabled_instances_fn: Callable[[], list[dict]] | None = None,
        insert_gen_fn: Callable | None = None,
        protection_check_fn: Callable[[str, list[dict], float], None] | None = None,
    ) -> None:
        """初始化 JobRunner。

        Args:
            inst_mgr: InstanceManager 实例。
            jobs: 共享的 jobs 字典引用。
            history: 共享的 history 列表引用。
            broadcast_fn: WebSocket 广播函数。
            add_log_fn: 日志记录函数。
            save_jobs_fn: 保存活跃 job 的函数。
            save_history_fn: 保存历史记录的函数。
            make_thumbnail_fn: 生成缩略图的函数。
            get_image_size_fn: 获取图片尺寸的函数。
            comfyui_up_fn: 检查 ComfyUI 是否在线的函数。
            comfyui_get_fn: 向 ComfyUI 发送 GET 请求的函数。
            download_images_fn: 下载远程 ComfyUI 输出图片的函数。
            vllm_running_fn: 检查 vLLM 是否在运行的函数。
            stop_vllm_fn: 停止 vLLM 的函数。
            start_vllm_fn: 启动 vLLM 的函数。
            get_node_by_id_fn: 按 ID 查找节点的函数。
            run_instance_action_fn: 执行实例 action 的函数。
            instance_semas: 实例级别的信号量字典。
            instance_group: 实例模型组字典。
            instance_last_active: 实例最后活跃时间字典。
            output_dir: ComfyUI 输出目录。
            history_dir: 历史图片目录。
            input_dir: 本地上传参考图目录。
            get_enabled_instances_fn: 获取已启用实例列表的函数。
        """
        self._inst_mgr = inst_mgr
        self._jobs = jobs
        self._history = history
        self._broadcast = broadcast_fn
        self._add_log = add_log_fn
        self._save_jobs = save_jobs_fn
        self._save_history = save_history_fn
        self._insert_gen = insert_gen_fn or (lambda r, e: None)
        self._protection_check = protection_check_fn
        self._make_thumbnail = make_thumbnail_fn
        self._get_image_size = get_image_size_fn
        self._comfyui_up = comfyui_up_fn
        self._comfyui_get = comfyui_get_fn
        self._download_images = download_images_fn
        self._vllm_running = vllm_running_fn
        self._stop_vllm = stop_vllm_fn
        self._start_vllm = start_vllm_fn
        self._get_node_by_id = get_node_by_id_fn
        self._run_instance_action = run_instance_action_fn
        self._instance_semas = instance_semas
        self._instance_group = instance_group
        self._instance_last_active = instance_last_active
        self._output_dir = output_dir
        self._history_dir = history_dir
        self._input_dir = input_dir
        self._get_enabled_instances = get_enabled_instances_fn

        # ── 运行态 ──────────────────────────────────────────────────
        self._running_jobs: dict[str, asyncio.Task] = {}
        self._step_calculator = StepCalculator()
        self._submit_retry_limit = 3

    # ── 主入口 ─────────────────────────────────────────────────────────

    def _running_generation_blockers(self, job_id: str) -> list[tuple[str, str]]:
        blockers: list[tuple[str, str]] = []
        for other_id, job in self._jobs.items():
            if other_id == job_id:
                continue
            status = str(job.get("status") or "")
            if status in RUNNING_GENERATION_STATUSES:
                blockers.append((other_id, str(job.get("instance") or "")))
        return blockers

    async def _wait_for_generation_turn(self, job_id: str, instance_name: str) -> bool:
        last_notice = 0.0
        while job_id in self._jobs:
            blockers = self._running_generation_blockers(job_id)
            if not blockers:
                return True
            now = time.time()
            if now - last_notice >= 5:
                blocker_instance = next((name for _jid, name in blockers if name), "")
                wait_for = blocker_instance or instance_name
                self._jobs[job_id]["status"] = "queued"
                self._jobs[job_id]["last_update"] = now
                self._jobs[job_id]["message"] = (
                    f"排队等待 {wait_for} 当前任务完成..."
                    if wait_for else "排队等待当前任务完成..."
                )
                self._jobs[job_id]["progress"] = {"pct": 0}
                self._save_jobs()
                await self._broadcast({"type": "job_update", "job": self._jobs[job_id]})
                last_notice = now
            await asyncio.sleep(2)
        return False

    async def run(
        self,
        job_id: str,
        workflow_path: str,
        field_values: dict,
        seed: int,
        vllm_was_running: bool,
        img_width: int = 0,
        img_height: int = 0,
        user_id: str = "",
        preferred_instance: str = "",
        preferred_node_id: str = "",
    ) -> None:
        while True:
            try:
                await self._run_attempt(
                    job_id=job_id,
                    workflow_path=workflow_path,
                    field_values=field_values,
                    seed=seed,
                    vllm_was_running=vllm_was_running,
                    img_width=img_width,
                    img_height=img_height,
                    user_id=user_id,
                    preferred_instance=preferred_instance,
                    preferred_node_id=preferred_node_id,
                )
                return
            except _SubmitStallRetry:
                preferred_instance = ""

    async def _run_attempt(
        self,
        job_id: str,
        workflow_path: str,
        field_values: dict,
        seed: int,
        vllm_was_running: bool,
        img_width: int = 0,
        img_height: int = 0,
        user_id: str = "",
        preferred_instance: str = "",
        preferred_node_id: str = "",
    ) -> None:
        """执行一次完整的出图流程。

        编排步骤:
        1. 选择最佳实例
        2. 如需则停止 vLLM
        3. 实例冷启动
        4. 获取实例信号量
        5. StepCalculator 计算进度信息
        6. WSTracker 追踪出图
        7. 下载输出图片
        8. 释放实例信号量
        9. 标记实例活跃
        10. 恢复 vLLM

        Args:
            job_id: 任务 ID。
            workflow_path: 工作流 JSON 文件路径。
            field_values: 字段值映射（nid::field → value）。
            seed: 随机种子。
            vllm_was_running: vLLM 是否正在运行（之后需恢复）。
            img_width: 图片宽度提示。
            img_height: 图片高度提示。
            user_id: 用户 ID（用于权限）。
        """
        sem: asyncio.Semaphore | None = None
        inst_held = False
        instance: dict | None = None
        inst_sem_key: str = ""
        prompt_id = ""
        restart_vllm_on_exit = True

        try:
            workflow_name = os.path.basename(workflow_path)
            self._jobs[job_id]["status"] = "dispatching"
            self._jobs[job_id]["last_update"] = time.time()
            self._jobs[job_id]["message"] = "排队等待..."
            await self._broadcast({"type": "job_update", "job": self._jobs[job_id]})

            # ── Phase 1: 选择最佳实例 ──────────────────────────────
            instances = self._get_enabled_instances() if self._get_enabled_instances else []
            if not instances:
                # 降级：从 inst_mgr 获取
                pass
            failed_instances = set(self._jobs[job_id].get("failed_instances", []))
            instances = _filter_retry_instances(instances, workflow_name, failed_instances)
            strict_preferred = strict_preferred_instance_name(workflow_name)
            if preferred_node_id:
                instances = [inst for inst in instances if inst.get("_node_id") == preferred_node_id]
            if preferred_instance:
                preferred_match = next((inst for inst in instances if inst.get("name") == preferred_instance), None)
                if preferred_match:
                    instance = preferred_match
                else:
                    instance = None
            elif strict_preferred:
                preferred_match = next((inst for inst in instances if inst.get("name") == strict_preferred), None)
                if preferred_match:
                    instance = preferred_match
                else:
                    instance = None
            else:
                instance = None

            def _affinity_getter(wf_name: str) -> str:
                from modules.config import ModelGroup
                return ""

            def _health_check(inst: dict) -> bool:
                # A stopped instance is still a valid candidate: the next phase
                # is responsible for cold-starting it and reporting real startup
                # failures. Filtering here would skip cold start entirely.
                return True

            def _queue_size(inst: dict) -> int:
                try:
                    q = self._comfyui_get("/queue", inst.get("url", ""))
                    if isinstance(q, dict):
                        running = len(q.get("queue_running", []))
                        pending = len(q.get("queue_pending", []))
                        return running + pending
                    return 999
                except Exception:
                    return 999

            def _local_queue_size(inst: dict) -> int:
                name = inst.get("name", "")
                if not name:
                    return 0
                active_status = {"dispatching", "queued", "starting_comfyui", "preparing", "submitting", "generating", "downloading"}
                return sum(
                    1
                    for jid, job in self._jobs.items()
                    if jid != job_id
                    and job.get("instance") == name
                    and job.get("status") in active_status
                )

            def _combined_queue_size(inst: dict) -> int:
                remote = _queue_size(inst)
                if remote >= 999:
                    return remote
                return remote + _local_queue_size(inst)

            def _group_getter(inst_name: str) -> str:
                return self._instance_group.get(inst_name, "")

            if instance is None:
                instance = await pick_best_instance(
                    instances=instances,
                    workflow_name=workflow_name,
                    affinity_getter=_affinity_getter,
                    health_check=_health_check,
                    queue_size_getter=_combined_queue_size,
                    group_getter=_group_getter,
                )

            if not instance:
                raise RuntimeError("没有可用实例")

            self._jobs[job_id]["instance"] = instance["name"]
            self._jobs[job_id]["target_node_id"] = instance.get("_node_id", "")
            self._jobs[job_id]["target_url"] = instance.get("url", "")

            # ── 获取实例信号量 ─────────────────────────────────────
            inst_sem_key = instance.get("name") or instance.get("id", "")
            sem = self._instance_semas.get(
                inst_sem_key,
                self._instance_semas.get(instance.get("id", ""), asyncio.Semaphore(1)),
            )

            self._jobs[job_id]["message"] = f"匹配实例 {instance['name']}..."
            self._jobs[job_id]["progress"] = {"pct": 0}
            await self._broadcast({"type": "job_update", "job": self._jobs[job_id]})

            if not await self._wait_for_generation_turn(job_id, instance["name"]):
                return

            # ── Phase 2: 等待实例信号量 ────────────────────────────
            self._jobs[job_id]["status"] = "queued"
            self._jobs[job_id]["last_update"] = time.time()
            self._jobs[job_id]["message"] = f"排队等待 {instance['name']}..."
            self._jobs[job_id]["progress"] = {"pct": 0}
            await self._broadcast({"type": "job_update", "job": self._jobs[job_id]})

            await sem.acquire()
            inst_held = True
            self._jobs[job_id]["sem_acquired"] = True
            self._jobs[job_id]["semaphore_key"] = inst_sem_key
            if self._jobs[job_id].get("cancelled"):
                return

            # ── Phase 3: 停止 vLLM（如需） ─────────────────────────
            if vllm_was_running:
                self._jobs[job_id]["message"] = "停止 vLLM 释放显存..."
                self._jobs[job_id]["progress"] = {"pct": 0}
                await self._broadcast({"type": "job_update", "job": self._jobs[job_id]})
                self._stop_vllm()
                await asyncio.sleep(2)

            # ── Phase 4: 实例冷启动 ────────────────────────────────
            self._jobs[job_id]["status"] = "starting_comfyui"
            self._jobs[job_id]["message"] = f"启动 ComfyUI #{instance['name']}..."
            self._jobs[job_id]["progress"] = {"pct": 0}
            await self._broadcast({"type": "job_update", "job": self._jobs[job_id]})

            try:
                await self._inst_mgr.ensure_running(instance, timeout=300)
            except (TimeoutError, Exception) as e:
                self._add_log("warn", "coldstart", f"冷启动失败: {e}", job_id)
                self._jobs[job_id]["message"] = f"实例 {instance['name']} 首次启动未就绪，正在重试..."
                self._jobs[job_id]["progress"] = {"pct": 0}
                await self._broadcast({"type": "job_update", "job": self._jobs[job_id]})
                # 兜底：直接使用 app 级别的启动方法
                node = self._get_node_by_id(instance.get("_node_id", ""))
                if node:
                    started = self._run_instance_action(node, instance, "start")
                else:
                    svc_name = f"comfyui-{instance['name'].lower()}"
                    result = subprocess.run(
                        ["systemctl", "--user", "start", svc_name],
                        capture_output=True, timeout=5,
                        env={
                            **os.environ,
                            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
                            "XDG_RUNTIME_DIR": "/run/user/1000",
                        },
                    )
                    started = result.returncode == 0
                if not started:
                    raise RuntimeError(f"实例 {instance['name']} 启动命令失败")
                for _ in range(90):
                    await asyncio.sleep(2)
                    if self._comfyui_up(instance["url"]):
                        break
                else:
                    raise TimeoutError(f"ComfyUI #{instance['name']} 启动超时 (180s)")

            self._jobs[job_id]["status"] = "preparing"
            self._jobs[job_id]["message"] = f"实例 {instance['name']} 就绪，开始出图"
            self._jobs[job_id]["instance"] = instance["name"]
            self._jobs[job_id]["progress"] = {"pct": 0}
            await self._broadcast({"type": "job_update", "job": self._jobs[job_id]})

            # ── Phase 5: 加载并准备 workflow ───────────────────────
            self._jobs[job_id]["status"] = "preparing"
            self._jobs[job_id]["message"] = "准备 workflow..."
            self._jobs[job_id]["progress"] = {"pct": 0}
            await self._broadcast({"type": "job_update", "job": self._jobs[job_id]})

            with open(workflow_path, "r") as f:
                wf = json.load(f)

            # 注入字段值
            for key, val in field_values.items():
                if "::" not in key:
                    continue
                nid, field = key.split("::", 1)
                if nid in wf and "inputs" in wf[nid]:
                    wf[nid]["inputs"][field] = val

            # 注入种子
            for nid, v in wf.items():
                if isinstance(v, dict) and v.get("class_type") == "KSampler":
                    if "seed" in v.get("inputs", {}):
                        v["inputs"]["seed"] = seed

            apply_qwen_frame_roll_to_workflow(wf, field_values, self._input_dir)

            issues = validate_api_prompt(wf)
            if issues:
                raise RuntimeError(describe_api_prompt_issues(issues))

            ensure_workflow_images_available(wf, self._input_dir, instance["url"])

            # ── 记录实例模型组 ─────────────────────────────────────
            from modules.config import ModelGroup
            self._instance_group[instance["name"]] = ModelGroup.extract_model_group(workflow_name)

            # ── Step 5: 计算进度信息 ───────────────────────────────
            step_info = self._step_calculator.calculate(wf)

            # ── 构建 node_types ────────────────────────────────────
            node_types: dict[str, str] = {}
            for nid, v in wf.items():
                if isinstance(v, dict) and "class_type" in v:
                    node_types[str(nid)] = v["class_type"]

            # ── Phase 6: WS 追踪出图 ───────────────────────────────
            self._add_log("info", "generate", "Starting generation", job_id)
            self._jobs[job_id]["status"] = "submitting"
            self._jobs[job_id]["message"] = "提交工作流..."
            self._jobs[job_id]["progress"] = {"pct": 0}
            self._jobs[job_id]["submitted_at"] = time.time()
            self._jobs[job_id]["last_update"] = time.time()
            client_id = str(self._jobs[job_id].get("client_id") or f"ez-{uuid.uuid4().hex[:12]}")
            self._jobs[job_id]["client_id"] = client_id
            self._save_jobs()
            await self._broadcast({"type": "job_update", "job": self._jobs[job_id]})

            ws_ok = False
            elapsed_start = time.time()

            # 创建 progress callback
            async def _progress_callback(progress: dict) -> None:
                if job_id not in self._jobs:
                    return
                pct = progress.get("pct", 0)
                msg = progress.get("message", "")
                pid = progress.get("prompt_id", "")
                progress_state = {"pct": int(pct)}
                for key in ("current_node", "sampler_cur", "sampler_total"):
                    if key in progress:
                        progress_state[key] = progress.get(key)
                self._jobs[job_id]["message"] = msg
                self._jobs[job_id]["progress"] = progress_state
                self._jobs[job_id]["last_update"] = time.time()
                if self._jobs[job_id].get("status") == "submitting" and msg not in (
                    "提交工作流...",
                    "等待实例开始执行...",
                ):
                    self._jobs[job_id]["status"] = "generating"
                    self._jobs[job_id]["generating_at"] = time.time()
                if pid:
                    self._jobs[job_id]["prompt_id"] = pid
                self._save_jobs()
                await self._broadcast({"type": "job_update", "job": self._jobs[job_id]})

            tracker = WSTracker(
                job_id=job_id,
                workflow=wf,
                step_info=step_info,
                instance_url=instance["url"],
                node_types=node_types,
                progress_callback=_progress_callback,
                log_callback=self._add_log,
                client_id=client_id,
            )

            try:
                result: TrackResult = await tracker.track(
                    timeout=_workflow_track_timeout(self._jobs.get(job_id), workflow_path)
                )
                ws_ok = result.ok
                prompt_id = result.prompt_id
                if prompt_id:
                    self._jobs[job_id]["prompt_id"] = prompt_id
            except PromptStartTimeout as stalled:
                prompt_id = stalled.prompt_id
                attempt_count = int(self._jobs[job_id].get("submit_retry_count", 0)) + 1
                self._jobs[job_id]["submit_retry_count"] = attempt_count
                failed = list(dict.fromkeys(
                    list(self._jobs[job_id].get("failed_instances", [])) +
                    [instance["name"]]
                ))
                self._jobs[job_id]["failed_instances"] = failed
                self._jobs[job_id]["ws_error"] = str(stalled)[:300]
                self._jobs[job_id]["message"] = (
                    f"实例 {instance['name']} 提交后无响应，自动纠错 {attempt_count}/{self._submit_retry_limit}..."
                )
                self._jobs[job_id]["progress"] = {"pct": 0}
                self._save_jobs()
                await self._broadcast({"type": "job_update", "job": self._jobs[job_id]})
                await self._recover_submit_stall(job_id, instance, prompt_id)
                if inst_held and sem:
                    self._jobs[job_id]["sem_acquired"] = False
                    sem.release()
                    inst_held = False
                if attempt_count < self._submit_retry_limit:
                    restart_vllm_on_exit = False
                    raise _SubmitStallRetry()
                raise TimeoutError("提交工作流多次无响应，实例容器或设备可能异常")
            except PromptSubmitError as submit_err:
                self._add_log("error", "wstrack", f"Prompt submit rejected: {submit_err}", job_id)
                self._jobs[job_id]["ws_error"] = str(submit_err)[:500]
                raise RuntimeError(_friendly_generation_error(submit_err))
            except Exception as _ws_err:
                self._add_log("error", "wstrack", f"WS error: {_ws_err}", job_id)
                self._jobs[job_id]["ws_error"] = str(_ws_err)[:300]

            # ── WS 失败时 HTTP polling 兜底 ────────────────────────
            if not ws_ok and prompt_id:
                for _ in range(60):
                    if self._jobs.get(job_id, {}).get("cancelled"):
                        raise RuntimeError("任务已取消")
                    await asyncio.sleep(5)
                    try:
                        check = self._comfyui_get(
                            f"/history/{prompt_id}",
                            instance["url"],
                        )
                        if isinstance(check, dict) and prompt_id in check:
                            st = check[prompt_id].get("status", {})
                            if st.get("completed", False):
                                ws_ok = True
                                break
                            if st.get("status_str") == "error":
                                raise RuntimeError("ComfyUI 执行出错")
                        q = self._comfyui_get("/queue", instance["url"])
                        running_ids = []
                        if isinstance(q, dict):
                            running_ids = [
                                item[1] if isinstance(item, list) and len(item) > 1 else None
                                for item in q.get("queue_running", [])
                            ]
                        if prompt_id not in running_ids and (
                            not isinstance(check, dict) or prompt_id not in check
                        ):
                            break
                    except RuntimeError as e:
                        if _is_transient_comfyui_error(e):
                            continue
                        raise
                    except Exception:
                        pass

            elapsed = time.time() - elapsed_start

            # ── Phase 7: 保存输出结果（由 _save_output 负责下载/入库） ─────
            if prompt_id:
                self._jobs[job_id]["status"] = "downloading"
                self._jobs[job_id]["message"] = "正在保存结果..."
                self._jobs[job_id]["progress"] = {"pct": 100}
                await self._broadcast({"type": "job_update", "job": self._jobs[job_id]})

            if job_id not in self._jobs:
                return

            if not ws_ok:
                extra = self._jobs[job_id].get("ws_error", "")
                raise TimeoutError(
                    f"出图失败{' (' + extra[:100] + ')' if extra else ''}"
                )

            # ── Phase 8: 保存历史记录（带 120s 超时） ────────────────
            try:
                await asyncio.wait_for(
                    self._save_output(
                        job_id=job_id,
                        prompt_id=prompt_id,
                        instance=instance,
                        workflow_path=workflow_path,
                        field_values=field_values,
                        seed=seed,
                        elapsed=elapsed,
                        img_width=img_width,
                        img_height=img_height,
                        user_id=user_id,
                    ),
                    timeout=120,
                )
            except asyncio.TimeoutError:
                raise TimeoutError("保存历史超时")

        except _SubmitStallRetry:
            raise
        except Exception as e:
            import traceback
            if job_id in self._jobs and self._jobs[job_id].get("status") not in ("done", "cancelled"):
                self._jobs[job_id]["status"] = "error"
                self._jobs[job_id]["trace"] = traceback.format_exc()[:500]
                if isinstance(e, TimeoutError):
                    self._jobs[job_id]["message"] = "出图失败"
                else:
                    self._jobs[job_id]["message"] = _friendly_generation_error(e)
                await self._broadcast({"type": "job_update", "job": self._jobs[job_id]})
                self._save_jobs()

        finally:
            if inst_held and sem:
                if job_id in self._jobs:
                    self._jobs[job_id]["sem_acquired"] = False
                sem.release()
            if instance:
                self._instance_last_active[instance["name"]] = time.time()
            self._save_jobs()
            if vllm_was_running and restart_vllm_on_exit:
                self._start_vllm()

    async def _recover_submit_stall(self, job_id: str, instance: dict, prompt_id: str) -> None:
        """Try to clean up a prompt that was accepted but never began execution."""
        inst_name = instance.get("name", "")
        inst_url = instance.get("url", "").rstrip("/")
        self._add_log(
            "warn", "stuck",
            f"实例 {inst_name} 提交后无执行事件，正在自动纠错",
            job_id,
        )

        def _post(path: str, payload: dict) -> None:
            if not inst_url:
                return
            req = urllib.request.Request(
                f"{inst_url}{path}",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5):
                pass

        if prompt_id:
            try:
                await asyncio.to_thread(_post, "/queue", {"delete": [prompt_id]})
            except Exception as e:
                self._add_log("warn", "stuck", f"清理队列失败: {e}", job_id)

        try:
            await asyncio.to_thread(_post, "/interrupt", {})
        except Exception:
            pass

        node = self._get_node_by_id(instance.get("_node_id", ""))
        if node:
            try:
                restarted = await asyncio.to_thread(
                    self._run_instance_action, node, instance, "restart"
                )
                if restarted:
                    self._add_log("warn", "stuck", f"已重启实例 {inst_name}", job_id)
                    for _ in range(60):
                        await asyncio.sleep(2)
                        try:
                            if self._comfyui_up(instance["url"]):
                                return
                        except Exception:
                            pass
                else:
                    self._add_log("warn", "stuck", f"实例 {inst_name} 重启命令失败", job_id)
            except Exception as e:
                self._add_log("warn", "stuck", f"实例 {inst_name} 重启异常: {e}", job_id)

    # ── 取消 ────────────────────────────────────────────────────────────

    async def cancel(self, job_id: str) -> bool:
        """取消指定 job。

        流程:
        1. POST /interrupt 通知 ComfyUI
        2. 取消运行中的 task
        3. 释放信号量
        4. 删除 jobs 条目

        Args:
            job_id: 要取消的 job ID。

        Returns:
            True 表示取消成功。
        """
        if job_id not in self._jobs:
            return False

        job = self._jobs[job_id]
        active_status = {
            "dispatching",
            "queued",
            "starting_comfyui",
            "preparing",
            "submitting",
            "generating",
            "downloading",
            "checking",
        }
        if job.get("status") == "generating":
            # 获取实例 URL 发送 interrupt
            inst_name = job.get("instance", "")
            if inst_name:
                instances = self._get_enabled_instances() if self._get_enabled_instances else []
                for inst in instances:
                    if inst["name"] == inst_name:
                        try:
                            import urllib.request, urllib.error
                            req = urllib.request.Request(
                                f"{inst['url'].rstrip('/')}/interrupt",
                                data=b"{}",
                                headers={"Content-Type": "application/json"},
                            )
                            urllib.request.urlopen(req, timeout=5)
                        except Exception:
                            pass
                        break

        if job.get("status") in active_status:
            job["cancelled"] = True
            job["status"] = "cancelled"
            job["message"] = "任务已取消"
            job["last_update"] = time.time()
        else:
            del self._jobs[job_id]
        self._save_jobs()
        await self._broadcast({"type": "job_cancelled", "job_id": job_id})
        return True

    # ── 重试 ────────────────────────────────────────────────────────────

    def retry(self, job_id: str) -> str | None:
        """重试失败 job。

        继承原 job 的参数，生成新 seed 和新 job_id。

        Args:
            job_id: 要重试的 job ID。

        Returns:
            新 job_id，或 None（原 job 不存在/状态不是 error）。
        """
        if job_id not in self._jobs:
            return None
        old = self._jobs[job_id]
        if old["status"] not in ("error",):
            return None

        wf = old.get("workflow", "")
        fields = old.get("fields", {})
        new_seed = random.randint(0, 2 ** 63)
        width = old.get("width", 0)
        height = old.get("height", 0)

        new_id = f"job_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"

        prompt_preview = infer_generation_label(wf, fields)[:200]

        new_vllm_was = False
        old["status"] = "retrying"
        old["message"] = "已重新排队，等待新任务完成..."
        old["retried_by"] = new_id
        old["last_update"] = time.time()

        self._jobs[new_id] = {
            "id": new_id,
            "status": "queued",
            "message": "排队中...",
            "workflow": wf,
            "seed": str(new_seed),
            "prompt_preview": prompt_preview,
            "width": width,
            "height": height,
            "fields": fields,
            "retry_of": job_id,
            "queued_at": datetime.now().strftime("%H:%M:%S"),
            "created_at_ts": time.time(),
        }
        for key in ("estimated_duration_sec", "estimated_duration_label"):
            if key in old:
                self._jobs[new_id][key] = old[key]
        return new_id

    # ── 输出保存 ────────────────────────────────────────────────────────

    async def _save_output(
        self,
        job_id: str,
        prompt_id: str,
        instance: dict,
        workflow_path: str,
        field_values: dict,
        seed: int,
        elapsed: float,
        img_width: int,
        img_height: int,
        user_id: str,
    ) -> None:
        """保存出图输出到历史记录。

        Args:
            job_id: 任务 ID。
            prompt_id: ComfyUI prompt_id。
            instance: 实例字典。
            workflow_path: 工作流文件路径。
            field_values: 字段值映射。
            seed: 种子。
            elapsed: 耗时秒数。
            img_width: 图片宽度。
            img_height: 图片高度。
            user_id: 用户 ID。
        """
        inst_url = instance["url"]
        inst_output = self._output_dir

        if not prompt_id and job_id in self._jobs:
            prompt_id = self._jobs[job_id].get("prompt_id", "") or ""

        sources: list[tuple[str, str, str]] = []

        downloaded = await asyncio.to_thread(
            self._download_images,
            job_id,
            prompt_id,
            inst_url,
            self._output_dir,
        )
        if downloaded:
            for path in downloaded:
                if path and os.path.isfile(path):
                    sources.append((path, os.path.basename(path), output_media_type(path)))

        if not sources:
            last_history_error = None
            for _wait in range(30):
                try:
                    hist = self._comfyui_get(f"/history/{prompt_id}", inst_url)
                    if isinstance(hist, dict) and prompt_id in hist:
                        found: list[tuple[str, str, str]] = []
                        for ref in collect_preferred_outputs(hist[prompt_id].get("outputs", {})):
                            filename = ref.get("filename", "")
                            rel_path = output_ref_rel_path(ref)
                            if not filename or not rel_path:
                                continue
                            src_path = os.path.join(self._output_dir, rel_path)
                            if not os.path.isfile(src_path):
                                for root, _dirs, files in os.walk(self._output_dir):
                                    if filename in files:
                                        src_path = os.path.join(root, filename)
                                        break
                            if os.path.isfile(src_path):
                                found.append((src_path, filename, output_media_type(filename)))
                        if found:
                            sources = found
                            break
                except Exception as e:
                    last_history_error = e
                import time as _t
                _t.sleep(1)

            if not sources and last_history_error:
                raise RuntimeError(_friendly_generation_error(last_history_error))

        deduped: list[tuple[str, str, str]] = []
        seen_paths: set[str] = set()
        for src_path, original_name, media_type in sources:
            real_path = os.path.abspath(src_path)
            if real_path in seen_paths or not os.path.isfile(src_path):
                continue
            seen_paths.add(real_path)
            deduped.append((src_path, original_name or os.path.basename(src_path), media_type or output_media_type(src_path)))
        sources = deduped

        if not sources:
            raise RuntimeError(f"未找到输出媒体 (prompt={prompt_id[:12]})")

        date_str = datetime.now().strftime("%Y-%m-%d")
        owner = user_id or "anonymous"
        subdir = f"{owner}/{date_str}"
        wf_basename = os.path.basename(workflow_path).replace(".json", "")
        existing = glob.glob(os.path.join(self._output_dir, subdir, f"{wf_basename}_*.*"))
        seq = 1
        for p in existing:
            m = re.search(rf"{re.escape(wf_basename)}_(\d+)\.[^.]+$", os.path.basename(p))
            if m:
                seq = max(seq, int(m.group(1)) + 1)

        prompt_text = infer_generation_label(
            os.path.basename(workflow_path),
            field_values,
        )

        batch_count = len(sources)
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        records: list[dict] = []
        for idx, (src, original_name, media_type) in enumerate(sources):
            ext = os.path.splitext(original_name or src)[1].lower() or ".png"
            hist_name = f"{wf_basename}_{seq + idx:04d}{ext}"
            rel_path = f"{subdir}/{hist_name}"
            dst = os.path.join(self._output_dir, rel_path)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)

            thumb_rel = self._make_thumbnail(rel_path) or ""
            actual_w, actual_h = self._get_image_size(rel_path) if media_type == "image" else (0, 0)
            if media_type == "video" and thumb_rel:
                actual_w, actual_h = self._get_image_size(thumb_rel)
            record_id = job_id if idx == 0 else f"{job_id}_{idx + 1:02d}"
            records.append({
                "id": record_id,
                "filename": rel_path,
                "media_type": media_type,
                "original": original_name,
                "workflow": os.path.basename(workflow_path),
                "prompt": prompt_text,
                "seed": str(seed),
                "width": actual_w or img_width,
                "height": actual_h or img_height,
                "elapsed": round(elapsed, 1),
                "time": created_at,
                "thumb": thumb_rel,
                "field_values": field_values,
                "user_id": user_id or "",
                "is_public": False,
                "protection_status": "pending",
                "batch_id": job_id if batch_count > 1 else "",
                "batch_index": idx,
                "batch_count": batch_count,
            })

        for record in reversed(records):
            self._history.insert(0, record)
        self._save_history()
        # 同步写入 SQLite
        for record in reversed(records):
            try:
                self._insert_gen(record, round(elapsed, 1), user_id=user_id or "")
            except Exception:
                pass

        if job_id in self._jobs:
            cover = records[0]
            done_payload = {
                "image": cover.get("filename", ""),
                "media_type": cover.get("media_type", "image") or "image",
                "thumb": cover.get("thumb", ""),
                "images": [record.get("filename", "") for record in records],
                "media_types": [record.get("media_type", "image") or "image" for record in records],
                "thumbs": [record.get("thumb", "") for record in records],
                "batch_id": job_id if batch_count > 1 else "",
                "batch_count": batch_count,
                "batch_items": records,
                "elapsed": round(elapsed, 1),
                "progress": {"pct": 100},
            }
            if self._protection_check:
                self._jobs[job_id].update(
                    status="checking",
                    message="内容校验中",
                    protection_status="pending",
                    pending_image=cover.get("filename", ""),
                    pending_media_type=cover.get("media_type", "image") or "image",
                    pending_thumb=cover.get("thumb", ""),
                    **{k: v for k, v in done_payload.items() if k not in ("image", "thumb")},
                )
                self._save_jobs()
                self._protection_check(job_id, records, round(elapsed, 1))
            else:
                self._jobs[job_id].update(
                    status="done",
                    message=f"完成 ({elapsed:.1f}s)",
                    **done_payload,
                )
                self._cleanup_retry_source_jobs(job_id)
            await self._broadcast({"type": "job_update", "job": self._jobs[job_id]})

    def _cleanup_retry_source_jobs(self, completed_job_id: str) -> list[str]:
        removed: list[str] = []
        for old_id, old in list(self._jobs.items()):
            if old_id == completed_job_id:
                continue
            if old.get("retried_by") == completed_job_id and old.get("status") == "retrying":
                self._jobs.pop(old_id, None)
                removed.append(old_id)
        return removed
