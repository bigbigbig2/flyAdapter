from __future__ import annotations

import threading
import time
import os
from typing import Any, Callable

from app.config import AppConfig
from app.core.events import EventHub
from app.core.state import RuntimeState
from app.core.utils import now_ms, pose_dict, quaternion_from_yaw


class BridgeUnavailable(RuntimeError):
    pass


class RosBridge:
    def __init__(self, config: AppConfig, state: RuntimeState, events: EventHub) -> None:
        self.config = config
        self.state = state
        self.events = events
        self.available = False
        self.ready = False
        self.error: str | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._node: Any | None = None
        self._clients: dict[str, Any] = {}
        self._types: dict[str, Any] = {}
        self._nav_client: Any | None = None
        self._initial_pose_pub: Any | None = None
        self._nav_points_pub: Any | None = None
        self._current_goal_pub: Any | None = None
        self._cruise_path_pub: Any | None = None
        self._last_pose_event_s = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._spin_thread, name="ros-bridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def diagnostics(self) -> dict[str, Any]:
        clients: dict[str, Any] = {}
        for name, client in self._clients.items():
            try:
                clients[name] = {
                    "service": client.srv_name,
                    "ready": self.service_ready(name),
                }
            except Exception as exc:
                clients[name] = {"error": str(exc)}
        return {
            "available": self.available,
            "ready": self.ready,
            "namespace": self.config.ns,
            "error": self.error,
            "ros_domain_id": os.getenv("ROS_DOMAIN_ID", ""),
            "rmw_implementation": os.getenv("RMW_IMPLEMENTATION", ""),
            "clients": clients,
            "visualization_topics": self.visualization_topics(),
        }

    def service_ready(self, client_name: str) -> bool:
        client = self._clients.get(client_name)
        if client is None:
            return False
        try:
            return bool(client.service_is_ready())
        except Exception:
            return False

    def switch_mode(self, mode: str) -> dict[str, Any]:
        SetMode = self._require_type("SetMode")
        req = SetMode.Request()
        req.mode = mode
        return self._call_service("set_mode", req)

    def load_map(self, map_path: str, x: float = 0.0, y: float = 0.0, z: float = 0.0, yaw: float = 0.0) -> dict[str, Any]:
        LoadMap = self._require_type("LoadMap")
        req = LoadMap.Request()
        req.map_path = map_path
        req.x = float(x)
        req.y = float(y)
        req.z = float(z)
        req.yaw = float(yaw)
        result = self._call_service("load_map", req, timeout_sec=self.config.map_load_timeout_sec)
        if "result" in result:
            try:
                code = int(result.get("result", -1))
            except (TypeError, ValueError):
                code = -1
            result["success"] = code == 0
            result["status_code"] = code
            result.setdefault("message", self._load_map_response_message(code))
        return result

    def save_map(self, map_id: str) -> dict[str, Any]:
        SaveMap = self._require_type("SaveMap")
        req = SaveMap.Request()
        req.map_id = map_id
        result = self._call_service("save_map", req, timeout_sec=self.config.map_save_timeout_sec)
        if "response" in result:
            try:
                code = int(result.get("response", -1))
            except (TypeError, ValueError):
                code = -1
            result["success"] = code == 0
            result["status_code"] = code
            result.setdefault("message", self._save_map_response_message(code))
        return result

    def cancel_current_action(self) -> dict[str, Any]:
        CancelCurrentAction = self._require_type("CancelCurrentAction")
        req = CancelCurrentAction.Request()
        return self._call_service("cancel_current_action", req)

    def get_current_action(self) -> dict[str, Any]:
        GetCurrentAction = self._require_type("GetCurrentAction")
        req = GetCurrentAction.Request()
        return self._call_service("get_current_action", req)

    def publish_initial_pose(self, x: float, y: float, z: float = 0.0, yaw: float = 0.0, frame_id: str = "map") -> dict[str, Any]:
        self._require_ready()
        PoseWithCovarianceStamped = self._require_type("PoseWithCovarianceStamped")
        msg = PoseWithCovarianceStamped()
        msg.header.frame_id = frame_id
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.pose.pose.position.x = float(x)
        msg.pose.pose.position.y = float(y)
        msg.pose.pose.position.z = float(z)
        quat = quaternion_from_yaw(float(yaw))
        msg.pose.pose.orientation.x = quat["q_x"]
        msg.pose.pose.orientation.y = quat["q_y"]
        msg.pose.pose.orientation.z = quat["q_z"]
        msg.pose.pose.orientation.w = quat["q_w"]
        msg.pose.covariance[0] = 0.25
        msg.pose.covariance[7] = 0.25
        msg.pose.covariance[35] = 0.0685
        self._initial_pose_pub.publish(msg)
        return {"success": True, "message": "initial pose published"}

    def visualization_topics(self) -> dict[str, str]:
        return {
            "nav_points": self.config.ros_name("gr3/nav_points"),
            "current_goal": self.config.ros_name("gr3/current_goal"),
            "cruise_path": self.config.ros_name("gr3/cruise_path"),
        }

    def publish_nav_points(
        self,
        points: list[dict[str, Any]],
        map_file: str = "",
        active_name: str | None = None,
    ) -> dict[str, Any]:
        self._require_ready()
        if self._nav_points_pub is None:
            raise BridgeUnavailable("nav point marker publisher is not ready")
        MarkerArray = self._require_type("MarkerArray")
        msg = MarkerArray()
        msg.markers.append(self._delete_all_marker("gr3_nav_points"))
        stamp = self._node.get_clock().now().to_msg()
        for index, point in enumerate(points):
            active = bool(active_name and point.get("name") == active_name)
            msg.markers.extend(self._point_markers(point, index, "gr3_nav_points", stamp, active=active))
        self._nav_points_pub.publish(msg)
        return {
            "success": True,
            "message": "nav point markers published",
            "count": len(points),
            "map_file": map_file,
            "topics": self.visualization_topics(),
        }

    def publish_current_goal(self, point: dict[str, Any] | None) -> dict[str, Any]:
        self._require_ready()
        if self._current_goal_pub is None:
            raise BridgeUnavailable("current goal marker publisher is not ready")
        MarkerArray = self._require_type("MarkerArray")
        msg = MarkerArray()
        msg.markers.append(self._delete_all_marker("gr3_current_goal"))
        if point:
            stamp = self._node.get_clock().now().to_msg()
            msg.markers.extend(self._point_markers(point, 0, "gr3_current_goal", stamp, active=True, label_prefix="GOAL "))
        self._current_goal_pub.publish(msg)
        return {
            "success": True,
            "message": "current goal marker published" if point else "current goal marker cleared",
            "target": point,
            "topics": self.visualization_topics(),
        }

    def publish_cruise_path(self, points: list[dict[str, Any]], map_file: str = "") -> dict[str, Any]:
        self._require_ready()
        if self._cruise_path_pub is None:
            raise BridgeUnavailable("cruise path publisher is not ready")
        Path = self._require_type("Path")
        PoseStamped = self._require_type("PoseStamped")
        msg = Path()
        msg.header.frame_id = self._frame_id(points[0]) if points else "map"
        msg.header.stamp = self._node.get_clock().now().to_msg()
        for point in points:
            pose = PoseStamped()
            pose.header.frame_id = self._frame_id(point)
            pose.header.stamp = msg.header.stamp
            pose.pose.position.x = float(point.get("x", 0.0))
            pose.pose.position.y = float(point.get("y", 0.0))
            pose.pose.position.z = float(point.get("z", 0.0))
            pose.pose.orientation.x = float(point.get("q_x", 0.0))
            pose.pose.orientation.y = float(point.get("q_y", 0.0))
            pose.pose.orientation.z = float(point.get("q_z", 0.0))
            pose.pose.orientation.w = float(point.get("q_w", 1.0))
            msg.poses.append(pose)
        self._cruise_path_pub.publish(msg)
        return {
            "success": True,
            "message": "cruise path published",
            "count": len(points),
            "map_file": map_file,
            "topics": self.visualization_topics(),
        }

    def navigate_to_pose(
        self,
        pose: dict[str, Any],
        wait: bool = False,
        timeout_sec: float | None = None,
        feedback_cb: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        self._require_ready()
        if self._nav_client is None:
            raise BridgeUnavailable("navigate_to_pose action client is not ready")
        NavigateToPose = self._require_type("NavigateToPose")
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = pose.get("frame_id", "map")
        goal.pose.header.stamp = self._node.get_clock().now().to_msg()
        goal.pose.pose.position.x = float(pose.get("x", 0.0))
        goal.pose.pose.position.y = float(pose.get("y", 0.0))
        goal.pose.pose.position.z = float(pose.get("z", 0.0))
        goal.pose.pose.orientation.x = float(pose.get("q_x", 0.0))
        goal.pose.pose.orientation.y = float(pose.get("q_y", 0.0))
        goal.pose.pose.orientation.z = float(pose.get("q_z", 0.0))
        goal.pose.pose.orientation.w = float(pose.get("q_w", 1.0))

        if not self._nav_client.wait_for_server(timeout_sec=3.0):
            raise BridgeUnavailable(self.config.ros_name("navigate_to_pose") + " action server unavailable")

        def _feedback(msg: Any) -> None:
            if feedback_cb is None:
                return
            feedback = getattr(msg, "feedback", None)
            feedback_cb({"raw": str(feedback)})

        future = self._nav_client.send_goal_async(goal, feedback_callback=_feedback)
        goal_handle = self._wait_future(future, timeout_sec=5.0)
        if not goal_handle or not goal_handle.accepted:
            return {"accepted": False, "status": 6, "message": "goal rejected"}

        if not wait:
            return {"accepted": True, "status": 2, "message": "goal accepted"}

        result_future = goal_handle.get_result_async()
        result = self._wait_future(result_future, timeout_sec=timeout_sec)
        if result is None:
            return {"accepted": True, "status": 3, "message": "goal timeout"}
        return {"accepted": True, "status": int(getattr(result, "status", 0)), "message": "goal completed"}

    def _spin_thread(self) -> None:
        try:
            import rclpy
            from action_msgs.msg import GoalStatus
            from fourier_msgs.msg import ActionStatus, EventsInfo, HealthInfo
            from fourier_msgs.srv import CancelCurrentAction, GetCurrentAction, LoadMap, SaveMap, SetMode
            from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
            from nav2_msgs.action import NavigateToPose
            from nav_msgs.msg import Path
            from rclpy.action import ActionClient
            from rclpy.node import Node
            from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
            from std_msgs.msg import Float32, Int8, String
            from visualization_msgs.msg import Marker, MarkerArray
        except Exception as exc:
            self.available = False
            self.ready = False
            self.error = f"ROS2 Python imports unavailable: {exc}"
            return

        self.available = True
        self._types.update(
            {
                "CancelCurrentAction": CancelCurrentAction,
                "GetCurrentAction": GetCurrentAction,
                "LoadMap": LoadMap,
                "SaveMap": SaveMap,
                "SetMode": SetMode,
                "PoseWithCovarianceStamped": PoseWithCovarianceStamped,
                "PoseStamped": PoseStamped,
                "NavigateToPose": NavigateToPose,
                "GoalStatus": GoalStatus,
                "Marker": Marker,
                "MarkerArray": MarkerArray,
                "Path": Path,
            }
        )

        try:
            if not rclpy.ok():
                rclpy.init(args=None)
            node = Node("gr3_adapter")
            self._node = node

            node.create_subscription(String, self.config.ros_name("slam/mode_status"), self._on_slam_mode, 10)
            node.create_subscription(Int8, self.config.ros_name("odom_status_code"), self._on_odom_status_code, 10)
            node.create_subscription(Float32, self.config.ros_name("odom_status_score"), self._on_odom_status_score, 10)
            node.create_subscription(ActionStatus, self.config.ros_name("action_status"), self._on_action_status, 10)
            node.create_subscription(HealthInfo, self.config.ros_name("Humanoid_nav/health"), self._on_health, 10)
            node.create_subscription(EventsInfo, self.config.ros_name("Humanoid_nav/events"), self._on_events, 10)

            node.create_subscription(PoseStamped, self.config.ros_name("robot_pose"), self._on_robot_pose, 20)

            self._clients = {
                "set_mode": node.create_client(SetMode, self.config.ros_name("slam/set_mode")),
                "load_map": node.create_client(LoadMap, self.config.ros_name("slam/load_map")),
                "save_map": node.create_client(SaveMap, self.config.ros_name("slam/save_map")),
                "cancel_current_action": node.create_client(CancelCurrentAction, self.config.ros_name("cancel_current_action")),
                "get_current_action": node.create_client(GetCurrentAction, self.config.ros_name("get_current_action")),
            }
            self._nav_client = ActionClient(node, NavigateToPose, self.config.ros_name("navigate_to_pose"))
            self._initial_pose_pub = node.create_publisher(
                PoseWithCovarianceStamped, self.config.ros_name("initialpose"), 10
            )
            visual_qos = QoSProfile(depth=1)
            visual_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL
            visual_qos.reliability = ReliabilityPolicy.RELIABLE
            self._nav_points_pub = node.create_publisher(
                MarkerArray, self.config.ros_name("gr3/nav_points"), visual_qos
            )
            self._current_goal_pub = node.create_publisher(
                MarkerArray, self.config.ros_name("gr3/current_goal"), visual_qos
            )
            self._cruise_path_pub = node.create_publisher(
                Path, self.config.ros_name("gr3/cruise_path"), visual_qos
            )
            self.ready = True
            self.error = None

            while not self._stop.is_set():
                rclpy.spin_once(node, timeout_sec=0.1)
        except Exception as exc:
            self.ready = False
            self.error = str(exc)
        finally:
            try:
                if self._node is not None:
                    self._node.destroy_node()
            except Exception:
                pass

    def _on_robot_pose(self, msg: Any) -> None:
        pose = pose_dict(
            x=msg.pose.position.x,
            y=msg.pose.position.y,
            z=msg.pose.position.z,
            q_x=msg.pose.orientation.x,
            q_y=msg.pose.orientation.y,
            q_z=msg.pose.orientation.z,
            q_w=msg.pose.orientation.w,
            frame_id=msg.header.frame_id or "map",
        )
        self.state.update_pose(pose)
        now = time.monotonic()
        if now - self._last_pose_event_s >= 2.0:
            self.events.publish({"event_type": "position_update", "timestamp": now_ms(), "current_pose": pose})
            self._last_pose_event_s = now

    def _on_slam_mode(self, msg: Any) -> None:
        self.state.update_slam_mode(str(msg.data))

    def _on_odom_status_code(self, msg: Any) -> None:
        self.state.update_odom_status_code(int(msg.data))

    def _on_odom_status_score(self, msg: Any) -> None:
        self.state.update_odom_status_score(float(msg.data))

    def _on_action_status(self, msg: Any) -> None:
        self.state.update_action_status(
            {
                "action_name": getattr(msg, "action_name", ""),
                "status": int(getattr(msg, "status", 0)),
                "status_description": getattr(msg, "status_description", ""),
            }
        )

    def _on_health(self, msg: Any) -> None:
        errors = []
        for error in getattr(msg, "errors", []):
            errors.append(
                {
                    "error_code": int(getattr(error, "error_code", 0)),
                    "level": int(getattr(error, "level", 0)),
                    "component": int(getattr(error, "component", 0)),
                    "message": getattr(error, "message", ""),
                    "timestamp": int(getattr(error, "timestamp", 0)),
                }
            )
        self.state.update_health(
            {
                "errors": errors,
                "has_warning": bool(getattr(msg, "has_warning", False)),
                "has_error": bool(getattr(msg, "has_error", False)),
                "has_fatal": bool(getattr(msg, "has_fatal", False)),
            }
        )

    def _on_events(self, msg: Any) -> None:
        events = []
        for event in getattr(msg, "events", []):
            payload = {
                "event_type": getattr(event, "event_type", ""),
                "message": getattr(event, "message", ""),
                "source": getattr(event, "source", ""),
                "timestamp": int(getattr(event, "timestamp", 0)),
            }
            events.append(payload)
            self.events.publish(payload)
        self.state.update_events(events)

    def _delete_all_marker(self, namespace: str) -> Any:
        Marker = self._require_type("Marker")
        marker = Marker()
        marker.header.frame_id = "map"
        marker.header.stamp = self._node.get_clock().now().to_msg()
        marker.ns = namespace
        marker.action = getattr(Marker, "DELETEALL", 3)
        return marker

    def _point_markers(
        self,
        point: dict[str, Any],
        index: int,
        namespace: str,
        stamp: Any,
        active: bool = False,
        label_prefix: str = "",
    ) -> list[Any]:
        Marker = self._require_type("Marker")
        base_id = index * 3
        name = str(point.get("name") or f"point_{index + 1}")
        frame_id = self._frame_id(point)
        x = float(point.get("x", 0.0))
        y = float(point.get("y", 0.0))
        z = float(point.get("z", 0.0))
        sphere_color = (1.0, 0.62, 0.12, 0.95) if active else (0.1, 0.55, 1.0, 0.85)
        text_color = (1.0, 0.92, 0.35, 1.0) if active else (0.86, 0.96, 1.0, 1.0)

        sphere = self._marker(Marker, namespace, base_id, frame_id, stamp, getattr(Marker, "SPHERE", 2))
        sphere.pose.position.x = x
        sphere.pose.position.y = y
        sphere.pose.position.z = z + 0.12
        sphere.pose.orientation.w = 1.0
        sphere.scale.x = 0.28 if active else 0.22
        sphere.scale.y = 0.28 if active else 0.22
        sphere.scale.z = 0.28 if active else 0.22
        self._set_color(sphere, sphere_color)

        arrow = self._marker(Marker, namespace, base_id + 1, frame_id, stamp, getattr(Marker, "ARROW", 0))
        arrow.pose.position.x = x
        arrow.pose.position.y = y
        arrow.pose.position.z = z + 0.16
        arrow.pose.orientation.x = float(point.get("q_x", 0.0))
        arrow.pose.orientation.y = float(point.get("q_y", 0.0))
        arrow.pose.orientation.z = float(point.get("q_z", 0.0))
        arrow.pose.orientation.w = float(point.get("q_w", 1.0))
        arrow.scale.x = 0.55 if active else 0.42
        arrow.scale.y = 0.08
        arrow.scale.z = 0.08
        self._set_color(arrow, sphere_color)

        text = self._marker(Marker, namespace, base_id + 2, frame_id, stamp, getattr(Marker, "TEXT_VIEW_FACING", 9))
        text.pose.position.x = x
        text.pose.position.y = y
        text.pose.position.z = z + 0.58
        text.pose.orientation.w = 1.0
        text.scale.z = 0.24 if active else 0.2
        text.text = f"{label_prefix}{index + 1}. {name}"
        self._set_color(text, text_color)
        return [sphere, arrow, text]

    @staticmethod
    def _marker(Marker: Any, namespace: str, marker_id: int, frame_id: str, stamp: Any, marker_type: int) -> Any:
        marker = Marker()
        marker.header.frame_id = frame_id
        marker.header.stamp = stamp
        marker.ns = namespace
        marker.id = marker_id
        marker.type = marker_type
        marker.action = getattr(Marker, "ADD", 0)
        return marker

    @staticmethod
    def _set_color(marker: Any, rgba: tuple[float, float, float, float]) -> None:
        marker.color.r = rgba[0]
        marker.color.g = rgba[1]
        marker.color.b = rgba[2]
        marker.color.a = rgba[3]

    @staticmethod
    def _frame_id(point: dict[str, Any]) -> str:
        return str(point.get("frame_id") or "map")

    def _call_service(self, client_name: str, req: Any, timeout_sec: float = 10.0) -> dict[str, Any]:
        self._require_ready()
        client = self._clients.get(client_name)
        if client is None:
            raise BridgeUnavailable(f"service client not ready: {client_name}")
        wait_sec = max(2.0, min(10.0, float(timeout_sec or 10.0)))
        if not client.wait_for_service(timeout_sec=wait_sec):
            raise BridgeUnavailable(f"service unavailable: {client.srv_name}")
        future = client.call_async(req)
        result = self._wait_future(future, timeout_sec=timeout_sec)
        if result is None:
            raise BridgeUnavailable(f"service timeout: {client.srv_name}")
        return self._message_to_dict(result)

    @staticmethod
    def _message_to_dict(msg: Any) -> dict[str, Any]:
        data: dict[str, Any] = {"success": True}
        for name in dir(msg):
            if name.startswith("_"):
                continue
            try:
                value = getattr(msg, name)
            except Exception:
                continue
            if callable(value):
                continue
            if name in {"SLOT_TYPES"}:
                continue
            if isinstance(value, (str, int, float, bool, type(None))):
                data[name] = value
            else:
                data[name] = str(value)
        return data

    @staticmethod
    def _save_map_response_message(code: int) -> str:
        return {
            0: "map saved",
            1: "save_map already running",
            2: "image render reset failed",
            3: "map data is empty",
            4: "localization expansion failed",
        }.get(code, f"save_map returned {code}")

    @staticmethod
    def _load_map_response_message(code: int) -> str:
        return {
            0: "map loaded",
            1: "map not found",
            2: "map load failed",
            3: "mode switch failed",
        }.get(code, f"load_map returned {code}")

    @staticmethod
    def _wait_future(future: Any, timeout_sec: float | None) -> Any:
        start = time.monotonic()
        while not future.done():
            if timeout_sec is not None and time.monotonic() - start > timeout_sec:
                return None
            time.sleep(0.02)
        return future.result()

    def _require_ready(self) -> None:
        if not self.ready or self._node is None:
            raise BridgeUnavailable(self.error or "ROS bridge is not ready")

    def _require_type(self, name: str) -> Any:
        self._require_ready()
        if name not in self._types:
            raise BridgeUnavailable(f"ROS type unavailable: {name}")
        return self._types[name]
