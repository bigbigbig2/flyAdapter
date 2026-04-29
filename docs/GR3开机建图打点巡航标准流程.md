# GR3 开机-建图-打点-巡航标准流程

这份文档是现场按步骤操作的 SOP，目标是从机器人开机开始，完整完成：

```plain
安全检查 -> 启动底层服务 -> 启动适配服务 -> 建图 -> 保存地图
-> 加载地图定位 -> 打点 -> 单点验证 -> 多点巡航 -> 背包接入验收 -> 收尾
```

默认配置：

```plain
机器人命名空间：GR301AA0025
工程目录：~/aurora_ws/flyAdapter
Adapter 地址：http://127.0.0.1:8080
Aurora Agent 地址：http://127.0.0.1:18080
```

如果在外部电脑访问机器人，把 `127.0.0.1` 换成机器人 IP。机器人本机终端里仍然使用 `127.0.0.1`。

---

## 0. 操作终端规划

建议固定开 5 个终端，避免把服务和检查命令混在一起：

| 终端 | 用途 | 是否常驻 |
| --- | --- | --- |
| 终端 1 | AuroraCore | 常驻 |
| 终端 2 | HumanoidNav | 常驻 |
| 终端 3 | Aurora Agent | 常驻 |
| 终端 4 | GR3 Adapter | 常驻 |
| 终端 5 | curl、ROS2 检查、RViz | 临时操作 |

本流程里的命令默认在机器人本机执行，直接使用固定地址和固定目录，不需要先 export 变量：

```plain
工程目录：~/aurora_ws/flyAdapter
Adapter：http://127.0.0.1:8080
Aurora Agent：http://127.0.0.1:18080
地图示例路径：/opt/fftai/nav/maps/showroom_1f_20260429
```

进入工程目录：

```bash
cd ~/aurora_ws/flyAdapter || exit 1
```

如果 `cd` 失败，不要继续执行后续命令。先确认工程是否真的部署在 `~/aurora_ws/flyAdapter`。

---

## 1. 现场安全检查

开机前先确认：

- 机器人周围 1.5 米内没有人、线缆、杂物。
- 急停按钮可用，现场人员知道急停位置。
- 电量充足，不建议低电量建图或巡航。
- 背包、雷达、相机、网络连接正常。
- 建图区域的门、坡、窄通道、临时障碍已经人工确认。
- 巡航路线中不会有人长期站在机器人必经路线上。

操作原则：

- 建图阶段低速移动，转弯慢，尽量闭环。
- 定位稳定后再打点。
- 先单点验证，再短路线巡航，最后跑完整路线。
- 正式验收不要依赖 `force=true`，除非明确知道 blocker 可以忽略。

继续下一步条件：

```plain
现场安全、急停、网络、电量、传感器都确认正常。
```

---

## 2. 命名规范

地图目录建议：

```plain
/opt/fftai/nav/maps/<场地>_<楼层>_<日期>
```

示例：

```plain
/opt/fftai/nav/maps/showroom_1f_20260429
```

点位命名建议：

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

巡航路线命名建议：

```plain
<场地>_<路线>_<版本>
```

示例：

```plain
showroom_main_v1
```

---

## 3. 开机和基础环境确认

登录机器人：

```bash
ssh -X gr301ab0113@<robot-ip>
```

确认机器、时间、磁盘和工程目录：

```bash
hostname
date
df -h /opt/fftai/nav ~
test -d ~/aurora_ws/flyAdapter && echo PROJECT_DIR_OK
```

确认网络：

```bash
ip addr
ping -c 3 127.0.0.1
```

继续下一步条件：

```plain
PROJECT_DIR_OK 出现；
/opt/fftai/nav 所在磁盘空间足够；
机器人网络正常。
```

---

## 4. 启动 AuroraCore

终端 1：

```bash
sudo docker start fourier_aurora_server
sudo docker exec -it fourier_aurora_server bash
```

进入容器后：

```bash
cd /workspace || exit 1
grep -E "DomainID|RobotName|RunType" config/config.yaml
AuroraCore --config config/config.yaml
```

需要重点确认：

```plain
DomainID = 123
RobotName = gr3v233
```

这两个值必须和后面的 Aurora Agent 环境变量一致：

```bash
export AURORA_DOMAIN_ID=123
export AURORA_ROBOT_NAME=gr3v233
```

另开检查命令：

```bash
sudo docker ps | grep fourier_aurora_server
```

继续下一步条件：

```plain
AuroraCore 进程保持运行；
容器没有退出；
DomainID 和 RobotName 与现场变量一致。
```

如果 Aurora Agent 后面报 `Unmatched subscriber: rt/aurora_state`，优先回到这一步检查 AuroraCore、DomainID、RobotName 和容器网络。

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

注意：

- 全流程命名空间统一为 `GR301AA0025`。
- 这里使用 `--no-rviz`，RViz 后面单独开。
- 这个终端要保持运行。

另开终端 5 检查 ROS2 接口：

```bash
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash

ros2 service list | egrep "/GR301AA0025/(slam/set_mode|slam/save_map|slam/load_map|cancel_current_action|get_current_action)"
ros2 action list | grep /GR301AA0025/navigate_to_pose
timeout 5s ros2 topic echo /GR301AA0025/robot_pose --once
timeout 5s ros2 topic echo /GR301AA0025/slam/mode_status --once
```

继续下一步条件：

```plain
能看到 slam/set_mode、slam/save_map、slam/load_map；
能看到 /GR301AA0025/navigate_to_pose；
robot_pose 能 echo 到数据。
```

如果这里查不到接口，Adapter 后面的 `/slam/start_mapping`、`/slam/relocation`、`/slam/start_cruise` 都不会真正可用。

---

## 6. 启动 Aurora Agent

终端 3：

```bash
cd ~/aurora_ws/flyAdapter || exit 1

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

终端 5 检查：

```bash
curl http://127.0.0.1:18080/health
curl http://127.0.0.1:18080/state
curl http://127.0.0.1:18080/diagnostics
```

正常结果要点：

```plain
available=true
connected=true
mock=false
import_attempts 里有 fourier_aurora_client.AuroraClient: ok
module_diagnostics 里能找到 fourier_msgs.msg.AuroraCmd
```

如果 AuroraCore 重启过，重置 Agent SDK 客户端：

```bash
curl -X POST http://127.0.0.1:18080/reset
curl http://127.0.0.1:18080/state
```

继续下一步条件：

```plain
Aurora Agent 能返回 state；
connected=true；
没有 DDS unmatched 或 SDK import 错误。
```

---

## 7. 启动 GR3 Adapter

终端 4：

```bash
cd ~/aurora_ws/flyAdapter || exit 1

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

终端 5 检查：

```bash
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/robot/status
curl http://127.0.0.1:8080/slam/status
curl http://127.0.0.1:8080/robot/readiness
```

正常结果要点：

```plain
healthz.ok=true
adapter.namespace=/GR301AA0025
ros.available=true
ros.ready=true
aurora.backend=agent
aurora.connected=true
```

也可以打开 Swagger 调试页：

```plain
http://127.0.0.1:8080/docs
```

继续下一步条件：

```plain
Adapter 启动；
ROS ready；
Aurora connected；
/slam/status 能稳定返回。
```

---

## 8. 建图前检查和进入建图模式

先设置本次地图名：

```bash
echo /opt/fftai/nav/maps/showroom_1f_20260429
```

确认当前状态：

```bash
curl http://127.0.0.1:8080/slam/status
curl http://127.0.0.1:8080/slam/pose
```

切换到建图模式：

```bash
curl -X POST http://127.0.0.1:8080/slam/start_mapping
```

再次确认：

```bash
curl http://127.0.0.1:8080/slam/status
```

建图模式下看到下面状态是正常的：

```plain
slam_mode=mapping
odom_status_code=1
localization_status=INITIALIZING
ready_for_navigation=false
```

原因是建图模式不是导航模式。只有保存地图、加载地图并进入定位后，`ready_for_navigation` 才应该变成 true。

如果 `/slam/start_mapping` 返回：

```plain
result.success=true
result.message=Already in mapping mode
```

这也表示已经处在建图模式，不是失败。

继续下一步条件：

```plain
slam_mode 是 mapping；
robot_pose 有数据且持续更新；
RViz 可以打开并看到点云或地图变化。
```

---

## 9. 打开建图 RViz

终端 5，使用脚本：

```bash
cd ~/aurora_ws/flyAdapter || exit 1
chmod +x scripts/open_rviz.sh
./scripts/open_rviz.sh mapping
```

脚本默认会给 RViz 加上软件渲染环境变量，避开部分机器上 Map 显示的 OpenGL shader 报错：

```plain
LIBGL_ALWAYS_SOFTWARE=1
QT_X11_NO_MITSHM=1
```

如果要临时关闭软件渲染：

```bash
GR3_RVIZ_SOFTWARE=0 ./scripts/open_rviz.sh mapping
```

等价完整命令：

```bash
cd ~/aurora_ws/flyAdapter || exit 1
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash

LIBGL_ALWAYS_SOFTWARE=1 QT_X11_NO_MITSHM=1 rviz2 -d rviz/mapping_GR301AA0025.rviz \
  --ros-args \
  -r tf:=/GR301AA0025/tf \
  -r tf_static:=/GR301AA0025/tf_static
```

建图 RViz 重点看：

| 项 | 期望 |
| --- | --- |
| `/GR301AA0025/map` | 地图随建图逐步生成 |
| `/GR301AA0025/scan` | 激光和周围环境轮廓一致 |
| `/GR301AA0025/cloud_registered_gravity` | 点云正常刷新 |
| `/GR301AA0025/odom` | 轨迹连续，没有大跳变 |
| TF | 能连接到 `map` |

Map 显示里的 `Update Topic` 必须是合法 topic，不能留空。当前工程配置为：

```plain
/GR301AA0025/map_updates
```

如果现场没有发布这个增量 topic，不影响 RViz 显示 `/GR301AA0025/map` 全量地图；但如果配置成空字符串，RViz2 会直接报 `Invalid topic name`。

关于 Fixed Frame：

```plain
RViz 的 Fixed Frame 使用 map，不写 /GR301AA0025/map。
原因是 map 是 TF frame 名，不是 topic 名。
topic 已经配置为 /GR301AA0025/...，TF 通过命令行 remap 到 /GR301AA0025/tf 和 /GR301AA0025/tf_static。
```

如果 RViz 提示 `map passed to lookupTransform argument target_frame does not exist`：

```bash
ros2 topic echo /GR301AA0025/tf --once
ros2 topic echo /GR301AA0025/tf_static --once
ros2 topic echo /GR301AA0025/map --once
```

优先判断是 TF 还没有发布、建图还没产生 map，还是 RViz 没有带 remap 启动。

---

## 10. 建图操作步骤

建图时按下面顺序走：

1. 从固定入口或计划的巡航起点开始。
2. 先走主通道，再走支路和房间。
3. 每个区域尽量闭环，最后回到起点附近。
4. 门口、转角、窄通道、玻璃墙附近放慢速度。
5. 不要长时间原地快速旋转。
6. 不要让大量行人持续遮挡雷达。
7. 地图明显撕裂、重影或跳变时，暂停移动并检查定位和 TF。

建图过程中每 30 秒检查一次：

```bash
curl http://127.0.0.1:8080/slam/status
curl http://127.0.0.1:8080/slam/pose
```

ROS 侧也可以检查：

```bash
timeout 5s ros2 topic echo /GR301AA0025/robot_pose --once
timeout 5s ros2 topic echo /GR301AA0025/slam/mode_status --once
```

继续下一步条件：

```plain
RViz 中地图完整；
主要通道和目标点位区域都覆盖；
回到起点附近后地图没有明显错位；
robot_pose 仍然持续刷新。
```

---

## 11. 保存地图

确认地图路径：

```bash
echo "/opt/fftai/nav/maps/showroom_1f_20260429"
```

保存地图：

```bash
curl -X POST http://127.0.0.1:8080/slam/stop_mapping \
  -H "Content-Type: application/json" \
  -d "{\"map_path\":\"/opt/fftai/nav/maps/showroom_1f_20260429\"}"
```

也可以用调试接口保存：

```bash
curl -X POST http://127.0.0.1:8080/robot/map/save \
  -H "Content-Type: application/json" \
  -d "{\"map_path\":\"/opt/fftai/nav/maps/showroom_1f_20260429\"}"
```

保存后检查文件：

```bash
test -d "/opt/fftai/nav/maps/showroom_1f_20260429" && echo MAP_DIR_OK
find "/opt/fftai/nav/maps/showroom_1f_20260429" -maxdepth 2 -type f | sort
curl http://127.0.0.1:8080/robot/map/list
```

继续下一步条件：

```plain
MAP_DIR_OK 出现；
地图目录中有 map/global/pcd/yaml 等相关文件；
/robot/map/list 能识别到本次地图。
```

如果保存失败：

- 先看 HumanoidNav 终端有没有 `/slam/save_map` 错误。
- 确认 `/opt/fftai/nav/maps` 有写权限和空间。
- 不要直接进入打点，先重新保存成功。

---

## 12. 加载地图并进入定位模式

加载刚保存的地图：

```bash
curl -X POST http://127.0.0.1:8080/slam/relocation \
  -H "Content-Type: application/json" \
  -d "{\"map_path\":\"/opt/fftai/nav/maps/showroom_1f_20260429\",\"x\":0,\"y\":0,\"z\":0,\"yaw\":0,\"wait_for_localization\":true}"
```

查询定位状态：

```bash
curl http://127.0.0.1:8080/robot/localization/status
curl http://127.0.0.1:8080/robot/readiness
```

连续观察 30 秒：

```bash
for i in $(seq 1 30); do
  curl -s http://127.0.0.1:8080/robot/localization/status
  echo
  sleep 1
done
```

理想状态：

```plain
slam_mode=localization
pose_age_sec <= 3
odom_status_code=2
/robot/readiness 里没有 localization_not_good
```

如果位置不准，发布初始位姿：

```bash
curl -X POST http://127.0.0.1:8080/robot/localization/initial_pose \
  -H "Content-Type: application/json" \
  -d '{"x":0,"y":0,"z":0,"yaw":0,"frame_id":"map"}'
```

然后再次检查：

```bash
curl http://127.0.0.1:8080/robot/localization/status
curl http://127.0.0.1:8080/robot/readiness
```

继续下一步条件：

```plain
定位模式正常；
odom_status_code=2；
readiness 没有 localization_not_good；
机器人在 RViz 中的位置和现场一致。
```

---

## 13. 打开定位 / 重定位 RViz

终端 5：

```bash
cd ~/aurora_ws/flyAdapter || exit 1
./scripts/open_rviz.sh relocation
```

等价完整命令：

```bash
cd ~/aurora_ws/flyAdapter || exit 1
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash

LIBGL_ALWAYS_SOFTWARE=1 QT_X11_NO_MITSHM=1 rviz2 -d rviz/relocation_GR301AA0025.rviz \
  --ros-args \
  -r tf:=/GR301AA0025/tf \
  -r tf_static:=/GR301AA0025/tf_static
```

定位 RViz 重点看：

| 项 | 期望 |
| --- | --- |
| `/GR301AA0025/map` | 已加载全局地图 |
| `/GR301AA0025/scan` | 当前激光和地图轮廓对齐 |
| `/GR301AA0025/odom` | 机器人位置合理 |
| `/GR301AA0025/plan` | 导航时能看到路径 |
| TF | `map -> odom -> base_link` 或等效链路连续 |

继续下一步条件：

```plain
RViz 中当前机器人位置和实际位置一致；
当前激光与全局地图基本重合；
TF 不再持续报 map frame 缺失。
```

---

## 14. 打点前准备

正式打点前，先确认是否需要清空旧点位。

查看现有点位：

```bash
curl http://127.0.0.1:8080/slam/nav_points
```

如果这是新地图，清空旧点位：

```bash
curl -X POST http://127.0.0.1:8080/slam/clear_nav_points
curl http://127.0.0.1:8080/slam/nav_points
```

确保机器人站立：

```bash
curl -X POST http://127.0.0.1:8080/robot/aurora/ensure_stand
curl http://127.0.0.1:8080/robot/aurora/state
```

执行导航预检：

```bash
curl -X POST http://127.0.0.1:8080/robot/navigation/precheck \
  -H "Content-Type: application/json" \
  -d '{"force":false}'
```

继续下一步条件：

```plain
precheck 返回 ok=true；
readiness.ready=true；
aurora.standing=true；
pose_age_sec 正常。
```

如果 `readiness.ready=false`，先处理 `blockers`。常见 blocker：

| blocker | 处理 |
| --- | --- |
| `ros_python_unavailable` | Adapter 没 source ROS 或虚拟环境缺依赖 |
| `robot_pose_not_fresh` | HumanoidNav/robot_pose 没更新 |
| `localization_not_good` | 重新加载地图或发布初始位姿 |
| `map_not_loaded` | 重新 `/slam/relocation` |
| `aurora_unavailable` | 检查 Aurora Agent / AuroraCore |
| `robot_not_standing` | 调 `/robot/aurora/ensure_stand` |

---

## 15. 逐点打点操作

每个点位按同一套动作执行。

第 1 步，移动到目标位置，停稳 2 到 3 秒：

```bash
curl http://127.0.0.1:8080/slam/pose
curl http://127.0.0.1:8080/robot/localization/status
```

第 2 步，保存当前位置为点位：

```bash
curl -X POST http://127.0.0.1:8080/slam/add_nav_point \
  -H "Content-Type: application/json" \
  -d '{"name":"lobby_01_start"}'
```

第 3 步，确认点位数量增加：

```bash
curl http://127.0.0.1:8080/slam/nav_points
curl http://127.0.0.1:8080/robot/poi/list
```

第 4 步，每打 3 到 5 个点保存一次：

```bash
curl -X POST http://127.0.0.1:8080/slam/save_nav_points
```

继续添加更多点位：

```bash
curl -X POST http://127.0.0.1:8080/slam/add_nav_point \
  -H "Content-Type: application/json" \
  -d '{"name":"lobby_02_frontdesk"}'

curl -X POST http://127.0.0.1:8080/slam/add_nav_point \
  -H "Content-Type: application/json" \
  -d '{"name":"corridor_01_turn"}'
```

点位要求：

- 不要贴墙、贴玻璃、贴障碍物。
- 点位前方和左右要给机器人留出转身空间。
- 需要停靠展示的点位，朝向也要调好再保存。
- 转角和窄通道建议额外设置过渡点。
- 起点、终点、充电区或人工接管区要单独命名。

继续下一步条件：

```plain
/slam/nav_points 的 count 与现场记录一致；
每个点位名称唯一；
点位已保存；
机器人仍处于定位良好状态。
```

---

## 16. 单点导航验证

不要直接跑完整巡航，先逐个验证关键点。

导航到第一个点：

```bash
curl -X POST http://127.0.0.1:8080/robot/navigation/goto_poi \
  -H "Content-Type: application/json" \
  -d '{"name":"lobby_01_start","force":false}'
```

观察状态：

```bash
watch -n 1 "curl -s http://127.0.0.1:8080/slam/nav_status"
```

另一个终端也可以看底层动作：

```bash
curl http://127.0.0.1:8080/robot/navigation/current_action
```

取消当前导航：

```bash
curl -X POST http://127.0.0.1:8080/robot/navigation/cancel
```

对第二个点重复：

```bash
curl -X POST http://127.0.0.1:8080/robot/navigation/goto_poi \
  -H "Content-Type: application/json" \
  -d '{"name":"lobby_02_frontdesk","force":false}'
```

单点验证通过标准：

```plain
请求能 accepted 或 success；
机器人能到达点位附近；
到达后姿态大致正确；
取消导航后能停止；
RViz 中路径和实际路线合理。
```

如果某个点失败：

- 点位太靠近障碍物：删除或覆盖该点。
- 目标朝向不好：重新停稳后保存点位。
- 路径绕路或穿墙：检查地图质量、代价地图、障碍物。
- readiness blocker 出现：先处理 blocker，不要用 `force=true` 掩盖问题。

---

## 17. 多点巡航验证

确认点位顺序：

```bash
curl http://127.0.0.1:8080/slam/nav_points
```

建议先只用 2 到 3 个低风险点做短路线验证。确认没问题后再增加完整路线。

启动巡航：

```bash
curl -X POST http://127.0.0.1:8080/slam/start_cruise \
  -H "Content-Type: application/json" \
  -d '{"force":false}'
```

轮询状态：

```bash
watch -n 1 "curl -s http://127.0.0.1:8080/slam/nav_status"
```

订阅事件流：

```bash
curl -N http://127.0.0.1:8080/slam/events
```

暂停、恢复、停止：

```bash
curl -X POST http://127.0.0.1:8080/slam/pause_nav
curl -X POST http://127.0.0.1:8080/slam/resume_nav
curl -X POST http://127.0.0.1:8080/slam/stop_cruise
```

巡航通过标准：

```plain
current_nav_index 正常推进；
每个点能按顺序到达；
stop_cruise 能停止；
pause/resume 行为符合预期；
/slam/events 有到点、失败或完成事件；
机器人实际运动没有明显抖动或危险路径。
```

---

## 18. 固定路线 patrol / mission

如果要把一组点固化成业务路线，先保存 route：

```bash
curl -X POST http://127.0.0.1:8080/robot/routes/upsert \
  -H "Content-Type: application/json" \
  -d '{
    "route": {
      "name": "showroom_main_v1",
      "map_name": "showroom_1f_20260429",
      "points": [
        "lobby_01_start",
        "lobby_02_frontdesk",
        "corridor_01_turn"
      ],
      "meta": {
        "remark": "main patrol route"
      }
    }
  }'
```

查看路线：

```bash
curl http://127.0.0.1:8080/robot/routes
```

启动路线巡航：

```bash
curl -X POST http://127.0.0.1:8080/robot/patrol/start \
  -H "Content-Type: application/json" \
  -d '{"route_name":"showroom_main_v1","map_name":"showroom_1f_20260429","loop":false,"force":false}'
```

查看状态：

```bash
curl http://127.0.0.1:8080/robot/patrol/status
```

停止：

```bash
curl -X POST http://127.0.0.1:8080/robot/patrol/stop
```

继续下一步条件：

```plain
route 能保存；
patrol/start 能启动；
patrol/status 能看到执行状态；
patrol/stop 能安全停止。
```

---

## 19. 背包接入前验收

背包接入前至少执行下面检查：

```bash
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/slam/status
curl http://127.0.0.1:8080/slam/pose
curl http://127.0.0.1:8080/slam/nav_points
curl http://127.0.0.1:8080/slam/nav_status
curl http://127.0.0.1:8080/robot/status
curl http://127.0.0.1:8080/robot/readiness
curl http://127.0.0.1:8080/robot/aurora/state
```

验收标准：

```plain
healthz.ok=true
ros.ready=true
aurora.connected=true
readiness.ready=true
nav_points.count 与现场点位一致
单点导航成功
多点巡航成功
stop_cruise 和 navigation/cancel 能安全停止
```

建议记录一次验收结果：

```plain
日期：
场地：
机器人：
命名空间：GR301AA0025
地图路径：
地图名称：
点位数量：
路线名称：
单点验证结果：
巡航验证结果：
测试人员：
遗留问题：
```

背包侧一般只需要关心兼容接口：

```plain
GET  /slam/status
GET  /slam/pose
POST /slam/relocation
POST /slam/add_nav_point
GET  /slam/nav_points
POST /slam/start_cruise
POST /slam/stop_cruise
GET  /slam/nav_status
GET  /slam/events
```

---

## 20. 常见异常处理

### 20.1 立即停止机器人

先停巡航，再取消导航，再停机体运动：

```bash
curl -X POST http://127.0.0.1:8080/slam/stop_cruise
curl -X POST http://127.0.0.1:8080/robot/navigation/cancel
curl -X POST http://127.0.0.1:8080/robot/aurora/stop_motion
```

### 20.2 Aurora Agent 状态异常

```bash
curl http://127.0.0.1:18080/health
curl http://127.0.0.1:18080/state
curl http://127.0.0.1:18080/diagnostics
curl -X POST http://127.0.0.1:18080/reset
```

通过 Adapter 重置：

```bash
curl -X POST http://127.0.0.1:8080/robot/aurora/reset
curl http://127.0.0.1:8080/robot/aurora/state?force_refresh=true
```

### 20.3 定位丢失

```bash
curl http://127.0.0.1:8080/robot/localization/status
curl -X POST http://127.0.0.1:8080/slam/relocation \
  -H "Content-Type: application/json" \
  -d "{\"map_path\":\"/opt/fftai/nav/maps/showroom_1f_20260429\",\"x\":0,\"y\":0,\"z\":0,\"yaw\":0,\"wait_for_localization\":true}"
```

必要时重新发布初始位姿：

```bash
curl -X POST http://127.0.0.1:8080/robot/localization/initial_pose \
  -H "Content-Type: application/json" \
  -d '{"x":0,"y":0,"z":0,"yaw":0,"frame_id":"map"}'
```

### 20.4 ROS2 接口异常

```bash
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash

ros2 service list | grep /GR301AA0025
ros2 topic list | grep /GR301AA0025
ros2 action list | grep /GR301AA0025
curl http://127.0.0.1:8080/robot/status
```

### 20.5 RViz 看不到地图或 TF

确认 RViz 是用脚本或带 remap 命令启动的：

```bash
./scripts/open_rviz.sh mapping
./scripts/open_rviz.sh relocation
```

检查 topic：

```bash
ros2 topic list | egrep "/GR301AA0025/(map|scan|tf|tf_static|odom)"
```

Fixed Frame 使用 `map`，不要改成 `/GR301AA0025/map`。

如果 Map 左侧状态报红，并且终端里有下面这类报错：

```plain
GLSL link result:
active samplers with a different type refer to the same texture image unit
```

这通常是 RViz Map 插件和显卡 OpenGL 驱动的渲染兼容问题，不是命名空间或 Adapter 状态问题。优先用脚本启动，脚本会默认启用软件渲染：

```bash
./scripts/open_rviz.sh mapping
```

如果手动启动，命令前加：

```bash
LIBGL_ALWAYS_SOFTWARE=1 QT_X11_NO_MITSHM=1 rviz2 -d rviz/mapping_GR301AA0025.rviz \
  --ros-args \
  -r tf:=/GR301AA0025/tf \
  -r tf_static:=/GR301AA0025/tf_static
```

---

## 21. 收尾和关机

停止巡航和运动：

```bash
curl -X POST http://127.0.0.1:8080/slam/stop_cruise
curl -X POST http://127.0.0.1:8080/robot/navigation/cancel
curl -X POST http://127.0.0.1:8080/robot/aurora/stop_motion
```

保存点位：

```bash
curl -X POST http://127.0.0.1:8080/slam/save_nav_points
```

保存现场记录：

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

## 22. 一页命令速查

```bash
# 本机固定环境：Adapter=http://127.0.0.1:8080，工程目录=~/aurora_ws/flyAdapter

# 状态
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/slam/status
curl http://127.0.0.1:8080/robot/readiness
curl http://127.0.0.1:8080/robot/status

# RViz
cd ~/aurora_ws/flyAdapter
./scripts/open_rviz.sh mapping
./scripts/open_rviz.sh relocation

# 建图
curl -X POST http://127.0.0.1:8080/slam/start_mapping
curl -X POST http://127.0.0.1:8080/slam/stop_mapping \
  -H "Content-Type: application/json" \
  -d "{\"map_path\":\"/opt/fftai/nav/maps/showroom_1f_20260429\"}"

# 定位
curl -X POST http://127.0.0.1:8080/slam/relocation \
  -H "Content-Type: application/json" \
  -d "{\"map_path\":\"/opt/fftai/nav/maps/showroom_1f_20260429\",\"x\":0,\"y\":0,\"z\":0,\"yaw\":0,\"wait_for_localization\":true}"

# 打点
curl -X POST http://127.0.0.1:8080/slam/add_nav_point \
  -H "Content-Type: application/json" \
  -d '{"name":"lobby_01_start"}'
curl -X POST http://127.0.0.1:8080/slam/save_nav_points
curl http://127.0.0.1:8080/slam/nav_points

# 单点导航
curl -X POST http://127.0.0.1:8080/robot/navigation/goto_poi \
  -H "Content-Type: application/json" \
  -d '{"name":"lobby_01_start","force":false}'

# 巡航
curl -X POST http://127.0.0.1:8080/slam/start_cruise \
  -H "Content-Type: application/json" \
  -d '{"force":false}'
curl http://127.0.0.1:8080/slam/nav_status
curl -N http://127.0.0.1:8080/slam/events
curl -X POST http://127.0.0.1:8080/slam/stop_cruise

# 急停式接口停止
curl -X POST http://127.0.0.1:8080/slam/stop_cruise
curl -X POST http://127.0.0.1:8080/robot/navigation/cancel
curl -X POST http://127.0.0.1:8080/robot/aurora/stop_motion
```
