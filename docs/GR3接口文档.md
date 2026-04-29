# GR3 适配服务接口文档

默认服务地址：

```plain
http://机器人IP:8080
```

默认命名空间：

```plain
/GR301AA0025
```

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
| `ready_for_navigation` | GR3 扩展字段，是否满足导航预检 |

### GET `/slam/pose`

返回当前位姿，来自 `/GR301AA0025/robot_pose`。

```bash
curl http://127.0.0.1:8080/slam/pose
```

### POST `/slam/start_mapping`

切到建图模式。

```bash
curl -X POST http://127.0.0.1:8080/slam/start_mapping
```

### POST `/slam/stop_mapping`

保存地图。兼容原工程误写的 `/aslam/stop_mapping`。

```bash
curl -X POST http://127.0.0.1:8080/slam/stop_mapping \
  -H "Content-Type: application/json" \
  -d '{"map_path":"/opt/fftai/nav/map"}'
```

### POST `/slam/relocation`

加载地图并进入定位模式。

```bash
curl -X POST http://127.0.0.1:8080/slam/relocation \
  -H "Content-Type: application/json" \
  -d '{"map_path":"/opt/fftai/nav/map","x":0,"y":0,"z":0,"yaw":0,"wait_for_localization":false}'
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

聚合状态，包括 ROS、Aurora Agent 缓存、runtime、readiness。

### GET `/robot/readiness`

查看导航前预检。

### POST `/robot/aurora/ensure_stand`

通过 Aurora Agent 让机器人进入站立态。

### POST `/robot/aurora/stop_motion`

通过 Aurora Agent 停止机体运动。

### POST `/robot/aurora/reset`

重置 Aurora Agent 内部的 `AuroraClient` 和连接退避状态。适用于 AuroraCore 重启、`DomainID`/`RobotName` 修正、容器网络修正后，不想重启主 Adapter 的场景。

### POST `/robot/map/load`

直接按路径加载地图。

```bash
curl -X POST http://127.0.0.1:8080/robot/map/load \
  -H "Content-Type: application/json" \
  -d '{"map_path":"/opt/fftai/nav/map","x":0,"y":0,"yaw":0}'
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
- Aurora ensure_stand / stop_motion。
- SSE 事件查看。
