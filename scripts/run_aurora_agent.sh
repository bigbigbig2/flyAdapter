#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

clean_colon_var() {
  local name="$1"
  local value="${!name:-}"
  local cleaned=""
  local item
  local -a parts=()
  if [ -z "$value" ]; then
    return
  fi
  IFS=':' read -r -a parts <<< "$value"
  for item in "${parts[@]}"; do
    if [ -z "$item" ]; then
      continue
    fi
    case "$item" in
      *humanoidnav*|*/opt/fftai/humanoidnav*)
        ;;
      *)
        if [ -z "$cleaned" ]; then
          cleaned="$item"
        else
          cleaned="${cleaned}:$item"
        fi
        ;;
    esac
  done
  export "$name=$cleaned"
}

if [ "${AURORA_ENV_CLEAN:-1}" = "1" ]; then
  # Agent must not inherit HumanoidNav overlays. HumanoidNav ships a
  # fourier_msgs package without AuroraCmd, which shadows Aurora SDK messages.
  clean_colon_var PYTHONPATH
  clean_colon_var AMENT_PREFIX_PATH
  clean_colon_var CMAKE_PREFIX_PATH
  clean_colon_var COLCON_PREFIX_PATH
  clean_colon_var ROS_PACKAGE_PATH
  clean_colon_var LD_LIBRARY_PATH
  clean_colon_var PKG_CONFIG_PATH
fi

# Source only the Aurora SDK environment here. Do not source HumanoidNav here.
if [ -n "${AURORA_SETUP_SCRIPT:-}" ] && [ -f "${AURORA_SETUP_SCRIPT}" ]; then
  source "${AURORA_SETUP_SCRIPT}"
fi

if [ "${AURORA_ENV_CLEAN:-1}" = "1" ]; then
  clean_colon_var PYTHONPATH
  clean_colon_var AMENT_PREFIX_PATH
  clean_colon_var CMAKE_PREFIX_PATH
  clean_colon_var COLCON_PREFIX_PATH
  clean_colon_var ROS_PACKAGE_PATH
  clean_colon_var LD_LIBRARY_PATH
  clean_colon_var PKG_CONFIG_PATH
fi

if [ -d ".venv_aurora" ]; then
  source .venv_aurora/bin/activate
elif [ -d ".venv" ]; then
  source .venv/bin/activate
fi

export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"

echo "[aurora-agent] robot=${AURORA_ROBOT_NAME:-gr3v233} domain=${AURORA_DOMAIN_ID:-123}"
echo "[aurora-agent] module=${AURORA_CLIENT_MODULE:-fourier_aurora_client} class=${AURORA_CLIENT_CLASS:-AuroraClient}"
python - <<'PY' || true
import importlib.util
import sys

for name in ("fourier_msgs", "fourier_msgs.msg", "fourier_msgs.msg.AuroraCmd"):
    try:
        spec = importlib.util.find_spec(name)
        origin = None if spec is None else (spec.origin or spec.submodule_search_locations)
        print(f"[aurora-agent] {name}: {origin}")
    except Exception as exc:
        print(f"[aurora-agent] {name}: ERROR {exc}")
print("[aurora-agent] sys.path:")
for item in sys.path[:12]:
    print(f"  {item}")
PY
python -c "import importlib, os; getattr(importlib.import_module(os.getenv('AURORA_CLIENT_MODULE', 'fourier_aurora_client')), os.getenv('AURORA_CLIENT_CLASS', 'AuroraClient'))" >/dev/null 2>&1 || echo "[aurora-agent] warning: Aurora SDK is not importable in this environment"
echo "[aurora-agent] starting on ${AURORA_AGENT_HOST:-127.0.0.1}:${AURORA_AGENT_PORT:-18080}"

exec uvicorn app.aurora_agent:app \
  --host "${AURORA_AGENT_HOST:-127.0.0.1}" \
  --port "${AURORA_AGENT_PORT:-18080}"
