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
        self.aurora.stop()
        self.ros.stop()

    def legacy_status(self) -> dict[str, Any]:
        snap = self.state.snapshot()
        aurora = self.aurora.state()
        navigation_readiness = self.readiness(snap=snap, aurora=aurora)
        mapping_readiness = self.mapping_readiness(snap=snap)
        poi_readiness = self.poi_readiness(snap=snap)
        motion_authority = self.motion_authority(aurora=aurora)
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
            "localization_status": self._localization_status_for_display(snap),
            "last_error": snap["last_error"],
        }
        status["map_config"] = self.map_config(snap=snap)
        status["ready_for_mapping"] = mapping_readiness["ready"]
        status["ready_for_poi"] = poi_readiness["ready"]
        status["ready_for_navigation"] = navigation_readiness["ready"]
        status["mapping_readiness"] = mapping_readiness
        status["poi_readiness"] = poi_readiness
        status["motion_authority"] = motion_authority
        status["aurora"] = aurora
        status["ros"] = self.ros.diagnostics()
        return status

    def status(self) -> dict[str, Any]:
        snap = self.state.snapshot()
        aurora = self.aurora.state()
        mapping_readiness = self.mapping_readiness(snap=snap)
        poi_readiness = self.poi_readiness(snap=snap)
        navigation_readiness = self.readiness(snap=snap, aurora=aurora)
        motion_authority = self.motion_authority(aurora=aurora)
        return {
            "adapter": {"status": "running", "namespace": self.config.ns},
            "ros": self.ros.diagnostics(),
            "aurora": aurora,
            "runtime": snap,
            "map_config": self.map_config(snap=snap),
            "motion_authority": motion_authority,
            "workflow": {
                "manual_mapping": mapping_readiness,
                "manual_poi": poi_readiness,
                "auto_navigation": navigation_readiness,
                "motion_authority": motion_authority,
            },
            "readiness": navigation_readiness,
            "navigation_readiness": navigation_readiness,
            "mapping_readiness": mapping_readiness,
            "poi_readiness": poi_readiness,
        }

    def get_pose(self) -> dict[str, Any]:
        return self.state.snapshot()["pose"]

    def localization_status(self) -> dict[str, Any]:
        snap = self.state.snapshot()
        poi_readiness = self.poi_readiness(snap=snap)
        navigation_readiness = self.readiness(snap=snap)
        return {
            "current_map": snap["current_map"],
            "slam_mode": snap["slam_mode"],
            "pose": snap["pose"],
            "pose_age_sec": snap["pose_age_sec"],
            "odom_status_code": snap["odom_status_code"],
            "odom_status": self._localization_status_for_display(snap),
            "odom_status_score": snap["odom_status_score"],
            "odom_status_age_sec": snap["odom_status_age_sec"],
            "health": snap["health"],
            "mapping_readiness": self.mapping_readiness(snap=snap),
            "poi_readiness": poi_readiness,
            "navigation_readiness": navigation_readiness,
            "ready": poi_readiness["ready"],
        }

    def workflow_status(self) -> dict[str, Any]:
        snap = self.state.snapshot()
        aurora = self.aurora.state()
        mapping_readiness = self.mapping_readiness(snap=snap)
        poi_readiness = self.poi_readiness(snap=snap)
        navigation_readiness = self.readiness(snap=snap, aurora=aurora)
        motion_authority = self.motion_authority(aurora=aurora)
        return {
            "namespace": self.config.ns,
            "ros": self.ros.diagnostics(),
            "aurora": aurora,
            "map_config": self.map_config(snap=snap),
            "motion_authority": motion_authority,
            "manual_mapping": mapping_readiness,
            "manual_poi": poi_readiness,
            "auto_navigation": navigation_readiness,
        }

    def map_config(self, snap: dict[str, Any] | None = None) -> dict[str, Any]:
        snap = snap or self.state.snapshot()
        current_map = snap["current_map"]
        return {
            "map_root": str(self.config.map_root),
            "default_map_name": self.config.default_map_name,
            "default_map_path": self.config.default_map_path,
            "current_map": current_map,
            "current_map_name": self.store.map_name_from_path(current_map),
            "save_timeout_sec": self.config.map_save_timeout_sec,
        }

    def motion_authority(self, aurora: dict[str, Any] | None = None) -> dict[str, Any]:
        aurora = aurora if aurora is not None else self.aurora.state()
        raw = aurora.get("raw") if isinstance(aurora.get("raw"), dict) else {}
        raw_value = raw.get("value") if isinstance(raw.get("value"), dict) else {}
        velocity_source = raw_value.get("velocity_source")
        velocity_source_name = raw_value.get("velocity_source_name") or aurora.get("velocity_source_name")
        authority = "unknown"
        if isinstance(velocity_source_name, str):
            source = velocity_source_name.strip().lower()
            if "joystick" in source or "remote" in source:
                authority = "manual_joystick"
            elif "navigation" in source or source == "nav":
                authority = "navigation"
            elif source:
                authority = source
        elif self._motion_policy() == "none":
            authority = "external_manual_or_nav2"
        elif self._motion_policy() == "observe":
            authority = "observed_external"
        elif self._motion_policy() == "aurora":
            authority = "aurora_guarded_navigation"

        return {
            "policy": self._motion_policy(),
            "aurora_required": self._motion_guard_requires_aurora(),
            "aurora_observed": self._motion_guard_observes_aurora(),
            "aurora_connected": bool(aurora.get("connected")),
            "aurora_backend": aurora.get("backend"),
            "velocity_source": velocity_source,
            "velocity_source_name": velocity_source_name,
            "authority": authority,
            "manual_mapping_motion": "remote_or_joystick",
            "manual_poi_motion": "remote_or_joystick",
            "auto_navigation_motion": "nav2_goal",
            "aurora_commands_enabled": self._motion_guard_requires_aurora(),
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

        aurora_connected = bool(aurora.get("connected"))
        aurora_standing = bool(aurora.get("standing"))
        aurora_standing_known = bool(aurora.get("standing_known", "standing" in aurora))
        aurora_required = self._motion_guard_requires_aurora()
        aurora_observed = self._motion_guard_observes_aurora()
        if aurora_required:
            if not aurora_connected:
                blockers.append("aurora_unavailable")
            elif aurora_standing_known and not aurora_standing:
                blockers.append("robot_not_standing")
            elif not aurora_standing_known:
                warnings.append("aurora_standing_unknown")
        elif aurora_observed:
            if not aurora_connected:
                warnings.append("aurora_unavailable")
            elif aurora_standing_known and not aurora_standing:
                warnings.append("robot_not_standing")
            elif not aurora_standing_known:
                warnings.append("aurora_standing_unknown")
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
                "motion_guard": self._motion_policy(),
                "aurora_required": aurora_required,
                "aurora_observed": aurora_observed,
                "aurora_connected": aurora_connected,
                "aurora_standing_known": aurora_standing_known,
                "robot_standing": aurora_standing,
            },
        }

    def mapping_readiness(self, snap: dict[str, Any] | None = None, aurora: dict[str, Any] | None = None) -> dict[str, Any]:
        snap = snap or self.state.snapshot()
        blockers: list[str] = []
        warnings: list[str] = []

        if not self.ros.available:
            blockers.append("ros_python_unavailable")
        elif not self.ros.ready:
            blockers.append("ros_bridge_not_ready")

        if not self._is_mapping_mode(snap["slam_mode"]):
            blockers.append("not_in_mapping_mode")
        if snap["pose_age_sec"] is None or snap["pose_age_sec"] > 3.0:
            blockers.append("robot_pose_not_fresh")
        if snap["health"].get("has_error") or snap["health"].get("has_fatal"):
            blockers.append("health_error")

        if snap["odom_status_code"] is None:
            warnings.append("odom_status_not_published_in_mapping")

        return {
            "ready": not blockers,
            "blockers": blockers,
            "warnings": warnings,
            "checks": {
                "ros_available": self.ros.available,
                "ros_ready": self.ros.ready,
                "mapping_mode": self._is_mapping_mode(snap["slam_mode"]),
                "pose_fresh": snap["pose_age_sec"] is not None and snap["pose_age_sec"] <= 3.0,
                "health_ok": not snap["health"].get("has_error") and not snap["health"].get("has_fatal"),
                "manual_motion": True,
                "motion_source": "remote_or_joystick",
            },
        }

    def poi_readiness(self, snap: dict[str, Any] | None = None) -> dict[str, Any]:
        snap = snap or self.state.snapshot()
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
                "manual_motion": True,
                "motion_source": "remote_or_joystick",
            },
        }

    def precheck_navigation(self, force: bool = False) -> dict[str, Any]:
        readiness = self.readiness()
        if force or readiness["ready"]:
            return {"ok": True, "readiness": readiness}
        return {"ok": False, "readiness": readiness}

    def start_mapping(self, map_path: str | None = None, map_name: str | None = None) -> dict[str, Any]:
        try:
            target = self._resolve_map_target(map_path=map_path, map_name=map_name)
        except (FileNotFoundError, ValueError) as exc:
            return self._map_target_error(exc, "start_mapping")
        result = self._safe_ros_call(lambda: self.ros.switch_mode("mapping"), "start_mapping")
        if result.get("success", True):
            self._record_current_map(target, map_name=map_name)
        result["map_file"] = target
        result["map_name"] = self.store.map_name_from_path(target)
        result["save_timing"] = "map data is written when stop_mapping/save_map is called"
        return result

    def stop_mapping(self, map_path: str | None = None, map_name: str | None = None) -> dict[str, Any]:
        try:
            target = self._resolve_map_target(map_path=map_path, map_name=map_name)
        except (FileNotFoundError, ValueError) as exc:
            return self._map_target_error(exc, "stop_mapping")
        result = self._safe_ros_call(lambda: self.ros.save_map(target), "stop_mapping")
        result["map_file"] = target
        result["map_name"] = self.store.map_name_from_path(target)
        result["timeout_sec"] = self.config.map_save_timeout_sec
        if result.get("success", True):
            self._record_current_map(target, map_name=map_name)
        return result

    def set_map_path(self, path: str) -> dict[str, Any]:
        try:
            target = self._resolve_map_target(map_path=path)
        except (FileNotFoundError, ValueError) as exc:
            error = self._map_target_error(exc, "set_map_path")
            return {**self.legacy_status(), "result": error}
        self._record_current_map(target)
        return self.legacy_status()

    def relocation(
        self,
        map_path: str | None = None,
        map_name: str | None = None,
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
        yaw: float = 0.0,
        wait_for_localization: bool = False,
    ) -> dict[str, Any]:
        try:
            path = self._resolve_map_target(map_path=map_path, map_name=map_name, require_exists=True)
        except (FileNotFoundError, ValueError) as exc:
            error = self._map_target_error(exc, "relocation")
            return {**self.legacy_status(), "result": error}
        result = self._safe_ros_call(lambda: self.ros.load_map(path, x=x, y=y, z=z, yaw=yaw), "relocation")
        if result.get("success", True):
            self._record_current_map(path, map_name=map_name)
        if wait_for_localization:
            result["wait"] = self.wait_for_localization()
        return {**self.legacy_status(), "result": result}

    def _resolve_map_target(
        self,
        map_path: str | None = None,
        map_name: str | None = None,
        fallback_current: bool = True,
        require_exists: bool = False,
    ) -> str:
        raw_path = str(map_path or "").strip()
        raw_name = str(map_name or "").strip()
        if raw_path:
            return self.store.resolve_map_reference(raw_path, require_exists=require_exists)
        if raw_name:
            return self.store.resolve_map_reference(raw_name, require_exists=require_exists)
        if fallback_current and self.state.snapshot()["current_map"]:
            if require_exists:
                return self.store.resolve_map_reference(self.state.snapshot()["current_map"], require_exists=True)
            return self.state.snapshot()["current_map"]
        if require_exists:
            return self.store.resolve_map_reference(self.config.default_map_path, require_exists=True)
        return self.config.default_map_path

    def _map_target_error(self, exc: Exception, action_name: str) -> dict[str, Any]:
        status_code = 404 if isinstance(exc, FileNotFoundError) else 400
        self.state.mark_error(str(exc), status_code=status_code)
        return {"success": False, "message": str(exc), "action": action_name, "status_code": status_code}

    def _record_current_map(self, path: str, map_name: str | None = None) -> None:
        self.state.current_map = path
        runtime = self.store.load_runtime()
        runtime["current_map"] = path
        runtime["current_map_name"] = map_name or self.store.map_name_from_path(path)
        runtime["map_root"] = str(self.config.map_root)
        self.store.save_runtime(runtime)

    def wait_for_localization(self, timeout_sec: float = 30.0) -> dict[str, Any]:
        start = time.monotonic()
        while time.monotonic() - start < timeout_sec:
            readiness = self.poi_readiness()
            if readiness["checks"]["localization_good"] and readiness["checks"]["pose_fresh"]:
                return {"ready": True, "elapsed_sec": round(time.monotonic() - start, 2)}
            time.sleep(0.2)
        return {"ready": False, "elapsed_sec": round(time.monotonic() - start, 2), "readiness": self.poi_readiness()}

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
            self._record_current_map(map_file)
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
            self._record_current_map(map_file)
        self.state.current_nav_name = name
        self.state.total_nav_points = len(points)
        return self.legacy_status()

    def navigate_to(self, target: dict[str, Any], label: str = "API Target", force: bool = False) -> dict[str, Any]:
        with self._nav_lock:
            check = self.precheck_navigation(force=force)
            if not check["ok"]:
                self.state.mark_error("navigation precheck failed", status_code=409)
                return {"status": "blocked", "message": "navigation precheck failed", "precheck": check, "status_code": 409}

            motion_guard = self.prepare_auto_navigation_motion()
            if motion_guard.get("required") and not motion_guard.get("success"):
                self.state.mark_error("ensure_stand failed", status_code=409)
                return {"status": "blocked", "message": "ensure_stand failed", "motion_guard": motion_guard, "status_code": 409}

            self.state.set_navigation_task({"status": "running", "label": label, "target": target, "started_at": now_ms()})
            result = self._safe_ros_call(lambda: self.ros.navigate_to_pose(target, wait=False), "navigate_to")
            self.state.set_current_action({"action_name": "navigate_to_pose", "target": target, "result": result})
            return {
                "status": "success" if result.get("accepted", result.get("success", False)) else "failed",
                "message": "Navigation command sent",
                "target": target,
                "motion_guard": motion_guard,
                "status_code": self.state.status_code,
                "result": result,
            }

    def start_cruise(self, force: bool = False) -> dict[str, Any]:
        points, _, _ = self.store.load_nav_points()
        if not points:
            self.state.mark_error("no navigation points", status_code=400)
            return {"status": "failed", "message": "no navigation points", **self.legacy_status()}
        check = self.precheck_navigation(force=force)
        if not check["ok"]:
            self.state.mark_error("cruise precheck failed", status_code=409)
            return {"status": "blocked", "message": "cruise precheck failed", "precheck": check, **self.legacy_status()}

        motion_guard = self.prepare_auto_navigation_motion()
        if motion_guard.get("required") and not motion_guard.get("success"):
            self.state.mark_error("ensure_stand failed", status_code=409)
            return {"status": "blocked", "message": "ensure_stand failed", "motion_guard": motion_guard, **self.legacy_status()}

        if self.state.snapshot()["is_cruising"]:
            self.stop_cruise(cancel_robot=True)
        else:
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
        return {**self.legacy_status(), "motion_guard": motion_guard}

    def stop_cruise(self, cancel_robot: bool = True) -> dict[str, Any]:
        was_cruising = self.state.snapshot()["is_cruising"]
        self._cruise_stop.set()
        self._cruise_pause.clear()
        thread = self._cruise_thread
        motion_stop: dict[str, Any] | None = None
        if cancel_robot:
            try:
                self.ros.cancel_current_action()
            except Exception:
                pass
            motion_stop = self.stop_motion_by_policy()
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
            if not thread.is_alive():
                self._cruise_thread = None
        self.state.is_cruising = False
        self.state.is_paused = False
        self.state.set_navigation_task({"status": "idle"})
        if was_cruising:
            self.events.publish({"event_type": "cruise_stop", "timestamp": now_ms(), "completed_points": self.state.current_nav_index, "total_points": self.state.total_nav_points})
        status = self.legacy_status()
        if motion_stop is not None:
            status["motion_stop"] = motion_stop
        return status

    def cancel_navigation(self) -> dict[str, Any]:
        result = self._safe_ros_call(lambda: self.ros.cancel_current_action(), "cancel")
        motion_stop = self.stop_motion_by_policy()
        self._cruise_stop.set()
        self._cruise_pause.clear()
        self.state.is_cruising = False
        self.state.is_paused = False
        self.state.set_navigation_task({"status": "idle"})
        return {"result": result, "motion_stop": motion_stop, "status": self.legacy_status()}

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
        snap = self.state.snapshot()
        return {
            "maps": self.store.list_maps(),
            "current_map": snap["current_map"],
            "map_config": self.map_config(snap=snap),
        }

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

    def prepare_auto_navigation_motion(self) -> dict[str, Any]:
        policy = self._motion_policy()
        if not self._motion_guard_requires_aurora():
            return {
                "success": True,
                "required": False,
                "skipped": True,
                "policy": policy,
                "message": "Aurora motion guard disabled; Nav2 owns autonomous navigation command",
            }
        result = self.aurora.ensure_stand()
        result["required"] = True
        result["policy"] = policy
        return result

    def stop_motion_by_policy(self) -> dict[str, Any]:
        policy = self._motion_policy()
        if not self._motion_guard_requires_aurora():
            return {
                "success": True,
                "required": False,
                "skipped": True,
                "policy": policy,
                "message": "Aurora stop_motion skipped by motion policy",
            }
        result = self.aurora.stop_motion()
        result["required"] = True
        result["policy"] = policy
        return result

    def _motion_policy(self) -> str:
        policy = (self.config.motion_guard or "none").strip().lower()
        if policy in {"none", "observe", "aurora"}:
            return policy
        return "none"

    def _motion_guard_requires_aurora(self) -> bool:
        return self.config.require_aurora or self._motion_policy() == "aurora"

    def _motion_guard_observes_aurora(self) -> bool:
        return self._motion_policy() in {"observe", "aurora"} or self.config.require_aurora

    @staticmethod
    def _is_mapping_mode(mode: Any) -> bool:
        return str(mode or "").strip().lower() in {"mapping", "map", "0"}

    def _localization_status_for_display(self, snap: dict[str, Any]) -> str:
        if self._is_mapping_mode(snap["slam_mode"]) and snap["odom_status_code"] is None:
            return "NOT_REQUIRED_IN_MAPPING"
        return RuntimeState.localization_status_from_code(snap["odom_status_code"])

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
        if self._cruise_thread is threading.current_thread():
            self._cruise_thread = None

    def _safe_ros_call(self, fn: Any, action_name: str) -> dict[str, Any]:
        try:
            result = fn()
            self.state.status_code = self._status_code_from_result(result)
            self.state.last_error = None
            return result
        except BridgeUnavailable as exc:
            self.state.mark_error(str(exc), status_code=-1)
            return {"success": False, "message": str(exc), "action": action_name, "status_code": -1}
        except Exception as exc:
            self.state.mark_error(str(exc), status_code=-1)
            return {"success": False, "message": str(exc), "action": action_name, "status_code": -1}

    @staticmethod
    def _status_code_from_result(result: dict[str, Any]) -> int:
        if result.get("success") is False or result.get("accepted") is False:
            for key in ("status_code", "result", "status"):
                value = result.get(key)
                if value is None:
                    continue
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return -1
            return -1
        value = result.get("status_code")
        if value is not None:
            try:
                code = int(value)
                if code < 0:
                    return code
            except (TypeError, ValueError):
                return -1
        return 0


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
