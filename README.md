# GR3 Robot Adapter

这个工程是 GR3 机器人的 Python 适配服务，目标是对外兼容原 Unitree `keyDemo` 的 HTTP 协议，让背包可以继续调用 `/slam/...`、`/audio/...` 接口；内部桥接 GR3 的 HumanoidNav / ROS2，并通过独立 Aurora Agent 调用底层运动控制。

默认命名空间固定为：

```bash
GR301AA0025
```

## 运行

```bash
cd ~/aurora_ws/gr3 || exit 1

python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements.txt

source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash
python -c "import numpy; import rclpy; print('PY_ROS_IMPORT_OK')"

export AURORA_BACKEND=agent
export AURORA_AGENT_URL=http://127.0.0.1:18080

chmod +x scripts/run_adapter.sh
./scripts/run_adapter.sh
```

Aurora SDK 不在主 Adapter 进程里 import。需要在 Aurora SDK 正确环境或容器里另起一个常驻 Agent：

```bash
cd ~/aurora_ws/gr3 || exit 1
export AURORA_DOMAIN_ID=123
export AURORA_ROBOT_NAME=gr3v233
export AURORA_CLIENT_MODULE=fourier_aurora_client
export AURORA_CLIENT_CLASS=AuroraClient
export AURORA_STAND_FSM_STATE=2

chmod +x scripts/run_aurora_agent.sh
./scripts/run_aurora_agent.sh
```

启动后：

- Web 调试页：`http://<robot-ip>:8080/`
- Swagger：`http://<robot-ip>:8080/docs`
- Unitree 兼容状态：`http://<robot-ip>:8080/slam/status`

## 关键设计

- 外部兼容层：`/slam/...`、`/audio/...`
- 内部调试层：`/robot/...`
- ROS2 桥接：HumanoidNav 的 topic/service/action
- Aurora 桥接：主 Adapter 只调用本地 Aurora Agent；Agent 独立运行在能 import Aurora SDK 且能 DDS 匹配 AuroraCore 的环境里，负责站立、FSM、停止运动和状态缓存
- 本地数据：导航点、巡航文件、runtime 状态

如果 Agent 能 import `fourier_aurora_client`，但日志报 `Timeout waiting for subscribers to be matched`，优先检查 AuroraCore 是否运行、`DomainID`/`RobotName` 是否一致，以及 Agent 和 AuroraCore 是否在同一个容器/DDS 网络里。

详见：

- `docs/GR3适配服务设计.md`
- `docs/AuroraAgent重构说明.md`
- `docs/GR3接口文档.md`
- `docs/GR3逐步调试操作手册.md`
- `docs/GR3端到端逐步测试指南.md`
- `docs/GR3开机建图打点巡航标准流程.md`
