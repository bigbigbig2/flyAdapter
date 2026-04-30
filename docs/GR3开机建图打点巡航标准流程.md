# GR3 开机-建图-打点-巡航标准流程

这份文档按当前 GR3 适配服务的新架构编写：**建图和手动打点阶段，机器人运动由遥控器/手柄负责；适配服务只负责切 SLAM 模式、保存地图、读取位姿、保存点位。**

自动导航、单点验证、巡航阶段才由适配服务向 HumanoidNav/Nav2 发送目标点。AuroraCore / Aurora Agent 不是默认必需项，只有在明确配置 `MOTION_GUARD=aurora` 时才作为自动导航保护链路使用。

默认信息：

```plain
机器人命名空间：GR301AA0025
工程目录：~/aurora_ws/flyAdapter
Adapter 地址：http://127.0.0.1:8080
地图根目录：/opt/fftai/nav
地图名称示例：map
地图最终路径：/opt/fftai/nav/map
```

外部电脑访问时，把 `127.0.0.1` 换成机器人 IP；机器人本机终端里继续使用 `127.0.0.1`。

---

## 0. 控制权原则

先把控制权讲清楚，后面操作就不会乱：

| 阶段 | 谁控制机器人走路 | 适配服务做什么 | 是否需要 Aurora |
| --- | --- | --- | --- |
| 建图 | 遥控器/手柄 | 切到 mapping、读位姿、保存地图 | 不需要 |
| 定位后打点 | 遥控器/手柄 | 读当前位姿、保存点位 | 不需要 |
| 单点验证 | HumanoidNav/Nav2 | 发送一个目标点 | 默认不需要 |
| 多点巡航 | HumanoidNav/Nav2 | 按顺序发送多个目标点 | 默认不需要 |
| 自动导航保护 | HumanoidNav/Nav2 + Aurora guard | 导航前 ensure_stand，取消时 stop_motion | 仅 `MOTION_GUARD=aurora` 需要 |

如果遥控器连接后 AuroraCore 断开，而你当前只是建图或手动打点，这不是本流程的 blocker。建图和打点不依赖 AuroraCore。

---

## 1. 终端规划

建议固定开 4 个终端：

| 终端 | 用途 | 是否常驻 |
| --- | --- | --- |
| 终端 1 | HumanoidNav | 常驻 |
| 终端 2 | GR3 Adapter | 常驻 |
| 终端 3 | RViz | 需要时打开 |
| 终端 4 | curl / ROS2 检查 | 临时操作 |

只有在要启用 Aurora 自动导航保护时，再额外打开：

| 终端 | 用途 | 是否常驻 |
| --- | --- | --- |
| 可选终端 A | AuroraCore | 可选 |
| 可选终端 B | Aurora Agent | 可选 |

---

## 2. 现场安全检查

开机前确认：

- 机器人周围 1.5 米内没有人、线缆、杂物。
- 急停按钮可用，现场人员知道急停位置。
- 电量充足，不建议低电量建图或巡航。
- 背包、雷达、相机、网络连接正常。
- 建图区域的门、坡、窄通道、临时障碍已经人工确认。
- 巡航路线中不会有人长期站在机器人必经路线上。

操作原则：

- 建图阶段用遥控器低速移动，转弯慢，尽量闭环。
- 定位稳定后再打点。
- 先单点验证，再短路线巡航，最后跑完整路线。
- 正式验收不要依赖 `force=true`。

---

## 3. 登录机器人和基础检查

登录机器人：

```bash
ssh -X gr301ab0113@<robot-ip>
```

检查基础环境：

```bash
hostname
date
df -h /opt/fftai/nav ~
test -d ~/aurora_ws/flyAdapter && echo PROJECT_DIR_OK
ip addr
ping -c 3 127.0.0.1
```

继续条件：

```plain
PROJECT_DIR_OK 出现；
/opt/fftai/nav 所在磁盘空间足够；
机器人本机网络正常。
```

---

## 4. 启动 HumanoidNav

终端 1：

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

另开终端检查 ROS2 能看到 GR3 命名空间：

```bash
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash

ros2 service list | egrep "/GR301AA0025/(slam/load_map|slam/save_map|cancel_current_action|get_current_action)"
ros2 action list | grep /GR301AA0025/navigate_to_pose
timeout 5s ros2 topic echo /GR301AA0025/robot_pose --once
```

继续条件：

```plain
能看到 /GR301AA0025/slam/load_map、/GR301AA0025/slam/save_map；
能看到 /GR301AA0025/navigate_to_pose；
/GR301AA0025/robot_pose 能输出一次。
```

---

## 5. 启动 GR3 Adapter

终端 2，默认使用手动运动控制策略：

```bash
cd ~/aurora_ws/flyAdapter || exit 1

source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash
source .venv/bin/activate

export ROBOT_NAMESPACE=GR301AA0025
export MAP_ROOT=/opt/fftai/nav
export DEFAULT_MAP_NAME=map
export MOTION_GUARD=none
export AURORA_ENABLED=0

chmod +x scripts/run_adapter.sh
./scripts/run_adapter.sh
```

这个默认策略的含义：

```plain
建图：遥控器控制机器人运动
打点：遥控器控制机器人运动
导航/巡航：适配服务向 Nav2 发目标点
Aurora：不作为 readiness blocker，也不会自动调用 ensure_stand/stop_motion
```

检查 Adapter：

```bash
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/robot/status
curl http://127.0.0.1:8080/robot/workflow/status
```

继续条件：

```plain
/healthz 返回 ok=true；
/robot/status 里的 ros.ready=true；
motion_authority.policy=none。
```

Web 操作台：

```plain
http://127.0.0.1:8080/
```

Swagger：

```plain
http://127.0.0.1:8080/docs
```

---

## 6. 进入建图模式

终端 4：

```bash
curl -X POST http://127.0.0.1:8080/slam/start_mapping \
  -H "Content-Type: application/json" \
  -d '{"map_name":"map"}'
curl http://127.0.0.1:8080/robot/readiness/mapping
curl http://127.0.0.1:8080/slam/status
```

说明：开始建图只切换 HumanoidNav 到 mapping 模式，不会立刻创建地图文件。
这里传入的 `map_name` 会按 `MAP_ROOT/map_name` 解析成本次建图的保存目标，
实际写入发生在停止建图并保存时。只有临时绕过统一目录时，才传绝对 `map_path`。

建图模式下，下面这些是正常的：

```plain
slam_mode=mapping
ready_for_mapping=true
ready_for_navigation=false
localization_status=NOT_REQUIRED_IN_MAPPING
odom_status_code=null 时可能出现 warning: odom_status_not_published_in_mapping
```

原因：建图模式不是定位导航模式，不要求 `odom_status_code=2`。

---

## 7. 打开建图 RViz

终端 3：

```bash
cd ~/aurora_ws/flyAdapter || exit 1
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash

./scripts/open_rviz.sh mapping
```

等价命令：

```bash
rviz2 -d rviz/mapping_GR301AA0025.rviz \
  --ros-args \
  -r tf:=/GR301AA0025/tf \
  -r tf_static:=/GR301AA0025/tf_static
```

RViz 重点看：

| 内容 | 作用 |
| --- | --- |
| `/GR301AA0025/map` | 地图是否生成 |
| `/GR301AA0025/registered_scan` 或当前点云 | 当前雷达点云是否正常 |
| `/GR301AA0025/robot_pose` | 机器人位姿是否连续 |
| TF | map/odom/base/lidar 链路是否存在 |

如果 Map 左侧报红，先判断：

```bash
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash

ros2 topic list | grep /GR301AA0025/map
ros2 topic echo /GR301AA0025/map --once
ros2 topic echo /GR301AA0025/robot_pose --once
```

建图刚开始时地图还没有生成，Map 短时间报红可以接受；持续报红才继续查 topic / TF / RViz remap。

---

## 8. 用遥控器进行建图运动

开启建图模式后，用遥控器/手柄让机器人低速行走。

推荐路线：

1. 从起点缓慢出发。
2. 沿场地外圈走一圈。
3. 经过主要通道、门口、拐角。
4. 在关键区域做小闭环。
5. 回到起点附近闭环。

建图过程中每 30 秒检查一次：

```bash
curl http://127.0.0.1:8080/slam/status
curl http://127.0.0.1:8080/robot/readiness/mapping
```

正常重点：

```plain
ready_for_mapping=true
pose_age_sec 小于 3 秒
health.has_error=false
地图在 RViz 中持续增长
```

不要在建图阶段调用自动导航接口，也不要让程序控制机体运动。

---

## 9. 保存地图

建图路线完成后，让机器人停稳，然后保存地图：

```bash
curl -X POST http://127.0.0.1:8080/slam/stop_mapping \
  -H "Content-Type: application/json" \
  -d '{"map_name":"map"}'
```

保存 3D 点云地图可能需要几十秒；Adapter 默认等待 `MAP_SAVE_TIMEOUT_SEC=120` 秒。
如果仍然超时，优先在 HumanoidNav 终端看 `/slam/save_map` 是否仍在写盘、地图数据是否为空、目标磁盘是否可写。

检查地图：

```bash
curl http://127.0.0.1:8080/robot/map/list
ls -lah /opt/fftai/nav/map
```

继续条件：

```plain
地图目录存在；
能看到地图相关文件；
/robot/map/list 能列出该地图。
```

---

## 10. 加载地图进入定位模式

终端 4：

```bash
curl -X POST http://127.0.0.1:8080/slam/relocation \
  -H "Content-Type: application/json" \
  -d '{"map_name":"map","x":0,"y":0,"z":0,"yaw":0,"wait_for_localization":true}'
```

打开定位 RViz：

```bash
cd ~/aurora_ws/flyAdapter || exit 1
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash

./scripts/open_rviz.sh relocation
```

等价命令：

```bash
rviz2 -d rviz/relocation_GR301AA0025.rviz \
  --ros-args \
  -r tf:=/GR301AA0025/tf \
  -r tf_static:=/GR301AA0025/tf_static
```

检查定位：

```bash
curl http://127.0.0.1:8080/robot/localization/status
curl http://127.0.0.1:8080/robot/readiness/poi
```

如果初始位姿不对，在 RViz 里用 `2D Pose Estimate`，或者用接口发布初始位姿：

```bash
curl -X POST http://127.0.0.1:8080/robot/localization/initial_pose \
  -H "Content-Type: application/json" \
  -d '{"x":0,"y":0,"z":0,"yaw":0,"frame_id":"map"}'
```

继续条件：

```plain
slam_mode=localization；
odom_status_code=2；
localization_status=GOOD；
/robot/readiness/poi 返回 ready=true。
```

---

## 11. 手动打点

定位稳定后，继续用遥控器/手柄把机器人移动到需要打点的位置。

到点后让机器人停稳，保存当前位姿：

```bash
curl -X POST http://127.0.0.1:8080/slam/add_nav_point \
  -H "Content-Type: application/json" \
  -d '{"name":"lobby_01_start"}'
```

移动到下一个点后继续保存：

```bash
curl -X POST http://127.0.0.1:8080/slam/add_nav_point \
  -H "Content-Type: application/json" \
  -d '{"name":"lobby_02_frontdesk"}'
```

检查点位：

```bash
curl http://127.0.0.1:8080/slam/nav_points
```

保存点位文件：

```bash
curl -X POST http://127.0.0.1:8080/slam/save_nav_points
```

继续条件：

```plain
点位数量正确；
每个点位名称清楚；
点位坐标没有明显跳变。
```

---

## 12. 单点自动导航验证

从这里开始，运动控制从“遥控器手动行走”切到“HumanoidNav/Nav2 目标点导航”。

导航前检查：

```bash
curl http://127.0.0.1:8080/robot/readiness/navigation
curl http://127.0.0.1:8080/robot/motion/authority
```

默认 `MOTION_GUARD=none` 时，`/robot/motion/authority` 应该看到：

```plain
policy=none
aurora_required=false
auto_navigation_motion=nav2_goal
```

发送单点导航：

```bash
curl -X POST http://127.0.0.1:8080/robot/navigation/goto_poi \
  -H "Content-Type: application/json" \
  -d '{"name":"lobby_01_start","force":false}'
```

观察当前动作：

```bash
curl http://127.0.0.1:8080/robot/navigation/current_action
curl http://127.0.0.1:8080/slam/nav_status
```

取消导航：

```bash
curl -X POST http://127.0.0.1:8080/robot/navigation/cancel
```

默认策略下，取消导航只取消 Nav2 goal，不会额外调用 Aurora `stop_motion`。

继续条件：

```plain
机器人能朝目标点运动；
取消导航后底层 action 被取消；
RViz 中目标和当前位置合理。
```

---

## 13. 多点巡航

确认至少有 2 个点位：

```bash
curl http://127.0.0.1:8080/slam/nav_points
```

开始巡航：

```bash
curl -X POST http://127.0.0.1:8080/slam/start_cruise \
  -H "Content-Type: application/json" \
  -d '{"force":false}'
```

查看巡航状态：

```bash
curl http://127.0.0.1:8080/slam/nav_status
curl http://127.0.0.1:8080/slam/status
```

暂停、恢复、停止：

```bash
curl -X POST http://127.0.0.1:8080/slam/pause_nav
curl -X POST http://127.0.0.1:8080/slam/resume_nav
curl -X POST http://127.0.0.1:8080/slam/stop_cruise
```

建议验收顺序：

1. 先跑 2 个点的短路线。
2. 再跑 3 到 5 个点的中等路线。
3. 最后跑完整路线。

---

## 14. 可选：启用 Aurora 自动导航保护

只有在你明确希望程序导航前调用 Aurora `ensure_stand`、取消导航时调用 Aurora `stop_motion`，才启用这一段。

启动 AuroraCore 和 Aurora Agent 后，Adapter 使用：

```bash
cd ~/aurora_ws/flyAdapter || exit 1

source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash
source .venv/bin/activate

export ROBOT_NAMESPACE=GR301AA0025
export MOTION_GUARD=aurora
export AURORA_ENABLED=1
export AURORA_BACKEND=agent
export AURORA_AGENT_URL=http://127.0.0.1:18080

./scripts/run_adapter.sh
```

检查：

```bash
curl http://127.0.0.1:8080/robot/aurora/state
curl http://127.0.0.1:8080/robot/motion/authority
curl http://127.0.0.1:8080/robot/readiness/navigation
```

预期：

```plain
policy=aurora
aurora_required=true
aurora.connected=true
robot_standing=true
```

注意：建图和手动打点仍然推荐使用 `MOTION_GUARD=none`。遥控器接管时 AuroraCore 可能被挤掉，这种情况下不要把 Aurora 作为建图 blocker。

---

## 15. 背包接入验收

背包接入前跑一遍：

```bash
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/slam/status
curl http://127.0.0.1:8080/slam/pose
curl http://127.0.0.1:8080/slam/nav_points
curl http://127.0.0.1:8080/robot/workflow/status
curl http://127.0.0.1:8080/robot/readiness/navigation
```

关键结果：

```plain
healthz.ok=true
ros.ready=true
ready_for_mapping 在 mapping 模式下为 true
定位模式下 odom_status_code=2
点位数量正确
navigation_readiness.ready=true
motion_authority.policy 符合现场策略
```

Web 页面也可以点“运行验收检查”：

```plain
http://127.0.0.1:8080/
```

---

## 16. 常见状态解释

| 状态 | 是否正常 | 说明 |
| --- | --- | --- |
| `slam_mode=mapping` 且 `ready_for_navigation=false` | 正常 | 建图模式不是导航模式 |
| `localization_status=NOT_REQUIRED_IN_MAPPING` | 正常 | 建图不要求定位 GOOD |
| `odom_status_code=null` 且 warning 为 `odom_status_not_published_in_mapping` | 通常正常 | 建图阶段可能不发布定位质量 |
| `motion_authority.policy=none` | 默认正常 | Aurora 不参与控制权 |
| `aurora.backend=disabled` | 默认正常 | 手动建图/打点不依赖 Aurora |
| `localization_not_good` | 需要处理 | 加载地图后定位未 GOOD，不能自动导航 |
| `robot_pose_not_fresh` | 需要处理 | 位姿没有更新，检查 HumanoidNav 和 topic |
| `ros_bridge_not_ready` | 需要处理 | 检查 ROS setup 和 HumanoidNav |
| `aurora_unavailable` | 仅 aurora 策略下需要处理 | 默认 `MOTION_GUARD=none` 不应阻塞建图/打点 |

---

## 17. 收尾

停止巡航：

```bash
curl -X POST http://127.0.0.1:8080/slam/stop_cruise
```

保存点位：

```bash
curl -X POST http://127.0.0.1:8080/slam/save_nav_points
```

确认最后状态：

```bash
curl http://127.0.0.1:8080/slam/status
curl http://127.0.0.1:8080/robot/workflow/status
```

按顺序关闭：

```plain
1. 停止巡航或当前导航
2. 关闭 RViz
3. Ctrl+C 关闭 Adapter
4. Ctrl+C 关闭 HumanoidNav
5. 如果启用了 Aurora Agent / AuroraCore，再关闭它们
```
