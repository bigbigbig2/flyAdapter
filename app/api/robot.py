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


@router.get("/status", summary="查询 GR3 适配服务总状态")
def status(request: Request) -> dict:
    """聚合 adapter、ROS bridge、可选 Aurora、runtime、workflow readiness，用于调试总览。"""
    return service(request).status()


@router.get("/readiness", summary="查询导航前预检状态")
def readiness(request: Request) -> dict:
    """返回当前是否具备导航条件，以及 blockers/warnings 的具体原因。"""
    return service(request).readiness()


@router.get("/workflow/status", summary="查询分阶段流程状态")
def workflow_status(request: Request) -> dict:
    """分别返回手动建图、手动打点、自动导航三条流程的就绪状态。"""
    return service(request).workflow_status()


@router.get("/readiness/mapping", summary="查询手动建图就绪状态")
def readiness_mapping(request: Request) -> dict:
    """手动建图只要求 ROS/HumanoidNav、mapping 模式、位姿和健康状态，不依赖 Aurora。"""
    return service(request).mapping_readiness()


@router.get("/readiness/poi", summary="查询手动打点就绪状态")
def readiness_poi(request: Request) -> dict:
    """手动打点要求已加载地图、定位良好、位姿新鲜，不依赖 Aurora。"""
    return service(request).poi_readiness()


@router.get("/readiness/navigation", summary="查询自动导航就绪状态")
def readiness_navigation(request: Request) -> dict:
    """自动导航预检；只有 MOTION_GUARD=aurora 或 REQUIRE_AURORA=1 时才把 Aurora 作为前置条件。"""
    return service(request).readiness()


@router.get("/motion/authority", summary="查询运动控制权策略")
def motion_authority(request: Request) -> dict:
    """说明当前运动控制策略：手动建图/打点由遥控器控制，自动导航由 Nav2 goal 控制。"""
    return service(request).motion_authority()


@router.post("/motion/safety_stop", summary="按当前运动策略执行安全停止")
def motion_safety_stop(request: Request) -> dict:
    """取消当前导航；默认不碰遥控器运动链路，MOTION_GUARD=aurora 时才补充 Aurora stop_motion。"""
    return service(request).cancel_navigation()


@router.post("/navigation/precheck", summary="执行导航前预检")
def navigation_precheck(request: Request, body: dict | None = Body(default=None)) -> dict:
    """和 `/robot/readiness` 类似，但支持 `force=true`，用于导航接口内部调用。"""
    return service(request).precheck_navigation(force=bool((body or {}).get("force", False)))


@router.get("/localization/status", summary="查询定位链路状态")
def localization_status(request: Request) -> dict:
    """只关注地图、slam_mode、robot_pose、odom_status_code、odom_status_score 和 health。"""
    return service(request).localization_status()


@router.post("/slam/mode", summary="切换 HumanoidNav 建图/定位模式")
def slam_mode(request: Request, body: SlamModeRequest) -> dict:
    """调用 `/GR301AA0025/slam/set_mode`，mode 支持 mapping/localization。"""
    result = service(request).start_mapping() if body.mode == "mapping" else service(request)._safe_ros_call(
        lambda: service(request).ros.switch_mode(body.mode),
        "set_mode",
    )
    return {"result": result, "status": service(request).legacy_status()}


@router.get("/map/list", summary="列出可识别地图目录")
def map_list(request: Request) -> dict:
    """扫描 `MAP_ROOT`，识别包含 global.pcd、map.yaml、map.pgm 的地图目录。"""
    return service(request).list_maps()


@router.get("/map/current", summary="查询当前地图")
def map_current(request: Request) -> dict:
    """返回适配层 runtime 里记录的当前地图路径。"""
    return {"current_map": service(request).state.snapshot()["current_map"]}


@router.post("/map/save", summary="保存当前地图")
def map_save(request: Request, body: MapSaveRequest) -> dict:
    """调用 HumanoidNav `/slam/save_map`，保存当前建图结果。"""
    return service(request).stop_mapping(body.map_path or body.map_name)


@router.post("/map/load", summary="按路径加载地图")
def map_load(request: Request, body: MapLoadRequest) -> dict:
    """调用 HumanoidNav `/slam/load_map`，加载地图并进入 localization。"""
    return service(request).relocation(
        body.map_path,
        x=body.x,
        y=body.y,
        z=body.z,
        yaw=body.yaw,
        wait_for_localization=body.wait_for_localization,
    )


@router.post("/map/load_by_name", summary="按名称加载地图")
def map_load_by_name(request: Request, body: MapLoadByNameRequest) -> dict:
    """在 `MAP_ROOT` 下按地图目录名解析路径，再调用 `/robot/map/load`。"""
    return service(request).load_map_by_name(body.map_name, body.x, body.y, body.z, body.yaw, body.wait_for_localization)


@router.post("/localization/initial_pose", summary="发布初始位姿")
def initial_pose(request: Request, body: InitialPoseRequest) -> dict:
    """发布 `/GR301AA0025/initialpose`，用于手动辅助定位初始化。"""
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


@router.post("/navigation/goto_pose", summary="按坐标导航")
def goto_pose(request: Request, body: GotoPoseRequest) -> dict:
    """内部调试用导航接口，目标最终转成 Nav2 `navigate_to_pose` action。"""
    return service(request).navigate_to(body.pose.to_pose_dict(), label=body.label, force=body.force)


@router.post("/navigation/goto_poi", summary="按 POI 名称导航")
def goto_poi(request: Request, body: GotoPoiRequest) -> dict:
    """从本地导航点中查找 POI，再复用坐标导航。"""
    return service(request).goto_poi(body.name, force=body.force)


@router.post("/navigation/cancel", summary="取消当前导航")
def navigation_cancel(request: Request) -> dict:
    """取消 Nav2 当前 goal；只有运动策略要求 Aurora 时才调用 stop_motion。"""
    return service(request).cancel_navigation()


@router.get("/navigation/task", summary="查询适配层导航任务")
def navigation_task(request: Request) -> dict:
    """返回适配层维护的当前导航任务对象，不等价于底层 Nav2 的唯一真相。"""
    return service(request).state.snapshot()["navigation_task"]


@router.get("/navigation/current_action", summary="查询底层当前动作")
def navigation_current_action(request: Request) -> dict:
    """调用 `/get_current_action` 并返回缓存的 `/action_status` 快照。"""
    return service(request).current_action()


@router.get("/poi/list", summary="查询 POI 列表")
def poi_list(request: Request, use_current_map: bool = Query(default=False)) -> dict:
    """返回本地导航点；`use_current_map=true` 时只看当前地图相关点。"""
    points = service(request).nav_points_response()["nav_points"]
    if use_current_map:
        current_map = service(request).state.snapshot()["current_map"]
        points = [p for p in points if not p.get("map_file") or p.get("map_file") == current_map]
    return {"points": points, "count": len(points)}


@router.get("/poi/{name}", summary="查询单个 POI")
def poi_get(request: Request, name: str) -> dict:
    """按名称查找本地 POI。"""
    points = service(request).nav_points_response()["nav_points"]
    for point in points:
        if point.get("name") == name:
            return {"found": True, "poi": point}
    return {"found": False, "message": f"poi not found: {name}"}


@router.delete("/poi/{name}", summary="删除 POI")
def poi_delete(request: Request, name: str) -> dict:
    """从本地导航点文件中删除指定名称的 POI。"""
    return service(request).delete_poi(name)


@router.post("/poi/save_current", summary="保存当前位置为 POI")
def poi_save_current(request: Request, body: SaveCurrentPoiRequest) -> dict:
    """读取当前 robot_pose，保存成指定名称的 POI。"""
    return service(request).save_current_poi(body.name, body.map_name, body.tags, body.meta)


@router.post("/poi/upsert", summary="新增或覆盖 POI")
def poi_upsert(request: Request, body: PoiUpsertRequest) -> dict:
    """手动写入一个 POI 坐标，适合批量导入或修正点位。"""
    return service(request).upsert_poi(body.poi.to_nav_point())


@router.get("/routes", summary="查询 route 列表")
def routes(request: Request) -> dict:
    """返回本地 route 数据，route 本质是一组 POI 名称。"""
    return service(request).store.load_routes()


@router.post("/routes/upsert", summary="新增或覆盖 route")
def route_upsert(request: Request, body: RouteUpsertRequest) -> dict:
    """保存 route，后续 patrol/mission 会按 route 中的 POI 顺序执行。"""
    data = service(request).store.load_routes()
    routes_list = [route for route in data.get("routes", []) if route.get("name") != body.route.name]
    routes_list.append(body.route.model_dump())
    data["routes"] = routes_list
    service(request).store.save_routes(data)
    return {"success": True, "route": body.route.model_dump()}


@router.post("/patrol/start", summary="启动巡航路线")
def patrol_start(request: Request, body: PatrolStartRequest) -> dict:
    """根据 route_name 查找路线，把 POI 转成导航点，然后启动 Unitree 风格巡航。"""
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


@router.post("/patrol/stop", summary="停止巡航路线")
def patrol_stop(request: Request) -> dict:
    """停止当前 patrol，并取消底层导航 goal。"""
    return service(request).stop_cruise()


@router.get("/patrol/status", summary="查询巡航状态")
def patrol_status(request: Request) -> dict:
    """返回当前巡航 index、目标、位姿和距离。"""
    return service(request).nav_status()


@router.get("/missions", summary="查询 mission 列表")
def missions(request: Request) -> dict:
    """mission 目前复用 route 存储。"""
    return service(request).store.load_routes()


@router.get("/missions/context", summary="查询 mission 调试上下文")
def missions_context(request: Request) -> dict:
    """一次性返回 status、points、routes，适合现场排查 mission 为什么跑不起来。"""
    return {
        "status": service(request).status(),
        "points": service(request).nav_points_response(),
        "routes": service(request).store.load_routes(),
    }


@router.post("/missions/upsert", summary="新增或覆盖 mission")
def mission_upsert(request: Request, body: RouteUpsertRequest) -> dict:
    """mission 目前和 route 数据结构相同。"""
    return route_upsert(request, body)


@router.post("/missions/start", summary="启动 mission")
def mission_start(request: Request, body: PatrolStartRequest) -> dict:
    """启动 mission，内部复用 patrol 顺序执行器。"""
    return patrol_start(request, body)


@router.post("/missions/stop", summary="停止 mission")
def mission_stop(request: Request) -> dict:
    """停止当前 mission，内部等同于停止 patrol。"""
    return service(request).stop_cruise()


@router.get("/missions/status", summary="查询 mission 状态")
def mission_status(request: Request) -> dict:
    """返回当前 mission/patrol 的执行状态。"""
    return service(request).nav_status()


@router.get("/aurora/ping", summary="检查 Aurora Agent 连通性")
def aurora_ping(request: Request) -> dict:
    """检查 Aurora Agent 是否可用，区别于 HumanoidNav/ROS2 状态。"""
    return service(request).aurora.ping()


@router.get("/aurora/state", summary="查询 Aurora 状态")
def aurora_state(request: Request, force_refresh: bool = Query(default=False)) -> dict:
    """返回缓存的 Aurora FSM、是否站立、是否 mock、Agent 错误信息等。"""
    return service(request).aurora.state(force_refresh=force_refresh)


@router.post("/aurora/fsm", summary="设置 Aurora FSM")
def aurora_fsm(request: Request, body: FsmRequest) -> dict:
    """通过 Aurora Agent 设置 FSM，用于底层动作调试，谨慎使用。"""
    return service(request).aurora.set_fsm(body.fsm_state)


@router.post("/aurora/ensure_stand", summary="确保机器人站立")
def aurora_ensure_stand(request: Request) -> dict:
    """导航前建议调用，让机器人进入站立态。"""
    return service(request).aurora.ensure_stand()


@router.post("/aurora/stop_motion", summary="停止机体运动")
def aurora_stop_motion(request: Request) -> dict:
    """通过 Aurora Agent 调用停止运动能力，常作为导航取消后的安全兜底。"""
    return service(request).aurora.stop_motion()


@router.post("/aurora/reset", summary="重置 Aurora Agent SDK 客户端")
def aurora_reset(request: Request) -> dict:
    """AuroraCore 重启或 DDS 参数修正后调用，清掉 Agent 内部 AuroraClient 和退避状态。"""
    return service(request).aurora.reset()
