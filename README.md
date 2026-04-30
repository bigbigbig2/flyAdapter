# GR3 Robot Adapter

这个工程是 GR3 机器人的 Python 适配服务，目标是对外兼容原 Unitree `keyDemo` 的 HTTP 协议，让背包可以继续调用 `/slam/...`、`/audio/...` 接口；内部桥接 GR3 的 HumanoidNav / ROS2。

当前默认架构已经把“建图/打点的手动运动控制”和“自动导航目标点控制”拆开：建图、打点阶段由遥控器/手柄控制机器人行走；适配服务只管 SLAM、地图、位姿和点位。Aurora 默认关闭，只在 `MOTION_GUARD=observe` 或 `MOTION_GUARD=aurora` 时作为诊断/自动导航保护链路启用。

默认命名空间固定为：

```bash
GR301AA0025
```

## 运行

```bash
cd ~/aurora_ws/flyAdapter || exit 1

python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements.txt

source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash
python -c "import numpy; import rclpy; print('PY_ROS_IMPORT_OK')"

export MOTION_GUARD=none
export AURORA_ENABLED=0
export MAP_ROOT=/opt/fftai/nav
export DEFAULT_MAP_NAME=map
export MAP_SAVE_ID_MODE=name
export MAP_LOAD_TIMEOUT_SEC=10
export MAP_SAVE_TIMEOUT_SEC=10

chmod +x scripts/run_adapter.sh
./scripts/run_adapter.sh
```

Aurora SDK 不在主 Adapter 进程里 import。只有需要 Aurora 诊断或自动导航保护时，才在 Aurora SDK 正确环境或容器里另起一个常驻 Agent：

```bash
cd ~/aurora_ws/flyAdapter || exit 1
export AURORA_DOMAIN_ID=123
export AURORA_ROBOT_NAME=gr3v233
export AURORA_CLIENT_MODULE=fourier_aurora_client
export AURORA_CLIENT_CLASS=AuroraClient
export AURORA_STAND_FSM_STATE=2

chmod +x scripts/run_aurora_agent.sh
./scripts/run_aurora_agent.sh
```

启用 Aurora 自动导航保护时，Adapter 需要额外配置：

```bash
export MOTION_GUARD=aurora
export AURORA_ENABLED=1
export AURORA_BACKEND=agent
export AURORA_AGENT_URL=http://127.0.0.1:18080
```

启动后：

- Web 调试页：`http://<robot-ip>:8080/`
- Swagger：`http://<robot-ip>:8080/docs`
- Unitree 兼容状态：`http://<robot-ip>:8080/slam/status`

## 关键设计

- 外部兼容层：`/slam/...`、`/audio/...`
- 内部调试层：`/robot/...`
- ROS2 桥接：HumanoidNav 的 topic/service/action
- 运动控制策略：默认 `MOTION_GUARD=none`，建图/打点由遥控器控制，自动导航由 Nav2 goal 控制
- 地图命名：统一使用 `map_name`，保存/加载路径解析为 `MAP_ROOT/map_name`；默认 `map_name=map` 对应机器人现有 `/opt/fftai/nav/map`，只有临时绕过统一目录时才传绝对 `map_path`
- Aurora 桥接：可选。主 Adapter 只调用本地 Aurora Agent；Agent 独立运行在能 import Aurora SDK 且能 DDS 匹配 AuroraCore 的环境里
- 本地数据：导航点、巡航文件、runtime 状态

如果 Agent 能 import `fourier_aurora_client`，但日志报 `Timeout waiting for subscribers to be matched`，说明 AuroraCore / DDS 没匹配。默认手动建图和手动打点不依赖它；只有启用 `MOTION_GUARD=aurora` 时才需要优先检查 AuroraCore、`DomainID`/`RobotName` 和容器/DDS 网络。

详见：

- `docs/GR3适配服务设计.md`
- `docs/AuroraAgent重构说明.md`
- `docs/GR3接口文档.md`
- `docs/GR3逐步调试操作手册.md`
- `docs/GR3端到端逐步测试指南.md`
- `docs/GR3开机建图打点巡航标准流程.md`
- `rviz/README.md`
