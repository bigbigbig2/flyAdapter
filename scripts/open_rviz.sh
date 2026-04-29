#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-mapping}"

case "$MODE" in
  mapping|map)
    CONFIG="$ROOT_DIR/rviz/mapping_GR301AA0025.rviz"
    ;;
  relocation|localization|loc)
    CONFIG="$ROOT_DIR/rviz/relocation_GR301AA0025.rviz"
    ;;
  *)
    echo "Usage: $0 [mapping|relocation]" >&2
    exit 2
    ;;
esac

if [ -f /opt/ros/humble/setup.bash ]; then
  source /opt/ros/humble/setup.bash
fi
if [ -f /opt/fftai/humanoidnav/install/setup.bash ]; then
  source /opt/fftai/humanoidnav/install/setup.bash
fi

echo "[gr3-rviz] mode=${MODE}"
echo "[gr3-rviz] config=${CONFIG}"

exec rviz2 -d "$CONFIG" \
  --ros-args \
  -r tf:=/GR301AA0025/tf \
  -r tf_static:=/GR301AA0025/tf_static
