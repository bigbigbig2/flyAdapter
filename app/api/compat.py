from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Body, File, Request, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse

from app.core.utils import now_ms
from app.schemas import (
    AddNavPointRequest,
    NavigateToRequest,
    RelocationRequest,
    SetMapPathRequest,
    StartShowCruiseRequest,
    TalkTextRequest,
)
from app.services.robot_service import RobotService

router = APIRouter(tags=["unitree-compatible"])


def service(request: Request) -> RobotService:
    return request.app.state.robot_service


@router.get("/slam/status", summary="查询 Unitree 兼容状态")
def slam_status(request: Request) -> dict:
    """返回背包最常用的兼容状态，包含巡航状态、地图路径、定位状态、ROS/Aurora 扩展状态。"""
    return service(request).legacy_status()


@router.get("/slam/pose", summary="查询当前机器人位姿")
def slam_pose(request: Request) -> dict:
    """返回当前缓存的 `/GR301AA0025/robot_pose`，字段兼容 Unitree 的 x/y/z/q_x/q_y/q_z/q_w。"""
    return service(request).get_pose()


@router.post("/slam/start_mapping", summary="开始建图模式")
def start_mapping(request: Request) -> dict:
    """调用 HumanoidNav `/slam/set_mode` 切换到 mapping，用于开始建图流程。"""
    result = service(request).start_mapping()
    return {**service(request).legacy_status(), "result": result}


@router.post("/slam/stop_mapping", summary="结束建图并保存地图")
@router.post("/aslam/stop_mapping", summary="兼容旧拼写：结束建图并保存地图")
def stop_mapping(request: Request, body: dict | None = Body(default=None)) -> dict:
    """调用 HumanoidNav `/slam/save_map` 保存地图，同时兼容原 Unitree 工程中的 `/aslam/stop_mapping` 误拼写。"""
    map_path = None
    if body:
        map_path = body.get("map_path") or body.get("path") or body.get("map_file")
    result = service(request).stop_mapping(map_path)
    return {**service(request).legacy_status(), "result": result}


@router.post("/slam/relocation", summary="加载地图并进入定位模式")
def relocation(request: Request, body: RelocationRequest | None = Body(default=None)) -> dict:
    """调用 HumanoidNav `/slam/load_map`，加载地图目录并切到 localization。"""
    body = body or RelocationRequest()
    init_pose = body.init_pose
    x = body.x if body.x is not None else (init_pose.x if init_pose else 0.0)
    y = body.y if body.y is not None else (init_pose.y if init_pose else 0.0)
    z = body.z if body.z is not None else (init_pose.z if init_pose else 0.0)
    yaw = body.yaw if body.yaw is not None else (init_pose.yaw if init_pose and init_pose.yaw is not None else 0.0)
    return service(request).relocation(
        map_path=body.map_path or body.path,
        x=x,
        y=y,
        z=z,
        yaw=yaw,
        wait_for_localization=body.wait_for_localization,
    )


@router.post("/slam/add_nav_point", summary="保存当前位置为导航点")
def add_nav_point(request: Request, body: AddNavPointRequest | None = Body(default=None)) -> dict:
    """读取当前 `robot_pose` 缓存，保存为本地 Unitree 风格导航点。"""
    return service(request).add_current_pose_to_nav_points((body.name if body else "") or "")


@router.get("/slam/nav_points", summary="查询导航点列表")
def nav_points(request: Request) -> dict:
    """读取本地 `data/navigation_points.json`，返回 `nav_points` 和 `count`。"""
    return service(request).nav_points_response()


@router.post("/slam/start_cruise", summary="开始多点巡航")
def start_cruise(request: Request, body: dict | None = Body(default=None)) -> dict:
    """按本地导航点顺序逐个发送 `navigate_to_pose`，事件通过 `/slam/events` 推送。"""
    return service(request).start_cruise(force=bool((body or {}).get("force", False)))


@router.post("/slam/start_show_cruise", summary="按名称加载巡航文件并开始巡航")
def start_show_cruise(request: Request, body: StartShowCruiseRequest) -> dict:
    """兼容展厅演示流程，按 `name` 加载 `{name}.json` 巡航点文件后开始巡航。"""
    loaded = service(request).load_nav_points_by_name(body.name)
    if loaded.get("success") is False:
        return loaded
    return service(request).start_cruise(force=body.force)


@router.post("/slam/stop_cruise", summary="停止巡航")
def stop_cruise(request: Request) -> dict:
    """停止适配层巡航线程，取消当前 Nav2 goal，并调用 Aurora stop_motion 兜底。"""
    return service(request).stop_cruise()


@router.post("/slam/save_nav_points", summary="保存导航点文件")
def save_nav_points(request: Request) -> dict:
    """把当前导航点写入本地 `navigation_points.json`。"""
    return service(request).save_nav_points()


@router.post("/slam/load_nav_points", summary="加载导航点文件")
def load_nav_points(request: Request) -> dict:
    """从本地 `navigation_points.json` 加载地图路径、初始位姿和导航点。"""
    return service(request).load_nav_points()


@router.post("/slam/clear_nav_points", summary="清空导航点")
def clear_nav_points(request: Request) -> dict:
    """清空本地导航点，并把巡航 index 重置为 0。"""
    return service(request).clear_nav_points()


@router.post("/slam/pause_nav", summary="暂停导航")
def pause_nav(request: Request) -> dict:
    """GR3 当前用 cancel 当前 goal + 保留巡航 index 的方式模拟暂停。"""
    return service(request).pause_nav()


@router.post("/slam/resume_nav", summary="恢复导航")
def resume_nav(request: Request) -> dict:
    """清除暂停标记，巡航线程会继续发送当前 index 对应的目标。"""
    return service(request).resume_nav()


@router.post("/slam/set_map_path", summary="设置当前地图路径")
def set_map_path(request: Request, body: SetMapPathRequest) -> dict:
    """只更新适配层 runtime 里的当前地图路径，不等价于底层 load_map。"""
    return service(request).set_map_path(body.path)


@router.post("/slam/navigate_to", summary="导航到指定坐标")
def navigate_to(request: Request, body: NavigateToRequest) -> dict:
    """执行导航前会走 readiness 预检，然后把目标转换成 Nav2 `navigate_to_pose` action。"""
    return service(request).navigate_to(body.to_pose_dict(), label=body.name, force=body.force)


@router.get("/slam/nav_status", summary="轮询导航状态")
def nav_status(request: Request) -> dict:
    """不使用 SSE 时可通过本接口轮询巡航进度、当前目标和距离。"""
    return service(request).nav_status()


@router.get("/slam/events", summary="订阅 Unitree 兼容 SSE 事件")
def slam_events(request: Request) -> StreamingResponse:
    """返回 `text/event-stream`，推送 position_update、nav_arrival、nav_failed、cruise_complete 等事件。"""
    async def stream():
        payload = {"event_type": "connection_established", "message": "SSE connection established", "timestamp": now_ms()}
        yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
        async for item in service(request).events.stream():
            yield item

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/task/{task_id}/events", summary="兼容任务 SSE 事件")
def task_events(request: Request, task_id: str) -> StreamingResponse:
    """兼容旧调试入口，当前复用 `/slam/events` 的事件源。"""
    async def stream():
        payload = {"event_type": "connection_established", "task_id": task_id, "timestamp": now_ms()}
        yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
        async for item in service(request).events.stream():
            yield item

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/audio/play_wav", summary="兼容 WAV 上传接口")
async def play_wav(request: Request, wavfile: UploadFile = File(...)) -> PlainTextResponse:
    """接收 `wavfile` 表单文件并保存到 uploads；当前不直接驱动 GR3 播放。"""
    cfg = request.app.state.config
    filename = Path(wavfile.filename or "upload.wav").name
    target = cfg.upload_dir / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        handle.write(await wavfile.read())
    # Audio playback is intentionally a compatibility hook. Wire a GR3 audio
    # bridge here if the backpack expects the robot body to play sound.
    return PlainTextResponse("Upload OK")


@router.post("/audio/talk_text", summary="兼容文本朗读接口")
def talk_text(request: Request, body: TalkTextRequest) -> dict:
    """兼容背包可能调用的 TTS 文本接口；当前作为 no-op 返回成功。"""
    return {
        **service(request).legacy_status(),
        "audio": {"success": True, "message": "talk_text accepted as compatibility no-op", "text": body.text},
    }
