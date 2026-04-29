#!/usr/bin/env bash
set -eo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

set +u

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
echo "[gr3-adapter] aurora_backend=${AURORA_BACKEND:-agent} agent=${AURORA_AGENT_URL:-http://127.0.0.1:18080}"
python -c "import numpy" >/dev/null 2>&1 || echo "[gr3-adapter] warning: numpy is not importable; ROS2 Python messages may fail. Run: pip install -r requirements.txt"
python -c "import rclpy" >/dev/null 2>&1 || echo "[gr3-adapter] warning: rclpy is not importable; check ROS2/HumanoidNav setup.bash"
echo "[gr3-adapter] starting on ${ADAPTER_HOST:-0.0.0.0}:${ADAPTER_PORT:-8080}"

exec uvicorn app.main:app \
  --host "${ADAPTER_HOST:-0.0.0.0}" \
  --port "${ADAPTER_PORT:-8080}"
