from __future__ import annotations

from fastapi import APIRouter, Body, Query, Request

from app.schemas import (
    FsmRequest,
    GotoPoiRequest,
    GotoPoseRequest,
    InitialPoseRequest,
    MapLoadByNameRequest,
    MapLoadRequest,
    MapSaveRequest,
    PatrolStartRequest,
    PoiUpsertRequest,
    RouteUpsertRequest,
    SaveCurrentPoiRequest,
    SlamModeRequest,
)
from app.services.robot_service import RobotService

router = APIRouter(prefix="/robot", tags=["gr3-debug"])


def service(request: Request) -> RobotService:
    return request.app.state.robot_service


@router.get("/status")
def status(request: Request) -> dict:
    return service(request).status()


@router.get("/readiness")
def readiness(request: Request) -> dict:
    return service(request).readiness()


@router.post("/navigation/precheck")
def navigation_precheck(request: Request, body: dict | None = Body(default=None)) -> dict:
    return service(request).precheck_navigation(force=bool((body or {}).get("force", False)))


@router.get("/localization/status")
def localization_status(request: Request) -> dict:
    return service(request).localization_status()


@router.post("/slam/mode")
def slam_mode(request: Request, body: SlamModeRequest) -> dict:
    result = service(request).start_mapping() if body.mode == "mapping" else service(request)._safe_ros_call(
        lambda: service(request).ros.switch_mode(body.mode),
        "set_mode",
    )
    return {"result": result, "status": service(request).legacy_status()}


@router.get("/map/list")
def map_list(request: Request) -> dict:
    return service(request).list_maps()


@router.get("/map/current")
def map_current(request: Request) -> dict:
    return {"current_map": service(request).state.snapshot()["current_map"]}


@router.post("/map/save")
def map_save(request: Request, body: MapSaveRequest) -> dict:
    return service(request).stop_mapping(body.map_path or body.map_name)


@router.post("/map/load")
def map_load(request: Request, body: MapLoadRequest) -> dict:
    return service(request).relocation(
        body.map_path,
        x=body.x,
        y=body.y,
        z=body.z,
        yaw=body.yaw,
        wait_for_localization=body.wait_for_localization,
    )


@router.post("/map/load_by_name")
def map_load_by_name(request: Request, body: MapLoadByNameRequest) -> dict:
    return service(request).load_map_by_name(body.map_name, body.x, body.y, body.z, body.yaw, body.wait_for_localization)


@router.post("/localization/initial_pose")
def initial_pose(request: Request, body: InitialPoseRequest) -> dict:
    result = service(request)._safe_ros_call(
        lambda: service(request).ros.publish_initial_pose(
            body.x,
            body.y,
            z=body.z,
            yaw=body.yaw or 0.0,
            frame_id=body.frame_id,
        ),
        "initial_pose",
    )
    return {"result": result, "status": service(request).localization_status()}


@router.post("/navigation/goto_pose")
def goto_pose(request: Request, body: GotoPoseRequest) -> dict:
    return service(request).navigate_to(body.pose.to_pose_dict(), label=body.label, force=body.force)


@router.post("/navigation/goto_poi")
def goto_poi(request: Request, body: GotoPoiRequest) -> dict:
    return service(request).goto_poi(body.name, force=body.force)


@router.post("/navigation/cancel")
def navigation_cancel(request: Request) -> dict:
    result = service(request)._safe_ros_call(lambda: service(request).ros.cancel_current_action(), "cancel")
    service(request).aurora.stop_motion()
    return {"result": result, "status": service(request).legacy_status()}


@router.get("/navigation/task")
def navigation_task(request: Request) -> dict:
    return service(request).state.snapshot()["navigation_task"]


@router.get("/navigation/current_action")
def navigation_current_action(request: Request) -> dict:
    return service(request).current_action()


@router.get("/poi/list")
def poi_list(request: Request, use_current_map: bool = Query(default=False)) -> dict:
    points = service(request).nav_points_response()["nav_points"]
    if use_current_map:
        current_map = service(request).state.snapshot()["current_map"]
        points = [p for p in points if not p.get("map_file") or p.get("map_file") == current_map]
    return {"points": points, "count": len(points)}


@router.get("/poi/{name}")
def poi_get(request: Request, name: str) -> dict:
    points = service(request).nav_points_response()["nav_points"]
    for point in points:
        if point.get("name") == name:
            return {"found": True, "poi": point}
    return {"found": False, "message": f"poi not found: {name}"}


@router.delete("/poi/{name}")
def poi_delete(request: Request, name: str) -> dict:
    return service(request).delete_poi(name)


@router.post("/poi/save_current")
def poi_save_current(request: Request, body: SaveCurrentPoiRequest) -> dict:
    return service(request).save_current_poi(body.name, body.map_name, body.tags, body.meta)


@router.post("/poi/upsert")
def poi_upsert(request: Request, body: PoiUpsertRequest) -> dict:
    return service(request).upsert_poi(body.poi.to_nav_point())


@router.get("/routes")
def routes(request: Request) -> dict:
    return service(request).store.load_routes()


@router.post("/routes/upsert")
def route_upsert(request: Request, body: RouteUpsertRequest) -> dict:
    data = service(request).store.load_routes()
    routes_list = [route for route in data.get("routes", []) if route.get("name") != body.route.name]
    routes_list.append(body.route.model_dump())
    data["routes"] = routes_list
    service(request).store.save_routes(data)
    return {"success": True, "route": body.route.model_dump()}


@router.post("/patrol/start")
def patrol_start(request: Request, body: PatrolStartRequest) -> dict:
    data = service(request).store.load_routes()
    route = next((item for item in data.get("routes", []) if item.get("name") == body.route_name), None)
    if route is None:
        return {"success": False, "message": f"route not found: {body.route_name}"}
    all_points = service(request).nav_points_response()["nav_points"]
    selected = [point for name in route.get("points", []) for point in all_points if point.get("name") == name]
    if not selected:
        return {"success": False, "message": "route has no valid points"}
    service(request).store.save_nav_points(selected, service(request).state.snapshot()["current_map"])
    service(request).state.current_nav_name = body.route_name
    return service(request).start_cruise(force=body.force)


@router.post("/patrol/stop")
def patrol_stop(request: Request) -> dict:
    return service(request).stop_cruise()


@router.get("/patrol/status")
def patrol_status(request: Request) -> dict:
    return service(request).nav_status()


@router.get("/missions")
def missions(request: Request) -> dict:
    return service(request).store.load_routes()


@router.get("/missions/context")
def missions_context(request: Request) -> dict:
    return {
        "status": service(request).status(),
        "points": service(request).nav_points_response(),
        "routes": service(request).store.load_routes(),
    }


@router.post("/missions/upsert")
def mission_upsert(request: Request, body: RouteUpsertRequest) -> dict:
    return route_upsert(request, body)


@router.post("/missions/start")
def mission_start(request: Request, body: PatrolStartRequest) -> dict:
    return patrol_start(request, body)


@router.post("/missions/stop")
def mission_stop(request: Request) -> dict:
    return service(request).stop_cruise()


@router.get("/missions/status")
def mission_status(request: Request) -> dict:
    return service(request).nav_status()


@router.get("/aurora/ping")
def aurora_ping(request: Request) -> dict:
    return service(request).aurora.ping()


@router.get("/aurora/state")
def aurora_state(request: Request) -> dict:
    return service(request).aurora.state()


@router.post("/aurora/fsm")
def aurora_fsm(request: Request, body: FsmRequest) -> dict:
    return service(request).aurora.set_fsm(body.fsm_state)


@router.post("/aurora/ensure_stand")
def aurora_ensure_stand(request: Request) -> dict:
    return service(request).aurora.ensure_stand()


@router.post("/aurora/stop_motion")
def aurora_stop_motion(request: Request) -> dict:
    return service(request).aurora.stop_motion()
