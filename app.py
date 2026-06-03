#!/usr/bin/env python3
"""
ComfyUI Web v3 — 三段式布局，GPU 监控，服务管理。
节点管理支持从 config/nodes.json 动态读取。
"""
import asyncio, json, os, glob, random, shutil, subprocess, time, uuid, re, socket, sqlite3, secrets, zipfile
# Ensure D-Bus session is available for systemctl --user calls in nohup context
os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
os.environ.setdefault("XDG_RUNTIME_DIR", "/run/user/1000")
import websockets.client
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Optional

from fastapi import (
    FastAPI, HTTPException, BackgroundTasks, WebSocket,
    WebSocketDisconnect, UploadFile, File, Form, Request, Depends, Response
)
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn, urllib.request, urllib.error, urllib.parse
from jose import jwt, JWTError
import bcrypt

# ── V4 refactored module imports (keep inline implementations for backward compat) ──
from modules.config import NodeCategory, ModelGroup, NODE_STATUS_MAP
from modules.comfyui_upload import apply_qwen_frame_roll_to_workflow, ensure_workflow_images_available
from modules.image_protection import (
    ImageProtectionResult,
    ImageProtectionWorker,
    configure_image_protection,
    get_image_protection_settings,
    prompt_has_nsfw_risk,
    prompt_needs_protection,
)
from modules.instance_manager import InstanceManager, InstanceHealth
import modules.instance_picker as mod_picker
from modules.job_runner import JobRunner, _workflow_track_timeout
from modules.media_outputs import collect_preferred_outputs, output_media_type, output_ref_rel_path, is_image_output
from modules.llm_client import LLMVisionUnsupportedError, chat_completion, configure_llm_client, llm_provider_name
from modules.prompt_interrogator import (
    prepare_interrogate_image,
    run_llm_expert_image_interrogator,
    run_llm_image_interrogator,
)
from modules.prompt_labels import infer_generation_label
from modules.prompt_optimizer import (
    run_llm_prompt_language_switcher,
    run_llm_prompt_optimizer,
)
from modules.step_calculator import StepCalculator, StepInfo
from modules.time_estimator import TimeEstimator as TimeEstimatorModule
from modules.workflow_validation import describe_api_prompt_issues, validate_api_prompt
from modules.ws_tracker import WSTracker, TrackResult

APP_ROOT = Path(__file__).resolve().parent
VERSION_FILE = APP_ROOT / "VERSION"


def _read_app_version() -> str:
    override = os.environ.get("EZ_COMFYUI_VERSION", "").strip()
    if override:
        return override
    try:
        version = VERSION_FILE.read_text("utf-8").strip()
    except Exception:
        version = ""
    return version or "v0.0.0"


APP_VERSION = _read_app_version()

# ── Auth config
AUTH_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "auth.db")
JWT_SECRET_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "jwt_secret.key")


def _load_jwt_secret() -> str:
    env_secret = os.environ.get("JWT_SECRET_KEY", "").strip()
    if env_secret:
        return env_secret
    try:
        if os.path.exists(JWT_SECRET_FILE):
            stored = Path(JWT_SECRET_FILE).read_text("utf-8").strip()
            if stored:
                return stored
        os.makedirs(os.path.dirname(JWT_SECRET_FILE), exist_ok=True)
        generated = secrets.token_urlsafe(48)
        Path(JWT_SECRET_FILE).write_text(generated, encoding="utf-8")
        try:
            os.chmod(JWT_SECRET_FILE, 0o600)
        except Exception:
            pass
        print("[auth] JWT_SECRET_KEY is not set; generated a per-install secret in data/jwt_secret.key.")
        return generated
    except Exception as e:
        print(f"[auth] JWT_SECRET_KEY is not set and data/jwt_secret.key is unavailable: {e}; using an ephemeral secret.")
        return secrets.token_urlsafe(48)


SECRET_KEY = _load_jwt_secret()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 31
AUTH_COOKIE_NAME = "ez_comfyui_token"
CSRF_COOKIE_NAME = "ez_comfyui_csrf"
_CSRF_HEADER_NAME = "X-CSRF-Token"
_UNSAFE_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_AUTH_RATE_LIMIT_WINDOW_SEC = 300
_AUTH_RATE_LIMIT_MAX_ATTEMPTS = 8
_auth_rate_attempts: dict[str, list[float]] = {}

# ── Logging ──
_log_buffer: list[dict] = []
_MAX_LOG = 2000
_LOG_RETENTION_SEC = 3600
_LOG_FILE = os.environ.get(
    "EZ_COMFYUI_LOG_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "logs", "recent.jsonl"),
)

def _log_job_for_id(job_id: str) -> dict | None:
    if not job_id:
        return None
    job_id = str(job_id)
    job_map = globals().get("jobs") or {}
    if job_id in job_map:
        return job_map[job_id]
    suffix = job_id[-12:]
    for jid, job in job_map.items():
        if str(jid).endswith(suffix):
            return job
    return None


def _log_workflow_type(workflow: str) -> str:
    if not workflow:
        return ""
    classifier = globals().get("_workflow_primary_type")
    if callable(classifier):
        try:
            return classifier(workflow) or ""
        except Exception:
            pass
    return ""


def _trim_log_buffer(now: float | None = None) -> None:
    now = now or time.time()
    cutoff = now - _LOG_RETENTION_SEC
    _log_buffer[:] = [entry for entry in _log_buffer if float(entry.get("ts") or 0) >= cutoff]
    if len(_log_buffer) > _MAX_LOG:
        del _log_buffer[:len(_log_buffer) - _MAX_LOG]


def _persist_log_buffer() -> None:
    try:
        os.makedirs(os.path.dirname(_LOG_FILE), exist_ok=True)
        with open(_LOG_FILE, "w", encoding="utf-8") as fh:
            for entry in _log_buffer:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _append_persistent_log(entry: dict) -> None:
    try:
        os.makedirs(os.path.dirname(_LOG_FILE), exist_ok=True)
        with open(_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _is_non_actionable_thumbnail_log(entry: dict) -> bool:
    """Return True for legacy thumbnail noise from invalid temp/test files."""
    if str(entry.get("phase") or "") != "thumbnail":
        return False
    msg = str(entry.get("msg") or "")
    if msg.startswith("pillow thumbnail failed: cannot identify image file"):
        return True
    if msg == "project ffmpeg not configured; thumbnail skipped":
        rel = str(entry.get("job_id") or "").lower()
        return os.path.splitext(rel)[1] in THUMB_IMAGE_EXTS
    return False


def _load_recent_logs() -> None:
    if not os.path.isfile(_LOG_FILE):
        return
    now = time.time()
    cutoff = now - _LOG_RETENTION_SEC
    loaded: list[dict] = []
    try:
        with open(_LOG_FILE, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if _is_non_actionable_thumbnail_log(entry):
                    continue
                if float(entry.get("ts") or 0) >= cutoff:
                    loaded.append(entry)
        _log_buffer[:] = loaded[-_MAX_LOG:]
        _persist_log_buffer()
    except Exception:
        pass


def add_log(level: str, phase: str, msg: str, job_id: str = "", details: str = ""):
    phase = str(phase or "")
    raw_msg = str(msg or "")
    raw_details = str(details or "")
    if phase == "stop" or raw_msg.strip().lower() == "stop":
        return
    msg_map = {
        "Starting generation": "开始生成",
        "Workflow finished": "工作流完成",
        "Workflow execution started": "工作流开始执行",
    }
    phase_map = {
        "generate": "生成",
        "complete": "完成",
        "node": "节点",
        "sampler": "采样",
        "step": "步进",
        "start": "开始",
        "done": "完成",
        "error": "错误",
        "wstrack": "进度追踪",
        "coldstart": "冷启动",
        "instance": "实例",
        "queue": "队列",
        "wf_meta": "工作流元数据",
        "wf_config": "工作流配置",
        "db": "数据库",
        "idle": "空闲回收",
        "dead": "实例恢复",
        "stuck": "任务卡住",
        "ws": "通信",
    }
    msg = msg_map.get(raw_msg, raw_msg)
    if msg.startswith("Sampling "):
        msg = "采样 " + msg[len("Sampling "):]
    elif msg.startswith("WS error:"):
        msg = "进度追踪错误:" + msg[len("WS error:"):]
    elif msg.startswith("ComfyUI execution error:"):
        msg = "ComfyUI 执行错误:" + msg[len("ComfyUI execution error:"):]
    elif msg.startswith("Prompt 已提交:"):
        msg = "任务已提交:" + msg[len("Prompt 已提交:"):]
    elif msg.endswith(" started"):
        msg = msg[:-len(" started")] + " 已启动"
    elif msg.endswith(" stopped"):
        msg = msg[:-len(" stopped")] + " 已停止"
    elif msg.endswith(" restarted"):
        msg = msg[:-len(" restarted")] + " 已重启"
    elif msg.endswith(" start FAILED"):
        msg = msg[:-len(" start FAILED")] + " 启动失败"
    elif msg.endswith(" stop FAILED"):
        msg = msg[:-len(" stop FAILED")] + " 停止失败"
    elif msg.endswith(" restart FAILED"):
        msg = msg[:-len(" restart FAILED")] + " 重启失败"
    phase = phase_map.get(phase, phase)
    details = msg_map.get(raw_details, raw_details)
    job = _log_job_for_id(job_id)
    workflow = str((job or {}).get("workflow") or "")
    workflow_type = str((job or {}).get("workflow_type") or _log_workflow_type(workflow))
    entry = {"ts": time.time(), "level": level, "phase": phase,
             "msg": str(msg)[:200], "job_id": job_id[-12:], "details": str(details)[:500]}
    user_id = str((job or {}).get("user_id") or "")
    if user_id:
        entry["user_id"] = user_id
    if workflow:
        entry["workflow"] = workflow
    if workflow_type:
        entry["workflow_type"] = workflow_type
    _log_buffer.append(entry)
    _trim_log_buffer()
    _append_persistent_log(entry)
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(broadcast({"type": "log", "entry": entry}))
    except Exception:
        pass

NODES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "nodes.json")


def _friendly_generation_error(err: Exception) -> str:
    text = str(err)
    if "Connection refused" in text or "Errno 61" in text or "Errno 111" in text:
        return "ComfyUI 连接被拒绝，请检查出图实例是否仍在运行"
    if "timed out" in text or "TimeoutError" in text:
        return "ComfyUI 响应超时，请稍后重试"
    return text[:200]

# ── Runtime connection state ──
_connected_nodes: dict[str, bool] = {}  # node_id -> connected (default True if missing)
ACTIVE_JOB_STATUSES = {
    "dispatching",
    "queued",
    "starting_comfyui",
    "preparing",
    "submitting",
    "generating",
    "downloading",
}
IMAGE_PROTECTION_PENDING = "pending"
IMAGE_PROTECTION_SAFE = "safe"
IMAGE_PROTECTION_PROTECTED = "protected"
IMAGE_PROTECTION_ERROR = "error"
JOB_STAGE_TIMEOUTS = {
    "dispatching": 120,
    "starting_comfyui": 360,
    "preparing": 180,
    "submitting": 90,
    "generating": 1200,
    "downloading": 240,
}
NON_EXPIRING_JOB_STATUSES = {"queued"}
JOB_STAGE_TIMEOUT_MESSAGES = {
    "dispatching": "任务调度超时",
    "queued": "排队超时",
    "starting_comfyui": "实例启动超时",
    "preparing": "准备阶段超时",
    "submitting": "提交阶段超时",
    "generating": "生成阶段超时（长时间无进度）",
    "downloading": "保存结果超时",
}
VIDEO_GENERATING_TIMEOUT = 3600
INSTANCE_DOWN_ACTIVE_JOB_GRACE_SEC = 30
GPU_STALL_SECONDS = 60
GPU_STALL_SAMPLE_INTERVAL = 10
GPU_STALL_RETRY_LIMIT = 3
GPU_STALL_JOB_STATUSES = {"starting_comfyui", "preparing", "submitting", "generating", "downloading"}

def _is_node_connected(nid: str) -> bool:
    return _connected_nodes.get(nid, True)

def _job_is_active_for_instance(job: dict, instance_name: str) -> bool:
    return job.get("instance") == instance_name and job.get("status") in ACTIVE_JOB_STATUSES


def _has_active_instance_job(instance_name: str) -> bool:
    return any(_job_is_active_for_instance(job, instance_name) for job in jobs.values())


def _current_job_for_instance(instance_name: str) -> dict | None:
    active_jobs = [
        job
        for job in jobs.values()
        if _job_is_active_for_instance(job, instance_name)
    ]
    if not active_jobs:
        return None
    status_rank = {
        "downloading": 6,
        "generating": 5,
        "submitting": 4,
        "preparing": 3,
        "starting_comfyui": 2,
        "queued": 1,
        "dispatching": 0,
    }
    return max(
        active_jobs,
        key=lambda job: (
            status_rank.get(job.get("status"), 0),
            _job_last_activity_ts(job),
        ),
    )


def _status_jobs_for_instance(instance_name: str, instance_up: bool) -> list[dict]:
    out = []
    for job in jobs.values():
        if not _job_is_active_for_instance(job, instance_name):
            continue
        if instance_up or job.get("prompt_id"):
            out.append(job)
    return out


def _current_status_job_for_instance(instance_name: str, instance_up: bool) -> dict | None:
    active_jobs = _status_jobs_for_instance(instance_name, instance_up)
    if not active_jobs:
        return None
    status_rank = {
        "downloading": 6,
        "generating": 5,
        "submitting": 4,
        "preparing": 3,
        "starting_comfyui": 2,
        "queued": 1,
        "dispatching": 0,
    }
    return max(
        active_jobs,
        key=lambda job: (
            status_rank.get(job.get("status"), 0),
            _job_last_activity_ts(job),
        ),
    )


def _job_progress_pct(job: dict | None) -> int:
    if not job:
        return 0
    prog = job.get("progress", {}) or {}
    pct = prog.get("pct", 0) if isinstance(prog, dict) else 0
    try:
        return max(0, min(100, int(pct)))
    except (TypeError, ValueError):
        return 0


def _job_last_activity_ts(job: dict) -> float:
    for key in ("last_update", "submitted_at", "generating_at", "created_at_ts"):
        try:
            ts = float(job.get(key) or 0)
        except (TypeError, ValueError):
            ts = 0
        if ts > 0:
            return ts
    return 0


def _is_video_job(job: dict) -> bool:
    workflow_type = str(job.get("workflow_type") or "")
    workflow = os.path.basename(str(job.get("workflow") or "")).lower()
    return "视频" in workflow_type or any(token in workflow for token in ("i2v", "t2v", "video", "ltx", "sulphur"))


def _job_stage_timeout(job: dict, status: str) -> int | None:
    if status in NON_EXPIRING_JOB_STATUSES:
        return None
    timeout = JOB_STAGE_TIMEOUTS.get(status, 600)
    if status == "generating" and _is_video_job(job):
        return max(timeout, VIDEO_GENERATING_TIMEOUT)
    return timeout


def _job_stuck_state(job: dict, now: float | None = None) -> tuple[bool, float, int | None]:
    status = str(job.get("status") or "")
    timeout = _job_stage_timeout(job, status)
    last = _job_last_activity_ts(job)
    if not last or status in ("done", "error", "cancelled"):
        return False, 0.0, timeout
    now = now or time.time()
    age = max(0.0, now - last)
    if timeout is None:
        return False, age, None
    return age > timeout, age, timeout


def _finalize_stuck_job(job_id: str, job: dict, now: float | None = None) -> None:
    now = now or time.time()
    status = str(job.get("status") or "")
    _stuck, age, timeout = _job_stuck_state(job, now=now)
    message = JOB_STAGE_TIMEOUT_MESSAGES.get(status, "任务超时")
    job["status"] = "error"
    job["message"] = f"{message}（{int(age)}秒无状态变化，阈值{int(timeout)}秒）"
    job["last_update"] = now
    task = _job_tasks.pop(job_id, None)
    if task and not task.done():
        task.cancel()


def _finalize_instance_jobs(instance_name: str, message: str = "实例已停止") -> list[str]:
    now = time.time()
    affected: list[str] = []
    for job_id, job in list(jobs.items()):
        if job.get("instance") != instance_name or job.get("status") not in ACTIVE_JOB_STATUSES:
            continue
        job["status"] = "error"
        job["message"] = message
        job["last_update"] = now
        task = _job_tasks.pop(job_id, None)
        if task and not task.done():
            task.cancel()
        affected.append(job_id)
    if affected:
        save_jobs()
    return affected


def _finalize_interrupted_instance_jobs(
    instance_name: str,
    is_active: bool,
    now: float | None = None,
    remote_queue: dict | None = None,
) -> list[str]:
    """Fail only pre-submit jobs when a ComfyUI instance disappears.

    A job with a ComfyUI prompt_id may still be running remotely while
    /system_stats is temporarily unreachable under load. Those jobs are kept
    alive so WS resume plus /queue and /history polling can recover them.
    """
    if is_active:
        return []
    now = now or time.time()
    affected: list[str] = []
    interrupted_statuses = {"starting_comfyui", "submitting", "generating", "downloading"}
    for job_id, job in list(jobs.items()):
        if job.get("instance") != instance_name or job.get("status") not in interrupted_statuses:
            continue
        last = _job_last_activity_ts(job)
        if last and now - last < INSTANCE_DOWN_ACTIVE_JOB_GRACE_SEC:
            continue
        if str(job.get("prompt_id") or ""):
            continue
        job["status"] = "error"
        job["message"] = "实例已停止，任务已中断"
        job["last_update"] = now
        task = _job_tasks.pop(job_id, None)
        if task and not task.done():
            task.cancel()
        affected.append(job_id)
    if affected:
        save_jobs()
        add_log("warn", "queue", f"实例 {instance_name} 已停止，已结束 {len(affected)} 个残留任务")
    return affected


def _job_gpu_sample(stats: dict | None) -> tuple[int, int, int] | None:
    if not isinstance(stats, dict):
        return None
    try:
        total = int(float(stats.get("vram_total_mb") or 0))
        used = int(round(float(stats.get("vram_used_mb") or 0)))
        util = int(round(float(stats.get("util_pct") or 0)))
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None
    return used, util, total


def _job_progress_monitor_fields(job: dict) -> dict:
    progress = job.get("progress") if isinstance(job.get("progress"), dict) else {}
    return {
        "progress_pct": _job_progress_pct(job),
        "current_node": str(progress.get("current_node") or ""),
        "sampler_cur": progress.get("sampler_cur"),
        "sampler_total": progress.get("sampler_total"),
    }


def _gpu_activity_sample_signature(sample: dict) -> tuple:
    return (
        sample.get("status"),
        sample.get("progress_pct"),
        sample.get("current_node"),
        sample.get("sampler_cur"),
        sample.get("sampler_total"),
        sample.get("vram_used_mb"),
    )


def _gpu_activity_history_with_current(previous: dict | None, current: dict, now: float) -> list[dict]:
    raw_samples = []
    if isinstance(previous, dict):
        samples = previous.get("samples")
        if isinstance(samples, list):
            raw_samples = [s for s in samples if isinstance(s, dict)]
        elif previous.get("sampled_at") is not None:
            raw_samples = [previous]

    cutoff = now - GPU_STALL_SECONDS
    older = [s for s in raw_samples if float(s.get("sampled_at") or 0) < cutoff]
    recent = [s for s in raw_samples if float(s.get("sampled_at") or 0) >= cutoff]
    history = older[-1:] + recent + [current]
    return history[-20:]


def _gpu_activity_idle_since(history: list[dict], now: float) -> float:
    if not history:
        return 0.0
    current = history[-1]
    if int(current.get("util_pct") or 0) > 0:
        return 0.0
    current_signature = _gpu_activity_sample_signature(current)
    stable_since = float(current.get("sampled_at") or now)
    for sample in reversed(history):
        if int(sample.get("util_pct") or 0) > 0:
            break
        if _gpu_activity_sample_signature(sample) != current_signature:
            break
        stable_since = float(sample.get("sampled_at") or stable_since)
    return stable_since


def _job_gpu_activity_stalled(job_id: str, job: dict, stats: dict | None, now: float | None = None) -> bool:
    status = str(job.get("status") or "")
    if status not in GPU_STALL_JOB_STATUSES:
        _job_gpu_activity_watch.pop(job_id, None)
        return False
    sample = _job_gpu_sample(stats)
    if sample is None:
        _job_gpu_activity_watch.pop(job_id, None)
        return False
    vram_used, util, total = sample
    now = now or time.time()
    previous = _job_gpu_activity_watch.get(job_id)
    progress_fields = _job_progress_monitor_fields(job)
    previous_sample = None
    if isinstance(previous, dict):
        previous_samples = previous.get("samples")
        if isinstance(previous_samples, list) and previous_samples:
            previous_sample = previous_samples[-1]
        else:
            previous_sample = previous
    stage_or_progress_changed = (
        not previous_sample
        or previous_sample.get("status") != status
        or previous_sample.get("progress_pct") != progress_fields["progress_pct"]
        or previous_sample.get("current_node") != progress_fields["current_node"]
        or previous_sample.get("sampler_cur") != progress_fields["sampler_cur"]
        or previous_sample.get("sampler_total") != progress_fields["sampler_total"]
    )
    vram_changed = bool(previous_sample) and previous_sample.get("vram_used_mb") != vram_used
    gpu_working = util > 0
    last_gpu_active_at = now if gpu_working else float((previous or {}).get("last_gpu_active_at") or 0)

    current_sample = {
        "status": status,
        **progress_fields,
        "vram_used_mb": vram_used,
        "vram_total_mb": total,
        "util_pct": util,
        "sampled_at": now,
    }
    history = _gpu_activity_history_with_current(previous, current_sample, now)
    idle_since = _gpu_activity_idle_since(history, now)

    monitor = {
        **current_sample,
        "vram_changed": vram_changed,
        "stage_or_progress_changed": stage_or_progress_changed,
        "samples": history,
        "idle_since": idle_since,
        "last_gpu_active_at": last_gpu_active_at,
    }
    _job_gpu_activity_watch[job_id] = monitor
    job["runtime_monitor"] = dict(monitor)
    if idle_since <= 0:
        return False
    return now - idle_since >= GPU_STALL_SECONDS


def _clear_job_runtime_fields(job: dict) -> None:
    for key in (
        "prompt_id",
        "client_id",
        "submitted_at",
        "generating_at",
        "ws_error",
        "trace",
        "sem_acquired",
    ):
        job.pop(key, None)


async def _restart_gpu_stalled_job(job_id: str, job: dict, instance: dict, now: float | None = None) -> bool:
    now = now or time.time()
    retry_count = int(job.get("gpu_stall_retry_count") or 0) + 1
    if retry_count > GPU_STALL_RETRY_LIMIT:
        job["status"] = "error"
        job["message"] = f"GPU 连续无工作，已重试 {GPU_STALL_RETRY_LIMIT} 次仍失败"
        job["last_update"] = now
        save_jobs()
        await broadcast({"type": "job_update", "job": job})
        return False

    prompt_id = str(job.get("prompt_id") or "")
    inst_url = str(instance.get("url") or "")
    if prompt_id and inst_url:
        try:
            comfyui_post("/queue", {"delete": [prompt_id]}, base_url=inst_url)
        except Exception:
            pass
    if inst_url:
        try:
            comfyui_post("/interrupt", {}, base_url=inst_url)
        except Exception:
            pass

    node = _get_node_by_id(instance.get("_node_id", ""))
    if node:
        _managed_instance_action(node, instance, "restart", reason="gpu-stall")

    task = _job_tasks.pop(job_id, None)
    if task and not task.done():
        task.cancel()

    path = _resolve_workflow(str(job.get("workflow") or ""))
    if not path:
        job["status"] = "error"
        job["message"] = "GPU 静止后重启任务失败：工作流文件不存在"
        job["last_update"] = now
        save_jobs()
        await broadcast({"type": "job_update", "job": job})
        return False

    _clear_job_runtime_fields(job)
    job["status"] = "queued"
    job["message"] = "检测到 GPU 60 秒窗口无波动，正在重启任务..."
    job["progress"] = {"pct": 0}
    job["last_update"] = now
    job["gpu_stall_retry_count"] = retry_count
    _job_gpu_activity_watch.pop(job_id, None)
    save_jobs()
    await broadcast({"type": "job_update", "job": job})

    if job_id not in _queued_dispatch_job_ids():
        _job_queue.put_nowait((
            job_id,
            path,
            job.get("fields") or {},
            _job_seed_value(job),
            False,
            int(job.get("width") or 0),
            int(job.get("height") or 0),
            str(job.get("user_id") or ""),
            str(job.get("preferred_instance") or ""),
            str(job.get("preferred_node_id") or ""),
        ))
    add_log("warn", "stuck", f"任务 GPU {GPU_STALL_SECONDS}s 窗口无波动，已重启任务 {retry_count}/{GPU_STALL_RETRY_LIMIT}", job_id)
    return True

def _resolve_secret_value(value: str) -> str:
    """Resolve config secrets. Use env:NAME in JSON to avoid storing cleartext."""
    if isinstance(value, str) and value.startswith("env:"):
        return os.environ.get(value[4:], "")
    return value

def _resolve_ssh_config(ssh_config: dict) -> dict:
    ssh = dict(ssh_config or {})
    if "password" in ssh:
        ssh["password"] = _resolve_secret_value(ssh.get("password", ""))
    if "key_path" in ssh:
        ssh["key_path"] = os.path.expanduser(_resolve_secret_value(ssh.get("key_path", "")))
    return ssh

# ── Node & Instance Loading ──
_nodes_cache: list[dict] = []
_nodes_cache_ts: float = 0
_nodes_cache_max_age = 5  # seconds

def _load_nodes(force=False) -> list[dict]:
    """Load nodes from JSON file with caching. Use force=True to bypass cache."""
    global _nodes_cache, _nodes_cache_ts
    now = time.time()
    if not force and _nodes_cache and now - _nodes_cache_ts < _nodes_cache_max_age:
        return _nodes_cache
    if not os.path.isfile(NODES_FILE):
        _nodes_cache = []
        _nodes_cache_ts = now
        return _nodes_cache
    try:
        with open(NODES_FILE) as f:
            data = json.load(f)
        if isinstance(data, list):
            _nodes_cache = [_normalize_node(n) for n in data]
            _nodes_cache_ts = now
            return _nodes_cache
    except Exception as e:
        print(f"[nodes] Error loading nodes: {e}")
    _nodes_cache = []
    _nodes_cache_ts = now
    return _nodes_cache

def _save_nodes(nodes: list[dict]):
    """Save nodes to JSON file and invalidate cache."""
    global _nodes_cache_ts
    os.makedirs(os.path.dirname(NODES_FILE), exist_ok=True)
    with open(NODES_FILE, "w") as f:
        json.dump([_normalize_node(n) for n in nodes], f, ensure_ascii=False, indent=2)
    _nodes_cache_ts = 0  # invalidate cache

def _instance_api_url(node: dict, inst: dict) -> str:
    """Return the ComfyUI API base URL for an instance."""
    port = inst.get("port", "")
    access = node.get("access") or {}
    template = str(access.get("url") or "").strip()
    if access.get("type") == "proxy" and template:
        try:
            return template.format(port=port).rstrip("/")
        except Exception:
            pass
    return f"http://{node['host']}:{port}"

def _get_enabled_instances() -> list[dict]:
    """Return flat list of all enabled instances across all enabled nodes."""
    instances = []
    for node in _load_nodes():
        if not node.get("enabled", True):
            continue
        if not _is_node_connected(node["id"]):
            continue
        for inst in node.get("instances", []):
            if not inst.get("enabled", True):
                continue
            full = dict(inst)
            full["_node_id"] = node["id"]
            full["_node_name"] = node["name"]
            full["_node_host"] = node["host"]
            full["_node_connection"] = node.get("connection", "local")
            full["_node_ssh"] = _resolve_ssh_config(node.get("ssh_config", {}))
            full["url"] = _instance_api_url(node, inst)
            instances.append(full)
    return instances


def _get_generation_instances(instances: list[dict] | None = None) -> list[dict]:
    """Return instances that may accept image-generation jobs."""
    return _get_enabled_instances() if instances is None else list(instances or [])


def _can_view_instance(inst: dict, current_user: dict | None = None) -> bool:
    return True


def _get_enabled_instances_for_user(current_user: dict | None = None) -> list[dict]:
    """Return enabled instances visible to the current user."""
    instances = []
    for node in _load_nodes():
        if not node.get("enabled", True):
            continue
        if not _is_node_connected(node["id"]):
            continue
        normalized = _normalize_node(node)
        if current_user is None:
            if not normalized.get("shared"):
                continue
        elif not _can_view_node(normalized, current_user):
            continue
        for inst in normalized.get("instances", []):
            if not inst.get("enabled", True):
                continue
            if not _can_view_instance(inst, current_user):
                continue
            full = dict(inst)
            full["_node_id"] = normalized["id"]
            full["_node_name"] = normalized["name"]
            full["_node_host"] = normalized["host"]
            full["_node_connection"] = normalized.get("connection", "local")
            full["_node_ssh"] = _resolve_ssh_config(normalized.get("ssh_config", {}))
            full["url"] = _instance_api_url(normalized, inst)
            instances.append(full)
    return instances


def _instance_display_rank(inst: dict) -> tuple:
    name = str(inst.get("name") or inst.get("id") or "").strip()
    upper = name.upper()
    if upper == "A":
        return (0, 0)
    if upper == "B":
        return (0, 1)
    if len(upper) == 1 and "A" <= upper <= "Z":
        return (0, ord(upper) - ord("A"))
    match = re.search(r"\d+", name)
    if match:
        return (1, int(match.group(0)), name.lower())
    return (2, name.lower())


def _sort_instances_for_status(instances: list[dict]) -> list[dict]:
    node_order: dict[str, int] = {}
    original_order: dict[int, int] = {}
    for idx, inst in enumerate(instances or []):
        node_key = str(inst.get("_node_id") or inst.get("node_id") or inst.get("_node_name") or inst.get("node_name") or "default")
        if node_key not in node_order:
            node_order[node_key] = len(node_order)
        original_order[id(inst)] = idx
    return sorted(
        list(instances or []),
        key=lambda inst: (
            node_order.get(str(inst.get("_node_id") or inst.get("node_id") or inst.get("_node_name") or inst.get("node_name") or "default"), 0),
            _instance_display_rank(inst),
            original_order.get(id(inst), 0),
        ),
    )


def _get_node_by_id(nid: str) -> Optional[dict]:
    for node in _load_nodes():
        if node["id"] == nid:
            return node
    return None

def _get_instance_by_id(iid: str) -> Optional[dict]:
    for node in _load_nodes():
        for inst in node.get("instances", []):
            if inst["id"] == iid:
                return inst, node
    return None, None

def _run_instance_action(node: dict, instance: dict, action: str) -> bool:
    """Start/stop/restart/force-restart ComfyUI instance."""
    svc = instance.get("service", f"comfyui-{instance['name'].lower()}")
    conn = node.get("connection", "local")
    node_name = node.get("name", node.get("host", "?"))
    inst_name = instance.get("name", svc)
    ok = False

    # Build systemctl commands
    def _run_cmd(cmd_list: list[str]) -> bool:
        try:
            if conn == "local":
                r = subprocess.run(cmd_list, capture_output=True, timeout=30,
                    env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
                         "XDG_RUNTIME_DIR": "/run/user/1000"})
                return r.returncode == 0
            elif conn == "remote-ssh":
                ssh = _resolve_ssh_config(node.get("ssh_config", {}))
                prefix = []
                if ssh.get("auth") == "password" and ssh.get("password"):
                    prefix = ["sshpass", "-p", ssh["password"], "ssh",
                              "-p", str(ssh.get("port", 22)),
                              f"{ssh.get('user', 'root')}@{node['host']}"]
                else:
                    prefix = ["ssh", "-p", str(ssh.get("port", 22)),
                              f"{ssh.get('user', 'root')}@{node['host']}"]
                # SSH needs D-Bus env for systemctl --user
                dbus_cmd = ["DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus",
                            "XDG_RUNTIME_DIR=/run/user/1000"] + cmd_list
                r = subprocess.run(prefix + dbus_cmd, capture_output=True, timeout=30)
                return r.returncode == 0
        except Exception:
            return False

    if action == "force-restart":
        # Kill -9 then start fresh
        add_log("warn", "instance", f"[{node_name}] {inst_name} force-restarting (kill + start)")
        _run_cmd(["systemctl", "--user", "kill", "-s", "KILL", svc])
        import time as _time
        _time.sleep(2)
        ok = _run_cmd(["systemctl", "--user", "start", svc])
    else:
        ok = _run_cmd(["systemctl", "--user", action, svc])

    if ok:
        action_text = {"stop": "stopped"}.get(action, f"{action}ed")
        add_log("info", "instance", f"[{node_name}] {inst_name} {action_text}", details=action)
        if action in ("start", "restart", "force-restart"):
            _instance_start_grace[inst_name] = time.time()
        elif action == "stop":
            _instance_last_active[inst_name] = 0
            _instance_group[inst_name] = ""
            _instance_start_grace.pop(inst_name, None)
    else:
        add_log("warn", "instance", f"[{node_name}] {inst_name} {action} FAILED", details=action)
    return ok


def _managed_instance_action(node: dict | None, instance: dict, action: str, reason: str = "") -> bool:
    """Route lifecycle actions through InstanceManager when it is available."""
    if _inst_mgr is not None:
        return _inst_mgr.run_action(instance, action, node=node, reason=reason)
    if not node:
        node = _get_node_by_id(instance.get("_node_id", ""))
    if not node:
        return False
    return _run_instance_action(node, instance, action)


# ── 任务队列：single global generation dispatcher ──
_job_queue: asyncio.Queue = asyncio.Queue()
_inst_mgr: InstanceManager | None = None
_job_runner: JobRunner | None = None
_app_loop: asyncio.AbstractEventLoop | None = None
_job_gpu_activity_watch: dict[str, dict] = {}
_generation_dispatch_lock: asyncio.Lock | None = None
_generation_dispatch_lock_loop: asyncio.AbstractEventLoop | None = None

def _generation_queue_worker_count() -> int:
    """Only one generation dispatcher is allowed so A/B never run concurrently."""
    return 1

def _start_queue_workers() -> list[asyncio.Task]:
    return [asyncio.create_task(_queue_worker()) for _ in range(_generation_queue_worker_count())]

def _get_generation_dispatch_lock() -> asyncio.Lock:
    global _generation_dispatch_lock, _generation_dispatch_lock_loop
    loop = asyncio.get_running_loop()
    if _generation_dispatch_lock is None or _generation_dispatch_lock_loop is not loop:
        _generation_dispatch_lock = asyncio.Lock()
        _generation_dispatch_lock_loop = loop
    return _generation_dispatch_lock

async def _queue_worker():
    """Global generation dispatcher.

    All generation jobs are serialized globally. Per-instance semaphores remain
    as a local safety net, but the dispatch lock prevents A/B from generating
    at the same time.
    """
    while True:
        try:
            job_id, workflow_path, field_values, seed, vllm_was, img_w, img_h, user_id, preferred_instance, preferred_node_id = await _job_queue.get()
            if job_id not in jobs:
                _job_queue.task_done()
                continue
            async with _get_generation_dispatch_lock():
                if job_id not in jobs:
                    _job_queue.task_done()
                    continue
                if _job_runner:
                    task = asyncio.create_task(_run_job_v4(job_id, workflow_path, field_values, seed, vllm_was, img_w, img_h, user_id, preferred_instance, preferred_node_id))
                else:
                    task = asyncio.create_task(_dispatch_and_run(job_id, workflow_path, field_values, seed, vllm_was, img_w, img_h, preferred_instance, preferred_node_id))
                _job_tasks[job_id] = task
                try:
                    await task
                except asyncio.CancelledError:
                    if asyncio.current_task() and asyncio.current_task().cancelling():
                        raise
                except Exception as e:
                    print(f"[queue_worker] Job {job_id} failed: {e}")
                finally:
                    _job_tasks.pop(job_id, None)
        except Exception as e:
            print(f"[queue_worker] Error in dispatch loop: {e}")
            await asyncio.sleep(1)


async def _run_job_v4(job_id, workflow_path, field_values, seed, vllm_was, img_w, img_h, user_id, preferred_instance="", preferred_node_id=""):
    try:
        await _job_runner.run(
            job_id, workflow_path, field_values, seed, vllm_was, img_w, img_h,
            user_id=user_id,
            preferred_instance=preferred_instance,
            preferred_node_id=preferred_node_id,
        )
    finally:
        _job_queue.task_done()

async def _dispatch_and_run(job_id, workflow_path, field_values, seed, vllm_was, img_w, img_h, preferred_instance="", preferred_node_id=""):
    """Dispatch a job and serialize only per selected ComfyUI instance."""
    sem = None
    inst_held = False
    inst = None
    try:
        workflow_name = os.path.basename(workflow_path)
        jobs[job_id]["status"] = "dispatching"
        jobs[job_id]["last_update"] = time.time()
        jobs[job_id]["message"] = "排队等待..."
        await broadcast({"type": "job_update", "job": jobs[job_id]})

        # Phase 1: find the best instance
        candidate_instances = _get_generation_instances()
        if preferred_node_id:
            candidate_instances = [item for item in candidate_instances if item.get("_node_id") == preferred_node_id]
        if not candidate_instances:
            raise RuntimeError("No enabled instances available")
        inst = None
        if preferred_instance:
            inst = next((item for item in candidate_instances if item.get("name") == preferred_instance), None)
        if not inst:
            inst = await mod_picker.pick_best_instance(
                instances=candidate_instances,
                workflow_name=workflow_name,
                affinity_getter=lambda wf: (pick_affinity_instance(wf) or {}).get("name", ""),
                health_check=lambda _inst: True,
                queue_size_getter=lambda item: _get_instance_queue_size(item["url"]) + sum(
                    1
                    for jid, job in jobs.items()
                    if jid != job_id
                    and job.get("instance") == item.get("name")
                    and job.get("status") in ACTIVE_JOB_STATUSES
                ),
                group_getter=lambda name: _instance_group.get(name, ""),
            )
        sem = _instance_semas.get(inst["name"]) or _instance_semas.get(inst["id"]) or asyncio.Semaphore(1)
        jobs[job_id]["instance"] = inst["name"]
        jobs[job_id]["target_node_id"] = inst.get("_node_id", "")
        jobs[job_id]["target_url"] = inst.get("url", "")
        jobs[job_id]["message"] = f"匹配实例 {inst['name']}..."
        await broadcast({"type": "job_update", "job": jobs[job_id]})

        # Phase 2: wait for instance semaphore
        jobs[job_id]["status"] = "queued"
        jobs[job_id]["last_update"] = time.time()
        jobs[job_id]["message"] = f"排队等待 {inst['name']}..."
        await broadcast({"type": "job_update", "job": jobs[job_id]})
        await sem.acquire()
        inst_held = True
        jobs[job_id]["sem_acquired"] = True

        jobs[job_id]["status"] = "preparing"
        jobs[job_id]["message"] = f"实例 {inst['name']} 就绪，开始出图"
        await broadcast({"type": "job_update", "job": jobs[job_id]})

        _instance_group[inst["name"]] = extract_model_group(workflow_name)

        await generate_task(job_id, workflow_path, field_values, seed, vllm_was, img_w, img_h, instance=inst)
        _instance_last_active[inst["name"]] = time.time()
    except Exception as e:
        import traceback
        traceback.print_exc()
        if job_id in jobs and jobs[job_id].get("status") not in ("done", "error"):
            jobs[job_id]["status"] = "error"
            jobs[job_id]["message"] = str(e)[:200]
            await broadcast({"type": "job_update", "job": jobs[job_id]})
            save_jobs()
    finally:
        if inst_held:
            if job_id in jobs:
                jobs[job_id]["sem_acquired"] = False
            sem.release()
        _job_queue.task_done()

# ── Remote Workflow Sync ────────────────────────────────────────────────

def sync_remote_workflows():
    """Sync workflows from all enabled remote devices via SSH."""
    results = {"synced": 0, "errors": 0, "total": 0, "details": [], "timestamp": datetime.now().isoformat()}
    meta = _load_wf_meta()
    changed = False
    all_dirs_to_add = set()

    for node in _load_nodes():
        if not node.get("enabled", True):
            continue
        conn = node.get("connection", "local")
        if conn == "local":
            continue  # local is already handled by normal file scanning

        # Collect workflow_dirs from node level or instances
        wf_dirs = node.get("workflow_dirs", [])
        if not wf_dirs:
            for inst in node.get("instances", []):
                for wd in inst.get("workflow_dirs", []):
                    if wd not in wf_dirs:
                        wf_dirs.append(wd)

        if not wf_dirs:
            results["details"].append(f"[{node['name']}] 未配置 workflow_dirs，跳过")
            continue

        if conn == "remote-ssh":
            node_result = _sync_ssh_workflows(node, wf_dirs, meta)
            results["synced"] += node_result["synced"]
            results["errors"] += node_result["errors"]
            results["total"] += node_result["total"]
            for detail in node_result["details"]:
                results["details"].append(detail)
            if node_result["synced"] > 0:
                changed = True
        elif conn == "remote-http":
            results["details"].append(f"[{node['name']}] HTTP 同步暂不支持（Phase 1 简化）")

    if changed:
        _save_wf_meta(meta)
        # Also add the local cache dir to wf_dirs if not already present
        wf_dirs_list = _load_wf_dirs()
        if WORKFLOW_DIR not in wf_dirs_list:
            wf_dirs_list.append(WORKFLOW_DIR)
            _save_wf_dirs(wf_dirs_list)

    return results


def _sync_ssh_workflows(node: dict, wf_dirs: list[str], meta: dict) -> dict:
    """Sync workflows from a remote SSH node."""
    result = {"synced": 0, "errors": 0, "total": 0, "details": []}
    ssh = _resolve_ssh_config(node.get("ssh_config", {}))
    host = node["host"]
    user = ssh.get("user", "root")
    port = str(ssh.get("port", 22))
    password = ssh.get("password", "")

    for wf_dir in wf_dirs:
        result["details"].append(f"[{node['name']}] 扫描 {wf_dir}...")
        try:
            # SSH find to list .json files
            find_cmd = []
            if password:
                find_cmd = ["sshpass", "-p", password, "ssh",
                            "-o", "StrictHostKeyChecking=no",
                            "-p", port,
                            f"{user}@{host}",
                            f'find "{wf_dir}" -name "*.json" -maxdepth 2']
            else:
                find_cmd = ["ssh",
                            "-o", "StrictHostKeyChecking=no",
                            "-p", port,
                            f"{user}@{host}",
                            f'find "{wf_dir}" -name "*.json" -maxdepth 2']

            r = subprocess.run(find_cmd, capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                result["errors"] += 1
                result["details"].append(f"[{node['name']}] find 失败: {r.stderr.strip()[:200]}")
                continue

            file_paths = [p.strip() for p in r.stdout.splitlines() if p.strip()]
            if not file_paths:
                result["details"].append(f"[{node['name']}] {wf_dir} 无 .json 文件")
                continue

            result["total"] += len(file_paths)

            for remote_path in file_paths:
                try:
                    # SSH cat to read file content
                    cat_cmd = []
                    if password:
                        cat_cmd = ["sshpass", "-p", password, "ssh",
                                   "-o", "StrictHostKeyChecking=no",
                                   "-p", port,
                                   f"{user}@{host}",
                                   f'cat "{remote_path}"']
                    else:
                        cat_cmd = ["ssh",
                                   "-o", "StrictHostKeyChecking=no",
                                   "-p", port,
                                   f"{user}@{host}",
                                   f'cat "{remote_path}"']

                    r2 = subprocess.run(cat_cmd, capture_output=True, text=True, timeout=30)
                    if r2.returncode != 0:
                        result["errors"] += 1
                        result["details"].append(f"[{node['name']}] 读取失败: {os.path.basename(remote_path)}: {r2.stderr.strip()[:100]}")
                        continue

                    content = r2.stdout
                    try:
                        wf_json = json.loads(content)
                    except json.JSONDecodeError as e:
                        result["errors"] += 1
                        result["details"].append(f"[{node['name']}] JSON 解析失败: {os.path.basename(remote_path)}: {e}")
                        continue

                    # Write to local data/workflows/{device_name}/
                    local_name = os.path.basename(remote_path)
                    device_dir = os.path.join(WORKFLOW_DIR, node['name'])
                    local_path = os.path.join(device_dir, local_name)
                    os.makedirs(device_dir, exist_ok=True)
                    with open(local_path, "w", encoding="utf-8") as out_f:
                        json.dump(wf_json, out_f, ensure_ascii=False, indent=2)

                    # Extract metadata for wf_meta.json
                    model_name = ""
                    for nid, nv in wf_json.items():
                        if isinstance(nv, dict) and "model_name" in nv.get("inputs", {}):
                            model_name = nv["inputs"]["model_name"]
                            break

                    # Auto-detect tags
                    tags = _auto_detect_tags(local_path)
                    tags.append(node.get("name", "remote").replace(" ", ""))

                    # Update meta
                    if local_name not in meta:
                        meta[local_name] = {
                            "name": local_name.replace(".json", ""),
                            "tags": tags,
                            "source": node["name"],
                            "source_path": local_path,
                        }
                        result["synced"] += 1
                        result["details"].append(f"[{node['name']}] + {local_name}")
                    else:
                        # Update source and source_path
                        existing = meta[local_name]
                        changed = False
                        if "source" not in existing or existing["source"] != node["name"]:
                            existing["source"] = node["name"]
                            changed = True
                        if "source_path" not in existing or existing["source_path"] != local_path:
                            existing["source_path"] = local_path
                            changed = True
                        if changed:
                            result["synced"] += 1
                            result["details"].append(f"[{node['name']}] ~ {local_name} (元数据更新)")

                except subprocess.TimeoutExpired:
                    result["errors"] += 1
                    result["details"].append(f"[{node['name']}] 超时: {os.path.basename(remote_path)}")
                except Exception as e:
                    result["errors"] += 1
                    result["details"].append(f"[{node['name']}] 错误: {os.path.basename(remote_path)}: {str(e)[:100]}")

        except subprocess.TimeoutExpired:
            result["errors"] += 1
            result["details"].append(f"[{node['name']}] SSH find 超时: {wf_dir}")
        except Exception as e:
            result["errors"] += 1
            result["details"].append(f"[{node['name']}] SSH 错误: {str(e)[:200]}")

    return result


# ── Config ──────────────────────────────────────────────────────────────
import os, platform

_BASE = os.environ.get("EZ_COMFYUI_HOME", os.path.dirname(os.path.abspath(__file__)))

COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8190")
WORKFLOW_DIR = os.environ.get("WORKFLOW_DIR", os.path.join(_BASE, "data", "workflows"))
OUTPUT_DIR   = os.environ.get("OUTPUT_DIR", os.path.join(_BASE, "data", "outputs"))
HISTORY_DIR  = os.environ.get("HISTORY_DIR", os.path.join(_BASE, "data", "history"))
WF_META_FILE = os.environ.get("WF_META_FILE", os.path.join(_BASE, "data", "wf_meta.json"))
WF_DIRS_FILE = os.environ.get("WF_DIRS_FILE", os.path.join(_BASE, "data", "wf_dirs.json"))
WF_CONFIG_DIR = os.environ.get("WF_CONFIG_DIR", os.path.join(_BASE, "data", "wf_configs"))
os.makedirs(WF_CONFIG_DIR, exist_ok=True)
WF_THUMB_DIR = os.environ.get("WF_THUMB_DIR", os.path.join(_BASE, "data", "thumbs", "wf"))
JOBS_FILE    = os.environ.get("JOBS_FILE", os.path.join(_BASE, "data", "jobs.json"))
CANCELLED_PROMPTS_FILE = os.environ.get("CANCELLED_PROMPTS_FILE", os.path.join(_BASE, "data", "cancelled_prompts.json"))
SYSTEM_SETTINGS_FILE = os.environ.get("SYSTEM_SETTINGS_FILE", os.path.join(_BASE, "data", "system_settings.json"))
PORT = int(os.environ.get("EZ_COMFYUI_PORT", "9091"))
MAX_HISTORY = int(os.environ.get("MAX_HISTORY", "200"))


def _safe_rel_path(base_dir: str, rel_path: str) -> str:
    safe = (rel_path or "").replace("\\", "/").lstrip("/")
    root = os.path.abspath(base_dir)
    path = os.path.abspath(os.path.join(root, safe))
    if os.path.commonpath([root, path]) != root:
        raise HTTPException(400, "Invalid path")
    return path


def _workflow_thumbnail_rel(path: str) -> str:
    root = os.path.abspath(WORKFLOW_DIR)
    full = os.path.abspath(path)
    if os.path.commonpath([root, full]) != root:
        raise HTTPException(400, "Workflow thumbnail must live under workflow directory")
    return os.path.relpath(full, root).replace("\\", "/")


def _workflow_thumbnail_path(filename: str, entry: dict | None, ext: str) -> tuple[str, str]:
    workflow_path = _resolve_workflow(filename, entry)
    if not workflow_path:
        workflow_path = os.path.join(WORKFLOW_DIR, filename)
    workflow_dir = os.path.dirname(os.path.abspath(workflow_path))
    thumb_name = os.path.splitext(os.path.basename(filename))[0] + ext
    thumb_path = os.path.join(workflow_dir, thumb_name)
    return thumb_path, _workflow_thumbnail_rel(thumb_path)


def _candidate_generated_media_paths(rel_path: str) -> list[str]:
    safe = (rel_path or "").replace("\\", "/").lstrip("/")
    if not safe:
        return []
    return [_safe_rel_path(OUTPUT_DIR, safe)]


def _image_media_type(path: str, default: str = "application/octet-stream") -> str:
    ext = os.path.splitext(path)[1].lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".mp4": "video/mp4",
        ".m4v": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
    }.get(ext, default)

# ── Generation SQLite Database ──
GEN_DB = os.path.join(_BASE, "data", "generation.db")

def _db_connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or GEN_DB)
    conn.row_factory = sqlite3.Row
    return conn

def _json_dumps_compact(value) -> str:
    return json.dumps(value, ensure_ascii=False)

def _json_loads_safe(value, default):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _mask_secret(value: str) -> str:
    value = str(value or "")
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _is_secret_placeholder(value: str, current_secret: str) -> bool:
    value = str(value or "")
    current_secret = str(current_secret or "")
    return bool(current_secret and value and value == _mask_secret(current_secret))


def _redact_llm_profiles(profiles: list[dict]) -> list[dict]:
    redacted = []
    for profile in profiles:
        item = dict(profile or {})
        item["api_key"] = _mask_secret(str(item.get("api_key") or ""))
        redacted.append(item)
    return redacted


def _normalize_system_settings(raw: dict | None, *, redact_secrets: bool = True) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    image_settings = raw.get("image_protection") if isinstance(raw.get("image_protection"), dict) else {}
    llm_settings = raw.get("llm_api") if isinstance(raw.get("llm_api"), dict) else {}
    llm_profiles = _normalize_llm_api_profiles(raw.get("llm_api_profiles"), llm_settings)
    active_profile = str(raw.get("active_llm_api_profile") or "").strip()
    active_profile_settings = _llm_profile_settings(llm_profiles, active_profile)
    effective_llm_settings = active_profile_settings or llm_settings
    llm_api = configure_llm_client(effective_llm_settings, include_api_key=not redact_secrets)
    return {
        "image_protection": configure_image_protection(image_settings),
        "llm_api": llm_api,
        "llm_api_profiles": _redact_llm_profiles(llm_profiles) if redact_secrets else llm_profiles,
        "active_llm_api_profile": active_profile if active_profile_settings else "",
    }


def _normalize_llm_api_profiles(value, fallback_llm: dict | None = None) -> list[dict]:
    raw_profiles = value if isinstance(value, list) else []
    profiles: list[dict] = []
    seen: set[str] = set()
    for idx, item in enumerate(raw_profiles):
        if not isinstance(item, dict):
            continue
        profile_id = re.sub(r"[^a-zA-Z0-9_.:-]+", "-", str(item.get("id") or item.get("name") or f"llm-{idx + 1}")).strip("-")
        if not profile_id or profile_id in seen:
            continue
        seen.add(profile_id)
        caps = item.get("capabilities")
        if not isinstance(caps, list):
            caps = ["text"]
        profiles.append(
            {
                "id": profile_id,
                "name": str(item.get("name") or profile_id).strip() or profile_id,
                "enabled": item.get("enabled", True) is not False,
                "base_url": str(item.get("base_url") or "").strip().rstrip("/"),
                "model": str(item.get("model") or "").strip(),
                "api_key": str(item.get("api_key") or "").strip(),
                "timeout": int(float(item.get("timeout") or 180)),
                "capabilities": [str(cap).strip() for cap in caps if str(cap).strip()],
                "notes": str(item.get("notes") or "").strip(),
            }
        )
    if not profiles and isinstance(fallback_llm, dict) and (fallback_llm.get("base_url") or fallback_llm.get("model")):
        profiles.append(
            {
                "id": "default",
                "name": "默认 LLM API",
                "enabled": fallback_llm.get("enabled", True) is not False,
                "base_url": str(fallback_llm.get("base_url") or "").strip().rstrip("/"),
                "model": str(fallback_llm.get("model") or "").strip(),
                "api_key": str(fallback_llm.get("api_key") or "").strip(),
                "timeout": int(float(fallback_llm.get("timeout") or 180)),
                "capabilities": ["text", "vision"],
                "notes": "",
            }
        )
    return profiles


def _llm_profile_settings(profiles: list[dict], profile_id: str) -> dict | None:
    if not profile_id:
        return None
    for profile in profiles:
        if profile.get("id") == profile_id:
            return {
                "enabled": profile.get("enabled", True),
                "base_url": profile.get("base_url", ""),
                "model": profile.get("model", ""),
                "api_key": profile.get("api_key", ""),
                "timeout": profile.get("timeout", 180),
            }
    return None


def _load_system_settings_raw() -> dict:
    try:
        with open(SYSTEM_SETTINGS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        data = {}
    return data if isinstance(data, dict) else {}


def _load_system_settings() -> dict:
    return _normalize_system_settings(_load_system_settings_raw(), redact_secrets=True)


def _save_system_settings(settings: dict) -> None:
    os.makedirs(os.path.dirname(SYSTEM_SETTINGS_FILE), exist_ok=True)
    with open(SYSTEM_SETTINGS_FILE, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, ensure_ascii=False, indent=2)


def _update_system_settings(patch: dict | None) -> dict:
    current = _load_system_settings_raw()
    patch = patch if isinstance(patch, dict) else {}
    if isinstance(patch.get("image_protection"), dict):
        image_current = dict(current.get("image_protection") or {})
        image_current.update(patch["image_protection"])
        current["image_protection"] = image_current
    if isinstance(patch.get("llm_api"), dict):
        llm_current = dict(current.get("llm_api") or {})
        llm_patch = dict(patch["llm_api"])
        incoming_key = str(llm_patch.get("api_key", ""))
        if (
            llm_current.get("api_key")
            and (incoming_key == "" or _is_secret_placeholder(incoming_key, llm_current.get("api_key", "")))
        ):
            llm_patch.pop("api_key", None)
        llm_current.update(llm_patch)
        current["llm_api"] = llm_current
        if "llm_api_profiles" not in patch and "active_llm_api_profile" not in patch:
            current["active_llm_api_profile"] = ""
    if isinstance(patch.get("llm_api_profiles"), list):
        existing_profiles = {
            str(profile.get("id") or ""): profile
            for profile in _normalize_llm_api_profiles(current.get("llm_api_profiles"), current.get("llm_api"))
        }
        incoming_profiles = []
        for item in patch["llm_api_profiles"]:
            profile = dict(item) if isinstance(item, dict) else {}
            existing = existing_profiles.get(str(profile.get("id") or ""))
            incoming_key = str(profile.get("api_key", ""))
            if (
                existing
                and existing.get("api_key")
                and (incoming_key == "" or _is_secret_placeholder(incoming_key, existing.get("api_key", "")))
            ):
                profile.pop("api_key", None)
                profile["api_key"] = existing.get("api_key", "")
            incoming_profiles.append(profile)
        current["llm_api_profiles"] = incoming_profiles
    if "active_llm_api_profile" in patch:
        current["active_llm_api_profile"] = str(patch.get("active_llm_api_profile") or "").strip()
    updated = _normalize_system_settings(current, redact_secrets=False)
    _save_system_settings(updated)
    return _normalize_system_settings(updated, redact_secrets=True)


def _protection_candidate_paths(record: dict | sqlite3.Row) -> list[str]:
    """Return thumbnail and original image candidates, preserving order."""
    values: list[str] = []
    for key in ("thumb", "thumb_path", "filename", "image_path"):
        try:
            rel = record.get(key, "") if hasattr(record, "get") else record[key]
        except Exception:
            rel = ""
        rel = str(rel or "").strip()
        if rel and rel not in values:
            values.append(rel)
    paths: list[str] = []
    for rel in values:
        path = rel if os.path.isabs(rel) else os.path.join(OUTPUT_DIR, rel)
        if path not in paths:
            paths.append(path)
    return paths


def _check_image_protection_candidates(
    worker: ImageProtectionWorker,
    record: dict | sqlite3.Row,
    prompt: str,
) -> ImageProtectionResult:
    fallback: ImageProtectionResult | None = None
    for path in _protection_candidate_paths(record):
        result = worker.check(path, prompt)
        if result.status == IMAGE_PROTECTION_PROTECTED:
            return result
        if result.status == IMAGE_PROTECTION_SAFE:
            fallback = result
        elif fallback is None:
            fallback = result
    return fallback or ImageProtectionResult(IMAGE_PROTECTION_ERROR, 1.0, "missing image", "local-error")

def _workflow_meta_row_to_entry(row: sqlite3.Row | None) -> dict | None:
    if not row:
        return None
    filename = row["filename"]
    entry = {
        "name": row["name"] or filename.replace(".json", ""),
        "tags": _json_loads_safe(row["tags_json"], []),
        "owner_id": row["owner_id"] or _bootstrap_admin_user_id(),
        "shared": bool(row["shared"]),
    }
    optional_fields = {
        "source": row["source"],
        "source_path": row["source_path"],
        "thumbnail": row["thumbnail"],
        "sort_order": row["sort_order"],
        "active_version": row["active_version"],
    }
    for key, value in optional_fields.items():
        if value not in (None, ""):
            entry[key] = value
    versions = _json_loads_safe(row["versions_json"], {})
    if versions:
        entry["versions"] = versions
    return _normalize_wf_meta_entry(filename, entry)


def _workflow_config_row_to_entry(row: sqlite3.Row | None) -> dict | None:
    if not row:
        return None
    return _json_loads_safe(row["config_json"], None)

def _init_gen_db():
    conn = sqlite3.connect(GEN_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS generations (
            id TEXT PRIMARY KEY,
            workflow TEXT NOT NULL,
            workflow_name TEXT DEFAULT '',
            device TEXT DEFAULT '',
            instance TEXT DEFAULT '',
            status TEXT DEFAULT 'done',
            media_type TEXT DEFAULT 'image',
            image_path TEXT DEFAULT '',
            thumb_path TEXT DEFAULT '',
            created_at DATETIME DEFAULT (datetime('now','localtime')),
            completed_at DATETIME,
            duration_sec INTEGER DEFAULT 0,
            params TEXT DEFAULT '{}',
            prompt TEXT DEFAULT '',
            width INTEGER DEFAULT 0,
            height INTEGER DEFAULT 0,
            seed INTEGER DEFAULT 0,
            protection_status TEXT DEFAULT 'pending',
            protection_score REAL DEFAULT 0,
            protection_reason TEXT DEFAULT '',
            protection_source TEXT DEFAULT '',
            protection_checked_at TEXT DEFAULT ''
        )
    """)
    # Add user_id column if not exists (migration for existing databases)
    try:
        conn.execute("ALTER TABLE generations ADD COLUMN user_id TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        conn.execute("ALTER TABLE generations ADD COLUMN is_public INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE generations ADD COLUMN deleted_at TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE generations ADD COLUMN deleted_by TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    for ddl in (
        "ALTER TABLE generations ADD COLUMN batch_id TEXT DEFAULT ''",
        "ALTER TABLE generations ADD COLUMN batch_index INTEGER DEFAULT 0",
        "ALTER TABLE generations ADD COLUMN batch_count INTEGER DEFAULT 1",
        "ALTER TABLE generations ADD COLUMN media_type TEXT DEFAULT 'image'",
        "ALTER TABLE generations ADD COLUMN protection_status TEXT DEFAULT 'safe'",
        "ALTER TABLE generations ADD COLUMN protection_score REAL DEFAULT 0",
        "ALTER TABLE generations ADD COLUMN protection_reason TEXT DEFAULT ''",
        "ALTER TABLE generations ADD COLUMN protection_source TEXT DEFAULT ''",
        "ALTER TABLE generations ADD COLUMN protection_checked_at TEXT DEFAULT ''",
        "ALTER TABLE generations ADD COLUMN is_hidden INTEGER DEFAULT 0",
        "ALTER TABLE generations ADD COLUMN hidden_at TEXT DEFAULT ''",
        "ALTER TABLE generations ADD COLUMN hidden_by TEXT DEFAULT ''",
    ):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass
    _backfill_legacy_prompt_protection(conn)
    _recheck_safe_heuristic_nsfw_risk_rows(conn)
    _recheck_safe_heuristic_video_rows(conn)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workflow_meta (
            filename TEXT PRIMARY KEY,
            name TEXT DEFAULT '',
            tags_json TEXT DEFAULT '[]',
            owner_id TEXT DEFAULT '',
            shared INTEGER DEFAULT 0,
            source TEXT DEFAULT '',
            source_path TEXT DEFAULT '',
            thumbnail TEXT DEFAULT '',
            sort_order INTEGER,
            versions_json TEXT DEFAULT '{}',
            active_version TEXT DEFAULT '',
            updated_at DATETIME DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workflow_editor_config (
            workflow_filename TEXT NOT NULL,
            config_scope TEXT NOT NULL DEFAULT 'global',
            user_id TEXT NOT NULL DEFAULT '',
            config_json TEXT NOT NULL,
            updated_at DATETIME DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (workflow_filename, config_scope, user_id)
        )
    """)
    conn.commit()
    conn.close()
    # Initialize auth DB
    _init_auth_db()
    _migrate_wf_meta_json_to_db()
    _migrate_legacy_wf_thumbnails()
    _migrate_wf_configs_to_db()


def _init_auth_db():
    """Create auth tables if needed."""
    conn = sqlite3.connect(AUTH_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            disabled INTEGER DEFAULT 0,
            avatar TEXT DEFAULT '',
            created_at DATETIME DEFAULT (datetime('now','localtime'))
        )
    """)
    for ddl in (
        "ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'",
        "ALTER TABLE users ADD COLUMN disabled INTEGER DEFAULT 0",
    ):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass
    has_admin = conn.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
    if not has_admin:
        first_user = conn.execute("SELECT id FROM users ORDER BY created_at ASC LIMIT 1").fetchone()
        if first_user:
            conn.execute("UPDATE users SET role='admin' WHERE id=?", (first_user[0],))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS site_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_by TEXT DEFAULT '',
            created_at DATETIME DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS site_notification_state (
            user_id TEXT PRIMARY KEY,
            suppressed_until_id INTEGER DEFAULT 0,
            updated_at DATETIME DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()
    conn.close()


def _history_prompt_preview(prompt: str, max_len: int = 320) -> str:
    text = str(prompt or "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "..."


def _gen_db_to_record(row: dict, compact: bool = False) -> dict:
    """Transform a SQLite generations row to the JSON record format used by the frontend."""
    if not isinstance(row, dict):
        row = dict(row)
    seed_val = str(row["seed"]) if row.get("seed") else ""
    deleted_at = row.get("deleted_at", "") or ""
    hidden_at = row.get("hidden_at", "") or ""
    params = {}
    if not compact and row.get("params"):
        try:
            params = json.loads(row["params"])
        except Exception:
            pass
    workflow = row["workflow"]
    workflow_type = _workflow_primary_type(workflow)
    prompt = row.get("prompt", "") or ""
    prompt_preview = _history_prompt_preview(prompt)
    record = {
        "id": row["id"],
        "filename": row.get("image_path", ""),
        "media_type": row.get("media_type", "") or output_media_type(row.get("image_path", "")),
        "thumb": row.get("thumb_path", ""),
        "workflow": workflow,
        "workflow_type": workflow_type,
        "prompt": "" if compact else prompt,
        "prompt_preview": prompt_preview,
        "seed": seed_val,
        "width": row.get("width", 0),
        "height": row.get("height", 0),
        "elapsed": row.get("duration_sec", 0),
        "time": row.get("created_at", ""),
        "user_id": row.get("user_id", ""),
        "username": row.get("username", ""),
        "is_public": bool(row.get("is_public", 0)),
        "is_hidden": bool(row.get("is_hidden", 0)),
        "hidden_at": hidden_at,
        "hidden_by": row.get("hidden_by", "") or "",
        "is_deleted": bool(deleted_at),
        "deleted_at": deleted_at,
        "deleted_by": row.get("deleted_by", "") or "",
        "sort_index": row.get("history_rowid", 0),
        "batch_id": row.get("batch_id", "") or "",
        "batch_index": row.get("batch_index", 0) or 0,
        "batch_count": row.get("batch_count", 1) or 1,
        "protection_status": row.get("protection_status", IMAGE_PROTECTION_SAFE) or IMAGE_PROTECTION_SAFE,
        "protection_score": float(row.get("protection_score", 0) or 0),
        "protection_reason": row.get("protection_reason", "") or "",
        "protection_source": row.get("protection_source", "") or "",
        "protection_checked_at": row.get("protection_checked_at", "") or "",
    }
    if compact:
        record["__compact"] = True
    else:
        record["field_values"] = params
    return record


def _backfill_legacy_prompt_protection(conn: sqlite3.Connection | None = None) -> int:
    """Persist protection for legacy rows using the current fallback image check."""
    own_conn = conn is None
    if conn is None:
        conn = sqlite3.connect(GEN_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT id, prompt, image_path, thumb_path
           FROM generations
           WHERE COALESCE(protection_status, '') IN ('', ?)
             AND COALESCE(protection_source, '') = ''
             AND COALESCE(protection_checked_at, '') = ''""",
        (IMAGE_PROTECTION_SAFE,),
    ).fetchall()
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    worker = ImageProtectionWorker(load_classifier=lambda: None)
    updates = []
    for row in rows:
        prompt = row["prompt"] or ""
        result = _check_image_protection_candidates(worker, row, prompt)
        if result.status != IMAGE_PROTECTION_PROTECTED:
            continue
        updates.append((result.status, result.score, result.reason, result.source, checked_at, row["id"]))
    if updates:
        conn.executemany(
            """UPDATE generations
               SET protection_status=?, protection_score=?, protection_reason=?, protection_source=?, protection_checked_at=?
               WHERE id=?""",
            updates,
        )
        conn.commit()
    if own_conn:
        conn.close()
    return len(updates)


def _recheck_safe_heuristic_nsfw_risk_rows(conn: sqlite3.Connection | None = None) -> int:
    """Re-check rows previously marked safe by the lightweight fallback after rule tuning."""
    own_conn = conn is None
    if conn is None:
        conn = sqlite3.connect(GEN_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT id, prompt, image_path, thumb_path
           FROM generations
           WHERE COALESCE(protection_status, '') = ?
             AND COALESCE(protection_source, '') = 'heuristic'""",
        (IMAGE_PROTECTION_SAFE,),
    ).fetchall()
    worker = ImageProtectionWorker(load_classifier=lambda: None)
    updates = []
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for row in rows:
        prompt = row["prompt"] or ""
        if not (prompt_needs_protection(prompt) or prompt_has_nsfw_risk(prompt)):
            continue
        result = _check_image_protection_candidates(worker, row, prompt)
        if result.status != IMAGE_PROTECTION_PROTECTED:
            continue
        updates.append((
            result.status,
            result.score,
            result.reason,
            result.source,
            checked_at,
            row["id"],
        ))
    if updates:
        conn.executemany(
            """UPDATE generations
               SET protection_status=?, protection_score=?, protection_reason=?, protection_source=?, protection_checked_at=?
               WHERE id=?""",
            updates,
        )
        conn.commit()
    if own_conn:
        conn.close()
    return len(updates)


def _recheck_safe_heuristic_video_rows(conn: sqlite3.Connection | None = None) -> int:
    """Re-check video previews that were marked safe before visual fallback tuning."""
    own_conn = conn is None
    if conn is None:
        conn = sqlite3.connect(GEN_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT id, prompt, image_path, thumb_path
           FROM generations
           WHERE COALESCE(protection_status, '') = ?
             AND COALESCE(protection_source, '') = 'heuristic'
             AND (
               COALESCE(media_type, '') = 'video'
               OR lower(COALESCE(image_path, '')) LIKE '%.mp4'
               OR lower(COALESCE(image_path, '')) LIKE '%.webm'
               OR lower(COALESCE(image_path, '')) LIKE '%.mov'
               OR lower(COALESCE(image_path, '')) LIKE '%.m4v'
             )""",
        (IMAGE_PROTECTION_SAFE,),
    ).fetchall()
    worker = ImageProtectionWorker(load_classifier=lambda: None)
    updates = []
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for row in rows:
        result = _check_image_protection_candidates(worker, row, row["prompt"] or "")
        if result.status != IMAGE_PROTECTION_PROTECTED:
            continue
        updates.append((
            result.status,
            result.score,
            result.reason,
            result.source,
            checked_at,
            row["id"],
        ))
    if updates:
        conn.executemany(
            """UPDATE generations
               SET protection_status=?, protection_score=?, protection_reason=?, protection_source=?, protection_checked_at=?
               WHERE id=?""",
            updates,
        )
        conn.commit()
    if own_conn:
        conn.close()
    return len(updates)


def _duration_percentile(durations: list[float], percentile: float) -> float:
    if not durations:
        return 0.0
    if len(durations) == 1:
        return float(durations[0])
    bounded = max(0.0, min(1.0, float(percentile)))
    pos = (len(durations) - 1) * bounded
    lower = int(pos)
    upper = min(lower + 1, len(durations) - 1)
    weight = pos - lower
    return float(durations[lower] * (1 - weight) + durations[upper] * weight)


def _workflow_cold_start_floor_sec(workflow: str) -> int:
    lower = os.path.basename(str(workflow or "")).lower()
    if "firered" in lower or "fire-red" in lower:
        return 300
    if "seedvr" in lower:
        return 240
    if "qwen" in lower:
        return 180
    if "flux2" in lower or "flux-2" in lower:
        return 180
    return 150


def _read_recent_log_entries() -> list[dict]:
    entries: list[dict] = []
    try:
        entries.extend(item for item in _log_buffer if isinstance(item, dict))
    except Exception:
        pass
    try:
        with open(_LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if isinstance(item, dict):
                    entries.append(item)
    except Exception:
        pass
    deduped: dict[tuple[str, str, float, str], dict] = {}
    for item in entries:
        try:
            key = (
                str(item.get("job_id") or ""),
                str(item.get("workflow") or ""),
                float(item.get("ts") or 0),
                str(item.get("msg") or ""),
            )
        except (TypeError, ValueError):
            continue
        deduped[key] = item
    return sorted(deduped.values(), key=lambda item: float(item.get("ts") or 0))


def _extract_log_node_class(msg: str) -> str:
    match = re.search(r"\[([^\]]+)\]", str(msg or ""))
    return match.group(1).strip() if match else ""


def _latest_logged_node_for_job(job: dict) -> str:
    job_id = str((job or {}).get("id") or "")
    if not job_id:
        return ""
    short_id = job_id[-12:]
    latest_ts = 0.0
    latest_node = ""
    for entry in _read_recent_log_entries():
        if str(entry.get("job_id") or "") != short_id:
            continue
        node = _extract_log_node_class(str(entry.get("msg") or ""))
        if not node:
            continue
        try:
            ts = float(entry.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        if ts >= latest_ts:
            latest_ts = ts
            latest_node = node
    return latest_node


def _workflow_node_calibrated_estimate_sec(workflow: str, job: dict) -> int | None:
    workflow = os.path.basename(str(workflow or ""))
    progress = (job or {}).get("progress") or {}
    current_node = str(progress.get("current_node") or "").strip() if isinstance(progress, dict) else ""
    if not current_node:
        current_node = _latest_logged_node_for_job(job or {})
    if not workflow or not current_node:
        return None

    grouped: dict[str, dict] = {}
    job_id = str((job or {}).get("id") or "")
    current_short_id = job_id[-12:] if job_id else ""
    for entry in _read_recent_log_entries():
        if os.path.basename(str(entry.get("workflow") or "")) != workflow:
            continue
        log_job_id = str(entry.get("job_id") or "")
        if not log_job_id or log_job_id == current_short_id:
            continue
        try:
            ts = float(entry.get("ts") or 0)
        except (TypeError, ValueError):
            continue
        if ts <= 0:
            continue
        group = grouped.setdefault(log_job_id, {"start": 0.0, "end": 0.0, "nodes": {}})
        phase = str(entry.get("phase") or "")
        msg = str(entry.get("msg") or "")
        if phase == "开始" or (not group["start"] and phase in {"生成", "队列"}):
            group["start"] = ts
        node = _extract_log_node_class(msg)
        if node and node not in group["nodes"]:
            group["nodes"][node] = ts
        if phase == "完成" and "工作流完成" in msg:
            group["end"] = ts

    remaining_samples: list[float] = []
    total_samples: list[float] = []
    for group in grouped.values():
        start = float(group.get("start") or 0)
        end = float(group.get("end") or 0)
        node_ts = float((group.get("nodes") or {}).get(current_node) or 0)
        if not start or not end or end <= start:
            continue
        total_samples.append(end - start)
        if node_ts and end > node_ts:
            remaining_samples.append(end - node_ts)

    if not remaining_samples:
        return None

    started_at = 0.0
    for key in ("generating_at", "submitted_at", "created_at_ts"):
        try:
            started_at = float((job or {}).get(key) or 0)
        except (TypeError, ValueError):
            started_at = 0.0
        if started_at:
            break
    elapsed = max(0.0, time.time() - started_at) if started_at else 0.0
    remaining = _duration_percentile(sorted(remaining_samples), 0.5)
    total_floor = _duration_percentile(sorted(total_samples), 0.5) if total_samples else 0.0
    return int(round(max(elapsed + remaining, total_floor)))


def _is_cold_or_model_loading_job(job: dict, workflow: str) -> bool:
    status = str((job or {}).get("status") or "").strip().lower()
    if status in {"dispatching", "starting_comfyui"}:
        return True
    workflow = os.path.basename(str(workflow or ""))
    if not workflow:
        return False

    try:
        progress = (job or {}).get("progress") or {}
        pct = float(progress.get("pct") or 0)
    except (TypeError, ValueError):
        pct = 0.0
    lower = workflow.lower()
    if status in {"preparing", "submitting", "generating"} and pct and pct <= 35:
        if any(token in lower for token in ("firered", "fire-red", "qwen", "flux2", "flux-2")):
            return True

    inst_name = str((job or {}).get("instance") or "").strip()
    if not inst_name:
        return status in {"queued", "preparing", "submitting"}
    expected_group = extract_model_group(workflow)
    loaded_group = _instance_group.get(inst_name, "")
    return bool(expected_group and loaded_group != expected_group)


def _estimate_workflow_duration_sec(workflow: str, job: dict | None = None) -> int | None:
    workflow = os.path.basename(str(workflow or ""))
    if not workflow:
        return None
    try:
        conn = sqlite3.connect(GEN_DB)
        rows = conn.execute(
            """
            SELECT duration_sec
            FROM generations
            WHERE workflow = ?
              AND duration_sec > 0
              AND (status IS NULL OR status != 'deleted')
            ORDER BY duration_sec ASC
            """,
            (workflow,),
        ).fetchall()
        conn.close()
    except Exception:
        return None
    durations = [float(row[0]) for row in rows if row and row[0]]
    if not durations:
        return None
    median = _duration_percentile(durations, 0.5)
    calibrated = _workflow_node_calibrated_estimate_sec(workflow, job or {})
    if _is_cold_or_model_loading_job(job or {}, workflow):
        p90 = _duration_percentile(durations, 0.9)
        floor = _workflow_cold_start_floor_sec(workflow)
        return int(round(max(p90, median + floor * 0.6, floor, calibrated or 0)))
    lower = workflow.lower()
    if "firered" in lower or "fire-red" in lower:
        median = max(median, 120)
    return int(round(max(median, calibrated or 0)))


def _format_estimated_duration_label(seconds: int | float | None) -> str:
    try:
        raw_seconds = float(seconds or 0)
    except (TypeError, ValueError):
        return ""
    if raw_seconds <= 0:
        return ""
    half_minutes = max(1.0, int((raw_seconds / 60.0) * 2 + 0.5) / 2.0)
    if half_minutes.is_integer():
        minute_text = str(int(half_minutes))
    else:
        minute_text = f"{half_minutes:.1f}".rstrip("0").rstrip(".")
    return f"预计{minute_text}分钟"


def _job_with_time_estimate(job: dict) -> dict:
    enriched = dict(job or {})
    estimate = _estimate_workflow_duration_sec(enriched.get("workflow", ""), enriched)
    if estimate:
        existing = 0
        try:
            existing = int(float(enriched.get("estimated_duration_sec") or 0))
        except (TypeError, ValueError):
            existing = 0
        estimate = max(estimate, existing)
        enriched["estimated_duration_sec"] = estimate
        label = _format_estimated_duration_label(estimate)
        if label:
            enriched["estimated_duration_label"] = label
    return enriched


def _enrich_broadcast_payload(data: dict) -> dict:
    if not isinstance(data, dict) or data.get("type") != "job_update":
        return data
    job = data.get("job")
    if not isinstance(job, dict):
        return data
    enriched = dict(data)
    enriched["job"] = _job_with_time_estimate(job)
    return enriched


def _history_username_map(user_ids: list[str]) -> dict[str, str]:
    """Look up usernames from the auth database for generation history rows."""
    ids = sorted({str(uid) for uid in user_ids if uid})
    if not ids:
        return {}
    try:
        conn = sqlite3.connect(AUTH_DB)
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT id, username FROM users WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        conn.close()
        return {row["id"]: row["username"] for row in rows}
    except Exception as e:
        add_log("warn", "history", f"用户名查询失败：{e}", "")
        return {}


def _workflow_primary_type(filename: str) -> str:
    """Return the backend workflow category even when the workflow itself is not visible."""
    name = os.path.basename(filename or "")
    try:
        meta = _load_wf_meta()
        entry = _normalize_wf_meta_entry(name, meta.get(name, {}))
        tags = entry.get("tags") or []
        if tags:
            return str(tags[0])
    except Exception:
        pass
    lower = name.lower()
    if lower.startswith("i2v") or "-i2v" in lower or "_i2v" in lower:
        return "图生视频"
    if lower.startswith("t2v") or "-t2v" in lower or "_t2v" in lower:
        return "文生视频"
    if lower.startswith("i2i") or "-i2i" in lower or "_i2i" in lower:
        return "图生图"
    if lower.startswith("t2i") or "-t2i" in lower or "_t2i" in lower:
        return "文生图"
    return ""


def _insert_generation(record: dict, elapsed: float, user_id: str = ""):
    """Insert a generation record into SQLite."""
    try:
        if not record.get("thumb") and record.get("filename"):
            record["thumb"] = make_thumbnail(record.get("filename", "")) or ""
        media_type = str(record.get("media_type") or output_media_type(record.get("filename", "")))
        if media_type not in {"image", "video"}:
            media_type = output_media_type(record.get("filename", ""))
        actual_w, actual_h = get_media_size(record.get("filename", ""), media_type, record.get("thumb", ""))
        if actual_w and actual_h:
            record["width"] = actual_w
            record["height"] = actual_h
        conn = sqlite3.connect(GEN_DB)
        protection_status = str(record.get("protection_status") or IMAGE_PROTECTION_SAFE)
        if protection_status not in {IMAGE_PROTECTION_PENDING, IMAGE_PROTECTION_SAFE, IMAGE_PROTECTION_PROTECTED, IMAGE_PROTECTION_ERROR}:
            protection_status = IMAGE_PROTECTION_PENDING
        conn.execute(
            """INSERT OR REPLACE INTO generations
               (id, workflow, media_type, image_path, thumb_path, prompt, width, height, seed, duration_sec, created_at, params, user_id, is_public, batch_id, batch_index, batch_count,
                protection_status, protection_score, protection_reason, protection_source, protection_checked_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record["id"],
                record.get("workflow", ""),
                media_type,
                record.get("filename", ""),
                record.get("thumb", ""),
                record.get("prompt", ""),
                record.get("width", 0),
                record.get("height", 0),
                int(record.get("seed", 0) or 0),
                round(elapsed),
                record.get("time", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                json.dumps(record.get("field_values", {}), ensure_ascii=False),
                user_id,
                1 if record.get("is_public") else 0,
                record.get("batch_id", "") or "",
                int(record.get("batch_index", 0) or 0),
                int(record.get("batch_count", 1) or 1),
                protection_status,
                float(record.get("protection_score", 0) or 0),
                record.get("protection_reason", "") or "",
                record.get("protection_source", "") or "",
                record.get("protection_checked_at", "") or "",
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        add_log("error", "db", f"SQLite insert failed: {e}", record.get("id", ""))


def _update_generation_protection(
    item_id: str,
    status: str,
    score: float = 0.0,
    reason: str = "",
    source: str = "",
    checked_at: str | None = None,
) -> None:
    """Persist image protection status for a generation record."""
    normalized = status if status in {IMAGE_PROTECTION_SAFE, IMAGE_PROTECTION_PROTECTED, IMAGE_PROTECTION_ERROR} else IMAGE_PROTECTION_ERROR
    checked = checked_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(GEN_DB)
    conn.execute(
        """UPDATE generations
           SET protection_status=?, protection_score=?, protection_reason=?, protection_source=?, protection_checked_at=?
           WHERE id=?""",
        (normalized, float(score or 0), reason or "", source or "", checked, item_id),
    )
    conn.commit()
    conn.close()
    for item in history:
        if str(item.get("id") or "") == str(item_id):
            item["protection_status"] = normalized
            item["protection_score"] = float(score or 0)
            item["protection_reason"] = reason or ""
            item["protection_source"] = source or ""
            item["protection_checked_at"] = checked
            break


def _update_generation_thumb(item_id: str, thumb: str) -> None:
    if not item_id or not thumb:
        return
    conn = _db_connect()
    try:
        conn.execute("UPDATE generations SET thumb_path=? WHERE id=?", (thumb, item_id))
        conn.commit()
    finally:
        conn.close()
    for item in history:
        if str(item.get("id") or "") == str(item_id):
            item["thumb"] = thumb
            break


def _scan_generation_cover_thumb(item_id: str, thumb: str, prompt: str = "") -> ImageProtectionResult:
    """Run protection review for a manually selected video-cover frame."""
    record = {
        "id": item_id,
        "thumb": thumb,
        "thumb_path": thumb,
        "filename": thumb,
        "image_path": thumb,
        "media_type": "image",
    }
    try:
        result = _check_image_protection_candidates(_image_protection_worker, record, prompt or "")
    except Exception as exc:
        result = ImageProtectionResult(IMAGE_PROTECTION_ERROR, 1.0, str(exc), "local-error")
    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _update_generation_protection(
        item_id,
        status=result.status,
        score=result.score,
        reason=result.reason,
        source=result.source,
        checked_at=checked_at,
    )
    result.checked_at = checked_at
    add_log("info", "image_protection", f"{item_id}: cover {result.status} ({result.score:.3f})", item_id)
    return result


def _extract_history_video_frame(
    video_rel: str,
    item_id: str,
    time_sec: float,
    current_user: dict,
    copy_to_input: bool = False,
) -> dict:
    safe_video_rel = str(video_rel or "").replace("\\", "/").lstrip("/")
    if not safe_video_rel:
        raise HTTPException(400, "Missing video path")
    src = _safe_rel_path(OUTPUT_DIR, safe_video_rel)
    if not os.path.isfile(src):
        raise HTTPException(404, "Video file not found")
    if output_media_type(safe_video_rel) != "video":
        raise HTTPException(400, "History item is not a video")
    ffmpeg = _project_ffmpeg_bin()
    if not ffmpeg:
        raise HTTPException(500, "ffmpeg is not configured")
    try:
        requested_pos = max(0.0, min(float(time_sec or 0), 60 * 60 * 6))
    except (TypeError, ValueError):
        requested_pos = 0.0
    duration, fps = _probe_video_timing(src)
    pos = _safe_video_frame_time(requested_pos, duration, fps)
    millis = int(round(pos * 1000))
    rel_dir = os.path.dirname(safe_video_rel)
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.splitext(os.path.basename(safe_video_rel))[0])[:80] or "video"
    frame_name = f"{stem}_frame_{millis:08d}.jpg"
    frame_rel = os.path.join(rel_dir, frame_name).replace("\\", "/") if rel_dir else frame_name
    frame_path = _safe_rel_path(OUTPUT_DIR, frame_rel)
    os.makedirs(os.path.dirname(frame_path), exist_ok=True)
    result = None
    frame_ok = False
    stderr = ""
    attempts = [pos]
    if duration > 0:
        fallback = _safe_video_frame_time(pos - max(0.25, 2.0 / max(fps, 1.0)), duration, fps)
        if abs(fallback - pos) > 0.001:
            attempts.append(fallback)
    for attempt_pos in attempts:
        try:
            result = _extract_video_frame_with_ffmpeg(ffmpeg, src, frame_path, attempt_pos)
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "Frame extraction timed out")
        except Exception as e:
            raise HTTPException(500, f"Frame extraction failed: {e}")
        stderr = (result.stderr or b"").decode("utf-8", "ignore").strip()
        frame_ok = result.returncode == 0 and os.path.isfile(frame_path) and os.path.getsize(frame_path) > 0
        if frame_ok:
            pos = attempt_pos
            break
        try:
            if os.path.isfile(frame_path):
                os.remove(frame_path)
        except OSError:
            pass
    if not frame_ok:
        detail = "视频最后一帧截取失败，请向前移动一帧后重试" if duration > 0 else "视频帧截取失败"
        if stderr and "conversion failed" not in stderr.lower():
            detail = f"{detail}: {stderr[-240:]}"
        raise HTTPException(500, detail)
    payload = {
        "ok": True,
        "frame": frame_rel,
        "time": pos,
    }
    if copy_to_input:
        user_dir = _user_id(current_user) or "anonymous"
        date_dir = datetime.now().strftime("%Y-%m-%d")
        input_name = f"{stem}_frame_{millis:08d}_{random.randint(1000, 9999)}.jpg"
        input_rel = f"{user_dir}/{date_dir}/{input_name}"
        input_path = os.path.join(COMFYUI_INPUT, user_dir, date_dir, input_name)
        os.makedirs(os.path.dirname(input_path), exist_ok=True)
        shutil.copyfile(frame_path, input_path)
        payload["input_filename"] = input_rel
    return payload


# ── Auth Helpers ──


def _create_token(user_id: str, username: str) -> str:
    """Create a JWT token."""
    role = _get_user_role(user_id)
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "exp": datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _get_user_role(user_id: str) -> str:
    if not user_id:
        return "user"
    try:
        conn = sqlite3.connect(AUTH_DB)
        row = conn.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        conn.close()
        return (row[0] if row else "user") or "user"
    except Exception:
        return "user"


def _auth_token_from_request(request: Request) -> str:
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer "):
        return auth.split(" ", 1)[1]
    cookie_token = request.cookies.get(AUTH_COOKIE_NAME, "")
    if cookie_token:
        if cookie_token.startswith("Bearer "):
            return cookie_token.split(" ", 1)[1]
        return cookie_token
    return ""


def _set_auth_cookie(response: Response, token: str, request: Request | None = None) -> None:
    secure = bool(request and request.url.scheme == "https")
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        max_age=ACCESS_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    _set_csrf_cookie(response, request)


def _set_csrf_cookie(response: Response, request: Request | None = None) -> str:
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        max_age=ACCESS_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=False,
        secure=bool(request and request.url.scheme == "https"),
        samesite="lax",
        path="/",
    )
    return token


def _csrf_token_valid(request: Request) -> bool:
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
    header_token = request.headers.get(_CSRF_HEADER_NAME, "")
    return bool(cookie_token and header_token and secrets.compare_digest(cookie_token, header_token))


def _auth_rate_limit_key(request: Request, action: str, username: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{action}:{host}:{str(username or '').strip().lower()}"


def _check_auth_rate_limit(request: Request, action: str, username: str) -> None:
    now = time.time()
    key = _auth_rate_limit_key(request, action, username)
    cutoff = now - _AUTH_RATE_LIMIT_WINDOW_SEC
    attempts = [ts for ts in _auth_rate_attempts.get(key, []) if ts >= cutoff]
    if len(attempts) >= _AUTH_RATE_LIMIT_MAX_ATTEMPTS:
        _auth_rate_attempts[key] = attempts
        raise HTTPException(429, "Too many authentication attempts")
    attempts.append(now)
    _auth_rate_attempts[key] = attempts


def _clear_auth_rate_limit(request: Request, action: str, username: str) -> None:
    _auth_rate_attempts.pop(_auth_rate_limit_key(request, action, username), None)


def get_current_user(request: Request) -> dict:
    """Extract current user from Authorization header."""
    token = _auth_token_from_request(request)
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        conn = sqlite3.connect(AUTH_DB)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT role, disabled FROM users WHERE id=?", (payload.get("sub", ""),)).fetchone()
        conn.close()
        if not row:
            raise HTTPException(401, "User not found")
        if row["disabled"]:
            raise HTTPException(403, "User disabled")
        payload["role"] = row["role"] or "user"
        return payload
    except JWTError:
        raise HTTPException(401, "Invalid token")


def get_current_user_optional(request: Request) -> dict | None:
    token = _auth_token_from_request(request)
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        conn = sqlite3.connect(AUTH_DB)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT role, disabled FROM users WHERE id=?", (payload.get("sub", ""),)).fetchone()
        conn.close()
        if not row or row["disabled"]:
            return None
        payload["role"] = row["role"] or "user"
        return payload
    except Exception:
        return None


def _get_user_from_token(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        conn = sqlite3.connect(AUTH_DB)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT role, disabled FROM users WHERE id=?", (payload.get("sub", ""),)).fetchone()
        conn.close()
        if not row or row["disabled"]:
            return None
        payload["role"] = row["role"] or "user"
        return payload
    except Exception:
        return None


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Require an authenticated administrator for privileged local operations."""
    if current_user.get("role") != "admin" and _get_user_role(current_user.get("sub", "")) != "admin":
        raise HTTPException(403, "Admin permission required")
    return current_user


def _user_id(current_user: dict) -> str:
    return current_user.get("sub", "") if current_user else ""


def _is_admin_user(current_user: dict | None) -> bool:
    if not current_user:
        return False
    if current_user.get("role") == "admin":
        return True
    return _get_user_role(current_user.get("sub", "")) == "admin"


def _bootstrap_admin_user_id() -> str:
    try:
        conn = sqlite3.connect(AUTH_DB)
        row = conn.execute("SELECT id FROM users WHERE username='admin' LIMIT 1").fetchone()
        conn.close()
        return row[0] if row else "admin"
    except Exception:
        return "admin"


def _normalize_node(node: dict) -> dict:
    normalized = dict(node or {})
    normalized.setdefault("owner_id", _bootstrap_admin_user_id())
    normalized["shared"] = bool(normalized.get("shared", False))
    for inst in normalized.get("instances", []) or []:
        if isinstance(inst, dict):
            inst["shared"] = bool(inst.get("shared", normalized["shared"]))
    return normalized


def _can_view_node(node: dict, current_user: dict) -> bool:
    if _is_admin_user(current_user):
        return True
    uid = _user_id(current_user or {})
    owner_id = node.get("owner_id") or _bootstrap_admin_user_id()
    return bool(uid and (owner_id == uid or node.get("shared")))


def _can_manage_node(node: dict, current_user: dict) -> bool:
    if _is_admin_user(current_user):
        return True
    uid = _user_id(current_user or {})
    owner_id = node.get("owner_id") or _bootstrap_admin_user_id()
    return bool(uid and owner_id == uid)


def _ensure_node_access(node: dict | None, current_user: dict, require_manage: bool = False) -> dict:
    if not node:
        raise HTTPException(404, "Node not found")
    normalized = _normalize_node(node)
    allowed = _can_manage_node(normalized, current_user) if require_manage else _can_view_node(normalized, current_user)
    if not allowed:
        raise HTTPException(403, "No permission for this device")
    return normalized


def _normalize_wf_meta_entry(filename: str, entry: dict | None) -> dict:
    item = dict(entry or {})
    item.setdefault("name", filename.replace(".json", ""))
    item.setdefault("tags", [])
    item.setdefault("owner_id", _bootstrap_admin_user_id())
    item["shared"] = bool(item.get("shared", False))
    return item


def _write_wf_meta_entry_to_db(filename: str, entry: dict, conn: sqlite3.Connection | None = None):
    normalized = _normalize_wf_meta_entry(filename, entry)
    own_conn = conn is None
    if own_conn:
        conn = _db_connect()
    conn.execute(
        """
        INSERT INTO workflow_meta
            (filename, name, tags_json, owner_id, shared, source, source_path, thumbnail, sort_order, versions_json, active_version, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
        ON CONFLICT(filename) DO UPDATE SET
            name=excluded.name,
            tags_json=excluded.tags_json,
            owner_id=excluded.owner_id,
            shared=excluded.shared,
            source=excluded.source,
            source_path=excluded.source_path,
            thumbnail=excluded.thumbnail,
            sort_order=excluded.sort_order,
            versions_json=excluded.versions_json,
            active_version=excluded.active_version,
            updated_at=datetime('now','localtime')
        """,
        (
            filename,
            normalized.get("name", filename.replace(".json", "")),
            _json_dumps_compact(normalized.get("tags", [])),
            normalized.get("owner_id", _bootstrap_admin_user_id()),
            1 if normalized.get("shared") else 0,
            normalized.get("source", ""),
            normalized.get("source_path", ""),
            normalized.get("thumbnail", ""),
            normalized.get("sort_order"),
            _json_dumps_compact(normalized.get("versions", {})),
            normalized.get("active_version", ""),
        ),
    )
    if own_conn:
        conn.commit()
        conn.close()


def _migrate_wf_meta_json_to_db():
    if not os.path.isfile(WF_META_FILE):
        return
    try:
        with open(WF_META_FILE) as f:
            raw = json.load(f)
    except Exception as e:
        add_log("warn", "wf_meta", f"Failed to migrate wf_meta.json: {e}")
        return
    if not isinstance(raw, dict):
        return
    conn = _db_connect()
    try:
        for filename, entry in raw.items():
            exists = conn.execute("SELECT 1 FROM workflow_meta WHERE filename=? LIMIT 1", (filename,)).fetchone()
            if exists:
                continue
            _write_wf_meta_entry_to_db(filename, entry or {}, conn=conn)
        conn.commit()
    finally:
        conn.close()


def _migrate_legacy_wf_thumbnails():
    """Move old flat workflow thumbnails next to their workflow JSON files."""
    if not os.path.isdir(WF_THUMB_DIR):
        return
    meta = _load_wf_meta()
    changed = False
    for fname, entry in list(meta.items()):
        thumb = str((entry or {}).get("thumbnail") or "")
        if not thumb or "/" in thumb.replace("\\", "/"):
            continue
        src = os.path.join(WF_THUMB_DIR, thumb)
        if not os.path.isfile(src):
            continue
        ext = os.path.splitext(thumb)[1].lower() or ".jpg"
        entry = _normalize_wf_meta_entry(fname, entry)
        try:
            dest, rel = _workflow_thumbnail_path(fname, entry, ext)
        except HTTPException as e:
            add_log("warn", "wf_thumb", f"Failed to migrate {thumb}: {e.detail}")
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.abspath(dest) != os.path.abspath(src):
            if os.path.isfile(dest):
                os.remove(src)
            else:
                shutil.move(src, dest)
        entry["thumbnail"] = rel
        _write_wf_meta_entry_to_db(fname, entry)
        changed = True
    if changed:
        _export_wf_meta_json_from_db()


def _delete_wf_meta_entry(filename: str):
    conn = _db_connect()
    try:
        conn.execute("DELETE FROM workflow_meta WHERE filename=?", (filename,))
        conn.commit()
    finally:
        conn.close()


def _export_wf_meta_json_from_db():
    meta = _load_wf_meta()
    with open(WF_META_FILE, "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _can_view_workflow(filename: str, entry: dict, current_user: dict | None) -> bool:
    if current_user and _is_admin_user(current_user):
        return True
    owner_id = entry.get("owner_id") or _bootstrap_admin_user_id()
    if not current_user:
        return bool(entry.get("shared"))
    uid = _user_id(current_user or {})
    return bool(uid and (owner_id == uid or entry.get("shared")))


def _can_manage_workflow(filename: str, entry: dict, current_user: dict) -> bool:
    if _is_admin_user(current_user):
        return True
    uid = _user_id(current_user or {})
    owner_id = entry.get("owner_id") or _bootstrap_admin_user_id()
    return bool(uid and owner_id == uid)


def _can_access_job(job: dict, current_user: dict) -> bool:
    if _is_admin_user(current_user):
        return True
    owner = job.get("user_id", "")
    uid = _user_id(current_user or {})
    return bool(uid and owner == uid)


def get_current_user_id(request: Request) -> str:
    """Get user_id from Authorization header, returns 'anonymous' if not available."""
    token = _auth_token_from_request(request)
    if not token:
        return "anonymous"
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub", "anonymous")
    except JWTError:
        return "anonymous"


# Legacy DGX paths (kept for backward compat when running on Spark)
COMFYUI_DIR   = "/home/sjcta/software/ComfyUI-Project"
COMFYUI_INPUT = os.environ.get("COMFYUI_INPUT") or "/home/sjcta/software/ComfyUI-Project/ComfyUI/input"
if not os.path.isdir(COMFYUI_INPUT):
    COMFYUI_INPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "input")
VLLM_CONTAINER = "qwen36-vllm"
LEGACY_VLLM_MANAGEMENT_ENV = "EZ_ENABLE_LEGACY_VLLM_MANAGEMENT"

# ── State ───────────────────────────────────────────────────────────────
jobs: dict[str, dict] = {}
_job_tasks: dict[str, asyncio.Task] = {}
history: list[dict] = []
ws_clients: list[WebSocket] = []
ws_client_users: dict[WebSocket, dict] = {}
gpu_cache: dict = {"ts": 0, "data": None}
node_gpu_cache: dict = {}
NODE_GPU_CACHE_TTL = 5
NODE_GPU_STALE_TTL = 60

# ── Model Affinity Routing ──────────────────────────────────────────────
# Per-instance semaphores: one concurrent job per ComfyUI instance
def _build_instance_semas():
    return {inst["name"]: asyncio.Semaphore(1) for inst in _get_generation_instances()}
def _build_instance_last_active():
    return {inst["name"]: 0 for inst in _get_enabled_instances()}
def _build_instance_group():
    return {inst["name"]: "" for inst in _get_generation_instances()}

_instance_semas: dict[str, asyncio.Semaphore] = {}
_instance_last_active: dict[str, float] = {}
_instance_group: dict[str, str] = {}
_instance_start_grace: dict[str, float] = {}  # instance name -> ts of last start action
START_GRACE_PERIOD = 90  # seconds to skip dead watcher check after intentional start
DEFAULT_INSTANCE_IDLE_TIMEOUT = 900
FIRERED_INSTANCE_IDLE_TIMEOUT = 2700


def _idle_timeout_for_instance(instance_name: str) -> int:
    if _instance_group.get(instance_name) == "i2i-firered":
        return FIRERED_INSTANCE_IDLE_TIMEOUT
    return DEFAULT_INSTANCE_IDLE_TIMEOUT

def _refresh_instance_state():
    """Refresh per-instance semaphores and state dicts from current nodes."""
    global _instance_semas, _instance_last_active, _instance_group
    current = {inst["name"] for inst in _get_generation_instances()}
    # Add new
    for inst in _get_generation_instances():
        if inst["name"] not in _instance_semas:
            _instance_semas[inst["name"]] = asyncio.Semaphore(1)
        if inst["name"] not in _instance_last_active:
            _instance_last_active[inst["name"]] = 0
        if inst["name"] not in _instance_group:
            _instance_group[inst["name"]] = ""

# Model group definitions — workflows sharing a base model get the same group.
# Affinity matching is done at the GROUP level, not filename level.
MODEL_GROUPS = [
    # (group_name, keywords_in_filename)
    ("flux2-klein",  ["flux2_klein", "flux2-klein", "flux-2-klein"]),
    ("flux2-dev",    ["flux2_dev", "flux2-dev", "flux.2-dev"]),
    ("nunchaku",      ["nunchaku"]),
    ("z-image-turbo", ["z-image-turbo", "z_image_turbo", "z-image", "z-xxx", "z_xxx"]),
    ("seedvr",        ["seedvr"]),
    ("i2i-firered",   ["firered", "fire-red"]),
    ("i2i-qwen",      ["i2i_qwen", "i2i-qwen"]),
]

def extract_model_group(workflow_name: str) -> str:
    """Extract the model group from a workflow filename."""
    lower = workflow_name.lower()
    for group, keywords in MODEL_GROUPS:
        for kw in keywords:
            if kw in lower:
                return group
    return workflow_name  # unknown → exact match fallback

def pick_affinity_instance(workflow_name: str) -> dict | None:
    """Return the instance whose loaded model group matches this workflow's group."""
    if not workflow_name:
        return None
    wf_group = extract_model_group(workflow_name)
    for inst in _get_generation_instances():
        if _instance_group.get(inst["name"]) == wf_group:
            return inst
    return None

# ── Background tasks (hold references to prevent GC) ──
_background_tasks: list = []
_image_protection_worker = ImageProtectionWorker()
_image_protection_tasks: set[asyncio.Task] = set()


def _image_protection_path(record: dict) -> str:
    rel = record.get("thumb") or record.get("filename") or ""
    return os.path.join(OUTPUT_DIR, rel)


def _job_done_payload_from_records(job_id: str, records: list[dict], elapsed: float) -> dict:
    cover = records[0] if records else {}
    batch_count = len(records) or int(cover.get("batch_count", 1) or 1)
    return {
        "status": "done",
        "message": f"完成 ({elapsed:.1f}s)",
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
        "protection_status": cover.get("protection_status", IMAGE_PROTECTION_SAFE) or IMAGE_PROTECTION_SAFE,
        "protection_score": cover.get("protection_score", 0) or 0,
        "protection_source": cover.get("protection_source", "") or "",
        "protection_reason": cover.get("protection_reason", "") or "",
    }


def _apply_protection_result(record: dict, result: ImageProtectionResult) -> None:
    _update_generation_protection(
        record.get("id", ""),
        status=result.status,
        score=result.score,
        reason=result.reason,
        source=result.source,
    )
    record["protection_status"] = result.status
    record["protection_score"] = result.score
    record["protection_reason"] = result.reason
    record["protection_source"] = result.source
    record["protection_checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def _complete_image_protection_job(job_id: str, records: list[dict], elapsed: float) -> None:
    if not records:
        return
    try:
        for record in records:
            media_type = str(record.get("media_type") or output_media_type(record.get("filename", "")) or "image")
            if media_type == "video" and not record.get("thumb") and record.get("filename"):
                thumb = make_thumbnail(record.get("filename", "")) or ""
                if thumb:
                    record["thumb"] = thumb
                    _update_generation_thumb(record.get("id", ""), thumb)
            if media_type != "image" and not (media_type == "video" and record.get("thumb")):
                result = ImageProtectionResult(IMAGE_PROTECTION_SAFE, 0.0, "non-image media skipped", "media-type")
                _apply_protection_result(record, result)
                add_log("info", "image_protection", f"{record.get('id', '')}: skipped {media_type}", job_id)
                continue
            result = await asyncio.to_thread(
                _check_image_protection_candidates,
                _image_protection_worker,
                record,
                record.get("prompt", "") or record.get("prompt_preview", ""),
            )
            _apply_protection_result(record, result)
            add_log("info", "image_protection", f"{record.get('id', '')}: {result.status} ({result.score:.3f})", job_id)
        save_history()
        if job_id and job_id in jobs:
            jobs[job_id].update(_job_done_payload_from_records(job_id, records, elapsed))
            _cleanup_retry_source_jobs(job_id)
            save_jobs()
            await broadcast({"type": "job_update", "job": jobs[job_id]})
    except Exception as exc:
        add_log("error", "image_protection", f"Image protection failed: {exc}", job_id)
        for record in records:
            result = ImageProtectionResult(IMAGE_PROTECTION_ERROR, 1.0, str(exc), "local-error")
            try:
                _apply_protection_result(record, result)
            except Exception:
                pass
        save_history()
        if job_id and job_id in jobs:
            jobs[job_id].update(_job_done_payload_from_records(job_id, records, elapsed))
            _cleanup_retry_source_jobs(job_id)
            save_jobs()
            await broadcast({"type": "job_update", "job": jobs[job_id]})


def _schedule_image_protection(job_id: str, records: list[dict], elapsed: float) -> None:
    task = asyncio.create_task(_complete_image_protection_job(job_id, records, elapsed))
    _image_protection_tasks.add(task)
    task.add_done_callback(lambda t: _image_protection_tasks.discard(t))


def _pending_image_protection_records(limit: int = 100) -> list[dict]:
    conn = sqlite3.connect(GEN_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT * FROM generations
           WHERE COALESCE(protection_status, 'safe') = ?
             AND COALESCE(deleted_at, '') = ''
           ORDER BY datetime(created_at) ASC
           LIMIT ?""",
        (IMAGE_PROTECTION_PENDING, limit),
    ).fetchall()
    conn.close()
    return [_gen_db_to_record(dict(row)) for row in rows]


def _resume_pending_image_protection_checks() -> None:
    for record in _pending_image_protection_records():
        _schedule_image_protection("", [record], float(record.get("elapsed", 0) or 0))

# ── Lifecycle ───────────────────────────────────────────────────────────

async def _idle_instance_watcher():
    """Stop instances idle for more than 15 minutes to free VRAM."""
    while True:
        await asyncio.sleep(60)
        now = time.time()
        for inst in _get_enabled_instances():
            name = inst["name"]
            last = _instance_last_active.get(name, 0)
            if last == 0:
                continue
            if _has_active_instance_job(name):
                continue
            idle_timeout = _idle_timeout_for_instance(name)
            if now - last > idle_timeout:
                node = _get_node_by_id(inst.get("_node_id", ""))
                if node:
                    if not _check_service_active(node, inst):
                        _instance_last_active[name] = 0
                        _instance_group[name] = ""
                        continue
                    add_log("warn", "idle", f"Stopping idle {name} ({now - last:.0f}s idle)")
                    _managed_instance_action(node, inst, "stop", reason="idle")


async def _dead_instance_watcher():
    while True:
        await asyncio.sleep(60)
        for inst in _get_enabled_instances():
            name = inst["name"]
            node = _get_node_by_id(inst.get("_node_id", ""))
            if not node:
                continue
            conn = node.get("connection", "local")
            if conn not in ("local", "remote-ssh"):
                continue
            # Skip instances in grace period (recently started, still booting)
            grace_ts = _instance_start_grace.get(name, 0)
            if grace_ts and time.time() - grace_ts < START_GRACE_PERIOD:
                continue
            if _has_active_instance_job(name):
                continue
            # Check systemd status via SSH or local
            active = _check_service_active(node, inst)
            if active and not comfyui_up(inst["url"]):
                add_log("warn", "dead", f"Instance {name} unresponsive, restarting...")
                _managed_instance_action(node, inst, "restart", reason="dead")
                for _ in range(90):
                    if comfyui_up(inst["url"]):
                        add_log("info", "dead", f"Instance {name} recovered")
                        break
                    await asyncio.sleep(2)

def _check_service_active(node: dict, instance: dict) -> bool:
    svc = instance.get("service", f"comfyui-{instance['name'].lower()}")
    conn = node.get("connection", "local")
    try:
        if conn == "local":
            r = subprocess.run(["systemctl", "--user", "is-active", svc],
                capture_output=True, text=True, timeout=5,
                env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
                     "XDG_RUNTIME_DIR": "/run/user/1000"})
            return r.stdout.strip() == "active"
        elif conn == "remote-ssh":
            ssh = _resolve_ssh_config(node.get("ssh_config", {}))
            cmd = []
            if ssh.get("auth") == "password" and ssh.get("password"):
                cmd = ["sshpass", "-p", ssh["password"], "ssh",
                       "-p", str(ssh.get("port", 22)),
                       f"{ssh.get('user', 'root')}@{node['host']}"]
            else:
                cmd = ["ssh", "-p", str(ssh.get("port", 22)),
                       f"{ssh.get('user', 'root')}@{node['host']}"]
            cmd += ["systemctl", "--user", "is-active", svc]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return r.stdout.strip() == "active"
    except Exception:
        pass
    return False


def _managed_service_active(instance: dict) -> bool:
    node = _get_node_by_id(instance.get("_node_id", ""))
    if not node:
        return False
    return _check_service_active(node, instance)

async def _stuck_job_watcher():
    """Fail jobs that exceed their current stage timeout and release their instance."""
    while True:
        await asyncio.sleep(60)
        now = time.time()
        for jid, j in list(jobs.items()):
            stuck, age, _timeout = _job_stuck_state(j, now=now)
            if not stuck:
                continue
            _finalize_stuck_job(jid, j, now=now)
            print(f"[stuck-watcher] Killed stuck job {jid[-12:]} (idle {age:.0f}s)")
            add_log("warn", "stuck", f"Killed job idle {age:.0f}s", jid)
            inst_name = j.get("instance", "")
            if inst_name:
                for inst in _get_enabled_instances():
                    if inst["name"] == inst_name:
                        node = _get_node_by_id(inst.get("_node_id", ""))
                        if node:
                            _managed_instance_action(node, inst, "stop", reason="stuck-job")
                        break
            save_jobs()
            asyncio.ensure_future(broadcast({"type": "job_update", "job": j}))


async def _gpu_stall_watcher():
    """Restart jobs whose current stage has no GPU or VRAM activity for a minute."""
    while True:
        await asyncio.sleep(GPU_STALL_SAMPLE_INTERVAL)
        now = time.time()
        instances = {inst.get("name"): inst for inst in _get_generation_instances()}
        gpu_by_node: dict[str, dict] = {}
        monitored = False
        for job_id, job in list(jobs.items()):
            if job.get("status") not in GPU_STALL_JOB_STATUSES:
                _job_gpu_activity_watch.pop(job_id, None)
                continue
            inst = instances.get(job.get("instance"))
            if not inst:
                _job_gpu_activity_watch.pop(job_id, None)
                continue
            node_id = inst.get("_node_id", "")
            if node_id not in gpu_by_node:
                gpu_by_node[node_id] = await asyncio.to_thread(get_node_gpu_stats, _get_node_by_id(node_id))
            monitored = True
            if not _job_gpu_activity_stalled(job_id, job, gpu_by_node.get(node_id), now=now):
                continue
            await _restart_gpu_stalled_job(job_id, job, inst, now=now)
        if monitored:
            save_jobs()


async def _remote_prompt_adoption_watcher():
    """Periodically recover remote prompts that survived a local restart."""
    while True:
        await asyncio.sleep(8)
        for inst in _get_generation_instances():
            try:
                remote_queue = _get_instance_queue_counts(inst.get("url", ""))
                _adopt_untracked_remote_prompts(inst, remote_queue)
            except Exception as e:
                add_log("warn", "queue", f"远端任务找回检查失败: {inst.get('name', '')}", details=str(e)[:200])



@asynccontextmanager
async def lifespan(app: FastAPI):
    global _inst_mgr, _job_runner, _app_loop
    _app_loop = asyncio.get_running_loop()
    _load_recent_logs()
    _load_cancelled_remote_prompts()
    load_jobs()
    load_history()
    os.makedirs(HISTORY_DIR, exist_ok=True)
    _load_system_settings()
    _init_gen_db()
    os.makedirs(WORKFLOW_DIR, exist_ok=True)
    _refresh_instance_state()
    _inst_mgr = InstanceManager(_get_generation_instances)
    _inst_mgr._get_node_by_id = _get_node_by_id
    _inst_mgr._run_instance_action = _run_instance_action
    _inst_mgr._has_active_jobs = _has_active_instance_job
    _inst_mgr._last_active = _instance_last_active
    _inst_mgr._start_grace = _instance_start_grace
    _inst_mgr._idle_timeout_provider = _idle_timeout_for_instance
    _inst_mgr._service_active_checker = _managed_service_active
    _job_runner = JobRunner(
        inst_mgr=_inst_mgr,
        jobs=jobs,
        history=history,
        broadcast_fn=broadcast,
        add_log_fn=add_log,
        save_jobs_fn=save_jobs,
        save_history_fn=save_history,
        make_thumbnail_fn=make_thumbnail,
        get_image_size_fn=get_image_size,
        comfyui_up_fn=comfyui_up,
        comfyui_get_fn=comfyui_get,
        download_images_fn=_download_remote_images_sync,
        vllm_running_fn=vllm_running,
        stop_vllm_fn=stop_vllm,
        start_vllm_fn=start_vllm,
        get_node_by_id_fn=_get_node_by_id,
        run_instance_action_fn=_managed_instance_action,
        instance_semas=_instance_semas,
        instance_group=_instance_group,
        instance_last_active=_instance_last_active,
        output_dir=OUTPUT_DIR,
        history_dir=HISTORY_DIR,
        get_enabled_instances_fn=_get_generation_instances,
        insert_gen_fn=_insert_generation,
        protection_check_fn=_schedule_image_protection,
        input_dir=COMFYUI_INPUT,
    )
    # Start a single generation dispatcher so A/B never generate at the same time.
    _background_tasks.extend(_start_queue_workers())
    _inst_mgr.start_background_tasks()
    _background_tasks.append(asyncio.create_task(_stuck_job_watcher()))
    _background_tasks.append(asyncio.create_task(_gpu_stall_watcher()))
    _background_tasks.append(asyncio.create_task(_remote_prompt_adoption_watcher()))
    _resume_pending_image_protection_checks()
    _resume_persisted_generation_jobs()
    try:
        yield
    finally:
        save_jobs()
        for task in list(_background_tasks):
            try:
                task.cancel()
            except Exception:
                pass
        if _background_tasks:
            try:
                await asyncio.wait(_background_tasks, timeout=5)
            except Exception:
                pass
        _background_tasks.clear()
        if _inst_mgr:
            stop_loops = getattr(_inst_mgr, "stop_background_loops", None)
            if callable(stop_loops):
                try:
                    stop_loops()
                except Exception:
                    pass

app = FastAPI(title="Ez ComfyUI Showcase", version=APP_VERSION, lifespan=lifespan)


@app.middleware("http")
async def _csrf_cookie_guard(request: Request, call_next):
    if request.method.upper() not in _UNSAFE_HTTP_METHODS:
        return await call_next(request)
    path = request.url.path
    if path in ("/auth/login", "/auth/register"):
        return await call_next(request)
    if not (path.startswith("/api/") or path.startswith("/auth/")):
        return await call_next(request)
    if not request.cookies.get(AUTH_COOKIE_NAME):
        return await call_next(request)
    if not _csrf_token_valid(request):
        return JSONResponse({"detail": "CSRF token missing or invalid"}, status_code=403)
    return await call_next(request)


@app.post("/api/nodes/{nid}/connect")
def _api_node_connect(nid: str, current_user: dict = Depends(require_admin)):
    _connected_nodes[nid] = True
    return {"ok": True}

@app.post("/api/nodes/{nid}/disconnect")
def _api_node_disconnect(nid: str, current_user: dict = Depends(require_admin)):
    _connected_nodes[nid] = False
    return {"ok": True}

def _can_view_log_entry(entry: dict, current_user: dict) -> bool:
    if _is_admin_user(current_user):
        return True
    entry_user_id = str(entry.get("user_id") or "")
    if entry_user_id and entry_user_id == str(current_user.get("id") or ""):
        return True
    log_job_suffix = str(entry.get("job_id") or "")
    if not log_job_suffix:
        return False
    for jid, job in jobs.items():
        if str(jid).endswith(log_job_suffix) and _can_access_job(job, current_user):
            return True
    return False


@app.get("/api/logs")
def api_logs(limit: int = _MAX_LOG, current_user: dict = Depends(get_current_user)):
    _trim_log_buffer()
    _persist_log_buffer()
    safe_limit = max(1, min(int(limit or _MAX_LOG), _MAX_LOG))
    visible = [entry for entry in _log_buffer if _can_view_log_entry(entry, current_user)]
    return list(visible[-safe_limit:])
static_dir = Path(__file__).parent / "static"
if static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# ══════════════════════════════════════════════════════════════════════════
#  GPU / Service helpers
# ══════════════════════════════════════════════════════════════════════════

_NVIDIA_NA_VALUES = {"[N/A]", "[N/A ]", "N/A", ""}


def _gpu_float(value: str | int | float | None) -> float:
    text = str(value if value is not None else "").strip()
    if text in _NVIDIA_NA_VALUES:
        return 0.0
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def _parse_gpu_process_memory_used(out: str) -> int:
    total = 0
    for line in (out or "").strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        used = _gpu_float(parts[1])
        if used > 0:
            total += int(round(used))
    return total


def _query_local_gpu_process_memory_used() -> int:
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,used_memory,name,process_name",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
        )
        return _parse_gpu_process_memory_used(out)
    except Exception:
        return 0


def get_gpu_stats() -> dict:
    """Return GPU memory/util/temp.  GB10 unified memory → /proc/meminfo.  Cached 3 s."""
    now = time.time()
    if gpu_cache["data"] and now - gpu_cache["ts"] < 3:
        return gpu_cache["data"]

    temp, util = 0, 0
    mem_used_mb, mem_total_mb = 0, 1
    system_used_mb, system_total_mb = 0, 0
    source = ""

    # nvidia-smi for temp + util
    try:
        out = subprocess.check_output(
            ["nvidia-smi",
             "--query-gpu=memory.used,memory.total,temperature.gpu,utilization.gpu",
             "--format=csv,noheader,nounits"],
            text=True, timeout=5,
        ).strip()
        parts = [x.strip() for x in out.split(",")]
        raw_used, raw_total = parts[0], parts[1]
        temp = int(_gpu_float(parts[2]))
        util = int(_gpu_float(parts[3]))
        mem_used_mb = _gpu_float(raw_used)
        mem_total_mb = _gpu_float(raw_total) or mem_total_mb
        if mem_total_mb > 1:
            source = "nvidia-smi"
    except Exception:
        pass

    if mem_total_mb <= 1:
        try:
            out = subprocess.check_output(
                ["sh", "-lc", "command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi --query-gpu=memory.used,memory.total,temperature.gpu,utilization.gpu --format=csv,noheader,nounits | head -n 1"],
                text=True, timeout=5,
            ).strip()
            if out:
                parts = [x.strip() for x in out.split(",")]
                raw_used, raw_total = parts[0], parts[1]
                temp = int(_gpu_float(parts[2])) or temp
                util = int(_gpu_float(parts[3])) or util
                mem_used_mb = _gpu_float(raw_used) or mem_used_mb
                mem_total_mb = _gpu_float(raw_total) or mem_total_mb
                if mem_total_mb > 1:
                    source = "nvidia-smi"
        except Exception:
            pass

    if mem_total_mb <= 1:
        process_used_mb = _query_local_gpu_process_memory_used()
        try:
            mi = Path("/proc/meminfo").read_text()
            total_kb = int(re.search(r"MemTotal:\s+(\d+)", mi).group(1))
            avail_kb = int(re.search(r"MemAvailable:\s+(\d+)", mi).group(1))
            system_total_mb = total_kb / 1024
            system_used_mb = (total_kb - avail_kb) / 1024
            mem_total_mb = system_total_mb
            if process_used_mb > 0:
                mem_used_mb = process_used_mb
                source = "process-sum"
            else:
                mem_used_mb = system_used_mb
                source = "meminfo"
        except Exception:
            pass

    if mem_used_mb == 0 and mem_total_mb <= 1:
        try:
            mem_total_mb = float(os.environ.get("EZ_GPU_TOTAL_MB", "0") or 0)
            mem_used_mb = float(os.environ.get("EZ_GPU_USED_MB", "0") or 0)
            temp = temp or int(float(os.environ.get("EZ_GPU_TEMP_C", "0") or 0))
            util = util or int(float(os.environ.get("EZ_GPU_UTIL_PCT", "0") or 0))
            source = "env" if mem_total_mb else source
        except Exception:
            pass

    pct = round(mem_used_mb / mem_total_mb * 100, 1) if mem_total_mb else 0
    data = {
        "vram_used_mb": round(mem_used_mb),
        "vram_total_mb": round(mem_total_mb),
        "vram_pct": pct,
        "temp_c": temp,
        "util_pct": util,
        "memory_source": source,
        "system_used_mb": round(system_used_mb),
        "system_total_mb": round(system_total_mb),
    }
    gpu_cache["ts"] = now
    gpu_cache["data"] = data
    return data


def _empty_gpu_stats(message: str = "", detail: str = "") -> dict:
    return {
        "vram_used_mb": 0,
        "vram_total_mb": 0,
        "vram_pct": 0,
        "temp_c": 0,
        "util_pct": 0,
        "memory_source": "",
        "system_used_mb": 0,
        "system_total_mb": 0,
        "message": message,
        "detail": detail,
    }


def _gpu_stats_has_vram(data: dict | None) -> bool:
    try:
        return float((data or {}).get("vram_total_mb") or 0) > 0
    except (TypeError, ValueError):
        return False


def _node_gpu_cache_record(data: dict, now: float, previous: dict | None = None) -> dict:
    record = {"ts": now, "data": data}
    if _gpu_stats_has_vram(data) and not data.get("stale"):
        record["good_data"] = dict(data)
        record["good_ts"] = now
    elif previous:
        if previous.get("good_data"):
            record["good_data"] = dict(previous["good_data"])
            record["good_ts"] = float(previous.get("good_ts") or previous.get("ts") or now)
        elif _gpu_stats_has_vram(previous.get("data")):
            record["good_data"] = dict(previous["data"])
            record["good_ts"] = float(previous.get("ts") or now)
    return record


def _cached_stale_gpu_stats(cached: dict | None, failed: dict, now: float) -> dict | None:
    if not cached:
        return None
    good = cached.get("good_data")
    good_ts = float(cached.get("good_ts") or 0)
    if not good and _gpu_stats_has_vram(cached.get("data")):
        good = cached.get("data")
        good_ts = float(cached.get("ts") or 0)
    if not good or not _gpu_stats_has_vram(good):
        return None
    age = max(0.0, now - good_ts)
    if age > NODE_GPU_STALE_TTL:
        return None
    data = dict(good)
    data["message"] = "VRAM 使用缓存值"
    data["detail"] = str((failed or {}).get("detail") or (failed or {}).get("message") or "")[:240]
    data["stale"] = True
    data["stale_age_sec"] = int(round(age))
    return data


def _parse_nvidia_smi_stats(out: str) -> dict:
    line = (out or "").strip().splitlines()[0] if (out or "").strip() else ""
    if not line:
        return _empty_gpu_stats("VRAM 未上报")
    parts = [x.strip() for x in line.split(",")]
    if len(parts) < 4:
        return _empty_gpu_stats("VRAM 未上报")
    raw_used, raw_total, raw_temp, raw_util = parts[:4]
    used = _gpu_float(raw_used)
    total = _gpu_float(raw_total)
    temp = int(_gpu_float(raw_temp))
    util = int(_gpu_float(raw_util))
    pct = round(used / total * 100, 1) if total else 0
    return {
        "vram_used_mb": round(used),
        "vram_total_mb": round(total),
        "vram_pct": pct,
        "temp_c": temp,
        "util_pct": util,
        "memory_source": "nvidia-smi" if total else "",
        "system_used_mb": 0,
        "system_total_mb": 0,
        "message": "",
        "detail": "",
    }


def _build_ssh_command(node: dict, remote_args: list[str]) -> list[str]:
    ssh = _resolve_ssh_config(node.get("ssh_config", {}))
    if ssh.get("auth") == "password" and ssh.get("password"):
        cmd = [
            "sshpass", "-p", ssh["password"], "ssh",
            "-p", str(ssh.get("port", 22)),
            f"{ssh.get('user', 'root')}@{node['host']}",
        ]
    else:
        cmd = ["ssh", "-p", str(ssh.get("port", 22)),
               f"{ssh.get('user', 'root')}@{node['host']}"]
    return cmd + remote_args


def _parse_meminfo_stats(out: str, base: dict | None = None, process_used_mb: int = 0) -> dict:
    base = dict(base or _empty_gpu_stats())
    try:
        total = re.search(r"MemTotal:\s+(\d+)", out or "")
        avail = re.search(r"MemAvailable:\s+(\d+)", out or "")
        if not total or not avail:
            return base
        total_mb = int(total.group(1)) / 1024
        system_used_mb = total_mb - (int(avail.group(1)) / 1024)
        used_mb = float(process_used_mb or 0) or system_used_mb
        pct = round(used_mb / total_mb * 100, 1) if total_mb else 0
        base.update({
            "vram_used_mb": round(used_mb),
            "vram_total_mb": round(total_mb),
            "vram_pct": pct,
            "memory_source": "process-sum" if process_used_mb else "meminfo",
            "system_used_mb": round(system_used_mb),
            "system_total_mb": round(total_mb),
            "message": "",
        })
    except Exception:
        pass
    return base


def _run_remote_gpu_query(node: dict) -> dict:
    cmd = _build_ssh_command(node, [
        "nvidia-smi",
        "--query-gpu=memory.used,memory.total,temperature.gpu,utilization.gpu",
        "--format=csv,noheader,nounits",
    ])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
    if r.returncode != 0:
        return _empty_gpu_stats("VRAM 暂不可用", (r.stderr or "VRAM 未获取到").strip()[:240])
    data = _parse_nvidia_smi_stats(r.stdout)
    if data.get("vram_total_mb", 0) > 0:
        return data
    proc_cmd = _build_ssh_command(node, [
        "nvidia-smi",
        "--query-compute-apps=pid,used_memory,name,process_name",
        "--format=csv,noheader,nounits",
    ])
    proc = subprocess.run(proc_cmd, capture_output=True, text=True, timeout=8)
    process_used_mb = _parse_gpu_process_memory_used(proc.stdout) if proc.returncode == 0 else 0
    mem_cmd = _build_ssh_command(node, ["cat", "/proc/meminfo"])
    mem = subprocess.run(mem_cmd, capture_output=True, text=True, timeout=8)
    if mem.returncode == 0:
        return _parse_meminfo_stats(mem.stdout, data, process_used_mb=process_used_mb)
    data["message"] = data.get("message") or "VRAM 暂不可用"
    data["detail"] = (mem.stderr or data.get("detail") or "VRAM 未获取到").strip()[:240]
    return data


def get_node_gpu_stats(node: dict | None) -> dict:
    if not node:
        return _empty_gpu_stats("设备不存在")
    conn = node.get("connection", "local")
    if conn == "local":
        data = dict(get_gpu_stats())
        data.setdefault("message", "")
        return data
    if conn != "remote-ssh":
        return _empty_gpu_stats("该设备暂不支持 VRAM 查询")

    now = time.time()
    key = node.get("id") or node.get("host") or ""
    cached = node_gpu_cache.get(key)
    if cached and now - cached.get("ts", 0) < NODE_GPU_CACHE_TTL:
        return cached["data"]
    try:
        data = _run_remote_gpu_query(node)
    except Exception as e:
        data = _empty_gpu_stats("VRAM 暂不可用", str(e)[:240])
    if not _gpu_stats_has_vram(data):
        stale = _cached_stale_gpu_stats(cached, data, now)
        if stale:
            node_gpu_cache[key] = _node_gpu_cache_record(stale, now, cached)
            return stale
    node_gpu_cache[key] = _node_gpu_cache_record(data, now, cached)
    return data


def _select_status_node_id(instances: list[dict], target_node_id: str = "", target_instance: str = "") -> str:
    visible_node_ids = {inst.get("_node_id", "") for inst in instances}
    if target_node_id and target_node_id in visible_node_ids:
        return target_node_id
    if target_instance:
        for inst in instances:
            if inst.get("name") == target_instance:
                return inst.get("_node_id", "")
    return instances[0].get("_node_id", "") if instances else ""


def _gpu_stats_for_status_node(instances: list[dict], target_node_id: str = "", target_instance: str = "") -> dict[str, dict]:
    node_id = _select_status_node_id(instances, target_node_id, target_instance)
    if not node_id:
        return {}
    return {node_id: get_node_gpu_stats(_get_node_by_id(node_id))}


def comfyui_up(base_url: str = None) -> bool:
    try:
        with urllib.request.urlopen(f"{(base_url or COMFYUI_URL)}/system_stats", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def comfyui_pid() -> int | None:
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", r"ComfyUI/main\.py"], text=True, timeout=3
        ).strip()
        return int(out.split()[0]) if out else None
    except Exception:
        return None


def start_comfyui():
    script = f"""
cd {COMFYUI_DIR}
export LD_LIBRARY_PATH="{COMFYUI_DIR}/venv/lib/python3.12/site-packages/torch/lib"
export PYTHONWARNINGS="ignore" CM_SKIP_UPDATE=True USE_CUDNN=0
export TORCH_CUDNN_V8_API_ENABLED=0 TORCH_CUDNN_V9_API_ENABLED=0
export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True" CUDA_MODULE_LOADING=LAZY
nohup {COMFYUI_DIR}/venv/bin/python3 {COMFYUI_DIR}/ComfyUI/main.py \\
    --listen 0.0.0.0 --port 8190 --preview-method none \\
    --use-pytorch-cross-attention --lowvram --disable-smart-memory \\
    --output-directory {OUTPUT_DIR} > /tmp/comfyui.log 2>&1 &
"""
    subprocess.run(["bash", "-c", script], capture_output=True, timeout=5)


def stop_comfyui():
    pid = comfyui_pid()
    if pid:
        try:
            os.kill(pid, 15)  # SIGTERM
        except ProcessLookupError:
            pass


def _legacy_vllm_management_enabled() -> bool:
    return str(os.environ.get(LEGACY_VLLM_MANAGEMENT_ENV, "")).strip().lower() in {"1", "true", "yes", "on"}


def vllm_running() -> bool:
    if not _legacy_vllm_management_enabled():
        return False
    try:
        out = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", VLLM_CONTAINER],
            capture_output=True, text=True, timeout=5,
        )
        return "true" in out.stdout.lower()
    except Exception:
        return False


def stop_vllm():
    if not _legacy_vllm_management_enabled():
        return False
    subprocess.run(["docker", "stop", VLLM_CONTAINER], capture_output=True, timeout=60)
    return True


def start_vllm():
    if not _legacy_vllm_management_enabled():
        return False
    subprocess.Popen(["docker", "start", VLLM_CONTAINER],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def comfyui_post(path: str, data: dict, base_url: str = None) -> dict:
    url = (base_url or COMFYUI_URL) + path
    payload = json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
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


def comfyui_get(path: str, base_url: str = None) -> dict:
    url = (base_url or COMFYUI_URL) + path
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _is_image_output_file(filename: str) -> bool:
    return is_image_output(filename)


def _download_remote_images_sync(job_id: str, prompt_id: str, base_url: str, output_dir: str) -> list:
    """Download preferred output media from remote ComfyUI after generation.
    Returns list of local file paths that were downloaded."""
    try:
        history = comfyui_get(f"/history/{prompt_id}", base_url=base_url)
        if not history or prompt_id not in history:
            print(f"[download] No history entry for {prompt_id}")
            return []
        outputs = history[prompt_id].get("outputs", {})
        media = collect_preferred_outputs(outputs)
        if not media:
            print(f"[download] No output media in history for {prompt_id}")
            return []
        downloaded = []
        for ref in media:
            filename = ref["filename"]
            subfolder = ref.get("subfolder", "")
            media_type = ref.get("type", "output")
            rel_path = output_ref_rel_path(ref)
            local_path = os.path.join(output_dir, rel_path)
            # Skip if already exists locally
            if os.path.isfile(local_path):
                downloaded.append(local_path)
                continue
            query = urllib.parse.urlencode({
                "filename": filename,
                "subfolder": subfolder,
                "type": media_type,
            })
            view_url = f"{base_url}/view?{query}"
            try:
                with urllib.request.urlopen(view_url, timeout=120) as resp:
                    if resp.status == 200:
                        os.makedirs(os.path.dirname(local_path), exist_ok=True)
                        with open(local_path, "wb") as f:
                            f.write(resp.read())
                        downloaded.append(local_path)
                        print(f"[download] Saved {rel_path} ({len(downloaded)}/{len(media)})")
            except Exception as e:
                print(f"[download] Failed to download {filename}: {e}")
        return downloaded
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[download] Error for {job_id}: {e}")
        return []


# ── Multi-instance routing ──────────────────────────────────────────────
def _queue_prompt_id(item) -> str:
    if isinstance(item, list) and len(item) > 1:
        return str(item[1] or "")
    if isinstance(item, dict):
        return str(item.get("prompt_id") or item.get("id") or "")
    return ""


def _queue_prompt_client_id(item) -> str:
    candidates: list[dict] = []
    if isinstance(item, list):
        for idx in (3, 4):
            if len(item) > idx and isinstance(item[idx], dict):
                candidates.append(item[idx])
    elif isinstance(item, dict):
        candidates.append(item)
        for key in ("extra_data", "metadata", "extra"):
            meta = item.get(key)
            if isinstance(meta, dict):
                candidates.append(meta)
    for meta in candidates:
        client_id = str(meta.get("client_id") or meta.get("clientId") or "").strip()
        if client_id:
            return client_id
    return ""


def _get_instance_queue_counts(base_url: str) -> dict:
    """Return remote ComfyUI queue counts for one instance."""
    try:
        q = comfyui_get("/queue", base_url=base_url)
        running_items = q.get("queue_running", []) or []
        pending_items = q.get("queue_pending", []) or []
        running = len(running_items)
        pending = len(pending_items)
        return {
            "running": running,
            "pending": pending,
            "total": running + pending,
            "running_prompt_ids": [pid for pid in (_queue_prompt_id(item) for item in running_items) if pid],
            "pending_prompt_ids": [pid for pid in (_queue_prompt_id(item) for item in pending_items) if pid],
        }
    except Exception:
        return {"running": 0, "pending": 0, "total": 999, "running_prompt_ids": [], "pending_prompt_ids": []}


def _get_instance_queue_size(base_url: str) -> int:
    """Return number of pending + running jobs on a ComfyUI instance."""
    return _get_instance_queue_counts(base_url)["total"]


_untracked_remote_cleanup_at: dict[str, float] = {}
_cancelled_remote_prompts: dict[str, float] = {}


def _remote_prompt_key(instance_name: str, prompt_id: str) -> str:
    return f"{str(instance_name or '').strip()}:{str(prompt_id or '').strip()}"


def _prune_cancelled_remote_prompts(now: float | None = None) -> None:
    now = now or time.time()
    cutoff = now - 24 * 3600
    for key, ts in list(_cancelled_remote_prompts.items()):
        try:
            if float(ts or 0) < cutoff:
                _cancelled_remote_prompts.pop(key, None)
        except Exception:
            _cancelled_remote_prompts.pop(key, None)


def _save_cancelled_remote_prompts() -> None:
    try:
        _prune_cancelled_remote_prompts()
        os.makedirs(os.path.dirname(CANCELLED_PROMPTS_FILE), exist_ok=True)
        tmp_file = f"{CANCELLED_PROMPTS_FILE}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(_cancelled_remote_prompts, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, CANCELLED_PROMPTS_FILE)
    except Exception:
        pass


def _load_cancelled_remote_prompts() -> None:
    _cancelled_remote_prompts.clear()
    if not os.path.isfile(CANCELLED_PROMPTS_FILE):
        return
    try:
        with open(CANCELLED_PROMPTS_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            _cancelled_remote_prompts.update({str(k): float(v or 0) for k, v in raw.items()})
        _prune_cancelled_remote_prompts()
    except Exception:
        _cancelled_remote_prompts.clear()


def _mark_remote_prompt_cancelled(instance_name: str, prompt_id: str) -> None:
    if not prompt_id:
        return
    _cancelled_remote_prompts[_remote_prompt_key(instance_name, prompt_id)] = time.time()
    _save_cancelled_remote_prompts()


def _remote_prompt_was_cancelled(instance_name: str, prompt_id: str) -> bool:
    _prune_cancelled_remote_prompts()
    return _remote_prompt_key(instance_name, prompt_id) in _cancelled_remote_prompts


def _active_prompt_ids_for_instance(instance_name: str) -> set[str]:
    return {
        str(job.get("prompt_id") or "")
        for job in jobs.values()
        if _job_is_active_for_instance(job, instance_name) and job.get("prompt_id")
    }


def _untracked_remote_prompt_ids(instance_name: str, remote_queue: dict) -> list[str]:
    known = _active_prompt_ids_for_instance(instance_name)
    remote_ids = list(remote_queue.get("running_prompt_ids") or []) + list(remote_queue.get("pending_prompt_ids") or [])
    return [
        pid for pid in remote_ids
        if pid and pid not in known and not _remote_prompt_was_cancelled(instance_name, pid)
    ]


def _submit_log_entry_for_prompt_id(prompt_id: str) -> dict | None:
    tail = str(prompt_id or "")[-12:]
    if not tail:
        return None
    for entry in reversed(_log_buffer):
        msg = str(entry.get("msg") or "")
        if not msg.startswith("任务已提交:"):
            continue
        submitted_tail = msg[len("任务已提交:"):].strip()
        if submitted_tail and (str(prompt_id).endswith(submitted_tail) or submitted_tail.endswith(tail)):
            return entry
    return None


def _remote_queue_prompt_graph(inst: dict, prompt_id: str) -> dict:
    try:
        queue = comfyui_get("/queue", base_url=inst.get("url", ""))
    except Exception:
        return {}
    for section in ("queue_running", "queue_pending"):
        for item in queue.get(section, []) or []:
            if _queue_prompt_id(item) != prompt_id:
                continue
            if isinstance(item, list) and len(item) > 2 and isinstance(item[2], dict):
                return item[2]
            if isinstance(item, dict):
                prompt = item.get("prompt") or item.get("workflow")
                if isinstance(prompt, dict):
                    return prompt
    return {}


def _remote_queue_prompt_client_id(inst: dict, prompt_id: str) -> str:
    try:
        queue = comfyui_get("/queue", base_url=inst.get("url", ""))
    except Exception:
        return ""
    for section in ("queue_running", "queue_pending"):
        for item in queue.get(section, []) or []:
            if _queue_prompt_id(item) == prompt_id:
                return _queue_prompt_client_id(item)
    return ""


def _remote_graph_field_values(graph: dict) -> dict:
    fields: dict[str, str] = {}
    for node_id, node in graph.items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") or {}
        if not isinstance(inputs, dict):
            continue
        for field in ("text", "value", "image"):
            value = inputs.get(field)
            if isinstance(value, str) and value.strip():
                fields[f"{node_id}::{field}"] = value
    return fields


def _remote_graph_prompt_preview(graph: dict) -> str:
    preferred: list[str] = []
    fallback: list[str] = []
    for node in graph.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") or {}
        if not isinstance(inputs, dict):
            continue
        title = str((node.get("_meta") or {}).get("title") or "").lower()
        class_type = str(node.get("class_type") or "")
        value = inputs.get("value")
        text = inputs.get("text")
        candidate = value if isinstance(value, str) and value.strip() else text
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        if "negative" in title or "负" in title:
            continue
        if class_type == "PrimitiveStringMultiline" or "prompt" in title:
            preferred.append(candidate.strip())
        else:
            fallback.append(candidate.strip())
    text = (preferred or fallback or [""])[0]
    return text[:200]


def _workflow_graph_for_resume(path: str, job: dict) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            graph = json.load(f)
    except Exception:
        return {}
    fields = job.get("fields") or {}
    if isinstance(graph, dict) and isinstance(fields, dict):
        for key, val in fields.items():
            if "::" not in str(key):
                continue
            nid, field = str(key).split("::", 1)
            if nid in graph and isinstance(graph[nid], dict):
                inputs = graph[nid].setdefault("inputs", {})
                if isinstance(inputs, dict):
                    inputs[field] = val
    try:
        seed = _job_seed_value(job)
        for node in graph.values():
            if isinstance(node, dict) and node.get("class_type") == "KSampler":
                inputs = node.get("inputs") or {}
                if isinstance(inputs, dict) and "seed" in inputs:
                    inputs["seed"] = seed
    except Exception:
        pass
    return graph if isinstance(graph, dict) else {}


def _start_resume_ws_progress(job_id: str, inst: dict, graph: dict, prompt_id: str, client_id: str, timeout: int):
    if not graph or not prompt_id or not client_id:
        return None
    try:
        step_info = StepCalculator().calculate(graph)
    except Exception:
        return None
    node_types = {
        str(nid): str(node.get("class_type") or "")
        for nid, node in graph.items()
        if isinstance(node, dict) and node.get("class_type")
    }

    async def _progress_callback(progress: dict) -> None:
        job = jobs.get(job_id)
        if not job or job.get("status") not in ACTIVE_JOB_STATUSES:
            return
        pct = int(progress.get("pct", 0) or 0)
        msg = str(progress.get("message") or "").strip()
        progress_state = {"pct": pct}
        for key in ("current_node", "sampler_cur", "sampler_total"):
            if key in progress:
                progress_state[key] = progress.get(key)
        if msg:
            job["message"] = msg
        job["progress"] = progress_state
        job["last_update"] = time.time()
        job["resume_ws_active"] = True
        save_jobs()
        await broadcast({"type": "job_update", "job": job})

    tracker = WSTracker(
        job_id=job_id,
        workflow=graph,
        step_info=step_info,
        instance_url=inst.get("url", ""),
        node_types=node_types,
        progress_callback=_progress_callback,
        log_callback=add_log,
        client_id=client_id,
    )
    tracker.WS_SILENT_TIMEOUT = min(tracker.WS_SILENT_TIMEOUT, 45.0)

    async def _run_resume_ws():
        try:
            result = await tracker.resume(prompt_id, timeout=timeout)
            if result.ok:
                add_log("info", "queue", "重启恢复 WS 已收到完成事件", job_id, details=prompt_id)
        except Exception as e:
            job = jobs.get(job_id)
            if job:
                job["resume_ws_error"] = str(e)[:200]
                save_jobs()
            add_log("warn", "queue", f"重启恢复 WS 追踪失败: {e}", job_id, details=prompt_id)

    return asyncio.create_task(_run_resume_ws())


def _schedule_resume_tracker(job_id: str) -> bool:
    if not _job_runner or job_id in _job_tasks:
        return False
    coro = _resume_persisted_generation_job(job_id)
    try:
        task = asyncio.create_task(coro)
        _job_tasks[job_id] = task
        return True
    except RuntimeError:
        loop = _app_loop
        if loop and loop.is_running():
            _job_tasks[job_id] = asyncio.run_coroutine_threadsafe(coro, loop)
            return True
        coro.close()
        return False


def _adopt_untracked_remote_prompts(inst: dict, remote_queue: dict) -> list[str]:
    adopted: list[str] = []
    inst_name = str(inst.get("name") or "")
    for prompt_id in _untracked_remote_prompt_ids(inst_name, remote_queue):
        entry = _submit_log_entry_for_prompt_id(prompt_id)
        if not entry:
            continue
        workflow = str(entry.get("workflow") or "")
        if not workflow or not _resolve_workflow(workflow):
            continue
        graph = _remote_queue_prompt_graph(inst, prompt_id)
        client_id = _remote_queue_prompt_client_id(inst, prompt_id)
        field_values = _remote_graph_field_values(graph) if graph else {}
        suffix = str(entry.get("job_id") or "").strip()
        job_id = next((jid for jid in jobs if suffix and str(jid).endswith(suffix)), "")
        if not job_id:
            job_id = f"job_recovered_{suffix or str(prompt_id)[-12:]}"
        if job_id not in jobs:
            created_at = float(entry.get("ts") or time.time())
            workflow_type = str(entry.get("workflow_type") or _workflow_primary_type(workflow))
            jobs[job_id] = {
                "id": job_id,
                "status": "generating",
                "message": "已从远端队列找回，恢复追踪中...",
                "workflow": workflow,
                "workflow_type": workflow_type,
                "prompt_preview": _remote_graph_prompt_preview(graph) or infer_generation_label(workflow, field_values, workflow_type)[:200],
                "prompt_id": prompt_id,
                "client_id": client_id,
                "instance": inst_name,
                "target_node_id": inst.get("_node_id", ""),
                "target_url": inst.get("url", ""),
                "fields": field_values,
                "seed": "0",
                "width": 0,
                "height": 0,
                "created_at_ts": created_at,
                "submitted_at": created_at,
                "generating_at": created_at,
                "last_update": time.time(),
                "user_id": str(entry.get("user_id") or ""),
                "recovered_from_remote": True,
                "progress": {"pct": 0},
            }
            adopted.append(prompt_id)
            add_log("info", "queue", "已找回未追踪远端任务，恢复追踪", job_id, details=prompt_id)
        else:
            jobs[job_id]["prompt_id"] = prompt_id
            if client_id:
                jobs[job_id]["client_id"] = client_id
            jobs[job_id]["instance"] = inst_name
            jobs[job_id]["target_url"] = inst.get("url", "")
            jobs[job_id]["status"] = "generating"
            jobs[job_id]["message"] = "已从远端队列找回，恢复追踪中..."
            jobs[job_id]["last_update"] = time.time()
            if field_values and not jobs[job_id].get("fields"):
                jobs[job_id]["fields"] = field_values
            preview = _remote_graph_prompt_preview(graph)
            if preview and not jobs[job_id].get("prompt_preview"):
                jobs[job_id]["prompt_preview"] = preview
            adopted.append(prompt_id)
        _schedule_resume_tracker(job_id)
    if adopted:
        save_jobs()
    return adopted


def _cleanup_untracked_remote_prompts(inst: dict, remote_queue: dict) -> list[str]:
    """Report untracked remote ComfyUI prompts without interrupting them."""
    _adopt_untracked_remote_prompts(inst, remote_queue)
    prompt_ids = _untracked_remote_prompt_ids(inst.get("name", ""), remote_queue)
    if not prompt_ids:
        return []
    key = f"{inst.get('name', '')}:{','.join(prompt_ids)}"
    now = time.time()
    if now - _untracked_remote_cleanup_at.get(key, 0) < 60:
        return prompt_ids
    _untracked_remote_cleanup_at[key] = now
    add_log(
        "warn",
        "queue",
        f"发现未追踪远端任务，已保留: {inst.get('name', '')}",
        details=",".join(prompt_ids),
    )
    return prompt_ids


async def pick_best_instance(workflow_name: str = "") -> dict:
    """Pick the best ComfyUI instance using workflow affinity + queue depth."""
    instances = _get_enabled_instances()
    if not instances:
        raise RuntimeError("No enabled instances available")
    return await mod_picker.pick_best_instance(
        instances=instances,
        workflow_name=workflow_name,
        affinity_getter=lambda wf: (pick_affinity_instance(wf) or {}).get("name", ""),
        health_check=lambda _inst: True,
        queue_size_getter=lambda inst: _get_instance_queue_size(inst["url"]),
        group_getter=lambda name: _instance_group.get(name, ""),
    )


# ══════════════════════════════════════════════════════════════════════════
#  Workflow parsing
# ══════════════════════════════════════════════════════════════════════════

EDITABLE_FIELDS = {
    "CLIPTextEncode": {
        "text": {"type": "textarea", "label": "提示词"},
    },
    "TextEncodeQwenImageEditPlus": {
        "prompt": {"type": "textarea", "label": "提示词"},
    },
    "KSampler": {
        "seed":          {"type": "seed",    "label": "种子"},
        "steps":         {"type": "number",  "label": "步数",   "min": 1, "max": 100},
        "cfg":           {"type": "number",  "label": "CFG",    "min": 0, "max": 30, "step": 0.5},
        "sampler_name":  {"type": "select",  "label": "采样器",
                          "options": ["euler","euler_ancestral","heun","dpm_2","dpm_2_ancestral",
                                      "lms","dpm_fast","dpm_adaptive","dpmpp_2s_ancestral",
                                      "dpmpp_sde","dpmpp_2m","dpmpp_2m_sde","ddim","uni_pc",
                                      "uni_pc_bh2","res_multistep"]},
        "scheduler":     {"type": "select",  "label": "调度器",
                          "options": ["normal","karras","exponential","sgm_uniform",
                                      "simple","ddim_uniform","beta"]},
        "denoise":       {"type": "number",  "label": "降噪",   "min": 0, "max": 1, "step": 0.05},
    },
    "EmptySD3LatentImage": {
        "width":  {"type": "number", "label": "宽度",  "min": 256, "max": 4096, "step": 64},
        "height": {"type": "number", "label": "高度",  "min": 256, "max": 4096, "step": 64},
    },
    "EmptyLatentImage": {
        "width":  {"type": "number", "label": "宽度",  "min": 256, "max": 4096, "step": 64},
        "height": {"type": "number", "label": "高度",  "min": 256, "max": 4096, "step": 64},
    },
    "SaveImage": {
        "filename_prefix": {"type": "text", "label": "文件名前缀"},
    },
    "LoadImage": {
        "image": {"type": "image", "label": "参考图片"},
    },
    "LoadVideo": {
        "file": {"type": "video", "label": "参考视频"},
    },
    "SeedVR2VideoUpscaler": {
        "seed":       {"type": "seed",   "label": "超分种子", "min": 0, "max": 4294967295},
        "resolution": {"type": "number", "label": "超分分辨率", "min": 512, "max": 8192, "step": 64},
    },
    "QwenMultiangleCameraNode": {
        "horizontal_angle": {"type": "number", "label": "水平角度", "min": 0, "max": 360, "step": 1},
        "vertical_angle":   {"type": "number", "label": "俯仰角度", "min": -30, "max": 60, "step": 1},
        "zoom":             {"type": "number", "label": "镜头距离", "min": 0, "max": 10, "step": 0.1},
        "default_prompts":  {"type": "toggle", "label": "默认角度词"},
        "camera_view":      {"type": "toggle", "label": "相机视角"},
    },
}


def _looks_like_seed_field(ct: str, title: str, field: str) -> bool:
    field_l = str(field or "").lower()
    title_l = str(title or "").lower().replace("_", " ")
    ct_l = str(ct or "").lower()
    if field_l in ("seed", "noise_seed"):
        return True
    if field_l != "value":
        return False
    return "seed" in title_l or "seed" in ct_l


def _seed_limits_for_field(class_type: str, field: str) -> tuple[int, int] | None:
    if class_type == "SeedVR2VideoUpscaler" and field == "seed":
        return (0, 4294967295)
    return None


def _normalize_seed_value_for_field(class_type: str, field: str, value):
    limits = _seed_limits_for_field(class_type, field)
    if not limits:
        return value
    try:
        seed = int(value)
    except (TypeError, ValueError):
        return value
    mn, mx = limits
    if seed < mn:
        return mn
    if seed > mx:
        span = mx - mn + 1
        return mn + ((seed - mn) % span)
    return seed


def _apply_generated_seed_to_seed_fields(wf: dict, field_values: dict, seed: int) -> None:
    try:
        seed_value = int(seed)
    except (TypeError, ValueError):
        return
    for nid, node in (wf or {}).items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        ct = str(node.get("class_type") or "")
        title = str((node.get("_meta") or {}).get("title") or "")
        for field in list(inputs.keys()):
            if not _looks_like_seed_field(ct, title, str(field)):
                continue
            value = _normalize_seed_value_for_field(ct, str(field), seed_value)
            inputs[field] = value
            field_values[f"{nid}::{field}"] = value


def _first_latent_dimension_value(wf: dict, field_values: dict, dimension: str):
    for key, value in (field_values or {}).items():
        if "::" not in str(key):
            continue
        nid, field = str(key).split("::", 1)
        if field != dimension:
            continue
        node = wf.get(nid, {})
        if not isinstance(node, dict):
            continue
        if "LatentImage" in str(node.get("class_type") or ""):
            return value
    return None


def _sync_flux2_scheduler_dimensions(wf: dict, field_values: dict) -> None:
    width = _first_latent_dimension_value(wf, field_values, "width")
    height = _first_latent_dimension_value(wf, field_values, "height")
    if width is None and height is None:
        return
    for nid, node in (wf or {}).items():
        if not isinstance(node, dict) or node.get("class_type") != "Flux2Scheduler":
            continue
        inputs = node.get("inputs") or {}
        if width is not None and "width" in inputs:
            field_values.setdefault(f"{nid}::width", width)
        if height is not None and "height" in inputs:
            field_values.setdefault(f"{nid}::height", height)


def _sync_ltx_video_timing(wf: dict, field_values: dict) -> None:
    """Keep LTX video/audio timing nodes aligned when the card edits length/FPS."""
    length = None
    fps = None
    width = None
    audio_fps_node_id = None
    for nid, node in (wf or {}).items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") or {}
        ct = str(node.get("class_type") or "")
        if ct == "EmptyLTXVLatentVideo":
            length = field_values.get(f"{nid}::length", inputs.get("length", length))
            width = field_values.get(f"{nid}::width", inputs.get("width", width))
        elif ct == "LTXVConditioning" and fps is None:
            candidate = field_values.get(f"{nid}::frame_rate")
            if candidate is None:
                candidate = _resolve_link(wf, inputs.get("frame_rate", fps))
            if not isinstance(candidate, list):
                fps = candidate
        elif ct == "PrimitiveFloat" and str(node.get("_meta", {}).get("title") or "").lower() == "fps":
            fps = field_values.get(f"{nid}::value", inputs.get("value", fps))
        elif ct == "PrimitiveInt" and str(node.get("_meta", {}).get("title") or "").lower() == "audio fps":
            audio_fps_node_id = str(nid)
    if length is None and fps is None and width is None:
        return
    for nid, node in (wf or {}).items():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs") or {}
        ct = str(node.get("class_type") or "")
        if length is not None and ct == "LTXVEmptyLatentAudio" and "frames_number" in inputs:
            field_values[f"{nid}::frames_number"] = length
        if fps is not None and ct == "LTXVEmptyLatentAudio" and "frame_rate" in inputs:
            try:
                audio_fps = int(round(float(fps)))
            except Exception:
                audio_fps = fps
            field_values[f"{nid}::frame_rate"] = [audio_fps_node_id, 0] if audio_fps_node_id else audio_fps
        if fps is not None and ct == "CreateVideo" and "fps" in inputs:
            field_values[f"{nid}::fps"] = fps
        if fps is not None and ct == "PrimitiveInt" and str(node.get("_meta", {}).get("title") or "").lower() == "audio fps":
            try:
                field_values[f"{nid}::value"] = int(round(float(fps)))
            except Exception:
                field_values[f"{nid}::value"] = fps
        if length is not None and ct == "VAEDecodeTiled" and "temporal_size" in inputs:
            field_values[f"{nid}::temporal_size"] = length
        if width is not None and ct == "VAEDecodeTiled" and "tile_size" in inputs:
            try:
                field_values[f"{nid}::tile_size"] = max(64, min(512, int(float(width))))
            except Exception:
                pass


def _ltx_director_default_segment_prompt(global_prompt: str, index: int, total: int) -> str:
    if index < max(0, total - 1):
        transition = (
            "Smooth cinematic transition from this reference image to the next reference image, "
            "preserve subject identity, scene continuity, lighting continuity, camera motion continuity, no abrupt cut."
        )
    elif index > 0:
        transition = (
            "Continue from the previous reference image into this final reference image with subtle natural motion, "
            "stable composition, consistent lighting, no abrupt cut."
        )
    else:
        transition = (
            "Animate this reference image with subtle natural motion, stable composition, "
            "consistent lighting, no abrupt cut."
        )
    prompt = str(global_prompt or "").strip()
    return f"{prompt}\n{transition}" if prompt else transition


def _ltx_director_link_value(wf: dict, field_values: dict, value, depth: int = 0):
    if depth > 8 or not isinstance(value, list) or len(value) < 2:
        return value
    node_id = str(value[0])
    node = wf.get(node_id, {})
    if not isinstance(node, dict):
        return value
    inputs = node.get("inputs") or {}
    class_type = str(node.get("class_type") or "")
    if class_type in ("PrimitiveInt", "PrimitiveFloat"):
        return field_values.get(f"{node_id}::value", inputs.get("value", value))
    if class_type == "ComfyMathExpression":
        variables = {}
        for key, raw in inputs.items():
            if not str(key).startswith("values."):
                continue
            name = str(key).split(".", 1)[1]
            resolved = _ltx_director_link_value(wf, field_values, raw, depth + 1)
            try:
                variables[name] = float(resolved)
            except (TypeError, ValueError):
                return value
        expression = str(inputs.get("expression") or "")
        if not re.fullmatch(r"[A-Za-z0-9_+\-*/(). ]+", expression):
            return value
        try:
            return eval(expression, {"__builtins__": {}}, variables)
        except Exception:
            return value
    return value


def _ltx_director_expected_frames(wf: dict, node: dict, field_values: dict) -> int:
    inputs = node.get("inputs") or {}
    frames = _ltx_director_link_value(wf, field_values, inputs.get("duration_frames"))
    try:
        frames_i = int(round(float(frames)))
        if frames_i > 0:
            return frames_i
    except (TypeError, ValueError):
        pass
    seconds = _ltx_director_link_value(wf, field_values, inputs.get("duration_seconds"))
    fps = _ltx_director_link_value(wf, field_values, inputs.get("frame_rate"))
    try:
        return max(1, int(round(float(seconds) * float(fps))) + 1)
    except (TypeError, ValueError):
        return 0


def _sync_ltx_director_segment_coverage(wf: dict, node: dict, field_values: dict, segments: list[dict]) -> None:
    expected = _ltx_director_expected_frames(wf, node, field_values)
    if expected <= 0 or not segments:
        return
    total = 0
    for seg in segments:
        try:
            total += max(0, int(seg.get("length") or 0))
        except (TypeError, ValueError):
            pass
    gap = expected - total
    if gap <= 0:
        return
    last = next((seg for seg in reversed(segments) if isinstance(seg, dict)), None)
    if not last:
        return
    try:
        last["length"] = max(1, int(last.get("length") or 0) + gap)
    except (TypeError, ValueError):
        last["length"] = gap


def _sync_ltx_director_timeline_prompts(wf: dict, field_values: dict) -> None:
    for nid, node in (wf or {}).items():
        if not isinstance(node, dict) or node.get("class_type") != "LTXDirector":
            continue
        inputs = node.get("inputs") or {}
        timeline_key = f"{nid}::timeline_data"
        local_prompts_key = f"{nid}::local_prompts"
        segment_lengths_key = f"{nid}::segment_lengths"
        guide_strength_key = f"{nid}::guide_strength"
        global_prompt = field_values.get(f"{nid}::global_prompt", inputs.get("global_prompt", ""))
        raw_timeline = field_values.get(timeline_key, inputs.get("timeline_data", ""))
        try:
            data = json.loads(raw_timeline) if isinstance(raw_timeline, str) else dict(raw_timeline or {})
        except Exception:
            continue
        segments = data.get("segments")
        if not isinstance(segments, list) or not segments:
            continue
        changed = False
        before_lengths = [seg.get("length") for seg in segments if isinstance(seg, dict)]
        _sync_ltx_director_segment_coverage(wf, node, field_values, segments)
        after_lengths = [seg.get("length") for seg in segments if isinstance(seg, dict)]
        if before_lengths != after_lengths:
            changed = True
        total = len(segments)
        for idx, seg in enumerate(segments):
            if not isinstance(seg, dict):
                continue
            if str(seg.get("prompt") or "").strip():
                seg["prompt"] = str(seg.get("prompt") or "").strip()
                continue
            seg["prompt"] = _ltx_director_default_segment_prompt(str(global_prompt or ""), idx, total)
            changed = True
        if changed:
            field_values[timeline_key] = json.dumps(data, ensure_ascii=False)
        prompts = [str(seg.get("prompt") or "").strip() for seg in segments if isinstance(seg, dict)]
        if prompts:
            field_values[local_prompts_key] = "|".join(prompts)
        if not str(field_values.get(segment_lengths_key, "") or "").strip():
            lengths = [str(seg.get("length") or "") for seg in segments if isinstance(seg, dict)]
            field_values[segment_lengths_key] = ",".join(lengths)
        if not str(field_values.get(guide_strength_key, "") or "").strip():
            strengths = [str(seg.get("strength", 0.9)) for seg in segments if isinstance(seg, dict)]
            field_values[guide_strength_key] = ",".join(strengths)


def _normalize_workflow_field_values(wf: dict, field_values: dict) -> dict:
    normalized = dict(field_values or {})
    for key, value in list(normalized.items()):
        if "::" not in key:
            continue
        nid, field = key.split("::", 1)
        node = wf.get(nid, {})
        if not isinstance(node, dict):
            continue
        normalized[key] = _normalize_seed_value_for_field(
            str(node.get("class_type") or ""),
            field,
            value,
        )
    _sync_flux2_scheduler_dimensions(wf, normalized)
    _sync_ltx_video_timing(wf, normalized)
    _sync_ltx_director_timeline_prompts(wf, normalized)
    return normalized


def _resolve_link(wf: dict, value, depth: int = 0):
    """Follow ComfyUI link references to get actual value."""
    if depth > 10 or not isinstance(value, list) or len(value) < 2:
        return value
    node_id = str(value[0])
    node = wf.get(node_id, {})
    if not isinstance(node, dict):
        return value
    ct = node.get("class_type", "")
    inputs = node.get("inputs", {})
    if ct in ("PrimitiveInt", "PrimitiveFloat"):
        return inputs.get("value", value)
    if ct in ("ComfySwitchNode",):
        for branch in ("on_true", "on_false"):
            if branch in inputs:
                resolved = _resolve_link(wf, inputs[branch], depth + 1)
                if not isinstance(resolved, list):
                    return resolved
    return value


# ── Workflow Editor: auto-classify + config persistence ────────────────
def _auto_classify(ct: str, field: str, value) -> tuple:
    """Return (zone, visible) based on node type and field name."""
    if ct in ("CLIPTextEncode", "CLIPTextEncodeFlux", "TextEncodeQwenImageEditPlus"):
        f = "text" if ct in ("CLIPTextEncode", "CLIPTextEncodeFlux") else "prompt"
        if field == f:
            has_val = bool(value and str(value).strip())
            return ("user_input", True) if has_val else ("advanced", False)
    if ct == "LoadImage" and field == "image":
        return ("user_input", True)
    if ct == "LoadVideo" and field == "file":
        return ("user_input", True)
    if ct == "KSampler":
        return ("advanced", True)
    if ct in ("EmptySD3LatentImage", "EmptyLatentImage"):
        return ("advanced", True)
    if ct == "SaveImage":
        return ("output", True)
    if ct in ("SeedVR2VideoUpscaler",):
        return ("advanced", True)
    if ct == "QwenMultiangleCameraNode":
        if field in ("horizontal_angle", "vertical_angle", "zoom"):
            return ("user_input", True)
        if field in ("default_prompts", "camera_view"):
            return ("hidden", False)
    if ct == "SamplerCustom" and field == "noise_seed":
        return ("advanced", True)
    return ("hidden", False)


def analyze_workflow(path: str) -> dict:
    """Scan all nodes, return editable fields with auto-classification."""
    with open(path) as f:
        wf = json.load(f)
    nodes = []
    model_name = ""
    for nid, v in sorted(wf.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 999):
        if not isinstance(v, dict):
            continue
        ct = v.get("class_type", "")
        title = v.get("_meta", {}).get("title", ct)
        inputs = v.get("inputs", {})
        if "model_name" in inputs and not model_name:
            model_name = inputs["model_name"]
        node_fields = []
        for fk, fv in inputs.items():
            if isinstance(fv, list) and len(fv) == 2 and isinstance(fv[0], (str, int)):
                continue
            ui_type = "text"
            if isinstance(fv, bool):
                ui_type = "toggle"
            elif isinstance(fv, float):
                ui_type = "number"
            elif isinstance(fv, int):
                ui_type = "number"
            ef_extra = {}
            seed_like = _looks_like_seed_field(ct, title, fk)
            if ct in EDITABLE_FIELDS and fk in EDITABLE_FIELDS[ct]:
                ef = EDITABLE_FIELDS[ct][fk]
                ui_type = ef.get("type", ui_type)
                for k in ("options", "step", "min", "max"):
                    if k in ef:
                        ef_extra[k] = ef[k]
            elif seed_like:
                ui_type = "seed"
            zone, visible = _auto_classify(ct, fk, fv)
            if seed_like:
                zone, visible = "advanced", True
            field_entry = {
                "key": f"{nid}::{fk}",
                "field": fk,
                "type": ui_type,
                "label": title if seed_like and fk == "value" else fk,
                "value": fv,
                "zone": zone,
                "visible": visible,
            }
            field_entry.update(ef_extra)
            node_fields.append(field_entry)
        if node_fields:
            nodes.append({
                "node_id": nid,
                "class_type": ct,
                "title": title,
                "fields": node_fields,
            })
    summary = model_name or Path(path).stem.replace("-", " ").replace("_", " ")
    return {"nodes": nodes, "summary": summary, "model": model_name}


def load_wf_config(name: str):
    """Load per-workflow config. Returns None if not found."""
    try:
        conn = _db_connect()
        try:
            row = conn.execute(
                """
                SELECT config_json
                FROM workflow_editor_config
                WHERE workflow_filename=? AND config_scope='global' AND user_id=''
                LIMIT 1
                """,
                (name,),
            ).fetchone()
        finally:
            conn.close()
        config = _workflow_config_row_to_entry(row)
        if config is not None:
            return config
    except Exception as e:
        add_log("warn", "wf_config", f"Failed to load workflow config from DB: {e}")
    p = os.path.join(WF_CONFIG_DIR, name)
    if os.path.isfile(p):
        with open(p) as f:
            return json.load(f)
    return None


def save_wf_config(name: str, config: dict):
    """Save per-workflow config."""
    _write_wf_config_to_db(name, config)
    _export_wf_config_file_from_db(name)


def _write_wf_config_to_db(name: str, config: dict, conn: sqlite3.Connection | None = None):
    own_conn = conn is None
    if own_conn:
        conn = _db_connect()
    conn.execute(
        """
        INSERT INTO workflow_editor_config
            (workflow_filename, config_scope, user_id, config_json, updated_at)
        VALUES (?, 'global', '', ?, datetime('now','localtime'))
        ON CONFLICT(workflow_filename, config_scope, user_id) DO UPDATE SET
            config_json=excluded.config_json,
            updated_at=datetime('now','localtime')
        """,
        (name, _json_dumps_compact(config)),
    )
    if own_conn:
        conn.commit()
        conn.close()


def _delete_wf_config(name: str):
    conn = _db_connect()
    try:
        conn.execute(
            """
            DELETE FROM workflow_editor_config
            WHERE workflow_filename=? AND config_scope='global' AND user_id=''
            """,
            (name,),
        )
        conn.commit()
    finally:
        conn.close()
    p = os.path.join(WF_CONFIG_DIR, name)
    if os.path.isfile(p):
        os.remove(p)


def _export_wf_config_file_from_db(name: str):
    os.makedirs(WF_CONFIG_DIR, exist_ok=True)
    p = os.path.join(WF_CONFIG_DIR, name)
    config = None
    try:
        conn = _db_connect()
        try:
            row = conn.execute(
                """
                SELECT config_json
                FROM workflow_editor_config
                WHERE workflow_filename=? AND config_scope='global' AND user_id=''
                LIMIT 1
                """,
                (name,),
            ).fetchone()
        finally:
            conn.close()
        config = _workflow_config_row_to_entry(row)
    except Exception as e:
        add_log("warn", "wf_config", f"Failed to export workflow config mirror: {e}")
        return
    if config is None:
        if os.path.isfile(p):
            os.remove(p)
        return
    with open(p, "w") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _migrate_wf_configs_to_db():
    if not os.path.isdir(WF_CONFIG_DIR):
        return
    conn = _db_connect()
    migrated = 0
    try:
        for filename in sorted(os.listdir(WF_CONFIG_DIR)):
            p = os.path.join(WF_CONFIG_DIR, filename)
            if not os.path.isfile(p):
                continue
            exists = conn.execute(
                """
                SELECT 1
                FROM workflow_editor_config
                WHERE workflow_filename=? AND config_scope='global' AND user_id=''
                LIMIT 1
                """,
                (filename,),
            ).fetchone()
            if exists:
                continue
            try:
                with open(p) as f:
                    config = json.load(f)
            except Exception as e:
                add_log("warn", "wf_config", f"Failed to migrate {filename}: {e}")
                continue
            _write_wf_config_to_db(filename, config, conn=conn)
            migrated += 1
        conn.commit()
    finally:
        conn.close()
    if migrated:
        add_log("info", "wf_config", f"Migrated {migrated} workflow editor configs to DB")


def parse_workflow(path: str, wf_name: str = "") -> dict:
    """Return {fields: [...], summary: str}. Uses config overlay if available."""
    if wf_name:
        config = load_wf_config(wf_name)
        if config and "fields" in config:
            return _parse_with_config(path, config)
    return _parse_legacy(path)


def _parse_legacy(path: str) -> dict:
    """Original parse_workflow logic using EDITABLE_FIELDS."""
    with open(path) as f:
        wf = json.load(f)
    fields = []
    model_name = ""
    for nid, v in sorted(wf.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 999):
        if not isinstance(v, dict):
            continue
        ct = v.get("class_type", "")
        title = v.get("_meta", {}).get("title", ct)
        inputs = v.get("inputs", {})
        if "model_name" in inputs and not model_name:
            model_name = inputs["model_name"]
        if ct in EDITABLE_FIELDS:
            for fk, fm in EDITABLE_FIELDS[ct].items():
                if fk in inputs:
                    val = inputs[fk]
                    if isinstance(val, list):
                        val = _resolve_link(wf, val)
                    fields.append({
                        "node_id": nid, "node_title": title,
                        "class_type": ct, "field": fk,
                        "value": val, **fm,
                    })
        for fk, val in inputs.items():
            if ct in EDITABLE_FIELDS and fk in EDITABLE_FIELDS[ct]:
                continue
            if not _looks_like_seed_field(ct, title, fk):
                continue
            if isinstance(val, list):
                val = _resolve_link(wf, val)
            fields.append({
                "node_id": nid, "node_title": title,
                "class_type": ct, "field": fk,
                "value": val,
                "type": "seed",
                "label": title if fk == "value" else "种子",
            })
    summary = model_name or Path(path).stem.replace("-", " ").replace("_", " ")
    return {"fields": fields, "summary": summary, "model": model_name}


def _parse_with_config(path: str, config: dict) -> dict:
    """Parse workflow using saved config overlay."""
    with open(path) as f:
        wf = json.load(f)
    model_name = ""
    for nid, v in wf.items():
        if isinstance(v, dict) and "model_name" in v.get("inputs", {}):
            model_name = v["inputs"]["model_name"]
            break
    node_map = {}
    for nid, v in wf.items():
        if isinstance(v, dict):
            node_map[str(nid)] = v
    zone_rank = {"user_input": 0, "advanced": 1, "output": 2, "hidden": 3}
    def _field_cfg_order(item):
        idx, cfg = item
        cfg = cfg or {}
        try:
            order = int(cfg.get("order") or 0)
        except (TypeError, ValueError):
            order = 0
        return (zone_rank.get(str(cfg.get("zone") or "hidden"), 99), order, idx)

    config_fields = sorted(
        enumerate(config.get("fields", [])),
        key=_field_cfg_order,
    )
    fields = []
    for _cfg_index, field_cfg in config_fields:
        key = field_cfg.get("key", "")
        if "::" not in key:
            continue
        nid, fname = key.split("::", 1)
        node = node_map.get(nid, {})
        if not node:
            continue
        ct = node.get("class_type", "")
        title = node.get("_meta", {}).get("title", ct)
        val = node.get("inputs", {}).get(fname)
        if isinstance(val, list):
            val = _resolve_link(wf, val)
        ftype = field_cfg.get("type", "")
        fextra = {}
        seed_like = _looks_like_seed_field(ct, title, fname)
        if ct in EDITABLE_FIELDS and fname in EDITABLE_FIELDS[ct]:
            ef = EDITABLE_FIELDS[ct][fname]
            if not ftype:
                ftype = ef.get("type", "text")
            for k in ("options", "step", "min", "max"):
                if k in ef:
                    fextra[k] = ef[k]
        if seed_like:
            ftype = "seed"
        if not ftype:
            ftype = "text"
        for k in ("options", "step", "min", "max"):
            if k in field_cfg:
                fextra[k] = field_cfg[k]
        fields.append({
            "node_id": nid, "node_title": title,
            "class_type": ct, "field": fname,
            "value": val,
            "type": ftype,
            "label": title if seed_like and fname == "value" else field_cfg.get("label", fname),
            "zone": "advanced" if seed_like else field_cfg.get("zone", "user_input"),
            "visible": field_cfg.get("visible", True),
            "order": field_cfg.get("order", 0),
            **fextra,
        })
    summary = model_name or Path(path).stem.replace("-", " ").replace("_", " ")
    return {"fields": fields, "summary": summary, "model": model_name}


# ══════════════════════════════════════════════════════════════════════════
#  Broadcast
# ══════════════════════════════════════════════════════════════════════════

def _ws_payload_owner(data: dict) -> str:
    if not isinstance(data, dict):
        return ""
    msg_type = data.get("type")
    if msg_type == "job_update":
        job = data.get("job") or {}
        return str(job.get("user_id") or "")
    if msg_type == "job_cancelled":
        job_id = str(data.get("job_id") or "")
        job = jobs.get(job_id) or {}
        return str(job.get("user_id") or "")
    return ""


def _ws_client_can_receive(client_user: dict | None, data: dict) -> bool:
    owner = _ws_payload_owner(data)
    if not owner:
        return True
    if _is_admin_user(client_user):
        return True
    client_user_id = _user_id(client_user or {})
    return bool(client_user_id and client_user_id == owner)


async def broadcast(data: dict):
    data = _enrich_broadcast_payload(data)
    dead = []
    for ws in ws_clients:
        if not _ws_client_can_receive(ws_client_users.get(ws), data):
            continue
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.remove(ws)
        ws_client_users.pop(ws, None)


# ══════════════════════════════════════════════════════════════════════════
#  Background generation
# ══════════════════════════════════════════════════════════════════════════

# ── ComfyUI node → human-readable status ────────────────────────────────
NODE_STATUS_MAP = {
    "NunchakuZImageDiTLoader": "加载 DiT 模型...",
    "UNETLoader": "加载 UNet 模型...",
    "SeedVR2LoadDiTModel": "加载 SeedVR2 模型...",
    "DualCLIPLoader": "加载双 CLIP...",
    "CLIPLoader": "加载 CLIP...",
    "CLIPVisionLoader": "加载 CLIP Vision...",
    "VAELoader": "加载 VAE...",
    "UpscaleModelLoader": "加载超分模型...",
    "UNETLoaderGGUF": "加载 GGUF 模型...",
    "LoraLoader": "加载 LoRA...",
    "ModelSamplingAuraFlow": "配置采样策略...",
    "ModelSamplingFlux": "配置 Flux 采样...",
    "CLIPTextEncode": "编码提示词...",
    "TextEncodeQwenImageEditPlus": "编码提示词...",
    "CLIPTextEncodeFlux": "编码 Flux 提示词...",
    "ConditioningZeroOut": "处理条件...",
    "ConditioningSetTimestepRange": "设置时间步范围...",
    "EmptySD3LatentImage": "准备潜空间...",
    "EmptyLatentImage": "准备潜空间...",
    "KSampler": "采样中...",
    "KSamplerAdvanced": "高级采样中...",
    "SamplerCustom": "自定义采样中...",
    "VAEDecode": "解码内容...",
    "VAEEncode": "编码内容...",
    "ImageUpscaleWithModel": "超分辨率放大...",
    "SeedVR2VideoUpscaler": "超分辨率放大...",
    "ImageScaleBy": "缩放内容...",
    "ImageScale": "缩放内容...",
    "ImageCompositeMasked": "合成内容...",
    "LoadVideo": "加载视频...",
    "GetVideoComponents": "解析视频...",
    "CreateVideo": "创建视频...",
    "SaveVideo": "保存视频...",
    "SaveImage": "保存结果...",
}


async def comfyui_ws_track(job_id: str, workflow: dict, client_id: str, timeout: int = 600, base_url: str = None):
    """Connect to ComfyUI WS, submit prompt, track execution."""
    instance_url = base_url or COMFYUI_URL
    ws_url = instance_url.replace("http://", "ws://") + f"/ws?clientId={client_id}"
    start = time.time()
    current_node_cls = ""
    prompt_id = ""

    node_types = {}
    node_titles = {}
    for nid, v in workflow.items():
        if isinstance(v, dict) and "class_type" in v:
            node_types[str(nid)] = v["class_type"]
            title = v.get("_meta", {}).get("title", "")
            if title:
                node_titles[str(nid)] = title

    SAMPLER_NODES = {"KSampler", "KSamplerAdvanced", "SamplerCustom", "FluxSampler"}
    UPSCALE_ACT_NODES = {"ImageUpscaleWithModel", "SeedVR2VideoUpscaler"}

    non_sampler_cnt = 0
    sampler_steps_total = 0
    for nid, cls in node_types.items():
        if cls in SAMPLER_NODES or cls in UPSCALE_ACT_NODES:
            inp = workflow.get(nid, {}).get("inputs", {})
            v = inp.get("steps", 8 if cls in SAMPLER_NODES else 4)
            if isinstance(v, (int, float)):
                sampler_steps_total += int(v)
            elif isinstance(v, list) and len(v) >= 1:
                ln = workflow.get(str(v[0]), {}).get("inputs", {})
                for k in ("value", "INT"):
                    if k in ln and isinstance(ln[k], (int, float)):
                        sampler_steps_total += int(ln[k])
                        break
                else:
                    sampler_steps_total += 8 if cls in SAMPLER_NODES else 4
            else:
                sampler_steps_total += 8 if cls in SAMPLER_NODES else 4
        else:
            if cls != "VAEDecode":
                non_sampler_cnt += 1

    total_units = non_sampler_cnt + sampler_steps_total
    completed_units = 0.0
    last_prog = 0
    sampler_cur = 0
    sampler_total = 0

    def _overall_pct():
        return max(0, min(100, round(completed_units / total_units * 100))) if total_units > 0 else 0

    def update_job():
        label = NODE_STATUS_MAP.get(current_node_cls, current_node_cls) if current_node_cls else ""
        pct = _overall_pct()
        msg = "准备中..." if not current_node_cls and completed_units == 0 else (f"{label} {sampler_cur}/{sampler_total}" if label and sampler_total > 0 else ("采样准备中" if label and "采样" in label else ("超分准备中" if label and "超分" in label else (label if label else f"{pct:.0f}%..."))))
        jobs[job_id]["message"] = msg
        jobs[job_id]["progress"] = {"pct": pct}
        jobs[job_id]["last_update"] = time.time()
        save_jobs()

    try:
        async with websockets.connect(ws_url) as ws:
            update_job()
            await broadcast({"type": "job_update", "job": jobs[job_id]})

            resp = comfyui_post("/prompt", {"prompt": workflow, "client_id": client_id}, base_url=instance_url)
            prompt_id = resp.get("prompt_id", "")
            if not prompt_id:
                raise RuntimeError(f"ComfyUI 返回无 prompt_id: {json.dumps(resp)[:200]}")
            jobs[job_id]["prompt_id"] = prompt_id
            save_jobs()

            while time.time() - start < timeout:
                try:
                    async with asyncio.timeout(300):
                        raw = await ws.recv()
                except asyncio.TimeoutError:
                    break
                except websockets.exceptions.ConnectionClosed:
                    break

                try:
                    msg = json.loads(raw)
                except Exception:
                    continue

                msg_type = msg.get("type", "")
                data = msg.get("data", {})

                msg_pid = data.get("prompt_id", "")
                if msg_pid and prompt_id and msg_pid != prompt_id:
                    continue

                if msg_type == "executing":
                    node_id = data.get("node")
                    if node_id is None:
                        completed_units = total_units
                        update_job()
                        await broadcast({"type": "job_update", "job": jobs[job_id]})
                        add_log("info", "complete", f"Workflow finished", job_id)
                        return True, prompt_id
                    nid = str(node_id)
                    cls = node_types.get(nid, "")
                    current_node_cls = cls
                    title = node_titles.get(nid, cls or nid)
                    add_log("info", "node", f"[{cls}] {title}", job_id)
                    if cls not in SAMPLER_NODES and cls not in UPSCALE_ACT_NODES and cls != "VAEDecode":
                        completed_units += 1.0
                    else:
                        last_prog = 0
                        completed_units += 1.0
                        sampler_cur = 0
                        sampler_total = 0
                        if cls in SAMPLER_NODES:
                            add_log("info", "sampler", f"[{cls}] Starting sampling", job_id)
                    update_job()
                    await broadcast({"type": "job_update", "job": jobs[job_id]})

                elif msg_type == "progress":
                    cur = data.get("value", 0)
                    total = data.get("max", 1)
                    sampler_cur = cur
                    sampler_total = total
                    if cur > last_prog:
                        completed_units += cur - last_prog
                        last_prog = cur
                        if total > 0 and (cur == 1 or cur == total or cur % max(1, total // 4) == 0):
                            add_log("info", "step", f"Sampling {cur}/{total}", job_id)
                    prog_node = data.get("node")
                    if prog_node is not None:
                        cls = node_types.get(str(prog_node), "")
                    if not cls:
                        current_node_cls = ""
                        if cls:
                            current_node_cls = cls
                    update_job()
                    await broadcast({"type": "job_update", "job": jobs[job_id]})

                elif msg_type == "executed":
                    enode = data.get("node")
                    if enode is not None:
                        cls = node_types.get(str(enode), "")
                        if cls:
                            current_node_cls = cls
                            add_log("info", "done", f"[{cls}] Completed", job_id)
                    update_job()
                    await broadcast({"type": "job_update", "job": jobs[job_id]})

                elif msg_type == "execution_error":
                    err = data.get("exception_message", str(data)[:300])
                    add_log("error", "error", f"ComfyUI execution error: {err[:100]}", job_id)
                    raise RuntimeError(f"ComfyUI: {err}")

                elif msg_type == "execution_start":
                    add_log("info", "start", "Workflow execution started", job_id)
                    update_job()
                    await broadcast({"type": "job_update", "job": jobs[job_id]})

    except (ConnectionRefusedError, OSError, websockets.exceptions.WebSocketException):
        pass

    if prompt_id:
        while time.time() - start < timeout:
            await asyncio.sleep(3)
            job_data = jobs.get(job_id, {})
            if job_data and job_data.get("status") == "generating":
                await broadcast({"type": "job_update", "job": job_data})
            try:
                hist = comfyui_get(f"/history/{prompt_id}", base_url=instance_url)
                if prompt_id in hist:
                    entry = hist[prompt_id]
                    status = entry.get("status", {})
                    if status.get("completed", False):
                        return True, prompt_id
                    if status.get("status_str") == "error":
                        msgs = status.get("messages", [])
                        raise RuntimeError(str(msgs)[:300] if msgs else "ComfyUI 执行出错")
            except RuntimeError:
                raise
            except Exception:
                pass

    raise TimeoutError("出图超时 (600s)")

async def generate_task(job_id, workflow_path, field_values, seed, vllm_was_running, img_width=0, img_height=0, instance=None):
    inst = instance or _get_enabled_instances()[0] if _get_enabled_instances() else {"url": COMFYUI_URL, "output_dir": OUTPUT_DIR, "name": "default"}
    inst_url = inst["url"]
    inst_output = inst.get("output_dir", OUTPUT_DIR)
    try:
        jobs[job_id]["status"] = "preparing"
        jobs[job_id]["message"] = "准备 workflow..."
        jobs[job_id]["instance"] = inst["name"]
        await broadcast({"type": "job_update", "job": jobs[job_id]})

        with open(workflow_path) as f:
            wf = json.load(f)

        for key, val in field_values.items():
            if "::" not in key:
                continue
            nid, field = key.split("::", 1)
            if nid in wf and "inputs" in wf[nid]:
                wf[nid]["inputs"][field] = val

        for nid, v in wf.items():
            if isinstance(v, dict) and v.get("class_type") == "KSampler":
                if "seed" in v.get("inputs", {}):
                    v["inputs"]["seed"] = seed

        apply_qwen_frame_roll_to_workflow(wf, field_values, COMFYUI_INPUT)

        issues = validate_api_prompt(wf)
        if issues:
            raise RuntimeError(describe_api_prompt_issues(issues))

        if vllm_was_running:
            jobs[job_id]["message"] = "停止 vLLM 释放显存..."
            await broadcast({"type": "job_update", "job": jobs[job_id]})
            stop_vllm()
            await asyncio.sleep(2)

        if not comfyui_up(base_url=inst_url):
            jobs[job_id]["status"] = "starting_comfyui"
            jobs[job_id]["message"] = f"启动 ComfyUI #{inst['name']}..."
            await broadcast({"type": "job_update", "job": jobs[job_id]})
            node = _get_node_by_id(inst.get("_node_id", ""))
            if node:
                _managed_instance_action(node, inst, "start", reason="generate")
            else:
                svc = f"comfyui-{inst['name'].lower()}"
                subprocess.run(["systemctl", "--user", "start", svc], capture_output=True, timeout=5, env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus", "XDG_RUNTIME_DIR": "/run/user/1000"})
            for _ in range(90):
                await asyncio.sleep(2)
                if comfyui_up(base_url=inst_url):
                    break
            else:
                raise TimeoutError(f"ComfyUI #{inst['name']} 启动超时 (180s)")

        ensure_workflow_images_available(wf, COMFYUI_INPUT, inst_url)

        add_log("info", "generate", "Starting generation", job_id)
        jobs[job_id]["status"] = "generating"
        jobs[job_id]["message"] = "出图中..."
        jobs[job_id]["generating_at"] = time.time()
        save_jobs()
        await broadcast({"type": "job_update", "job": jobs[job_id]})

        elapsed_start = time.time()
        client_id = uuid.uuid4().hex[:12]
        jobs[job_id]["client_id"] = client_id
        save_jobs()
        ws_ok = False
        pid = ""
        try:
            ws_ok, pid = await comfyui_ws_track(job_id, wf, client_id, timeout=900, base_url=inst_url)
        except Exception as _ws_err:
            print(f"[WS_TRACK_ERROR] {job_id}: {_ws_err}")
            add_log("error", "wstrack", f"WS error: {_ws_err}", job_id)
            jobs[job_id]["ws_error"] = str(_ws_err)[:300]

        if not ws_ok and pid:
            for _ in range(60):
                await asyncio.sleep(5)
                try:
                    check = comfyui_get(f"/history/{pid}", base_url=inst_url)
                    if pid in check:
                        st = check[pid].get("status", {})
                        if st.get("completed", False):
                            ws_ok = True
                            break
                        if st.get("status_str") == "error":
                            raise RuntimeError("ComfyUI 执行出错")
                    q = comfyui_get("/queue", base_url=inst_url)
                    running_ids = [item[1] if isinstance(item, list) and len(item) > 1 else None for item in q.get("queue_running", [])]
                    if pid not in running_ids and pid not in check:
                        break
                except RuntimeError:
                    raise
                except Exception:
                    pass

        elapsed = time.time() - elapsed_start

        # ── Remote image pullback: download output images from remote instance ──
        downloaded = []
        if ws_ok and pid:
            jobs[job_id]["status"] = "downloading"
            jobs[job_id]["message"] = "正在保存结果..."
            await broadcast({"type": "job_update", "job": jobs[job_id]})

            downloaded = await asyncio.to_thread(
                _download_remote_images_sync, job_id, pid, inst_url, OUTPUT_DIR
            )
            if downloaded:
                print(f"[generate] Downloaded {len(downloaded)} media file(s) for {job_id[-12:]}")

        if job_id not in jobs:
            return False, pid or ""

        if not ws_ok:
            _extra = jobs[job_id].get("ws_error", "") if job_id in jobs else ""
            raise TimeoutError(f"出图失败{' ('+_extra[:100]+')' if _extra else ''}")

        sources = []
        if downloaded:
            for path in downloaded:
                if path and os.path.isfile(path):
                    sources.append((path, os.path.basename(path), output_media_type(path)))
        if not sources:
            try:
                hist = comfyui_get(f"/history/{pid}", base_url=inst_url)
                if pid in hist:
                    for ref in collect_preferred_outputs(hist[pid].get("outputs", {})):
                        filename = ref.get("filename", "")
                        rel_path = output_ref_rel_path(ref)
                        if not filename or not rel_path:
                            continue
                        src = os.path.join(OUTPUT_DIR, rel_path)
                        if not os.path.isfile(src):
                            matches = glob.glob(os.path.join(OUTPUT_DIR, "**", filename), recursive=True)
                            if matches:
                                src = matches[0]
                        if os.path.isfile(src):
                            sources.append((src, filename, output_media_type(filename)))
            except Exception as e:
                raise RuntimeError(_friendly_generation_error(e))
        if job_id not in jobs or jobs[job_id].get("status") == "error":
            return False, pid or ""
        deduped = []
        seen_paths = set()
        for src, filename, media_type in sources:
            real_path = os.path.abspath(src)
            if real_path in seen_paths or not os.path.isfile(src):
                continue
            seen_paths.add(real_path)
            deduped.append((src, filename or os.path.basename(src), media_type or output_media_type(src)))
        sources = deduped
        if not sources:
            raise RuntimeError("未找到输出媒体")

        gen_user_id = jobs[job_id].get("user_id", "anonymous") if job_id in jobs else "anonymous"
        date_str = datetime.now().strftime("%Y-%m-%d")
        subdir = f"{gen_user_id}/{date_str}"

        wf_basename = os.path.basename(workflow_path).replace('.json', '')
        # Find next sequential number for this workflow today
        existing = glob.glob(os.path.join(OUTPUT_DIR, subdir, f"{wf_basename}_*.*"))
        seq = 1
        for p in existing:
            m = re.search(rf"{re.escape(wf_basename)}_(\d+)\.[^.]+$", os.path.basename(p))
            if m:
                n = int(m.group(1))
                if n >= seq: seq = n + 1
        output_subdir = os.path.join(OUTPUT_DIR, subdir)
        os.makedirs(output_subdir, exist_ok=True)

        prompt_text = infer_generation_label(
            os.path.basename(workflow_path),
            field_values,
            _workflow_primary_type(os.path.basename(workflow_path)),
        )

        batch_count = len(sources)
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        records = []
        for idx, (src, filename, media_type) in enumerate(sources):
            ext = os.path.splitext(filename or src)[1].lower() or ".png"
            hist_name = f"{wf_basename}_{seq + idx:04d}{ext}"
            rel_path = f"{subdir}/{hist_name}"
            dst_path = os.path.join(output_subdir, hist_name)
            shutil.copy2(src, dst_path)
            thumb_rel = make_thumbnail(rel_path) or ""
            actual_w, actual_h = get_media_size(rel_path, media_type, thumb_rel)
            records.append({
                "id": job_id if idx == 0 else f"{job_id}_{idx + 1:02d}",
                "filename": rel_path,
                "media_type": media_type,
                "original": filename,
                "workflow": os.path.basename(workflow_path),
                "prompt": prompt_text, "seed": str(seed),
                "width": actual_w or img_width, "height": actual_h or img_height,
                "elapsed": round(elapsed, 1),
                "time": created_at,
                "thumb": thumb_rel,
                "field_values": field_values,
                "user_id": gen_user_id,
                "batch_id": job_id if batch_count > 1 else "",
                "batch_index": idx,
                "batch_count": batch_count,
                "protection_status": IMAGE_PROTECTION_PENDING,
            })
        for record in reversed(records):
            history.insert(0, record)
        save_history()
        # Also write to SQLite with user_id
        gen_user_id = ""
        if job_id in jobs:
            gen_user_id = jobs[job_id].get("user_id", "")
        for record in reversed(records):
            _insert_generation(record, elapsed, user_id=gen_user_id)

        cover = records[0]
        jobs[job_id].update(
            status="checking", message="内容校验中",
            protection_status=IMAGE_PROTECTION_PENDING,
            pending_image=cover.get("filename", ""),
            pending_media_type=cover.get("media_type", "image") or "image",
            pending_thumb=cover.get("thumb", ""),
            images=[record.get("filename", "") for record in records],
            media_types=[record.get("media_type", "image") or "image" for record in records],
            thumbs=[record.get("thumb", "") for record in records],
            batch_id=job_id if batch_count > 1 else "",
            batch_count=batch_count,
            batch_items=records,
            elapsed=round(elapsed, 1),
            progress={"pct": 100},
        )
        _schedule_image_protection(job_id, records, round(elapsed, 1))
        await broadcast({"type": "job_update", "job": jobs[job_id]})

    except Exception as e:
        import traceback
        jobs[job_id]["status"] = "error"
        jobs[job_id]["trace"] = traceback.format_exc()[:500]
        if isinstance(e, TimeoutError):
            jobs[job_id]["message"] = "出图失败"
        else:
            jobs[job_id]["message"] = _friendly_generation_error(e)
        await broadcast({"type": "job_update", "job": jobs[job_id]})
    finally:
        save_jobs()
        if vllm_was_running:
            start_vllm()


# ══════════════════════════════════════════════════════════════════════════
#  Jobs persistence
# ══════════════════════════════════════════════════════════════════════════

def save_jobs():
    active = {k: v for k, v in jobs.items() if v.get("status") not in ("done", "cancelled")}
    try:
        os.makedirs(os.path.dirname(JOBS_FILE), exist_ok=True)
        tmp_file = f"{JOBS_FILE}.tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(list(active.values()), f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, JOBS_FILE)
    except Exception:
        pass


def load_jobs():
    if not os.path.isfile(JOBS_FILE):
        return
    try:
        with open(JOBS_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        add_log("warn", "queue", f"恢复任务文件失败: {e}")
        return
    if isinstance(raw, dict):
        raw_jobs = list(raw.values())
    elif isinstance(raw, list):
        raw_jobs = raw
    else:
        raw_jobs = []
    restored = 0
    now = time.time()
    for item in raw_jobs:
        if not isinstance(item, dict):
            continue
        job_id = str(item.get("id") or "")
        status = str(item.get("status") or "")
        if not job_id or status in ("done", "cancelled"):
            continue
        job = dict(item)
        job["id"] = job_id
        job["status"] = status or "queued"
        job["last_update"] = float(job.get("last_update") or now)
        if job.get("prompt_id") and job["status"] not in ("error", "cancelled", "retrying"):
            job["message"] = "服务重启后恢复追踪中..."
        jobs[job_id] = job
        restored += 1
    if restored:
        add_log("info", "queue", f"已恢复 {restored} 个重启前活跃任务")


def _job_log_suffix(job_id: str) -> str:
    return str(job_id or "")[-12:]


def _recent_submit_prompt_tail(job_id: str) -> str:
    suffix = _job_log_suffix(job_id)
    for entry in reversed(_log_buffer):
        if str(entry.get("job_id") or "") != suffix:
            continue
        msg = str(entry.get("msg") or "")
        for prefix in ("任务已提交:", "Prompt 已提交:"):
            if msg.startswith(prefix):
                return msg[len(prefix):].strip()
    return ""


def _recover_prompt_id_from_recent_logs(job: dict, inst: dict) -> str:
    """Recover a full ComfyUI prompt_id from the persistent submit-log tail."""
    tail = _recent_submit_prompt_tail(str(job.get("id") or ""))
    if not tail:
        return ""
    candidates: list[str] = []
    try:
        remote_queue = _get_instance_queue_counts(inst.get("url", ""))
        candidates.extend(str(pid) for pid in remote_queue.get("running_prompt_ids", []) if pid)
        candidates.extend(str(pid) for pid in remote_queue.get("pending_prompt_ids", []) if pid)
    except Exception:
        pass
    try:
        hist = comfyui_get("/history", base_url=inst.get("url", ""))
        if isinstance(hist, dict):
            candidates.extend(str(pid) for pid in hist.keys() if pid)
    except Exception:
        pass
    for pid in candidates:
        if pid.endswith(tail):
            return pid
    return ""


def _instance_for_job(job: dict) -> dict | None:
    inst_name = str(job.get("instance") or "")
    if not inst_name:
        return None
    for inst in _get_generation_instances():
        if inst.get("name") == inst_name:
            return inst
    return None


def _job_seed_value(job: dict) -> int:
    try:
        return int(job.get("seed") or 0)
    except Exception:
        return 0


def _job_elapsed_from_resume(job: dict) -> float:
    for key in ("generating_at", "submitted_at", "created_at_ts"):
        try:
            started_at = float(job.get(key) or 0)
        except Exception:
            started_at = 0
        if started_at:
            return max(0.0, time.time() - started_at)
    return 0.0


def _queued_dispatch_job_ids() -> set[str]:
    queued_ids: set[str] = set()
    for item in list(getattr(_job_queue, "_queue", []) or []):
        if isinstance(item, (list, tuple)) and item:
            queued_ids.add(str(item[0]))
    return queued_ids


def _kick_queued_generation_jobs(reason: str = "") -> list[str]:
    queued_statuses = {"queued", "dispatching", "preparing", "starting_comfyui"}
    already_queued = _queued_dispatch_job_ids()
    requeued: list[str] = []
    for job_id, job in list(jobs.items()):
        if job_id in _job_tasks or job_id in already_queued:
            continue
        status = str(job.get("status") or "")
        if job.get("prompt_id") or status not in queued_statuses:
            continue
        path = _resolve_workflow(str(job.get("workflow") or ""))
        if not path:
            job["status"] = "error"
            job["message"] = "恢复排队失败：工作流文件不存在"
            job["last_update"] = time.time()
            continue
        job["status"] = "queued"
        job["message"] = f"{reason}恢复排队..." if reason else "恢复排队..."
        job["last_update"] = time.time()
        _job_queue.put_nowait((
            job_id,
            path,
            job.get("fields") or {},
            _job_seed_value(job),
            False,
            int(job.get("width") or 0),
            int(job.get("height") or 0),
            str(job.get("user_id") or ""),
            str(job.get("preferred_instance") or ""),
            str(job.get("preferred_node_id") or ""),
        ))
        already_queued.add(job_id)
        requeued.append(job_id)
        add_log("info", "queue", f"{reason}已恢复排队任务" if reason else "已恢复排队任务", job_id)
    if requeued:
        save_jobs()
    return requeued


def _resume_persisted_generation_jobs() -> None:
    for job_id, job in list(jobs.items()):
        if job_id in _job_tasks:
            continue
        status = str(job.get("status") or "")
        if status in {"done", "error", "cancelled", "retrying"}:
            continue
        if job.get("prompt_id") or status in {"submitting", "generating", "downloading"}:
            _job_tasks[job_id] = asyncio.create_task(_resume_persisted_generation_job(job_id))
    _kick_queued_generation_jobs("重启后")
    save_jobs()


def _cleanup_retry_source_jobs(completed_job_id: str) -> list[str]:
    removed: list[str] = []
    for old_id, old in list(jobs.items()):
        if old_id == completed_job_id:
            continue
        if old.get("retried_by") == completed_job_id and old.get("status") == "retrying":
            jobs.pop(old_id, None)
            removed.append(old_id)
    return removed


async def _resume_persisted_generation_job(job_id: str) -> None:
    job = jobs.get(job_id)
    if not job:
        return
    inst = _instance_for_job(job)
    if not inst:
        job["status"] = "error"
        job["message"] = "服务重启后恢复失败：找不到原出图实例"
        save_jobs()
        await broadcast({"type": "job_update", "job": job})
        return
    prompt_id = str(job.get("prompt_id") or "")
    if not prompt_id:
        prompt_id = _recover_prompt_id_from_recent_logs(job, inst)
        if prompt_id:
            job["prompt_id"] = prompt_id
    if not prompt_id:
        job["status"] = "error"
        job["message"] = "服务重启后恢复失败：缺少 ComfyUI prompt_id，未重新提交以避免冲突"
        save_jobs()
        await broadcast({"type": "job_update", "job": job})
        return
    graph = _remote_queue_prompt_graph(inst, prompt_id)
    client_id = str(job.get("client_id") or "").strip()
    if not client_id:
        client_id = _remote_queue_prompt_client_id(inst, prompt_id)
        if client_id:
            job["client_id"] = client_id
    if graph and (not job.get("fields") or not job.get("prompt_preview")):
        fields = _remote_graph_field_values(graph)
        if fields and not job.get("fields"):
            job["fields"] = fields
        preview = _remote_graph_prompt_preview(graph)
        if preview and not job.get("prompt_preview"):
            job["prompt_preview"] = preview
    path = _resolve_workflow(str(job.get("workflow") or ""))
    if not path:
        job["status"] = "error"
        job["message"] = "服务重启后恢复失败：工作流文件不存在"
        save_jobs()
        await broadcast({"type": "job_update", "job": job})
        return
    if not graph:
        graph = _workflow_graph_for_resume(path, job)

    add_log("info", "queue", "服务重启后恢复任务追踪", job_id, details=prompt_id)
    job["status"] = "generating"
    job["message"] = "服务重启后恢复追踪中..."
    job["last_update"] = time.time()
    job["instance"] = inst.get("name", "")
    job["progress"] = job.get("progress") or {"pct": 0}
    save_jobs()
    await broadcast({"type": "job_update", "job": job})

    sem_key = inst.get("name", "")
    sem = _instance_semas.setdefault(sem_key, asyncio.Semaphore(1)) if sem_key else None
    acquired = False
    ws_task = None
    try:
        timeout = _workflow_track_timeout(job, path)
        if sem:
            await sem.acquire()
            acquired = True
            job["sem_acquired"] = True
            save_jobs()
        ws_task = _start_resume_ws_progress(job_id, inst, graph, prompt_id, client_id, timeout)
        start = time.time()
        while time.time() - start < timeout:
            hist = {}
            try:
                hist = comfyui_get(f"/history/{prompt_id}", base_url=inst.get("url", ""))
            except Exception:
                hist = {}
            if isinstance(hist, dict) and prompt_id in hist:
                status = hist[prompt_id].get("status", {}) if isinstance(hist[prompt_id], dict) else {}
                if status.get("status_str") == "error":
                    raise RuntimeError("ComfyUI 执行出错")
                if status.get("completed", False):
                    if _job_runner:
                        job["status"] = "downloading"
                        job["message"] = "正在保存结果..."
                        job["progress"] = {"pct": 100}
                        save_jobs()
                        await broadcast({"type": "job_update", "job": job})
                        await _job_runner._save_output(
                            job_id=job_id,
                            prompt_id=prompt_id,
                            instance=inst,
                            workflow_path=path,
                            field_values=job.get("fields") or {},
                            seed=_job_seed_value(job),
                            elapsed=_job_elapsed_from_resume(job),
                            img_width=int(job.get("width") or 0),
                            img_height=int(job.get("height") or 0),
                            user_id=str(job.get("user_id") or ""),
                        )
                        add_log("info", "queue", "重启恢复任务已保存输出", job_id, details=prompt_id)
                    return
            try:
                remote_queue = _get_instance_queue_counts(inst.get("url", ""))
                remote_ids = set(remote_queue.get("running_prompt_ids", []) + remote_queue.get("pending_prompt_ids", []))
                if prompt_id not in remote_ids and not (isinstance(hist, dict) and prompt_id in hist):
                    raise RuntimeError("ComfyUI 队列中已找不到该任务")
            except RuntimeError:
                raise
            except Exception:
                pass
            await asyncio.sleep(5)
        raise TimeoutError("恢复追踪超时")
    except Exception as e:
        if job_id in jobs and jobs[job_id].get("status") not in ("done",):
            jobs[job_id]["status"] = "error"
            jobs[job_id]["message"] = f"服务重启后恢复失败：{str(e)[:120]}"
            save_jobs()
            await broadcast({"type": "job_update", "job": jobs[job_id]})
            add_log("error", "queue", jobs[job_id]["message"], job_id, details=prompt_id)
    finally:
        if acquired and sem:
            try:
                sem.release()
            except ValueError:
                pass
        if job_id in jobs:
            jobs[job_id]["sem_acquired"] = False
        if ws_task and not ws_task.done():
            ws_task.cancel()
            try:
                await ws_task
            except asyncio.CancelledError:
                pass
        _job_tasks.pop(job_id, None)
        save_jobs()


# ══════════════════════════════════════════════════════════════════════════
#  History
# ══════════════════════════════════════════════════════════════════════════

HISTORY_FILE = os.path.join(HISTORY_DIR, "history.json")
THUMB_SIZE = 400
THUMB_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def _project_ffmpeg_bin() -> str | None:
    """Return an explicitly configured or project-local ffmpeg binary."""
    configured = os.environ.get("EZ_COMFYUI_FFMPEG", "")
    candidates = [
        configured,
        os.path.join(_BASE, ".venv", "bin", "ffmpeg"),
        os.path.join(_BASE, "bin", "ffmpeg"),
        os.path.join(_BASE, "tools", "ffmpeg", "ffmpeg"),
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        shutil.which("ffmpeg") or "",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _project_ffprobe_bin() -> str | None:
    """Return an explicitly configured, project-local, or PATH ffprobe binary."""
    ffmpeg = _project_ffmpeg_bin() or ""
    candidates = [
        os.environ.get("EZ_COMFYUI_FFPROBE", ""),
        os.path.join(os.path.dirname(ffmpeg), "ffprobe") if ffmpeg else "",
        os.path.join(_BASE, ".venv", "bin", "ffprobe"),
        os.path.join(_BASE, "bin", "ffprobe"),
        os.path.join(_BASE, "tools", "ffmpeg", "ffprobe"),
        "/opt/homebrew/bin/ffprobe",
        "/usr/local/bin/ffprobe",
        shutil.which("ffprobe") or "",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _parse_video_rate(value: str) -> float:
    value = str(value or "").strip()
    if not value or value == "0/0":
        return 0.0
    try:
        if "/" in value:
            num, den = value.split("/", 1)
            den_f = float(den or 0)
            return float(num or 0) / den_f if den_f else 0.0
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _probe_video_timing(src: str) -> tuple[float, float]:
    """Return (duration_seconds, fps) for the first video stream when ffprobe is available."""
    ffprobe = _project_ffprobe_bin()
    if not ffprobe or not src:
        return 0.0, 0.0
    try:
        result = subprocess.run([
            ffprobe,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=duration,avg_frame_rate,r_frame_rate:format=duration",
            "-of", "json",
            src,
        ], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return 0.0, 0.0
        data = json.loads(getattr(result, "stdout", "") or "{}")
        streams = data.get("streams") or []
        stream = streams[0] if streams and isinstance(streams[0], dict) else {}
        fmt = data.get("format") or {}
        duration = 0.0
        for candidate in (stream.get("duration"), fmt.get("duration")):
            try:
                duration = max(duration, float(candidate or 0))
            except (TypeError, ValueError):
                pass
        fps = _parse_video_rate(stream.get("avg_frame_rate")) or _parse_video_rate(stream.get("r_frame_rate"))
        return max(0.0, duration), max(0.0, fps)
    except Exception:
        return 0.0, 0.0


def _safe_video_frame_time(requested: float, duration: float = 0.0, fps: float = 0.0) -> float:
    try:
        pos = max(0.0, min(float(requested or 0.0), 60 * 60 * 6))
    except (TypeError, ValueError):
        pos = 0.0
    try:
        duration_f = max(0.0, float(duration or 0.0))
    except (TypeError, ValueError):
        duration_f = 0.0
    try:
        fps_f = max(0.0, float(fps or 0.0))
    except (TypeError, ValueError):
        fps_f = 0.0
    if duration_f <= 0:
        return pos
    frame_margin = (1.0 / fps_f) if fps_f > 0 else 0.05
    frame_margin = max(0.001, min(max(frame_margin, 0.04), duration_f / 2.0))
    return max(0.0, min(pos, duration_f - frame_margin))


def _extract_video_frame_with_ffmpeg(ffmpeg: str, src: str, frame_path: str, pos: float):
    return subprocess.run([
        ffmpeg, "-y",
        "-ss", f"{max(0.0, float(pos or 0.0)):.3f}",
        "-i", src,
        "-frames:v", "1",
        "-q:v", "2",
        frame_path,
    ], capture_output=True, timeout=20)


def _make_thumbnail_with_pillow(src: str, thumb_path: str) -> bool:
    """Create a thumbnail using the project Python environment."""
    try:
        from PIL import Image, ImageOps
        try:
            from PIL import UnidentifiedImageError
        except Exception:
            UnidentifiedImageError = OSError
    except Exception as e:
        add_log("warn", "thumbnail", f"pillow unavailable: {e}", os.path.basename(src))
        return False
    try:
        with Image.open(src) as img:
            img = ImageOps.exif_transpose(img)
            img.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
            if img.mode not in ("RGB", "L"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                if "A" in img.getbands():
                    background.paste(img, mask=img.getchannel("A"))
                else:
                    background.paste(img)
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")
            img.save(thumb_path, "JPEG", quality=82, optimize=True)
        return os.path.isfile(thumb_path)
    except UnidentifiedImageError:
        return False
    except Exception as e:
        add_log("warn", "thumbnail", f"pillow thumbnail failed: {e}", os.path.basename(src))
        return False


def make_thumbnail(rel_path: str) -> str | None:
    """Create a thumbnail for the image at OUTPUT_DIR/{rel_path}.
    Returns the relative path to the thumbnail, or None on failure."""
    src = os.path.join(OUTPUT_DIR, rel_path)
    if not os.path.isfile(src):
        return None
    rel_dir = os.path.dirname(rel_path)
    basename = os.path.basename(rel_path)
    thumb_name = basename.rsplit(".", 1)[0] + "_thumb.jpg"
    thumb_rel = os.path.join(rel_dir, thumb_name) if rel_dir else thumb_name
    thumb_path = os.path.join(OUTPUT_DIR, thumb_rel)
    if os.path.isfile(thumb_path):
        return thumb_rel
    os.makedirs(os.path.dirname(thumb_path), exist_ok=True)
    if _make_thumbnail_with_pillow(src, thumb_path):
        return thumb_rel
    if os.path.splitext(basename)[1].lower() in THUMB_IMAGE_EXTS:
        return None
    ffmpeg = _project_ffmpeg_bin()
    if not ffmpeg:
        add_log("warn", "thumbnail", "project ffmpeg not configured; thumbnail skipped", rel_path)
        return None
    try:
        result = subprocess.run([
            ffmpeg, "-y", "-i", src,
            "-vf", f"scale=w={THUMB_SIZE}:h={THUMB_SIZE}:force_original_aspect_ratio=decrease",
            "-frames:v", "1",
            "-q:v", "3", thumb_path
        ], capture_output=True, timeout=10)
        if os.path.isfile(thumb_path):
            return thumb_rel
        stderr = (result.stderr or b"").decode("utf-8", "ignore").strip()
        add_log("warn", "thumbnail", f"thumbnail failed ({result.returncode}): {stderr[-300:]}", rel_path)
    except Exception as e:
        add_log("warn", "thumbnail", f"thumbnail failed: {e}", rel_path)
    return None

def get_image_size(rel_path: str) -> tuple[int, int]:
    """Get image dimensions from OUTPUT_DIR/{rel_path}."""
    path = os.path.join(OUTPUT_DIR, rel_path)
    if not os.path.isfile(path):
        return 0, 0
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img)
            return int(img.width or 0), int(img.height or 0)
    except Exception:
        pass
    try:
        with open(path, "rb") as f:
            f.seek(16)
            buf = f.read(8)
            w = int.from_bytes(buf[0:4], "big")
            h = int.from_bytes(buf[4:8], "big")
            return w, h
    except Exception:
        return 0, 0


def get_video_size(rel_path: str) -> tuple[int, int]:
    """Get first video stream dimensions from OUTPUT_DIR/{rel_path}."""
    path = os.path.join(OUTPUT_DIR, rel_path)
    if not os.path.isfile(path):
        return 0, 0
    ffprobe = _project_ffprobe_bin()
    if not ffprobe:
        return 0, 0
    try:
        result = subprocess.run([
            ffprobe,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=s=x:p=0",
            path,
        ], capture_output=True, text=True, timeout=5)
        line = (result.stdout or "").strip().splitlines()[0] if result.stdout else ""
        match = re.search(r"(\d+)\s*x\s*(\d+)", line)
        if match:
            return int(match.group(1)), int(match.group(2))
    except Exception:
        return 0, 0
    return 0, 0


def get_media_size(rel_path: str, media_type: str = "", thumb_rel: str = "") -> tuple[int, int]:
    """Return real media dimensions, falling back to preview thumbnail dimensions for video."""
    normalized = str(media_type or output_media_type(rel_path)).lower()
    if normalized == "video":
        w, h = get_video_size(rel_path)
        if w and h:
            return w, h
        if thumb_rel:
            w, h = get_image_size(thumb_rel)
            if w and h:
                return w, h
        return 0, 0
    return get_image_size(rel_path)


def load_history():
    global history
    os.makedirs(HISTORY_DIR, exist_ok=True)
    if os.path.isfile(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                history = json.load(f)
        except Exception:
            history = []
    changed = False
    for h in history:
        if "seed" in h and not isinstance(h["seed"], str):
            h["seed"] = str(h["seed"])
            changed = True
        if not h.get("thumb"):
            thumb = make_thumbnail(h.get("filename", ""))
            if thumb:
                h["thumb"] = thumb
                changed = True
        media_type = str(h.get("media_type") or output_media_type(h.get("filename", "")))
        if media_type == "video":
            w, ht = get_video_size(h.get("filename", ""))
            if w > 0 and ht > 0 and (h.get("width") != w or h.get("height") != ht):
                h["width"] = w
                h["height"] = ht
                changed = True
        if not h.get("width") or not h.get("height"):
            w, ht = get_media_size(h.get("filename", ""), media_type, h.get("thumb", ""))
            if w > 0 and ht > 0:
                h["width"] = w
                h["height"] = ht
                changed = True
    if changed:
        save_history()

def save_history():
    with open(HISTORY_FILE, "w") as f:
        json.dump(history[:MAX_HISTORY], f, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════════════════════════
#  Models
# ══════════════════════════════════════════════════════════════════════════

class GenerateRequest(BaseModel):
    workflow: str
    fields: dict[str, object] = {}
    seed: int | None = None
    width: int = 0
    height: int = 0
    preferred_instance: str = ""
    preferred_node_id: str = ""


class PromptOptimizeRequest(BaseModel):
    prompt: str
    max_new_tokens: int = 384
    mode: str = "image"
    prompt_context: dict = Field(default_factory=dict)


class PromptTranslateRequest(BaseModel):
    prompt: str
    target_language: str = ""
    max_new_tokens: int | None = None


_PROMPT_TRANSLATE_CACHE: OrderedDict[tuple[str, str], dict] = OrderedDict()
_PROMPT_TRANSLATE_CACHE_MAX = 160
_PROMPT_TRANSLATE_CACHE_TTL = 6 * 3600


def _prompt_translate_cache_key(prompt: str, target: str) -> tuple[str, str]:
    normalized = re.sub(r"\s+", " ", str(prompt or "").strip())
    return (target, normalized)


def _prompt_translate_cache_get(prompt: str, target: str) -> dict | None:
    key = _prompt_translate_cache_key(prompt, target)
    entry = _PROMPT_TRANSLATE_CACHE.get(key)
    if not entry:
        return None
    if time.time() - float(entry.get("ts", 0)) > _PROMPT_TRANSLATE_CACHE_TTL:
        _PROMPT_TRANSLATE_CACHE.pop(key, None)
        return None
    _PROMPT_TRANSLATE_CACHE.move_to_end(key)
    cached = dict(entry.get("data") or {})
    cached["cached"] = True
    cached["instance"] = cached.get("instance") or "cache"
    return cached


def _prompt_translate_cache_put(prompt: str, target: str, result: dict) -> None:
    translated = str((result or {}).get("translated_prompt") or "").strip()
    if not prompt or not target or not translated:
        return
    data = dict(result or {})
    data["cached"] = True
    _PROMPT_TRANSLATE_CACHE[_prompt_translate_cache_key(prompt, target)] = {"ts": time.time(), "data": data}
    _PROMPT_TRANSLATE_CACHE.move_to_end(_prompt_translate_cache_key(prompt, target))
    reverse_target = "zh" if target == "en" else "en"
    reverse = {
        "ok": True,
        "provider": "prompt-translate-cache",
        "original_prompt": translated,
        "target_language": reverse_target,
        "translated_prompt": str(prompt or "").strip(),
        "prompt_en": str(prompt or "").strip() if reverse_target == "en" else "",
        "prompt_zh": str(prompt or "").strip() if reverse_target == "zh" else "",
        "cached": True,
        "instance": "cache",
    }
    _PROMPT_TRANSLATE_CACHE[_prompt_translate_cache_key(translated, reverse_target)] = {"ts": time.time(), "data": reverse}
    _PROMPT_TRANSLATE_CACHE.move_to_end(_prompt_translate_cache_key(translated, reverse_target))
    while len(_PROMPT_TRANSLATE_CACHE) > _PROMPT_TRANSLATE_CACHE_MAX:
        _PROMPT_TRANSLATE_CACHE.popitem(last=False)


def _is_json_object_text(text: str) -> bool:
    try:
        return isinstance(json.loads(str(text or "").strip()), dict)
    except Exception:
        return False


def _consume_reverse_prompt_quality(result: dict, current_user: dict | None = None) -> dict:
    """Keep reverse-prompt scoring internal; do not expose it to prompt-result JSON."""
    if not isinstance(result, dict):
        return result
    quality = result.pop("reverse_prompt_quality", None)
    expert = result.get("expert_interrogate")
    if isinstance(expert, dict):
        expert.pop("quality", None)
    if isinstance(quality, dict):
        score = quality.get("score")
        target = quality.get("target_score")
        passed = quality.get("passed")
        issues = quality.get("issues") if isinstance(quality.get("issues"), list) else []
        issue_codes = ",".join(str(item.get("code") or "") for item in issues if isinstance(item, dict) and item.get("code"))
        level = "info" if passed else "warn"
        add_log(
            level,
            "prompt_interrogate_quality",
            f"Reverse prompt quality {score}/{target}",
            details=f"user={_user_id(current_user)} issues={issue_codes}",
        )
    return result


class PromptInterrogateRequest(BaseModel):
    image: str
    mode: str = "image"
    prompt_context: dict = Field(default_factory=dict)
    level: int | None = None
    expert: bool = False
    expert_team: bool = False
    # Backward-compatible no-op: model comparison was removed from the product UI.
    compare_models: bool = False


# ══════════════════════════════════════════════════════════════════════════
#  API: Page
# ══════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(html_path.read_text("utf-8")) if html_path.is_file() else HTMLResponse("<h1>index.html missing</h1>", 500)


@app.get("/api/version")
def api_version():
    return {"version": APP_VERSION}


# ══════════════════════════════════════════════════════════════════════════
#  API: Status & GPU
# ══════════════════════════════════════════════════════════════════════════

@app.get("/api/status")
def api_status(
    target_node_id: str = "",
    target_instance: str = "",
    current_user: dict | None = Depends(get_current_user_optional),
):
    instances = []
    visible_instances = _sort_instances_for_status(_get_enabled_instances_for_user(current_user))
    node_gpu = _gpu_stats_for_status_node(visible_instances, target_node_id, target_instance)
    for inst in visible_instances:
        node_id = inst.get("_node_id", "")
        name = inst["name"]
        remote_queue = _get_instance_queue_counts(inst["url"])
        is_active = comfyui_up(base_url=inst["url"])
        _finalize_interrupted_instance_jobs(name, is_active, remote_queue=remote_queue)
        grp = _instance_group.get(name, "")
        inst_jobs = _status_jobs_for_instance(name, is_active)
        local_run = len([j for j in inst_jobs if j["status"] in ("dispatching", "starting_comfyui", "submitting", "generating", "downloading")])
        local_pend = len([j for j in inst_jobs if j["status"] in ("queued", "preparing")])
        untracked_remote_ids = _cleanup_untracked_remote_prompts(inst, remote_queue)
        q_run = max(local_run, remote_queue["running"])
        q_pend = max(local_pend, remote_queue["pending"])
        q_size = max(remote_queue["total"], q_run + q_pend)
        current_job = _current_status_job_for_instance(name, is_active)
        remote_untracked_running = bool(untracked_remote_ids) and not current_job
        current_workflow = ""
        current_label = ""
        if current_job:
            current_workflow = (current_job.get("workflow") or "").replace(".json", "")
            prompt_preview = current_job.get("prompt_preview", "")
            current_label = prompt_preview[:60] if prompt_preview else current_workflow
        instances.append({
            "name": name,
            "port": inst.get("port"),
            "url": inst["url"],
            "node_id": inst.get("_node_id", ""),
            "node_name": inst.get("_node_name", ""),
            "node_connection": inst.get("_node_connection", "local"),
            "role": "generation",
            "up": is_active,
            "queue": q_size,
            "queue_running": q_run,
            "queue_pending": q_pend,
            "progress": _job_progress_pct(current_job),
            "progress_known": bool(current_job),
            "remote_untracked_running": remote_untracked_running,
            "remote_running_prompt_ids": untracked_remote_ids or remote_queue.get("running_prompt_ids", []),
            "current_workflow": current_workflow,
            "current_prompt": current_label,
            "loaded_group": grp,
            "gpu": node_gpu.get(node_id, _empty_gpu_stats("VRAM 未获取到")),
        })
    return {
        "version": APP_VERSION,
        "comfyui": any(i["up"] for i in instances),
        "instances": instances,
        "comfyui_pid": comfyui_pid(),
        "vllm": vllm_running(),
        "workflows": sum(len(glob.glob(os.path.join(d, "**", "*.json"), recursive=True)) for d in _load_wf_dirs()),
        "gpu": get_gpu_stats(),
    }


@app.get("/api/gpu")
def api_gpu(current_user: dict = Depends(get_current_user)):
    return get_gpu_stats()


# ══════════════════════════════════════════════════════════════════════════
#  API: Service management
# ══════════════════════════════════════════════════════════════════════════

@app.post("/api/comfyui/{action}")
def api_comfyui(action: str, current_user: dict = Depends(require_admin)):
    if action == "start":
        results = []
        for inst in _get_enabled_instances():
            node = _get_node_by_id(inst.get("_node_id", ""))
            if node:
                _managed_instance_action(node, inst, "start", reason="api-comfyui")
            else:
                svc = f"comfyui-{inst['name'].lower()}"
                subprocess.run(["systemctl", "--user", "start", svc], capture_output=True, timeout=5, env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus", "XDG_RUNTIME_DIR": "/run/user/1000"})
            results.append(f"{inst['name']} 启动中")
        return {"ok": True, "msg": "; ".join(results)}
    elif action == "stop":
        results = []
        for inst in _get_enabled_instances():
            node = _get_node_by_id(inst.get("_node_id", ""))
            if node:
                _managed_instance_action(node, inst, "stop", reason="api-comfyui")
            else:
                svc = f"comfyui-{inst['name'].lower()}"
                subprocess.run(["systemctl", "--user", "stop", svc], capture_output=True, timeout=5)
            _instance_group[inst["name"]] = ""
            results.append(f"{inst['name']} 已停止")
            _finalize_instance_jobs(inst["name"], "实例已停止")
        _kick_queued_generation_jobs("实例停止后")
        return {"ok": True, "msg": "; ".join(results)}
    raise HTTPException(400)



@app.get("/api/gpu-processes")
def api_gpu_processes(current_user: dict = Depends(require_admin)):
    import subprocess as _sp
    result = []
    try:
        r = _sp.run(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory,name,process_name",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        for line in r.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 4:
                result.append({"pid": parts[0], "mem_mb": int(parts[1]), "name": parts[2], "process": parts[3]})
    except Exception as e:
        return {"error": str(e), "processes": []}
    known_pids = set()
    for inst in _get_enabled_instances():
        node = _get_node_by_id(inst.get("_node_id", ""))
        if node and node.get("connection") == "local":
            try:
                svc = f"comfyui-{inst['name'].lower()}"
                r2 = _sp.run(["systemctl", "--user", "show", svc, "--property=MainPID"],
                             capture_output=True, text=True, timeout=3)
                pid_val = r2.stdout.strip().split("=")[-1]
                if pid_val and pid_val != "0":
                    known_pids.add(int(pid_val))
            except Exception:
                pass
    skip = {"Xorg", "gnome-shell", "Xwayland"}
    filtered = []
    for p in result:
        if int(p["pid"]) in known_pids or p["name"] in skip:
            continue
        if any(s in p["process"].lower() for s in ["xorg", "gnome", "firefox", "xwayland"]):
            continue
        filtered.append(p)
    return {"processes": filtered, "comfyui_pids": list(known_pids)}

@app.post("/api/gpu-processes/kill")
def api_gpu_kill(req: dict, current_user: dict = Depends(require_admin)):
    import subprocess as _sp
    pid = str(req.get("pid", ""))
    if not pid.isdigit():
        raise HTTPException(400, "Invalid PID")
    try:
        _sp.run(["kill", pid], capture_output=True, timeout=3)
        return {"ok": True, "msg": f"PID {pid} terminated"}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/comfyui/status")
def api_comfyui_status(current_user: dict | None = Depends(get_current_user_optional)):
    result = []
    visible_instances = _sort_instances_for_status(_get_enabled_instances_for_user(current_user))
    node_gpu = _gpu_stats_for_status_node(visible_instances)
    for inst in visible_instances:
        name = inst["name"]
        node_id = inst.get("_node_id", "")
        svc = f"comfyui-{name.lower()}"
        is_active = comfyui_up(base_url=inst["url"])
        remote_queue = _get_instance_queue_counts(inst["url"])
        _finalize_interrupted_instance_jobs(name, is_active, remote_queue=remote_queue)
        inst_jobs = _status_jobs_for_instance(name, is_active)
        local_running = len([j for j in inst_jobs if j["status"] in ("generating", "dispatching", "starting_comfyui", "downloading")])
        local_pending = len([j for j in inst_jobs if j["status"] in ("queued", "preparing")])
        queue_running = max(local_running, remote_queue["running"])
        queue_pending = max(local_pending, remote_queue["pending"])
        queue_total = max(remote_queue["total"], queue_running + queue_pending)
        grp = _instance_group.get(name, "")
        current_job = _current_status_job_for_instance(name, is_active)
        untracked_remote_ids = _cleanup_untracked_remote_prompts(inst, remote_queue)
        remote_untracked_running = bool(untracked_remote_ids) and not current_job
        current_label = ""
        current_workflow = ""
        pending_workflows = []
        if current_job:
            workflow_name = (current_job.get("workflow") or "").replace(".json", "")
            current_workflow = workflow_name
            prompt_preview = current_job.get("prompt_preview", "")
            current_label = prompt_preview[:60] if prompt_preview else workflow_name
        for j in inst_jobs:
            if j.get("status") in ("queued", "preparing", "starting_comfyui"):
                wf = (j.get("workflow") or "").replace(".json", "")
                if wf:
                    pending_workflows.append(wf)
        result.append({
            "name": name, "up": is_active, "service": svc,
            "node_id": inst.get("_node_id", ""),
            "node_name": inst.get("_node_name", ""),
            "node_connection": inst.get("_node_connection", "local"),
            "role": "generation",
            "queue": queue_total,
            "queue_running": queue_running, "queue_pending": queue_pending,
            "progress": _job_progress_pct(current_job),
            "progress_known": bool(current_job),
            "remote_untracked_running": remote_untracked_running,
            "remote_running_prompt_ids": untracked_remote_ids or remote_queue.get("running_prompt_ids", []),
            "current_workflow": current_workflow,
            "pending_workflows": pending_workflows,
            "current_prompt": current_label, "loaded_group": grp,
            "port": inst["url"].split(":")[-1] if ":" in inst["url"] else "",
            "gpu": node_gpu.get(node_id, _empty_gpu_stats("VRAM 未获取到")),
        })
    return {"instances": result}

@app.post("/api/comfyui/{instance}/{action}")
def api_comfyui_instance(instance: str, action: str, current_user: dict = Depends(require_admin)):
    """Start/stop a single ComfyUI instance (A or B)."""
    inst = next((i for i in _get_enabled_instances() if i["name"].upper() == instance.upper()), None)
    if not inst:
        raise HTTPException(404, f"Instance {instance} not found")
    node = _get_node_by_id(inst.get("_node_id", ""))
    if action == "start":
        if node:
            _managed_instance_action(node, inst, "start", reason="api-comfyui-instance")
        else:
            svc = f"comfyui-{inst['name'].lower()}"
            subprocess.run(["systemctl", "--user", "start", svc], capture_output=True, timeout=5, env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus", "XDG_RUNTIME_DIR": "/run/user/1000"})
        return {"ok": True, "msg": f"{inst['name']} 启动中"}
    elif action == "stop":
        if node:
            _managed_instance_action(node, inst, "stop", reason="api-comfyui-instance")
        else:
            svc = f"comfyui-{inst['name'].lower()}"
            subprocess.run(["systemctl", "--user", "stop", svc], capture_output=True, timeout=5)
        _instance_group[inst["name"]] = ""
        _finalize_instance_jobs(inst["name"], "实例已停止")
        _kick_queued_generation_jobs("实例停止后")
        return {"ok": True, "msg": f"{inst['name']} 已停止"}
    raise HTTPException(400)


@app.post("/api/vllm/{action}")
def api_vllm(action: str, current_user: dict = Depends(require_admin)):
    if not _legacy_vllm_management_enabled():
        raise HTTPException(410, "Legacy vLLM container management is disabled")
    if action == "start":
        start_vllm()
        return {"ok": True, "msg": "已启动"}
    elif action == "stop":
        stop_vllm()
        return {"ok": True, "msg": "已停止"}
    raise HTTPException(400)


# ══════════════════════════════════════════════════════════════════════════
#  API: Workflows
# ══════════════════════════════════════════════════════════════════════════

def _get_workflow_dirs() -> list[str]:
    """Collect workflow directories from all enabled nodes (node-level + instance-level) + legacy dirs."""
    dirs = []
    seen = set()

    def _append_dir(path: str):
        if not path:
            return
        if path in seen:
            return
        seen.add(path)
        dirs.append(path)

    for node in _load_nodes():
        if not node.get("enabled", True):
            continue
        # Node-level workflow_dirs
        for wd in node.get("workflow_dirs", []):
            _append_dir(wd)
        # Instance-level workflow_dirs
        for inst in node.get("instances", []):
            for wd in inst.get("workflow_dirs", []):
                _append_dir(wd)
    # Also include legacy WF_DIRS_FILE dirs
    legacy = _load_wf_dirs()
    for d in legacy:
        _append_dir(d)
    return dirs

@app.post("/api/workflows/sync")
async def api_sync_workflows(current_user: dict = Depends(require_admin)):
    """Manually trigger remote workflow sync."""
    try:
        result = await asyncio.to_thread(sync_remote_workflows)
        return {"ok": True, "data": result}
    except Exception as e:
        raise HTTPException(500, f"同步失败: {e}")


@app.get("/api/workflows")
def api_workflows(current_user: dict | None = Depends(get_current_user_optional)):
    seen = {}
    meta = _load_wf_meta()
    for d in _get_workflow_dirs():
        for f in glob.glob(os.path.join(d, "**", "*.json"), recursive=True):
            name = os.path.basename(f)
            if name not in seen:
                seen[name] = f
    result = []
    for name in sorted(seen):
        entry = _normalize_wf_meta_entry(name, meta.get(name, {}))
        if not _can_view_workflow(name, entry, current_user):
            continue
        info = parse_workflow(seen[name])
        result.append({
            "name": name,
            "summary": info["summary"],
            "model": info["model"],
            "field_count": len(info["fields"]),
            "dir": os.path.dirname(seen[name]),
            "owner_id": entry.get("owner_id", ""),
            "shared": bool(entry.get("shared", False)),
        })
    return result


@app.get("/api/workflows/find-closest")
def api_workflow_find_closest(workflow: str = "", wf_id: str = "", wf_tags: str = ""):
    """Find the best current workflow for an old history/job record."""
    meta = _load_wf_meta()
    candidates = {}
    for d in _get_workflow_dirs():
        for f in glob.glob(os.path.join(d, "**", "*.json"), recursive=True):
            name = os.path.basename(f)
            if name not in candidates:
                candidates[name] = f

    if workflow in candidates:
        return {"filename": workflow, "matched_by": "filename", "score": 100}

    try:
        requested_tags = set(json.loads(wf_tags)) if wf_tags else set()
    except Exception:
        requested_tags = set()
    requested_stem = os.path.splitext(os.path.basename(workflow or ""))[0].lower()

    best_name = ""
    best_score = 0
    best_reason = ""
    for name in candidates:
        entry = meta.get(name, {})
        score = 0
        reason = ""
        if wf_id and entry.get("id") == wf_id:
            return {"filename": name, "matched_by": "wf_id", "score": 100}

        display = str(entry.get("name", "")).lower()
        stem = os.path.splitext(name)[0].lower()
        if requested_stem and requested_stem in (stem, display):
            score += 60
            reason = "name"
        elif requested_stem and (requested_stem in stem or requested_stem in display):
            score += 35
            reason = "partial_name"

        tags = set(entry.get("tags", []))
        tag_hits = len(tags & requested_tags)
        if tag_hits:
            score += tag_hits * 10
            reason = reason or "tags"

        if score > best_score:
            best_name, best_score, best_reason = name, score, reason

    if best_name and best_score >= 20:
        return {"filename": best_name, "matched_by": best_reason or "score", "score": best_score}
    raise HTTPException(404, "No matching workflow")


@app.get("/api/workflows/{name}/fields")
def api_workflow_fields(name: str, current_user: dict | None = Depends(get_current_user_optional)):
    entry = _normalize_wf_meta_entry(name, _load_wf_meta().get(name, {}))
    if not _can_view_workflow(name, entry, current_user):
        raise HTTPException(403, "No permission for this workflow")
    path = _resolve_workflow(name, entry)
    if not path:
        raise HTTPException(404)
    return parse_workflow(path, wf_name=name)

@app.get("/api/workflows/{name}/analyze")
def api_workflow_analyze(name: str, current_user: dict | None = Depends(get_current_user_optional)):
    entry = _normalize_wf_meta_entry(name, _load_wf_meta().get(name, {}))
    if not _can_view_workflow(name, entry, current_user):
        raise HTTPException(403, "No permission for this workflow")
    path = _resolve_workflow(name, entry)
    if not path:
        raise HTTPException(404)
    return analyze_workflow(path)



@app.get("/api/workflows/{name}/download")
def api_workflow_download(name: str, current_user: dict | None = Depends(get_current_user_optional)):
    entry = _normalize_wf_meta_entry(name, _load_wf_meta().get(name, {}))
    if not _can_view_workflow(name, entry, current_user):
        raise HTTPException(403, "No permission for this workflow")
    path = _resolve_workflow(name, entry)
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type="application/json", filename=name)

@app.get("/api/workflows/{name}/config")
def api_workflow_config_get(name: str, current_user: dict | None = Depends(get_current_user_optional)):
    config = load_wf_config(name)
    if not config:
        raise HTTPException(404)
    return config


@app.put("/api/workflows/{name}/config")
def api_workflow_config_put(name: str, req: dict, current_user: dict = Depends(require_admin)):
    save_wf_config(name, req)
    return {"ok": True}


@app.delete("/api/workflows/{name}/config")
def api_workflow_config_delete(name: str, current_user: dict = Depends(require_admin)):
    _delete_wf_config(name)
    return {"ok": True}


@app.post("/api/workflows/upload")
async def api_workflow_upload(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    name = os.path.basename((file.filename or "").replace("\\", "/"))
    if not name or not name.endswith(".json"):
        raise HTTPException(400, "需要 .json 文件")
    content = await _read_upload_limited(file, _UPLOAD_WORKFLOW_MAX_BYTES, "Workflow")
    try:
        json.loads(content)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"无效 JSON: {e}")
    upload_dir = os.path.join(WORKFLOW_DIR, "ez-comfy")
    os.makedirs(upload_dir, exist_ok=True)
    dest = os.path.join(upload_dir, name)
    with open(dest, "wb") as f:
        f.write(content)
    meta = _load_wf_meta()
    if name not in meta:
        meta[name] = {
            "name": name.replace(".json", ""),
            "tags": _auto_detect_tags(dest),
            "source": "ez-comfy",
            "source_path": dest,
            "owner_id": _user_id(current_user),
            "shared": False,
        }
        _write_wf_meta_entry_to_db(name, meta[name])
        _export_wf_meta_json_from_db()
    else:
        meta[name]["source"] = "ez-comfy"
        meta[name]["source_path"] = dest
        meta[name]["owner_id"] = meta[name].get("owner_id") or _user_id(current_user)
        _write_wf_meta_entry_to_db(name, meta[name])
        _export_wf_meta_json_from_db()
    return {"ok": True, "name": name}


# ── Workflow Directory Management ─────────────────────────────────────

@app.get("/api/workflow-dirs")
def api_workflow_dirs(current_user: dict = Depends(require_admin)):
    dirs = _load_wf_dirs()
    result = []
    for d in dirs:
        count = len(glob.glob(os.path.join(d, "**", "*.json"), recursive=True))
        result.append({"path": d, "exists": os.path.isdir(d), "count": count})
    return result


@app.post("/api/workflow-dirs")
def api_workflow_dir_add(req: dict, current_user: dict = Depends(require_admin)):
    d = req.get("path", "").strip()
    if not d:
        raise HTTPException(400, "path is required")
    d = os.path.expanduser(d)
    d = os.path.abspath(d)
    dirs = _load_wf_dirs()
    if d in dirs:
        raise HTTPException(409, "Directory already added")
    os.makedirs(d, exist_ok=True)
    dirs.append(d)
    _save_wf_dirs(dirs)
    return {"ok": True, "path": d}


@app.delete("/api/workflow-dirs")
def api_workflow_dir_remove(path: str, current_user: dict = Depends(require_admin)):
    d = path.strip()
    if not d:
        raise HTTPException(400, "path is required")
    dirs = _load_wf_dirs()
    if d not in dirs:
        raise HTTPException(404, "Directory not found")
    if len(dirs) <= 1:
        raise HTTPException(400, "Cannot remove the last directory")
    dirs.remove(d)
    _save_wf_dirs(dirs)
    return {"ok": True}


# ── Image Upload ────────────────────────────────────────────────────

_UPLOAD_PASSTHROUGH_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_UPLOAD_NORMALIZE_IMAGE_EXTS = {".tif", ".tiff", ".gif", ".jfif", ".jpe", ".avif", ".heic", ".heif", ""}
_UPLOAD_ALLOWED_IMAGE_EXTS = _UPLOAD_PASSTHROUGH_IMAGE_EXTS | _UPLOAD_NORMALIZE_IMAGE_EXTS
_UPLOAD_ALLOWED_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v"}
_UPLOAD_FORMAT_EXTS = {
    "PNG": {".png"},
    "JPEG": {".jpg", ".jpeg"},
    "WEBP": {".webp"},
    "BMP": {".bmp"},
}
_UPLOAD_SAFE_PASSTHROUGH_MODES = {"RGB", "RGBA", "L", "LA", "P"}
_UPLOAD_IMAGE_MAX_BYTES = int(os.environ.get("EZ_UPLOAD_IMAGE_MAX_BYTES", str(50 * 1024 * 1024)))
_UPLOAD_VIDEO_MAX_BYTES = int(os.environ.get("EZ_UPLOAD_VIDEO_MAX_BYTES", str(512 * 1024 * 1024)))
_UPLOAD_WORKFLOW_MAX_BYTES = int(os.environ.get("EZ_UPLOAD_WORKFLOW_MAX_BYTES", str(10 * 1024 * 1024)))
_UPLOAD_READ_CHUNK_BYTES = 1024 * 1024


async def _read_upload_limited(file: UploadFile, max_bytes: int, label: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(413, f"{label} file is too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _register_optional_image_openers() -> None:
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except Exception:
        pass


def _decode_uploaded_image(content: bytes):
    try:
        from PIL import Image, ImageOps
    except Exception as e:
        raise HTTPException(400, f"Image validation unavailable: {e}") from e
    _register_optional_image_openers()
    try:
        with Image.open(BytesIO(content)) as img:
            source_format = str(img.format or "").upper()
            try:
                img.seek(0)
            except Exception:
                pass
            img.load()
            img = ImageOps.exif_transpose(img)
            return img.copy(), source_format
    except Exception as e:
        raise HTTPException(400, f"Invalid image file: {e}") from e


def _png_bytes_from_image(img) -> bytes:
    if img.mode == "P":
        img = img.convert("RGBA" if "transparency" in img.info else "RGB")
    elif img.mode == "LA":
        img = img.convert("RGBA")
    elif img.mode not in ("RGB", "RGBA", "L"):
        img = img.convert("RGB")
    out = BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _normalize_uploaded_image_content(filename: str, content: bytes) -> tuple[str, bytes]:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in _UPLOAD_ALLOWED_IMAGE_EXTS:
        raise HTTPException(400, f"Unsupported image format: {ext}")
    img, source_format = _decode_uploaded_image(content)
    expected_exts = _UPLOAD_FORMAT_EXTS.get(source_format, set())
    can_passthrough = (
        ext in _UPLOAD_PASSTHROUGH_IMAGE_EXTS
        and ext in expected_exts
        and img.mode in _UPLOAD_SAFE_PASSTHROUGH_MODES
    )
    if can_passthrough:
        return ext, content
    return ".png", _png_bytes_from_image(img)


@app.post("/api/upload-image")
async def api_upload_image(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    content = await _read_upload_limited(file, _UPLOAD_IMAGE_MAX_BYTES, "Image")
    if not content:
        raise HTTPException(400, "Empty file")
    ext, content = _normalize_uploaded_image_content(file.filename or "", content)
    unique_name = f"{int(time.time()*1000)}_{random.randint(1000,9999)}{ext}"
    user_dir = _user_id(current_user) or "anonymous"
    date_dir = datetime.now().strftime("%Y-%m-%d")
    rel_name = f"{user_dir}/{date_dir}/{unique_name}"
    dest = os.path.join(COMFYUI_INPUT, user_dir, date_dir, unique_name)
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(500, "Image upload failed")
    return {"ok": True, "filename": rel_name, "path": dest}


@app.post("/api/upload-video")
async def api_upload_video(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    content = await _read_upload_limited(file, _UPLOAD_VIDEO_MAX_BYTES, "Video")
    if not content:
        raise HTTPException(400, "Empty file")
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _UPLOAD_ALLOWED_VIDEO_EXTS:
        raise HTTPException(400, f"Unsupported video format: {ext}")
    unique_name = f"{int(time.time()*1000)}_{random.randint(1000,9999)}{ext}"
    user_dir = _user_id(current_user) or "anonymous"
    date_dir = datetime.now().strftime("%Y-%m-%d")
    rel_name = f"{user_dir}/{date_dir}/{unique_name}"
    dest = os.path.join(COMFYUI_INPUT, user_dir, date_dir, unique_name)
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(500, "Video upload failed")
    return {"ok": True, "filename": rel_name, "path": dest}


@app.get("/api/input-image/{filename:path}")
def api_input_image(filename: str, current_user: dict = Depends(get_current_user)):
    safe = filename.replace("\\", "/").lstrip("/")
    path = _resolve_input_image_path(safe)
    if not path:
        raise HTTPException(404)
    ext = os.path.splitext(path)[1].lower()
    media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".bmp": "image/bmp"}.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=media)


@app.get("/api/input-video/{filename:path}")
def api_input_video(filename: str, current_user: dict = Depends(get_current_user)):
    safe = filename.replace("\\", "/").lstrip("/")
    path = _resolve_input_image_path(safe)
    if not path:
        raise HTTPException(404)
    ext = os.path.splitext(path)[1].lower()
    media = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".m4v": "video/x-m4v",
    }.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=media)


def _resolve_input_image_path(filename: str) -> str:
    safe = filename.replace("\\", "/").lstrip("/")
    input_root = os.path.abspath(COMFYUI_INPUT)
    path = os.path.abspath(os.path.join(input_root, safe))
    if os.path.commonpath([input_root, path]) != input_root:
        raise HTTPException(400, "Invalid image path")
    if os.path.isfile(path):
        return path
    return ""


# ── Workflow Metadata ─────────────────────────────────────────────────

def _load_wf_meta() -> dict:
    try:
        conn = _db_connect()
        rows = conn.execute("SELECT * FROM workflow_meta ORDER BY filename").fetchall()
        conn.close()
        result = {}
        for row in rows:
            entry = _workflow_meta_row_to_entry(row)
            if entry is not None:
                result[row["filename"]] = entry
        return result
    except Exception as e:
        add_log("warn", "wf_meta", f"Failed to load workflow_meta table: {e}")
        if os.path.isfile(WF_META_FILE):
            try:
                with open(WF_META_FILE) as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    return {k: _normalize_wf_meta_entry(k, v) for k, v in raw.items()}
            except Exception as json_err:
                add_log("warn", "wf_meta", f"Failed to load wf_meta.json fallback: {json_err}")
        return {}

def _save_wf_meta(meta: dict):
    normalized = {k: _normalize_wf_meta_entry(k, v) for k, v in meta.items()}
    conn = _db_connect()
    try:
        conn.execute("DELETE FROM workflow_meta")
        for filename, entry in normalized.items():
            _write_wf_meta_entry_to_db(filename, entry, conn=conn)
        conn.commit()
    finally:
        conn.close()
    with open(WF_META_FILE, "w") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)


def _load_wf_dirs() -> list[str]:
    if os.path.isfile(WF_DIRS_FILE):
        with open(WF_DIRS_FILE) as f:
            dirs = json.load(f)
        if isinstance(dirs, list) and dirs:
            return dirs
    dirs = [WORKFLOW_DIR]
    os.makedirs(os.path.dirname(WF_DIRS_FILE), exist_ok=True)
    with open(WF_DIRS_FILE, "w") as f:
        json.dump(dirs, f, indent=2)
    return dirs


def _save_wf_dirs(dirs: list[str]):
    os.makedirs(os.path.dirname(WF_DIRS_FILE), exist_ok=True)
    with open(WF_DIRS_FILE, "w") as f:
        json.dump(dirs, f, ensure_ascii=False, indent=2)


def _resolve_workflow(name: str, entry: dict | None = None) -> str | None:
    """Resolve a workflow file by filename, preferring the metadata-pinned source path.

    This avoids reading the wrong file when multiple workflow directories contain the
    same basename (for example local cache plus synced remote copies).
    """
    normalized = _normalize_wf_meta_entry(name, entry or _load_wf_meta().get(name, {}))
    source_path = str(normalized.get("source_path") or "").strip()
    if source_path:
        preferred = os.path.abspath(os.path.expanduser(source_path))
        if os.path.basename(preferred) == name and os.path.isfile(preferred):
            return preferred

    candidates = []
    for d in _get_workflow_dirs():
        p = os.path.join(d, name)
        if os.path.isfile(p):
            candidates.append(os.path.abspath(p))
        candidates.extend(
            os.path.abspath(m)
            for m in glob.glob(os.path.join(d, "**", name), recursive=True)
            if os.path.isfile(m)
        )
    if candidates:
        # Deterministic fallback for names without pinned metadata.
        return sorted(set(candidates))[0]
    return None


def _auto_detect_tags(workflow_path: str) -> list[str]:
    tags = []
    try:
        with open(workflow_path) as f:
            wf = json.load(f)
        has_image_input = False
        max_width = 0
        max_height = 0
        for nid, node in wf.items():
            if not isinstance(node, dict):
                continue
            cls = node.get("class_type", "")
            inputs = node.get("inputs", {})
            if cls in ("LoadImage", "LoadImageFromPath"):
                has_image_input = True
            if "image" in inputs and isinstance(inputs["image"], str) and inputs["image"].startswith("http"):
                has_image_input = True
            if "width" in inputs:
                try: max_width = max(max_width, int(inputs["width"]))
                except: pass
            if "height" in inputs:
                try: max_height = max(max_height, int(inputs["height"]))
                except: pass
        if has_image_input:
            tags.append("图生图")
        else:
            tags.append("文生图")
        max_dim = max(max_width, max_height)
        if max_dim >= 3840:
            tags.append("4K")
        elif max_dim >= 1920:
            tags.append("2K")
    except Exception:
        tags.append("文生图")
    return tags


@app.get("/api/workflows/meta")
def api_workflows_meta(current_user: dict | None = Depends(get_current_user_optional)):
    meta = _load_wf_meta()
    dirty = False
    seen = {}
    for d in _get_workflow_dirs():
        for f in glob.glob(os.path.join(d, "**", "*.json"), recursive=True):
            name = os.path.basename(f)
            if name not in seen:
                seen[name] = f
    result = {}
    for fname in sorted(seen):
        f = seen[fname]
        raw_entry = meta.get(fname, {})
        entry = _normalize_wf_meta_entry(fname, raw_entry)
        if fname not in meta:
            meta[fname] = entry
            dirty = True
        if "tags" not in raw_entry:
            entry["tags"] = _auto_detect_tags(f)
            meta[fname] = entry
            dirty = True
        if "name" not in raw_entry:
            entry["name"] = fname.replace(".json", "")
            meta[fname] = entry
            dirty = True
        if not _can_view_workflow(fname, entry, current_user):
            continue
        result[fname] = entry
    if dirty:
        _save_wf_meta(meta)
    return result


@app.post("/api/workflows/meta/sort")
def api_sort_wf_meta(body: dict, current_user: dict = Depends(get_current_user)):
    if not isinstance(body, dict):
        raise HTTPException(400, "Sort payload must be an object")
    meta = _load_wf_meta()
    seen = set()
    for d in _get_workflow_dirs():
        for f in glob.glob(os.path.join(d, "**", "*.json"), recursive=True):
            seen.add(os.path.basename(f))
    updates: list[tuple[str, int]] = []
    for filename, order in body.items():
        filename = os.path.basename(str(filename or ""))
        if not filename or filename not in seen:
            raise HTTPException(404, f"Workflow not found: {filename}")
        entry = _normalize_wf_meta_entry(filename, meta.get(filename, {}))
        if not _can_manage_workflow(filename, entry, current_user):
            raise HTTPException(403, f"No permission for workflow: {filename}")
        try:
            updates.append((filename, int(order)))
        except (TypeError, ValueError):
            raise HTTPException(400, f"Invalid sort order for workflow: {filename}")
    for filename, order in updates:
        entry = _normalize_wf_meta_entry(filename, meta.get(filename, {}))
        entry["sort_order"] = order
        meta[filename] = entry
        _write_wf_meta_entry_to_db(filename, entry)
    _export_wf_meta_json_from_db()
    return {"ok": True, "meta": api_workflows_meta(current_user)}


@app.put("/api/workflows/meta/{filename}")
def api_update_wf_meta(filename: str, body: dict, current_user: dict = Depends(get_current_user)):
    meta = _load_wf_meta()
    meta[filename] = _normalize_wf_meta_entry(filename, meta.get(filename, {}))
    if not _can_manage_workflow(filename, meta[filename], current_user):
        raise HTTPException(403, "No permission for this workflow")
    if "name" in body:
        meta[filename]["name"] = body["name"]
    if "tags" in body:
        meta[filename]["tags"] = body["tags"]
    if "shared" in body and not _is_admin_user(current_user):
        raise HTTPException(403, "Admin permission required to share workflows")
    if "shared" in body:
        meta[filename]["shared"] = bool(body["shared"])
        add_log(
            "info",
            "workflow",
            f"Workflow {filename} shared={meta[filename]['shared']} by {_user_id(current_user)}",
        )
    _write_wf_meta_entry_to_db(filename, meta[filename])
    _export_wf_meta_json_from_db()
    saved = _normalize_wf_meta_entry(filename, _load_wf_meta().get(filename, {}))
    return saved


@app.delete("/api/workflows/meta/{filename}")
def api_delete_wf_meta(filename: str, current_user: dict = Depends(get_current_user)):
    meta = _load_wf_meta()
    entry = _normalize_wf_meta_entry(filename, meta.get(filename, {}))
    if filename in meta and _can_manage_workflow(filename, entry, current_user):
        _delete_wf_meta_entry(filename)
        _export_wf_meta_json_from_db()
    elif filename in meta:
        raise HTTPException(403, "No permission for this workflow")
    return {"ok": True}


@app.post("/api/workflows/meta/thumbnail")
async def api_upload_wf_thumbnail(filename: str = Form(...), file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    ext = os.path.splitext(file.filename or "")[1].lower() or ".jpg"
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        raise HTTPException(400, f"Unsupported image format: {ext}")
    content = await _read_upload_limited(file, _UPLOAD_IMAGE_MAX_BYTES, "Thumbnail")
    if not content:
        raise HTTPException(400, "Empty file")
    meta = _load_wf_meta()
    meta[filename] = _normalize_wf_meta_entry(filename, meta.get(filename, {}))
    if not _can_manage_workflow(filename, meta[filename], current_user):
        raise HTTPException(403, "No permission for this workflow")
    thumb_path, rel_thumb = _workflow_thumbnail_path(filename, meta[filename], ext)
    os.makedirs(os.path.dirname(thumb_path), exist_ok=True)
    with open(thumb_path, "wb") as f:
        f.write(content)
    meta[filename]["thumbnail"] = rel_thumb
    _write_wf_meta_entry_to_db(filename, meta[filename])
    _export_wf_meta_json_from_db()
    return {"ok": True, "thumbnail": rel_thumb}


@app.get("/api/workflows/thumbnail/{name:path}")
def api_get_wf_thumbnail(name: str):
    path = _safe_rel_path(WORKFLOW_DIR, name)
    if not os.path.isfile(path):
        raise HTTPException(404)
    ext = os.path.splitext(path)[1].lower()
    media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".bmp": "image/bmp"}.get(ext, "application/octet-stream")
    return FileResponse(
        path,
        media_type=media,
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.put("/api/workflows/{filename}/rename")
def api_rename_workflow(filename: str, body: dict, current_user: dict = Depends(get_current_user)):
    meta = _load_wf_meta()
    meta[filename] = _normalize_wf_meta_entry(filename, meta.get(filename, {}))
    if not _can_manage_workflow(filename, meta[filename], current_user):
        raise HTTPException(403, "No permission for this workflow")
    meta[filename]["name"] = body.get("name", filename.replace(".json", ""))
    _write_wf_meta_entry_to_db(filename, meta[filename])
    _export_wf_meta_json_from_db()
    return meta[filename]


# ── Catch-all workflow delete (MUST be last) ─────────────────────────

@app.delete("/api/workflows/{name}")
def api_workflow_delete(name: str, current_user: dict = Depends(get_current_user)):
    meta = _load_wf_meta()
    entry = _normalize_wf_meta_entry(name, meta.get(name, {}))
    if not _can_manage_workflow(name, entry, current_user):
        raise HTTPException(403, "No permission for this workflow")
    path = _resolve_workflow(name, entry)
    if not path:
        raise HTTPException(404)
    os.remove(path)
    if name in meta:
        _delete_wf_meta_entry(name)
        _export_wf_meta_json_from_db()
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════
#  API: Generation
# ══════════════════════════════════════════════════════════════════════════

@app.post("/api/prompt/optimize")
def api_prompt_optimize(req: PromptOptimizeRequest, current_user: dict = Depends(get_current_user)):
    prompt = str(req.prompt or "").strip()
    if not prompt:
        raise HTTPException(400, "Prompt is required")
    prompt_mode = "video_script" if str(req.mode or "").lower() in {"video", "video_script", "script"} else "image"
    action_label = "视频脚本优化" if prompt_mode == "video_script" else "提示词优化"
    try:
        result = run_llm_prompt_optimizer(
            prompt,
            timeout=300,
            max_new_tokens=req.max_new_tokens,
            prompt_mode=prompt_mode,
            prompt_context=req.prompt_context if prompt_mode == "video_script" else {},
        )
    except TimeoutError as e:
        add_log("error", "prompt_optimize", str(e), details=f"user={_user_id(current_user)}")
        raise HTTPException(504, f"{action_label}超时: {e}") from e
    except RuntimeError as e:
        add_log("error", "prompt_optimize", str(e), details=f"user={_user_id(current_user)}")
        raise HTTPException(500, f"{action_label}失败: {e}") from e
    except Exception as e:
        add_log("error", "prompt_optimize", str(e), details=f"user={_user_id(current_user)}")
        raise HTTPException(500, f"{action_label}失败: {e}") from e
    result["instance"] = "LLM"
    add_log("info", "prompt_optimize", f"{action_label} by {result.get('provider', 'unknown')}", details=f"user={_user_id(current_user)}")
    return result


@app.post("/api/prompt/translate")
def api_prompt_translate(req: PromptTranslateRequest, current_user: dict = Depends(get_current_user)):
    prompt = str(req.prompt or "").strip()
    if not prompt:
        raise HTTPException(400, "Prompt is required")
    target = str(req.target_language or "").strip().lower()
    if target not in ("zh", "en"):
        target = "en" if re.search(r"[\u4e00-\u9fff]", prompt) else "zh"
    cached = _prompt_translate_cache_get(prompt, target)
    if cached:
        add_log("info", "prompt_translate", f"Prompt translation cache hit to {target}", details=f"user={_user_id(current_user)}")
        return cached
    try:
        result = run_llm_prompt_language_switcher(
            prompt,
            target,
            timeout=180,
            max_new_tokens=req.max_new_tokens,
        )
    except TimeoutError as e:
        add_log("error", "prompt_translate", str(e), details=f"user={_user_id(current_user)}")
        raise HTTPException(504, f"提示词翻译超时: {e}") from e
    except RuntimeError as e:
        add_log("error", "prompt_translate", str(e), details=f"user={_user_id(current_user)}")
        raise HTTPException(500, f"提示词翻译失败: {e}") from e
    except Exception as e:
        add_log("error", "prompt_translate", str(e), details=f"user={_user_id(current_user)}")
        raise HTTPException(500, f"提示词翻译失败: {e}") from e
    result["instance"] = "LLM"
    result["cached"] = False
    if _is_json_object_text(result.get("translated_prompt", "")):
        result["format"] = "json"
    _prompt_translate_cache_put(prompt, target, result)
    add_log("info", "prompt_translate", f"Prompt translated to {result.get('target_language', target)}", details=f"user={_user_id(current_user)}")
    return result


@app.post("/api/prompt/interrogate")
def api_prompt_interrogate(req: PromptInterrogateRequest, current_user: dict = Depends(get_current_user)):
    image = str(req.image or "").replace("\\", "/").lstrip("/")
    if not image:
        raise HTTPException(400, "Image is required")
    resolved_image_path = _resolve_input_image_path(image)
    if not resolved_image_path:
        raise HTTPException(404, "Image not found")
    prepared_image = prepare_interrogate_image(image, COMFYUI_INPUT)
    image_for_interrogate = prepared_image.get("filename") or image
    prepared_image_path = _resolve_input_image_path(image_for_interrogate) or resolved_image_path
    prompt_mode = "video_script" if str(req.mode or "").lower() in {"video", "video_script", "script"} else "image"
    try:
        reverse_level = int(req.level) if req.level is not None else (2 if req.expert_team else (1 if req.expert else 0))
    except (TypeError, ValueError):
        reverse_level = 0
    reverse_level = max(0, min(2, reverse_level))
    expert_mode = reverse_level > 0 and prompt_mode == "image"
    started_at = time.monotonic()

    def _attach_interrogate_timing(result: dict) -> dict:
        if isinstance(result, dict):
            result["interrogate_elapsed_seconds"] = round(max(0.0, time.monotonic() - started_at), 3)
        return result

    def _apply_video_script_interrogate(result: dict) -> dict:
        if prompt_mode != "video_script":
            return result
        source_prompt = str(result.get("prompt_zh") or result.get("prompt") or result.get("promptgen") or "").strip()
        if not source_prompt:
            return result
        try:
            optimized = run_llm_prompt_optimizer(
                source_prompt,
                timeout=180,
                max_new_tokens=768,
                prompt_mode="video_script",
                prompt_context=req.prompt_context or {},
            )
        except Exception as video_error:
            add_log("warn", "prompt_interrogate", f"Video script optimization skipped: {video_error}", details=f"user={_user_id(current_user)}")
            return result
        script = str(optimized.get("optimized_prompt") or optimized.get("cleaned_prompt") or "").strip()
        if not script:
            return result
        result["image_prompt"] = result.get("prompt") or source_prompt
        if result.get("prompt_zh"):
            result["image_prompt_zh"] = result.get("prompt_zh")
        result["prompt"] = script
        result["prompt_zh"] = script
        result["prompt_mode"] = "video_script"
        result["video_script_provider"] = optimized.get("provider", "")
        if optimized.get("cleaned_prompt"):
            result["video_script_source_prompt"] = optimized.get("cleaned_prompt")
        return result

    if expert_mode:
        try:
            team_mode = reverse_level >= 2
            result = run_llm_expert_image_interrogator(
                prepared_image_path,
                timeout=None,
                max_new_tokens=6144 if team_mode else 4096,
                single_pass=True,
                review_enabled=team_mode,
                expert_team=team_mode,
                include_quality=True,
            )
            result = _consume_reverse_prompt_quality(result, current_user)
            result = _attach_interrogate_timing(result)
            result["image_preprocess"] = prepared_image
            result["instance"] = "LLM"
            result["source_image"] = image
            result["reverse_level"] = reverse_level
            result["reverse_mode"] = "expert" if team_mode else "advanced"
            result["reverse_mode_label"] = "专家" if team_mode else "加强"
            add_log("info", "prompt_interrogate", f"Expert image interrogated by {result.get('provider', 'unknown')}", details=f"user={_user_id(current_user)} elapsed={result.get('interrogate_elapsed_seconds')}")
            return result
        except TimeoutError as e:
            add_log("error", "prompt_interrogate", str(e), details=f"user={_user_id(current_user)}")
            raise HTTPException(504, f"{'专家' if team_mode else '加强'}图片反推超时: {e}") from e
        except LLMVisionUnsupportedError as e:
            add_log("error", "prompt_interrogate", str(e), details=f"user={_user_id(current_user)}")
            raise HTTPException(503, f"{'专家' if team_mode else '加强'}图片反推失败: {e}") from e
        except Exception as e:
            add_log("error", "prompt_interrogate", str(e), details=f"user={_user_id(current_user)}")
            raise HTTPException(500, f"{'专家' if team_mode else '加强'}图片反推失败: {e}") from e

    try:
        result = run_llm_image_interrogator(
            prepared_image_path,
            timeout=None,
            max_new_tokens=1024,
            compact=True,
            include_quality=True,
        )
        result = _consume_reverse_prompt_quality(result, current_user)
        result = _apply_video_script_interrogate(result)
        result = _attach_interrogate_timing(result)
        result["image_preprocess"] = prepared_image
        result["instance"] = "LLM"
        result["source_image"] = image
        add_log("info", "prompt_interrogate", f"Image interrogated by {result.get('provider', 'unknown')}", details=f"user={_user_id(current_user)} elapsed={result.get('interrogate_elapsed_seconds')}")
        return result
    except LLMVisionUnsupportedError as llm_error:
        add_log("error", "prompt_interrogate", str(llm_error), details=f"user={_user_id(current_user)}")
        raise HTTPException(503, f"图片反推失败: {llm_error}") from llm_error
    except Exception as llm_error:
        add_log("error", "prompt_interrogate", str(llm_error), details=f"user={_user_id(current_user)}")
        raise HTTPException(500, f"图片反推失败: {llm_error}") from llm_error


@app.post("/api/generate")
def api_generate(req: GenerateRequest, bg: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    meta = _load_wf_meta()
    entry = _normalize_wf_meta_entry(req.workflow, meta.get(req.workflow, {}))
    if not _can_view_workflow(req.workflow, entry, current_user):
        raise HTTPException(403, "No permission for this workflow")
    path = _resolve_workflow(req.workflow, entry)
    if not path:
        raise HTTPException(404, "Workflow not found")

    user_id = current_user.get("sub", "")
    job_id = f"job_{int(time.time()*1000)}_{random.randint(1000,9999)}"
    random_seed_requested = req.seed is None
    seed = req.seed if req.seed is not None else random.randint(0, 2**63)
    vllm_was = False

    try:
        with open(path) as f:
            wf_check = json.load(f)
        normalized_fields = _normalize_workflow_field_values(wf_check, req.fields)
        if random_seed_requested:
            _apply_generated_seed_to_seed_fields(wf_check, normalized_fields, seed)
        for key, val in normalized_fields.items():
            if "::" not in key:
                continue
            nid, field = key.split("::", 1)
            if nid in wf_check and "inputs" in wf_check[nid]:
                wf_check[nid]["inputs"][field] = val
        for nid, v in wf_check.items():
            if isinstance(v, dict) and v.get("class_type") == "KSampler":
                if "seed" in v.get("inputs", {}):
                    v["inputs"]["seed"] = seed
        issues = validate_api_prompt(wf_check)
        if issues:
            detail = describe_api_prompt_issues(issues)
            add_log("error", "workflow", detail)
            raise HTTPException(400, detail)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"工作流校验失败: {e}") from e

    workflow_type = _workflow_primary_type(req.workflow)
    prompt_preview = infer_generation_label(req.workflow, normalized_fields, workflow_type)[:200]
    now_ts = time.time()
    jobs[job_id] = {
        "id": job_id, "status": "queued", "message": "排队中...",
        "workflow": req.workflow, "seed": str(seed),
        "workflow_type": workflow_type,
        "prompt_preview": prompt_preview,
        "width": req.width, "height": req.height,
        "fields": normalized_fields,
        "preferred_instance": req.preferred_instance or "",
        "preferred_node_id": req.preferred_node_id or "",
        "queued_at": datetime.now().strftime("%H:%M:%S"),
        "created_at_ts": now_ts,
        "last_update": now_ts,
        "user_id": user_id,
    }
    jobs[job_id].update({
        k: v for k, v in _job_with_time_estimate(jobs[job_id]).items()
        if k.startswith("estimated_")
    })
    add_log("info", "queue", f"Job queued: {req.workflow}", job_id)
    save_jobs()

    _job_queue.put_nowait((
        job_id, path, normalized_fields, seed, vllm_was, req.width, req.height, user_id,
        req.preferred_instance or "", req.preferred_node_id or ""
    ))
    return {"job_id": job_id, "seed": seed}


@app.get("/api/jobs")
def api_all_jobs(current_user: dict = Depends(get_current_user)):
    snapshot = list(jobs.values())
    return [_job_with_time_estimate(j) for j in snapshot if _can_access_job(j, current_user)]


@app.get("/api/jobs/{job_id}")
def api_job_status(job_id: str, current_user: dict = Depends(get_current_user)):
    if job_id not in jobs:
        raise HTTPException(404)
    if not _can_access_job(jobs[job_id], current_user):
        raise HTTPException(403, "无权访问他人的任务")
    return _job_with_time_estimate(jobs[job_id])


@app.delete("/api/jobs/{job_id}")
async def api_cancel_job(job_id: str, current_user: dict = Depends(get_current_user)):
    if job_id not in jobs:
        raise HTTPException(404)
    job = jobs[job_id]
    if not _can_access_job(job, current_user):
        raise HTTPException(403, "只能取消自己的任务")
    prompt_id = str(job.get("prompt_id") or "")
    inst_url = None
    inst_name = str(job.get("instance") or "")
    if prompt_id:
        _mark_remote_prompt_cancelled(inst_name, prompt_id)
    if prompt_id or job.get("status") == "generating":
        try:
            for inst in _get_enabled_instances():
                if inst.get("name") == inst_name:
                    inst_url = inst.get("url")
                    break
            if prompt_id:
                comfyui_post("/queue", {"delete": [prompt_id]}, base_url=inst_url)
        except Exception:
            pass
        try:
            comfyui_post("/interrupt", {}, base_url=inst_url)
        except Exception:
            pass
    task = _job_tasks.get(job_id)
    if task and not task.done():
        task.cancel()
    _job_tasks.pop(job_id, None)
    job["cancelled"] = True
    job["status"] = "cancelled"
    job["message"] = "任务已取消"
    job["last_update"] = time.time()
    job["sem_acquired"] = False
    removed_job = dict(job)
    jobs.pop(job_id, None)
    save_jobs()
    _kick_queued_generation_jobs("取消后")
    removed_job["deleted"] = True
    await broadcast({"type": "job_update", "job": removed_job})
    return {"ok": True}


@app.delete("/api/jobs/{job_id}/dismiss")
def api_dismiss_job(job_id: str, current_user: dict = Depends(get_current_user)):
    if job_id not in jobs:
        raise HTTPException(404)
    job = jobs[job_id]
    if not _can_access_job(job, current_user):
        raise HTTPException(403, "只能删除自己的任务")
    if job.get("status") not in ("error", "retrying"):
        raise HTTPException(400, "只能丢弃失败或重试中的任务")
    del jobs[job_id]
    save_jobs()
    return {"ok": True}


@app.post("/api/jobs/{job_id}/retry")
def api_retry_job(job_id: str, bg: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    if job_id not in jobs:
        raise HTTPException(404)
    old = jobs[job_id]
    if old["status"] not in ("error",):
        raise HTTPException(400, "只能重试失败的任务")

    user_id = current_user.get("sub", "")
    if old.get("user_id") != user_id:
        raise HTTPException(403, "只能重试自己的任务")

    wf = old.get("workflow", "")
    fields = old.get("fields", {})
    seed = random.randint(0, 2**63)
    width = old.get("width", 0)
    height = old.get("height", 0)
    preferred_instance = old.get("preferred_instance", "")
    preferred_node_id = old.get("preferred_node_id", "")

    meta = _load_wf_meta()
    entry = _normalize_wf_meta_entry(wf, meta.get(wf, {}))
    if not _can_view_workflow(wf, entry, current_user):
        raise HTTPException(403, "No permission for this workflow")
    path = _resolve_workflow(wf, entry)
    if not path:
        raise HTTPException(404, "Workflow not found")
    try:
        with open(path) as f:
            wf_check = json.load(f)
        fields = _normalize_workflow_field_values(wf_check, fields)
        _apply_generated_seed_to_seed_fields(wf_check, fields, seed)
    except Exception:
        pass

    new_id = f"job_{int(time.time()*1000)}_{random.randint(1000,9999)}"
    vllm_was = False

    prompt_preview = infer_generation_label(wf, fields, _workflow_primary_type(wf))[:200]

    jobs[new_id] = {
        "id": new_id, "status": "queued", "message": "排队中...",
        "workflow": wf, "seed": str(seed),
        "workflow_type": _workflow_primary_type(wf),
        "prompt_preview": prompt_preview,
        "user_id": user_id,
        "width": width, "height": height,
        "fields": fields,
        "preferred_instance": preferred_instance,
        "preferred_node_id": preferred_node_id,
        "retry_of": job_id,
        "queued_at": datetime.now().strftime("%H:%M:%S"),
        "created_at_ts": time.time(),
    }
    jobs[new_id].update({
        k: v for k, v in _job_with_time_estimate(jobs[new_id]).items()
        if k.startswith("estimated_")
    })
    jobs.pop(job_id, None)
    save_jobs()

    _job_queue.put_nowait((
        new_id, path, fields, seed, vllm_was, width, height, user_id,
        preferred_instance, preferred_node_id
    ))
    return {"job_id": new_id, "seed": seed, "dismissed_job_id": job_id}


# ══════════════════════════════════════════════════════════════════════════
#  API: History
# ══════════════════════════════════════════════════════════════════════════

def _history_where_params(scope: str, status: str, current_user: dict | None) -> tuple[str, list]:
    uid = _user_id(current_user or {})
    trash_mode = scope == "trash"
    hidden_mode = scope == "hidden"
    if trash_mode and not current_user:
        raise HTTPException(401, "Not authenticated")
    if hidden_mode and not current_user:
        raise HTTPException(401, "Not authenticated")
    if current_user and (trash_mode or hidden_mode) and current_user.get("role") == "admin":
        conditions = []
        params = []
    elif current_user and (trash_mode or hidden_mode):
        conditions = ["user_id = ?"]
        params = [uid]
    elif current_user and scope == "mine":
        conditions = ["user_id = ?"]
        params = [uid]
    elif current_user and current_user.get("role") == "admin":
        conditions = [] if scope == "all" else ["(user_id = ? OR is_public = 1)"]
        params = [] if scope == "all" else [uid]
    elif current_user:
        if scope == "mine":
            conditions = ["user_id = ?"]
            params = [uid]
        else:
            conditions = ["(user_id = ? OR is_public = 1)"]
            params = [uid]
    else:
        conditions = ["is_public = 1"]
        params = []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if trash_mode:
        conditions.append("COALESCE(deleted_at, '') != ''")
    else:
        conditions.append("COALESCE(deleted_at, '') = ''")
        if hidden_mode:
            conditions.append("COALESCE(is_hidden, 0) = 1")
        else:
            conditions.append("COALESCE(is_hidden, 0) = 0")
        conditions.append("COALESCE(protection_status, 'safe') != ?")
        params.append(IMAGE_PROTECTION_PENDING)
    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    return where_clause, params


def _history_signature(rows: list[dict], total: int) -> str:
    parts = [f"total:{int(total or 0)}"]
    for row in rows:
        parts.append(":".join([
            str(row.get("id", "")),
            str(row.get("image_path", "")),
            str(row.get("thumb_path", "")),
            "1" if row.get("is_public") else "0",
            "1" if row.get("is_hidden") else "0",
            str(row.get("hidden_at", "") or ""),
            str(row.get("deleted_at", "") or ""),
            str(row.get("protection_status", "") or ""),
            str(row.get("protection_score", "") or ""),
            str(row.get("protection_source", "") or ""),
            str(row.get("protection_checked_at", "") or ""),
            str(row.get("history_rowid", "") or ""),
        ]))
    return "|".join(parts)


@app.get("/api/history/summary")
def api_history_summary(limit: int = 80, offset: int = 0, status: str = "", scope: str = "gallery", current_user: dict | None = Depends(get_current_user_optional)):
    """Lightweight history signature for polling; does not touch media files."""
    safe_limit = max(1, min(int(limit or 80), 5000))
    safe_offset = max(0, int(offset or 0))
    conn = sqlite3.connect(GEN_DB)
    conn.row_factory = sqlite3.Row
    where_clause, params = _history_where_params(scope, status, current_user)
    rows = [
        dict(r) for r in conn.execute(
            "SELECT id, image_path, thumb_path, is_public, is_hidden, hidden_at, deleted_at, protection_status, "
            "protection_score, protection_source, protection_checked_at, generations.rowid AS history_rowid "
            "FROM generations" +
            where_clause +
            " ORDER BY datetime(created_at) DESC, history_rowid DESC LIMIT ? OFFSET ?",
            params + [safe_limit, safe_offset],
        ).fetchall()
    ]
    total = conn.execute(
        "SELECT COUNT(*) FROM generations" + where_clause,
        params,
    ).fetchone()[0]
    conn.close()
    return {"ok": True, "total": total, "count": len(rows), "signature": _history_signature(rows, total)}


@app.get("/api/workflows/previews")
def api_workflow_previews(current_user: dict | None = Depends(get_current_user_optional)):
    """Return the latest preview per workflow for the current user using lightweight DB rows."""
    conn = sqlite3.connect(GEN_DB)
    conn.row_factory = sqlite3.Row
    if current_user:
        conditions = ["user_id = ?"]
        params = [_user_id(current_user)]
    else:
        conditions = ["is_public = 1"]
        params = []
    conditions.extend([
        "COALESCE(deleted_at, '') = ''",
        "COALESCE(is_hidden, 0) = 0",
        "COALESCE(protection_status, 'safe') != ?",
    ])
    params.append(IMAGE_PROTECTION_PENDING)
    where_clause = " WHERE " + " AND ".join(conditions)
    rows = [
        dict(r) for r in conn.execute(
            "SELECT generations.*, generations.rowid AS history_rowid FROM generations" +
            where_clause +
            " ORDER BY datetime(created_at) DESC, history_rowid DESC",
            params,
        ).fetchall()
    ]
    conn.close()
    counts: dict[str, int] = {}
    latest: dict[str, dict] = {}
    for row in rows:
        workflow = row.get("workflow", "") or ""
        if not workflow:
            continue
        counts[workflow] = counts.get(workflow, 0) + 1
        if workflow not in latest and (row.get("thumb_path") or row.get("image_path")):
            record = _gen_db_to_record(row)
            record["workflow_count"] = counts[workflow]
            latest[workflow] = record
    for workflow, record in latest.items():
        record["workflow_count"] = counts.get(workflow, 0)
    return {"ok": True, "data": list(latest.values()), "counts": counts}


@app.get("/api/history")
def api_history(limit: int = 50, offset: int = 0, status: str = "", scope: str = "gallery", compact: bool = False, current_user: dict | None = Depends(get_current_user_optional)):
    """Query generation history from SQLite with pagination."""
    safe_limit = max(1, min(int(limit or 50), 5000))
    safe_offset = max(0, int(offset or 0))
    compact_mode = bool(compact)
    conn = sqlite3.connect(GEN_DB)
    conn.row_factory = sqlite3.Row
    where_clause, params = _history_where_params(scope, status, current_user)
    rows = [
        dict(r) for r in conn.execute(
            "SELECT generations.*, generations.rowid AS history_rowid FROM generations" +
            where_clause +
            " ORDER BY datetime(created_at) DESC, history_rowid DESC LIMIT ? OFFSET ?",
            params + [safe_limit, safe_offset],
        ).fetchall()
    ]
    thumb_updates = []
    dimension_updates = []
    if not compact_mode:
        for row in rows:
            if not row.get("image_path"):
                continue
            if not row.get("thumb_path"):
                thumb = make_thumbnail(row.get("image_path", "")) or ""
                if thumb:
                    row["thumb_path"] = thumb
                    thumb_updates.append((thumb, row.get("id", "")))
            media_type = str(row.get("media_type", "") or output_media_type(row.get("image_path", ""))).lower()
            if media_type == "video":
                w, h = get_video_size(row.get("image_path", ""))
                if w and h and (row.get("width") != w or row.get("height") != h):
                    row["width"] = w
                    row["height"] = h
                    dimension_updates.append((w, h, row.get("id", "")))
            if not row.get("width") or not row.get("height"):
                w, h = get_media_size(row.get("image_path", ""), media_type, row.get("thumb_path", ""))
                if w and h:
                    row["width"] = w
                    row["height"] = h
                    dimension_updates.append((w, h, row.get("id", "")))
    if thumb_updates:
        conn.executemany("UPDATE generations SET thumb_path=? WHERE id=?", thumb_updates)
    if dimension_updates:
        conn.executemany("UPDATE generations SET width=?, height=? WHERE id=?", dimension_updates)
    if thumb_updates or dimension_updates:
        conn.commit()
    total = conn.execute(
        "SELECT COUNT(*) FROM generations" + where_clause,
        params,
    ).fetchone()[0]
    conn.close()
    usernames = _history_username_map([r.get("user_id", "") for r in rows])
    for row in rows:
        row["username"] = usernames.get(row.get("user_id", ""), "")
    return {"ok": True, "data": [_gen_db_to_record(r, compact=compact_mode) for r in rows], "total": total}


@app.post("/api/history")
def api_history_create(req: dict, current_user: dict = Depends(get_current_user)):
    """Insert a generation record into SQLite."""
    elapsed = req.get("duration_sec", req.get("elapsed", 0))
    _insert_generation(req, elapsed, user_id=_user_id(current_user))
    return {"ok": True}


@app.get("/api/history/user-counts")
def api_history_user_counts(current_user: dict = Depends(require_admin)):
    """Return lightweight visible generation counts grouped by user."""
    conn = sqlite3.connect(GEN_DB)
    where_clause, params = _history_where_params("all", "", current_user)
    rows = conn.execute(
        "SELECT user_id, COUNT(*) FROM generations" + where_clause + " GROUP BY user_id",
        params,
    ).fetchall()
    conn.close()
    return {"ok": True, "counts": {str(uid or ""): int(count or 0) for uid, count in rows if uid}}


def _history_detail_visible(row: dict, current_user: dict | None) -> bool:
    uid = _user_id(current_user or {})
    is_owner = bool(uid and row.get("user_id") == uid)
    is_admin = _is_admin_user(current_user)
    is_deleted = bool(row.get("deleted_at"))
    is_hidden = bool(row.get("is_hidden"))
    if str(row.get("protection_status") or IMAGE_PROTECTION_SAFE) == IMAGE_PROTECTION_PENDING:
        return is_owner or is_admin
    if is_deleted:
        return is_owner or is_admin
    if is_hidden and not (is_owner or is_admin):
        return False
    if is_owner or is_admin:
        return True
    return bool(row.get("is_public"))


@app.get("/api/history/{item_id}")
def api_history_detail(item_id: str, current_user: dict | None = Depends(get_current_user_optional)):
    """Return a single full history record for reuse/lightbox details."""
    conn = sqlite3.connect(GEN_DB)
    conn.row_factory = sqlite3.Row
    row_obj = conn.execute(
        "SELECT generations.*, generations.rowid AS history_rowid FROM generations WHERE id=?",
        (item_id,),
    ).fetchone()
    if not row_obj:
        conn.close()
        raise HTTPException(404, "Record not found")
    row = dict(row_obj)
    if not _history_detail_visible(row, current_user):
        conn.close()
        raise HTTPException(403, "无权查看该记录")
    row["username"] = _history_username_map([row.get("user_id", "")]).get(row.get("user_id", ""), "")
    conn.close()
    return {"ok": True, "data": _gen_db_to_record(row, compact=False)}


@app.delete("/api/history/{item_id}")
def api_history_delete(item_id: str, current_user: dict = Depends(get_current_user)):
    """Soft-delete a generation record while keeping image files untouched."""
    conn = sqlite3.connect(GEN_DB)
    conn.row_factory = sqlite3.Row
    _history_owner_check(conn, item_id, current_user, allow_deleted=True)
    deleted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE generations SET deleted_at=?, deleted_by=? WHERE id=?",
        (deleted_at, current_user.get("sub", ""), item_id),
    )
    conn.commit()
    conn.close()
    global history
    item = next((h for h in history if h["id"] == item_id), None)
    if item:
        item["is_deleted"] = True
        item["deleted_at"] = deleted_at
        item["deleted_by"] = current_user.get("sub", "")
        save_history()
    return {"ok": True, "deleted": True, "deleted_at": deleted_at}


@app.post("/api/history/{item_id}/video-frame")
def api_history_video_frame(item_id: str, body: dict, current_user: dict = Depends(get_current_user)):
    """Extract a video frame for preview reuse, card cover, or workflow import."""
    conn = sqlite3.connect(GEN_DB)
    conn.row_factory = sqlite3.Row
    try:
        row = _history_owner_check(conn, item_id, current_user)
        video_rel = row["image_path"]
        prompt = row["prompt"] or ""
    finally:
        conn.close()
    media_type = output_media_type(video_rel)
    if media_type != "video":
        raise HTTPException(400, "History item is not a video")
    time_sec = body.get("time", 0) if isinstance(body, dict) else 0
    set_cover = bool(body.get("set_cover")) if isinstance(body, dict) else False
    import_input = bool(body.get("import_input")) if isinstance(body, dict) else False
    data = _extract_history_video_frame(
        video_rel,
        item_id,
        time_sec,
        current_user,
        copy_to_input=import_input,
    )
    if set_cover:
        _update_generation_thumb(item_id, data["frame"])
        protection = _scan_generation_cover_thumb(item_id, data["frame"], prompt)
        data["thumb"] = data["frame"]
        data.update({
            "protection_status": protection.status,
            "protection_score": protection.score,
            "protection_reason": protection.reason,
            "protection_source": protection.source,
            "protection_checked_at": getattr(protection, "checked_at", ""),
        })
    return data


def _history_owner_check(conn, item_id: str, current_user: dict, allow_deleted: bool = False):
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT id, image_path, thumb_path, media_type, user_id, deleted_at, is_hidden, hidden_at, params, prompt FROM generations WHERE id=?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Record not found")
    if current_user.get("role") != "admin" and row["user_id"] != current_user.get("sub"):
        raise HTTPException(403, "无权操作他人的记录")
    if not allow_deleted and row["deleted_at"]:
        raise HTTPException(404, "Record deleted")
    return row


def _history_row_value(row, key: str, default=""):
    if not row:
        return default
    try:
        if key in row.keys():
            return row[key]
    except AttributeError:
        if isinstance(row, dict):
            return row.get(key, default)
    return default


def _history_input_image_refs(row) -> set[str]:
    params = _history_row_value(row, "params", "")
    if isinstance(params, str):
        params = _json_loads_safe(params, {})
    if not isinstance(params, dict):
        return set()
    refs: set[str] = set()
    media_exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".mp4", ".webm", ".mov", ".m4v")
    for key, value in params.items():
        if not isinstance(value, str):
            continue
        field = str(key).split("::", 1)[-1].lower()
        if not (field.startswith("image") or field == "upload"):
            continue
        rel = value.replace("\\", "/").lstrip("/")
        if rel.lower().endswith(media_exts):
            refs.add(rel)
    return refs


def _history_input_ref_path(rel_path: str, user_id: str) -> str:
    safe = (rel_path or "").replace("\\", "/").lstrip("/")
    if not safe:
        return ""
    parts = safe.split("/")
    owner = user_id or "anonymous"
    if len(parts) < 3 or parts[0] != owner or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[1]):
        return ""
    root = os.path.abspath(COMFYUI_INPUT)
    path = os.path.abspath(os.path.join(root, safe))
    if os.path.commonpath([root, path]) != root:
        raise HTTPException(400, "Invalid image path")
    return path


def _history_input_ref_in_use(conn, rel_path: str, item_id: str, excluding_ids: set[str] | None = None) -> bool:
    if not conn or not rel_path:
        return False
    target = rel_path.replace("\\", "/").lstrip("/")
    excluded = {str(item_id)}
    if excluding_ids:
        excluded.update(str(x) for x in excluding_ids)
    rows = conn.execute("SELECT id, params FROM generations").fetchall()
    for other in rows:
        if str(_history_row_value(other, "id", "")) in excluded:
            continue
        if target in _history_input_image_refs(other):
            return True
    return False


def _delete_history_files(row, conn=None, excluding_ids: set[str] | None = None) -> None:
    image_path = _history_row_value(row, "image_path", "")
    thumb_path = _history_row_value(row, "thumb_path", "")
    item_id = _history_row_value(row, "id", "")
    user_id = _history_row_value(row, "user_id", "")
    candidates = []
    if image_path:
        candidates.append(_safe_rel_path(OUTPUT_DIR, image_path))
        thumb_guess = image_path.rsplit(".", 1)[0] + "_thumb.jpg"
        candidates.append(_safe_rel_path(OUTPUT_DIR, thumb_guess))
    if thumb_path:
        candidates.append(_safe_rel_path(OUTPUT_DIR, thumb_path))
    for rel in _history_input_image_refs(row):
        if _history_input_ref_in_use(conn, rel, item_id, excluding_ids):
            continue
        candidates.append(_history_input_ref_path(rel, user_id))
    seen = set()
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        if os.path.isfile(path):
            os.remove(path)


def _purge_history_record(conn, item_id: str, current_user: dict) -> bool:
    row = _history_owner_check(conn, item_id, current_user, allow_deleted=True)
    _delete_history_files(row, conn)
    conn.execute("DELETE FROM generations WHERE id=?", (item_id,))
    global history
    history = [h for h in history if h.get("id") != item_id]
    return True


@app.post("/api/history/{item_id}/restore")
def api_history_restore(item_id: str, current_user: dict = Depends(get_current_user)):
    """Restore a soft-deleted generation record."""
    conn = sqlite3.connect(GEN_DB)
    conn.row_factory = sqlite3.Row
    _history_owner_check(conn, item_id, current_user, allow_deleted=True)
    conn.execute("UPDATE generations SET deleted_at='', deleted_by='' WHERE id=?", (item_id,))
    conn.commit()
    conn.close()
    item = next((h for h in history if h.get("id") == item_id), None)
    if item:
        item["is_deleted"] = False
        item["deleted_at"] = ""
        item["deleted_by"] = ""
        save_history()
    return {"ok": True, "restored": True}


@app.post("/api/history/{item_id}/permanent-delete")
def api_history_permanent_delete(item_id: str, current_user: dict = Depends(get_current_user)):
    """Permanently delete a generation record and its files."""
    conn = sqlite3.connect(GEN_DB)
    conn.row_factory = sqlite3.Row
    _purge_history_record(conn, item_id, current_user)
    conn.commit()
    conn.close()
    save_history()
    return {"ok": True, "deleted": True}


@app.post("/api/history/batch-restore")
def api_history_batch_restore(body: dict, current_user: dict = Depends(get_current_user)):
    ids = [str(x) for x in body.get("ids", []) if str(x)]
    if not ids:
        raise HTTPException(400, "ids required")
    restored = 0
    for item_id in ids:
        try:
            api_history_restore(item_id, current_user)
            restored += 1
        except HTTPException as e:
            if e.status_code in (403, 404):
                continue
            raise
    return {"ok": True, "restored": restored}


@app.post("/api/history/batch-permanent-delete")
def api_history_batch_permanent_delete(body: dict, current_user: dict = Depends(get_current_user)):
    ids = [str(x) for x in body.get("ids", []) if str(x)]
    if not ids:
        raise HTTPException(400, "ids required")
    conn = sqlite3.connect(GEN_DB)
    conn.row_factory = sqlite3.Row
    deleted = 0
    for item_id in ids:
        try:
            _purge_history_record(conn, item_id, current_user)
            deleted += 1
        except HTTPException as e:
            if e.status_code in (403, 404):
                continue
            raise
    conn.commit()
    conn.close()
    save_history()
    return {"ok": True, "deleted": deleted}


@app.post("/api/history/trash/clear")
def api_history_clear_trash(current_user: dict = Depends(get_current_user)):
    """Permanently delete every deleted record the current user can manage."""
    conn = sqlite3.connect(GEN_DB)
    conn.row_factory = sqlite3.Row
    if current_user.get("role") == "admin":
        rows = conn.execute("SELECT id, image_path, thumb_path, user_id, deleted_at, params FROM generations WHERE COALESCE(deleted_at, '') != ''").fetchall()
    else:
        rows = conn.execute(
            "SELECT id, image_path, thumb_path, user_id, deleted_at, params FROM generations WHERE user_id=? AND COALESCE(deleted_at, '') != ''",
            (current_user.get("sub", ""),),
        ).fetchall()
    deleted_ids = [row["id"] for row in rows]
    for row in rows:
        _delete_history_files(row, conn, set(deleted_ids))
    if deleted_ids:
        placeholders = ",".join("?" for _ in deleted_ids)
        conn.execute(f"DELETE FROM generations WHERE id IN ({placeholders})", deleted_ids)
    conn.commit()
    conn.close()
    if deleted_ids:
        global history
        deleted_set = set(deleted_ids)
        history = [h for h in history if h.get("id") not in deleted_set]
        save_history()
    return {"ok": True, "deleted": len(deleted_ids)}


@app.post("/api/history/{item_id}/share")
def api_history_share(item_id: str, body: dict, current_user: dict = Depends(get_current_user)):
    is_public = 1 if body.get("is_public", True) else 0
    conn = sqlite3.connect(GEN_DB)
    _history_owner_check(conn, item_id, current_user)
    conn.execute("UPDATE generations SET is_public=? WHERE id=?", (is_public, item_id))
    conn.commit()
    conn.close()
    return {"ok": True, "is_public": bool(is_public)}


@app.post("/api/history/{item_id}/hide")
def api_history_hide(item_id: str, body: dict, current_user: dict = Depends(get_current_user)):
    is_hidden = 1 if body.get("is_hidden", True) else 0
    hidden_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if is_hidden else ""
    hidden_by = current_user.get("sub", "") if is_hidden else ""
    conn = sqlite3.connect(GEN_DB)
    _history_owner_check(conn, item_id, current_user)
    conn.execute(
        "UPDATE generations SET is_hidden=?, hidden_at=?, hidden_by=? WHERE id=?",
        (is_hidden, hidden_at, hidden_by, item_id),
    )
    conn.commit()
    conn.close()
    item = next((h for h in history if h.get("id") == item_id), None)
    if item:
        item["is_hidden"] = bool(is_hidden)
        item["hidden_at"] = hidden_at
        item["hidden_by"] = hidden_by
        save_history()
    return {"ok": True, "is_hidden": bool(is_hidden), "hidden_at": hidden_at}


@app.post("/api/history/batch-delete")
def api_history_batch_delete(body: dict, current_user: dict = Depends(get_current_user)):
    ids = [str(x) for x in body.get("ids", []) if str(x)]
    if not ids:
        raise HTTPException(400, "ids required")
    deleted = 0
    for item_id in ids:
        try:
            api_history_delete(item_id, current_user)
            deleted += 1
        except HTTPException as e:
            if e.status_code in (403, 404):
                continue
            raise
    return {"ok": True, "deleted": deleted}


@app.post("/api/history/batch-download")
def api_history_batch_download(body: dict, current_user: dict = Depends(get_current_user)):
    ids = [str(x) for x in body.get("ids", []) if str(x)]
    if not ids:
        raise HTTPException(400, "ids required")
    conn = sqlite3.connect(GEN_DB)
    conn.row_factory = sqlite3.Row
    rows = []
    for item_id in ids:
        try:
            rows.append(_history_owner_check(conn, item_id, current_user))
        except HTTPException:
            pass
    conn.close()
    if not rows:
        raise HTTPException(404, "No downloadable records")
    zip_name = f"ez_comfyui_history_{int(time.time())}.zip"
    zip_path = os.path.join("/private/tmp", zip_name)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            rel = row["image_path"]
            p = _safe_rel_path(OUTPUT_DIR, rel)
            if os.path.isfile(p):
                zf.write(p, arcname=os.path.basename(rel))
    return FileResponse(zip_path, media_type="application/zip", filename=zip_name)


@app.delete("/api/history")
def api_history_clear(current_user: dict = Depends(get_current_user)):
    """Move all generation records for the current user to trash."""
    user_id = current_user.get("sub", "")
    deleted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(GEN_DB)
    conn.execute(
        "UPDATE generations SET deleted_at=?, deleted_by=? WHERE user_id=? AND COALESCE(deleted_at, '') = ''",
        (deleted_at, user_id, user_id),
    )
    conn.commit()
    conn.close()
    changed = False
    for item in history:
        if item.get("user_id") == user_id and not item.get("deleted_at"):
            item["is_deleted"] = True
            item["deleted_at"] = deleted_at
            item["deleted_by"] = user_id
            changed = True
    if changed:
        save_history()
    return {"ok": True, "deleted": True, "deleted_at": deleted_at}


@app.get("/api/images/{filename:path}")
def api_image(filename: str, current_user: dict = Depends(get_current_user)):
    """Serve generated images."""
    path = _safe_rel_path(OUTPUT_DIR, filename)
    if os.path.isfile(path):
        return FileResponse(path, media_type=_image_media_type(path, "image/png"))
    raise HTTPException(404)


@app.get("/api/thumbs/{filename:path}")
def api_thumb(filename: str, current_user: dict = Depends(get_current_user)):
    """Serve thumbnail images."""
    path = _safe_rel_path(OUTPUT_DIR, filename)
    if os.path.isfile(path):
        return FileResponse(path, media_type=_image_media_type(path, "image/jpeg"))
    raise HTTPException(404)


# ══════════════════════════════════════════════════════════════════════════
#  Auth Routes
# ══════════════════════════════════════════════════════════════════════════


class AuthRequest(BaseModel):
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class AdminUserUpdateRequest(BaseModel):
    role: Optional[str] = None
    disabled: Optional[bool] = None
    new_password: Optional[str] = None


class AdminUserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "user"


class SiteNotificationCreateRequest(BaseModel):
    title: str
    content: str


class SiteNotificationUpdateRequest(BaseModel):
    title: str
    content: str


class SiteNotificationDismissRequest(BaseModel):
    notification_id: Optional[int] = None


def _site_notification_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "content": row["content"],
        "created_by": row["created_by"] or "",
        "created_by_username": row["created_by_username"] or "",
        "created_at": row["created_at"],
    }


def _validate_site_notification_payload(title: str, content: str) -> tuple[str, str]:
    title = (title or "").strip()
    content = (content or "").strip()
    if len(title) < 1:
        raise HTTPException(400, "Notification title is required")
    if len(content) < 1:
        raise HTTPException(400, "Notification content is required")
    if len(title) > 120:
        raise HTTPException(400, "Notification title is too long")
    if len(content) > 4000:
        raise HTTPException(400, "Notification content is too long")
    return title, content


def _fetch_site_notification(conn: sqlite3.Connection, notification_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT n.id, n.title, n.content, n.created_by, n.created_at,
               COALESCE(u.username, '') AS created_by_username
          FROM site_notifications n
          LEFT JOIN users u ON u.id = n.created_by
         WHERE n.id=?
        """,
        (notification_id,),
    ).fetchone()


@app.post("/auth/register")
def auth_register(req: AuthRequest, response: Response, request: Request):
    username = req.username.strip()
    password = req.password
    _check_auth_rate_limit(request, "register", username)
    if len(username) < 2 or len(password) < 6:
        raise HTTPException(400, "Username (min 2) or password (min 6) too short")
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    user_id = str(uuid.uuid4())[:8]
    conn = sqlite3.connect(AUTH_DB)
    try:
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        role = "admin" if user_count == 0 else "user"
        conn.execute("INSERT INTO users (id, username, password_hash, role) VALUES (?, ?, ?, ?)",
                     (user_id, username, hashed, role))
        conn.commit()
        token = _create_token(user_id, username)
        _set_auth_cookie(response, token, request)
        _clear_auth_rate_limit(request, "register", username)
        conn.close()
        return {"id": user_id, "username": username, "role": role, "token": token}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(409, "Username already exists")


@app.post("/auth/login")
def auth_login(req: AuthRequest, response: Response, request: Request):
    username = req.username.strip()
    password = req.password
    _check_auth_rate_limit(request, "login", username)
    if not username:
        raise HTTPException(400, "Username is required")
    if not password:
        raise HTTPException(400, "Password is required")
    conn = sqlite3.connect(AUTH_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Username does not exist")
    if row and row["disabled"]:
        raise HTTPException(403, "User disabled")
    if not bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
        raise HTTPException(401, "Incorrect password")
    token = _create_token(row["id"], row["username"])
    _set_auth_cookie(response, token, request)
    _clear_auth_rate_limit(request, "login", username)
    return {"id": row["id"], "username": row["username"], "role": row["role"], "token": token}


@app.post("/auth/logout")
def auth_logout(response: Response):
    response.delete_cookie(AUTH_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/auth/me")
def auth_me(current_user: dict = Depends(get_current_user)):
    conn = sqlite3.connect(AUTH_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT id, username, role, disabled, avatar, created_at FROM users WHERE id=?",
                       (current_user["sub"],)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "User not found")
    return {"id": row["id"], "username": row["username"], "role": row["role"],
            "disabled": bool(row["disabled"]),
            "avatar": row["avatar"], "created_at": row["created_at"]}


@app.post("/auth/change-password")
def auth_change_password(req: PasswordChangeRequest, current_user: dict = Depends(get_current_user)):
    if len(req.new_password) < 6:
        raise HTTPException(400, "New password too short")
    conn = sqlite3.connect(AUTH_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT password_hash FROM users WHERE id=?", (current_user["sub"],)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "User not found")
    if not bcrypt.checkpw(req.current_password.encode(), row["password_hash"].encode()):
        conn.close()
        raise HTTPException(403, "Current password is incorrect")
    hashed = bcrypt.hashpw(req.new_password.encode(), bcrypt.gensalt()).decode()
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hashed, current_user["sub"]))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/api/users")
def api_users_list(current_user: dict = Depends(require_admin)):
    conn = sqlite3.connect(AUTH_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, username, role, disabled, avatar, created_at FROM users ORDER BY created_at ASC"
    ).fetchall()

    gen_conn = sqlite3.connect(GEN_DB)
    gen_conn.row_factory = sqlite3.Row
    counts = {
        r["user_id"] or "": int(r["gen_count"] or 0)
        for r in gen_conn.execute(
            "SELECT user_id, COUNT(*) AS gen_count FROM generations GROUP BY user_id"
        ).fetchall()
    }
    gen_conn.close()

    conn.close()
    return {"ok": True, "data": [
        {"id": r["id"], "username": r["username"], "role": r["role"],
         "disabled": bool(r["disabled"]), "avatar": r["avatar"], "created_at": r["created_at"],
         "generation_count": counts.get(r["id"], 0)}
        for r in rows
    ]}


@app.post("/api/users")
def api_user_create(req: AdminUserCreateRequest, current_user: dict = Depends(require_admin)):
    username = req.username.strip()
    password = req.password or ""
    role = req.role if req.role in ("admin", "user") else "user"
    if len(username) < 2:
        raise HTTPException(400, "Username too short")
    if len(password) < 6:
        raise HTTPException(400, "Password too short")
    conn = sqlite3.connect(AUTH_DB)
    try:
        user_id = uuid.uuid4().hex[:8]
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, disabled) VALUES (?, ?, ?, ?, 0)",
            (user_id, username, hashed, role),
        )
        conn.commit()
        return {"ok": True, "data": {"id": user_id, "username": username, "role": role, "disabled": False}}
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Username already exists")
    finally:
        conn.close()


@app.put("/api/users/{user_id}")
def api_user_update(user_id: str, req: AdminUserUpdateRequest, current_user: dict = Depends(require_admin)):
    updates = []
    params = []
    if req.role is not None:
        if req.role not in ("admin", "user"):
            raise HTTPException(400, "Invalid role")
        updates.append("role=?")
        params.append(req.role)
    if req.disabled is not None:
        if user_id == current_user.get("sub") and req.disabled:
            raise HTTPException(400, "Cannot disable yourself")
        updates.append("disabled=?")
        params.append(1 if req.disabled else 0)
    if req.new_password:
        if len(req.new_password) < 6:
            raise HTTPException(400, "Password too short")
        updates.append("password_hash=?")
        params.append(bcrypt.hashpw(req.new_password.encode(), bcrypt.gensalt()).decode())
    if not updates:
        return {"ok": True}
    params.append(user_id)
    conn = sqlite3.connect(AUTH_DB)
    cur = conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id=?", params)
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "User not found")
    return {"ok": True}


@app.delete("/api/users/{user_id}")
def api_user_delete(user_id: str, current_user: dict = Depends(require_admin)):
    if user_id == current_user.get("sub"):
        raise HTTPException(400, "Cannot delete yourself")
    conn = sqlite3.connect(AUTH_DB)
    cur = conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "User not found")
    return {"ok": True}


@app.get("/api/system-settings")
def api_system_settings_get(current_user: dict = Depends(require_admin)):
    return {"ok": True, "data": _load_system_settings()}


@app.put("/api/system-settings")
def api_system_settings_put(req: dict, current_user: dict = Depends(require_admin)):
    return {"ok": True, "data": _update_system_settings(req)}


@app.post("/api/system-settings/llm/test")
def api_llm_api_test(req: dict, current_user: dict = Depends(require_admin)):
    raw = req.get("llm_api") if isinstance(req, dict) and isinstance(req.get("llm_api"), dict) else {}
    cfg = configure_llm_client(raw, include_api_key=True)
    try:
        response = chat_completion(
            [{"role": "user", "content": "Reply with pong only."}],
            base_url=cfg.get("base_url"),
            model=cfg.get("model"),
            api_key=cfg.get("api_key"),
            temperature=0,
            max_tokens=16,
            timeout=cfg.get("timeout"),
        )
    except Exception as e:
        raise HTTPException(502, f"LLM API 测试失败: {e}") from e
    content = ""
    try:
        content = str(response["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        content = ""
    return {
        "ok": True,
        "provider": llm_provider_name(str(cfg.get("model") or "")),
        "base_url": cfg.get("base_url", ""),
        "model": cfg.get("model", ""),
        "reply": content,
    }


@app.get("/api/site-notifications")
def api_site_notifications(current_user: dict | None = Depends(get_current_user_optional)):
    conn = sqlite3.connect(AUTH_DB)
    conn.row_factory = sqlite3.Row
    latest_row = conn.execute("SELECT COALESCE(MAX(id), 0) AS latest_id FROM site_notifications").fetchone()
    latest_id = int(latest_row["latest_id"] or 0)
    suppressed_until_id = 0
    user_id = (current_user or {}).get("sub", "")
    if user_id:
        state = conn.execute(
            "SELECT suppressed_until_id FROM site_notification_state WHERE user_id=?",
            (user_id,),
        ).fetchone()
        suppressed_until_id = int((state and state["suppressed_until_id"]) or 0)
    rows = conn.execute(
        """
        SELECT n.id, n.title, n.content, n.created_by, n.created_at,
               COALESCE(u.username, '') AS created_by_username
          FROM site_notifications n
          LEFT JOIN users u ON u.id = n.created_by
         WHERE n.id > ?
         ORDER BY n.id ASC
        """,
        (suppressed_until_id,),
    ).fetchall()
    conn.close()
    return {
        "ok": True,
        "data": [_site_notification_row(row) for row in rows],
        "latest_id": latest_id,
        "suppressed_until_id": suppressed_until_id,
    }


@app.get("/api/site-notifications/admin")
def api_site_notifications_admin(current_user: dict = Depends(require_admin)):
    conn = sqlite3.connect(AUTH_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT n.id, n.title, n.content, n.created_by, n.created_at,
               COALESCE(u.username, '') AS created_by_username
          FROM site_notifications n
          LEFT JOIN users u ON u.id = n.created_by
         ORDER BY n.id DESC
         LIMIT 100
        """
    ).fetchall()
    conn.close()
    return {"ok": True, "data": [_site_notification_row(row) for row in rows]}


@app.post("/api/site-notifications")
def api_site_notification_create(req: SiteNotificationCreateRequest, current_user: dict = Depends(require_admin)):
    title, content = _validate_site_notification_payload(req.title, req.content)
    conn = sqlite3.connect(AUTH_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "INSERT INTO site_notifications (title, content, created_by) VALUES (?, ?, ?)",
        (title, content, current_user.get("sub", "")),
    )
    conn.commit()
    row = _fetch_site_notification(conn, int(cur.lastrowid))
    conn.close()
    return {"ok": True, "data": _site_notification_row(row)}


@app.put("/api/site-notifications/{notification_id}")
def api_site_notification_update(
    notification_id: int,
    req: SiteNotificationUpdateRequest,
    current_user: dict = Depends(require_admin),
):
    title, content = _validate_site_notification_payload(req.title, req.content)
    conn = sqlite3.connect(AUTH_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "UPDATE site_notifications SET title=?, content=? WHERE id=?",
        (title, content, notification_id),
    )
    conn.commit()
    if cur.rowcount == 0:
        conn.close()
        raise HTTPException(404, "Notification not found")
    row = _fetch_site_notification(conn, notification_id)
    conn.close()
    return {"ok": True, "data": _site_notification_row(row)}


@app.delete("/api/site-notifications/{notification_id}")
def api_site_notification_delete(notification_id: int, current_user: dict = Depends(require_admin)):
    conn = sqlite3.connect(AUTH_DB)
    cur = conn.execute("DELETE FROM site_notifications WHERE id=?", (notification_id,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "Notification not found")
    return {"ok": True, "id": notification_id}


@app.post("/api/site-notifications/dismiss")
def api_site_notification_dismiss(req: SiteNotificationDismissRequest, current_user: dict = Depends(get_current_user)):
    conn = sqlite3.connect(AUTH_DB)
    latest_row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM site_notifications").fetchone()
    latest_id = int((latest_row and latest_row[0]) or 0)
    target_id = int(req.notification_id or latest_id or 0)
    target_id = max(0, min(target_id, latest_id))
    conn.execute(
        """
        INSERT INTO site_notification_state (user_id, suppressed_until_id, updated_at)
        VALUES (?, ?, datetime('now','localtime'))
        ON CONFLICT(user_id) DO UPDATE SET
          suppressed_until_id=max(site_notification_state.suppressed_until_id, excluded.suppressed_until_id),
          updated_at=datetime('now','localtime')
        """,
        (current_user.get("sub", ""), target_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "suppressed_until_id": target_id}


# ══════════════════════════════════════════════════════════════════════════
#  WebSocket
# ══════════════════════════════════════════════════════════════════════════

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    ws_user = _get_user_from_token(
        ws.cookies.get(AUTH_COOKIE_NAME) or ws.query_params.get("token")
    )
    await ws.accept()
    ws_clients.append(ws)
    ws_client_users[ws] = ws_user or {}
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        if ws in ws_clients:
            ws_clients.remove(ws)
        ws_client_users.pop(ws, None)


# ══════════════════════════════════════════════════════════════════════════
#  API: NODES
# ══════════════════════════════════════════════════════════════════════════

def _check_node_http(node: dict) -> bool:
    """Check if any instance on the node is reachable via HTTP."""
    for inst in node.get("instances", []):
        url = _instance_api_url(node, inst)
        if comfyui_up(base_url=url):
            return True
    return False


def _check_node_ssh(node: dict) -> bool:
    """Check SSH connectivity."""
    if node.get("connection") not in ("local", "remote-ssh"):
        return False
    if node.get("connection") == "local":
        return True
    try:
        ssh = _resolve_ssh_config(node.get("ssh_config", {}))
        if ssh.get("auth") == "password" and ssh.get("password"):
            cmd = ["sshpass", "-p", ssh["password"], "ssh",
                   "-p", str(ssh.get("port", 22)),
                   "-o", "ConnectTimeout=5",
                   f"{ssh.get('user', 'root')}@{node['host']}",
                   "echo", "ok"]
        else:
            cmd = ["ssh", "-p", str(ssh.get("port", 22)),
                   "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
                   f"{ssh.get('user', 'root')}@{node['host']}",
                   "echo", "ok"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.stdout.strip() == "ok"
    except Exception:
        return False


def _check_node_systemd(node: dict) -> bool:
    """Check if systemd services for node instances are active."""
    for inst in node.get("instances", []):
        if _check_service_active(node, inst):
            return True
    return False


def _get_instance_status(node: dict, instance: dict) -> dict:
    """Get status for a single instance."""
    url = _instance_api_url(node, instance)
    http_up = comfyui_up(base_url=url)
    q_size = _get_instance_queue_size(url)
    conn = node.get("connection", "local")

    if http_up and q_size > 0:
        status = "running"
    elif http_up and q_size == 0:
        status = "idle"
    elif conn in ("local", "remote-ssh") and _check_service_active(node, instance) and not http_up:
        status = "dead"
    elif conn in ("local", "remote-ssh") and not _check_service_active(node, instance) and not http_up:
        status = "offline"
    elif conn == "remote-http" and not http_up:
        status = "unreachable"
    else:
        status = "unknown"

    return {
        "id": instance.get("id", ""),
        "name": instance["name"],
        "port": instance["port"],
        "status": status,
        "http_up": http_up,
        "queue": q_size,
        "service": instance.get("service", f"comfyui-{instance['name'].lower()}"),
    }


@app.get("/api/nodes")
def api_nodes_list(current_user: dict = Depends(get_current_user)):
    """List all enabled nodes with real-time status."""
    nodes = [_normalize_node(n) for n in _load_nodes() if n.get("enabled", True)]
    result = []
    for node in nodes:
        if not _can_view_node(node, current_user):
            continue
        visible_node_instances = [
            inst for inst in node.get("instances", [])
            if _can_view_instance(inst, current_user)
        ]
        inst_statuses = [_get_instance_status(node, inst) for inst in visible_node_instances]
        http_up = any(s["http_up"] for s in inst_statuses)
        ssh_ok = _check_node_ssh(node)

        # Overall node status
        running = sum(1 for s in inst_statuses if s["status"] == "running")
        idle = sum(1 for s in inst_statuses if s["status"] == "idle")
        dead = sum(1 for s in inst_statuses if s["status"] == "dead")
        offline = sum(1 for s in inst_statuses if s["status"] == "offline")

        result.append({
            "id": node["id"],
            "name": node["name"],
            "host": node["host"],
            "connection": node.get("connection", "local"),
            "enabled": node.get("enabled", True),
            "access": node.get("access"),
            "labels": node.get("labels", []),
            "sort_order": node.get("sort_order", 0),
            "owner_id": node.get("owner_id", ""),
            "shared": bool(node.get("shared", False)),
            "can_manage": _can_manage_node(node, current_user),
            "can_share": _is_admin_user(current_user),
            "http_up": http_up,
            "ssh_ok": ssh_ok,
            "connected": _is_node_connected(node["id"]),
            "instances": inst_statuses,
            "stats": {
                "total": len(inst_statuses),
                "running": running,
                "idle": idle,
                "dead": dead,
                "offline": offline,
            },
        })
    return {"ok": True, "data": result}


@app.get("/api/nodes/{nid}")
def api_node_get(nid: str, current_user: dict = Depends(get_current_user)):
    """Get single node detail with password mask."""
    node = _ensure_node_access(_get_node_by_id(nid), current_user, require_manage=True)
    # Mask password
    result = dict(node)
    if "ssh_config" in result and result["ssh_config"].get("password"):
        result["ssh_config"]["password"] = "__MASKED__"
    return {"ok": True, "data": result}


class NodeCreateRequest(BaseModel):
    name: str
    host: str = "127.0.0.1"
    connection: str = "local"
    labels: list[str] = []
    ssh_config: dict = {}
    scan_ports: dict = {}
    instances: list[dict] = []
    sort_order: int = 0
    shared: bool = False


@app.post("/api/nodes")
def api_node_create(req: NodeCreateRequest, current_user: dict = Depends(get_current_user)):
    """Create a new node."""
    nodes = _load_nodes()
    new_node = {
        "id": uuid.uuid4().hex[:12],
        "name": req.name,
        "host": req.host,
        "connection": req.connection,
        "enabled": True,
        "labels": req.labels,
        "ssh_config": req.ssh_config or {"auth": "password", "user": "", "port": 22, "password": ""},
        "scan_ports": req.scan_ports or {"range": "8188-8195", "extra": []},
        "instances": req.instances or [],
        "sort_order": req.sort_order or len(nodes),
        "owner_id": _user_id(current_user),
        "shared": bool(req.shared) if _is_admin_user(current_user) else False,
    }
    nodes.append(new_node)
    _save_nodes(nodes)
    return {"ok": True, "data": new_node}


class NodeUpdateRequest(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    connection: Optional[str] = None
    enabled: Optional[bool] = None
    labels: Optional[list[str]] = None
    ssh_config: Optional[dict] = None
    scan_ports: Optional[dict] = None
    instances: Optional[list[dict]] = None
    sort_order: Optional[int] = None
    shared: Optional[bool] = None


class NodeReorderRequest(BaseModel):
    order: list[dict]

@app.put("/api/nodes/reorder")
def api_node_reorder(req: NodeReorderRequest, current_user: dict = Depends(require_admin)):
    """Reorder nodes."""
    nodes = _load_nodes()
    order_map = {item["id"]: item.get("sort_order", 0) for item in req.order}
    for node in nodes:
        if node["id"] in order_map:
            node["sort_order"] = order_map[node["id"]]
    # Sort nodes list by sort_order
    nodes.sort(key=lambda n: n.get("sort_order", 0))
    _save_nodes(nodes)
    return {"ok": True}
@app.put("/api/nodes/{nid}")
def api_node_update(nid: str, req: NodeUpdateRequest, current_user: dict = Depends(get_current_user)):
    """Update a node (partial merge)."""
    nodes = _load_nodes()
    node = next((n for n in nodes if n["id"] == nid), None)
    node = _ensure_node_access(node, current_user, require_manage=True)

    update_data = {k: v for k, v in req.model_dump(exclude_unset=True).items() if v is not None}
    if "shared" in update_data and not _is_admin_user(current_user):
        del update_data["shared"]
    # Password: __MASKED__ means skip
    if "ssh_config" in update_data and isinstance(update_data["ssh_config"], dict):
        if update_data["ssh_config"].get("password") == "__MASKED__":
            del update_data["ssh_config"]["password"]
            merged_ssh = dict(node.get("ssh_config", {}))
            merged_ssh.update(update_data["ssh_config"])
            update_data["ssh_config"] = merged_ssh
    node.update(update_data)
    _save_nodes(nodes)
    return {"ok": True, "data": node}


@app.delete("/api/nodes/{nid}")
def api_node_delete(nid: str, current_user: dict = Depends(get_current_user)):
    """Delete a node. Must keep at least 1 node."""
    nodes = _load_nodes()
    visible_nodes = [n for n in nodes if _can_manage_node(_normalize_node(n), current_user)]
    if len(nodes) <= 1 or len(visible_nodes) <= 1:
        raise HTTPException(400, "Cannot delete the last node")
    node = next((n for n in nodes if n["id"] == nid), None)
    node = _ensure_node_access(node, current_user, require_manage=True)
    nodes.remove(node)
    _save_nodes(nodes)
    return {"ok": True}


@app.post("/api/nodes/{nid}/instances/{iid}/start")
def api_node_instance_start(nid: str, iid: str, current_user: dict = Depends(get_current_user)):
    node = _ensure_node_access(_get_node_by_id(nid), current_user, require_manage=False)
    inst = next((x for x in node.get("instances", []) if x["id"] == iid), None)
    if not inst:
        raise HTTPException(404, "Instance not found")
    if comfyui_up(base_url=_instance_api_url(node, inst)):
        return {"ok": True}
    if node.get("connection") == "remote-http":
        raise HTTPException(400, "Cannot start instance via remote-http")
    if _managed_instance_action(node, inst, "start", reason="node-api"):
        return {"ok": True}
    raise HTTPException(500, "Failed to start instance")


@app.post("/api/nodes/{nid}/instances/{iid}/stop")
def api_node_instance_stop(nid: str, iid: str, current_user: dict = Depends(get_current_user)):
    node = _ensure_node_access(_get_node_by_id(nid), current_user, require_manage=True)
    inst = next((x for x in node.get("instances", []) if x["id"] == iid), None)
    if not inst:
        raise HTTPException(404, "Instance not found")
    if node.get("connection") == "remote-http":
        raise HTTPException(400, "Cannot stop instance via remote-http")
    if _managed_instance_action(node, inst, "stop", reason="node-api"):
        _instance_group[inst["name"]] = ""
        _finalize_instance_jobs(inst["name"], "实例已停止")
        _kick_queued_generation_jobs("实例停止后")
        return {"ok": True}
    raise HTTPException(500, "Failed to stop instance")


@app.post("/api/nodes/{nid}/instances/{iid}/restart")
def api_node_instance_restart(nid: str, iid: str, current_user: dict = Depends(get_current_user)):
    node = _ensure_node_access(_get_node_by_id(nid), current_user, require_manage=True)
    inst = next((x for x in node.get("instances", []) if x["id"] == iid), None)
    if not inst:
        raise HTTPException(404, "Instance not found")
    if node.get("connection") == "remote-http":
        raise HTTPException(400, "Cannot restart instance via remote-http")
    if _managed_instance_action(node, inst, "restart", reason="node-api"):
        return {"ok": True}
    raise HTTPException(500, "Failed to restart instance")

@app.post("/api/nodes/{nid}/instances/{iid}/force-restart")
def api_node_instance_force_restart(nid: str, iid: str, current_user: dict = Depends(get_current_user)):
    node = _ensure_node_access(_get_node_by_id(nid), current_user, require_manage=True)
    inst = next((x for x in node.get("instances", []) if x["id"] == iid), None)
    if not inst:
        raise HTTPException(404, "Instance not found")
    if node.get("connection") == "remote-http":
        raise HTTPException(400, "Cannot force-restart instance via remote-http")
    if _managed_instance_action(node, inst, "force-restart", reason="node-api"):
        return {"ok": True}
    raise HTTPException(500, "Failed to force-restart instance")


@app.post("/api/nodes/{nid}/discover")
def api_node_discover(nid: str, current_user: dict = Depends(get_current_user)):
    """Port scan to discover ComfyUI instances on a node."""
    node = _ensure_node_access(_get_node_by_id(nid), current_user, require_manage=True)

    scan_ports = node.get("scan_ports", {})
    port_range = scan_ports.get("range", "8188-8195")
    extra = scan_ports.get("extra", [])

    # Parse port range
    ports = set()
    try:
        if "-" in port_range:
            lo, hi = map(int, port_range.split("-", 1))
            ports.update(range(lo, hi + 1))
        else:
            ports.add(int(port_range))
    except (ValueError, TypeError):
        pass
    for p in extra:
        try:
            ports.add(int(p))
        except (ValueError, TypeError):
            pass

    detected = []
    for port in sorted(ports):
        probe_inst = {"port": port}
        url = _instance_api_url(node, probe_inst)
        try:
            with urllib.request.urlopen(url + "/system_stats", timeout=3) as r:
                is_comfyui = r.status == 200
                q_size = 0
                if is_comfyui:
                    try:
                        q = comfyui_get("/queue", base_url=url)
                        q_size = len(q.get("queue_running", [])) + len(q.get("queue_pending", []))
                    except Exception:
                        pass
                detected.append({"port": port, "comfyui": is_comfyui, "queue": q_size})
        except Exception:
            detected.append({"port": port, "comfyui": False, "queue": 0})

    # Compare with registered instances
    registered_ports = {inst.get("port") for inst in node.get("instances", []) if inst.get("port")}
    new_ports = [d for d in detected if d["comfyui"] and d["port"] not in registered_ports]
    missing_ports = [d for d in detected if d["comfyui"] and d["port"] in registered_ports]

    return {
        "ok": True,
        "data": {
            "detected": detected,
            "new": new_ports,
            "missing": missing_ports,
        }
    }






@app.post("/api/nodes/{nid}/test")
def api_node_test(nid: str, current_user: dict = Depends(get_current_user)):
    """Test connectivity for a node."""
    node = _ensure_node_access(_get_node_by_id(nid), current_user, require_manage=False)
    return {
        "ok": True,
        "data": {
            "http": _check_node_http(node),
            "ssh": _check_node_ssh(node),
            "systemd": _check_node_systemd(node),
        }
    }


# ══════════════════════════════════════════════════════════════════════════
#  API: Nodes - Apply Scan Results
# ══════════════════════════════════════════════════════════════════════════

class ApplyScanRequest(BaseModel):
    selected: list[dict]


@app.post("/api/nodes/{nid}/apply-scan")
def api_node_apply_scan(nid: str, req: ApplyScanRequest, current_user: dict = Depends(get_current_user)):
    """Apply scan results: add new instances to node."""
    nodes = _load_nodes(force=True)
    found = None
    for n in nodes:
        if n["id"] == nid:
            found = n
            break
    found = _ensure_node_access(found, current_user, require_manage=True)
    added = []
    for sel in req.selected:
        port = sel.get("port")
        if not port:
            continue
        existing = [inst for inst in found.get("instances", []) if inst.get("port") == port]
        if existing:
            continue
        idx = len(found.get("instances", [])) + len(added)
        name = chr(65 + idx) if idx < 26 else f"inst-{idx}"
        new_inst = {
            "id": uuid.uuid4().hex[:8],
            "name": name,
            "port": port,
            "service": f"comfyui-{name.lower()}",
            "enabled": True,
            "workflow_dirs": [],
        }
        found["instances"].append(new_inst)
        added.append(new_inst)
    _save_nodes(nodes)
    return {"ok": True, "data": {"added": len(added)}}


# ══════════════════════════════════════════════════════════════════════════
#  Workflow Version Management
# ══════════════════════════════════════════════════════════════════════════

MAX_WORKFLOW_SIZE = 1 * 1024 * 1024

@app.get("/api/workflows/{name}/versions")
def api_workflow_versions(name: str):
    meta = _load_wf_meta()
    entry = meta.get(name, {})
    versions = entry.get("versions", {})
    base = name.replace(".json", "")
    vdir = os.path.join(WORKFLOW_DIR, "__versions", base)
    if os.path.isdir(vdir):
        for vf in sorted(os.listdir(vdir)):
            if vf.endswith(".json"):
                vname = vf.replace(".json", "")
                if vname not in versions:
                    versions[vname] = os.path.join(vdir, vf)
        if versions != entry.get("versions", {}):
            entry["versions"] = versions
            meta[name] = entry
            _write_wf_meta_entry_to_db(name, entry)
            _export_wf_meta_json_from_db()
    return {"versions": versions, "active_version": entry.get("active_version", ""),
            "base": {"filename": name, "path": _resolve_workflow(name) or ""}}

@app.get("/api/workflows/{name}/version-download")
def api_workflow_version_download(name: str, version: str = "v1"):
    meta = _load_wf_meta()
    entry = meta.get(name, {})
    versions = entry.get("versions", {})
    if version == "v1" or version == "base":
        path = _resolve_workflow(name)
        if path: return FileResponse(path, media_type="application/json", filename=f"{name}")
        raise HTTPException(404)
    vpath = versions.get(version, "")
    if not vpath or not os.path.isfile(vpath):
        raise HTTPException(404, f"Version {version} not found")
    base_name = name.replace(".json", "")
    return FileResponse(vpath, media_type="application/json", filename=f"{base_name}_{version}.json")

@app.post("/api/workflows/{name}/upload-version")
async def api_upload_workflow_version(name: str, file: UploadFile = File(...), current_user: dict = Depends(require_admin)):
    content = await _read_upload_limited(file, MAX_WORKFLOW_SIZE, "Workflow")
    try:
        json.loads(content)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"Invalid JSON: {e}")
    meta = _load_wf_meta()
    if name not in meta:
        raise HTTPException(404, f"Workflow {name} not found")
    entry = meta[name]
    versions = entry.get("versions", {})
    existing_vnums = []
    for k in versions:
        m = re.match(r'v(\d+)', k)
        if m:
            existing_vnums.append(int(m.group(1)))
    next_v = max(existing_vnums, default=0) + 1
    vname = f"v{next_v}"
    base = name.replace(".json", "")
    vdir = os.path.join(WORKFLOW_DIR, "__versions", base)
    os.makedirs(vdir, exist_ok=True)
    vpath = os.path.join(vdir, f"{vname}.json")
    with open(vpath, "wb") as f:
        f.write(content)
    current_path = _resolve_workflow(name)
    if current_path and not versions:
        v1_path = os.path.join(vdir, "v1.json")
        if not os.path.isfile(v1_path):
            import shutil
            shutil.copy2(current_path, v1_path)
            versions["v1"] = v1_path
    versions[vname] = vpath
    entry["versions"] = versions
    entry["active_version"] = vname
    _write_wf_meta_entry_to_db(name, entry)
    _export_wf_meta_json_from_db()
    return {"ok": True, "version": vname, "versions": versions}


@app.post("/api/workflows/{name}/activate-version")
def api_activate_workflow_version(name: str, body: dict, current_user: dict = Depends(require_admin)):
    version = body.get("version", "")
    if not version:
        raise HTTPException(400, "version required")
    meta = _load_wf_meta()
    entry = meta.get(name, {})
    versions = entry.get("versions", {})
    if version not in versions:
        raise HTTPException(404, f"Version {version} not found")
    vpath = versions[version]
    if not os.path.isfile(vpath):
        raise HTTPException(404, f"Version file not found")
    current_path = _resolve_workflow(name)
    if current_path:
        import shutil
        shutil.copy2(vpath, current_path)
    entry["active_version"] = version
    _write_wf_meta_entry_to_db(name, entry)
    _export_wf_meta_json_from_db()
    return {"ok": True, "version": version}


@app.delete("/api/workflows/{name}/versions/{version}")
def api_delete_workflow_version(name: str, version: str, current_user: dict = Depends(require_admin)):
    if version == "v1" or version == "base":
        raise HTTPException(400, "Cannot delete base version")
    meta = _load_wf_meta()
    entry = meta.get(name, {})
    versions = entry.get("versions", {})
    vpath = versions.get(version, "")
    if not vpath:
        raise HTTPException(404, f"Version {version} not found")
    if os.path.isfile(vpath):
        os.remove(vpath)
    del versions[version]
    if entry.get("active_version") == version:
        entry["active_version"] = "v1"
    entry["versions"] = versions
    _write_wf_meta_entry_to_db(name, entry)
    _export_wf_meta_json_from_db()
    return {"ok": True, "deleted": version}

if __name__ == "__main__":
    load_history()
    os.makedirs(HISTORY_DIR, exist_ok=True)
    print(f"🎨 ComfyUI Web v3: http://0.0.0.0:{PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
