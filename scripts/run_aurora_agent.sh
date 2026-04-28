#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Source only the Aurora SDK environment here. Avoid sourcing HumanoidNav if it
# shadows the fourier_msgs package required by Aurora SDK.
if [ -n "${AURORA_SETUP_SCRIPT:-}" ] && [ -f "${AURORA_SETUP_SCRIPT}" ]; then
  source "${AURORA_SETUP_SCRIPT}"
fi

if [ -d ".venv_aurora" ]; then
  source .venv_aurora/bin/activate
elif [ -d ".venv" ]; then
  source .venv/bin/activate
fi

export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"

echo "[aurora-agent] robot=${AURORA_ROBOT_NAME:-gr3v233} domain=${AURORA_DOMAIN_ID:-123}"
echo "[aurora-agent] module=${AURORA_CLIENT_MODULE:-fourier_aurora_client} class=${AURORA_CLIENT_CLASS:-AuroraClient}"
python -c "import importlib, os; getattr(importlib.import_module(os.getenv('AURORA_CLIENT_MODULE', 'fourier_aurora_client')), os.getenv('AURORA_CLIENT_CLASS', 'AuroraClient'))" >/dev/null 2>&1 || echo "[aurora-agent] warning: Aurora SDK is not importable in this environment"
echo "[aurora-agent] starting on ${AURORA_AGENT_HOST:-127.0.0.1}:${AURORA_AGENT_PORT:-18080}"

exec uvicorn app.aurora_agent:app \
  --host "${AURORA_AGENT_HOST:-127.0.0.1}" \
  --port "${AURORA_AGENT_PORT:-18080}"
