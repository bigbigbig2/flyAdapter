from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.core.utils import pose_dict, quaternion_from_yaw


class PoseIn(BaseModel):
    x: float = Field(default=0.0, description="目标或初始位姿的 x 坐标，单位米")
    y: float = Field(default=0.0, description="目标或初始位姿的 y 坐标，单位米")
    z: float = Field(default=0.0, description="目标或初始位姿的 z 坐标，通常为 0")
    yaw: float | None = Field(default=None, description="航向角，单位弧度；填写后会自动转换为四元数")
    q_x: float = Field(default=0.0, description="姿态四元数 x；未填写 yaw 时生效")
    q_y: float = Field(default=0.0, description="姿态四元数 y；未填写 yaw 时生效")
    q_z: float = Field(default=0.0, description="姿态四元数 z；未填写 yaw 时生效")
    q_w: float = Field(default=1.0, description="姿态四元数 w；未填写 yaw 时生效")
    frame_id: str = Field(default="map", description="ROS 坐标系，通常使用 map")

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
    map_path: str | None = Field(default=None, description="地图绝对路径，例如 /opt/fftai/nav/maps/office_a")
    map_name: str | None = Field(default=None, description="MAP_ROOT 下的地图目录名；未传 map_path 时使用")
    path: str | None = Field(default=None, description="兼容字段，等同于 map_path")
    init_pose: PoseIn | None = Field(default=None, description="加载地图后的初始位姿")
    x: float | None = Field(default=None, description="兼容旧接口的初始 x 坐标")
    y: float | None = Field(default=None, description="兼容旧接口的初始 y 坐标")
    z: float | None = Field(default=None, description="兼容旧接口的初始 z 坐标")
    yaw: float | None = Field(default=None, description="兼容旧接口的初始航向角，单位弧度")
    wait_for_localization: bool = Field(default=False, description="是否等待 odom_status_code 变为 GOOD 后再返回")


class AddNavPointRequest(BaseModel):
    name: str = Field(default="", description="导航点名称；为空时由适配层自动生成")


class SetMapPathRequest(BaseModel):
    path: str | None = Field(default=None, description="兼容字段，等同于 map_path")
    map_path: str | None = Field(default=None, description="地图绝对路径；为空时可使用 map_name")
    map_name: str | None = Field(default=None, description="MAP_ROOT 下的地图目录名")


class NavigateToRequest(PoseIn):
    name: str = Field(default="API Target", description="本次导航目标名称，用于状态和事件展示")
    force: bool = Field(default=False, description="是否跳过 readiness blocker 强制下发导航")


class StartShowCruiseRequest(BaseModel):
    name: str = Field(description="巡航点文件名称，不需要写 .json")
    force: bool = Field(default=False, description="是否跳过 readiness blocker 强制开始巡航")


class TalkTextRequest(BaseModel):
    text: str = Field(description="需要朗读的文本；当前实现为兼容 no-op")


class SlamModeRequest(BaseModel):
    mode: str = Field(description="HumanoidNav 模式，通常为 mapping 或 localization")


class MapSaveRequest(BaseModel):
    map_name: str | None = Field(default=None, description="地图名称；可由服务侧解析为保存路径")
    map_path: str | None = Field(default=None, description="地图保存目录路径")


class MapLoadRequest(BaseModel):
    map_path: str | None = Field(default=None, description="地图绝对路径；为空时可使用 map_name")
    map_name: str | None = Field(default=None, description="MAP_ROOT 下的地图目录名")
    x: float = Field(default=0.0, description="加载地图后的初始 x 坐标")
    y: float = Field(default=0.0, description="加载地图后的初始 y 坐标")
    z: float = Field(default=0.0, description="加载地图后的初始 z 坐标")
    yaw: float = Field(default=0.0, description="加载地图后的初始航向角，单位弧度")
    wait_for_localization: bool = Field(default=True, description="是否等待定位状态 GOOD 后再返回")


class MapLoadByNameRequest(BaseModel):
    map_name: str = Field(description="MAP_ROOT 下的地图目录名")
    x: float = Field(default=0.0, description="加载地图后的初始 x 坐标")
    y: float = Field(default=0.0, description="加载地图后的初始 y 坐标")
    z: float = Field(default=0.0, description="加载地图后的初始 z 坐标")
    yaw: float = Field(default=0.0, description="加载地图后的初始航向角，单位弧度")
    wait_for_localization: bool = Field(default=True, description="是否等待定位状态 GOOD 后再返回")


class InitialPoseRequest(PoseIn):
    pass


class GotoPoseRequest(BaseModel):
    pose: PoseIn = Field(description="导航目标位姿")
    label: str = Field(default="API Target", description="本次导航任务标签")
    force: bool = Field(default=False, description="是否跳过 readiness blocker 强制下发导航")


class GotoPoiRequest(BaseModel):
    name: str = Field(description="POI 名称")
    map_name: str | None = Field(default=None, description="地图名称，用于后续按地图过滤 POI")
    force: bool = Field(default=False, description="是否跳过 readiness blocker 强制下发导航")


class Poi(BaseModel):
    name: str = Field(description="POI 名称")
    map_name: str | None = Field(default=None, description="POI 所属地图名称")
    x: float = Field(description="POI x 坐标，单位米")
    y: float = Field(description="POI y 坐标，单位米")
    z: float = Field(default=0.0, description="POI z 坐标，通常为 0")
    yaw: float | None = Field(default=None, description="POI 航向角，单位弧度；填写后会自动转换为四元数")
    q_x: float = Field(default=0.0, description="POI 四元数 x；未填写 yaw 时生效")
    q_y: float = Field(default=0.0, description="POI 四元数 y；未填写 yaw 时生效")
    q_z: float = Field(default=0.0, description="POI 四元数 z；未填写 yaw 时生效")
    q_w: float = Field(default=1.0, description="POI 四元数 w；未填写 yaw 时生效")
    frame_id: str = Field(default="map", description="ROS 坐标系，通常使用 map")
    tags: list[str] = Field(default_factory=list, description="POI 标签，便于业务侧过滤")
    meta: dict[str, Any] = Field(default_factory=dict, description="POI 扩展信息")

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
    poi: Poi = Field(description="需要新增或覆盖的 POI")


class SaveCurrentPoiRequest(BaseModel):
    name: str = Field(description="要保存的 POI 名称")
    map_name: str | None = Field(default=None, description="POI 所属地图名称")
    tags: list[str] = Field(default_factory=list, description="POI 标签")
    meta: dict[str, Any] = Field(default_factory=dict, description="POI 扩展信息")


class Route(BaseModel):
    name: str = Field(description="路线名称")
    map_name: str | None = Field(default=None, description="路线所属地图名称")
    points: list[str] = Field(description="路线包含的 POI 名称列表，按顺序执行")
    meta: dict[str, Any] = Field(default_factory=dict, description="路线扩展信息")


class RouteUpsertRequest(BaseModel):
    route: Route = Field(description="需要新增或覆盖的路线")


class PatrolStartRequest(BaseModel):
    route_name: str = Field(description="要启动的路线名称")
    map_name: str | None = Field(default=None, description="路线所属地图名称")
    loop: bool = Field(default=False, description="是否循环巡航；当前保留字段")
    force: bool = Field(default=False, description="是否跳过 readiness blocker 强制开始巡航")


class FsmRequest(BaseModel):
    fsm_state: int = Field(description="Aurora FSM 状态值，需按厂商 SDK 定义填写")
