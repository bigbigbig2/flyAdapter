# GR3 机器人适配服务设计

## 1. 目标

这个工程的目标不是重新定义一套背包协议，而是让 GR3 对外表现得像原来的 Unitree 适配服务。背包继续调用 `/slam/...` 和 `/audio/...`，GR3 适配层内部把这些调用翻译到 HumanoidNav / ROS2 和 Aurora SDK。

固定命名空间：

```plain
/GR301AA0025
```

启动 HumanoidNav、load_map、RViz 和本适配服务时都必须保持这个命名空间一致。

## 2. 总体结构

```plain
背包
  |
  | HTTP / SSE
  v
GR3 Adapter
  |
  | Unitree-compatible API: /slam/... /audio/...
  |
  +-- CompatibilityService
  |
  +-- RobotService
      |
      +-- HumanoidNavBridge
      |   +-- /GR301AA0025/slam/set_mode
      |   +-- /GR301AA0025/slam/load_map
      |   +-- /GR301AA0025/slam/save_map
      |   +-- /GR301AA0025/navigate_to_pose
      |   +-- /GR301AA0025/robot_pose
      |   +-- /GR301AA0025/odom_status_code
      |   +-- /GR301AA0025/Humanoid_nav/health
      |
      +-- AuroraBridge
      |   +-- FSM 状态
      |   +-- ensure_stand
      |   +-- stop_motion
      |
      +-- JsonStore
          +-- navigation_points.json
          +-- runtime.json
          +-- routes.json
```

## 3. 为什么外层要兼容 Unitree

原 Unitree 工程实际暴露的是 HTTP 服务：

- `GET /slam/status`
- `GET /slam/pose`
- `POST /slam/start_mapping`
- `POST /slam/stop_mapping`
- `POST /slam/relocation`
- `POST /slam/add_nav_point`
- `GET /slam/nav_points`
- `POST /slam/start_cruise`
- `POST /slam/start_show_cruise`
- `POST /slam/stop_cruise`
- `POST /slam/pause_nav`
- `POST /slam/resume_nav`
- `POST /slam/navigate_to`
- `GET /slam/events`
- `GET /slam/nav_status`

背包很可能已经按这些路径和字段做了集成。因此 GR3 工程优先保证这些接口可用；`/robot/...` 只是调试和内部能力层。

## 4. 核心映射

| Unitree 语义 | GR3 实现 |
| --- | --- |
| 当前位姿 | 订阅 `/GR301AA0025/robot_pose` |
| 定位状态 | 订阅 `/GR301AA0025/odom_status_code` 和 `/GR301AA0025/odom_status_score` |
| 开始建图 | 调 `/GR301AA0025/slam/set_mode`，mode=`mapping` |
| 加载地图重定位 | 调 `/GR301AA0025/slam/load_map` |
| 保存地图 | 调 `/GR301AA0025/slam/save_map` |
| 单点导航 | 调 `/GR301AA0025/navigate_to_pose` action |
| 停止导航 | 调 `/GR301AA0025/cancel_current_action`，并调用 Aurora stop_motion 兜底 |
| 巡航 | 适配层顺序发送多个 `navigate_to_pose` goal |
| 事件流 | 适配层 SSE 广播 Unitree 风格事件 |
| 站立检查 | Aurora SDK / FSM |

## 5. 导航前预检

GR3 是人形机器人，适配层必须在导航前做安全检查：

1. ROS2 Python 环境是否可用。
2. HumanoidNav bridge 是否 ready。
3. 地图是否加载。
4. `/robot_pose` 是否新鲜。
5. `/odom_status_code` 是否等于 `2`，即 GOOD。
6. `/Humanoid_nav/health` 是否无 error/fatal。
7. Aurora 是否连接。
8. 机器人是否站立。

Aurora SDK 按现场文档默认走容器后端：

```bash
export AURORA_BACKEND=docker
export AURORA_CONTAINER_NAME=fourier_aurora_server
```

默认 `REQUIRE_AURORA=0`，便于 Aurora 容器权限或 SDK 模块名还没确认时先调 HTTP 和 ROS；真机安全部署时建议在 Aurora 后端连通后改成：

```bash
export REQUIRE_AURORA=1
```

## 6. 数据文件

默认数据目录：

```plain
gr3/data
```

主要文件：

- `navigation_points.json`：Unitree 风格导航点文件。
- `runtime.json`：当前地图等运行态信息。
- `routes.json`：route / mission 数据。
- `show_cruises/*.json`：`/slam/start_show_cruise` 使用的巡航文件。

`navigation_points.json` 兼容 Unitree 格式：

```json
{
  "map_file": "/opt/fftai/nav/map",
  "initial_pose": {
    "x": 0,
    "y": 0,
    "z": 0,
    "q_x": 0,
    "q_y": 0,
    "q_z": 0,
    "q_w": 1
  },
  "navigation_points": [
    {
      "name": "front_desk",
      "x": 1.0,
      "y": 2.0,
      "z": 0.0,
      "q_x": 0,
      "q_y": 0,
      "q_z": 0,
      "q_w": 1
    }
  ]
}
```

## 7. 启动顺序

建议真机顺序：

1. 启动 AuroraCore。
2. 启动 HumanoidNav：

```bash
cd /opt/fftai/humanoidnav
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash

./scripts/run_real.sh \
  --unified-init mapping \
  --sensor-type airy \
  --disable-ddscmd \
  --no-rviz \
  --namespace GR301AA0025
```

3. 启动适配服务：

```bash
cd ~/aurora_ws/gr3
source .venv/bin/activate
pip install -r requirements.txt
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash
python -c "import numpy; import rclpy; print('PY_ROS_IMPORT_OK')"
export ROBOT_NAMESPACE=GR301AA0025
./scripts/run_adapter.sh
```

4. 加载地图：

```bash
cd /opt/fftai/humanoidnav
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash

./scripts/load_map.sh \
  --map-path /opt/fftai/nav/map \
  --namespace GR301AA0025
```

也可以通过本适配服务调用：

```bash
curl -X POST http://127.0.0.1:8080/slam/relocation \
  -H "Content-Type: application/json" \
  -d '{"map_path":"/opt/fftai/nav/map","x":0,"y":0,"yaw":0}'
```

## 8. Web 调试页

启动后打开：

```plain
http://机器人IP:8080/
```

这个页面会同时检查：

- `/robot/status`
- `/robot/readiness`
- `/slam/nav_points`
- `/slam/events`

用于确认背包兼容接口和 GR3 内部状态是否一致。
