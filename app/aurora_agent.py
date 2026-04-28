from __future__ import annotations

import importlib
import sys
import threading
import time
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.config import AppConfig, load_config
from app.core.utils import now_ms


class FsmBody(BaseModel):
    fsm_state: int = Field(description="Aurora FSM state")


class StopMotionBody(BaseModel):
    duration: float = Field(default=1.0, description="Zero velocity command duration")


class AuroraSdkController:
    """Long-lived Aurora SDK owner.

    Run this process in the environment/container where Aurora SDK and its DDS
    message dependencies are valid. The main GR3 adapter calls this process over
    localhost instead of importing Aurora SDK directly.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._lock = threading.RLock()
        self._command_lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client_cls: Any | None = None
        self._client: Any | None = None
        self._import_attempts: list[str] = []
        self._last_fsm_state: int | None = None
        self._state: dict[str, Any] = self._unavailable("Aurora state not polled yet")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll_loop, name="aurora-sdk-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        with self._lock:
            if self._client is not None and hasattr(self._client, "close"):
                try:
                    self._client.close()
                except Exception:
                    pass
            self._client = None

    def health(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
        return {
            "success": True,
            "available": bool(state.get("available")),
            "connected": bool(state.get("connected")),
            "backend": "sdk",
            "domain_id": self.config.aurora_domain_id,
            "robot_name": self.config.aurora_robot_name,
            "fsm_state": state.get("fsm_state"),
            "standing": bool(state.get("standing")),
            "error": state.get("error"),
            "import_attempts": list(self._import_attempts),
            "updated_at_ms": state.get("updated_at_ms"),
        }

    def state(self, force_refresh: bool = False) -> dict[str, Any]:
        if force_refresh:
            return self.refresh_state()
        with self._lock:
            return dict(self._state)

    def set_fsm(self, fsm_state: int) -> dict[str, Any]:
        start = time.monotonic()
        with self._command_lock:
            try:
                client = self._connect()
                if not hasattr(client, "set_fsm_state"):
                    raise RuntimeError("Current AuroraClient does not provide set_fsm_state")
                client.set_fsm_state(int(fsm_state))
                self._last_fsm_state = int(fsm_state)
                state = self.refresh_state()
                return {
                    **state,
                    "success": True,
                    "operation": "set_fsm",
                    "fsm_state": int(fsm_state),
                    "message": "fsm command sent",
                    "elapsed_ms": self._elapsed_ms(start),
                    "state": state,
                }
            except Exception as exc:
                state = self._record_error(str(exc))
                return {
                    **state,
                    "success": False,
                    "operation": "set_fsm",
                    "fsm_state": int(fsm_state),
                    "error": str(exc),
                    "elapsed_ms": self._elapsed_ms(start),
                }

    def ensure_stand(self) -> dict[str, Any]:
        result = self.set_fsm(self.config.aurora_stand_fsm_state)
        result["operation"] = "ensure_stand"
        result["message"] = "stand command sent" if result.get("success") else result.get("error")
        return result

    def stop_motion(self, duration: float = 1.0) -> dict[str, Any]:
        start = time.monotonic()
        with self._command_lock:
            try:
                client = self._connect()
                if hasattr(client, "set_velocity_source"):
                    client.set_velocity_source(2)
                if not hasattr(client, "set_velocity"):
                    raise RuntimeError("Current AuroraClient does not provide set_velocity")
                method = getattr(client, "set_velocity")
                try:
                    method(0.0, 0.0, 0.0, float(duration))
                    args = (0.0, 0.0, 0.0, float(duration))
                except TypeError:
                    method(0.0, 0.0, 0.0)
                    args = (0.0, 0.0, 0.0)
                state = self.state()
                return {
                    **state,
                    "success": True,
                    "operation": "stop_motion",
                    "message": "zero velocity command sent",
                    "duration": duration,
                    "args": args,
                    "elapsed_ms": self._elapsed_ms(start),
                    "state": state,
                }
            except Exception as exc:
                state = self._record_error(str(exc))
                return {
                    **state,
                    "success": False,
                    "operation": "stop_motion",
                    "error": str(exc),
                    "elapsed_ms": self._elapsed_ms(start),
                }

    def refresh_state(self) -> dict[str, Any]:
        try:
            client = self._connect()
            raw = self._get_state_raw(client)
            fsm_state = self._extract_fsm_state(raw)
            if fsm_state is not None:
                self._last_fsm_state = fsm_state
            else:
                fsm_state = self._last_fsm_state
            state = {
                "success": True,
                "available": True,
                "connected": True,
                "backend": "sdk",
                "domain_id": self.config.aurora_domain_id,
                "robot_name": self.config.aurora_robot_name,
                "fsm_state": fsm_state,
                "standing": self._is_standing(raw, fsm_state),
                "raw": raw,
                "import_attempts": list(self._import_attempts),
                "updated_at_ms": now_ms(),
            }
            with self._lock:
                self._state = state
            return dict(state)
        except Exception as exc:
            return self._record_error(str(exc))

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            self.refresh_state()
            self._stop.wait(max(self.config.aurora_poll_interval_sec, 0.2))

    def _connect(self) -> Any:
        with self._lock:
            if self._client is not None:
                return self._client
            if self._client_cls is None:
                self._client_cls = self._import_client()
            self._client = self._create_client(self._client_cls)
            return self._client

    def _import_client(self) -> Any:
        if self.config.aurora_sdk_path and self.config.aurora_sdk_path not in sys.path:
            sys.path.insert(0, self.config.aurora_sdk_path)

        candidates: list[tuple[str, str]] = []
        if self.config.aurora_client_module:
            candidates.append((self.config.aurora_client_module, self.config.aurora_client_class or "AuroraClient"))
        candidates.extend(
            [
                ("fourier_aurora_client", "AuroraClient"),
                ("aurora_sdk", "AuroraClient"),
                ("aurora", "AuroraClient"),
                ("fftai_aurora_sdk", "AuroraClient"),
            ]
        )

        errors: list[str] = []
        self._import_attempts = []
        seen: set[tuple[str, str]] = set()
        for module_name, class_name in candidates:
            key = (module_name, class_name)
            if key in seen:
                continue
            seen.add(key)
            try:
                module = importlib.import_module(module_name)
                client_cls = getattr(module, class_name)
                self._import_attempts.append(f"{module_name}.{class_name}: ok")
                return client_cls
            except Exception as exc:
                message = f"{module_name}.{class_name}: {exc}"
                errors.append(message)
                self._import_attempts.append(message)
        raise RuntimeError("cannot import AuroraClient from candidates: " + "; ".join(errors))

    def _create_client(self, client_cls: Any) -> Any:
        if not hasattr(client_cls, "get_instance"):
            return client_cls()
        try:
            return client_cls.get_instance(
                domain_id=self.config.aurora_domain_id,
                robot_name=self.config.aurora_robot_name,
            )
        except TypeError:
            try:
                return client_cls.get_instance(
                    domain_id=self.config.aurora_domain_id,
                    robot_name=self.config.aurora_robot_name,
                    namespace=None,
                    is_ros_compatible=False,
                )
            except TypeError:
                try:
                    return client_cls.get_instance(self.config.aurora_domain_id, robot_name=self.config.aurora_robot_name)
                except TypeError:
                    return client_cls.get_instance(self.config.aurora_robot_name)

    def _get_state_raw(self, client: Any) -> dict[str, Any]:
        for method_name in ("get_fsm_state", "get_state", "get_robot_state"):
            if not hasattr(client, method_name):
                continue
            method = getattr(client, method_name)
            value = method()
            return {"method": method_name, "value": self._to_jsonable(value)}
        return {"warning": "No known state getter on current AuroraClient object"}

    @classmethod
    def _extract_fsm_state(cls, value: Any) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return None
        if isinstance(value, dict):
            for key in ("fsm_state", "fsm", "state", "state_id", "current_fsm", "value"):
                if key in value:
                    nested = cls._extract_fsm_state(value[key])
                    if nested is not None:
                        return nested
            for nested in value.values():
                found = cls._extract_fsm_state(nested)
                if found is not None:
                    return found
        return None

    def _is_standing(self, raw: Any, fsm_state: int | None) -> bool:
        names = {"PdStand", "JointStand", "PD_STAND", "JOINT_STAND"}
        if isinstance(raw, dict):
            for key in ("fsm_state_name", "state_name", "fsm_name", "name", "value"):
                value = raw.get(key)
                if isinstance(value, str) and value in names:
                    return True
            for value in raw.values():
                if self._is_standing(value, None):
                    return True
        return fsm_state in {1, 2, self.config.aurora_stand_fsm_state}

    @classmethod
    def _to_jsonable(cls, value: Any) -> Any:
        if isinstance(value, (str, int, float, bool, type(None))):
            return value
        if isinstance(value, dict):
            return {str(key): cls._to_jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._to_jsonable(item) for item in value]
        if hasattr(value, "__dict__"):
            return cls._to_jsonable(vars(value))
        return str(value)

    def _record_error(self, message: str) -> dict[str, Any]:
        state = self._unavailable(message)
        state["fsm_state"] = self._last_fsm_state
        state["standing"] = self._is_standing(None, self._last_fsm_state)
        with self._lock:
            self._state = state
        return dict(state)

    def _unavailable(self, message: str) -> dict[str, Any]:
        return {
            "success": False,
            "available": self._client_cls is not None,
            "connected": False,
            "backend": "sdk",
            "domain_id": self.config.aurora_domain_id,
            "robot_name": self.config.aurora_robot_name,
            "fsm_state": self._last_fsm_state,
            "standing": False,
            "error": message,
            "import_attempts": list(self._import_attempts),
            "updated_at_ms": now_ms(),
        }

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        return int((time.monotonic() - start) * 1000)


config = load_config()
controller = AuroraSdkController(config)

app = FastAPI(
    title="GR3 Aurora Agent",
    description="Local Aurora SDK sidecar. Run it only in the Aurora SDK environment.",
    version="0.1.0",
)


@app.on_event("startup")
def on_startup() -> None:
    controller.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    controller.stop()


@app.get("/health", summary="Check Aurora Agent health")
def health() -> dict[str, Any]:
    return controller.health()


@app.get("/state", summary="Get cached Aurora state")
def state(force_refresh: bool = False) -> dict[str, Any]:
    return controller.state(force_refresh=force_refresh)


@app.post("/fsm", summary="Set Aurora FSM")
def set_fsm(body: FsmBody) -> dict[str, Any]:
    return controller.set_fsm(body.fsm_state)


@app.post("/ensure_stand", summary="Ensure standing state")
def ensure_stand() -> dict[str, Any]:
    return controller.ensure_stand()


@app.post("/stop_motion", summary="Send zero velocity command")
def stop_motion(body: StopMotionBody | None = None) -> dict[str, Any]:
    return controller.stop_motion(duration=(body.duration if body else 1.0))
