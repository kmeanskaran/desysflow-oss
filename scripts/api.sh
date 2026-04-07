#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ -f ".env" ]; then
  set -a
  . ./.env
  set +a
fi

export DESYSFLOW_STORAGE_ROOT="${DESYSFLOW_STORAGE_ROOT:-./desysflow}"
export CHAT_STORE_BACKEND="${CHAT_STORE_BACKEND:-sqlite}"
export MODEL_PROVIDER="${MODEL_PROVIDER:-ollama}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-gpt-oss:20b-cloud}"
export OLLAMA_CRITIC_MODEL="${OLLAMA_CRITIC_MODEL:-$OLLAMA_MODEL}"

mkdir -p "$DESYSFLOW_STORAGE_ROOT"

uv run python scripts/check_model.py
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 600
