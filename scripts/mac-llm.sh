#!/usr/bin/env zsh
set -euo pipefail

APP_DIR="${0:A:h:h}"
LABEL="${EZ_MAC_LLM_SERVICE_LABEL:-com.ez-comfyui-showcase.mac-llm}"
HOST="${EZ_MAC_LLM_HOST:-127.0.0.1}"
PORT="${EZ_MAC_LLM_PORT:-18080}"
MODEL_PATH="${EZ_MAC_LLM_MODEL_PATH:-$APP_DIR/models/llm/qwen3.5-9b-uncensored-hauhaucs-aggressive-q4-vision/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf}"
MMPROJ_PATH="${EZ_MAC_LLM_MMPROJ_PATH:-$APP_DIR/models/llm/qwen3.5-9b-uncensored-hauhaucs-aggressive-q4-vision/mmproj-Qwen3.5-9B-Uncensored-HauhauCS-Aggressive-BF16.gguf}"
MODEL_ALIAS="${EZ_MAC_LLM_MODEL_ALIAS:-mac-qwen3.5-9b-hauhaucs-aggressive-q4-vision}"
DEVICE="${EZ_MAC_LLM_DEVICE:-none}"
GPU_LAYERS="${EZ_MAC_LLM_GPU_LAYERS:-0}"
CTX_SIZE="${EZ_MAC_LLM_CTX_SIZE:-8192}"
BATCH_SIZE="${EZ_MAC_LLM_BATCH_SIZE:-4096}"
UBATCH_SIZE="${EZ_MAC_LLM_UBATCH_SIZE:-4096}"
PARALLEL="${EZ_MAC_LLM_PARALLEL:-1}"
REQUEST_TIMEOUT="${EZ_MAC_LLM_REQUEST_TIMEOUT:-720}"
LLAMA_SERVER="${EZ_LLAMA_SERVER:-$(command -v llama-server || true)}"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
LOG_PATH="${EZ_MAC_LLM_LOG:-/private/tmp/ez_mac_llm.launchd.log}"
ERR_LOG_PATH="${EZ_MAC_LLM_ERR_LOG:-/private/tmp/ez_mac_llm.launchd.err.log}"
DOMAIN="gui/$(id -u)"
ACTION="${1:-start}"

if [[ -z "${LLAMA_SERVER:-}" || ! -x "$LLAMA_SERVER" ]]; then
  echo "llama-server not found. Install llama.cpp first, for example: brew install llama.cpp" >&2
  exit 1
fi

if [[ ! -f "$MODEL_PATH" ]]; then
  echo "Model file not found: $MODEL_PATH" >&2
  exit 1
fi

if [[ -n "${MMPROJ_PATH:-}" && ! -f "$MMPROJ_PATH" ]]; then
  echo "mmproj file not found: $MMPROJ_PATH" >&2
  exit 1
fi

write_plist() {
  mkdir -p "$PLIST_DIR"
  /usr/bin/python3 - "$PLIST_PATH" "$LABEL" "$APP_DIR" "$LLAMA_SERVER" "$MODEL_PATH" "$MMPROJ_PATH" "$MODEL_ALIAS" "$HOST" "$PORT" "$LOG_PATH" "$ERR_LOG_PATH" "$DEVICE" "$GPU_LAYERS" "$CTX_SIZE" "$BATCH_SIZE" "$UBATCH_SIZE" "$PARALLEL" "$REQUEST_TIMEOUT" <<'PY'
import plistlib
import sys

plist_path, label, app_dir, llama_server, model_path, mmproj_path, model_alias, host, port, log_path, err_log_path, device, gpu_layers, ctx_size, batch_size, ubatch_size, parallel, request_timeout = sys.argv[1:]
program_args = [
    llama_server,
    "--model", model_path,
    "--alias", model_alias,
    "--host", host,
    "--port", str(port),
    "--ctx-size", str(ctx_size),
    "--batch-size", str(batch_size),
    "--ubatch-size", str(ubatch_size),
    "--parallel", str(parallel),
    "--timeout", str(request_timeout),
    "--no-cont-batching",
    "--device", device,
    "--gpu-layers", str(gpu_layers),
    "--jinja",
    "--reasoning", "off",
]
if mmproj_path:
    program_args.extend(["--mmproj", mmproj_path, "--no-mmproj-offload"])
payload = {
    "Label": label,
    "WorkingDirectory": app_dir,
    "ProgramArguments": program_args,
    "RunAtLoad": True,
    "KeepAlive": True,
    "StandardOutPath": log_path,
    "StandardErrorPath": err_log_path,
}
with open(plist_path, "wb") as fh:
    plistlib.dump(payload, fh)
PY
}

is_loaded() {
  launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1
}

start_service() {
  write_plist
  if is_loaded; then
    launchctl kickstart -k "$DOMAIN/$LABEL" >/dev/null
  else
    launchctl bootstrap "$DOMAIN" "$PLIST_PATH"
  fi
  echo "Mac LLM is running at http://$HOST:$PORT/"
  echo "Model: $MODEL_ALIAS"
  echo "Service: $LABEL"
}

stop_service() {
  if is_loaded; then
    launchctl bootout "$DOMAIN/$LABEL"
    echo "Mac LLM stopped."
  else
    echo "Mac LLM is not loaded."
  fi
}

restart_service() {
  write_plist
  if is_loaded; then
    launchctl bootout "$DOMAIN/$LABEL"
    sleep 1
    if ! launchctl bootstrap "$DOMAIN" "$PLIST_PATH"; then
      sleep 2
      launchctl bootstrap "$DOMAIN" "$PLIST_PATH"
    fi
    echo "Mac LLM restarted at http://$HOST:$PORT/"
    echo "Model: $MODEL_ALIAS"
    echo "Service: $LABEL"
  else
    start_service
  fi
}

status_service() {
  if is_loaded; then
    launchctl print "$DOMAIN/$LABEL" | /usr/bin/awk '
      /state =|pid =|path =/ { print }
    '
    echo "URL: http://$HOST:$PORT/"
    echo "Model: $MODEL_ALIAS"
  else
    echo "Mac LLM is not loaded."
    exit 1
  fi
}

logs_service() {
  echo "== stdout: $LOG_PATH =="
  [[ -f "$LOG_PATH" ]] && tail -n 80 "$LOG_PATH" || echo "No stdout log yet."
  echo
  echo "== stderr: $ERR_LOG_PATH =="
  [[ -f "$ERR_LOG_PATH" ]] && tail -n 80 "$ERR_LOG_PATH" || echo "No stderr log yet."
}

case "$ACTION" in
  start)
    start_service
    ;;
  stop)
    stop_service
    ;;
  restart)
    restart_service
    ;;
  status)
    status_service
    ;;
  logs)
    logs_service
    ;;
  *)
    echo "Usage: ./scripts/mac-llm.sh [start|stop|restart|status|logs]" >&2
    exit 2
    ;;
esac
