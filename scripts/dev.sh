#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [ -f ".env.example" ]; then
  set -a
  . ./.env.example
  set +a
fi

cleanup() {
  echo "Stopping DesysFlow dev services..."
  kill "${API_PID:-}" "${UI_PID:-}" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

./scripts/api.sh &
API_PID=$!

./scripts/ui.sh &
UI_PID=$!

echo "DesysFlow local dev started."
echo "API: http://localhost:8000/docs"
echo "UI:  http://localhost:5173"

wait
