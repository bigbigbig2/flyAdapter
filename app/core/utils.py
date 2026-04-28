from __future__ import annotations

import math
import time
from typing import Any


def now_ms() -> int:
    return int(time.time() * 1000)


def monotonic_s() -> float:
    return time.monotonic()


def quaternion_from_yaw(yaw: float) -> dict[str, float]:
    half = yaw * 0.5
    return {
        "q_x": 0.0,
        "q_y": 0.0,
        "q_z": math.sin(half),
        "q_w": math.cos(half),
    }


def yaw_from_quaternion(q_x: float, q_y: float, q_z: float, q_w: float) -> float:
    siny_cosp = 2.0 * (q_w * q_z + q_x * q_y)
    cosy_cosp = 1.0 - 2.0 * (q_y * q_y + q_z * q_z)
    return math.atan2(siny_cosp, cosy_cosp)


def pose_dict(
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
    q_x: float = 0.0,
    q_y: float = 0.0,
    q_z: float = 0.0,
    q_w: float = 1.0,
    mode: int = 1,
    frame_id: str = "map",
) -> dict[str, Any]:
    return {
        "x": float(x),
        "y": float(y),
        "z": float(z),
        "q_x": float(q_x),
        "q_y": float(q_y),
        "q_z": float(q_z),
        "q_w": float(q_w),
        "mode": int(mode),
        "frame_id": frame_id,
    }


def legacy_point_from_pose(name: str, pose: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": name,
        "x": float(pose.get("x", 0.0)),
        "y": float(pose.get("y", 0.0)),
        "z": float(pose.get("z", 0.0)),
        "q_x": float(pose.get("q_x", 0.0)),
        "q_y": float(pose.get("q_y", 0.0)),
        "q_z": float(pose.get("q_z", 0.0)),
        "q_w": float(pose.get("q_w", 1.0)),
    }
