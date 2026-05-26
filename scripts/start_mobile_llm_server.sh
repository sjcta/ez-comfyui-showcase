#!/usr/bin/env zsh
set -euo pipefail

MODEL_PATH="${EZ_MOBILE_AGENT_GGUF_MODEL:-/Users/ai/projects/ez-comfyui-showcase/model/gemma-4-E2B-it-Q4_K_M.gguf}"
HOST="${EZ_MOBILE_AGENT_LLM_HOST:-127.0.0.1}"
PORT="${EZ_MOBILE_AGENT_LLM_PORT:-8080}"
ALIAS="${EZ_MOBILE_AGENT_LLM_MODEL:-gemma-4-e2b}"
CTX_SIZE="${EZ_MOBILE_AGENT_LLM_CTX:-4096}"
THREADS="${EZ_MOBILE_AGENT_LLM_THREADS:-8}"

exec /opt/homebrew/bin/llama-server \
  --host "$HOST" \
  --port "$PORT" \
  --model "$MODEL_PATH" \
  --alias "$ALIAS" \
  --ctx-size "$CTX_SIZE" \
  --threads "$THREADS" \
  --parallel 1 \
  --no-ui \
  --reasoning off
