#!/usr/bin/env zsh
set -euo pipefail

APP_DIR="${0:A:h}"
APP_NAME="EZ ComfyUI Showcase"
LABEL="${EZ_COMFYUI_SERVICE_LABEL:-com.ez-comfyui-showcase}"
PORT="${EZ_COMFYUI_PORT:-18000}"
PYTHON_BIN="${EZ_COMFYUI_PYTHON:-$APP_DIR/.venv/bin/python}"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
LOG_PATH="${EZ_COMFYUI_LOG:-/private/tmp/ez_comfyui_showcase.launchd.log}"
ERR_LOG_PATH="${EZ_COMFYUI_ERR_LOG:-/private/tmp/ez_comfyui_showcase.launchd.err.log}"
DOMAIN="gui/$(id -u)"
ACTION="${1:-start}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [[ -z "${PYTHON_BIN:-}" || ! -x "$PYTHON_BIN" ]]; then
  echo "No Python runtime found. Expected .venv/bin/python or python3 in PATH." >&2
  exit 1
fi

write_plist() {
  mkdir -p "$PLIST_DIR"
  /usr/bin/python3 - "$PLIST_PATH" "$LABEL" "$APP_DIR" "$PYTHON_BIN" "$PORT" "$LOG_PATH" "$ERR_LOG_PATH" <<'PY'
import plistlib
import sys

plist_path, label, app_dir, python_bin, port, log_path, err_log_path = sys.argv[1:]
payload = {
    "Label": label,
    "WorkingDirectory": app_dir,
    "ProgramArguments": [python_bin, f"{app_dir}/app.py"],
    "EnvironmentVariables": {"EZ_COMFYUI_PORT": str(port)},
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
  echo "$APP_NAME is running at http://127.0.0.1:$PORT/"
  echo "Service: $LABEL"
}

stop_service() {
  if is_loaded; then
    launchctl bootout "$DOMAIN/$LABEL"
    echo "$APP_NAME stopped."
  else
    echo "$APP_NAME is not loaded."
  fi
}

status_service() {
  if is_loaded; then
    launchctl print "$DOMAIN/$LABEL" | /usr/bin/awk '
      /state =|pid =|path =|EZ_COMFYUI_PORT/ { print }
    '
    echo "URL: http://127.0.0.1:$PORT/"
  else
    echo "$APP_NAME is not loaded."
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
    stop_service || true
    start_service
    ;;
  status)
    status_service
    ;;
  logs)
    logs_service
    ;;
  *)
    echo "Usage: ./quick-start.sh [start|stop|restart|status|logs]" >&2
    exit 2
    ;;
esac
