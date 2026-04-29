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
  - AuroraClient: get_instance 后长期复用
  - 后台轮询 FSM/standing 状态
```

## 性能策略

- `/slam/status`、`/robot/status`、`/robot/readiness` 只读内存缓存，不 import SDK，不 `docker exec`，不阻塞底层 DDS。
- Adapter 后台按 `AURORA_POLL_INTERVAL_SEC` 轮询 Agent `/state`。
- `ensure_stand`、`set_fsm`、`stop_motion` 才短超时调用 Agent。
- Adapter 对 Agent 调用有超时和熔断，Agent 异常时不会拖垮背包接口。
- Agent 内部使用命令锁串行化 FSM/速度控制命令。

## 启动

Aurora Agent 在 SDK 环境里启动：

```bash
cd ~/aurora_ws/gr3
export AURORA_DOMAIN_ID=123
export AURORA_ROBOT_NAME=gr3v233
export AURORA_CLIENT_MODULE=fourier_aurora_client
export AURORA_CLIENT_CLASS=AuroraClient
export AURORA_STAND_FSM_STATE=2
./scripts/run_aurora_agent.sh
```

GR3 Adapter 在 HumanoidNav/ROS2 环境里启动：

```bash
cd ~/aurora_ws/gr3
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
curl http://127.0.0.1:8080/robot/aurora/state
curl http://127.0.0.1:8080/robot/readiness
```

如果 Agent 提示缺少 `fourier_msgs.msg.AuroraCmd`，说明 Agent 所在环境不是完整 Aurora SDK 环境；此时不要改主 Adapter，应该把 Agent 移到正确环境或容器里运行。

`scripts/run_aurora_agent.sh` 默认会执行 `AURORA_ENV_CLEAN=1`，自动从 `PYTHONPATH`、`AMENT_PREFIX_PATH`、`LD_LIBRARY_PATH` 等变量里移除 `humanoidnav` 路径，防止导航版 `fourier_msgs` 覆盖 Aurora SDK 消息。`/health` 响应里的 `module_diagnostics` 会显示 `fourier_msgs` 和 `AuroraCmd` 的实际加载位置。
