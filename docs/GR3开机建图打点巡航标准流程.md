# GR3 开机-建图-打点-巡航标准流程

本文档是一套现场标准作业流程，适用于从机器人开机开始，完成：

```plain
开机检查 -> 启动底层服务 -> 建图 -> 保存地图 -> 加载地图定位 -> 打点 -> 单点验证 -> 多点巡航 -> 收尾
```

默认命名空间：

```plain
GR301AA0025
```

默认 Adapter 地址：

```plain
http://127.0.0.1:8080
```

如果现场不是本机访问，把 `127.**0**.0.1` 换成机器人 IP。

---

## 1. 现场安全检查

开机前先确认：

- 机器人周围 1.5 米内没有人、线缆、杂物。
- 急停按钮可用，现场人员知道急停位置。
- 电量充足，建图和巡航过程中不要低电量测试。
- 地面环境适合建图：光照稳定、可通行区域清晰、临时障碍尽量移走。
- 背包、雷达、相机、网络连接正常。
- 如果要巡航，路线上的门、坡、窄通道要先人工确认。

操作原则：

- 建图阶段慢速推/走，路线闭环，避免快速旋转。
- 打点只在定位稳定后进行。
- 巡航先短距离、低风险点位验证，再跑完整路线。
- 不建议常态使用 `force=true`，除非明确知道 readiness blocker 可忽略。

---

## 2. 命名规范

建议统一命名，方便背包和现场排查。

地图目录：

```plain
/opt/fftai/nav/maps/<场地>_<楼层>_<日期>
```

示例：

```plain
/opt/fftai/nav/maps/showroom_1f_20260429
```

点位名称：

```plain
<区域>_<序号>_<含义>
```

示例：

```plain
lobby_01_start
lobby_02_frontdesk
corridor_01_turn
rooma_01_door
```

巡航路线名称：

```plain
<场地>_<路线>_<版本>
```

示例：

```plain
showroom_main_v1
```

---

## 3. 开机和网络确认

机器人上电后，先登录机器人：

```bash
ssh -X gr301ab0113@<robot-ip>
```

确认基础网络：

```bash
hostname
ip addr
ping -c 3 127.0.0.1
```

进入工程目录：

```bash
cd ~/aurora_ws/gr3 || exit 1
```

如果这个目录不存在，不要继续执行。先确认工程部署位置。

---

## 4. 启动 AuroraCore

终端 1：

```bash
sudo docker start fourier_aurora_server
sudo docker exec -it fourier_aurora_server bash

cd /workspace || exit 1
grep -E "DomainID|RobotName|RunType" config/config.yaml

AuroraCore --config config/config.yaml
```

要求：

- `RobotName` 与后面 `AURORA_ROBOT_NAME` 一致。
- `DomainID` 与后面 `AURORA_DOMAIN_ID` 一致。
- AuroraCore 进程保持运行。

示例环境变量：

```plain
AURORA_DOMAIN_ID=123
AURORA_ROBOT_NAME=gr3v233
```

---

## 5. 启动 HumanoidNav

终端 2：

```bash
cd /opt/fftai/humanoidnav || exit 1
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash

./scripts/run_real.sh \
  --unified-init mapping \
  --sensor-type airy \
  --disable-ddscmd \
  --no-rviz \
  --namespace GR301AA0025
```

要求：

- 全流程统一使用 `GR301AA0025`。
- 进程保持运行。
- 如果要打开 RViz，另开终端启动，不要影响主进程。

---

## 6. 启动 Aurora Agent

终端 3：

```bash
cd ~/aurora_ws/gr3 || exit 1

export AURORA_DOMAIN_ID=123
export AURORA_ROBOT_NAME=gr3v233
export AURORA_CLIENT_MODULE=fourier_aurora_client
export AURORA_CLIENT_CLASS=AuroraClient
export AURORA_STAND_FSM_STATE=2
export AURORA_ENV_CLEAN=1
export AURORA_AGENT_HOST=127.0.0.1
export AURORA_AGENT_PORT=18080

chmod +x scripts/run_aurora_agent.sh
./scripts/run_aurora_agent.sh
```

另开测试终端检查：

```bash
curl http://127.0.0.1:18080/health
curl http://127.0.0.1:18080/state
```

要求：

- `fourier_aurora_client.AuroraClient: ok`
- `connected=true`

如果出现 DDS unmatched，优先检查 AuroraCore、`DomainID`、`RobotName`、容器网络。

---

## 7. 启动 GR3 Adapter

终端 4：

```bash
cd ~/aurora_ws/gr3 || exit 1

python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements.txt

source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash
python -c "import numpy; import rclpy; print('PY_ROS_IMPORT_OK')"

export ROBOT_NAMESPACE=GR301AA0025
export ADAPTER_HOST=0.0.0.0
export ADAPTER_PORT=8080
export AURORA_BACKEND=agent
export AURORA_AGENT_URL=http://127.0.0.1:18080

chmod +x scripts/run_adapter.sh
./scripts/run_adapter.sh
```

基础检查：

```bash
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/robot/status
curl http://127.0.0.1:8080/slam/status
```

要求：

- `healthz.ok=true`
- `ros.ready=true`
- `aurora.backend=agent`
- `adapter.namespace=/GR301AA0025`

---

## 8. 建图前检查

检查 ROS2 接口：

```bash
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash

ros2 service list | egrep "/GR301AA0025/(slam/set_mode|slam/save_map|slam/load_map)"
ros2 topic list | egrep "/GR301AA0025/(robot_pose|slam/mode_status|map|scan)"
```

检查当前模式：

```bash
curl http://127.0.0.1:8080/slam/status
```

如果不在 mapping，可以切换：

```bash
curl -X POST http://127.0.0.1:8080/slam/start_mapping
```

预期：

- `slam_mode` 为 `mapping` 或底层返回建图模式。
- `robot_pose` 有持续更新。

这时 `/slam/status` 里如果看到：

```plain
slam_mode=mapping
odom_status_code=1
localization_status=INITIALIZING
ready_for_navigation=false
```

这是正常的。建图模式不是导航模式，`ready_for_navigation=false` 不代表服务异常。导航前必须先保存地图、加载地图进入定位，并等 `odom_status_code=2`。

### 8.1 打开建图 RViz

开始建图后，另开一个有图形环境的终端启动建图可视化：

```bash
cd ~/aurora_ws/gr3 || exit 1
chmod +x scripts/open_rviz.sh
./scripts/open_rviz.sh mapping
```

等价完整命令：

```bash
cd ~/aurora_ws/gr3 || exit 1
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash

rviz2 -d rviz/mapping_GR301AA0025.rviz \
  --ros-args \
  -r tf:=/GR301AA0025/tf \
  -r tf_static:=/GR301AA0025/tf_static
```

建图 RViz 主要看：

- `/GR301AA0025/map`：当前 2D 地图。
- `/GR301AA0025/scan`：当前 2D 激光。
- `/GR301AA0025/cloud_registered_gravity`：当前配准点云。
- `/GR301AA0025/odom`：里程计轨迹。
- TF 是否能连到 `map`。

---

## 9. 建图操作规范

建图时按这个方式走：

1. 从场地入口或固定起点开始。
2. 先走主通道，再走支路和房间。
3. 每个区域尽量形成闭环，最后回到起点附近。
4. 经过门口、转角、窄通道时放慢速度。
5. 不要长时间原地快速旋转。
6. 不要让大量行人持续遮挡雷达。

建图过程中可以轮询：

```bash
curl http://127.0.0.1:8080/slam/pose
curl http://127.0.0.1:8080/slam/status
```

如果使用 RViz，注意：

- Fixed Frame 使用 `map`。
- TF topic remap 到 `/GR301AA0025/tf`、`/GR301AA0025/tf_static`。
- 建图阶段使用 `rviz/mapping_GR301AA0025.rviz`。

---

## 10. 保存地图

建图结束后，设置地图保存路径：

```bash
export MAP_PATH=/opt/fftai/nav/maps/showroom_1f_20260429
```

保存地图：

```bash
curl -X POST http://127.0.0.1:8080/slam/stop_mapping \
  -H "Content-Type: application/json" \
  -d "{\"map_path\":\"${MAP_PATH}\"}"
```

也可以使用调试接口：

```bash
curl -X POST http://127.0.0.1:8080/robot/map/save \
  -H "Content-Type: application/json" \
  -d "{\"map_path\":\"${MAP_PATH}\"}"
```

保存后检查：

```bash
ls -lah "${MAP_PATH}"
curl http://127.0.0.1:8080/robot/map/list
```

要求：

- 地图目录存在。
- 能看到地图相关文件。
- `/robot/map/list` 能识别该地图。

---

## 11. 加载地图进入定位

加载刚保存的地图：

```bash
curl -X POST http://127.0.0.1:8080/slam/relocation \
  -H "Content-Type: application/json" \
  -d "{
    \"map_path\":\"${MAP_PATH}\",
    \"x\":0,
    \"y\":0,
    \"z\":0,
    \"yaw\":0,
    \"wait_for_localization\":true
  }"
```

检查定位状态：

```bash
curl http://127.0.0.1:8080/robot/localization/status
curl http://127.0.0.1:8080/robot/readiness
```

要求：

- `slam_mode` 为 `localization` 或等效定位模式。
- `pose_age_sec <= 3`。
- `odom_status_code=2`。
- `/robot/readiness` 没有 `localization_not_good`。

### 11.1 打开定位 / 重定位 RViz

地图加载后，另开一个有图形环境的终端启动定位可视化：

```bash
cd ~/aurora_ws/gr3 || exit 1
chmod +x scripts/open_rviz.sh
./scripts/open_rviz.sh relocation
```

等价完整命令：

```bash
cd ~/aurora_ws/gr3 || exit 1
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash

rviz2 -d rviz/relocation_GR301AA0025.rviz \
  --ros-args \
  -r tf:=/GR301AA0025/tf \
  -r tf_static:=/GR301AA0025/tf_static
```

定位 RViz 主要看：

- `/GR301AA0025/map`：已加载地图。
- `/GR301AA0025/scan`：当前激光是否和地图轮廓对齐。
- `/GR301AA0025/odom`：机器人当前位置是否合理。
- `/GR301AA0025/plan`：导航时的全局路径。
- TF 是否存在 `map -> odom -> base_link` 或等效链路。

如果定位不稳定，可以发布初始位姿：

```bash
curl -X POST http://127.0.0.1:8080/robot/localization/initial_pose \
  -H "Content-Type: application/json" \
  -d '{"x":0,"y":0,"z":0,"yaw":0,"frame_id":"map"}'
```

---

## 12. 打点前准备

清空旧点位前要确认是否需要备份。正式打点建议先清空测试点：

```bash
curl -X POST http://127.0.0.1:8080/slam/clear_nav_points
```

确保机器人站立：

```bash
curl -X POST http://127.0.0.1:8080/robot/aurora/ensure_stand
```

确保导航预检通过：

```bash
curl -X POST http://127.0.0.1:8080/robot/navigation/precheck \
  -H "Content-Type: application/json" \
  -d '{"force":false}'
```

要求：

- `ok=true`。
- 如果 `ok=false`，先处理 `blockers`。

---

## 13. 打点规范

人工把机器人移动或导航到目标位置，确认姿态朝向正确后保存点位。

保存第一个点：

```bash
curl -X POST http://127.0.0.1:8080/slam/add_nav_point \
  -H "Content-Type: application/json" \
  -d '{"name":"lobby_01_start"}'
```

保存更多点：

```bash
curl -X POST http://127.0.0.1:8080/slam/add_nav_point \
  -H "Content-Type: application/json" \
  -d '{"name":"lobby_02_frontdesk"}'

curl -X POST http://127.0.0.1:8080/slam/add_nav_point \
  -H "Content-Type: application/json" \
  -d '{"name":"corridor_01_turn"}'
```

查看点位：

```bash
curl http://127.0.0.1:8080/slam/nav_points
curl http://127.0.0.1:8080/robot/poi/list
```

保存点位文件：

```bash
curl -X POST http://127.0.0.1:8080/slam/save_nav_points
```

打点要求：

- 点位不要贴墙、贴玻璃、贴障碍物。
- 点位之间预留足够转身空间。
- 需要停靠展示的位置，朝向也要调整好再保存。
- 每打 3 到 5 个点，建议保存一次。

---

## 14. 单点导航验证

先验证每个点能否单独到达。

```bash
curl -X POST http://127.0.0.1:8080/robot/navigation/goto_poi \
  -H "Content-Type: application/json" \
  -d '{"name":"lobby_01_start","force":false}'
```

查看状态：

```bash
curl http://127.0.0.1:8080/slam/nav_status
curl http://127.0.0.1:8080/robot/navigation/current_action
```

取消当前导航：

```bash
curl -X POST http://127.0.0.1:8080/robot/navigation/cancel
```

要求：

- 导航请求被 accepted。
- 机器人能到点附近。
- 取消时能停止。

所有关键点位都建议先单点验证，再进入巡航。

---

## 15. 多点巡航

确认当前点位顺序：

```bash
curl http://127.0.0.1:8080/slam/nav_points
```

启动巡航：

```bash
curl -X POST http://127.0.0.1:8080/slam/start_cruise \
  -H "Content-Type: application/json" \
  -d '{"force":false}'
```

轮询巡航状态：

```bash
watch -n 1 'curl -s http://127.0.0.1:8080/slam/nav_status'
```

停止巡航：

```bash
curl -X POST http://127.0.0.1:8080/slam/stop_cruise
```

暂停和恢复：

```bash
curl -X POST http://127.0.0.1:8080/slam/pause_nav
curl -X POST http://127.0.0.1:8080/slam/resume_nav
```

要求：

- 巡航按点位顺序执行。
- `current_nav_index` 正常推进。
- 到点后 `is_arrived=true` 或事件里出现到达记录。
- `stop_cruise` 后机器人停止，底层 action 被取消。

---

## 16. 路线文件巡航

如果要做固定路线，可以用 route/patrol 接口。

创建路线：

```bash
curl -X POST http://127.0.0.1:8080/robot/routes/upsert \
  -H "Content-Type: application/json" \
  -d '{
    "route": {
      "name": "showroom_main_v1",
      "points": [
        "lobby_01_start",
        "lobby_02_frontdesk",
        "corridor_01_turn"
      ]
    }
  }'
```

启动路线巡航：

```bash
curl -X POST http://127.0.0.1:8080/robot/patrol/start \
  -H "Content-Type: application/json" \
  -d '{"route_name":"showroom_main_v1","force":false}'
```

查看路线巡航状态：

```bash
curl http://127.0.0.1:8080/robot/patrol/status
```

停止：

```bash
curl -X POST http://127.0.0.1:8080/robot/patrol/stop
```

---

## 17. 背包接入前验收

背包接入前至少确认：

```bash
curl http://127.0.0.1:8080/slam/status
curl http://127.0.0.1:8080/slam/nav_points
curl http://127.0.0.1:8080/slam/nav_status
curl http://127.0.0.1:8080/robot/readiness
```

验收标准：

- `/slam/status` 正常返回。
- `/slam/nav_points` 有正式点位。
- `/robot/readiness.ready=true`，或 blocker 原因明确且可接受。
- Aurora `ensure_stand` 成功。
- 单点导航成功。
- 多点巡航成功。
- `stop_cruise`、`navigation/cancel` 能安全停止。

---

## 18. 异常处理

立即停止巡航：

```bash
curl -X POST http://127.0.0.1:8080/slam/stop_cruise
curl -X POST http://127.0.0.1:8080/robot/navigation/cancel
curl -X POST http://127.0.0.1:8080/robot/aurora/stop_motion
```

AuroraCore 重启后：

```bash
curl -X POST http://127.0.0.1:8080/robot/aurora/reset
curl http://127.0.0.1:8080/robot/aurora/state?force_refresh=true
```

定位丢失：

```bash
curl http://127.0.0.1:8080/robot/localization/status
curl -X POST http://127.0.0.1:8080/slam/relocation \
  -H "Content-Type: application/json" \
  -d "{
    \"map_path\":\"${MAP_PATH}\",
    \"x\":0,
    \"y\":0,
    \"z\":0,
    \"yaw\":0,
    \"wait_for_localization\":true
  }"
```

ROS2 接口异常：

```bash
ros2 service list | grep /GR301AA0025
ros2 topic list | grep /GR301AA0025
curl http://127.0.0.1:8080/robot/status
```

---

## 19. 收尾和关机

停止巡航和运动：

```bash
curl -X POST http://127.0.0.1:8080/slam/stop_cruise
curl -X POST http://127.0.0.1:8080/robot/aurora/stop_motion
```

保存点位：

```bash
curl -X POST http://127.0.0.1:8080/slam/save_nav_points
```

记录现场信息：

```plain
日期：
场地：
地图路径：
点位数量：
路线名称：
测试人员：
问题记录：
```

关闭顺序建议：

```plain
1. 停止巡航 / 停止运动
2. 关闭 Adapter
3. 关闭 Aurora Agent
4. 关闭 HumanoidNav
5. 关闭 AuroraCore
6. 机器人下电
```

---

## 20. 一页命令速查

```bash
# 状态
curl http://127.0.0.1:8080/slam/status
curl http://127.0.0.1:8080/robot/readiness

# RViz
./scripts/open_rviz.sh mapping
./scripts/open_rviz.sh relocation

# 建图
curl -X POST http://127.0.0.1:8080/slam/start_mapping
curl -X POST http://127.0.0.1:8080/slam/stop_mapping \
  -H "Content-Type: application/json" \
  -d "{\"map_path\":\"${MAP_PATH}\"}"

# 定位
curl -X POST http://127.0.0.1:8080/slam/relocation \
  -H "Content-Type: application/json" \
  -d "{\"map_path\":\"${MAP_PATH}\",\"wait_for_localization\":true}"

# 打点
curl -X POST http://127.0.0.1:8080/slam/add_nav_point \
  -H "Content-Type: application/json" \
  -d '{"name":"lobby_01_start"}'
curl -X POST http://127.0.0.1:8080/slam/save_nav_points

# 单点导航
curl -X POST http://127.0.0.1:8080/robot/navigation/goto_poi \
  -H "Content-Type: application/json" \
  -d '{"name":"lobby_01_start","force":false}'

# 巡航
curl -X POST http://127.0.0.1:8080/slam/start_cruise \
  -H "Content-Type: application/json" \
  -d '{"force":false}'
curl http://127.0.0.1:8080/slam/nav_status
curl -X POST http://127.0.0.1:8080/slam/stop_cruise
```
