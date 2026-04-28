from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.compat import router as compat_router
from app.api.robot import router as robot_router
from app.bridges.aurora_bridge import AuroraBridge
from app.bridges.ros_bridge import RosBridge
from app.config import load_config
from app.core.events import EventHub
from app.core.state import RuntimeState
from app.core.store import JsonStore
from app.services.robot_service import RobotService


def create_app() -> FastAPI:
    config = load_config()
    state = RuntimeState(config)
    events = EventHub()
    store = JsonStore(config)
    ros = RosBridge(config, state, events)
    aurora = AuroraBridge(config)
    robot_service = RobotService(config, state, store, ros, aurora, events)

    app = FastAPI(
        title="GR3 Robot Adapter",
        description=(
            "GR3 机器人适配服务。外层兼容原 Unitree /slam 与 /audio 接口，"
            "内部桥接 HumanoidNav ROS2，并通过 Aurora Agent 调用底层运动控制。默认命名空间为 /GR301AA0025。"
        ),
        version="0.1.0",
        openapi_tags=[
            {
                "name": "unitree-compatible",
                "description": "背包优先调用的 Unitree 兼容接口，路径保持 /slam/... 和 /audio/...",
            },
            {
                "name": "gr3-debug",
                "description": "GR3 内部调试接口，用于检查 readiness、ROS2、Aurora Agent、地图、POI、巡航任务。",
            },
        ],
    )
    app.state.config = config
    app.state.robot_service = robot_service

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(compat_router)
    app.include_router(robot_router)

    @app.on_event("startup")
    def on_startup() -> None:
        robot_service.start()

    @app.on_event("shutdown")
    def on_shutdown() -> None:
        robot_service.stop()

    @app.exception_handler(FileNotFoundError)
    async def not_found_handler(request: Request, exc: FileNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"success": False, "message": str(exc)})

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"success": False, "message": str(exc)})

    @app.get("/healthz", tags=["gr3-debug"], summary="检查适配服务进程是否存活")
    def healthz() -> dict:
        """只表示 FastAPI 进程活着，不代表 ROS2、HumanoidNav、Aurora Agent 或定位已经 ready。"""
        return {"ok": True, "namespace": config.ns}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    return app


app = create_app()
