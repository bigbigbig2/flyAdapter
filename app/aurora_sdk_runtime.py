from __future__ import annotations

import importlib
import importlib.util
import sys
import threading
import time
from typing import Any

from app.config import AppConfig
from app.core.utils import now_ms


class AuroraSdkRuntime:
    """Owns the long-lived Aurora SDK client.

    This module is intentionally isolated from the main adapter process. It is
    imported only by the Aurora Agent, which must run in the Python/DDS
    environment where Fourier's Aurora SDK is valid.
    """

    OFFICIAL_STATE_GETTERS = (
        ("get_fsm_state", "fsm_state"),
        ("get_fsm_name", "fsm_name"),
        ("get_velocity_source", "velocity_source"),
        ("get_velocity_source_name", "velocity_source_name"),
    )

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._state_lock = threading.RLock()
        self._connect_lock = threading.Lock()
        self._command_lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client_cls: Any | None = None
        self._client: Any | None = None
        self._import_attempts: list[str] = []
        self._last_fsm_state: int | None = None
        self._last_fsm_name: str | None = None
        self._connect_failure_count = 0
        self._next_connect_attempt_s = 0.0
        self._last_connect_error: str | None = None
        self._state = self._offline_state("Aurora state not polled yet")

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
        self.reset_client()

    def health(self) -> dict[str, Any]:
        with self._state_lock:
            state = dict(self._state)
        return {
            "success": True,
            "available": bool(state.get("available")),
            "connected": bool(state.get("connected")),
            "backend": "sdk",
            "domain_id": self.config.aurora_domain_id,
            "robot_name": self.config.aurora_robot_name,
            "fsm_state": state.get("fsm_state"),
            "fsm_name": state.get("fsm_name"),
            "standing": bool(state.get("standing")),
            "standing_known": bool(state.get("standing_known")),
            "state_known": bool(state.get("state_known")),
            "error": state.get("error"),
            "last_connect_error": state.get("last_connect_error"),
            "connect_retry_after_sec": state.get("connect_retry_after_sec"),
            "connect_failure_count": state.get("connect_failure_count"),
            "import_attempts": list(self._import_attempts),
            "module_diagnostics": self.module_diagnostics(),
            "updated_at_ms": state.get("updated_at_ms"),
        }

    def state(self, force_refresh: bool = False) -> dict[str, Any]:
        if force_refresh:
            return self.refresh_state()
        with self._state_lock:
            return dict(self._state)

    def diagnostics(self) -> dict[str, Any]:
        with self._state_lock:
            retry_after = self._connect_retry_after()
            return {
                "backend": "sdk",
                "domain_id": self.config.aurora_domain_id,
                "robot_name": self.config.aurora_robot_name,
                "client_imported": self._client_cls is not None,
                "client_connected": self._client is not None,
                "connect_failure_count": self._connect_failure_count,
                "last_connect_error": self._last_connect_error,
                "connect_retry_after_sec": retry_after,
                "import_attempts": list(self._import_attempts),
                "module_diagnostics": self.module_diagnostics(),
            }

    def reset_client(self) -> dict[str, Any]:
        with self._connect_lock:
            with self._state_lock:
                client = self._client
                self._client = None
                self._connect_failure_count = 0
                self._next_connect_attempt_s = 0.0
                self._last_connect_error = None
                self._state = self._offline_state("Aurora client reset")
            if client is not None and hasattr(client, "close"):
                try:
                    client.close()
                except Exception:
                    pass
        return {"success": True, "message": "Aurora client reset", "updated_at_ms": now_ms()}

    def set_fsm(self, fsm_state: int) -> dict[str, Any]:
        start = time.monotonic()
        with self._command_lock:
            try:
                client = self._connect()
                setter = self._require_method(client, "set_fsm_state")
                setter(int(fsm_state))
                self._last_fsm_state = int(fsm_state)
                state = self._optimistic_state(
                    fsm_state=int(fsm_state),
                    fsm_name=self._last_fsm_name,
                    operation="set_fsm",
                    message="fsm command sent",
                )
                refreshed = self.refresh_state_if_connected()
                if refreshed.get("connected"):
                    state = refreshed
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
                velocity = self._require_method(client, "set_velocity")
                args = self._send_zero_velocity(velocity, duration)
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

    def refresh_state_if_connected(self) -> dict[str, Any]:
        with self._state_lock:
            connected = self._client is not None
        if not connected:
            return self.state()
        return self.refresh_state()

    def refresh_state(self) -> dict[str, Any]:
        try:
            client = self._connect()
            raw = self._read_official_state(client)
            fsm_state = self._extract_fsm_state(raw)
            fsm_name = self._extract_fsm_name(raw)
            if fsm_state is not None:
                self._last_fsm_state = fsm_state
            else:
                fsm_state = self._last_fsm_state
            if fsm_name:
                self._last_fsm_name = fsm_name
            else:
                fsm_name = self._last_fsm_name
            state_known = any(item.endswith(":ok") for item in raw.get("checked_methods", []))
            standing_known = state_known or fsm_state is not None or bool(fsm_name)
            state = {
                "success": True,
                "available": True,
                "connected": True,
                "backend": "sdk",
                "domain_id": self.config.aurora_domain_id,
                "robot_name": self.config.aurora_robot_name,
                "fsm_state": fsm_state,
                "fsm_name": fsm_name,
                "standing": self._is_standing(fsm_state, fsm_name) if standing_known else False,
                "standing_known": standing_known,
                "state_known": state_known,
                "state_getter": "official_getters" if state_known else None,
                "raw": raw,
                "import_attempts": list(self._import_attempts),
                "module_diagnostics": self.module_diagnostics(),
                "updated_at_ms": now_ms(),
            }
            with self._state_lock:
                self._state = state
            return dict(state)
        except Exception as exc:
            return self._record_error(str(exc))

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            self.refresh_state()
            self._stop.wait(max(self.config.aurora_poll_interval_sec, 0.2))

    def _connect(self) -> Any:
        with self._state_lock:
            if self._client is not None:
                return self._client

        with self._connect_lock:
            with self._state_lock:
                if self._client is not None:
                    return self._client
                retry_after = self._next_connect_attempt_s - time.monotonic()
                if retry_after > 0:
                    raise RuntimeError(
                        "AuroraClient initialization backoff "
                        f"({retry_after:.1f}s remaining): {self._last_connect_error}"
                    )
                client_cls = self._client_cls

            if client_cls is None:
                client_cls = self._import_client()
                with self._state_lock:
                    self._client_cls = client_cls

            try:
                client = self._create_client(client_cls)
            except Exception as exc:
                self._record_connect_failure(str(exc))
                raise

            with self._state_lock:
                self._client = client
                self._connect_failure_count = 0
                self._next_connect_attempt_s = 0.0
                self._last_connect_error = None
                return client

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
        diagnostics = self.module_diagnostics()
        aurora_cmd = diagnostics.get("fourier_msgs.msg.AuroraCmd", {})
        if not aurora_cmd.get("found"):
            self._import_attempts.append(
                "fourier_msgs.msg.AuroraCmd: missing; "
                f"fourier_msgs={diagnostics.get('fourier_msgs', {}).get('origin')}; "
                "hint=run Aurora Agent outside HumanoidNav overlay or set AURORA_SETUP_SCRIPT to Aurora SDK setup"
            )

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
                namespace=None,
                is_ros_compatible=False,
            )
        except TypeError:
            return client_cls.get_instance(
                domain_id=self.config.aurora_domain_id,
                robot_name=self.config.aurora_robot_name,
            )

    def _read_official_state(self, client: Any) -> dict[str, Any]:
        value: dict[str, Any] = {}
        checked: list[str] = []
        for method_name, key in self.OFFICIAL_STATE_GETTERS:
            result = self._call_optional_zero_arg(client, method_name)
            checked.append(result["checked"])
            if result["ok"]:
                value[key] = result["value"]
        raw: dict[str, Any] = {
            "method": "official_getters",
            "value": value,
            "checked_methods": checked,
        }
        if not value:
            raw["warning"] = "No official Aurora state getter succeeded"
            raw["sdk_capabilities"] = self._sdk_capabilities(client)
        return raw

    def _call_optional_zero_arg(self, client: Any, method_name: str) -> dict[str, Any]:
        if not hasattr(client, method_name):
            return {"ok": False, "checked": f"{method_name}:missing"}
        method = getattr(client, method_name)
        if not callable(method):
            return {"ok": False, "checked": f"{method_name}:not_callable"}
        try:
            return {"ok": True, "checked": f"{method_name}:ok", "value": self._to_jsonable(method())}
        except Exception as exc:
            return {"ok": False, "checked": f"{method_name}:error:{exc}"}

    @staticmethod
    def _require_method(client: Any, method_name: str) -> Any:
        if not hasattr(client, method_name):
            raise RuntimeError(f"Current AuroraClient does not provide {method_name}")
        method = getattr(client, method_name)
        if not callable(method):
            raise RuntimeError(f"Current AuroraClient attribute is not callable: {method_name}")
        return method

    @staticmethod
    def _send_zero_velocity(method: Any, duration: float) -> tuple[float, ...]:
        try:
            method(0.0, 0.0, 0.0, float(duration))
            return (0.0, 0.0, 0.0, float(duration))
        except TypeError:
            method(0.0, 0.0, 0.0)
            return (0.0, 0.0, 0.0)

    def _optimistic_state(
        self,
        fsm_state: int | None,
        fsm_name: str | None,
        operation: str,
        message: str,
    ) -> dict[str, Any]:
        standing_known = fsm_state is not None or bool(fsm_name)
        state = {
            "success": True,
            "available": True,
            "connected": True,
            "backend": "sdk",
            "domain_id": self.config.aurora_domain_id,
            "robot_name": self.config.aurora_robot_name,
            "fsm_state": fsm_state,
            "fsm_name": fsm_name,
            "standing": self._is_standing(fsm_state, fsm_name) if standing_known else False,
            "standing_known": standing_known,
            "state_known": False,
            "state_getter": None,
            "operation": operation,
            "message": message,
            "import_attempts": list(self._import_attempts),
            "module_diagnostics": self.module_diagnostics(),
            "updated_at_ms": now_ms(),
        }
        with self._state_lock:
            self._state = state
        return dict(state)

    def _record_connect_failure(self, message: str) -> None:
        with self._state_lock:
            self._client = None
            self._connect_failure_count += 1
            delay = min(5.0 * (2 ** min(self._connect_failure_count - 1, 3)), 30.0)
            self._next_connect_attempt_s = time.monotonic() + delay
            self._last_connect_error = message

    def _record_error(self, message: str) -> dict[str, Any]:
        state = self._offline_state(message)
        retry_after = self._connect_retry_after()
        if retry_after is not None:
            state["connect_retry_after_sec"] = retry_after
        if self._last_connect_error:
            state["last_connect_error"] = self._last_connect_error
        with self._state_lock:
            self._state = state
        return dict(state)

    def _offline_state(self, message: str) -> dict[str, Any]:
        fsm_state = self._last_fsm_state
        fsm_name = self._last_fsm_name
        standing_known = fsm_state is not None or bool(fsm_name)
        return {
            "success": False,
            "available": self._client_cls is not None,
            "connected": False,
            "backend": "sdk",
            "domain_id": self.config.aurora_domain_id,
            "robot_name": self.config.aurora_robot_name,
            "fsm_state": fsm_state,
            "fsm_name": fsm_name,
            "standing": self._is_standing(fsm_state, fsm_name) if standing_known else False,
            "standing_known": standing_known,
            "state_known": False,
            "state_getter": None,
            "error": message,
            "connect_failure_count": self._connect_failure_count,
            "last_connect_error": self._last_connect_error,
            "import_attempts": list(self._import_attempts),
            "module_diagnostics": self.module_diagnostics(),
            "updated_at_ms": now_ms(),
        }

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
            for key in ("fsm_state", "fsm", "state", "state_id", "current_fsm"):
                if key in value:
                    nested = cls._extract_fsm_state(value[key])
                    if nested is not None:
                        return nested
            for nested in value.values():
                found = cls._extract_fsm_state(nested)
                if found is not None:
                    return found
        return None

    @classmethod
    def _extract_fsm_name(cls, value: Any) -> str | None:
        if isinstance(value, dict):
            for key in ("fsm_name", "fsm_state_name", "state_name", "name"):
                item = value.get(key)
                if isinstance(item, str) and item:
                    return item
            for nested in value.values():
                found = cls._extract_fsm_name(nested)
                if found:
                    return found
        if isinstance(value, (list, tuple, set)):
            for nested in value:
                found = cls._extract_fsm_name(nested)
                if found:
                    return found
        return None

    def _is_standing(self, fsm_state: int | None, fsm_name: str | None) -> bool:
        if fsm_name:
            normalized = fsm_name.replace("_", "").replace("-", "").replace(" ", "").lower()
            if normalized in {"pdstand", "jointstand", "pdstanding", "jointstanding", "stand", "standing"}:
                return True
            if normalized.endswith("stand"):
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

    @staticmethod
    def _sdk_capabilities(client: Any) -> list[str]:
        keywords = ("fsm", "state", "status", "robot", "velocity", "motion", "stand")
        names: list[str] = []
        for name in dir(client):
            if name.startswith("_"):
                continue
            lowered = name.lower()
            if not any(keyword in lowered for keyword in keywords):
                continue
            try:
                value = getattr(client, name)
            except Exception:
                continue
            if callable(value):
                names.append(name)
        return sorted(names)[:80]

    def _connect_retry_after(self) -> float | None:
        retry_after = self._next_connect_attempt_s - time.monotonic()
        if retry_after <= 0:
            return None
        return round(retry_after, 3)

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        return int((time.monotonic() - start) * 1000)

    @staticmethod
    def module_diagnostics() -> dict[str, Any]:
        diagnostics: dict[str, Any] = {}
        for name in ("fourier_msgs", "fourier_msgs.msg", "fourier_msgs.msg.AuroraCmd"):
            try:
                spec = importlib.util.find_spec(name)
                diagnostics[name] = {
                    "found": spec is not None,
                    "origin": None if spec is None else str(spec.origin or spec.submodule_search_locations),
                }
            except Exception as exc:
                diagnostics[name] = {"found": False, "error": str(exc)}
        diagnostics["sys_path_head"] = list(sys.path[:12])
        return diagnostics
