from __future__ import annotations

import json
import subprocess
import sys
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
        self._import_attempts: list[str] = []
        self._backend = config.aurora_backend or "docker"
        self._mock_fsm_state = 2

    def start(self) -> None:
        if self.config.aurora_mock:
            return
        if self._backend in {"docker", "container"}:
            self._client = None
            self._error = None
            return
        try:
            if self.config.aurora_sdk_path and self.config.aurora_sdk_path not in sys.path:
                sys.path.insert(0, self.config.aurora_sdk_path)
            client_cls = self._import_client()
            self._client = self._create_client(client_cls)
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
                "backend": "mock",
                "fsm_state": self._mock_fsm_state,
                "standing": self._mock_fsm_state in {1, 2, 3},
            }
        if self._backend in {"docker", "container"}:
            result = self._docker_call("get_fsm")
            if result.get("success"):
                fsm_state = self._as_int(result.get("fsm_state"))
                return {
                    "connected": True,
                    "mock": False,
                    "backend": "docker",
                    "container": self.config.aurora_container_name,
                    "fsm_state": fsm_state,
                    "standing": fsm_state in {1, 2, 3},
                    "raw": result,
                }
            return {
                "connected": False,
                "mock": False,
                "backend": "docker",
                "container": self.config.aurora_container_name,
                "fsm_state": None,
                "standing": False,
                "error": result.get("error") or "Aurora docker backend unavailable",
                "raw": result,
            }
        if self._client is None:
            return {
                "connected": False,
                "mock": False,
                "backend": "python-sdk",
                "fsm_state": None,
                "standing": False,
                "error": self._error or "Aurora SDK unavailable",
                "sdk_path": self.config.aurora_sdk_path or None,
                "import_attempts": self._import_attempts,
            }
        try:
            fsm_state = self._get_fsm_state()
            return {
                "connected": True,
                "mock": False,
                "backend": "python-sdk",
                "fsm_state": fsm_state,
                "standing": fsm_state in {1, 2, 3},
            }
        except Exception as exc:  # pragma: no cover - depends on robot SDK
            return {
                "connected": False,
                "mock": False,
                "backend": "python-sdk",
                "fsm_state": None,
                "standing": False,
                "error": str(exc),
                "sdk_path": self.config.aurora_sdk_path or None,
                "import_attempts": self._import_attempts,
            }

    def set_fsm(self, fsm_state: int) -> dict[str, Any]:
        if self.config.aurora_mock:
            self._mock_fsm_state = int(fsm_state)
            return {"success": True, "fsm_state": self._mock_fsm_state, "mock": True}
        if self._backend in {"docker", "container"}:
            result = self._docker_call("set_fsm", str(int(fsm_state)))
            if result.get("success"):
                return {"success": True, "fsm_state": int(fsm_state), "backend": "docker", "raw": result}
            return {"success": False, "message": result.get("error") or "set_fsm failed", "backend": "docker", "raw": result}
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
        if self._backend in {"docker", "container"}:
            result = self._docker_call("stop_motion")
            if result.get("success"):
                return {"success": True, "message": result.get("message", "stop_motion"), "backend": "docker", "raw": result}
            return {"success": False, "message": result.get("error") or "stop_motion failed", "backend": "docker", "raw": result}
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

    def _import_client(self) -> Any:
        candidates = [
            ("fourier_aurora_client", "AuroraClient"),
            ("aurora_sdk", "AuroraClient"),
            ("aurora", "AuroraClient"),
            ("fftai_aurora_sdk", "AuroraClient"),
        ]
        if self.config.aurora_client_module:
            candidates.insert(
                0,
                (self.config.aurora_client_module, self.config.aurora_client_class or "AuroraClient"),
            )

        errors: list[str] = []
        for module_name, class_name in candidates:
            try:
                module = __import__(module_name, fromlist=[class_name])
                self._import_attempts.append(f"{module_name}.{class_name}: ok")
                return getattr(module, class_name)
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
                namespace=None,
                is_ros_compatible=False,
            )
        except TypeError:
            try:
                return client_cls.get_instance(self.config.aurora_domain_id, robot_name=self.config.aurora_robot_name)
            except TypeError:
                return client_cls.get_instance(self.config.aurora_robot_name)

    def _docker_call(self, operation: str, value: str = "") -> dict[str, Any]:
        script = self._container_script()
        command = [
            "docker",
            "exec",
            "-w",
            self.config.aurora_container_workdir,
            self.config.aurora_container_name,
            self.config.aurora_container_python,
            "-c",
            script,
            self.config.aurora_robot_name,
            str(self.config.aurora_domain_id),
            operation,
            value,
            self.config.aurora_client_module,
            self.config.aurora_client_class or "AuroraClient",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                check=False,
                text=True,
                timeout=self.config.aurora_docker_timeout_sec,
            )
        except FileNotFoundError:
            return {"success": False, "error": "docker command not found"}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"docker exec timeout after {self.config.aurora_docker_timeout_sec}s"}
        except Exception as exc:  # pragma: no cover - depends on host docker setup
            return {"success": False, "error": str(exc)}

        parsed = self._parse_json_line(completed.stdout)
        if parsed is not None:
            parsed["returncode"] = completed.returncode
            if completed.stderr.strip():
                parsed["stderr"] = completed.stderr.strip()
            return parsed
        return {
            "success": False,
            "returncode": completed.returncode,
            "error": completed.stderr.strip() or completed.stdout.strip() or "docker exec returned no JSON",
            "stdout": completed.stdout.strip(),
        }

    @staticmethod
    def _parse_json_line(output: str) -> dict[str, Any] | None:
        for line in reversed(output.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
        return None

    @staticmethod
    def _as_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _container_script() -> str:
        return r'''
import importlib
import json
import sys
import traceback

robot_name = sys.argv[1]
domain_id = int(sys.argv[2])
operation = sys.argv[3]
value = sys.argv[4] if len(sys.argv) > 4 else ""
module_override = sys.argv[5] if len(sys.argv) > 5 else ""
class_name = sys.argv[6] if len(sys.argv) > 6 and sys.argv[6] else "AuroraClient"

def emit(payload):
    print(json.dumps(payload, ensure_ascii=False))

def call_first(obj, names, *args):
    tried = []
    for name in names:
        tried.append(name)
        method = getattr(obj, name, None)
        if method is None:
            continue
        return method(*args), name
    raise RuntimeError("no supported method, tried: " + ",".join(tried))

candidates = []
if module_override:
    candidates.append((module_override, class_name))
candidates.extend([
    ("fourier_aurora_client", "AuroraClient"),
    ("aurora_sdk", "AuroraClient"),
    ("aurora", "AuroraClient"),
    ("fftai_aurora_sdk", "AuroraClient"),
])

attempts = []
try:
    client_cls = None
    for module_name, cls_name in candidates:
        try:
            module = importlib.import_module(module_name)
            client_cls = getattr(module, cls_name)
            attempts.append(f"{module_name}.{cls_name}: ok")
            break
        except Exception as exc:
            attempts.append(f"{module_name}.{cls_name}: {exc}")
    if client_cls is None:
        raise RuntimeError("cannot import AuroraClient from candidates: " + "; ".join(attempts))

    if hasattr(client_cls, "get_instance"):
        try:
            client = client_cls.get_instance(domain_id=domain_id, robot_name=robot_name, namespace=None, is_ros_compatible=False)
        except TypeError:
            try:
                client = client_cls.get_instance(domain_id, robot_name=robot_name)
            except TypeError:
                client = client_cls.get_instance(robot_name)
    else:
        client = client_cls()

    if operation == "get_fsm":
        result, method = call_first(client, ["get_fsm_state", "GetFsmState", "getFsmState", "get_fsm"])
        emit({"success": True, "operation": operation, "fsm_state": result, "method": method, "import_attempts": attempts})
    elif operation == "set_fsm":
        result, method = call_first(client, ["set_fsm_state", "SetFsmState", "setFsmState", "set_fsm"], int(value))
        emit({"success": True, "operation": operation, "fsm_state": int(value), "method": method, "result": str(result), "import_attempts": attempts})
    elif operation == "stop_motion":
        result, method = call_first(client, ["stop_motion", "StopMotion", "stop", "Stop"])
        emit({"success": True, "operation": operation, "method": method, "message": str(result), "import_attempts": attempts})
    else:
        raise RuntimeError("unknown operation: " + operation)
except Exception as exc:
    emit({"success": False, "operation": operation, "error": str(exc), "traceback": traceback.format_exc(), "import_attempts": attempts})
'''
