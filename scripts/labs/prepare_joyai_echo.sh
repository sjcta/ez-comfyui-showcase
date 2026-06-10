#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT="$ROOT/data/labs/projects/JoyAI-Echo"
VENV="$PROJECT/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"

if [ ! -d "$PROJECT" ]; then
  git clone --depth 1 https://github.com/jd-opensource/JoyAI-Echo.git "$PROJECT"
fi

cd "$PROJECT"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Python 3.11 is required by JoyAI-Echo. Set PYTHON_BIN=/path/to/python3.11 and retry." >&2
  exit 2
fi

"$PYTHON_BIN" -m venv "$VENV"
"$VENV/bin/python" -m pip install -U pip
"$VENV/bin/python" -m pip install --extra-index-url https://download.pytorch.org/whl/cu128 -r requirements.txt

cat > "$PROJECT/configs/ez_lab_inference.yaml" <<'EOF'
env:
  venv_path: .venv
paths:
  checkpoint: ../../checkpoints/JoyAI-Echo/JoyAI-Echo-release.safetensors
  gemma_path: ../../checkpoints/JoyAI-Echo/gemma-3-12b
  prompts_dir: prompts
  prompts_glob: "*.json"
  output_root: ../../runs/JoyAI-Echo
video:
  num_frames: 121
  height: 480
  width: 832
  fps: 25
  seed: 42
denoising:
  steps:
    - 1000
    - 994
    - 988
    - 981
    - 975
    - 909
    - 725
    - 422
    - 0
  sigmas:
    - 1.0
    - 0.99375
    - 0.9875
    - 0.98125
    - 0.975
    - 0.909375
    - 0.725
    - 0.421875
    - 0.0
memory:
  max_size: 7
  num_fix_frames: 3
  downscale_factor: 1
  position_mode: reference
  lora_strength: 1.0
  lora_generator: true
  lora_path: ""
  save_mode: random_every_shot_frame
  frame_selection_mode: center
  clip_num_frames: 9
audio_memory:
  enable: true
  window_size: 96
  window_selection_mode: max_response
  sample_rate: 16000
  mel_bins: 128
  mel_hop_length: 160
  n_fft: 1024
  downsample_factor: 4
  is_causal: true
inference:
  device: cuda
  dtype: bfloat16
  v2a_grad_scale: 2.0
EOF

cat <<'EOF'
JoyAI-Echo code environment is prepared.

Expected checkpoints:
  data/labs/checkpoints/JoyAI-Echo/JoyAI-Echo-release.safetensors
  data/labs/checkpoints/JoyAI-Echo/gemma-3-12b/

Downloads:
  hf download jdopensource/JoyAI-Echo --include JoyAI-Echo-release.safetensors --local-dir data/labs/checkpoints/JoyAI-Echo
  hf download google/gemma-3-12b-it --local-dir data/labs/checkpoints/JoyAI-Echo/gemma-3-12b

Before running a case, acquire the Ez ComfyUI resource lock from /labs/joyai.
EOF
