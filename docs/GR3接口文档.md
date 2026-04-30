# GR3 适配服务接口文档

默认服务地址：

```plain
http://机器人IP:8080
```

默认命名空间：

```plain
/GR301AA0025
```

地图保存统一规则：

```plain
MAP_ROOT=/opt/fftai/nav
DEFAULT_MAP_NAME=map
最终路径 = MAP_ROOT / map_name
MAP_SAVE_ID_MODE=name
MAP_LOAD_TIMEOUT_SEC=10
MAP_SAVE_TIMEOUT_SEC=10
```

所有地图接口都优先推荐传 `map_name`。例如 `map`
会解析为机器人现有的 `/opt/fftai/nav/map`。只有需要临时绕过
统一目录时，才传绝对 `map_path`。

## 1. Unitree 兼容接口

### GET `/slam/status`

返回 Unitree 风格状态，背包优先使用这个接口。

```bash
curl http://127.0.0.1:8080/slam/status
```

核心字段：

| 字段 | 说明 |
| --- | --- |
| `status` | 适配服务状态 |
| `is_cruising` | 是否巡航中 |
| `current_nav_index` | 当前巡航点序号，兼容 Unitree，1 起始 |
| `total_nav_points` | 巡航点总数 |
| `is_arrived` | 最近目标是否到达 |
| `map_file` | 当前地图路径 |
| `status_code` | 最近一次底层调用状态 |
| `ready_for_mapping` | 建图模式是否满足手动建图条件 |
| `ready_for_poi` | 定位后是否满足手动打点条件 |
| `ready_for_navigation` | GR3 扩展字段，是否满足导航预检 |
| `motion_authority` | 当前运动策略和控制权说明 |

### GET `/slam/pose`

返回当前位姿，来自 `/GR301AA0025/robot_pose`。

```bash
curl http://127.0.0.1:8080/slam/pose
```

### POST `/slam/start_mapping`

切到建图模式。可选传入本次建图的保存目标；开始建图时不会写文件，
Adapter 只是先记录这个目标，真正落盘发生在 `/slam/stop_mapping`。

```bash
curl -X POST http://127.0.0.1:8080/slam/start_mapping \
  -H "Content-Type: application/json" \
  -d '{"map_name":"map"}'
```

如果不传 `map_name` 或 `map_path`，停止建图时会使用当前记录的地图路径或
`DEFAULT_MAP_PATH`。

### POST `/slam/stop_mapping`

保存地图。兼容原工程误写的 `/aslam/stop_mapping`。底层调用
`/GR301AA0025/slam/save_map`，请求字段是 `map_id`。默认 `MAP_SAVE_ID_MODE=name`，
因此传 `map_name=map` 时底层收到的 `map_id` 是 `map`，而不是
`/opt/fftai/nav/map`；如果现场确认 HumanoidNav 必须吃绝对路径，可以改成
`MAP_SAVE_ID_MODE=path`。
Adapter 默认等待 `MAP_SAVE_TIMEOUT_SEC=10` 秒；超过 10 秒直接按底层超时处理。

```bash
curl -X POST http://127.0.0.1:8080/slam/stop_mapping \
  -H "Content-Type: application/json" \
  -d '{"map_name":"map"}'
```

### POST `/slam/relocation`

加载地图并进入定位模式。

```bash
curl -X POST http://127.0.0.1:8080/slam/relocation \
  -H "Content-Type: application/json" \
  -d '{"map_name":"map","x":0,"y":0,"z":0,"yaw":0,"wait_for_localization":false}'
```

### POST `/slam/add_nav_point`

保存当前位置为导航点。

```bash
curl -X POST http://127.0.0.1:8080/slam/add_nav_point \
  -H "Content-Type: application/json" \
  -d '{"name":"front_desk"}'
```

### GET `/slam/nav_points`

查看导航点。

```bash
curl http://127.0.0.1:8080/slam/nav_points
```

### POST `/slam/navigate_to`

按坐标导航。

```bash
curl -X POST http://127.0.0.1:8080/slam/navigate_to \
  -H "Content-Type: application/json" \
  -d '{"name":"desk","x":1.0,"y":2.0,"yaw":0.0}'
```

也支持四元数：

```json
{
  "name": "desk",
  "x": 1.0,
  "y": 2.0,
  "z": 0.0,
  "q_x": 0.0,
  "q_y": 0.0,
  "q_z": 0.0,
  "q_w": 1.0
}
```

### POST `/slam/start_cruise`

按本地导航点顺序巡航。

```bash
curl -X POST http://127.0.0.1:8080/slam/start_cruise
```

### POST `/slam/start_show_cruise`

按名称加载巡航文件并巡航。默认查找：

- `data/show_cruises/{name}.json`
- `data/{name}.json`
- `/home/unitree/testdata/{name}.json`

```bash
curl -X POST http://127.0.0.1:8080/slam/start_show_cruise \
  -H "Content-Type: application/json" \
  -d '{"name":"demo_route"}'
```

### POST `/slam/stop_cruise`

停止巡航，并取消当前导航。

```bash
curl -X POST http://127.0.0.1:8080/slam/stop_cruise
```

### POST `/slam/pause_nav`

暂停导航。GR3 当前实现是取消当前 goal，并保留巡航 index。

```bash
curl -X POST http://127.0.0.1:8080/slam/pause_nav
```

### POST `/slam/resume_nav`

恢复巡航线程。

```bash
curl -X POST http://127.0.0.1:8080/slam/resume_nav
```

### GET `/slam/nav_status`

轮询导航状态。

```bash
curl http://127.0.0.1:8080/slam/nav_status
```

### GET `/slam/events`

SSE 事件流。

```bash
curl -N http://127.0.0.1:8080/slam/events
```

事件类型：

| event_type | 说明 |
| --- | --- |
| `position_update` | 位置更新 |
| `cruise_start` | 巡航开始 |
| `nav_start` | 单点导航开始 |
| `nav_arrival` | 到达导航点 |
| `nav_failed` | 导航失败 |
| `cruise_stop` | 巡航停止 |
| `cruise_complete` | 巡航完成 |

### POST `/audio/play_wav`

兼容上传接口，当前保存文件但不实际播放。

```bash
curl -X POST http://127.0.0.1:8080/audio/play_wav \
  -F "wavfile=@test.wav"
```

### POST `/audio/talk_text`

兼容文本朗读接口，当前为 no-op。

```bash
curl -X POST http://127.0.0.1:8080/audio/talk_text \
  -H "Content-Type: application/json" \
  -d '{"text":"hello"}'
```

## 2. GR3 调试接口

### GET `/healthz`

检查适配服务是否启动。

### GET `/robot/status`

聚合状态，包括 ROS、可选 Aurora 缓存、runtime、三类 readiness、运动控制策略。

返回里包含 `map_config`，用于确认当前统一地图配置：

```json
{
  "map_root": "/opt/fftai/nav",
  "default_map_name": "map",
  "default_map_path": "/opt/fftai/nav/map",
  "current_map": "/opt/fftai/nav/map",
  "save_id_mode": "name"
}
```

### GET `/robot/readiness`

查看自动导航前预检。只有 `MOTION_GUARD=aurora` 或 `REQUIRE_AURORA=1` 时，Aurora 才会成为 blocker。

### GET `/robot/workflow/status`

一次返回三套流程状态：

- `manual_mapping`：手动建图就绪。
- `manual_poi`：手动打点就绪。
- `auto_navigation`：自动导航就绪。
- `motion_authority`：当前运动控制策略。

```bash
curl http://127.0.0.1:8080/robot/workflow/status
```

### GET `/robot/readiness/mapping`

建图前检查。只检查 ROS、mapping 模式、位姿新鲜度、HumanoidNav health，不检查 Aurora。

```bash
curl http://127.0.0.1:8080/robot/readiness/mapping
```

### GET `/robot/readiness/poi`

手动打点前检查。要求地图已加载、定位 GOOD、位姿新鲜，不检查 Aurora。

```bash
curl http://127.0.0.1:8080/robot/readiness/poi
```

### GET `/robot/readiness/navigation`

自动导航前检查，等价于新版语义下的 `/robot/readiness`。

```bash
curl http://127.0.0.1:8080/robot/readiness/navigation
```

### GET `/robot/motion/authority`

查看运动控制权策略。

```bash
curl http://127.0.0.1:8080/robot/motion/authority
```

默认应看到：

```plain
policy=none
aurora_required=false
manual_mapping_motion=remote_or_joystick
manual_poi_motion=remote_or_joystick
auto_navigation_motion=nav2_goal
```

### POST `/robot/motion/safety_stop`

取消当前导航。默认 `MOTION_GUARD=none` 时只取消 Nav2 goal；`MOTION_GUARD=aurora` 时额外调用 Aurora `stop_motion`。

### POST `/robot/aurora/ensure_stand`

通过 Aurora Agent 让机器人进入站立态。默认手动建图/打点流程不需要调用。

### POST `/robot/aurora/stop_motion`

通过 Aurora Agent 停止机体运动。默认手动建图/打点流程不需要调用。

### POST `/robot/aurora/reset`

重置 Aurora Agent 内部的 `AuroraClient` 和连接退避状态。适用于 AuroraCore 重启、`DomainID`/`RobotName` 修正、容器网络修正后，不想重启主 Adapter 的场景。

### POST `/robot/map/load`

加载地图。推荐传 `map_name`，也兼容绝对 `map_path`。
底层调用 `/GR301AA0025/slam/load_map`，Adapter 默认等待
`MAP_LOAD_TIMEOUT_SEC=10` 秒；如果底层返回 `result != 0`，Adapter 会把它归一化为失败响应。

```bash
curl -X POST http://127.0.0.1:8080/robot/map/load \
  -H "Content-Type: application/json" \
  -d '{"map_name":"map","x":0,"y":0,"yaw":0}'
```

### GET `/robot/localization/status`

只查看定位链路状态。

### POST `/robot/navigation/goto_pose`

调试用坐标导航。

```bash
curl -X POST http://127.0.0.1:8080/robot/navigation/goto_pose \
  -H "Content-Type: application/json" \
  -d '{"pose":{"x":1,"y":2,"yaw":0},"label":"debug"}'
```

## 3. Web 调试页面

打开：

```plain
http://机器人IP:8080/
```

页面提供：

- 状态 / readiness 查看。
- 地图加载。
- 保存当前位置为导航点。
- 开始 / 暂停 / 恢复 / 停止巡航。
- 按坐标导航。
- 可选 Aurora ensure_stand / stop_motion。
- SSE 事件查看。
