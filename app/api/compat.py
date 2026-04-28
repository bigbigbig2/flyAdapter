from __future__ import annotations

import json

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


@router.get("/slam/status")
def slam_status(request: Request) -> dict:
    return service(request).legacy_status()


@router.get("/slam/pose")
def slam_pose(request: Request) -> dict:
    return service(request).get_pose()


@router.post("/slam/start_mapping")
def start_mapping(request: Request) -> dict:
    result = service(request).start_mapping()
    return {**service(request).legacy_status(), "result": result}


@router.post("/slam/stop_mapping")
@router.post("/aslam/stop_mapping")
def stop_mapping(request: Request, body: dict | None = Body(default=None)) -> dict:
    map_path = None
    if body:
        map_path = body.get("map_path") or body.get("path") or body.get("map_file")
    result = service(request).stop_mapping(map_path)
    return {**service(request).legacy_status(), "result": result}


@router.post("/slam/relocation")
def relocation(request: Request, body: RelocationRequest | None = Body(default=None)) -> dict:
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


@router.post("/slam/add_nav_point")
def add_nav_point(request: Request, body: AddNavPointRequest | None = Body(default=None)) -> dict:
    return service(request).add_current_pose_to_nav_points((body.name if body else "") or "")


@router.get("/slam/nav_points")
def nav_points(request: Request) -> dict:
    return service(request).nav_points_response()


@router.post("/slam/start_cruise")
def start_cruise(request: Request, body: dict | None = Body(default=None)) -> dict:
    return service(request).start_cruise(force=bool((body or {}).get("force", False)))


@router.post("/slam/start_show_cruise")
def start_show_cruise(request: Request, body: StartShowCruiseRequest) -> dict:
    service(request).load_nav_points_by_name(body.name)
    return service(request).start_cruise(force=body.force)


@router.post("/slam/stop_cruise")
def stop_cruise(request: Request) -> dict:
    return service(request).stop_cruise()


@router.post("/slam/save_nav_points")
def save_nav_points(request: Request) -> dict:
    return service(request).save_nav_points()


@router.post("/slam/load_nav_points")
def load_nav_points(request: Request) -> dict:
    return service(request).load_nav_points()


@router.post("/slam/clear_nav_points")
def clear_nav_points(request: Request) -> dict:
    return service(request).clear_nav_points()


@router.post("/slam/pause_nav")
def pause_nav(request: Request) -> dict:
    return service(request).pause_nav()


@router.post("/slam/resume_nav")
def resume_nav(request: Request) -> dict:
    return service(request).resume_nav()


@router.post("/slam/set_map_path")
def set_map_path(request: Request, body: SetMapPathRequest) -> dict:
    return service(request).set_map_path(body.path)


@router.post("/slam/navigate_to")
def navigate_to(request: Request, body: NavigateToRequest) -> dict:
    return service(request).navigate_to(body.to_pose_dict(), label=body.name, force=body.force)


@router.get("/slam/nav_status")
def nav_status(request: Request) -> dict:
    return service(request).nav_status()


@router.get("/slam/events")
def slam_events(request: Request) -> StreamingResponse:
    async def stream():
        payload = {"event_type": "connection_established", "message": "SSE connection established", "timestamp": now_ms()}
        yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
        async for item in service(request).events.stream():
            yield item

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/task/{task_id}/events")
def task_events(request: Request, task_id: str) -> StreamingResponse:
    async def stream():
        payload = {"event_type": "connection_established", "task_id": task_id, "timestamp": now_ms()}
        yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
        async for item in service(request).events.stream():
            yield item

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/audio/play_wav")
async def play_wav(request: Request, wavfile: UploadFile = File(...)) -> PlainTextResponse:
    cfg = request.app.state.config
    target = cfg.upload_dir / wavfile.filename
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        handle.write(await wavfile.read())
    # Audio playback is intentionally a compatibility hook. Wire a GR3 audio
    # bridge here if the backpack expects the robot body to play sound.
    return PlainTextResponse("Upload OK")


@router.post("/audio/talk_text")
def talk_text(request: Request, body: TalkTextRequest) -> dict:
    return {
        **service(request).legacy_status(),
        "audio": {"success": True, "message": "talk_text accepted as compatibility no-op", "text": body.text},
    }
