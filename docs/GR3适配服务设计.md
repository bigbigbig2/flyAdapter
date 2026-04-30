# GR3 机器人适配服务设计

## 1. 目标

GR3 Adapter 的目标是让 GR3 对外兼容原 Unitree 机器人适配服务，背包继续调用 `/slam/...`、`/audio/...`、SSE 等接口；内部由 Adapter 翻译到 HumanoidNav / ROS2。

固定命名空间：

```plain
/GR301AA0025
```

核心原则：

```plain
建图和手动打点：遥控器/手柄控制机器人运动，Adapter 不碰机体运动控制。
自动导航和巡航：Adapter 向 HumanoidNav/Nav2 发送目标点。
Aurora：默认关闭，只作为可选诊断或自动导航保护链路。
```

这个设计是为了避免把遥控器控制、AuroraCore、SLAM 建图、Nav2 目标点导航混在同一条强依赖链路里。遥控器接管时 AuroraCore 可能断开，这不应该影响建图和手动打点。

---

## 2. 总体结构

```plain
背包 / 调试 Web
  |
  | HTTP / SSE
  v
GR3 Adapter (FastAPI)
  |
  +-- Unitree-compatible API
  |   +-- /slam/status
  |   +-- /slam/start_mapping
  |   +-- /slam/stop_mapping
  |   +-- /slam/relocation
  |   +-- /slam/add_nav_point
  |   +-- /slam/start_cruise
  |   +-- /slam/stop_cruise
  |   +-- /audio/...
  |
  +-- GR3 debug API
  |   +-- /robot/status
  |   +-- /robot/workflow/status
  |   +-- /robot/readiness/mapping
  |   +-- /robot/readiness/poi
  |   +-- /robot/readiness/navigation
  |   +-- /robot/motion/authority
  |
  +-- RobotService
      |
      +-- RosBridge / HumanoidNav
      |   +-- /GR301AA0025/slam/set_mode
      |   +-- /GR301AA0025/slam/load_map
      |   +-- /GR301AA0025/slam/save_map
      |   +-- /GR301AA0025/navigate_to_pose
      |   +-- /GR301AA0025/cancel_current_action
      |   +-- /GR301AA0025/robot_pose
      |   +-- /GR301AA0025/odom_status_code
      |   +-- /GR301AA0025/Humanoid_nav/health
      |
      +-- AuroraBridge (optional)
      |   +-- disabled by default
      |   +-- observe mode: state only
      |   +-- aurora mode: ensure_stand / stop_motion
      |
      +-- JsonStore
          +-- navigation_points.json
          +-- runtime.json
          +-- routes.json
```

Aurora Agent 是独立可选进程：

```plain
GR3 Adapter
  |
  | localhost HTTP, short timeout
  v
Aurora Agent
  |
  | in-process AuroraClient
  v
Aurora SDK / AuroraCore / DDS
```

主 Adapter 不直接 import Aurora SDK，避免 DDS、消息包、容器环境把主服务拖垮。

---

## 3. 运动控制策略

通过 `MOTION_GUARD` 决定 Adapter 是否使用 Aurora。

| 策略 | 默认 | 行为 |
| --- | --- | --- |
| `none` | 是 | 不启动 Aurora 轮询，不调用 Aurora 命令。建图/打点靠遥控器，导航/巡航靠 Nav2 goal。 |
| `observe` | 否 | 只读取 Aurora Agent 状态用于诊断，不调用运动命令。 |
| `aurora` | 否 | 自动导航前调用 `ensure_stand`，取消导航/停止巡航时调用 `stop_motion`。 |

推荐默认配置：

```bash
export MOTION_GUARD=none
export AURORA_ENABLED=0
export REQUIRE_AURORA=0
```

需要 Aurora 自动导航保护时：

```bash
export MOTION_GUARD=aurora
export AURORA_ENABLED=1
export AURORA_BACKEND=agent
export AURORA_AGENT_URL=http://127.0.0.1:18080
```

`REQUIRE_AURORA=1` 兼容旧语义，等价于把 Aurora 作为导航 blocker。新部署优先使用 `MOTION_GUARD=aurora` 表达意图。

---

## 4. 三套 readiness

不要再用一个 readiness 判断所有阶段。当前工程拆成三类：

### 4.1 手动建图 readiness

接口：

```plain
GET /robot/readiness/mapping
```

检查项：

- ROS2 Python 可用。
- RosBridge ready。
- 当前是 mapping 模式。
- `/robot_pose` 新鲜。
- HumanoidNav health 无 error/fatal。

不检查：

- Aurora 是否连接。
- 机器人是否通过 Aurora 站立。
- `odom_status_code` 是否等于 2。

建图模式下 `odom_status_code=null` 可以是正常状态。

### 4.2 手动打点 readiness

接口：

```plain
GET /robot/readiness/poi
```

检查项：

- 地图已加载。
- `/robot_pose` 新鲜。
- `odom_status_code=2`。
- HumanoidNav health 无 error/fatal。

不检查 Aurora。因为打点阶段仍然由遥控器移动机器人，Adapter 只读当前位姿。

### 4.3 自动导航 readiness

接口：

```plain
GET /robot/readiness/navigation
GET /robot/readiness
```

检查项：

- 地图已加载。
- 定位 GOOD。
- 位姿新鲜。
- health 正常。
- 没有正在运行的导航任务。
- 只有 `MOTION_GUARD=aurora` 或 `REQUIRE_AURORA=1` 时，才检查 Aurora connected / standing。

---

## 5. Unitree 兼容映射

| Unitree 语义 | GR3 实现 |
| --- | --- |
| 当前位姿 | 订阅 `/GR301AA0025/robot_pose` |
| 定位状态 | 订阅 `/GR301AA0025/odom_status_code` 和 `/GR301AA0025/odom_status_score` |
| 开始建图 | 调 `/GR301AA0025/slam/set_mode`，mode=`mapping` |
| 停止建图并保存 | 调 `/GR301AA0025/slam/save_map` |
| 加载地图重定位 | 调 `/GR301AA0025/slam/load_map` |
| 添加导航点 | 读取当前 `robot_pose` 并写入 `navigation_points.json` |
| 单点导航 | 调 `/GR301AA0025/navigate_to_pose` action |
| 停止导航 | 调 `/GR301AA0025/cancel_current_action`；仅 aurora 策略下补充 `stop_motion` |
| 巡航 | 适配层顺序发送多个 `navigate_to_pose` goal |
| 事件流 | 适配层 SSE 广播 Unitree 风格事件 |
| 音频接口 | 先保留兼容 no-op / 上传入口 |

---

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

地图路径统一规则：

```plain
MAP_ROOT=/opt/fftai/nav
DEFAULT_MAP_NAME=map
map_name=map -> /opt/fftai/nav/map
MAP_SAVE_ID_MODE=name
MAP_LOAD_TIMEOUT_SEC=10
MAP_SAVE_TIMEOUT_SEC=10
```

API 优先使用 `map_name`，Adapter 统一解析成绝对路径后再传给
HumanoidNav 的 `LoadMap.map_path`。保存时默认把 `map_name` 作为
`SaveMap.map_id`，避免把 `/opt/fftai/nav/map` 这种既是现有地图目录又是保存目标
的路径直接交给底层删除重建。只有现场确认必须传绝对路径时，才把
`MAP_SAVE_ID_MODE` 改为 `path`。

`navigation_points.json` 格式：

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
      "name": "lobby_01_start",
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

---

## 7. 启动顺序

默认流程：

1. 启动 HumanoidNav。
2. 启动 GR3 Adapter，使用 `MOTION_GUARD=none`。
3. 打开 RViz。
4. 建图、保存地图、定位、手动打点。
5. 单点自动导航验证。
6. 多点巡航。

默认 Adapter 启动：

```bash
cd ~/aurora_ws/flyAdapter || exit 1
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash
source .venv/bin/activate

export ROBOT_NAMESPACE=GR301AA0025
export MOTION_GUARD=none
export AURORA_ENABLED=0

./scripts/run_adapter.sh
```

可选 Aurora Agent 启动：

```bash
cd ~/aurora_ws/flyAdapter || exit 1
export AURORA_DOMAIN_ID=123
export AURORA_ROBOT_NAME=gr3v233
export AURORA_CLIENT_MODULE=fourier_aurora_client
export AURORA_CLIENT_CLASS=AuroraClient
export AURORA_STAND_FSM_STATE=2

./scripts/run_aurora_agent.sh
```

---

## 8. 性能和稳定性考虑

- 主 Adapter 不 import Aurora SDK，避免 SDK/DDS 初始化阻塞 HTTP 服务。
- Aurora 默认 disabled，避免遥控器接管或 AuroraCore 状态影响建图链路。
- ROS topic 订阅结果写入 `RuntimeState`，HTTP 状态接口只读内存快照。
- Aurora Agent 只在 `observe/aurora` 策略下启动轮询。
- Aurora 命令有短超时、串行锁、熔断；但默认不参与手动流程。
- 巡航线程只维护点位顺序，底层运动由 HumanoidNav/Nav2 action 执行。
- `/robot/workflow/status` 一次返回三类 readiness，便于 Web UI 和现场验收直接判断当前阶段。

---

## 9. 调试入口

常用接口：

```bash
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/slam/status
curl http://127.0.0.1:8080/robot/status
curl http://127.0.0.1:8080/robot/workflow/status
curl http://127.0.0.1:8080/robot/readiness/mapping
curl http://127.0.0.1:8080/robot/readiness/poi
curl http://127.0.0.1:8080/robot/readiness/navigation
curl http://127.0.0.1:8080/robot/motion/authority
```

Web：

```plain
http://127.0.0.1:8080/
http://127.0.0.1:8080/docs
```
