#!/usr/bin/env python3
"""
ComfyUI Web v3 — 三段式布局，GPU 监控，服务管理。
"""
import asyncio, json, os, glob, random, shutil, subprocess, time, uuid, re
# Ensure D-Bus session is available for systemctl --user calls in nohup context
os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
os.environ.setdefault("XDG_RUNTIME_DIR", "/run/user/1000")
import websockets.client
from datetime import datetime
from pathlib import Path
from contextlib import asynccontextmanager
from io import BytesIO

from fastapi import (
    FastAPI, HTTPException, BackgroundTasks, WebSocket,
    WebSocketDisconnect, UploadFile, File, Form
)
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn, urllib.request, urllib.error

# ── Logging ──
_log_buffer: list[dict] = []
_MAX_LOG = 500

def add_log(level: str, phase: str, msg: str, job_id: str = "", details: str = ""):
    entry = {"ts": time.time(), "level": level, "phase": phase,
             "msg": str(msg)[:200], "job_id": job_id[-12:], "details": str(details)[:500]}
    _log_buffer.append(entry)
    if len(_log_buffer) > _MAX_LOG:
        _log_buffer[:50] = []
    try:
        asyncio.ensure_future(broadcast({"type": "log", "entry": entry}))
    except Exception:
        pass



# ── 任务队列：per-instance semaphores for parallel routing ──
_job_queue: asyncio.Queue = asyncio.Queue()

async def _queue_worker():
    """Non-blocking dispatcher — spawns a task per job so per-instance semaphore waits don't block the queue."""
    while True:
        try:
            job_id, workflow_path, field_values, seed, vllm_was, img_w, img_h = await _job_queue.get()
            task = asyncio.create_task(_dispatch_and_run(job_id, workflow_path, field_values, seed, vllm_was, img_w, img_h))
            _job_tasks[job_id] = task
            task.add_done_callback(lambda _t, jid=job_id: _job_tasks.pop(jid, None))
        except Exception as e:
            print(f"[queue_worker] Error in dispatch loop: {e}")
            await asyncio.sleep(1)

async def _dispatch_and_run(job_id, workflow_path, field_values, seed, vllm_was, img_w, img_h):
    """Serialize: one job at a time globally, per-instance sem for ComfyUI safety."""
    sem = None
    global_held = False
    inst_held = False
    inst = None
    try:
        workflow_name = os.path.basename(workflow_path)
        jobs[job_id]["status"] = "dispatching"
        jobs[job_id]["last_update"] = time.time()
        jobs[job_id]["message"] = "排队等待..."
        await broadcast({"type": "job_update", "job": jobs[job_id]})

        # Phase 1: find the best instance
        inst = await pick_best_instance(workflow_name)
        sem = _instance_semas[inst["name"]]
        await _global_sem.acquire()
        global_held = True
        jobs[job_id]["message"] = f"匹配实例 {inst['name']}..."
        await broadcast({"type": "job_update", "job": jobs[job_id]})

        # Ensure instance is up (cold start if needed)
        if not await asyncio.to_thread(comfyui_up, inst["url"]):
            svc = f"comfyui-{inst['name'].lower()}"
            try:
                await asyncio.to_thread(subprocess.run, ["systemctl", "--user", "start", svc],
                    capture_output=True, timeout=30,
                    env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus", "XDG_RUNTIME_DIR": "/run/user/1000"})
                for _ in range(90):
                    if await asyncio.to_thread(comfyui_up, inst["url"]):
                        break
                    await asyncio.sleep(2)
            except Exception as e:
                print(f"[cold-start] {svc} error: {e}")

        # Phase 2: wait for instance semaphore
        jobs[job_id]["status"] = "queued"
        jobs[job_id]["last_update"] = time.time()
        jobs[job_id]["message"] = f"排队等待 {inst['name']}..."
        await broadcast({"type": "job_update", "job": jobs[job_id]})
        try:
            await asyncio.wait_for(sem.acquire(), timeout=600)
            inst_held = True
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

        jobs[job_id]["instance"] = inst["name"]
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
            sem.release()
        if global_held:
            _global_sem.release()
        _job_queue.task_done()

# ── Config ──────────────────────────────────────────────────────────────
COMFYUI_INSTANCES = [
    {"name": "A", "url": "http://127.0.0.1:8190", "output_dir": "/home/sjcta/software/ComfyUI-Project/outputs"},
    {"name": "B", "url": "http://127.0.0.1:8189", "output_dir": "/home/sjcta/software/ComfyUI-Project/outputs2"},
]
COMFYUI_URL = COMFYUI_INSTANCES[0]["url"]  # backward compat fallback
WORKFLOW_DIR  = "/home/sjcta/software/ComfyUI-Project/workflow/api"  # legacy default, kept for compat
OUTPUT_DIR    = "/home/sjcta/software/ComfyUI-Project/outputs"
COMFYUI_DIR   = "/home/sjcta/software/ComfyUI-Project"
COMFYUI_INPUT = "/home/sjcta/software/ComfyUI-Project/ComfyUI/input"
HISTORY_DIR   = "/home/sjcta/comfyui-web/history"
WF_META_FILE  = "/home/sjcta/comfyui-web/wf_meta.json"
WF_DIRS_FILE  = "/home/sjcta/comfyui-web/wf_dirs.json"   # persisted workflow search directories
WF_CONFIG_DIR = "/home/sjcta/comfyui-web/wf_configs"
os.makedirs(WF_CONFIG_DIR, exist_ok=True)
WF_THUMB_DIR  = "/home/sjcta/comfyui-web/thumbs/wf"
VLLM_CONTAINER = "qwen36-vllm"
JOBS_FILE     = "/home/sjcta/comfyui-web/jobs.json"
PORT = 9091
MAX_HISTORY = 200

# ── State ───────────────────────────────────────────────────────────────
jobs: dict[str, dict] = {}
_job_tasks: dict[str, asyncio.Task] = {}
history: list[dict] = []
ws_clients: list[WebSocket] = []
gpu_cache: dict = {"ts": 0, "data": None}

# ── Model Affinity Routing ──────────────────────────────────────────────
# Per-instance semaphores: one concurrent job per ComfyUI instance
_instance_semas: dict[str, asyncio.Semaphore] = {inst["name"]: asyncio.Semaphore(1) for inst in COMFYUI_INSTANCES}
_instance_last_active: dict[str, float] = {inst["name"]: 0 for inst in COMFYUI_INSTANCES}
# Sequential execution semaphore: one job at a time across ALL instances
_global_sem: asyncio.Semaphore = asyncio.Semaphore(1)

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
    """Extract the model group from a workflow filename.

    Examples:
      t2i-nunchaku-z-image-turbo-highSD.json → "nunchaku"  (nunchaku checked first)
      t2i-z-image-seedvr4k.json              → "z-image-turbo"
      t2i-z-xxx.json                         → "z-image-turbo"
      t2i_nunchaku_seedvr4k.json             → "nunchaku"
      upscale-seedvr-only.json               → "seedvr"
    """
    lower = workflow_name.lower()
    for group, keywords in MODEL_GROUPS:
        for kw in keywords:
            if kw in lower:
                return group
    return workflow_name  # unknown → exact match fallback

# Tracks which MODEL GROUP each instance currently has loaded.
# Key = instance name ("A"/"B"), value = model group ("nunchaku", "z-image-turbo", etc.) or "".
_instance_group: dict[str, str] = {inst["name"]: "" for inst in COMFYUI_INSTANCES}

def pick_affinity_instance(workflow_name: str) -> dict | None:
    """Return the instance whose loaded model group matches this workflow's group."""
    if not workflow_name:
        return None
    wf_group = extract_model_group(workflow_name)
    for inst in COMFYUI_INSTANCES:
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
        for inst in COMFYUI_INSTANCES:
            name = inst["name"]
            last = _instance_last_active.get(name, 0)
            if last == 0:
                continue
            active_jobs = [j for j in jobs.values() if j.get("instance") == name and j.get("status") in ("generating", "dispatching", "preparing", "queued")]
            if active_jobs:
                continue
            if now - last > IDLE_TIMEOUT:
                svc = f"comfyui-{name.lower()}"
                try:
                    proc = await asyncio.to_thread(subprocess.run, ["systemctl", "--user", "is-active", svc], capture_output=True, text=True, timeout=5,
                        env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus", "XDG_RUNTIME_DIR": "/run/user/1000"})
                    if proc.stdout.strip() == "active":
                        await asyncio.to_thread(subprocess.run, ["systemctl", "--user", "stop", svc], capture_output=True, timeout=10,
                            env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus", "XDG_RUNTIME_DIR": "/run/user/1000"})
                        print(f"[idle-watcher] Stopped idle instance {name} (idle {now - last:.0f}s)")
                except Exception:
                    pass


async def _dead_instance_watcher():
    while True:
        await asyncio.sleep(60)
        for inst in COMFYUI_INSTANCES:
            name = inst["name"]
            svc = "comfyui-" + name.lower()
            try:
                r = subprocess.run(["systemctl", "--user", "is-active", svc],
                    capture_output=True, text=True, timeout=5,
                    env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
                         "XDG_RUNTIME_DIR": "/run/user/1000"})
                is_active = r.stdout.strip() == "active"
            except Exception:
                is_active = False
            if is_active and not comfyui_up(inst["url"]):
                print(f"[dead-watcher] Instance {name} active but unresponsive. Restarting...")
                subprocess.run(["systemctl", "--user", "restart", svc],
                    capture_output=True, timeout=30,
                    env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
                         "XDG_RUNTIME_DIR": "/run/user/1000"})
                add_log("warn", "dead", f"Instance {name} restarted")
                for _ in range(90):
                    if comfyui_up(inst["url"]):
                        print(f"[dead-watcher] Instance {name} recovered")
                        break
                    await asyncio.sleep(2)

async def _stuck_job_watcher():
    """Kill jobs stuck >10min without status change. Stop its instance."""
    while True:
        await asyncio.sleep(60)
        now = time.time()
        for jid, j in list(jobs.items()):
            if j.get("status") in ("done", "error"):
                continue
            last_up = j.get("last_update", j.get("generating_at", 0))
            if last_up and now - last_up > 600:  # 10 minutes
                j["status"] = "error"
                j["message"] = "任务超时（10分钟无状态变化）"
                print(f"[stuck-watcher] Killed stuck job {jid[-12:]} (idle {now-last_up:.0f}s)")
                add_log("warn", "stuck", f"Killed job idle {now-last_up:.0f}s", jid)
                add_log("warn", "stuck", f"Killed job idle {now-last_up:.0f}s", jid)
                inst_name = j.get("instance", "")
                if inst_name:
                    svc = f"comfyui-{inst_name.lower()}"
                    try:
                        import subprocess
                        subprocess.run(["systemctl", "--user", "stop", svc],
                            capture_output=True, timeout=10,
                            env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
                                 "XDG_RUNTIME_DIR": "/run/user/1000"})
                    except Exception:
                        pass
                asyncio.ensure_future(broadcast({"type": "job_update", "job": j}))



@asynccontextmanager
async def lifespan(app: FastAPI):
    load_jobs()
    load_history()
    os.makedirs(HISTORY_DIR, exist_ok=True)
    # Start the sequential job queue worker
    _background_tasks.append(asyncio.create_task(_queue_worker()))
    _background_tasks.append(asyncio.create_task(_dead_instance_watcher()))
    _background_tasks.append(asyncio.create_task(_idle_instance_watcher()))
    _background_tasks.append(asyncio.create_task(_stuck_job_watcher()))
    yield

app = FastAPI(title="Ez ComfyUI Showcase", lifespan=lifespan)
@app.get("/api/logs")
def api_logs(limit: int = 200):
    return list(_log_buffer[-limit:])
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
        # GB10 returns [N/A] for memory; still has temp + util
        raw_used, raw_total = parts[0], parts[1]
        temp = int(float(parts[2])) if parts[2] not in ('[N/A]','[N/A ]','N/A') else 0
        util = int(float(parts[3])) if parts[3] not in ('[N/A]','[N/A ]','N/A') else 0
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
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def comfyui_get(path: str, base_url: str = None) -> dict:
    url = (base_url or COMFYUI_URL) + path
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


# ── Multi-instance routing ──────────────────────────────────────────────
def _get_instance_queue_size(base_url: str) -> int:
    """Return number of pending + running jobs on a ComfyUI instance."""
    try:
        q = comfyui_get("/queue", base_url=base_url)
        running = len(q.get("queue_running", []))
        pending = len(q.get("queue_pending", []))
        return running + pending
    except Exception:
        return 999  # unreachable → lowest priority


async def pick_best_instance(workflow_name: str = "") -> dict:
    """Pick the best ComfyUI instance using workflow affinity + queue depth.

    Priority:
    0. T2I → A, I2I → B (hard route, Jeson 2026-05-11)
    1. If no instance is running → auto-start one
    2. Instance with matching workflow (models already in VRAM) → prefer even if busy
    3. Idle instance (queue == 0) → prefer for cold start
    4. Fallback: shortest queue
    """

    # Phase 0: T2I → A, I2I → B (hard route)
    if workflow_name:
        lower = workflow_name.lower()
        inst_a = next(i for i in COMFYUI_INSTANCES if i["name"] == "A")
        inst_b = next(i for i in COMFYUI_INSTANCES if i["name"] == "B")
        if lower.startswith("t2i") or "_t2i" in lower or "-t2i" in lower:
            return inst_a
        if lower.startswith("i2i") or "_i2i" in lower or "-i2i" in lower:
            return inst_b

    # Phase 1: try workflow affinity
    if workflow_name:
        affinity = pick_affinity_instance(workflow_name)
        if affinity:
            return affinity

    # Phase 2: prefer idle instance with same or no model group (avoid conflicting models)
    wf_group = extract_model_group(workflow_name) if workflow_name else ""
    sizes = await asyncio.gather(*[asyncio.to_thread(_get_instance_queue_size, inst["url"]) for inst in COMFYUI_INSTANCES])

    # Best: idle instance with matching group (models already in VRAM)
    for inst, sz in zip(COMFYUI_INSTANCES, sizes):
        if sz == 0 and _instance_group.get(inst["name"]) == wf_group:
            return inst
    # Good: idle instance with no loaded group (fresh start)
    for inst, sz in zip(COMFYUI_INSTANCES, sizes):
        if sz == 0 and not _instance_group.get(inst["name"]):
            return inst

    # Phase 3: shortest queue (prefer same group, then no group, avoid conflicting)
    best, best_load = None, 999
    for inst, load in zip(COMFYUI_INSTANCES, sizes):
        if load >= best_load:
            continue
        ig = _instance_group.get(inst["name"], "")
        # Strongly prefer: same group or no loaded group
        if ig in (wf_group, ""):
            best, best_load = inst, load
    # Fallback: any instance (might evict models)
    if not best:
        for inst, load in zip(COMFYUI_INSTANCES, sizes):
            if load < best_load:
                best, best_load = inst, load
    chosen = best or COMFYUI_INSTANCES[0]

    # Cold-start: ensure ALL instances are running (VRAM warm, no load delay)
    for cold_inst in COMFYUI_INSTANCES:
        if not await asyncio.to_thread(comfyui_up, cold_inst["url"]):
            svc = f"comfyui-{cold_inst['name'].lower()}"
            try:
                await asyncio.to_thread(subprocess.run, ["systemctl", "--user", "start", svc], capture_output=True, timeout=30,
                    env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus", "XDG_RUNTIME_DIR": "/run/user/1000"})
                for _ in range(150):
                    if await asyncio.to_thread(comfyui_up, cold_inst["url"]):
                        break
                    await asyncio.sleep(2)
            except Exception:
                pass
    return chosen


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
        "seed":       {"type": "seed",   "label": "超分种子"},
        "resolution": {"type": "number", "label": "超分分辨率", "min": 512, "max": 8192, "step": 64},
    },
}


def _resolve_link(wf: dict, value, depth: int = 0):
    """Follow ComfyUI link references to get actual value.
    Link format: ["node_id", output_slot] — connected to another node's output.
    Resolves through ComfySwitchNode → PrimitiveInt/PrimitiveFloat chains.
    """
    if depth > 10 or not isinstance(value, list) or len(value) < 2:
        return value
    node_id = str(value[0])
    node = wf.get(node_id, {})
    if not isinstance(node, dict):
        return value
    ct = node.get("class_type", "")
    inputs = node.get("inputs", {})
    # Primitive nodes have the actual value
    if ct in ("PrimitiveInt", "PrimitiveFloat"):
        return inputs.get("value", value)
    # ComfySwitchNode: try on_true first, then on_false
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
            if ct in EDITABLE_FIELDS and fk in EDITABLE_FIELDS[ct]:
                ef = EDITABLE_FIELDS[ct][fk]
                ui_type = ef.get("type", ui_type)
                for k in ("options", "step", "min", "max"):
                    if k in ef:
                        ef_extra[k] = ef[k]
            zone, visible = _auto_classify(ct, fk, fv)
            field_entry = {
                "key": f"{nid}::{fk}",
                "field": fk,
                "type": ui_type,
                "label": fk,
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
    p = os.path.join(WF_CONFIG_DIR, name)
    if os.path.isfile(p):
        with open(p) as f:
            return json.load(f)
    return None


def save_wf_config(name: str, config: dict):
    """Save per-workflow config."""
    os.makedirs(WF_CONFIG_DIR, exist_ok=True)
    p = os.path.join(WF_CONFIG_DIR, name)
    with open(p, "w") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


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
        # Always check EDITABLE_FIELDS for type + extra props (fill gaps)
        if ct in EDITABLE_FIELDS and fname in EDITABLE_FIELDS[ct]:
            ef = EDITABLE_FIELDS[ct][fname]
            if not ftype:
                ftype = ef.get("type", "text")
            for k in ("options", "step", "min", "max"):
                if k in ef:
                    fextra[k] = ef[k]
        if not ftype:
            ftype = "text"
        # Config overrides EDITABLE_FIELDS for extra props
        for k in ("options", "step", "min", "max"):
            if k in field_cfg:
                fextra[k] = field_cfg[k]
        fields.append({
            "node_id": nid, "node_title": title,
            "class_type": ct, "field": fname,
            "value": val,
            "type": ftype,
            "label": field_cfg.get("label", fname),
            "zone": field_cfg.get("zone", "user_input"),
            "visible": field_cfg.get("visible", True),
            "order": field_cfg.get("order", 0),
            **fextra,
        })
    summary = model_name or Path(path).stem.replace("-", " ").replace("_", " ")
    return {"fields": fields, "summary": summary, "model": model_name}


# ══════════════════════════════════════════════════════════════════════════
#  Broadcast
# ══════════════════════════════════════════════════════════════════════════

async def broadcast(data: dict):
    dead = []
    for ws in ws_clients:
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.remove(ws)


# ══════════════════════════════════════════════════════════════════════════
#  Background generation
# ══════════════════════════════════════════════════════════════════════════

# ── ComfyUI node → human-readable status ────────────────────────────────
NODE_STATUS_MAP = {
    # Model loading
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
    # Sampling config
    "ModelSamplingAuraFlow": "配置采样策略...",
    "ModelSamplingFlux": "配置 Flux 采样...",
    # Text encoding
    "CLIPTextEncode": "编码提示词...",
    "TextEncodeQwenImageEditPlus": "编码提示词...",
    "CLIPTextEncodeFlux": "编码 Flux 提示词...",
    "ConditioningZeroOut": "处理条件...",
    "ConditioningSetTimestepRange": "设置时间步范围...",
    # Latent
    "EmptySD3LatentImage": "准备潜空间...",
    "EmptyLatentImage": "准备潜空间...",
    # Sampling
    "KSampler": "采样中...",
    "KSamplerAdvanced": "高级采样中...",
    "SamplerCustom": "自定义采样中...",
    # VAE decode / encode
    "VAEDecode": "解码图像...",
    "VAEEncode": "编码图像...",
    # Upscale
    "ImageUpscaleWithModel": "超分辨率放大...",
    "SeedVR2VideoUpscaler": "超分辨率放大...",
    "ImageScaleBy": "图像缩放...",
    "ImageScale": "图像缩放...",
    # Composite / mask
    "ImageCompositeMasked": "合成图像...",
    # Save
    "SaveImage": "保存图像...",
}


async def comfyui_ws_track(job_id: str, workflow: dict, client_id: str, timeout: int = 600, base_url: str = None):
    """Connect to ComfyUI WS, submit prompt, track execution.

    Returns (True, prompt_id) on success, raises on error/timeout.
    WS connects BEFORE prompt submission to catch all executing events.

    Progress model:
      Prepare + [Encode + Step*N + Decode] * sampler_groups + Save = 100%
    All work units are pre-counted; pct = completed_units / total_units.
    """
    instance_url = base_url or COMFYUI_URL
    ws_url = instance_url.replace("http://", "ws://") + f"/ws?clientId={client_id}"
    start = time.time()
    current_node_cls = ""
    prompt_id = ""

    node_types = {}
    for nid, v in workflow.items():
        if isinstance(v, dict) and "class_type" in v:
            node_types[str(nid)] = v["class_type"]

    # ── Pre-analyze workflow: build work-unit chain ──────────────────────
    SAMPLER_NODES = {"KSampler", "KSamplerAdvanced", "SamplerCustom", "FluxSampler"}
    UPSCALE_ACT_NODES = {"ImageUpscaleWithModel", "SeedVR2VideoUpscaler"}

    # Jeson formula: non-sampler nodes=1, sampler steps=1
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
    print(f"[DEBUG] total_units={total_units} non_sampler={non_sampler_cnt} sampler_steps={sampler_steps_total}")
    completed_units = 0.0
    last_prog = 0
    sampler_cur = 0
    sampler_total = 0

    def _overall_pct():
        return max(0, min(100, round(completed_units / total_units * 100))) if total_units > 0 else 0

    def update_job():
        label = NODE_STATUS_MAP.get(current_node_cls, current_node_cls) if current_node_cls else ""
        pct = _overall_pct()
        print(f"[DEBUG] completed={completed_units}/{total_units} pct={pct}% label={label}")
        msg = "准备中..." if not current_node_cls and completed_units == 0 else (f"{label} {sampler_cur}/{sampler_total}" if label and sampler_total > 0 else ("采样准备中" if label and "采样" in label else ("超分准备中" if label and "超分" in label else (label if label else f"{pct:.0f}%..."))))
        jobs[job_id]["message"] = msg
        jobs[job_id]["progress"] = {"pct": pct}
        jobs[job_id]["last_update"] = time.time()
        save_jobs()

    try:
        async with websockets.connect(ws_url) as ws:
            update_job()
            await broadcast({"type": "job_update", "job": jobs[job_id]})

            # Submit prompt WITH client_id so ComfyUI routes events to us
            resp = comfyui_post("/prompt", {"prompt": workflow, "client_id": client_id}, base_url=instance_url)
            prompt_id = resp.get("prompt_id", "")
            if not prompt_id:
                raise RuntimeError(f"ComfyUI 返回无 prompt_id: {json.dumps(resp)[:200]}")
            jobs[job_id]["prompt_id"] = prompt_id
            save_jobs()

            # Listen for events
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

                # Filter by prompt_id
                msg_pid = data.get("prompt_id", "")
                if msg_pid and prompt_id and msg_pid != prompt_id:
                    continue

                if msg_type == "executing":
                    node_id = data.get("node")
                    if node_id is None:
                        completed_units = total_units
                        update_job()
                        await broadcast({"type": "job_update", "job": jobs[job_id]})
                        return True, prompt_id
                    nid = str(node_id)
                    cls = node_types.get(nid, "")
                    current_node_cls = cls
                    if cls not in SAMPLER_NODES and cls not in UPSCALE_ACT_NODES and cls != "VAEDecode":
                        completed_units += 1.0
                    else:
                        last_prog = 0
                        completed_units += 1.0  # sampler prep step
                        sampler_cur = 0
                        sampler_total = 0
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
                    update_job()
                    await broadcast({"type": "job_update", "job": jobs[job_id]})

                elif msg_type == "execution_error":
                    err = data.get("exception_message", str(data)[:300])
                    raise RuntimeError(f"ComfyUI: {err}")

                elif msg_type == "execution_start":
                    update_job()
                    await broadcast({"type": "job_update", "job": jobs[job_id]})

    except (ConnectionRefusedError, OSError, websockets.exceptions.WebSocketException):
        pass

    # Fallback: HTTP polling
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
    inst = instance or COMFYUI_INSTANCES[0]
    inst_url = inst["url"]
    inst_output = inst["output_dir"]
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

        if vllm_was_running:
            jobs[job_id]["message"] = "停止 vLLM 释放显存..."
            await broadcast({"type": "job_update", "job": jobs[job_id]})
            stop_vllm()
            await asyncio.sleep(2)

        if not comfyui_up(base_url=inst_url):
            jobs[job_id]["status"] = "starting_comfyui"
            jobs[job_id]["message"] = f"启动 ComfyUI #{inst['name']}..."
            await broadcast({"type": "job_update", "job": jobs[job_id]})
            svc = f"comfyui-{inst['name'].lower()}"
            subprocess.run(["systemctl", "--user", "start", svc], capture_output=True, timeout=5, env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus", "XDG_RUNTIME_DIR": "/run/user/1000"})
            for _ in range(90):
                await asyncio.sleep(2)
                if comfyui_up(base_url=inst_url):
                    break
            else:
                raise TimeoutError(f"ComfyUI #{inst['name']} 启动超时 (180s)")

        add_log("info", "generate", "Starting generation", job_id)
        jobs[job_id]["status"] = "generating"
        jobs[job_id]["message"] = "出图中..."
        jobs[job_id]["generating_at"] = time.time()
        save_jobs()
        await broadcast({"type": "job_update", "job": jobs[job_id]})

        # Track progress via ComfyUI WS (connects first, then submits prompt)
        elapsed_start = time.time()
        client_id = uuid.uuid4().hex[:12]
        ws_ok = False
        pid = ""
        try:
            ws_ok, pid = await comfyui_ws_track(job_id, wf, client_id, timeout=900, base_url=inst_url)
        except Exception as _ws_err:
            print(f"[WS_TRACK_ERROR] {job_id}: {_ws_err}")
            add_log("error", "wstrack", f"WS error: {_ws_err}", job_id)
            add_log("error", "wstrack", f"WS error: {_ws_err}", job_id)
            jobs[job_id]["ws_error"] = str(_ws_err)[:300]

        if not ws_ok and pid:
            # WS didn't confirm — check ComfyUI history directly
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
                    # Also check if prompt is still in ComfyUI queue (still running)
                    q = comfyui_get("/queue", base_url=inst_url)
                    running_ids = [item[1] if isinstance(item, list) and len(item) > 1 else None for item in q.get("queue_running", [])]
                    if pid not in running_ids and pid not in check:
                        # Not in queue and not in history — truly lost
                        break
                except RuntimeError:
                    raise
                except Exception:
                    pass

        elapsed = time.time() - elapsed_start

        # If job was cancelled (removed from jobs dict), stop here
        if job_id not in jobs:
            return False, prompt_id or ""

        if not ws_ok:
            _extra = jobs[job_id].get("ws_error", "") if job_id in jobs else ""
            raise TimeoutError(f"出图失败{' ('+_extra[:100]+')' if _extra else ''}")

        # Post-processing: find the output image
        hist = comfyui_get(f"/history/{pid}", base_url=inst_url)
        filename = None
        if pid in hist:
            for node_out in hist[pid].get("outputs", {}).values():
                for img in node_out.get("images", []):
                    filename = img["filename"]
                    break
                if filename:
                    break
        # If job was cancelled during generation, skip output
        if job_id not in jobs or jobs[job_id].get("status") == "error":
            return False, prompt_id or ""
        if not filename:
            raise RuntimeError("未找到输出图片")

        src = os.path.join(inst_output, filename)
        if not os.path.isfile(src):
            # ComfyUI may save into subdirectories (e.g. workflow_name/filename)
            matches = glob.glob(os.path.join(inst_output, "**", filename), recursive=True)
            if matches:
                src = matches[0]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        uid = uuid.uuid4().hex[:6]
        hist_name = f"{ts}_{uid}.png"
        shutil.copy2(src, os.path.join(HISTORY_DIR, hist_name))

        # Read actual image dimensions from output file
        actual_w, actual_h = get_image_size(hist_name)

        prompt_text = ""
        for k, v in field_values.items():
            if "text" in k.split("::")[-1] or "prompt" in k.split("::")[-1]:
                prompt_text = str(v)  # store full prompt, no truncation
                break

        record = {
            "id": job_id, "filename": hist_name,
            "original": filename,
            "workflow": os.path.basename(workflow_path),
            "prompt": prompt_text, "seed": str(seed),
            "width": actual_w or img_width, "height": actual_h or img_height,
            "elapsed": round(elapsed, 1),
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "thumb": make_thumbnail(hist_name) or "",
            "field_values": field_values,  # preserve all fields for full restore
        }
        history.insert(0, record)
        save_history()

        jobs[job_id].update(
            status="done", message=f"完成 ({elapsed:.1f}s)",
            image=hist_name, elapsed=round(elapsed, 1),
        )
        await broadcast({"type": "job_update", "job": jobs[job_id]})

    except Exception as e:
        import traceback
        jobs[job_id]["status"] = "error"
        jobs[job_id]["trace"] = traceback.format_exc()[:500]
        if isinstance(e, TimeoutError):
            jobs[job_id]["message"] = "出图失败"
        else:
            jobs[job_id]["message"] = str(e)
        await broadcast({"type": "job_update", "job": jobs[job_id]})
    finally:
        save_jobs()
        if vllm_was_running:
            start_vllm()


# ══════════════════════════════════════════════════════════════════════════
#  Jobs persistence
# ══════════════════════════════════════════════════════════════════════════

def save_jobs():
    """Persist active (queued/preparing/generating) jobs to disk."""
    active = {k: v for k, v in jobs.items() if v.get("status") not in ("done", "error")}
    try:
        with open(JOBS_FILE, "w") as f:
            json.dump(list(active.values()), f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_jobs():
    """Discard persisted active jobs on startup (service was restarted, they're dead)."""
    if os.path.isfile(JOBS_FILE):
        try:
            os.remove(JOBS_FILE)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════
#  History
# ══════════════════════════════════════════════════════════════════════════

HISTORY_FILE = os.path.join(HISTORY_DIR, "history.json")
THUMB_DIR = os.path.join(HISTORY_DIR, "thumbs")
THUMB_SIZE = 400  # max width for thumbnails


def make_thumbnail(filename: str) -> str | None:
    """Create JPEG thumbnail via ffmpeg. Returns thumb filename or None."""
    src = os.path.join(HISTORY_DIR, filename)
    if not os.path.isfile(src):
        return None
    thumb_name = filename.rsplit(".", 1)[0] + "_thumb.jpg"
    thumb_path = os.path.join(THUMB_DIR, thumb_name)
    if os.path.isfile(thumb_path):
        return thumb_name
    os.makedirs(THUMB_DIR, exist_ok=True)
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", src,
            "-vf", f"scale=w={THUMB_SIZE}:h={THUMB_SIZE}:force_original_aspect_ratio=decrease",
            "-q:v", "3", thumb_path
        ], capture_output=True, timeout=10)
        if os.path.isfile(thumb_path):
            return thumb_name
    except Exception:
        pass
    return None

def get_image_size(filename: str) -> tuple[int, int]:
    """Read image dimensions from file. Returns (width, height) or (0, 0)."""
    path = os.path.join(HISTORY_DIR, filename)
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
    # Backfill: ensure seed is string, and width/height are populated
    changed = False
    for h in history:
        # seed → string
        if "seed" in h and not isinstance(h["seed"], str):
            h["seed"] = str(h["seed"])
            changed = True
        # width/height backfill from image file
        if not h.get("width") or not h.get("height"):
            w, ht = get_image_size(h.get("filename", ""))
            if w > 0:
                h["width"] = w
                h["height"] = ht
                changed = True
        # thumbnail backfill
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


# ══════════════════════════════════════════════════════════════════════════
#  API: Page
# ══════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(html_path.read_text("utf-8")) if html_path.is_file() else HTMLResponse("<h1>index.html missing</h1>", 500)


# ══════════════════════════════════════════════════════════════════════════
#  API: Status & GPU
# ══════════════════════════════════════════════════════════════════════════

@app.get("/api/status")
def api_status():
    instances = []
    for inst in COMFYUI_INSTANCES:
        q_size = _get_instance_queue_size(inst["url"])
        grp = _instance_group.get(inst["name"], "")
        # Count webapp jobs for this instance
        name = inst["name"]
        inst_jobs = [j for j in jobs.values() if j.get("instance") == name and j.get("status") in ("dispatching", "generating", "preparing")]
        q_run = len([j for j in inst_jobs if j["status"] in ("generating", "dispatching")])
        q_pend = len([j for j in inst_jobs if j["status"] == "preparing"])
        instances.append({
            "name": name,
            "url": inst["url"],
            "up": comfyui_up(base_url=inst["url"]),
            "queue": q_size,
            "queue_running": q_run,
            "queue_pending": q_pend,
            "loaded_group": grp,
        })
    return {
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
def api_comfyui(action: str):
    if action == "start":
        results = []
        for inst in COMFYUI_INSTANCES:
            svc = f"comfyui-{inst['name'].lower()}"
            subprocess.run(["systemctl", "--user", "start", svc], capture_output=True, timeout=5, env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus", "XDG_RUNTIME_DIR": "/run/user/1000"})
            results.append(f"{inst['name']} 启动中")
        return {"ok": True, "msg": "; ".join(results)}
    elif action == "stop":
        results = []
        for inst in COMFYUI_INSTANCES:
            svc = f"comfyui-{inst['name'].lower()}"
            subprocess.run(["systemctl", "--user", "stop", svc], capture_output=True, timeout=5)
            _instance_group[inst["name"]] = ""  # models unloaded
            results.append(f"{inst['name']} 已停止")
            # Mark all active jobs on this instance as error
            for jid, jb in list(jobs.items()):
                if jb.get("instance") == inst["name"] and jb.get("status") in ("generating", "dispatching", "preparing"):
                    jb["status"] = "error"
                    jb["message"] = "实例已停止"
        return {"ok": True, "msg": "; ".join(results)}
    raise HTTPException(400)



@app.get("/api/gpu-processes")
def api_gpu_processes():
    """List GPU-consuming processes (excluding ComfyUI/vLLM)."""
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
    for inst in COMFYUI_INSTANCES:
        try:
            svc = "comfyui-" + inst["name"].lower()
            r2 = _sp.run(["systemctl", "--user", "show", svc, "--property=MainPID"],
                         capture_output=True, text=True, timeout=3)
            pid_val = r2.stdout.strip().split("=")[-1]
            if pid_val and pid_val != "0":
                known_pids.add(int(pid_val))
        except Exception:
            pass
    # vLLM included in list (no separate button)
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
def api_gpu_kill(req: dict):
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
def api_comfyui_status():
    """Detailed per-instance status including queue and current job."""
    result = []
    # Count webapp jobs per instance (not ComfyUI internal queue)
    active_statuses = {"dispatching", "generating", "preparing", "queued"}
    for inst in COMFYUI_INSTANCES:
        name = inst["name"]
        svc = f"comfyui-{name.lower()}"
        is_active = comfyui_up(base_url=inst["url"])
        # Count webapp jobs assigned to this instance
        inst_jobs = [j for j in jobs.values() if j.get("instance") == name and j.get("status") in ("dispatching", "generating", "preparing")]
        queue_running = len([j for j in inst_jobs if j["status"] in ("generating", "dispatching")])
        queue_pending = len([j for j in inst_jobs if j["status"] == "preparing"])
        grp = _instance_group.get(name, "")
        current_job = next((j for j in jobs.values() if j.get("instance") == name and j.get("status") in ("generating", "dispatching", "preparing")), None)
        current_label = ""
        current_workflow = ""
        current_progress = 0
        pending_workflows = []
        if current_job:
            workflow_name = (current_job.get("workflow") or "").replace(".json", "")
            current_workflow = workflow_name
            prompt_preview = current_job.get("prompt_preview", "")
            current_label = prompt_preview[:60] if prompt_preview else workflow_name
            prog = current_job.get("progress", {}) or {}
            current_progress = prog.get("pct", 0) if isinstance(prog, dict) else 0
        # Collect queued/pending jobs for this instance
        for j in jobs.values():
            if j.get("instance") == name and j.get("status") in ("queued", "preparing"):
                wf = (j.get("workflow") or "").replace(".json", "")
                if wf:
                    pending_workflows.append(wf)
        result.append({
            "name": name, "up": is_active, "service": svc,
            "queue_running": queue_running, "queue_pending": queue_pending,
            "progress": current_progress,
            "current_workflow": current_workflow,
            "pending_workflows": pending_workflows,
            "current_prompt": current_label, "loaded_group": grp,
            "port": inst["url"].split(":")[-1] if ":" in inst["url"] else "",
        })
    return {"instances": result}

@app.post("/api/comfyui/{instance}/{action}")
def api_comfyui_instance(instance: str, action: str):
    """Start/stop a single ComfyUI instance (A or B)."""
    inst = next((i for i in COMFYUI_INSTANCES if i["name"].upper() == instance.upper()), None)
    if not inst:
        raise HTTPException(404, f"Instance {instance} not found")
    svc = f"comfyui-{inst['name'].lower()}"
    if action == "start":
        subprocess.run(["systemctl", "--user", "start", svc], capture_output=True, timeout=5, env={**os.environ, "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus", "XDG_RUNTIME_DIR": "/run/user/1000"})
        return {"ok": True, "msg": f"{inst['name']} 启动中"}
    elif action == "stop":
        subprocess.run(["systemctl", "--user", "stop", svc], capture_output=True, timeout=5)
        _instance_group[inst["name"]] = ""
        # Mark all active jobs on this instance as error
        for jid, jb in list(jobs.items()):
            if jb.get("instance") == inst["name"] and jb.get("status") in ("generating", "dispatching", "preparing"):
                jb["status"] = "error"
                jb["message"] = "实例已停止"
        return {"ok": True, "msg": f"{inst['name']} 已停止"}
    raise HTTPException(400)


@app.post("/api/vllm/{action}")
def api_vllm(action: str):
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

@app.get("/api/workflows")
def api_workflows():
    seen = {}  # name → first path found (dedup across dirs)
    for d in _load_wf_dirs():
        for f in glob.glob(os.path.join(d, "**", "*.json"), recursive=True):
            name = os.path.basename(f)
            if name not in seen:
                seen[name] = f
    result = []
    for name in sorted(seen):
        info = parse_workflow(seen[name])
        result.append({
            "name": name,
            "summary": info["summary"],
            "model": info["model"],
            "field_count": len(info["fields"]),
            "dir": os.path.dirname(seen[name]),
        })
    return result


@app.get("/api/workflows/{name}/fields")
def api_workflow_fields(name: str):
    path = _resolve_workflow(name)
    if not path:
        raise HTTPException(404)
    return parse_workflow(path, wf_name=name)

@app.get("/api/workflows/{name}/analyze")
def api_workflow_analyze(name: str):
    """Analyze workflow: scan all nodes with auto-classification."""
    path = _resolve_workflow(name)
    if not path:
        raise HTTPException(404)
    return analyze_workflow(path)



@app.get("/api/workflows/{name}/download")
def api_workflow_download(name: str):
    path = _resolve_workflow(name)
    if not path:
        raise HTTPException(404)
    return FileResponse(path, media_type="application/json", filename=name)

@app.get("/api/workflows/{name}/config")
def api_workflow_config_get(name: str):
    """Get saved workflow config. Returns 404 if not configured."""
    config = load_wf_config(name)
    if not config:
        raise HTTPException(404)
    return config


@app.put("/api/workflows/{name}/config")
def api_workflow_config_put(name: str, req: dict):
    """Save workflow config (zone/visible/label/order per field)."""
    save_wf_config(name, req)
    return {"ok": True}


@app.delete("/api/workflows/{name}/config")
def api_workflow_config_delete(name: str):
    """Delete workflow config (revert to auto-classify)."""
    p = os.path.join(WF_CONFIG_DIR, name)
    if os.path.isfile(p):
        os.remove(p)
    return {"ok": True}


@app.post("/api/workflows/upload")
async def api_workflow_upload(file: UploadFile = File(...)):
    name = file.filename
    if not name.endswith(".json"):
        raise HTTPException(400, "需要 .json 文件")
    content = await file.read()
    try:
        json.loads(content)  # validate
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"无效 JSON: {e}")
    upload_dir = _load_wf_dirs()[0]
    dest = os.path.join(upload_dir, name)
    with open(dest, "wb") as f:
        f.write(content)
    # Auto-detect and save metadata
    meta = _load_wf_meta()
    if name not in meta:
        meta[name] = {
            "name": name.replace(".json", ""),
            "tags": _auto_detect_tags(dest),
        }
        _save_wf_meta(meta)
    return {"ok": True, "name": name}


# ── Workflow Directory Management ─────────────────────────────────────

@app.get("/api/workflow-dirs")
def api_workflow_dirs():
    """List configured workflow search directories."""
    dirs = _load_wf_dirs()
    result = []
    for d in dirs:
        count = len(glob.glob(os.path.join(d, "**", "*.json"), recursive=True))
        result.append({"path": d, "exists": os.path.isdir(d), "count": count})
    return result


@app.post("/api/workflow-dirs")
def api_workflow_dir_add(req: dict):
    """Add a workflow search directory."""
    d = req.get("path", "").strip()
    if not d:
        raise HTTPException(400, "path is required")
    d = os.path.expanduser(d)
    d = os.path.abspath(d)
    dirs = _load_wf_dirs()
    if d in dirs:
        raise HTTPException(409, "Directory already added")
    # Auto-create if doesn't exist
    os.makedirs(d, exist_ok=True)
    dirs.append(d)
    _save_wf_dirs(dirs)
    return {"ok": True, "path": d}


@app.delete("/api/workflow-dirs")
def api_workflow_dir_remove(path: str):
    """Remove a workflow search directory. Pass path as query param."""
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

@app.post("/api/upload-image")
async def api_upload_image(file: UploadFile = File(...)):
    """Upload an image to ComfyUI's input directory. Returns the saved filename."""
    content = await file.read()
    if not content:
        raise HTTPException(400, "Empty file")
    # Generate unique filename, keep original extension
    ext = os.path.splitext(file.filename or "")[1].lower() or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        raise HTTPException(400, f"Unsupported image format: {ext}")
    unique_name = f"{int(time.time()*1000)}_{random.randint(1000,9999)}{ext}"
    dest = os.path.join(COMFYUI_INPUT, unique_name)
    os.makedirs(COMFYUI_INPUT, exist_ok=True)
    with open(dest, "wb") as f:
        f.write(content)
    return {"ok": True, "filename": unique_name, "path": dest}


@app.get("/api/input-image/{filename}")
def api_input_image(filename: str):
    """Serve an image from ComfyUI's input directory."""
    # Security: only allow basename, no path traversal
    safe = os.path.basename(filename)
    path = os.path.join(COMFYUI_INPUT, safe)
    if not os.path.isfile(path):
        raise HTTPException(404)
    ext = os.path.splitext(safe)[1].lower()
    media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".bmp": "image/bmp"}.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=media)


# ── Workflow Metadata ─────────────────────────────────────────────────

def _load_wf_meta() -> dict:
    if os.path.isfile(WF_META_FILE):
        with open(WF_META_FILE) as f:
            return json.load(f)
    return {}

def _save_wf_meta(meta: dict):
    with open(WF_META_FILE, "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _load_wf_dirs() -> list[str]:
    """Return list of workflow search directories. Initializes with default if missing."""
    if os.path.isfile(WF_DIRS_FILE):
        with open(WF_DIRS_FILE) as f:
            dirs = json.load(f)
        if isinstance(dirs, list) and dirs:
            return dirs
    # First run: seed with the legacy default
    dirs = [WORKFLOW_DIR]
    os.makedirs(os.path.dirname(WF_DIRS_FILE), exist_ok=True)
    with open(WF_DIRS_FILE, "w") as f:
        json.dump(dirs, f, indent=2)
    return dirs


def _save_wf_dirs(dirs: list[str]):
    os.makedirs(os.path.dirname(WF_DIRS_FILE), exist_ok=True)
    with open(WF_DIRS_FILE, "w") as f:
        json.dump(dirs, f, ensure_ascii=False, indent=2)


def _resolve_workflow(name: str) -> str | None:
    """Find a workflow file across all configured directories (recursive). Returns path or None."""
    for d in _load_wf_dirs():
        # Try direct path first (fast path)
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
        # Search recursively in subdirectories
        matches = glob.glob(os.path.join(d, "**", name), recursive=True)
        if matches:
            return matches[0]
    return None


def _auto_detect_tags(workflow_path: str) -> list[str]:
    """Auto-detect tags from workflow JSON content."""
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
def api_workflows_meta():
    """Return metadata for all workflows, auto-detecting tags if needed."""
    meta = _load_wf_meta()
    seen = {}
    for d in _load_wf_dirs():
        for f in glob.glob(os.path.join(d, "**", "*.json"), recursive=True):
            name = os.path.basename(f)
            if name not in seen:
                seen[name] = f
    result = {}
    for fname in sorted(seen):
        f = seen[fname]
        entry = meta.get(fname, {})
        if "tags" not in entry:
            entry["tags"] = _auto_detect_tags(f)
            meta[fname] = entry
        if "name" not in entry:
            entry["name"] = fname.replace(".json", "")
            meta[fname] = entry
        result[fname] = entry
    _save_wf_meta(meta)
    return result


@app.put("/api/workflows/meta/{filename}")
def api_update_wf_meta(filename: str, body: dict):
    """Update metadata for a single workflow."""
    meta = _load_wf_meta()
    if filename not in meta:
        meta[filename] = {}
    if "name" in body:
        meta[filename]["name"] = body["name"]
    if "tags" in body:
        meta[filename]["tags"] = body["tags"]
    _save_wf_meta(meta)
    return meta[filename]


@app.delete("/api/workflows/meta/{filename}")
def api_delete_wf_meta(filename: str):
    """Remove metadata entry for a workflow."""
    meta = _load_wf_meta()
    if filename in meta:
        del meta[filename]
        _save_wf_meta(meta)
    return {"ok": True}


@app.post("/api/workflows/meta/thumbnail")
async def api_upload_wf_thumbnail(filename: str = Form(...), file: UploadFile = File(...)):
    """Upload a thumbnail for a workflow."""
    os.makedirs(WF_THUMB_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename)[1] or ".jpg"
    thumb_name = f"{os.path.splitext(filename)[0]}{ext}"
    thumb_path = os.path.join(WF_THUMB_DIR, thumb_name)
    content = await file.read()
    with open(thumb_path, "wb") as f:
        f.write(content)
    meta = _load_wf_meta()
    if filename not in meta:
        meta[filename] = {}
    meta[filename]["thumbnail"] = thumb_name
    _save_wf_meta(meta)
    return {"ok": True, "thumbnail": thumb_name}


@app.get("/api/workflows/thumbnail/{name}")
def api_get_wf_thumbnail(name: str):
    """Serve a workflow thumbnail."""
    path = os.path.join(WF_THUMB_DIR, name)
    if not os.path.isfile(path):
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg")


@app.put("/api/workflows/{filename}/rename")
def api_rename_workflow(filename: str, body: dict):
    """Rename the display name of a workflow."""
    meta = _load_wf_meta()
    if filename not in meta:
        meta[filename] = {}
    meta[filename]["name"] = body.get("name", filename.replace(".json", ""))
    _save_wf_meta(meta)
    return meta[filename]


# ── Catch-all workflow delete (MUST be last) ─────────────────────────

@app.delete("/api/workflows/{name}")
def api_workflow_delete(name: str):
    path = _resolve_workflow(name)
    if not path:
        raise HTTPException(404)
    os.remove(path)
    # Also delete metadata
    meta = _load_wf_meta()
    if name in meta:
        del meta[name]
        _save_wf_meta(meta)
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════
#  API: Generation
# ══════════════════════════════════════════════════════════════════════════

@app.post("/api/generate")
def api_generate(req: GenerateRequest, bg: BackgroundTasks):
    path = _resolve_workflow(req.workflow)
    if not path:
        raise HTTPException(404, "Workflow not found")

    job_id = f"job_{int(time.time()*1000)}_{random.randint(1000,9999)}"
    seed = req.seed if req.seed is not None else random.randint(0, 2**63)
    vllm_was = vllm_running()

    prompt_preview = ""
    for k, v in req.fields.items():
        if "text" in k.split("::")[-1] or "prompt" in k.split("::")[-1]:
            prompt_preview = str(v)[:200]
            break

    add_log("info", "queue", f"Job queued: {req.workflow}", job_id)
    jobs[job_id] = {
        "id": job_id, "status": "queued", "message": "排队中...",
        "workflow": req.workflow, "seed": str(seed),
        "prompt_preview": prompt_preview,
        "width": req.width, "height": req.height,
        "fields": req.fields,
        "queued_at": datetime.now().strftime("%H:%M:%S"),
    }

    _job_queue.put_nowait((job_id, path, req.fields, seed, vllm_was, req.width, req.height))
    return {"job_id": job_id, "seed": seed}


@app.get("/api/jobs")
def api_all_jobs():
    return list(jobs.values())


@app.get("/api/jobs/{job_id}")
def api_job_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404)
    return jobs[job_id]


@app.delete("/api/jobs/{job_id}")
async def api_cancel_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404)
    job = jobs[job_id]
    # If generating, try to interrupt ComfyUI
    if job.get("status") == "generating":
        try:
            comfyui_post("/interrupt", {})
        except Exception:
            pass
    # Cancel background task if still running
    task = _job_tasks.get(job_id)
    if task and not task.done():
        task.cancel()
    _job_tasks.pop(job_id, None)
    # Release semaphore if the task was holding it
    inst_name = job.get("instance", "")
    if inst_name and inst_name in _instance_semas:
        sem = _instance_semas[inst_name]
        # Try to release — if semaphore is at max, this is a no-op
        try:
            sem.release()
        except ValueError:
            pass  # already at max value
    try: _global_sem.release()
    except ValueError: pass
    del jobs[job_id]
    save_jobs()
    await broadcast({"type": "job_cancelled", "job_id": job_id})
    return {"ok": True}


@app.post("/api/jobs/{job_id}/retry")
def api_retry_job(job_id: str, bg: BackgroundTasks):
    if job_id not in jobs:
        raise HTTPException(404)
    old = jobs[job_id]
    if old["status"] not in ("error",):
        raise HTTPException(400, "只能重试失败的任务")

    # Reuse original params
    wf = old.get("workflow", "")
    fields = old.get("fields", {})
    seed = random.randint(0, 2**63)
    width = old.get("width", 0)
    height = old.get("height", 0)

    path = _resolve_workflow(wf)
    if not path:
        raise HTTPException(404, "Workflow not found")

    # Remove old job
    del jobs[job_id]

    # Create new job with same params
    new_id = f"job_{int(time.time()*1000)}_{random.randint(1000,9999)}"
    vllm_was = vllm_running()

    prompt_preview = ""
    for k, v in fields.items():
        if "text" in k.split("::")[-1] or "prompt" in k.split("::")[-1]:
            prompt_preview = str(v)[:200]
            break

    jobs[new_id] = {
        "id": new_id, "status": "queued", "message": "排队中...",
        "workflow": wf, "seed": str(seed),
        "prompt_preview": prompt_preview,
        "width": width, "height": height,
        "fields": fields,
        "queued_at": datetime.now().strftime("%H:%M:%S"),
    }

    _job_queue.put_nowait((new_id, path, fields, seed, vllm_was, width, height))
    return {"job_id": new_id, "seed": seed}


# ══════════════════════════════════════════════════════════════════════════
#  API: History
# ══════════════════════════════════════════════════════════════════════════

@app.get("/api/history")
def api_history(limit: int = 0):
    if limit <= 0:
        return history
    return history[:limit]


@app.delete("/api/history/{item_id}")
def api_history_delete(item_id: str):
    global history
    item = next((h for h in history if h["id"] == item_id), None)
    if item:
        img_path = os.path.join(HISTORY_DIR, item["filename"])
        if os.path.isfile(img_path):
            os.remove(img_path)
        history = [h for h in history if h["id"] != item_id]
        save_history()
    return {"ok": True}


@app.get("/api/images/{filename}")
def api_image(filename: str):
    path = os.path.join(HISTORY_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(404)
    return FileResponse(path, media_type="image/png")


@app.get("/api/thumbs/{filename}")
def api_thumb(filename: str):
    """Serve thumbnail. Falls back to original if thumb missing."""
    path = os.path.join(THUMB_DIR, filename)
    if os.path.isfile(path):
        return FileResponse(path, media_type="image/jpeg")
    # fallback: try original
    orig = os.path.join(HISTORY_DIR, filename.replace("_thumb.jpg", ".png"))
    if os.path.isfile(orig):
        return FileResponse(orig, media_type="image/png")
    raise HTTPException(404)


# ══════════════════════════════════════════════════════════════════════════
#  WebSocket
# ══════════════════════════════════════════════════════════════════════════

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.append(ws)
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


# ══════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════



MAX_WORKFLOW_SIZE = 1 * 1024 * 1024   # 1 MB

# ── Workflow Version Management ──────────────────────────────────────

@app.get("/api/workflows/{name}/versions")
def api_workflow_versions(name: str):
    """List all versions of a workflow."""
    meta = _load_wf_meta()
    entry = meta.get(name, {})
    versions = entry.get("versions", {})
    upload_dir = _load_wf_dirs()[0]
    base = name.replace(".json", "")
    vdir = os.path.join(upload_dir, "__versions", base)
    if os.path.isdir(vdir):
        for vf in sorted(os.listdir(vdir)):
            if vf.endswith(".json"):
                vname = vf.replace(".json", "")
                if vname not in versions:
                    versions[vname] = os.path.join(vdir, vf)
        if versions != entry.get("versions", {}):
            entry["versions"] = versions
            meta[name] = entry
            _save_wf_meta(meta)
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
async def api_upload_workflow_version(name: str, file: UploadFile = File(...)):
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
    upload_dir = _load_wf_dirs()[0]
    base = name.replace(".json", "")
    vdir = os.path.join(upload_dir, "__versions", base)
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
    meta[name] = entry
    _save_wf_meta(meta)
    return {"ok": True, "version": vname, "versions": versions}


@app.post("/api/workflows/{name}/activate-version")
def api_activate_workflow_version(name: str, body: dict):
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
    meta[name] = entry
    _save_wf_meta(meta)
    return {"ok": True, "version": version}


@app.delete("/api/workflows/{name}/versions/{version}")
def api_delete_workflow_version(name: str, version: str):
    """Delete a workflow version. v1 cannot be deleted."""
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
    meta[name] = entry
    _save_wf_meta(meta)
    return {"ok": True, "deleted": version}

if __name__ == "__main__":
    load_history()
    os.makedirs(HISTORY_DIR, exist_ok=True)
    print(f"🎨 ComfyUI Web v3: http://0.0.0.0:{PORT}")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
