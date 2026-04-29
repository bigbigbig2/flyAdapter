from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.aurora_sdk_runtime import AuroraSdkRuntime
from app.config import load_config


class FsmBody(BaseModel):
    fsm_state: int = Field(description="Aurora FSM state")


class StopMotionBody(BaseModel):
    duration: float = Field(default=1.0, description="Zero velocity command duration")


config = load_config()
runtime = AuroraSdkRuntime(config)

app = FastAPI(
    title="GR3 Aurora Agent",
    description="Local Aurora SDK sidecar. Run it only in the Aurora SDK environment.",
    version="0.2.0",
)


@app.on_event("startup")
def on_startup() -> None:
    runtime.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    runtime.stop()


@app.get("/health", summary="Check Aurora Agent health")
def health() -> dict[str, Any]:
    return runtime.health()


@app.get("/state", summary="Get cached Aurora state")
def state(force_refresh: bool = False) -> dict[str, Any]:
    return runtime.state(force_refresh=force_refresh)


@app.get("/diagnostics", summary="Get Aurora SDK diagnostics")
def diagnostics() -> dict[str, Any]:
    return runtime.diagnostics()


@app.post("/reset", summary="Reset Aurora SDK client")
def reset_client() -> dict[str, Any]:
    return runtime.reset_client()


@app.post("/fsm", summary="Set Aurora FSM")
def set_fsm(body: FsmBody) -> dict[str, Any]:
    return runtime.set_fsm(body.fsm_state)


@app.post("/ensure_stand", summary="Ensure standing state")
def ensure_stand() -> dict[str, Any]:
    return runtime.ensure_stand()


@app.post("/stop_motion", summary="Send zero velocity command")
def stop_motion(body: StopMotionBody | None = None) -> dict[str, Any]:
    return runtime.stop_motion(duration=(body.duration if body else 1.0))
