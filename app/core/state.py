from __future__ import annotations

import threading
from typing import Any

from app.config import AppConfig
from app.core.utils import monotonic_s, now_ms, pose_dict


class RuntimeState:
    def __init__(self, config: AppConfig) -> None:
        self._lock = threading.RLock()
        self.pose: dict[str, Any] = pose_dict()
        self.pose_stamp_s: float | None = None
        self.slam_mode: str = "unknown"
        self.slam_mode_stamp_s: float | None = None
        self.odom_status_code: int | None = None
        self.odom_status_stamp_s: float | None = None
        self.odom_status_score: float | None = None
        self.health: dict[str, Any] = {"has_warning": False, "has_error": False, "has_fatal": False, "errors": []}
        self.health_stamp_s: float | None = None
        self.events: list[dict[str, Any]] = []
        self.action_status: dict[str, Any] = {}
        self.action_status_stamp_s: float | None = None
        self.current_action: dict[str, Any] = {}

        self.current_map: str = config.default_map_path
        self.status_code: int = 0
        self.is_cruising: bool = False
        self.is_paused: bool = False
        self.is_arrived: bool = False
        self.current_nav_index: int = 0
        self.total_nav_points: int = 0
        self.current_nav_name: str = ""
        self.current_target: dict[str, Any] | None = None
        self.last_error: str | None = None
        self.navigation_task: dict[str, Any] = {"status": "idle"}

    def update_pose(self, pose: dict[str, Any]) -> None:
        with self._lock:
            self.pose = dict(pose)
            self.pose_stamp_s = monotonic_s()

    def update_slam_mode(self, mode: str) -> None:
        with self._lock:
            self.slam_mode = mode
            self.slam_mode_stamp_s = monotonic_s()

    def update_odom_status_code(self, code: int) -> None:
        with self._lock:
            self.odom_status_code = int(code)
            self.odom_status_stamp_s = monotonic_s()

    def update_odom_status_score(self, score: float) -> None:
        with self._lock:
            self.odom_status_score = float(score)

    def update_health(self, health: dict[str, Any]) -> None:
        with self._lock:
            self.health = dict(health)
            self.health_stamp_s = monotonic_s()

    def update_events(self, events: list[dict[str, Any]]) -> None:
        with self._lock:
            self.events = list(events)[-20:]

    def update_action_status(self, action_status: dict[str, Any]) -> None:
        with self._lock:
            self.action_status = dict(action_status)
            self.action_status_stamp_s = monotonic_s()

    def set_current_action(self, action: dict[str, Any]) -> None:
        with self._lock:
            self.current_action = dict(action)

    def set_navigation_task(self, task: dict[str, Any]) -> None:
        with self._lock:
            self.navigation_task = dict(task)

    def mark_error(self, message: str, status_code: int = -1) -> None:
        with self._lock:
            self.last_error = message
            self.status_code = status_code

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "pose": dict(self.pose),
                "pose_age_sec": self._age(self.pose_stamp_s),
                "slam_mode": self.slam_mode,
                "slam_mode_age_sec": self._age(self.slam_mode_stamp_s),
                "odom_status_code": self.odom_status_code,
                "odom_status_age_sec": self._age(self.odom_status_stamp_s),
                "odom_status_score": self.odom_status_score,
                "health": dict(self.health),
                "events": list(self.events),
                "action_status": dict(self.action_status),
                "current_action": dict(self.current_action),
                "current_map": self.current_map,
                "status_code": self.status_code,
                "is_cruising": self.is_cruising,
                "is_paused": self.is_paused,
                "is_arrived": self.is_arrived,
                "current_nav_index": self.current_nav_index,
                "total_nav_points": self.total_nav_points,
                "current_nav_name": self.current_nav_name,
                "current_target": dict(self.current_target) if self.current_target else None,
                "last_error": self.last_error,
                "navigation_task": dict(self.navigation_task),
                "timestamp": now_ms(),
            }

    def legacy_status(self) -> dict[str, Any]:
        snap = self.snapshot()
        return {
            "status": "running",
            "is_cruising": snap["is_cruising"],
            "is_paused": snap["is_paused"],
            "current_nav_index": snap["current_nav_index"] + 1,
            "total_nav_points": snap["total_nav_points"],
            "is_arrived": snap["is_arrived"],
            "map_file": snap["current_map"],
            "status_code": snap["status_code"],
            "slam_mode": snap["slam_mode"],
            "odom_status_code": snap["odom_status_code"],
            "odom_status_score": snap["odom_status_score"],
            "localization_status": self.localization_status_from_code(snap["odom_status_code"]),
            "last_error": snap["last_error"],
        }

    @staticmethod
    def localization_status_from_code(code: int | None) -> str:
        mapping = {
            0: "IDLE",
            1: "INITIALIZING",
            2: "GOOD",
            3: "FOLLOWING_DR",
            4: "FAIL",
        }
        return mapping.get(code, "UNKNOWN")

    @staticmethod
    def _age(stamp_s: float | None) -> float | None:
        if stamp_s is None:
            return None
        return round(monotonic_s() - stamp_s, 3)
