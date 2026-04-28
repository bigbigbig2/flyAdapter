#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -f "/opt/ros/humble/setup.bash" ]; then
  source /opt/ros/humble/setup.bash
fi

if [ -f "/opt/fftai/humanoidnav/install/setup.bash" ]; then
  source /opt/fftai/humanoidnav/install/setup.bash
fi

if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

export ROBOT_NAMESPACE="${ROBOT_NAMESPACE:-GR301AA0025}"
export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"

echo "[gr3-adapter] namespace=${ROBOT_NAMESPACE}"
echo "[gr3-adapter] starting on ${ADAPTER_HOST:-0.0.0.0}:${ADAPTER_PORT:-8080}"

exec uvicorn app.main:app \
  --host "${ADAPTER_HOST:-0.0.0.0}" \
  --port "${ADAPTER_PORT:-8080}"
