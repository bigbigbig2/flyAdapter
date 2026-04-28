from __future__ import annotations

import threading
import time
from typing import Any

from app.bridges.aurora_bridge import AuroraBridge
from app.bridges.ros_bridge import BridgeUnavailable, RosBridge
from app.config import AppConfig
from app.core.events import EventHub
from app.core.state import RuntimeState
from app.core.store import JsonStore
from app.core.utils import legacy_point_from_pose, now_ms, pose_dict, yaw_from_quaternion


class RobotService:
    def __init__(
        self,
        config: AppConfig,
        state: RuntimeState,
        store: JsonStore,
        ros: RosBridge,
        aurora: AuroraBridge,
        events: EventHub,
    ) -> None:
        self.config = config
        self.state = state
        self.store = store
        self.ros = ros
        self.aurora = aurora
        self.events = events
        self._cruise_stop = threading.Event()
        self._cruise_pause = threading.Event()
        self._cruise_thread: threading.Thread | None = None
        self._nav_lock = threading.RLock()

        runtime = self.store.load_runtime()
        if runtime.get("current_map"):
            self.state.current_map = str(runtime["current_map"])

    def start(self) -> None:
        self.aurora.start()
        self.ros.start()

    def stop(self) -> None:
        self.stop_cruise()
        self.ros.stop()

    def legacy_status(self) -> dict[str, Any]:
        snap = self.state.snapshot()
        aurora = self.aurora.state()
        status = {
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
            "localization_status": RuntimeState.localization_status_from_code(snap["odom_status_code"]),
            "last_error": snap["last_error"],
        }
        status["ready_for_navigation"] = self.readiness(snap=snap, aurora=aurora)["ready"]
        status["aurora"] = aurora
        status["ros"] = self.ros.diagnostics()
        return status

    def status(self) -> dict[str, Any]:
        snap = self.state.snapshot()
        aurora = self.aurora.state()
        return {
            "adapter": {"status": "running", "namespace": self.config.ns},
            "ros": self.ros.diagnostics(),
            "aurora": aurora,
            "runtime": snap,
            "readiness": self.readiness(snap=snap, aurora=aurora),
        }

    def get_pose(self) -> dict[str, Any]:
        return self.state.snapshot()["pose"]

    def localization_status(self) -> dict[str, Any]:
        snap = self.state.snapshot()
        return {
            "current_map": snap["current_map"],
            "slam_mode": snap["slam_mode"],
            "pose": snap["pose"],
            "pose_age_sec": snap["pose_age_sec"],
            "odom_status_code": snap["odom_status_code"],
            "odom_status": RuntimeState.localization_status_from_code(snap["odom_status_code"]),
            "odom_status_score": snap["odom_status_score"],
            "odom_status_age_sec": snap["odom_status_age_sec"],
            "health": snap["health"],
            "ready": self.readiness(snap=snap)["ready"],
        }

    def readiness(self, snap: dict[str, Any] | None = None, aurora: dict[str, Any] | None = None) -> dict[str, Any]:
        snap = snap or self.state.snapshot()
        aurora = aurora or self.aurora.state()
        blockers: list[str] = []
        warnings: list[str] = []

        if not self.ros.available:
            blockers.append("ros_python_unavailable")
        elif not self.ros.ready:
            blockers.append("ros_bridge_not_ready")

        if not snap["current_map"]:
            blockers.append("map_not_loaded")
        if snap["slam_mode"] not in {"localization", "loc", "1"}:
            warnings.append("not_in_localization_mode")
        if snap["pose_age_sec"] is None or snap["pose_age_sec"] > 3.0:
            blockers.append("robot_pose_not_fresh")
        if snap["odom_status_code"] != 2:
            blockers.append("localization_not_good")
        if snap["health"].get("has_error") or snap["health"].get("has_fatal"):
            blockers.append("health_error")
        if snap["is_cruising"] or snap["navigation_task"].get("status") in {"running", "executing"}:
            warnings.append("navigation_task_active")

        if self.config.require_aurora:
            if not aurora.get("connected"):
                blockers.append("aurora_unavailable")
            elif not aurora.get("standing"):
                blockers.append("robot_not_standing")
        elif not aurora.get("connected"):
            warnings.append("aurora_unavailable")
        elif not aurora.get("standing"):
            warnings.append("robot_not_standing")
        if aurora.get("stale"):
            warnings.append("aurora_state_stale")

        return {
            "ready": not blockers,
            "blockers": blockers,
            "warnings": warnings,
            "checks": {
                "ros_available": self.ros.available,
                "ros_ready": self.ros.ready,
                "map_loaded": bool(snap["current_map"]),
                "localization_good": snap["odom_status_code"] == 2,
                "pose_fresh": snap["pose_age_sec"] is not None and snap["pose_age_sec"] <= 3.0,
                "health_ok": not snap["health"].get("has_error") and not snap["health"].get("has_fatal"),
                "aurora_connected": bool(aurora.get("connected")),
                "robot_standing": bool(aurora.get("standing")),
                "aurora_cached": bool(aurora.get("cached")),
                "aurora_stale": bool(aurora.get("stale")),
            },
        }

    def precheck_navigation(self, force: bool = False) -> dict[str, Any]:
        readiness = self.readiness()
        if force or readiness["ready"]:
            return {"ok": True, "readiness": readiness}
        return {"ok": False, "readiness": readiness}

    def start_mapping(self) -> dict[str, Any]:
        return self._safe_ros_call(lambda: self.ros.switch_mode("mapping"), "start_mapping")

    def stop_mapping(self, map_path: str | None = None) -> dict[str, Any]:
        target = map_path or self.state.snapshot()["current_map"] or self.config.default_map_path
        result = self._safe_ros_call(lambda: self.ros.save_map(target), "stop_mapping")
        result["map_file"] = target
        return result

    def set_map_path(self, path: str) -> dict[str, Any]:
        self.state.current_map = path
        runtime = self.store.load_runtime()
        runtime["current_map"] = path
        self.store.save_runtime(runtime)
        return self.legacy_status()

    def relocation(
        self,
        map_path: str | None = None,
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
        yaw: float = 0.0,
        wait_for_localization: bool = False,
    ) -> dict[str, Any]:
        path = map_path or self.state.snapshot()["current_map"] or self.config.default_map_path
        result = self._safe_ros_call(lambda: self.ros.load_map(path, x=x, y=y, z=z, yaw=yaw), "relocation")
        if result.get("success", True):
            self.state.current_map = path
            runtime = self.store.load_runtime()
            runtime["current_map"] = path
            self.store.save_runtime(runtime)
        if wait_for_localization:
            result["wait"] = self.wait_for_localization()
        return {**self.legacy_status(), "result": result}

    def wait_for_localization(self, timeout_sec: float = 30.0) -> dict[str, Any]:
        start = time.monotonic()
        while time.monotonic() - start < timeout_sec:
            readiness = self.readiness()
            if readiness["checks"]["localization_good"] and readiness["checks"]["pose_fresh"]:
                return {"ready": True, "elapsed_sec": round(time.monotonic() - start, 2)}
            time.sleep(0.2)
        return {"ready": False, "elapsed_sec": round(time.monotonic() - start, 2), "readiness": self.readiness()}

    def add_current_pose_to_nav_points(self, name: str = "") -> dict[str, Any]:
        points, map_file, initial_pose = self.store.load_nav_points()
        point_name = name or f"point_{len(points) + 1}"
        point = legacy_point_from_pose(point_name, self.get_pose())
        points.append(point)
        self.store.save_nav_points(points, map_file or self.state.snapshot()["current_map"], initial_pose)
        self.state.total_nav_points = len(points)
        return self.legacy_status()

    def nav_points_response(self) -> dict[str, Any]:
        points, _, _ = self.store.load_nav_points()
        self.state.total_nav_points = len(points)
        return {"nav_points": points, "count": len(points)}

    def save_nav_points(self) -> dict[str, Any]:
        points, _, initial_pose = self.store.load_nav_points()
        self.store.save_nav_points(points, self.state.snapshot()["current_map"], initial_pose)
        return self.legacy_status()

    def load_nav_points(self) -> dict[str, Any]:
        points, map_file, _ = self.store.load_nav_points()
        if map_file:
            self.state.current_map = map_file
        self.state.total_nav_points = len(points)
        return self.legacy_status()

    def clear_nav_points(self) -> dict[str, Any]:
        self.store.save_nav_points([], self.state.snapshot()["current_map"])
        self.state.current_nav_index = 0
        self.state.total_nav_points = 0
        return self.legacy_status()

    def load_nav_points_by_name(self, name: str) -> dict[str, Any]:
        try:
            points, map_file, initial_pose = self.store.load_show_cruise(name)
        except (FileNotFoundError, ValueError) as exc:
            self.state.mark_error(str(exc), status_code=404)
            return {"success": False, "message": str(exc), "status_code": 404}
        self.store.save_nav_points(points, map_file or self.state.snapshot()["current_map"], initial_pose)
        if map_file:
            self.state.current_map = map_file
        self.state.current_nav_name = name
        self.state.total_nav_points = len(points)
        return self.legacy_status()

    def navigate_to(self, target: dict[str, Any], label: str = "API Target", force: bool = False) -> dict[str, Any]:
        with self._nav_lock:
            check = self.precheck_navigation(force=force)
            if not check["ok"]:
                self.state.mark_error("navigation precheck failed", status_code=409)
                return {"status": "blocked", "message": "navigation precheck failed", "precheck": check, "status_code": 409}

            stand = self.aurora.ensure_stand()
            if self.config.require_aurora and not stand.get("success"):
                self.state.mark_error("ensure_stand failed", status_code=409)
                return {"status": "blocked", "message": "ensure_stand failed", "aurora": stand, "status_code": 409}

            self.state.set_navigation_task({"status": "running", "label": label, "target": target, "started_at": now_ms()})
            result = self._safe_ros_call(lambda: self.ros.navigate_to_pose(target, wait=False), "navigate_to")
            self.state.set_current_action({"action_name": "navigate_to_pose", "target": target, "result": result})
            return {"status": "success" if result.get("accepted", result.get("success", False)) else "failed", "message": "Navigation command sent", "target": target, "status_code": self.state.status_code, "result": result}

    def start_cruise(self, force: bool = False) -> dict[str, Any]:
        points, _, _ = self.store.load_nav_points()
        if not points:
            self.state.mark_error("no navigation points", status_code=400)
            return {"status": "failed", "message": "no navigation points", **self.legacy_status()}
        check = self.precheck_navigation(force=force)
        if not check["ok"]:
            self.state.mark_error("cruise precheck failed", status_code=409)
            return {"status": "blocked", "message": "cruise precheck failed", "precheck": check, **self.legacy_status()}

        self.stop_cruise(cancel_robot=False)
        self._cruise_stop.clear()
        self._cruise_pause.clear()
        self.state.is_cruising = True
        self.state.is_paused = False
        self.state.is_arrived = False
        self.state.current_nav_index = 0
        self.state.total_nav_points = len(points)
        self.events.publish({"event_type": "cruise_start", "timestamp": now_ms(), "total_points": len(points), "first_target": points[0]})
        self._cruise_thread = threading.Thread(target=self._cruise_loop, args=(points,), name="cruise-runner", daemon=True)
        self._cruise_thread.start()
        return self.legacy_status()

    def stop_cruise(self, cancel_robot: bool = True) -> dict[str, Any]:
        was_cruising = self.state.snapshot()["is_cruising"]
        self._cruise_stop.set()
        self._cruise_pause.clear()
        if cancel_robot:
            try:
                self.ros.cancel_current_action()
            except Exception:
                pass
            self.aurora.stop_motion()
        self.state.is_cruising = False
        self.state.is_paused = False
        self.state.set_navigation_task({"status": "idle"})
        if was_cruising:
            self.events.publish({"event_type": "cruise_stop", "timestamp": now_ms(), "completed_points": self.state.current_nav_index, "total_points": self.state.total_nav_points})
        return self.legacy_status()

    def pause_nav(self) -> dict[str, Any]:
        self._cruise_pause.set()
        self.state.is_paused = True
        self._safe_ros_call(lambda: self.ros.cancel_current_action(), "pause_nav")
        return self.legacy_status()

    def resume_nav(self) -> dict[str, Any]:
        self._cruise_pause.clear()
        self.state.is_paused = False
        return self.legacy_status()

    def nav_status(self) -> dict[str, Any]:
        snap = self.state.snapshot()
        response = {
            "is_cruising": snap["is_cruising"],
            "is_paused": snap["is_paused"],
            "current_nav_index": snap["current_nav_index"] + 1,
            "total_nav_points": snap["total_nav_points"],
            "is_arrived": snap["is_arrived"],
            "current_pose": snap["pose"],
            "current_target": snap["current_target"],
            "timestamp": now_ms(),
        }
        if snap["current_target"]:
            dx = snap["pose"].get("x", 0.0) - snap["current_target"].get("x", 0.0)
            dy = snap["pose"].get("y", 0.0) - snap["current_target"].get("y", 0.0)
            response["distance_to_target"] = (dx * dx + dy * dy) ** 0.5
        return response

    def list_maps(self) -> dict[str, Any]:
        return {"maps": self.store.list_maps(), "current_map": self.state.snapshot()["current_map"]}

    def load_map_by_name(self, map_name: str, x: float, y: float, z: float, yaw: float, wait: bool) -> dict[str, Any]:
        try:
            path = self.store.resolve_map_name(map_name)
        except (FileNotFoundError, ValueError) as exc:
            self.state.mark_error(str(exc), status_code=404)
            return {"success": False, "message": str(exc), "status_code": 404}
        return self.relocation(path, x=x, y=y, z=z, yaw=yaw, wait_for_localization=wait)

    def save_current_poi(self, name: str, map_name: str | None = None, tags: list[str] | None = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        point = legacy_point_from_pose(name, self.get_pose())
        if map_name:
            point["map_name"] = map_name
        if tags:
            point["tags"] = tags
        if meta:
            point["meta"] = meta
        points, map_file, initial_pose = self.store.load_nav_points()
        points = [p for p in points if p.get("name") != name]
        points.append(point)
        self.store.save_nav_points(points, map_file or self.state.snapshot()["current_map"], initial_pose)
        return {"success": True, "poi": point}

    def upsert_poi(self, point: dict[str, Any]) -> dict[str, Any]:
        points, map_file, initial_pose = self.store.load_nav_points()
        points = [p for p in points if p.get("name") != point.get("name")]
        points.append(point)
        self.store.save_nav_points(points, map_file or self.state.snapshot()["current_map"], initial_pose)
        return {"success": True, "poi": point}

    def delete_poi(self, name: str) -> dict[str, Any]:
        points, map_file, initial_pose = self.store.load_nav_points()
        new_points = [p for p in points if p.get("name") != name]
        self.store.save_nav_points(new_points, map_file or self.state.snapshot()["current_map"], initial_pose)
        return {"success": len(new_points) != len(points), "count": len(new_points)}

    def goto_poi(self, name: str, force: bool = False) -> dict[str, Any]:
        points, _, _ = self.store.load_nav_points()
        for point in points:
            if point.get("name") == name:
                return self.navigate_to(point, label=name, force=force)
        return {"status": "failed", "message": f"poi not found: {name}", "status_code": 404}

    def current_action(self) -> dict[str, Any]:
        result = self._safe_ros_call(lambda: self.ros.get_current_action(), "get_current_action")
        self.state.set_current_action(result)
        return {"ros": result, "cached": self.state.snapshot()["current_action"], "action_status": self.state.snapshot()["action_status"]}

    def _cruise_loop(self, points: list[dict[str, Any]]) -> None:
        while not self._cruise_stop.is_set() and self.state.current_nav_index < len(points):
            while self._cruise_pause.is_set() and not self._cruise_stop.is_set():
                time.sleep(0.1)
            if self._cruise_stop.is_set():
                break

            index = self.state.current_nav_index
            target = points[index]
            self.state.current_target = target
            self.state.is_arrived = False
            self.events.publish({"event_type": "nav_start", "timestamp": now_ms(), "target": target, "index": index + 1, "total": len(points)})
            result = self._safe_ros_call(
                lambda: self.ros.navigate_to_pose(target, wait=True, timeout_sec=self.config.nav_goal_timeout_sec),
                "cruise_nav",
            )
            succeeded = int(result.get("status", 0)) == 4 or result.get("success") is True
            if succeeded:
                self.state.is_arrived = True
                self.events.publish({"event_type": "nav_arrival", "timestamp": now_ms(), "target_name": target.get("name"), "is_arrived": True, "current_nav_index": index + 1, "total_nav_points": len(points), "current_pose": self.get_pose(), "current_nav_name": self.state.current_nav_name})
            else:
                self.events.publish({"event_type": "nav_failed", "timestamp": now_ms(), "target_name": target.get("name"), "reason": result.get("message", "navigation failed"), "result": result})
            self.state.current_nav_index += 1

        if not self._cruise_stop.is_set() and self.state.current_nav_index >= len(points):
            self.state.is_cruising = False
            self.state.is_paused = False
            self.events.publish({"event_type": "cruise_complete", "timestamp": now_ms(), "message": "all navigation points completed", "total_points": len(points), "current_nav_name": self.state.current_nav_name})

    def _safe_ros_call(self, fn: Any, action_name: str) -> dict[str, Any]:
        try:
            result = fn()
            status_code = int(result.get("result", result.get("status", 0)) or 0)
            self.state.status_code = status_code
            self.state.last_error = None
            return result
        except BridgeUnavailable as exc:
            self.state.mark_error(str(exc), status_code=-1)
            return {"success": False, "message": str(exc), "action": action_name, "status_code": -1}
        except Exception as exc:
            self.state.mark_error(str(exc), status_code=-1)
            return {"success": False, "message": str(exc), "action": action_name, "status_code": -1}


def point_to_pose_in(point: dict[str, Any]) -> dict[str, Any]:
    return pose_dict(
        x=point.get("x", 0.0),
        y=point.get("y", 0.0),
        z=point.get("z", 0.0),
        q_x=point.get("q_x", 0.0),
        q_y=point.get("q_y", 0.0),
        q_z=point.get("q_z", 0.0),
        q_w=point.get("q_w", 1.0),
        frame_id=point.get("frame_id", "map"),
    )


def point_yaw(point: dict[str, Any]) -> float:
    return yaw_from_quaternion(
        float(point.get("q_x", 0.0)),
        float(point.get("q_y", 0.0)),
        float(point.get("q_z", 0.0)),
        float(point.get("q_w", 1.0)),
    )
