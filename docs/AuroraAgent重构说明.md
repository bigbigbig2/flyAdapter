# Aurora Agent 重构说明

## 目标

主 `GR3 Adapter` 不再直接 import Aurora SDK。Adapter 只负责 HTTP 兼容协议、HumanoidNav/ROS2 导航、状态聚合和 readiness；Aurora SDK 由独立常驻进程 `Aurora Agent` 持有。

## 进程边界

```plain
GR3 Adapter
  - FastAPI: /slam/... /robot/...
  - rclpy: HumanoidNav topic/service/action
  - AuroraBridge: 只调用 Aurora Agent

Aurora Agent
  - FastAPI: /health /state /fsm /ensure_stand /stop_motion
  - AuroraSdkRuntime: 负责 import、get_instance、退避重连、状态缓存
  - AuroraClient: get_instance 后长期复用，只使用官方 SDK API
  - 后台轮询 FSM/standing 状态；DDS 未就绪时退避，不重复刷爆初始化
```

## 性能策略

- `/slam/status`、`/robot/status`、`/robot/readiness` 只读内存缓存，不 import SDK，不 `docker exec`，不阻塞底层 DDS。
- Adapter 后台按 `AURORA_POLL_INTERVAL_SEC` 轮询 Agent `/state`。
- `ensure_stand`、`set_fsm`、`stop_motion` 才短超时调用 Agent。
- Adapter 对 Agent 调用有超时和熔断，Agent 异常时不会拖垮背包接口。
- Agent 内部使用命令锁串行化 FSM/速度控制命令。
- Agent 连接 AuroraCore 失败时做指数退避，返回 `connect_retry_after_sec` 和 `last_connect_error`，不再每秒反复 `get_instance()`。

## 官方 API 对齐

Agent 对 Aurora SDK 的调用只集中在 `app/aurora_sdk_runtime.py`：

- 建立连接：`AuroraClient.get_instance(domain_id=..., robot_name=..., namespace=None, is_ros_compatible=False)`。
- 状态读取：优先使用 `get_fsm_state()`、`get_fsm_name()`、`get_velocity_source()`、`get_velocity_source_name()`。
- 站立：`set_fsm_state(AURORA_STAND_FSM_STATE)`。
- 停止运动：先 `set_velocity_source(2)`，再 `set_velocity(0, 0, 0)`。

`app/aurora_agent.py` 只保留 FastAPI 路由，不再承担 SDK 生命周期逻辑。主 Adapter 的 `AuroraBridge` 只通过 HTTP 调 Agent，不 import Aurora SDK。

## 启动

Aurora Agent 在 SDK 环境里启动：

```bash
cd ~/aurora_ws/gr3 || exit 1
export AURORA_DOMAIN_ID=123
export AURORA_ROBOT_NAME=gr3v233
export AURORA_CLIENT_MODULE=fourier_aurora_client
export AURORA_CLIENT_CLASS=AuroraClient
export AURORA_STAND_FSM_STATE=2
./scripts/run_aurora_agent.sh
```

GR3 Adapter 在 HumanoidNav/ROS2 环境里启动：

```bash
cd ~/aurora_ws/gr3 || exit 1
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash
export ROBOT_NAMESPACE=GR301AA0025
export AURORA_BACKEND=agent
export AURORA_AGENT_URL=http://127.0.0.1:18080
./scripts/run_adapter.sh
```

## 排查

```bash
curl http://127.0.0.1:18080/health
curl http://127.0.0.1:18080/state
curl http://127.0.0.1:18080/diagnostics
curl http://127.0.0.1:8080/robot/aurora/state
curl http://127.0.0.1:8080/robot/readiness
```

如果 Agent 提示缺少 `fourier_msgs.msg.AuroraCmd`，说明 Agent 所在环境不是完整 Aurora SDK 环境；此时不要改主 Adapter，应该把 Agent 移到正确环境或容器里运行。

`scripts/run_aurora_agent.sh` 默认会执行 `AURORA_ENV_CLEAN=1`，自动从 `PYTHONPATH`、`AMENT_PREFIX_PATH`、`LD_LIBRARY_PATH` 等变量里移除 `humanoidnav` 路径，防止导航版 `fourier_msgs` 覆盖 Aurora SDK 消息。`/health` 响应里的 `module_diagnostics` 会显示 `fourier_msgs` 和 `AuroraCmd` 的实际加载位置。

如果 `fourier_msgs.msg.AuroraCmd` 已经能找到，但日志出现 `Timeout waiting for subscribers to be matched` 和一组 `Unmatched subscriber: rt/...`，说明 Python SDK 已经加载成功，失败点是 DDS 没匹配到 AuroraCore。优先检查 AuroraCore 是否真的运行、`DomainID` 和 `RobotName` 是否与 Agent 环境变量一致、Agent 与 AuroraCore 是否在同一个容器/DDS 网络里。

修正 AuroraCore 或 DDS 参数后可调用：

```bash
curl -X POST http://127.0.0.1:8080/robot/aurora/reset
curl http://127.0.0.1:8080/robot/aurora/state?force_refresh=true
```
