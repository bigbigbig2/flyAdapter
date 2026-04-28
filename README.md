# GR3 Robot Adapter

这个工程是 GR3 机器人的 Python 适配服务，目标是对外兼容原 Unitree `keyDemo` 的 HTTP 协议，让背包可以继续调用 `/slam/...`、`/audio/...` 接口；内部再桥接到 GR3 的 HumanoidNav / ROS2 和 Aurora SDK。

默认命名空间固定为：

```bash
GR301AA0025
```

## 运行

```bash
cd ~/aurora_ws/gr3

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash
python -c "import numpy; import rclpy; print('PY_ROS_IMPORT_OK')"

export AURORA_BACKEND=docker
export AURORA_CONTAINER_NAME=fourier_aurora_server
export AURORA_DOMAIN_ID=123
export AURORA_CLIENT_MODULE=fourier_aurora_client

chmod +x scripts/run_adapter.sh
./scripts/run_adapter.sh
```

启动后：

- Web 调试页：`http://<robot-ip>:8080/`
- Swagger：`http://<robot-ip>:8080/docs`
- Unitree 兼容状态：`http://<robot-ip>:8080/slam/status`

## 关键设计

- 外部兼容层：`/slam/...`、`/audio/...`
- 内部调试层：`/robot/...`
- ROS2 桥接：HumanoidNav 的 topic/service/action
- Aurora 桥接：站立、FSM、停止运动等底层状态和安全动作
- 本地数据：导航点、巡航文件、runtime 状态

详见：

- `docs/GR3适配服务设计.md`
- `docs/GR3接口文档.md`
- `docs/GR3逐步调试操作手册.md`
