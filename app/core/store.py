from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from app.config import AppConfig


class JsonStore:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._lock = threading.RLock()
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
        safe_name = self._safe_name(name)
        candidates = [
            self.config.show_cruise_dir / f"{safe_name}.json",
            self.config.data_dir / f"{safe_name}.json",
            Path("/home/unitree/testdata") / f"{safe_name}.json",
        ]
        for candidate in candidates:
            if candidate.exists():
                return self._parse_nav_points(self._read_json(candidate, {}))
        raise FileNotFoundError(f"cruise file not found: {name}")

    def list_maps(self) -> list[dict[str, Any]]:
        maps: list[dict[str, Any]] = []
        for root, root_kind in self._map_roots():
            if not root.exists():
                continue
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
                        "map_root": str(root),
                        "root_kind": root_kind,
                        "has_global_pcd": has_pcd,
                        "has_map_yaml": has_yaml,
                        "has_map_pgm": has_pgm,
                        "valid_for_load": has_pcd and has_yaml and has_pgm,
                    }
                )
        return maps

    def resolve_map_name(self, name: str) -> str:
        return self.resolve_map_reference(name, require_exists=True)

    def resolve_map_reference(self, value: str, require_exists: bool = False) -> str:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError("map name/path is empty")
        path = Path(raw).expanduser()
        if path.is_absolute():
            if require_exists and not path.exists():
                raise FileNotFoundError(f"map not found: {raw}")
            return str(path)

        safe_name = self._safe_name(raw)
        candidates = []
        for root, _ in self._map_roots():
            resolved_root = root.resolve()
            candidate = (resolved_root / safe_name).resolve()
            try:
                candidate.relative_to(resolved_root)
            except ValueError as exc:
                raise ValueError(f"map path escaped configured map roots: {raw}") from exc
            candidates.append(candidate)
            if require_exists and candidate.exists():
                return str(candidate)
        if require_exists:
            searched = ", ".join(str(path) for path in candidates)
            raise FileNotFoundError(f"map not found: {raw}; searched: {searched}")
        return str(candidates[0])

    def map_name_from_path(self, path: str) -> str:
        raw = str(path or "").strip()
        if not raw:
            return ""
        try:
            target = Path(raw).expanduser().resolve()
            for root, _ in self._map_roots():
                try:
                    return str(target.relative_to(root.resolve())).replace("\\", "/")
                except ValueError:
                    continue
        except Exception:
            pass
        return Path(raw).name

    def _map_roots(self) -> list[tuple[Path, str]]:
        roots: list[tuple[Path, str]] = [(self.config.map_root, "primary")]
        fallback = self.config.map_save_fallback_root
        if fallback is not None and fallback != self.config.map_root:
            roots.append((fallback, "fallback"))
        return roots

    def load_routes(self) -> dict[str, Any]:
        return self._read_json(self.routes_file, {"routes": []})

    def save_routes(self, routes: dict[str, Any]) -> None:
        self._write_json(self.routes_file, routes)

    @classmethod
    def _parse_nav_points(cls, data: dict[str, Any]) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
        points = data.get("navigation_points") or data.get("nav_points") or []
        map_file = data.get("map_file", "")
        initial_pose = data.get("initial_pose") or {}
        normalized: list[dict[str, Any]] = []
        for point in points:
            if not isinstance(point, dict):
                continue
            normalized.append(
                {
                    "name": str(point.get("name", f"point_{len(normalized) + 1}")),
                    "x": cls._float(point.get("x", point.get("pose", {}).get("x", 0.0))),
                    "y": cls._float(point.get("y", point.get("pose", {}).get("y", 0.0))),
                    "z": cls._float(point.get("z", point.get("pose", {}).get("z", 0.0))),
                    "q_x": cls._float(point.get("q_x", point.get("pose", {}).get("q_x", 0.0))),
                    "q_y": cls._float(point.get("q_y", point.get("pose", {}).get("q_y", 0.0))),
                    "q_z": cls._float(point.get("q_z", point.get("pose", {}).get("q_z", 0.0))),
                    "q_w": cls._float(point.get("q_w", point.get("pose", {}).get("q_w", 1.0)), default=1.0),
                    "map_file": point.get("map_file"),
                    "map_name": point.get("map_name"),
                    "frame_id": str(point.get("frame_id", "map")),
                    "tags": list(point.get("tags", [])) if isinstance(point.get("tags", []), list) else [],
                    "meta": dict(point.get("meta", {})) if isinstance(point.get("meta", {}), dict) else {},
                }
            )
        return normalized, map_file, initial_pose

    def _read_json(self, path: Path, default: Any) -> Any:
        with self._lock:
            if not path.exists():
                return default
            try:
                with path.open("r", encoding="utf-8") as handle:
                    return json.load(handle)
            except json.JSONDecodeError:
                return default

    def _write_json(self, path: Path, data: Any) -> None:
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{threading.get_ident()}.tmp")
            with tmp.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            tmp.replace(path)

    @staticmethod
    def _safe_name(name: str) -> str:
        value = str(name).strip()
        if not value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError(f"invalid name: {name}")
        return value

    @staticmethod
    def _float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
