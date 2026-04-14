#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install it first: https://docs.astral.sh/uv/"
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required."
  exit 1
fi

env_file="${DESYSFLOW_ENV_FILE:-.env.example}"
bootstrap_python="${DESYSFLOW_BOOTSTRAP_PYTHON:-3.11}"
non_interactive="${DESYSFLOW_BOOTSTRAP_NON_INTERACTIVE:-0}"
skip_model_check="${DESYSFLOW_SKIP_MODEL_CHECK:-0}"
overwrite_env="${DESYSFLOW_OVERWRITE_ENV:-0}"

echo "Creating local environment..."
uv venv --python "$bootstrap_python"
. .venv/bin/activate
uv pip install -r requirements.txt
uv pip install -e .

echo "Installing UI packages..."
(
  cd ui
  npm install
)

provider_default="${MODEL_PROVIDER:-ollama}"
ollama_model_default="${OLLAMA_MODEL:-gpt-oss:20b-cloud}"
openai_model_default="${OPENAI_MODEL:-gpt-5.4}"
anthropic_model_default="${ANTHROPIC_MODEL:-claude-opus-4-6}"

if is_true "$non_interactive"; then
  provider="$provider_default"
else
  printf "Model provider [ollama/openai/anthropic] (default: %s): " "$provider_default"
  read -r provider
  provider="${provider:-$provider_default}"
fi

llm_model="$ollama_model_default"
ollama_model="$ollama_model_default"
openai_model="$openai_model_default"
anthropic_model="$anthropic_model_default"
api_key=""

case "$provider" in
  ollama)
    if is_true "$non_interactive"; then
      llm_model="$ollama_model_default"
    else
      printf "Ollama model (default: %s): " "$ollama_model_default"
      read -r llm_model
      llm_model="${llm_model:-$ollama_model_default}"
    fi
    ollama_model="$llm_model"
    ;;
  openai)
    if is_true "$non_interactive"; then
      llm_model="$openai_model_default"
      api_key="${OPENAI_API_KEY:-}"
    else
      printf "OpenAI model (default: %s): " "$openai_model_default"
      read -r llm_model
      llm_model="${llm_model:-$openai_model_default}"
      printf "OpenAI API key: "
      read -r api_key
    fi
    openai_model="$llm_model"
    ;;
  anthropic)
    if is_true "$non_interactive"; then
      llm_model="$anthropic_model_default"
      api_key="${ANTHROPIC_API_KEY:-}"
    else
      printf "Anthropic model (default: %s): " "$anthropic_model_default"
      read -r llm_model
      llm_model="${llm_model:-$anthropic_model_default}"
      printf "Anthropic API key: "
      read -r api_key
    fi
    anthropic_model="$llm_model"
    ;;
  *)
    echo "Unsupported provider: $provider"
    exit 1
    ;;
esac

openai_api_key=""
anthropic_api_key=""
if [ "$provider" = "openai" ]; then
  openai_api_key="$api_key"
elif [ "$provider" = "anthropic" ]; then
  anthropic_api_key="$api_key"
fi

if [ -f "$env_file" ] && ! is_true "$overwrite_env"; then
  echo "Keeping existing config at $env_file"
else
  cat > "$env_file" <<EOF
DESYSFLOW_STORAGE_ROOT=./.desflow
CHAT_STORE_BACKEND=sqlite
CHAT_DB_PATH=
SESSION_DB_PATH=
DATABASE_URL=
REDIS_URL=redis://localhost:6379/0
CHAT_CACHE_TTL_SECONDS=60
MODEL_PROVIDER=$provider
OLLAMA_MODEL=$ollama_model
OLLAMA_CRITIC_MODEL=$ollama_model
OLLAMA_BASE_URL=http://localhost:11434
OPENAI_MODEL=$openai_model
OPENAI_CRITIC_MODEL=$openai_model
OPENAI_API_KEY=$openai_api_key
ANTHROPIC_MODEL=$anthropic_model
ANTHROPIC_CRITIC_MODEL=$anthropic_model
ANTHROPIC_API_KEY=$anthropic_api_key
WEB_SEARCH_ENABLED=true
WEB_SEARCH_MAX_RESULTS=5
CRITIC_MAX_RUNS_PER_SESSION=3
CRITIC_ITERATION_LIMIT=3
CRITIC_PASS_MAX_RISK=45
LLM_GUARDRAIL=true
VITE_API_PROXY_TARGET=http://localhost:8000
EOF
  echo "Saved local config to $env_file"
fi
if is_true "$skip_model_check"; then
  echo "Skipping model availability check."
else
  echo "Checking model availability..."
  if ! uv run python scripts/check_model.py; then
    echo "Model check failed. Update $env_file or install the Ollama model before running DesysFlow."
    exit 1
  fi
fi

echo "Cold start complete."
echo "CLI: letsvibedesign cli"
echo "UI + API: letsvibedesign dev"
