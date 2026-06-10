#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT="$ROOT/data/labs/projects/Bernini"
VENV="$PROJECT/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"

if [ ! -d "$PROJECT" ]; then
  git clone --depth 1 https://github.com/bytedance/Bernini.git "$PROJECT"
fi

cd "$PROJECT"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python 3.11 is required by Bernini. Set PYTHON_BIN=/path/to/python3.11 and retry." >&2
  exit 2
fi

"$PYTHON_BIN" -m venv "$VENV"
"$VENV/bin/python" -m pip install -U pip
"$VENV/bin/python" -m pip install -r requirements.txt

cat <<'EOF'
Bernini code environment is prepared.

Recommended checkpoint:
  hf download ByteDance/Bernini-R-Diffusers --local-dir data/labs/checkpoints/Bernini/Bernini-R-Diffusers

Before running a case, acquire the Ez ComfyUI resource lock from /labs/bernini.
EOF
