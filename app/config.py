from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional local convenience
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def normalize_namespace(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    if not value:
        return ""
    return value if value.startswith("/") else f"/{value}"


def normalize_motion_guard(value: str | None) -> str:
    value = (value or "none").strip().lower()
    if value in {"none", "observe", "aurora"}:
        return value
    return "none"


@dataclass(frozen=True)
class AppConfig:
    root_dir: Path
    namespace: str
    data_dir: Path
    map_root: Path
    default_map_name: str
    default_map_path: str
    nav_points_file: Path
    show_cruise_dir: Path
    upload_dir: Path
    motion_guard: str
    require_aurora: bool
    aurora_enabled: bool
    aurora_mock: bool
    aurora_backend: str
    aurora_agent_url: str
    aurora_robot_name: str
    aurora_domain_id: int
    aurora_stand_fsm_state: int
    aurora_sdk_path: str
    aurora_client_module: str
    aurora_client_class: str
    aurora_poll_interval_sec: float
    aurora_state_timeout_sec: float
    aurora_command_timeout_sec: float
    aurora_state_stale_sec: float
    aurora_circuit_failure_threshold: int
    aurora_circuit_open_sec: float
    nav_goal_timeout_sec: float
    map_save_timeout_sec: float

    @property
    def ns(self) -> str:
        return normalize_namespace(self.namespace)

    def ros_name(self, name: str) -> str:
        name = name if name.startswith("/") else f"/{name}"
        if not self.ns:
            return name
        return f"{self.ns}{name}"


def load_config() -> AppConfig:
    root_dir = Path(__file__).resolve().parents[1]
    data_dir = Path(os.getenv("ADAPTER_DATA_DIR", root_dir / "data")).expanduser()
    nav_points_file = Path(
        os.getenv("NAV_POINTS_FILE", data_dir / "navigation_points.json")
    ).expanduser()
    motion_guard = normalize_motion_guard(os.getenv("MOTION_GUARD", "none"))

    map_root = Path(os.getenv("MAP_ROOT", "/opt/fftai/nav")).expanduser()
    default_map_name = os.getenv("DEFAULT_MAP_NAME", "map").strip() or "map"
    default_map_path_raw = os.getenv("DEFAULT_MAP_PATH", "").strip()
    if default_map_path_raw:
        default_map_path_obj = Path(default_map_path_raw).expanduser()
        default_map_path = str(default_map_path_obj if default_map_path_obj.is_absolute() else map_root / default_map_path_obj)
    else:
        default_map_path = str(map_root / default_map_name)

    return AppConfig(
        root_dir=root_dir,
        namespace=os.getenv("ROBOT_NAMESPACE", "GR301AA0025"),
        data_dir=data_dir,
        map_root=map_root,
        default_map_name=default_map_name,
        default_map_path=default_map_path,
        nav_points_file=nav_points_file,
        show_cruise_dir=Path(
            os.getenv("SHOW_CRUISE_DIR", data_dir / "show_cruises")
        ).expanduser(),
        upload_dir=Path(os.getenv("UPLOAD_DIR", data_dir / "uploads")).expanduser(),
        motion_guard=motion_guard,
        require_aurora=_bool_env("REQUIRE_AURORA", False),
        aurora_enabled=_bool_env("AURORA_ENABLED", False) or motion_guard in {"aurora", "observe"},
        aurora_mock=_bool_env("AURORA_MOCK", False),
        aurora_backend=os.getenv("AURORA_BACKEND", "agent").strip().lower(),
        aurora_agent_url=os.getenv("AURORA_AGENT_URL", "http://127.0.0.1:18080").rstrip("/"),
        aurora_robot_name=os.getenv("AURORA_ROBOT_NAME", "gr3v233"),
        aurora_domain_id=int(os.getenv("AURORA_DOMAIN_ID", "123")),
        aurora_stand_fsm_state=int(os.getenv("AURORA_STAND_FSM_STATE", "2")),
        aurora_sdk_path=os.getenv("AURORA_SDK_PATH", ""),
        aurora_client_module=os.getenv("AURORA_CLIENT_MODULE", "fourier_aurora_client"),
        aurora_client_class=os.getenv("AURORA_CLIENT_CLASS", "AuroraClient"),
        aurora_poll_interval_sec=float(os.getenv("AURORA_POLL_INTERVAL_SEC", "1.0")),
        aurora_state_timeout_sec=float(os.getenv("AURORA_STATE_TIMEOUT_SEC", "2.0")),
        aurora_command_timeout_sec=float(os.getenv("AURORA_COMMAND_TIMEOUT_SEC", "3.0")),
        aurora_state_stale_sec=float(os.getenv("AURORA_STATE_STALE_SEC", "5.0")),
        aurora_circuit_failure_threshold=int(os.getenv("AURORA_CIRCUIT_FAILURE_THRESHOLD", "3")),
        aurora_circuit_open_sec=float(os.getenv("AURORA_CIRCUIT_OPEN_SEC", "5.0")),
        nav_goal_timeout_sec=float(os.getenv("NAV_GOAL_TIMEOUT_SEC", "300")),
        map_save_timeout_sec=float(os.getenv("MAP_SAVE_TIMEOUT_SEC", "120")),
    )
