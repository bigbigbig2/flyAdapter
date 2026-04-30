# GR3 纯 ROS2 地图建图保存加载测试

本文档用于绕过 GR3 Adapter，直接调用 HumanoidNav 的 ROS2 service，验证底层建图、保存地图、加载地图是否正常。

适用场景：

- Adapter `/slam/stop_mapping` 保存超时，需要确认底层 `/slam/save_map` 是否可用。
- Adapter `/slam/relocation` 加载超时，需要确认底层 `/slam/load_map` 是否可用。
- 想确认 `SaveMap.map_id` 应该传地图名还是绝对路径。

默认命名空间：

```bash
GR301AA0025
```

---

## 1. 准备环境

在机器人本机终端执行：

```bash
cd /opt/fftai/humanoidnav || exit 1
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash
export NS=/GR301AA0025
```

确认 HumanoidNav 已启动，并且服务、topic 可见：

```bash
ros2 service list | grep -E "$NS/slam/(set_mode|save_map|load_map)"
ros2 topic info $NS/robot_pose
ros2 topic info $NS/slam/mode_status
timeout 3s ros2 topic echo $NS/robot_pose --once
timeout 3s ros2 topic echo $NS/slam/mode_status --once
```

继续条件：

```plain
$NS/slam/set_mode 可见
$NS/slam/save_map 可见
$NS/slam/load_map 可见
$NS/robot_pose 的 Publisher count 大于 0
$NS/slam/mode_status 的 Publisher count 大于 0
robot_pose 能 echo 出一次
```

如果 service list 能看到名字，但 `ros2 service call` 一直停在 `waiting for service to become available...`，先检查 HumanoidNav 是否真的启动完整。只看到 service 名字不代表底层 service server 一定可调用。

---

## 2. 查看接口类型

```bash
ros2 service type $NS/slam/set_mode
ros2 service type $NS/slam/save_map
ros2 service type $NS/slam/load_map
```

预期：

```plain
fourier_msgs/srv/SetMode
fourier_msgs/srv/SaveMap
fourier_msgs/srv/LoadMap
```

查看字段：

```bash
ros2 interface show fourier_msgs/srv/SetMode
ros2 interface show fourier_msgs/srv/SaveMap
ros2 interface show fourier_msgs/srv/LoadMap
```

---

## 3. 开始建图

开始建图本质是切换到 mapping 模式：

```bash
ros2 service call $NS/slam/set_mode fourier_msgs/srv/SetMode "{mode: 'mapping'}"
```

成功返回通常类似：

```plain
response:
fourier_msgs.srv.SetMode_Response(result=0, message='Successfully switched to mapping mode')
```

如果已经在 mapping 模式，可能返回：

```plain
result=1
message='Already in mapping mode'
```

这也可以继续建图。

确认模式：

```bash
timeout 3s ros2 topic echo $NS/slam/mode_status --once
timeout 3s ros2 topic echo $NS/robot_pose --once
```

建图运动阶段由遥控器/手柄控制机器人行走，ROS2 命令只负责切模式和保存。

---

## 4. 保存地图：按地图名保存

先不要覆盖已有 `map`，建议用测试名：

```bash
ros2 service call $NS/slam/save_map fourier_msgs/srv/SaveMap "{map_id: 'test_save_001'}"
```

成功返回：

```plain
response:
fourier_msgs.srv.SaveMap_Response(response=0)
```

说明：

- `map_id='test_save_001'` 是按名字保存。
- HumanoidNav 对相对 `map_id` 的落盘目录由底层实现决定，不一定等于 `/opt/fftai/nav/test_save_001`。
- 如果需要明确保存到 `/opt/fftai/nav/...`，用下一节的绝对路径测试。

---

## 5. 保存地图：按绝对路径保存

推荐用这个方式确认 `/opt/fftai/nav` 下是否能直接落盘：

```bash
ros2 service call $NS/slam/save_map fourier_msgs/srv/SaveMap "{map_id: '/opt/fftai/nav/test_save_001'}"
```

成功返回：

```plain
response:
fourier_msgs.srv.SaveMap_Response(response=0)
```

检查文件：

```bash
ls -lah /opt/fftai/nav/test_save_001
```

有效地图目录通常至少应包含：

```plain
global.pcd
map.yaml
map.pgm
```

如果按名字保存超时或找不到结果，但绝对路径保存成功，Adapter 启动时应配置：

```bash
export MAP_SAVE_ID_MODE=path
```

---

## 6. 加载已有地图

加载机器人已有地图：

```bash
ros2 service call $NS/slam/load_map fourier_msgs/srv/LoadMap \
  "{map_path: '/opt/fftai/nav/map/', x: 0.0, y: 0.0, z: 0.0, yaw: 0.0}"
```

成功返回：

```plain
response:
fourier_msgs.srv.LoadMap_Response(result=0, message='Successfully loaded map and switched to localization mode')
```

确认定位状态：

```bash
timeout 3s ros2 topic echo $NS/slam/mode_status --once
timeout 3s ros2 topic echo $NS/robot_pose --once
timeout 3s ros2 topic echo $NS/odom_status_code --once
```

如果加载成功，`mode_status` 应该进入 localization 或类似定位模式。

---

## 7. 加载刚保存的测试地图

如果前面保存到了 `/opt/fftai/nav/test_save_001`：

```bash
ros2 service call $NS/slam/load_map fourier_msgs/srv/LoadMap \
  "{map_path: '/opt/fftai/nav/test_save_001', x: 0.0, y: 0.0, z: 0.0, yaw: 0.0}"
```

检查：

```bash
timeout 3s ros2 topic echo $NS/slam/mode_status --once
timeout 3s ros2 topic echo $NS/robot_pose --once
```

---

## 8. 使用 HumanoidNav 官方脚本加载地图

官方脚本在 `/opt/fftai/humanoidnav/scripts/`，不在 Adapter 工程里。

```bash
cd /opt/fftai/humanoidnav || exit 1
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash

./scripts/load_map.sh \
  --map-path /opt/fftai/nav/map/ \
  --namespace GR301AA0025
```

成功时会看到类似：

```plain
[load_map] Calling /GR301AA0025/slam/load_map service...
requester: making request: fourier_msgs.srv.LoadMap_Request(...)

response:
fourier_msgs.srv.LoadMap_Response(result=0, message='Successfully loaded map and switched to localization mode')
```

注意：

- 如果不加 `--namespace GR301AA0025`，脚本可能调用 `/slam/load_map`，而不是 `/GR301AA0025/slam/load_map`。
- `waiting for service to become available...` 不一定是失败，要看后面有没有 `requester` 和 `response result=0`。

---

## 9. 保存失败排查

如果 `save_map` 一直超时：

```bash
ros2 service call $NS/slam/save_map fourier_msgs/srv/SaveMap "{map_id: 'test_save_001'}"
ros2 service call $NS/slam/save_map fourier_msgs/srv/SaveMap "{map_id: '/opt/fftai/nav/test_save_001'}"
```

判断：

| 结果 | 说明 |
| --- | --- |
| 名字保存失败，绝对路径成功 | Adapter 应使用 `MAP_SAVE_ID_MODE=path` |
| 两种都超时 | HumanoidNav 当前保存服务或建图数据状态异常 |
| 返回 `response=3` | 地图数据为空，可能没有真实建图数据 |
| 返回 `response=1` | 保存操作已在运行，等底层恢复后再试 |

保存超时后不要立刻反复调用 `save_map` 或 `load_map`。先确认服务和位姿恢复：

```bash
ros2 service list | grep -E "$NS/slam/(set_mode|save_map|load_map)"
ros2 topic info $NS/robot_pose
timeout 3s ros2 topic echo $NS/robot_pose --once
```

---

## 10. 与 Adapter 对照

纯 ROS2 验证成功后，再测 Adapter：

```bash
curl -X POST http://127.0.0.1:8080/slam/start_mapping \
  -H "Content-Type: application/json" \
  -d '{"map_name":"test_save_001"}'

curl -X POST http://127.0.0.1:8080/slam/stop_mapping \
  -H "Content-Type: application/json" \
  -d '{"map_name":"test_save_001"}'

curl -X POST http://127.0.0.1:8080/slam/relocation \
  -H "Content-Type: application/json" \
  -d '{"map_path":"/opt/fftai/nav/test_save_001","x":0,"y":0,"z":0,"yaw":0,"wait_for_localization":false}'
```

如果纯 ROS2 成功而 Adapter 失败，检查 Adapter 进程视角：

```bash
curl http://127.0.0.1:8080/robot/status
```

重点看：

```plain
ros.clients.set_mode.ready
ros.clients.save_map.ready
ros.clients.load_map.ready
runtime.pose_age_sec
runtime.slam_mode
```

如果 HumanoidNav 重启过，Adapter 也建议重启。
