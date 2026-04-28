from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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
        description="Unitree-compatible HTTP adapter for GR3 HumanoidNav/Aurora.",
        version="0.1.0",
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

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "namespace": config.ns}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    return app


app = create_app()
