#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT="$ROOT/data/labs/projects/HY-World-2.0"
CHECKPOINT_ROOT="$ROOT/data/labs/checkpoints/HY-World-2.0"
VENV="$PROJECT/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ ! -d "$PROJECT" ]; then
  git clone --depth 1 https://github.com/Tencent-Hunyuan/HY-World-2.0.git "$PROJECT"
fi

cd "$PROJECT"
"$PYTHON_BIN" - <<'PY'
from pathlib import Path

path = Path("hyworld2/worldrecon/hyworldmirror/models/layers/attention.py")
text = path.read_text()
old_import = """try:
    from flash_attn_interface import flash_attn_func as flash_attn_func_v3
    _USE_FLASH_ATTN_V3 = True
except ImportError:
    from flash_attn.flash_attn_interface import flash_attn_func as flash_attn_func_v2
    _USE_FLASH_ATTN_V3 = False
"""
new_import = """try:
    from flash_attn_interface import flash_attn_func as flash_attn_func_v3
    flash_attn_func_v2 = None
    _USE_FLASH_ATTN_V3 = True
    _FLASH_ATTN_AVAILABLE = True
except ImportError:
    try:
        from flash_attn.flash_attn_interface import flash_attn_func as flash_attn_func_v2
        flash_attn_func_v3 = None
        _USE_FLASH_ATTN_V3 = False
        _FLASH_ATTN_AVAILABLE = True
    except ImportError:
        flash_attn_func_v2 = None
        flash_attn_func_v3 = None
        _USE_FLASH_ATTN_V3 = False
        _FLASH_ATTN_AVAILABLE = False
"""
old_condition = "        if q.dtype==torch.bfloat16 or q.dtype==torch.float16:\n"
new_condition = "        if _FLASH_ATTN_AVAILABLE and (q.dtype==torch.bfloat16 or q.dtype==torch.float16):\n"
if old_import in text:
    text = text.replace(old_import, new_import)
if old_condition in text:
    text = text.replace(old_condition, new_condition)
path.write_text(text)
PY
"$PYTHON_BIN" -m venv "$VENV"
"$VENV/bin/python" -m pip install -U pip setuptools wheel
cat > "$PROJECT/.ez_worldmirror_requirements.txt" <<'EOF'
torch==2.7.1
torchvision==0.22.1
safetensors
omegaconf
einops
scipy==1.14.1
numpy==1.26.4
Pillow
imageio[ffmpeg]
opencv-python==4.10.0.84
matplotlib==3.10.3
scikit-image==0.25.2
trimesh
plyfile
tqdm
requests
huggingface_hub
gradio
EOF
"$VENV/bin/python" -m pip install --extra-index-url https://download.pytorch.org/whl/cu128 -r "$PROJECT/.ez_worldmirror_requirements.txt"
"$VENV/bin/python" -m pip install git+https://github.com/nerfstudio-project/gsplat.git

mkdir -p "$CHECKPOINT_ROOT"
export CHECKPOINT_ROOT
"$VENV/bin/python" - <<'PY'
from huggingface_hub import snapshot_download
from pathlib import Path
import os
import shutil

root = Path(os.environ["CHECKPOINT_ROOT"])
cache = snapshot_download(
    repo_id="tencent/HY-World-2.0",
    allow_patterns=["HY-WorldMirror-2.0/*"],
)
src = Path(cache) / "HY-WorldMirror-2.0"
dst = root / "HY-WorldMirror-2.0"
dst.mkdir(parents=True, exist_ok=True)
for item in src.iterdir():
    target = dst / item.name
    if target.exists():
        continue
    if item.is_dir():
        shutil.copytree(item, target)
    else:
        shutil.copy2(item, target)
PY

cat <<'EOF'
HY-World 2.0 WorldMirror first-stage lab is prepared.

Prepared source:
  data/labs/projects/HY-World-2.0

Expected checkpoint files:
  data/labs/checkpoints/HY-World-2.0/HY-WorldMirror-2.0/model.safetensors
  data/labs/checkpoints/HY-World-2.0/HY-WorldMirror-2.0/config.json

Before running a case, acquire the Ez ComfyUI resource lock from /labs/hyworld2.
EOF
