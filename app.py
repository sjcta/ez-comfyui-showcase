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
    WebSocketDisconnect, UploadFile, File, Form, Request, Depends
)
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn, urllib.request, urllib.error
from jose import jwt, JWTError
import bcrypt

# ── V4 refactored module imports (keep inline implementations for backward compat) ──
from modules.config import NodeCategory, ModelGroup, NODE_STATUS_MAP
from modules.comfyui_upload import ensure_workflow_images_available
from modules.instance_manager import InstanceManager, InstanceHealth
import modules.instance_picker as mod_picker
from modules.job_runner import JobRunner
from modules.prompt_interrogator import build_image_interrogate_workflow, prepare_interrogate_image, run_image_interrogator
from modules.prompt_labels import infer_generation_label
from modules.prompt_optimizer import normalize_interrogated_chinese_prompt, run_prompt_language_switcher, run_prompt_optimizer, run_prompt_translator
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
SECRET_KEY = os.environ.get("JWT_SECRET_KEY") or "ez-comfyui-showcase-local-jwt-secret-v1"
if not os.environ.get("JWT_SECRET_KEY"):
    print("[auth] JWT_SECRET_KEY is not set; using a stable local development secret.")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7

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
JOB_STAGE_TIMEOUTS = {
    "dispatching": 120,
    "queued": 600,
    "starting_comfyui": 360,
    "preparing": 180,
    "submitting": 90,
    "generating": 1200,
    "downloading": 240,
}
JOB_STAGE_TIMEOUT_MESSAGES = {
    "dispatching": "任务调度超时",
    "queued": "排队超时",
    "starting_comfyui": "实例启动超时",
    "preparing": "准备阶段超时",
    "submitting": "提交阶段超时",
    "generating": "生成阶段超时（长时间无进度）",
    "downloading": "拉取图片超时",
}

def _is_node_connected(nid: str) -> bool:
    return _connected_nodes.get(nid, True)

def _job_is_active_for_instance(job: dict, instance_name: str) -> bool:
    return job.get("instance") == instance_name and job.get("status") in ACTIVE_JOB_STATUSES


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


def _job_stuck_state(job: dict, now: float | None = None) -> tuple[bool, float, int]:
    status = str(job.get("status") or "")
    timeout = JOB_STAGE_TIMEOUTS.get(status, 600)
    last = _job_last_activity_ts(job)
    if not last or status in ("done", "error", "cancelled"):
        return False, 0.0, timeout
    now = now or time.time()
    age = max(0.0, now - last)
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
            full["url"] = f"http://{node['host']}:{inst['port']}"
            instances.append(full)
    return instances


_AUX_INSTANCE_ROLE_TOKENS = {
    "aux",
    "assistant",
    "caption",
    "interrogate",
    "llm",
    "prompt",
    "prompt-aux",
    "prompt_aux",
    "prompt_optimize",
    "prompt_interrogate",
    "text",
    "反推",
    "提示词",
    "辅助",
}


def _instance_role_tokens(inst: dict) -> set[str]:
    """Return normalized role/label tokens that describe how an instance may be used."""
    values: list[str] = []
    for key in ("role", "roles", "purpose", "usage", "task_role", "labels", "tags"):
        raw = inst.get(key)
        if raw is None:
            continue
        if isinstance(raw, (list, tuple, set)):
            values.extend(str(item) for item in raw)
        else:
            values.extend(part.strip() for part in str(raw).replace("，", ",").split(","))

    name = str(inst.get("name") or inst.get("id") or "").strip()
    service = str(inst.get("service") or "").strip()
    env_aux_names = {
        item.strip().lower()
        for item in os.environ.get("EZ_COMFYUI_AUX_INSTANCES", "").replace("，", ",").split(",")
        if item.strip()
    }
    if name and name.lower() in env_aux_names:
        values.append("prompt_aux")
    if service and service.lower() in env_aux_names:
        values.append("prompt_aux")

    tokens = {item.strip().lower() for item in values if item and item.strip()}
    return tokens


def _is_prompt_aux_instance(inst: dict) -> bool:
    """Whether this instance is reserved for prompt optimization/image interrogation."""
    if bool(inst.get("prompt_aux") or inst.get("auxiliary") or inst.get("aux_instance")):
        return True
    tokens = _instance_role_tokens(inst)
    return bool(tokens & _AUX_INSTANCE_ROLE_TOKENS)


def _get_prompt_aux_instances(instances: list[dict] | None = None) -> list[dict]:
    """Return instances reserved for prompt optimization and image interrogation."""
    pool = _get_enabled_instances() if instances is None else list(instances or [])
    return [inst for inst in pool if _is_prompt_aux_instance(inst)]


def _get_generation_instances(instances: list[dict] | None = None) -> list[dict]:
    """Return instances that may accept image-generation jobs."""
    pool = _get_enabled_instances() if instances is None else list(instances or [])
    return [inst for inst in pool if not _is_prompt_aux_instance(inst)]


def _can_view_instance(inst: dict, current_user: dict | None = None) -> bool:
    if _is_admin_user(current_user):
        return True
    return not _is_prompt_aux_instance(inst)


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
            full["url"] = f"http://{normalized['host']}:{inst['port']}"
            instances.append(full)
    return instances

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
                              f"{ssh.get('user', 'root')}@{node['host']}",
                              "-p", str(ssh.get("port", 22))]
                else:
                    prefix = ["ssh", f"{ssh.get('user', 'root')}@{node['host']}",
                              "-p", str(ssh.get("port", 22))]
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


# ── 任务队列：per-instance semaphores for parallel routing ──
_job_queue: asyncio.Queue = asyncio.Queue()
_inst_mgr: InstanceManager | None = None
_job_runner: JobRunner | None = None

async def _queue_worker():
    """Non-blocking dispatcher — spawns a task per job so per-instance semaphore waits don't block the queue."""
    while True:
        try:
            job_id, workflow_path, field_values, seed, vllm_was, img_w, img_h, user_id, preferred_instance, preferred_node_id = await _job_queue.get()
            if _job_runner:
                task = asyncio.create_task(_run_job_v4(job_id, workflow_path, field_values, seed, vllm_was, img_w, img_h, user_id, preferred_instance, preferred_node_id))
            else:
                task = asyncio.create_task(_dispatch_and_run(job_id, workflow_path, field_values, seed, vllm_was, img_w, img_h, preferred_instance, preferred_node_id))
            _job_tasks[job_id] = task
            task.add_done_callback(lambda _t, jid=job_id: _job_tasks.pop(jid, None))
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
        try:
            await asyncio.wait_for(sem.acquire(), timeout=600)
            inst_held = True
            jobs[job_id]["sem_acquired"] = True
        except asyncio.TimeoutError:
            if job_id in jobs:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["message"] = "排队超时（实例繁忙，10分钟未释放）"
                await broadcast({"type": "job_update", "job": jobs[job_id]})
                save_jobs()
            return

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
                            f"{user}@{host}", "-p", port,
                            f'find "{wf_dir}" -name "*.json" -maxdepth 2']
            else:
                find_cmd = ["ssh",
                            "-o", "StrictHostKeyChecking=no",
                            f"{user}@{host}", "-p", port,
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
                                   f"{user}@{host}", "-p", port,
                                   f'cat "{remote_path}"']
                    else:
                        cat_cmd = ["ssh",
                                   "-o", "StrictHostKeyChecking=no",
                                   f"{user}@{host}", "-p", port,
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
            image_path TEXT DEFAULT '',
            thumb_path TEXT DEFAULT '',
            created_at DATETIME DEFAULT (datetime('now','localtime')),
            completed_at DATETIME,
            duration_sec INTEGER DEFAULT 0,
            params TEXT DEFAULT '{}',
            prompt TEXT DEFAULT '',
            width INTEGER DEFAULT 0,
            height INTEGER DEFAULT 0,
            seed INTEGER DEFAULT 0
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
    ):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass
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
    admin_row = conn.execute("SELECT id FROM users WHERE username='admin' LIMIT 1").fetchone()
    if not admin_row:
        admin_hash = bcrypt.hashpw("admin".encode(), bcrypt.gensalt()).decode()
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, disabled) VALUES (?, ?, ?, 'admin', 0)",
            ("admin", "admin", admin_hash),
        )
    else:
        conn.execute("UPDATE users SET role='admin', disabled=0 WHERE username='admin'")
    has_admin = conn.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
    if not has_admin:
        first_user = conn.execute("SELECT id FROM users ORDER BY created_at ASC LIMIT 1").fetchone()
        if first_user:
            conn.execute("UPDATE users SET role='admin' WHERE id=?", (first_user[0],))
    conn.commit()
    conn.close()


def _gen_db_to_record(row: dict) -> dict:
    """Transform a SQLite generations row to the JSON record format used by the frontend."""
    if not isinstance(row, dict):
        row = dict(row)
    seed_val = str(row["seed"]) if row.get("seed") else ""
    deleted_at = row.get("deleted_at", "") or ""
    params = {}
    if row.get("params"):
        try:
            params = json.loads(row["params"])
        except Exception:
            pass
    workflow = row["workflow"]
    workflow_type = _workflow_primary_type(workflow)
    return {
        "id": row["id"],
        "filename": row.get("image_path", ""),
        "thumb": row.get("thumb_path", ""),
        "workflow": workflow,
        "workflow_type": workflow_type,
        "prompt": row.get("prompt", ""),
        "seed": seed_val,
        "width": row.get("width", 0),
        "height": row.get("height", 0),
        "elapsed": row.get("duration_sec", 0),
        "time": row.get("created_at", ""),
        "field_values": params,
        "user_id": row.get("user_id", ""),
        "username": row.get("username", ""),
        "is_public": bool(row.get("is_public", 0)),
        "is_deleted": bool(deleted_at),
        "deleted_at": deleted_at,
        "deleted_by": row.get("deleted_by", "") or "",
        "sort_index": row.get("history_rowid", 0),
        "batch_id": row.get("batch_id", "") or "",
        "batch_index": row.get("batch_index", 0) or 0,
        "batch_count": row.get("batch_count", 1) or 1,
    }


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
    lower = name.lower()
    if lower.startswith("i2v") or "-i2v" in lower or "_i2v" in lower:
        return "图生视频"
    if lower.startswith("t2v") or "-t2v" in lower or "_t2v" in lower:
        return "文生视频"
    if lower.startswith("i2i") or "-i2i" in lower or "_i2i" in lower:
        return "图生图"
    if lower.startswith("t2i") or "-t2i" in lower or "_t2i" in lower:
        return "文生图"
    try:
        meta = _load_wf_meta()
        entry = _normalize_wf_meta_entry(name, meta.get(name, {}))
        tags = entry.get("tags") or []
        return tags[0] if tags else ""
    except Exception:
        return ""


def _insert_generation(record: dict, elapsed: float, user_id: str = ""):
    """Insert a generation record into SQLite."""
    try:
        if not record.get("thumb") and record.get("filename"):
            record["thumb"] = make_thumbnail(record.get("filename", "")) or ""
        conn = sqlite3.connect(GEN_DB)
        conn.execute(
            """INSERT OR REPLACE INTO generations
               (id, workflow, image_path, thumb_path, prompt, width, height, seed, duration_sec, created_at, params, user_id, is_public, batch_id, batch_index, batch_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record["id"],
                record.get("workflow", ""),
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
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        add_log("error", "db", f"SQLite insert failed: {e}", record.get("id", ""))


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


def get_current_user(request: Request) -> dict:
    """Extract current user from Authorization header."""
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    token = auth.split(" ")[1]
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
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None
    try:
        payload = jwt.decode(auth.split(" ")[1], SECRET_KEY, algorithms=[ALGORITHM])
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
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return "anonymous"
    try:
        payload = jwt.decode(auth.split(" ")[1], SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub", "anonymous")
    except JWTError:
        return "anonymous"


# Legacy DGX paths (kept for backward compat when running on Spark)
COMFYUI_DIR   = "/home/sjcta/software/ComfyUI-Project"
COMFYUI_INPUT = os.environ.get("COMFYUI_INPUT") or "/home/sjcta/software/ComfyUI-Project/ComfyUI/input"
if not os.path.isdir(COMFYUI_INPUT):
    COMFYUI_INPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "input")
VLLM_CONTAINER = "qwen36-vllm"

# ── State ───────────────────────────────────────────────────────────────
jobs: dict[str, dict] = {}
_job_tasks: dict[str, asyncio.Task] = {}
history: list[dict] = []
ws_clients: list[WebSocket] = []
ws_client_users: dict[WebSocket, dict] = {}
gpu_cache: dict = {"ts": 0, "data": None}
node_gpu_cache: dict = {}

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
    for inst in _get_prompt_aux_instances():
        if inst["name"] not in _instance_last_active:
            _instance_last_active[inst["name"]] = 0

# Model group definitions — workflows sharing a base model get the same group.
# Affinity matching is done at the GROUP level, not filename level.
MODEL_GROUPS = [
    # (group_name, keywords_in_filename)
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

# ── Lifecycle ───────────────────────────────────────────────────────────

async def _idle_instance_watcher():
    """Stop instances idle for more than 15 minutes to free VRAM."""
    IDLE_TIMEOUT = 900
    while True:
        await asyncio.sleep(60)
        now = time.time()
        for inst in _get_enabled_instances():
            if _is_prompt_aux_instance(inst):
                continue
            name = inst["name"]
            last = _instance_last_active.get(name, 0)
            if last == 0:
                continue
            active_jobs = [j for j in jobs.values() if _job_is_active_for_instance(j, name)]
            if active_jobs:
                continue
            if now - last > IDLE_TIMEOUT:
                node = _get_node_by_id(inst.get("_node_id", ""))
                if node:
                    if not _check_service_active(node, inst):
                        _instance_last_active[name] = 0
                        _instance_group[name] = ""
                        continue
                    add_log("warn", "idle", f"Stopping idle {name} ({now - last:.0f}s idle)")
                    _run_instance_action(node, inst, "stop")


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
            # Check systemd status via SSH or local
            active = _check_service_active(node, inst)
            if active and not comfyui_up(inst["url"]):
                add_log("warn", "dead", f"Instance {name} unresponsive, restarting...")
                _run_instance_action(node, inst, "restart")
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
                cmd = ["sshpass", "-p", ssh["password"], "ssh", f"{ssh.get('user', 'root')}@{node['host']}"]
            else:
                cmd = ["ssh", f"{ssh.get('user', 'root')}@{node['host']}"]
            cmd += ["-p", str(ssh.get("port", 22)), "systemctl", "--user", "is-active", svc]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return r.stdout.strip() == "active"
    except Exception:
        pass
    return False

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
                            _run_instance_action(node, inst, "stop")
                        break
            save_jobs()
            asyncio.ensure_future(broadcast({"type": "job_update", "job": j}))



@asynccontextmanager
async def lifespan(app: FastAPI):
    global _inst_mgr, _job_runner
    _load_recent_logs()
    load_jobs()
    load_history()
    os.makedirs(HISTORY_DIR, exist_ok=True)
    _init_gen_db()
    os.makedirs(WORKFLOW_DIR, exist_ok=True)
    _refresh_instance_state()
    _inst_mgr = InstanceManager(_get_enabled_instances)
    _inst_mgr._get_node_by_id = _get_node_by_id
    _inst_mgr._run_instance_action = _run_instance_action
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
        run_instance_action_fn=_run_instance_action,
        instance_semas=_instance_semas,
        instance_group=_instance_group,
        instance_last_active=_instance_last_active,
        output_dir=OUTPUT_DIR,
        history_dir=HISTORY_DIR,
        get_enabled_instances_fn=_get_generation_instances,
        insert_gen_fn=_insert_generation,
        input_dir=COMFYUI_INPUT,
    )
    # Start the sequential job queue worker
    _background_tasks.append(asyncio.create_task(_queue_worker()))
    _background_tasks.append(asyncio.create_task(_dead_instance_watcher()))
    _background_tasks.append(asyncio.create_task(_idle_instance_watcher()))
    _background_tasks.append(asyncio.create_task(_stuck_job_watcher()))
    yield

app = FastAPI(title="Ez ComfyUI Showcase", version=APP_VERSION, lifespan=lifespan)

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

def get_gpu_stats() -> dict:
    """Return GPU memory/util/temp.  GB10 unified memory → /proc/meminfo.  Cached 3 s."""
    now = time.time()
    if gpu_cache["data"] and now - gpu_cache["ts"] < 3:
        return gpu_cache["data"]

    temp, util = 0, 0
    mem_used_mb, mem_total_mb = 0, 1

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
        temp = int(float(parts[2])) if parts[2] not in ('[N/A]','[N/A ]','N/A') else 0
        util = int(float(parts[3])) if parts[3] not in ('[N/A]','[N/A ]','N/A') else 0
        if raw_used not in ('[N/A]','[N/A ]','N/A'):
            mem_used_mb = float(raw_used)
        if raw_total not in ('[N/A]','[N/A ]','N/A'):
            mem_total_mb = float(raw_total)
    except Exception:
        pass

    if mem_used_mb == 0 and mem_total_mb <= 1:
        try:
            out = subprocess.check_output(
                ["sh", "-lc", "command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi --query-gpu=memory.used,memory.total,temperature.gpu,utilization.gpu --format=csv,noheader,nounits | head -n 1"],
                text=True, timeout=5,
            ).strip()
            if out:
                parts = [x.strip() for x in out.split(",")]
                raw_used, raw_total = parts[0], parts[1]
                temp = int(float(parts[2])) if parts[2] not in ('[N/A]','[N/A ]','N/A') else temp
                util = int(float(parts[3])) if parts[3] not in ('[N/A]','[N/A ]','N/A') else util
                if raw_used not in ('[N/A]','[N/A ]','N/A'):
                    mem_used_mb = float(raw_used)
                if raw_total not in ('[N/A]','[N/A ]','N/A'):
                    mem_total_mb = float(raw_total)
        except Exception:
            pass

    # GB10 unified memory: use /proc/meminfo
    try:
        mi = Path("/proc/meminfo").read_text()
        total_kb = int(re.search(r"MemTotal:\s+(\d+)", mi).group(1))
        avail_kb = int(re.search(r"MemAvailable:\s+(\d+)", mi).group(1))
        mem_total_mb = total_kb / 1024
        mem_used_mb = (total_kb - avail_kb) / 1024
    except Exception:
        pass

    if mem_used_mb == 0 and mem_total_mb <= 1:
        try:
            mem_total_mb = float(os.environ.get("EZ_GPU_TOTAL_MB", "0") or 0)
            mem_used_mb = float(os.environ.get("EZ_GPU_USED_MB", "0") or 0)
            temp = temp or int(float(os.environ.get("EZ_GPU_TEMP_C", "0") or 0))
            util = util or int(float(os.environ.get("EZ_GPU_UTIL_PCT", "0") or 0))
        except Exception:
            pass

    pct = round(mem_used_mb / mem_total_mb * 100, 1) if mem_total_mb else 0
    data = {
        "vram_used_mb": round(mem_used_mb),
        "vram_total_mb": round(mem_total_mb),
        "vram_pct": pct,
        "temp_c": temp,
        "util_pct": util,
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
        "message": message,
        "detail": detail,
    }


def _parse_nvidia_smi_stats(out: str) -> dict:
    line = (out or "").strip().splitlines()[0] if (out or "").strip() else ""
    if not line:
        return _empty_gpu_stats("VRAM 未上报")
    parts = [x.strip() for x in line.split(",")]
    if len(parts) < 4:
        return _empty_gpu_stats("VRAM 未上报")
    raw_used, raw_total, raw_temp, raw_util = parts[:4]
    used = 0 if raw_used in ("[N/A]", "[N/A ]", "N/A") else float(raw_used or 0)
    total = 0 if raw_total in ("[N/A]", "[N/A ]", "N/A") else float(raw_total or 0)
    temp = 0 if raw_temp in ("[N/A]", "[N/A ]", "N/A") else int(float(raw_temp or 0))
    util = 0 if raw_util in ("[N/A]", "[N/A ]", "N/A") else int(float(raw_util or 0))
    pct = round(used / total * 100, 1) if total else 0
    return {
        "vram_used_mb": round(used),
        "vram_total_mb": round(total),
        "vram_pct": pct,
        "temp_c": temp,
        "util_pct": util,
        "message": "",
        "detail": "",
    }


def _build_ssh_command(node: dict, remote_args: list[str]) -> list[str]:
    ssh = _resolve_ssh_config(node.get("ssh_config", {}))
    if ssh.get("auth") == "password" and ssh.get("password"):
        cmd = [
            "sshpass", "-p", ssh["password"], "ssh",
            f"{ssh.get('user', 'root')}@{node['host']}",
        ]
    else:
        cmd = ["ssh", f"{ssh.get('user', 'root')}@{node['host']}"]
    return cmd + ["-p", str(ssh.get("port", 22))] + remote_args


def _parse_meminfo_stats(out: str, base: dict | None = None) -> dict:
    base = dict(base or _empty_gpu_stats())
    try:
        total = re.search(r"MemTotal:\s+(\d+)", out or "")
        avail = re.search(r"MemAvailable:\s+(\d+)", out or "")
        if not total or not avail:
            return base
        total_mb = int(total.group(1)) / 1024
        used_mb = total_mb - (int(avail.group(1)) / 1024)
        pct = round(used_mb / total_mb * 100, 1) if total_mb else 0
        base.update({
            "vram_used_mb": round(used_mb),
            "vram_total_mb": round(total_mb),
            "vram_pct": pct,
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
    mem_cmd = _build_ssh_command(node, ["cat", "/proc/meminfo"])
    mem = subprocess.run(mem_cmd, capture_output=True, text=True, timeout=8)
    if mem.returncode == 0:
        return _parse_meminfo_stats(mem.stdout, data)
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
    if cached and now - cached.get("ts", 0) < 5:
        return cached["data"]
    try:
        data = _run_remote_gpu_query(node)
    except Exception as e:
        data = _empty_gpu_stats("VRAM 暂不可用", str(e)[:240])
    node_gpu_cache[key] = {"ts": now, "data": data}
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


def _mark_aux_instance_active(instance: dict) -> None:
    name = str((instance or {}).get("name") or "")
    if name:
        _instance_last_active[name] = time.time()


def _ensure_aux_instance_ready(
    instance: dict,
    phase: str,
    timeout: float = 180.0,
    poll_interval: float = 2.0,
) -> dict:
    """Ensure a non-generation ComfyUI task has a live instance before submit."""
    inst = dict(instance or {})
    url = inst.get("url", "")
    name = inst.get("name", "unknown")
    if url and comfyui_up(url):
        _mark_aux_instance_active(inst)
        return inst

    node = _get_node_by_id(inst.get("_node_id", ""))
    conn = (node or {}).get("connection") or inst.get("_node_connection", "local")
    if conn == "remote-http":
        raise RuntimeError(f"实例 {name} 当前不可用，HTTP 远程实例不能自动启动")
    if not node:
        raise RuntimeError(f"实例 {name} 缺少设备信息，无法自动启动")

    add_log("info", phase, f"启动 ComfyUI 实例 {name}...", details="coldstart")
    if not _run_instance_action(node, inst, "start"):
        raise RuntimeError(f"实例 {name} 启动命令失败")

    deadline = time.time() + float(timeout or 180.0)
    interval = max(0.2, float(poll_interval or 2.0))
    while time.time() < deadline:
        if url and comfyui_up(url):
            _mark_aux_instance_active(inst)
            add_log("info", phase, f"ComfyUI 实例 {name} 已就绪", details="coldstart")
            return inst
        time.sleep(interval)
    raise TimeoutError(f"实例 {name} 启动后未就绪")


def _pick_ready_aux_instance(instances: list[dict], phase: str, timeout: float = 180.0) -> dict:
    """Pick a reserved auxiliary instance and cold-start it when needed."""
    aux_instances = _get_prompt_aux_instances(instances)
    if not aux_instances:
        raise RuntimeError("未配置提示词独立实例，请新增独立 ComfyUI 入口并为实例设置 roles: ['prompt_aux']")
    errors = []
    for inst in sorted(aux_instances, key=lambda item: _get_instance_queue_size(item.get("url", ""))):
        try:
            return _ensure_aux_instance_ready(inst, phase=phase, timeout=timeout)
        except Exception as e:
            errors.append(f"{inst.get('name', '?')}: {e}")
            add_log("warn", phase, f"实例 {inst.get('name', '?')} 不可用: {e}")
    detail = "；".join(errors) if errors else "无候选实例"
    raise RuntimeError(f"没有可用的提示词独立实例: {detail}")


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


def vllm_running() -> bool:
    try:
        out = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", VLLM_CONTAINER],
            capture_output=True, text=True, timeout=5,
        )
        return "true" in out.stdout.lower()
    except Exception:
        return False


def stop_vllm():
    subprocess.run(["docker", "stop", VLLM_CONTAINER], capture_output=True, timeout=60)


def start_vllm():
    subprocess.Popen(["docker", "start", VLLM_CONTAINER],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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


def _download_remote_images_sync(job_id: str, prompt_id: str, base_url: str, output_dir: str) -> list:
    """Download output images from remote ComfyUI after generation.
    Returns list of local file paths that were downloaded."""
    try:
        history = comfyui_get(f"/history/{prompt_id}", base_url=base_url)
        if not history or prompt_id not in history:
            print(f"[download] No history entry for {prompt_id}")
            return []
        outputs = history[prompt_id].get("outputs", {})
        images = []
        for node_id, node_out in outputs.items():
            for img in node_out.get("images", []):
                images.append(img)
        if not images:
            print(f"[download] No output images in history for {prompt_id}")
            return []
        downloaded = []
        for img in images:
            filename = img["filename"]
            subfolder = img.get("subfolder", "")
            img_type = img.get("type", "output")
            local_path = os.path.join(output_dir, filename)
            # Skip if already exists locally
            if os.path.isfile(local_path):
                downloaded.append(local_path)
                continue
            view_url = f"{base_url}/view?filename={filename}&subfolder={subfolder}&type={img_type}"
            try:
                with urllib.request.urlopen(view_url, timeout=120) as resp:
                    if resp.status == 200:
                        os.makedirs(os.path.dirname(local_path), exist_ok=True)
                        with open(local_path, "wb") as f:
                            f.write(resp.read())
                        downloaded.append(local_path)
                        print(f"[download] Saved {filename} ({len(downloaded)}/{len(images)})")
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


def _active_prompt_ids_for_instance(instance_name: str) -> set[str]:
    return {
        str(job.get("prompt_id") or "")
        for job in jobs.values()
        if _job_is_active_for_instance(job, instance_name) and job.get("prompt_id")
    }


def _untracked_remote_prompt_ids(instance_name: str, remote_queue: dict) -> list[str]:
    known = _active_prompt_ids_for_instance(instance_name)
    remote_ids = list(remote_queue.get("running_prompt_ids") or []) + list(remote_queue.get("pending_prompt_ids") or [])
    return [pid for pid in remote_ids if pid and pid not in known]


def _cleanup_untracked_remote_prompts(inst: dict, remote_queue: dict) -> list[str]:
    """Reject remote ComfyUI prompts that are not tracked by this frontend/backend job system."""
    prompt_ids = _untracked_remote_prompt_ids(inst.get("name", ""), remote_queue)
    if not prompt_ids:
        return []
    key = f"{inst.get('name', '')}:{','.join(prompt_ids)}"
    now = time.time()
    if now - _untracked_remote_cleanup_at.get(key, 0) < 15:
        return prompt_ids
    _untracked_remote_cleanup_at[key] = now
    base_url = inst.get("url", "")
    try:
        comfyui_post("/queue", {"delete": prompt_ids}, base_url=base_url)
    except Exception:
        pass
    try:
        comfyui_post("/interrupt", {}, base_url=base_url)
    except Exception:
        pass
    add_log(
        "warn",
        "queue",
        f"已拒绝未追踪远端任务: {inst.get('name', '')}",
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
    "SeedVR2VideoUpscaler": {
        "seed":       {"type": "seed",   "label": "超分种子", "min": 0, "max": 4294967295},
        "resolution": {"type": "number", "label": "超分分辨率", "min": 512, "max": 8192, "step": 64},
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
    if ct == "KSampler":
        return ("advanced", True)
    if ct in ("EmptySD3LatentImage", "EmptyLatentImage"):
        return ("advanced", True)
    if ct == "SaveImage":
        return ("output", True)
    if ct in ("SeedVR2VideoUpscaler",):
        return ("advanced", True)
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
    fields = []
    for field_cfg in config.get("fields", []):
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
    "VAEDecode": "解码图像...",
    "VAEEncode": "编码图像...",
    "ImageUpscaleWithModel": "超分辨率放大...",
    "SeedVR2VideoUpscaler": "超分辨率放大...",
    "ImageScaleBy": "图像缩放...",
    "ImageScale": "图像缩放...",
    "ImageCompositeMasked": "合成图像...",
    "SaveImage": "保存图像...",
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
                _run_instance_action(node, inst, "start")
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
            jobs[job_id]["message"] = "正在拉取图片..."
            await broadcast({"type": "job_update", "job": jobs[job_id]})

            downloaded = await asyncio.to_thread(
                _download_remote_images_sync, job_id, pid, inst_url, OUTPUT_DIR
            )
            if downloaded:
                print(f"[generate] Downloaded {len(downloaded)} image(s) for {job_id[-12:]}")

        if job_id not in jobs:
            return False, pid or ""

        if not ws_ok:
            _extra = jobs[job_id].get("ws_error", "") if job_id in jobs else ""
            raise TimeoutError(f"出图失败{' ('+_extra[:100]+')' if _extra else ''}")

        sources = []
        if downloaded:
            for path in downloaded:
                if path and os.path.isfile(path):
                    sources.append((path, os.path.basename(path)))
        if not sources:
            try:
                hist = comfyui_get(f"/history/{pid}", base_url=inst_url)
                if pid in hist:
                    for node_out in hist[pid].get("outputs", {}).values():
                        for img in node_out.get("images", []):
                            filename = img.get("filename", "")
                            if not filename:
                                continue
                            src = os.path.join(OUTPUT_DIR, filename)
                            if not os.path.isfile(src):
                                matches = glob.glob(os.path.join(OUTPUT_DIR, "**", filename), recursive=True)
                                if matches:
                                    src = matches[0]
                            if os.path.isfile(src):
                                sources.append((src, filename))
            except Exception as e:
                raise RuntimeError(_friendly_generation_error(e))
        if job_id not in jobs or jobs[job_id].get("status") == "error":
            return False, pid or ""
        deduped = []
        seen_paths = set()
        for src, filename in sources:
            real_path = os.path.abspath(src)
            if real_path in seen_paths or not os.path.isfile(src):
                continue
            seen_paths.add(real_path)
            deduped.append((src, filename or os.path.basename(src)))
        sources = deduped
        if not sources:
            raise RuntimeError("未找到输出图片")

        gen_user_id = jobs[job_id].get("user_id", "anonymous") if job_id in jobs else "anonymous"
        date_str = datetime.now().strftime("%Y-%m-%d")
        subdir = f"{gen_user_id}/{date_str}"

        wf_basename = os.path.basename(workflow_path).replace('.json', '')
        # Find next sequential number for this workflow today
        existing = glob.glob(os.path.join(OUTPUT_DIR, subdir, f"{wf_basename}_*.png"))
        seq = 1
        for p in existing:
            m = re.search(rf"{re.escape(wf_basename)}_(\d+)\.png$", os.path.basename(p))
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
        for idx, (src, filename) in enumerate(sources):
            hist_name = f"{wf_basename}_{seq + idx:04d}.png"
            shutil.copy2(src, os.path.join(output_subdir, hist_name))
            rel_path = f"{subdir}/{hist_name}"
            actual_w, actual_h = get_image_size(rel_path)
            thumb_rel = make_thumbnail(rel_path) or ""
            records.append({
                "id": job_id if idx == 0 else f"{job_id}_{idx + 1:02d}",
                "filename": rel_path,
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
            status="done", message=f"完成 ({elapsed:.1f}s)",
            image=cover.get("filename", ""),
            thumb=cover.get("thumb", ""),
            images=[record.get("filename", "") for record in records],
            thumbs=[record.get("thumb", "") for record in records],
            batch_id=job_id if batch_count > 1 else "",
            batch_count=batch_count,
            batch_items=records,
            elapsed=round(elapsed, 1),
        )
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
    active = {k: v for k, v in jobs.items() if v.get("status") not in ("done", "error")}
    try:
        with open(JOBS_FILE, "w") as f:
            json.dump(list(active.values()), f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_jobs():
    if os.path.isfile(JOBS_FILE):
        try:
            os.remove(JOBS_FILE)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════
#  History
# ══════════════════════════════════════════════════════════════════════════

HISTORY_FILE = os.path.join(HISTORY_DIR, "history.json")
THUMB_SIZE = 400


def _project_ffmpeg_bin() -> str | None:
    """Return an explicitly configured or project-local ffmpeg binary."""
    configured = os.environ.get("EZ_COMFYUI_FFMPEG", "")
    candidates = [
        configured,
        os.path.join(_BASE, ".venv", "bin", "ffmpeg"),
        os.path.join(_BASE, "bin", "ffmpeg"),
        os.path.join(_BASE, "tools", "ffmpeg", "ffmpeg"),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _make_thumbnail_with_pillow(src: str, thumb_path: str) -> bool:
    """Create a thumbnail using the project Python environment."""
    try:
        from PIL import Image, ImageOps
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
    """Get PNG image dimensions from OUTPUT_DIR/{rel_path}."""
    path = os.path.join(OUTPUT_DIR, rel_path)
    if not os.path.isfile(path):
        return 0, 0
    try:
        with open(path, "rb") as f:
            f.seek(16)
            buf = f.read(8)
            w = int.from_bytes(buf[0:4], "big")
            h = int.from_bytes(buf[4:8], "big")
            return w, h
    except Exception:
        return 0, 0


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
        if not h.get("width") or not h.get("height"):
            w, ht = get_image_size(h.get("filename", ""))
            if w > 0:
                h["width"] = w
                h["height"] = ht
                changed = True
        if not h.get("thumb"):
            thumb = make_thumbnail(h.get("filename", ""))
            if thumb:
                h["thumb"] = thumb
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


class PromptInterrogateRequest(BaseModel):
    image: str


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
    visible_instances = _get_enabled_instances_for_user(current_user)
    node_gpu = _gpu_stats_for_status_node(visible_instances, target_node_id, target_instance)
    for inst in visible_instances:
        node_id = inst.get("_node_id", "")
        remote_queue = _get_instance_queue_counts(inst["url"])
        grp = _instance_group.get(inst["name"], "")
        name = inst["name"]
        is_prompt_aux = _is_prompt_aux_instance(inst)
        inst_jobs = [j for j in jobs.values() if j.get("instance") == name and j.get("status") in ACTIVE_JOB_STATUSES]
        local_run = len([j for j in inst_jobs if j["status"] in ("dispatching", "starting_comfyui", "submitting", "generating", "downloading")])
        local_pend = len([j for j in inst_jobs if j["status"] in ("queued", "preparing")])
        untracked_remote_ids = [] if is_prompt_aux else _cleanup_untracked_remote_prompts(inst, remote_queue)
        q_run = max(local_run, remote_queue["running"])
        q_pend = max(local_pend, remote_queue["pending"])
        q_size = max(remote_queue["total"], q_run + q_pend)
        current_job = _current_job_for_instance(name)
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
            "role": "prompt_aux" if is_prompt_aux else "generation",
            "prompt_aux": is_prompt_aux,
            "up": comfyui_up(base_url=inst["url"]),
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
def api_gpu():
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
                _run_instance_action(node, inst, "start")
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
                _run_instance_action(node, inst, "stop")
            else:
                svc = f"comfyui-{inst['name'].lower()}"
                subprocess.run(["systemctl", "--user", "stop", svc], capture_output=True, timeout=5)
            _instance_group[inst["name"]] = ""
            results.append(f"{inst['name']} 已停止")
            for jid, jb in list(jobs.items()):
                if jb.get("instance") == inst["name"] and jb.get("status") in ACTIVE_JOB_STATUSES:
                    jb["status"] = "error"
                    jb["message"] = "实例已停止"
        return {"ok": True, "msg": "; ".join(results)}
    raise HTTPException(400)



@app.get("/api/gpu-processes")
def api_gpu_processes():
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
    visible_instances = _get_enabled_instances_for_user(current_user)
    node_gpu = _gpu_stats_for_status_node(visible_instances)
    for inst in visible_instances:
        name = inst["name"]
        node_id = inst.get("_node_id", "")
        svc = f"comfyui-{name.lower()}"
        is_active = comfyui_up(base_url=inst["url"])
        remote_queue = _get_instance_queue_counts(inst["url"])
        inst_jobs = [j for j in jobs.values() if _job_is_active_for_instance(j, name)]
        local_running = len([j for j in inst_jobs if j["status"] in ("generating", "dispatching", "starting_comfyui", "downloading")])
        local_pending = len([j for j in inst_jobs if j["status"] in ("queued", "preparing")])
        queue_running = max(local_running, remote_queue["running"])
        queue_pending = max(local_pending, remote_queue["pending"])
        queue_total = max(remote_queue["total"], queue_running + queue_pending)
        grp = _instance_group.get(name, "")
        is_prompt_aux = _is_prompt_aux_instance(inst)
        current_job = _current_job_for_instance(name)
        untracked_remote_ids = [] if is_prompt_aux else _cleanup_untracked_remote_prompts(inst, remote_queue)
        remote_untracked_running = bool(untracked_remote_ids) and not current_job
        current_label = ""
        current_workflow = ""
        pending_workflows = []
        if current_job:
            workflow_name = (current_job.get("workflow") or "").replace(".json", "")
            current_workflow = workflow_name
            prompt_preview = current_job.get("prompt_preview", "")
            current_label = prompt_preview[:60] if prompt_preview else workflow_name
        for j in jobs.values():
            if j.get("instance") == name and j.get("status") in ("queued", "preparing", "starting_comfyui"):
                wf = (j.get("workflow") or "").replace(".json", "")
                if wf:
                    pending_workflows.append(wf)
        result.append({
            "name": name, "up": is_active, "service": svc,
            "node_id": inst.get("_node_id", ""),
            "node_name": inst.get("_node_name", ""),
            "node_connection": inst.get("_node_connection", "local"),
            "role": "prompt_aux" if is_prompt_aux else "generation",
            "prompt_aux": is_prompt_aux,
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
            _run_instance_action(node, inst, "start")
        else:
            svc = f"comfyui-{inst['name'].lower()}"
            subprocess.run(["systemctl", "--user", "start", svc], capture_output=True, timeout=5, env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus", "XDG_RUNTIME_DIR": "/run/user/1000"})
        return {"ok": True, "msg": f"{inst['name']} 启动中"}
    elif action == "stop":
        if node:
            _run_instance_action(node, inst, "stop")
        else:
            svc = f"comfyui-{inst['name'].lower()}"
            subprocess.run(["systemctl", "--user", "stop", svc], capture_output=True, timeout=5)
        _instance_group[inst["name"]] = ""
        for jid, jb in list(jobs.items()):
            if jb.get("instance") == inst["name"] and jb.get("status") in ("generating", "dispatching", "preparing"):
                jb["status"] = "error"
                jb["message"] = "实例已停止"
        return {"ok": True, "msg": f"{inst['name']} 已停止"}
    raise HTTPException(400)


@app.post("/api/vllm/{action}")
def api_vllm(action: str, current_user: dict = Depends(require_admin)):
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
def api_workflow_config_get(name: str):
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
    name = file.filename
    if not name.endswith(".json"):
        raise HTTPException(400, "需要 .json 文件")
    content = await file.read()
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
def api_workflow_dirs():
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
_UPLOAD_FORMAT_EXTS = {
    "PNG": {".png"},
    "JPEG": {".jpg", ".jpeg"},
    "WEBP": {".webp"},
    "BMP": {".bmp"},
}
_UPLOAD_SAFE_PASSTHROUGH_MODES = {"RGB", "RGBA", "L", "LA", "P"}


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
    content = await file.read()
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
        raise HTTPException(500, f"Image upload failed: {e}")
    return {"ok": True, "filename": rel_name, "path": dest}


@app.get("/api/input-image/{filename:path}")
def api_input_image(filename: str):
    safe = filename.replace("\\", "/").lstrip("/")
    path = _resolve_input_image_path(safe)
    if not path:
        raise HTTPException(404)
    ext = os.path.splitext(path)[1].lower()
    media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".bmp": "image/bmp"}.get(ext, "application/octet-stream")
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
    content = await file.read()
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
    return FileResponse(path, media_type=media)


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
    instances = _get_enabled_instances()
    if not instances:
        raise HTTPException(503, "No enabled ComfyUI instances available")
    try:
        inst = _pick_ready_aux_instance(instances, "prompt_optimize", timeout=180)
        result = run_prompt_optimizer(
            prompt,
            inst.get("url", COMFYUI_URL),
            comfyui_post,
            comfyui_get,
            timeout=300,
            poll_interval=1,
            max_new_tokens=req.max_new_tokens,
        )
        _mark_aux_instance_active(inst)
    except TimeoutError as e:
        add_log("error", "prompt_optimize", str(e), details=f"user={_user_id(current_user)}")
        raise HTTPException(504, f"提示词优化超时: {e}") from e
    except RuntimeError as e:
        add_log("error", "prompt_optimize", str(e), details=f"user={_user_id(current_user)}")
        status_code = 503 if "提示词独立实例" in str(e) else 500
        raise HTTPException(status_code, f"提示词优化失败: {e}") from e
    except Exception as e:
        add_log("error", "prompt_optimize", str(e), details=f"user={_user_id(current_user)}")
        raise HTTPException(500, f"提示词优化失败: {e}") from e
    result["instance"] = inst.get("name", "")
    add_log("info", "prompt_optimize", f"Prompt optimized by {result.get('provider', 'unknown')}", details=f"user={_user_id(current_user)}")
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
    instances = _get_enabled_instances()
    if not instances:
        raise HTTPException(503, "No enabled ComfyUI instances available")
    try:
        inst = _pick_ready_aux_instance(instances, "prompt_translate", timeout=180)
        result = run_prompt_language_switcher(
            prompt,
            target,
            inst.get("url", COMFYUI_URL),
            comfyui_post,
            comfyui_get,
            timeout=180,
            poll_interval=1,
            max_new_tokens=req.max_new_tokens,
        )
        _mark_aux_instance_active(inst)
    except TimeoutError as e:
        add_log("error", "prompt_translate", str(e), details=f"user={_user_id(current_user)}")
        raise HTTPException(504, f"提示词翻译超时: {e}") from e
    except RuntimeError as e:
        add_log("error", "prompt_translate", str(e), details=f"user={_user_id(current_user)}")
        status_code = 503 if "提示词独立实例" in str(e) else 500
        raise HTTPException(status_code, f"提示词翻译失败: {e}") from e
    except Exception as e:
        add_log("error", "prompt_translate", str(e), details=f"user={_user_id(current_user)}")
        raise HTTPException(500, f"提示词翻译失败: {e}") from e
    result["instance"] = inst.get("name", "")
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
    if not _resolve_input_image_path(image):
        raise HTTPException(404, "Image not found")
    instances = _get_enabled_instances()
    if not instances:
        raise HTTPException(503, "No enabled ComfyUI instances available")
    try:
        inst = _pick_ready_aux_instance(instances, "prompt_interrogate", timeout=180)
        inst_url = inst.get("url", COMFYUI_URL)
        prepared_image = prepare_interrogate_image(image, COMFYUI_INPUT)
        image_for_interrogate = prepared_image.get("filename") or image
        workflow = build_image_interrogate_workflow(image_for_interrogate)
        ensure_workflow_images_available(workflow, COMFYUI_INPUT, inst_url)
        result = run_image_interrogator(
            image_for_interrogate,
            inst_url,
            comfyui_post,
            comfyui_get,
            timeout=180,
            poll_interval=1,
        )
        _mark_aux_instance_active(inst)
        result["image_preprocess"] = prepared_image
        prompt_text = str(result.get("prompt") or "").strip()
        if prompt_text and not result.get("prompt_zh"):
            try:
                translated = run_prompt_translator(
                    prompt_text,
                    inst_url,
                    comfyui_post,
                    comfyui_get,
                    timeout=90,
                    poll_interval=1,
                    max_new_tokens=192,
                )
                prompt_zh = normalize_interrogated_chinese_prompt(translated.get("prompt_zh", ""))
                if prompt_zh:
                    result["prompt_zh"] = prompt_zh
                    result["prompt_en"] = prompt_text
                    result["translator_provider"] = translated.get("provider", "")
            except Exception as translate_error:
                add_log("warn", "prompt_interrogate", f"Prompt Chinese translation skipped: {translate_error}", details=f"user={_user_id(current_user)}")
        if prompt_text and not result.get("structured_prompt_json"):
            source_prompt = str(result.get("prompt_zh") or prompt_text).strip()
            if source_prompt:
                try:
                    structured = run_prompt_optimizer(
                        source_prompt,
                        inst_url,
                        comfyui_post,
                        comfyui_get,
                        timeout=180,
                        poll_interval=1,
                        max_new_tokens=384,
                    )
                    if structured.get("structured_prompt_json"):
                        result["structured_prompt_json"] = structured.get("structured_prompt_json")
                    if structured.get("structured_prompt"):
                        result["structured_prompt"] = structured.get("structured_prompt")
                    if structured.get("optimized_prompt"):
                        result["structured_optimized_prompt"] = structured.get("optimized_prompt")
                    if structured.get("provider"):
                        result["structured_provider"] = structured.get("provider")
                except Exception as structure_error:
                    add_log("warn", "prompt_interrogate", f"Prompt JSON structure skipped: {structure_error}", details=f"user={_user_id(current_user)}")
    except TimeoutError as e:
        add_log("error", "prompt_interrogate", str(e), details=f"user={_user_id(current_user)}")
        raise HTTPException(504, f"图片反推超时: {e}") from e
    except RuntimeError as e:
        add_log("error", "prompt_interrogate", str(e), details=f"user={_user_id(current_user)}")
        status_code = 503 if "提示词独立实例" in str(e) else 500
        raise HTTPException(status_code, f"图片反推失败: {e}") from e
    except Exception as e:
        add_log("error", "prompt_interrogate", str(e), details=f"user={_user_id(current_user)}")
        raise HTTPException(500, f"图片反推失败: {e}") from e
    result["instance"] = inst.get("name", "")
    add_log("info", "prompt_interrogate", f"Image interrogated by {result.get('provider', 'unknown')}", details=f"user={_user_id(current_user)}")
    return result


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
    seed = req.seed if req.seed is not None else random.randint(0, 2**63)
    vllm_was = vllm_running()

    try:
        with open(path) as f:
            wf_check = json.load(f)
        normalized_fields = _normalize_workflow_field_values(wf_check, req.fields)
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
    add_log("info", "queue", f"Job queued: {req.workflow}", job_id)

    _job_queue.put_nowait((
        job_id, path, normalized_fields, seed, vllm_was, req.width, req.height, user_id,
        req.preferred_instance or "", req.preferred_node_id or ""
    ))
    return {"job_id": job_id, "seed": seed}


@app.get("/api/jobs")
def api_all_jobs(current_user: dict = Depends(get_current_user)):
    return [j for j in jobs.values() if _can_access_job(j, current_user)]


@app.get("/api/jobs/{job_id}")
def api_job_status(job_id: str, current_user: dict = Depends(get_current_user)):
    if job_id not in jobs:
        raise HTTPException(404)
    if not _can_access_job(jobs[job_id], current_user):
        raise HTTPException(403, "无权访问他人的任务")
    return jobs[job_id]


@app.delete("/api/jobs/{job_id}")
async def api_cancel_job(job_id: str, current_user: dict = Depends(get_current_user)):
    if job_id not in jobs:
        raise HTTPException(404)
    job = jobs[job_id]
    if not _can_access_job(job, current_user):
        raise HTTPException(403, "只能取消自己的任务")
    if job.get("status") == "generating":
        try:
            inst_url = None
            inst_name = job.get("instance", "")
            for inst in _get_enabled_instances():
                if inst.get("name") == inst_name:
                    inst_url = inst.get("url")
                    break
            comfyui_post("/interrupt", {}, base_url=inst_url)
        except Exception:
            pass
    task = _job_tasks.get(job_id)
    if task and not task.done():
        task.cancel()
    _job_tasks.pop(job_id, None)
    del jobs[job_id]
    save_jobs()
    await broadcast({"type": "job_cancelled", "job_id": job_id})
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
    except Exception:
        pass

    del jobs[job_id]

    new_id = f"job_{int(time.time()*1000)}_{random.randint(1000,9999)}"
    vllm_was = vllm_running()

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
        "queued_at": datetime.now().strftime("%H:%M:%S"),
    }

    _job_queue.put_nowait((
        new_id, path, fields, seed, vllm_was, width, height, user_id,
        preferred_instance, preferred_node_id
    ))
    return {"job_id": new_id, "seed": seed}


# ══════════════════════════════════════════════════════════════════════════
#  API: History
# ══════════════════════════════════════════════════════════════════════════

@app.get("/api/history")
def api_history(limit: int = 50, offset: int = 0, status: str = "", scope: str = "gallery", current_user: dict | None = Depends(get_current_user_optional)):
    """Query generation history from SQLite with pagination."""
    conn = sqlite3.connect(GEN_DB)
    conn.row_factory = sqlite3.Row
    uid = _user_id(current_user or {})
    trash_mode = scope == "trash"
    if trash_mode and not current_user:
        conn.close()
        raise HTTPException(401, "Not authenticated")
    if current_user and trash_mode and current_user.get("role") == "admin":
        conditions = []
        params = []
    elif current_user and trash_mode:
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
    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = [
        dict(r) for r in conn.execute(
            "SELECT generations.*, generations.rowid AS history_rowid FROM generations" +
            where_clause +
            " ORDER BY datetime(created_at) DESC, history_rowid DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
    ]
    thumb_updates = []
    for row in rows:
        if row.get("thumb_path") or not row.get("image_path"):
            continue
        thumb = make_thumbnail(row.get("image_path", "")) or ""
        if thumb:
            row["thumb_path"] = thumb
            thumb_updates.append((thumb, row.get("id", "")))
    if thumb_updates:
        conn.executemany("UPDATE generations SET thumb_path=? WHERE id=?", thumb_updates)
        conn.commit()
    total = conn.execute(
        "SELECT COUNT(*) FROM generations" + where_clause,
        params,
    ).fetchone()[0]
    conn.close()
    usernames = _history_username_map([r.get("user_id", "") for r in rows])
    for row in rows:
        row["username"] = usernames.get(row.get("user_id", ""), "")
    return {"ok": True, "data": [_gen_db_to_record(r) for r in rows], "total": total}


@app.post("/api/history")
def api_history_create(req: dict, current_user: dict = Depends(get_current_user)):
    """Insert a generation record into SQLite."""
    elapsed = req.get("duration_sec", req.get("elapsed", 0))
    _insert_generation(req, elapsed, user_id=_user_id(current_user))
    return {"ok": True}


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


def _history_owner_check(conn, item_id: str, current_user: dict, allow_deleted: bool = False):
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT id, image_path, thumb_path, user_id, deleted_at, params FROM generations WHERE id=?", (item_id,)).fetchone()
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
    image_exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
    for key, value in params.items():
        if not isinstance(value, str):
            continue
        field = str(key).split("::", 1)[-1].lower()
        if not (field.startswith("image") or field == "upload"):
            continue
        rel = value.replace("\\", "/").lstrip("/")
        if rel.lower().endswith(image_exts):
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
def api_image(filename: str):
    """Serve generated images."""
    path = _safe_rel_path(OUTPUT_DIR, filename)
    if os.path.isfile(path):
        return FileResponse(path, media_type=_image_media_type(path, "image/png"))
    raise HTTPException(404)


@app.get("/api/thumbs/{filename:path}")
def api_thumb(filename: str):
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
    password: str = "admin"
    role: str = "user"


@app.post("/auth/register")
def auth_register(req: AuthRequest):
    username = req.username.strip()
    password = req.password
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
        conn.close()
        return {"id": user_id, "username": username, "role": role, "token": token}
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(409, "Username already exists")


@app.post("/auth/login")
def auth_login(req: AuthRequest):
    username = req.username.strip()
    password = req.password
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
    return {"id": row["id"], "username": row["username"], "role": row["role"], "token": token}


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
    password = req.password or "admin"
    role = req.role if req.role in ("admin", "user") else "user"
    if len(username) < 2:
        raise HTTPException(400, "Username too short")
    if len(password) < 5:
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


# ══════════════════════════════════════════════════════════════════════════
#  WebSocket
# ══════════════════════════════════════════════════════════════════════════

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    ws_user = _get_user_from_token(ws.query_params.get("token"))
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
        url = f"http://{node['host']}:{inst['port']}"
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
                   f"{ssh.get('user', 'root')}@{node['host']}",
                   "-p", str(ssh.get("port", 22)),
                   "-o", "ConnectTimeout=5", "echo", "ok"]
        else:
            cmd = ["ssh", f"{ssh.get('user', 'root')}@{node['host']}",
                   "-p", str(ssh.get("port", 22)),
                   "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
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
    url = f"http://{node['host']}:{instance['port']}"
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
    if node.get("connection") == "remote-http":
        raise HTTPException(400, "Cannot start instance via remote-http")
    if _run_instance_action(node, inst, "start"):
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
    if _run_instance_action(node, inst, "stop"):
        _instance_group[inst["name"]] = ""
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
    if _run_instance_action(node, inst, "restart"):
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
    if _run_instance_action(node, inst, "force-restart"):
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
        url = f"http://{node['host']}:{port}"
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
    content = await file.read(MAX_WORKFLOW_SIZE + 1)
    if len(content) > MAX_WORKFLOW_SIZE:
        raise HTTPException(413, "File too large")
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
