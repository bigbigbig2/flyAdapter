from __future__ import annotations

import importlib
import sys
import threading
from typing import Any

from app.config import AppConfig


class AuroraBridge:
    """Thin Aurora SDK wrapper.

    This follows the verified adapter under D:\\shu\\2: the adapter process is
    expected to run in a Python environment that can import fourier_aurora_client
    directly. AuroraClient is created lazily and reused in-process.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._client: Any | None = None
        self._client_cls: Any | None = None
        self._error: str | None = None
        self._import_attempts: list[str] = []
        self._lock = threading.RLock()
        self._mock_fsm_state = config.aurora_stand_fsm_state
        self._last_fsm_state: int | None = None

    @property
    def available(self) -> bool:
        if not self.config.aurora_enabled:
            return False
        if self.config.aurora_mock:
            return True
        if self._client_cls is not None:
            return True
        try:
            self._client_cls = self._import_client()
            self._error = None
            return True
        except Exception as exc:  # pragma: no cover - depends on robot SDK
            self._error = str(exc)
            return False

    def start(self) -> None:
        if self.config.aurora_mock or not self.config.aurora_enabled:
            return
        try:
            self._client_cls = self._import_client()
            self._error = None
        except Exception as exc:  # pragma: no cover - depends on robot SDK
            self._client_cls = None
            self._error = str(exc)

    def stop(self) -> None:
        with self._lock:
            if self._client is not None and hasattr(self._client, "close"):
                try:
                    self._client.close()
                except Exception:
                    pass
            self._client = None

    def ping(self) -> dict[str, Any]:
        if self.config.aurora_mock:
            return {
                "available": True,
                "connected": True,
                "mock": True,
                "backend": "mock",
                "domain_id": self.config.aurora_domain_id,
                "robot_name": self.config.aurora_robot_name,
            }
        if not self.config.aurora_enabled:
            return {
                "available": False,
                "connected": False,
                "mock": False,
                "backend": "python-sdk",
                "error": "Aurora is disabled",
            }
        try:
            client = self._connect()
            return {
                "available": True,
                "connected": client is not None,
                "mock": False,
                "backend": "python-sdk",
                "domain_id": self.config.aurora_domain_id,
                "robot_name": self.config.aurora_robot_name,
                "import_attempts": self._import_attempts,
            }
        except Exception as exc:  # pragma: no cover - depends on robot SDK
            self._error = str(exc)
            return {
                "available": self._client_cls is not None,
                "connected": False,
                "mock": False,
                "backend": "python-sdk",
                "error": str(exc),
                "domain_id": self.config.aurora_domain_id,
                "robot_name": self.config.aurora_robot_name,
                "import_attempts": self._import_attempts,
            }

    def state(self, force_refresh: bool = False) -> dict[str, Any]:
        if self.config.aurora_mock:
            return {
                "available": True,
                "connected": True,
                "mock": True,
                "backend": "mock",
                "fsm_state": self._mock_fsm_state,
                "standing": self._is_standing(None, self._mock_fsm_state),
            }
        if not self.config.aurora_enabled:
            return {
                "available": False,
                "connected": False,
                "mock": False,
                "backend": "python-sdk",
                "fsm_state": None,
                "standing": False,
                "error": "Aurora is disabled",
            }
        try:
            client = self._connect()
            raw = self._get_state_raw(client)
            fsm_state = self._extract_fsm_state(raw)
            if fsm_state is None:
                fsm_state = self._last_fsm_state
            return {
                "available": True,
                "connected": True,
                "mock": False,
                "backend": "python-sdk",
                "fsm_state": fsm_state,
                "standing": self._is_standing(raw, fsm_state),
                "raw": raw,
                "domain_id": self.config.aurora_domain_id,
                "robot_name": self.config.aurora_robot_name,
                "import_attempts": self._import_attempts,
            }
        except Exception as exc:  # pragma: no cover - depends on robot SDK
            self._error = str(exc)
            return {
                "available": self._client_cls is not None,
                "connected": False,
                "mock": False,
                "backend": "python-sdk",
                "fsm_state": self._last_fsm_state,
                "standing": self._is_standing(None, self._last_fsm_state),
                "error": str(exc),
                "sdk_path": self.config.aurora_sdk_path or None,
                "import_attempts": self._import_attempts,
            }

    def set_fsm(self, fsm_state: int) -> dict[str, Any]:
        state = int(fsm_state)
        if self.config.aurora_mock:
            self._mock_fsm_state = state
            return {"success": True, "fsm_state": state, "mock": True}
        try:
            client = self._connect()
            if not hasattr(client, "set_fsm_state"):
                raise RuntimeError("Current AuroraClient does not provide set_fsm_state")
            client.set_fsm_state(state)
            self._last_fsm_state = state
            return {"success": True, "fsm_state": state, "backend": "python-sdk"}
        except Exception as exc:  # pragma: no cover - depends on robot SDK
            self._error = str(exc)
            return {"success": False, "message": str(exc), "backend": "python-sdk"}

    def ensure_stand(self) -> dict[str, Any]:
        result = self.set_fsm(self.config.aurora_stand_fsm_state)
        result["message"] = "stand command sent" if result.get("success") else result.get("message")
        return result

    def stop_motion(self, duration: float = 1.0) -> dict[str, Any]:
        if self.config.aurora_mock:
            return {"success": True, "message": "mock stop_motion"}
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
            return {"success": True, "message": "zero velocity command sent", "duration": duration, "args": args}
        except Exception as exc:  # pragma: no cover - depends on robot SDK
            self._error = str(exc)
            return {"success": False, "message": str(exc), "backend": "python-sdk"}

    def _connect(self) -> Any:
        with self._lock:
            if self._client is not None:
                return self._client
            if self._client_cls is None:
                self._client_cls = self._import_client()
            self._client = self._create_client(self._client_cls)
            self._error = None
            return self._client

    def _import_client(self) -> Any:
        if self.config.aurora_sdk_path and self.config.aurora_sdk_path not in sys.path:
            sys.path.insert(0, self.config.aurora_sdk_path)

        candidates = []
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
            except Exception as exc:  # pragma: no cover - depends on robot SDK
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
            try:
                value = getattr(client, method_name)()
                return {"available": True, "method": method_name, "raw": value}
            except Exception as exc:
                return {"available": True, "method": method_name, "error": str(exc)}
        return {"available": True, "warning": "No known state getter on current AuroraClient object"}

    @staticmethod
    def _extract_fsm_state(raw: Any) -> int | None:
        if isinstance(raw, dict):
            for key in ("fsm_state", "state"):
                value = raw.get(key)
                if isinstance(value, int):
                    return value
            nested = raw.get("raw")
            if nested is not raw:
                return AuroraBridge._extract_fsm_state(nested)
        for key in ("fsm_state", "state"):
            if hasattr(raw, key):
                value = getattr(raw, key)
                if isinstance(value, int):
                    return value
        if isinstance(raw, int):
            return raw
        return None

    def _is_standing(self, raw: Any, fsm_state: int | None) -> bool:
        state_names = {"PdStand", "JointStand", "PD_STAND", "JOINT_STAND"}
        if isinstance(raw, dict):
            for key in ("fsm_state_name", "state_name", "fsm_name"):
                value = raw.get(key)
                if isinstance(value, str):
                    return value in state_names
            nested = raw.get("raw")
            if nested is not raw and nested is not None:
                return self._is_standing(nested, fsm_state)
        for key in ("fsm_state_name", "state_name", "fsm_name"):
            if hasattr(raw, key):
                value = getattr(raw, key)
                if isinstance(value, str):
                    return value in state_names
        return fsm_state in {1, 2, 3, self.config.aurora_stand_fsm_state}
