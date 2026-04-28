from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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


@dataclass(frozen=True)
class AppConfig:
    root_dir: Path
    namespace: str
    data_dir: Path
    map_root: Path
    default_map_path: str
    nav_points_file: Path
    show_cruise_dir: Path
    upload_dir: Path
    require_aurora: bool
    aurora_mock: bool
    aurora_robot_name: str
    aurora_domain_id: int
    aurora_backend: str
    aurora_container_name: str
    aurora_container_workdir: str
    aurora_container_python: str
    aurora_docker_timeout_sec: float
    aurora_state_cache_ttl_sec: float
    aurora_state_stale_ttl_sec: float
    aurora_docker_lock_timeout_sec: float
    aurora_sdk_path: str
    aurora_client_module: str
    aurora_client_class: str
    nav_goal_timeout_sec: float

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

    return AppConfig(
        root_dir=root_dir,
        namespace=os.getenv("ROBOT_NAMESPACE", "GR301AA0025"),
        data_dir=data_dir,
        map_root=Path(os.getenv("MAP_ROOT", "/opt/fftai/nav")).expanduser(),
        default_map_path=os.getenv("DEFAULT_MAP_PATH", "/opt/fftai/nav/map"),
        nav_points_file=nav_points_file,
        show_cruise_dir=Path(
            os.getenv("SHOW_CRUISE_DIR", data_dir / "show_cruises")
        ).expanduser(),
        upload_dir=Path(os.getenv("UPLOAD_DIR", data_dir / "uploads")).expanduser(),
        require_aurora=_bool_env("REQUIRE_AURORA", False),
        aurora_mock=_bool_env("AURORA_MOCK", False),
        aurora_robot_name=os.getenv("AURORA_ROBOT_NAME", "gr3v233"),
        aurora_domain_id=int(os.getenv("AURORA_DOMAIN_ID", "123")),
        aurora_backend=os.getenv("AURORA_BACKEND", "docker").strip().lower(),
        aurora_container_name=os.getenv("AURORA_CONTAINER_NAME", "fourier_aurora_server"),
        aurora_container_workdir=os.getenv("AURORA_CONTAINER_WORKDIR", "/workspace"),
        aurora_container_python=os.getenv("AURORA_CONTAINER_PYTHON", "python3"),
        aurora_docker_timeout_sec=float(os.getenv("AURORA_DOCKER_TIMEOUT_SEC", "20")),
        aurora_state_cache_ttl_sec=float(os.getenv("AURORA_STATE_CACHE_TTL_SEC", "10")),
        aurora_state_stale_ttl_sec=float(os.getenv("AURORA_STATE_STALE_TTL_SEC", "120")),
        aurora_docker_lock_timeout_sec=float(os.getenv("AURORA_DOCKER_LOCK_TIMEOUT_SEC", "0.2")),
        aurora_sdk_path=os.getenv("AURORA_SDK_PATH", ""),
        aurora_client_module=os.getenv("AURORA_CLIENT_MODULE", ""),
        aurora_client_class=os.getenv("AURORA_CLIENT_CLASS", "AuroraClient"),
        nav_goal_timeout_sec=float(os.getenv("NAV_GOAL_TIMEOUT_SEC", "300")),
    )
