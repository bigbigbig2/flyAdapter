from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import AppConfig


class JsonStore:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self.config.show_cruise_dir.mkdir(parents=True, exist_ok=True)
        self.config.upload_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_file = self.config.data_dir / "runtime.json"
        self.routes_file = self.config.data_dir / "routes.json"
        if not self.config.nav_points_file.exists():
            self.save_nav_points([], self.config.default_map_path)

    def load_runtime(self) -> dict[str, Any]:
        return self._read_json(self.runtime_file, {})

    def save_runtime(self, data: dict[str, Any]) -> None:
        self._write_json(self.runtime_file, data)

    def load_nav_points(self) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
        data = self._read_json(self.config.nav_points_file, {})
        return self._parse_nav_points(data)

    def save_nav_points(
        self,
        points: list[dict[str, Any]],
        map_file: str,
        initial_pose: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "map_file": map_file,
            "initial_pose": initial_pose
            or {"x": 0.0, "y": 0.0, "z": 0.0, "q_x": 0.0, "q_y": 0.0, "q_z": 0.0, "q_w": 1.0},
            "navigation_points": points,
        }
        self._write_json(self.config.nav_points_file, payload)

    def load_show_cruise(self, name: str) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
        candidates = [
            self.config.show_cruise_dir / f"{name}.json",
            self.config.data_dir / f"{name}.json",
            Path("/home/unitree/testdata") / f"{name}.json",
        ]
        for candidate in candidates:
            if candidate.exists():
                return self._parse_nav_points(self._read_json(candidate, {}))
        raise FileNotFoundError(f"cruise file not found: {name}")

    def list_maps(self) -> list[dict[str, Any]]:
        root = self.config.map_root
        maps: list[dict[str, Any]] = []
        if not root.exists():
            return maps
        for path in sorted(root.iterdir()):
            if not path.is_dir():
                continue
            has_pcd = (path / "global.pcd").exists()
            has_yaml = (path / "map.yaml").exists()
            has_pgm = (path / "map.pgm").exists()
            maps.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "has_global_pcd": has_pcd,
                    "has_map_yaml": has_yaml,
                    "has_map_pgm": has_pgm,
                    "valid_for_load": has_pcd and has_yaml and has_pgm,
                }
            )
        return maps

    def resolve_map_name(self, name: str) -> str:
        path = self.config.map_root / name
        if not path.exists():
            raise FileNotFoundError(f"map not found: {name}")
        return str(path)

    def load_routes(self) -> dict[str, Any]:
        return self._read_json(self.routes_file, {"routes": []})

    def save_routes(self, routes: dict[str, Any]) -> None:
        self._write_json(self.routes_file, routes)

    @staticmethod
    def _parse_nav_points(data: dict[str, Any]) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
        points = data.get("navigation_points") or data.get("nav_points") or []
        map_file = data.get("map_file", "")
        initial_pose = data.get("initial_pose") or {}
        normalized: list[dict[str, Any]] = []
        for point in points:
            normalized.append(
                {
                    "name": str(point.get("name", f"point_{len(normalized) + 1}")),
                    "x": float(point.get("x", point.get("pose", {}).get("x", 0.0))),
                    "y": float(point.get("y", point.get("pose", {}).get("y", 0.0))),
                    "z": float(point.get("z", point.get("pose", {}).get("z", 0.0))),
                    "q_x": float(point.get("q_x", point.get("pose", {}).get("q_x", 0.0))),
                    "q_y": float(point.get("q_y", point.get("pose", {}).get("q_y", 0.0))),
                    "q_z": float(point.get("q_z", point.get("pose", {}).get("q_z", 0.0))),
                    "q_w": float(point.get("q_w", point.get("pose", {}).get("q_w", 1.0))),
                }
            )
        return normalized, map_file, initial_pose

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        tmp.replace(path)
