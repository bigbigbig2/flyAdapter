from __future__ import annotations

from typing import Any

from app.config import AppConfig


class AuroraBridge:
    """Best-effort Aurora SDK wrapper.

    The real robot SDK is usually available only on the GR3 runtime image. This
    bridge keeps the HTTP adapter usable when the SDK is absent, while exposing
    a clear unavailable state to readiness checks.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._client: Any | None = None
        self._error: str | None = None
        self._mock_fsm_state = 2

    def start(self) -> None:
        if self.config.aurora_mock:
            return
        try:
            client_cls = self._import_client()
            if hasattr(client_cls, "get_instance"):
                self._client = client_cls.get_instance(self.config.aurora_robot_name)
            else:
                self._client = client_cls()
        except Exception as exc:  # pragma: no cover - depends on robot SDK
            self._client = None
            self._error = str(exc)

    def ping(self) -> dict[str, Any]:
        state = self.state()
        return {
            "connected": state["connected"],
            "mock": self.config.aurora_mock,
            "error": state.get("error"),
        }

    def state(self) -> dict[str, Any]:
        if self.config.aurora_mock:
            return {
                "connected": True,
                "mock": True,
                "fsm_state": self._mock_fsm_state,
                "standing": self._mock_fsm_state in {1, 2, 3},
            }
        if self._client is None:
            return {
                "connected": False,
                "mock": False,
                "fsm_state": None,
                "standing": False,
                "error": self._error or "Aurora SDK unavailable",
            }
        try:
            fsm_state = self._get_fsm_state()
            return {
                "connected": True,
                "mock": False,
                "fsm_state": fsm_state,
                "standing": fsm_state in {1, 2, 3},
            }
        except Exception as exc:  # pragma: no cover - depends on robot SDK
            return {
                "connected": False,
                "mock": False,
                "fsm_state": None,
                "standing": False,
                "error": str(exc),
            }

    def set_fsm(self, fsm_state: int) -> dict[str, Any]:
        if self.config.aurora_mock:
            self._mock_fsm_state = int(fsm_state)
            return {"success": True, "fsm_state": self._mock_fsm_state, "mock": True}
        if self._client is None:
            return {"success": False, "message": self._error or "Aurora SDK unavailable"}
        try:
            if hasattr(self._client, "set_fsm_state"):
                self._client.set_fsm_state(int(fsm_state))
            elif hasattr(self._client, "SetFsmState"):
                self._client.SetFsmState(int(fsm_state))
            else:
                raise RuntimeError("Aurora client has no set_fsm_state method")
            return {"success": True, "fsm_state": int(fsm_state)}
        except Exception as exc:  # pragma: no cover - depends on robot SDK
            return {"success": False, "message": str(exc)}

    def ensure_stand(self) -> dict[str, Any]:
        state = self.state()
        if state.get("standing"):
            return {"success": True, "message": "already standing", "state": state}
        # PD stand is the safest documented stand-like target in the notes.
        result = self.set_fsm(2)
        result["message"] = "stand command sent" if result.get("success") else result.get("message")
        return result

    def stop_motion(self) -> dict[str, Any]:
        if self.config.aurora_mock:
            return {"success": True, "message": "mock stop_motion"}
        if self._client is None:
            return {"success": False, "message": self._error or "Aurora SDK unavailable"}
        try:
            for method_name in ("stop_motion", "StopMotion", "stop", "Stop"):
                if hasattr(self._client, method_name):
                    getattr(self._client, method_name)()
                    return {"success": True, "message": method_name}
            return {"success": False, "message": "Aurora client has no stop method"}
        except Exception as exc:  # pragma: no cover - depends on robot SDK
            return {"success": False, "message": str(exc)}

    def _get_fsm_state(self) -> int | None:
        if self._client is None:
            return None
        for method_name in ("get_fsm_state", "GetFsmState"):
            if hasattr(self._client, method_name):
                return int(getattr(self._client, method_name)())
        return None

    @staticmethod
    def _import_client() -> Any:
        candidates = [
            ("aurora_sdk", "AuroraClient"),
            ("aurora", "AuroraClient"),
            ("fftai_aurora_sdk", "AuroraClient"),
        ]
        last_error: Exception | None = None
        for module_name, class_name in candidates:
            try:
                module = __import__(module_name, fromlist=[class_name])
                return getattr(module, class_name)
            except Exception as exc:  # pragma: no cover - depends on robot SDK
                last_error = exc
        raise RuntimeError(f"cannot import AuroraClient: {last_error}")
