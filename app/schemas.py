from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.core.utils import pose_dict, quaternion_from_yaw


class PoseIn(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float | None = None
    q_x: float = 0.0
    q_y: float = 0.0
    q_z: float = 0.0
    q_w: float = 1.0
    frame_id: str = "map"

    def to_pose_dict(self) -> dict[str, Any]:
        quat = quaternion_from_yaw(self.yaw) if self.yaw is not None else {
            "q_x": self.q_x,
            "q_y": self.q_y,
            "q_z": self.q_z,
            "q_w": self.q_w,
        }
        return pose_dict(
            x=self.x,
            y=self.y,
            z=self.z,
            q_x=quat["q_x"],
            q_y=quat["q_y"],
            q_z=quat["q_z"],
            q_w=quat["q_w"],
            frame_id=self.frame_id,
        )


class RelocationRequest(BaseModel):
    map_path: str | None = None
    path: str | None = None
    init_pose: PoseIn | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    yaw: float | None = None
    wait_for_localization: bool = False


class AddNavPointRequest(BaseModel):
    name: str = ""


class SetMapPathRequest(BaseModel):
    path: str


class NavigateToRequest(PoseIn):
    name: str = "API Target"
    force: bool = False


class StartShowCruiseRequest(BaseModel):
    name: str
    force: bool = False


class TalkTextRequest(BaseModel):
    text: str


class SlamModeRequest(BaseModel):
    mode: str


class MapSaveRequest(BaseModel):
    map_name: str | None = None
    map_path: str | None = None


class MapLoadRequest(BaseModel):
    map_path: str
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0
    wait_for_localization: bool = True


class MapLoadByNameRequest(BaseModel):
    map_name: str
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw: float = 0.0
    wait_for_localization: bool = True


class InitialPoseRequest(PoseIn):
    pass


class GotoPoseRequest(BaseModel):
    pose: PoseIn
    label: str = "API Target"
    force: bool = False


class GotoPoiRequest(BaseModel):
    name: str
    map_name: str | None = None
    force: bool = False


class Poi(BaseModel):
    name: str
    map_name: str | None = None
    x: float
    y: float
    z: float = 0.0
    yaw: float | None = None
    q_x: float = 0.0
    q_y: float = 0.0
    q_z: float = 0.0
    q_w: float = 1.0
    frame_id: str = "map"
    tags: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

    def to_nav_point(self) -> dict[str, Any]:
        pose = PoseIn(
            x=self.x,
            y=self.y,
            z=self.z,
            yaw=self.yaw,
            q_x=self.q_x,
            q_y=self.q_y,
            q_z=self.q_z,
            q_w=self.q_w,
            frame_id=self.frame_id,
        ).to_pose_dict()
        return {
            "name": self.name,
            "x": pose["x"],
            "y": pose["y"],
            "z": pose["z"],
            "q_x": pose["q_x"],
            "q_y": pose["q_y"],
            "q_z": pose["q_z"],
            "q_w": pose["q_w"],
            "map_name": self.map_name,
            "frame_id": self.frame_id,
            "tags": self.tags,
            "meta": self.meta,
        }


class PoiUpsertRequest(BaseModel):
    poi: Poi


class SaveCurrentPoiRequest(BaseModel):
    name: str
    map_name: str | None = None
    tags: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class Route(BaseModel):
    name: str
    map_name: str | None = None
    points: list[str]
    meta: dict[str, Any] = Field(default_factory=dict)


class RouteUpsertRequest(BaseModel):
    route: Route


class PatrolStartRequest(BaseModel):
    route_name: str
    map_name: str | None = None
    loop: bool = False
    force: bool = False


class FsmRequest(BaseModel):
    fsm_state: int
