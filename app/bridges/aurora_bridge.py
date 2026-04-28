from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from app.config import AppConfig
from app.core.utils import now_ms


class AuroraBridge:
    """Adapter-side Aurora facade.

    The main adapter process never imports Aurora SDK. It talks to a local
    Aurora Agent process and keeps a short-lived state cache for status and
    readiness endpoints.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._lock = threading.RLock()
        self._command_lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._mock_fsm_state = config.aurora_stand_fsm_state
        self._last_refresh_s: float | None = None
        self._last_success_s: float | None = None
        self._failure_count = 0
        self._circuit_until_s = 0.0
        self._state: dict[str, Any] = self._initial_state()

    @property
    def backend(self) -> str:
        if not self.config.aurora_enabled:
            return "disabled"
        if self.config.aurora_mock:
            return "mock"
        return self.config.aurora_backend or "agent"

    def start(self) -> None:
        if self.backend in {"disabled", "mock"}:
            with self._lock:
                self._state = self._current_non_agent_state()
            return
        if self.backend != "agent":
            with self._lock:
                self._state = self._unavailable_state(f"unsupported Aurora backend: {self.backend}")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll_loop, name="aurora-agent-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def ping(self) -> dict[str, Any]:
        if self.backend in {"disabled", "mock"}:
            return self._current_non_agent_state()
        if self.backend != "agent":
            return self._unavailable_state(f"unsupported Aurora backend: {self.backend}")
        if self._circuit_is_open():
            return self._circuit_open_response("ping")
        try:
            payload = self._request_json("GET", "/health", None, self.config.aurora_state_timeout_sec)
            self._record_success()
            return self._normalize_agent_payload(payload, operation="ping")
        except Exception as exc:
            self._record_failure(str(exc))
            return self._unavailable_state(str(exc), operation="ping")

    def state(self, force_refresh: bool = False) -> dict[str, Any]:
        if self.backend in {"disabled", "mock"}:
            with self._lock:
                self._state = self._current_non_agent_state()
            return dict(self._state)
        if force_refresh and self.backend == "agent":
            self._refresh_state()
        with self._lock:
            state = dict(self._state)
            last_success_s = self._last_success_s

        now = time.monotonic()
        if self._last_refresh_s is not None:
            state["cache_age_sec"] = round(now - self._last_refresh_s, 3)
        if last_success_s is not None:
            state["last_success_age_sec"] = round(now - last_success_s, 3)
            if now - last_success_s > self.config.aurora_state_stale_sec:
                state["connected"] = False
                state["standing"] = False
                state["stale"] = True
                state["error"] = "Aurora state cache stale"
        else:
            state["stale"] = True
        return state

    def set_fsm(self, fsm_state: int) -> dict[str, Any]:
        if self.backend == "mock":
            self._mock_fsm_state = int(fsm_state)
            with self._lock:
                self._state = self._current_non_agent_state()
            return {"success": True, "fsm_state": int(fsm_state), "backend": "mock"}
        return self._command("fsm", {"fsm_state": int(fsm_state)})

    def ensure_stand(self) -> dict[str, Any]:
        if self.backend == "mock":
            self._mock_fsm_state = self.config.aurora_stand_fsm_state
            with self._lock:
                self._state = self._current_non_agent_state()
            return {"success": True, "fsm_state": self._mock_fsm_state, "backend": "mock", "message": "mock stand command sent"}
        return self._command("ensure_stand", {})

    def stop_motion(self, duration: float = 1.0) -> dict[str, Any]:
        if self.backend == "mock":
            return {"success": True, "message": "mock stop_motion", "backend": "mock"}
        return self._command("stop_motion", {"duration": float(duration)})

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            self._refresh_state()
            self._stop.wait(max(self.config.aurora_poll_interval_sec, 0.1))

    def _refresh_state(self) -> dict[str, Any]:
        if self.backend != "agent":
            state = self._current_non_agent_state()
            with self._lock:
                self._state = state
            return state
        try:
            payload = self._request_json("GET", "/state", None, self.config.aurora_state_timeout_sec)
            state = self._normalize_agent_payload(payload, operation="state")
            self._record_success()
            with self._lock:
                self._state = state
                self._last_refresh_s = time.monotonic()
            return state
        except Exception as exc:
            message = str(exc)
            self._record_failure(message)
            with self._lock:
                state = dict(self._state)
                state["agent_reachable"] = False
                state["last_error"] = message
                if self._last_success_s is None:
                    state.update(self._unavailable_state(message, operation="state"))
                self._state = state
                self._last_refresh_s = time.monotonic()
                return dict(self._state)

    def _command(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.config.aurora_enabled:
            return self._unavailable_state("Aurora is disabled", operation=operation, success=False)
        if self.backend != "agent":
            return self._unavailable_state(f"unsupported Aurora backend: {self.backend}", operation=operation, success=False)
        if self._circuit_is_open():
            return self._circuit_open_response(operation)
        with self._command_lock:
            try:
                result = self._request_json(
                    "POST",
                    f"/{operation}",
                    payload,
                    self.config.aurora_command_timeout_sec,
                )
                self._record_success()
                if isinstance(result, dict):
                    state_candidate = result.get("state") if isinstance(result.get("state"), dict) else result
                    if any(key in state_candidate for key in ("fsm_state", "standing", "connected")):
                        with self._lock:
                            self._state = self._normalize_agent_payload(state_candidate, operation=operation)
                            self._last_success_s = time.monotonic()
                return self._normalize_agent_payload(result, operation=operation, success_default=True)
            except Exception as exc:
                message = str(exc)
                self._record_failure(message)
                return self._unavailable_state(message, operation=operation, success=False)

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        timeout: float,
    ) -> dict[str, Any]:
        url = self.config.aurora_agent_url.rstrip("/") + path
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=max(timeout, 0.1)) as resp:
                text = resp.read().decode("utf-8")
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Aurora agent HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Aurora agent unavailable: {exc.reason}") from exc
        except TimeoutError as exc:
            raise RuntimeError("Aurora agent request timeout") from exc

    def _normalize_agent_payload(
        self,
        payload: dict[str, Any],
        operation: str,
        success_default: bool | None = None,
    ) -> dict[str, Any]:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        success = data.get("success", success_default)
        fsm_state = data.get("fsm_state")
        standing = bool(data.get("standing", False))
        connected = bool(data.get("connected", data.get("available", False)))
        normalized = {
            "success": success,
            "available": bool(data.get("available", connected)),
            "connected": connected,
            "mock": False,
            "backend": "agent",
            "agent_url": self.config.aurora_agent_url,
            "agent_reachable": True,
            "fsm_state": fsm_state,
            "standing": standing,
            "operation": data.get("operation", operation),
            "updated_at_ms": data.get("updated_at_ms", now_ms()),
            "raw": data.get("raw"),
            "error": data.get("error"),
            "message": data.get("message"),
        }
        for key in ("domain_id", "robot_name", "elapsed_ms", "args", "duration", "state"):
            if key in data:
                normalized[key] = data[key]
        return {key: value for key, value in normalized.items() if value is not None}

    def _record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            self._circuit_until_s = 0.0
            self._last_success_s = time.monotonic()

    def _record_failure(self, message: str) -> None:
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= max(self.config.aurora_circuit_failure_threshold, 1):
                self._circuit_until_s = time.monotonic() + max(self.config.aurora_circuit_open_sec, 0.1)

    def _circuit_is_open(self) -> bool:
        with self._lock:
            return time.monotonic() < self._circuit_until_s

    def _circuit_open_response(self, operation: str) -> dict[str, Any]:
        with self._lock:
            retry_after = max(self._circuit_until_s - time.monotonic(), 0.0)
        return {
            "success": False,
            "available": False,
            "connected": False,
            "mock": False,
            "backend": "agent",
            "agent_url": self.config.aurora_agent_url,
            "operation": operation,
            "error": "Aurora agent circuit is open",
            "retry_after_sec": round(retry_after, 3),
        }

    def _current_non_agent_state(self) -> dict[str, Any]:
        if not self.config.aurora_enabled or self.backend == "disabled":
            return {
                "available": False,
                "connected": False,
                "mock": False,
                "backend": "disabled",
                "fsm_state": None,
                "standing": False,
                "error": "Aurora is disabled",
            }
        if self.config.aurora_mock:
            return {
                "available": True,
                "connected": True,
                "mock": True,
                "backend": "mock",
                "fsm_state": self._mock_fsm_state,
                "standing": self._mock_fsm_state in {1, 2, self.config.aurora_stand_fsm_state},
                "updated_at_ms": now_ms(),
            }
        return self._unavailable_state(f"unsupported Aurora backend: {self.backend}")

    def _initial_state(self) -> dict[str, Any]:
        if self.config.aurora_mock or not self.config.aurora_enabled:
            return self._current_non_agent_state()
        return {
            "available": False,
            "connected": False,
            "mock": False,
            "backend": self.backend,
            "agent_url": self.config.aurora_agent_url,
            "agent_reachable": False,
            "fsm_state": None,
            "standing": False,
            "stale": True,
            "error": "Aurora agent state not received yet",
        }

    def _unavailable_state(
        self,
        message: str,
        operation: str = "state",
        success: bool | None = None,
    ) -> dict[str, Any]:
        return {
            "success": success,
            "available": False,
            "connected": False,
            "mock": False,
            "backend": self.backend,
            "agent_url": self.config.aurora_agent_url,
            "agent_reachable": False,
            "fsm_state": None,
            "standing": False,
            "operation": operation,
            "error": message,
        }
