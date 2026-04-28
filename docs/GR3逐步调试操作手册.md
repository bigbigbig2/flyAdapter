# GR3 适配服务逐步调试操作手册

## 0. 先明确一件事

本适配服务不是导航核心。它只是 HTTP 适配层。

接口是否能真正调用成功，取决于下面三层是否都起来：

```plain
AuroraCore
  负责底层机体 / FSM / 站立 / DDS

HumanoidNav
  负责 ROS2 建图 / 定位 / Nav2 导航

GR3 Adapter
  负责对背包暴露 Unitree 兼容 HTTP API
```

所以正确调试顺序一定是：

```plain
1. 先确认网络和 SSH
2. 启动 AuroraCore
3. 启动 HumanoidNav，必须使用 namespace GR301AA0025
4. 确认 ROS2 topic/service/action 存在
5. 启动 GR3 Adapter
6. 先测 /healthz 和 /robot/status
7. 加载地图，进入 localization
8. 确认 robot_pose / odom_status_code
9. 再测导航 / 巡航
```

全程统一命名空间：

```bash
NS=/GR301AA0025
```

适配服务环境变量写法不带开头斜杠也可以：

```bash
export ROBOT_NAMESPACE=GR301AA0025
```

代码内部会自动转成 `/GR301AA0025`。

---

## 1. 网络和登录检查

在外部 PC 上：

```bash
ping 192.168.137.220 -c 4
ssh gr301ab0113@192.168.137.220
```

如果 SSH 不通，先不要看 adapter。HTTP 接口一定也不会通。

如果机器人要安装依赖，还要确认外网：

```bash
ping 8.8.8.8 -c 4
ping pypi.org -c 4
```

外网不通时，先按 `docs/真机网络问题.md` 处理 NAT / 默认网关 / DNS。

---

## 2. 启动 AuroraCore

终端一：

```bash
sudo docker start fourier_aurora_server
sudo docker exec -it fourier_aurora_server bash

cd /workspace
sed -i 's/RobotName:.*/RobotName: gr3v233/g' config/config.yaml
sed -i 's/RunType:.*/RunType: 1/g' config/config.yaml

AuroraCore --config config/config.yaml
```

这个终端不要关。

如果后面 `/robot/aurora/state` 显示 unavailable，常见原因是：

- AuroraCore 没启动。
- 当前用户没有 docker 权限。
- Aurora SDK 只能在指定环境/容器内调用。

docker 权限问题可以先处理：

```bash
sudo usermod -aG docker gr301ab0113
newgrp docker
```

必要时重启登录会话。

---

## 3. 启动 HumanoidNav

终端二：

```bash
ssh -X gr301ab0113@192.168.137.220

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

注意：

- 不要再混用 `GR301AB0025`。
- 不要这个终端用 namespace，另一个终端不用 namespace。
- adapter、load_map、RViz、ros2 topic/service/action 检查都要使用同一个 namespace。

---

## 4. 检查 HumanoidNav 是否真的起来

终端三：

```bash
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash
export NS=/GR301AA0025
```

先看 ROS2 命令是否可用：

```bash
which ros2
ros2 --help >/dev/null && echo ROS2_OK
```

再看核心接口是否存在：

```bash
ros2 service list | egrep "$NS/(slam/set_mode|slam/load_map|slam/save_map|cancel_current_action|get_current_action)"
ros2 action list | grep "$NS/navigate_to_pose"
ros2 topic list | egrep "$NS/(robot_pose|odom|odom_status_code|odom_status_score|action_status|Humanoid_nav/health|Humanoid_nav/events|slam/mode_status|map|scan)"
```

如果这些查不到，adapter 调 `/slam/relocation`、`/slam/navigate_to` 必然不通。  
这时问题在 HumanoidNav 启动或 namespace，不在 FastAPI。

---

## 5. 启动 GR3 Adapter

终端四：

```bash
cd ~/aurora_ws/gr3

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash

export ROBOT_NAMESPACE=GR301AA0025
export ADAPTER_HOST=0.0.0.0
export ADAPTER_PORT=8080

./scripts/run_adapter.sh
```

启动成功后先测：

```bash
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/slam/status
curl http://127.0.0.1:8080/robot/status
curl http://127.0.0.1:8080/robot/readiness
```

预期：

- `/healthz` 通：说明 FastAPI 活着。
- `/slam/status` 通：说明 Unitree 兼容接口活着。
- `/robot/status` 里 `ros.ready=true`：说明 adapter 找到了 ROS2 Python 环境和 HumanoidNav 消息类型。
- `/robot/readiness` 可能还不是 ready，因为地图/定位还没完成。

如果 `/healthz` 通但 `/robot/status` 显示：

```plain
ros_python_unavailable
ros_bridge_not_ready
```

优先检查 adapter 启动前有没有 source：

```bash
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash
```

---

## 6. 加载地图进入定位模式

推荐先用官方脚本验证底层能通：

```bash
cd /opt/fftai/humanoidnav
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash

./scripts/load_map.sh \
  --map-path /opt/fftai/nav/map \
  --namespace GR301AA0025
```

看到类似：

```plain
Successfully loaded map and switched to localization mode
```

再检查：

```bash
timeout 5s ros2 topic echo /GR301AA0025/slam/mode_status --once
timeout 5s ros2 topic echo /GR301AA0025/robot_pose --once
timeout 5s ros2 topic echo /GR301AA0025/odom_status_code --once
timeout 5s ros2 topic echo /GR301AA0025/odom_status_score --once
```

`odom_status_code` 常见含义：

```plain
0 = IDLE
1 = INITIALIZING
2 = GOOD
3 = FOLLOWING_DR
4 = FAIL
```

只有 `2 = GOOD` 才适合导航。

也可以通过 adapter 加载：

```bash
curl -X POST http://127.0.0.1:8080/slam/relocation \
  -H "Content-Type: application/json" \
  -d '{"map_path":"/opt/fftai/nav/map","x":0,"y":0,"z":0,"yaw":0,"wait_for_localization":false}'
```

---

## 7. 检查 readiness

```bash
curl http://127.0.0.1:8080/robot/readiness
```

常见 blocker：

| blocker | 含义 | 处理 |
| --- | --- | --- |
| `ros_python_unavailable` | adapter 没拿到 ROS2 Python 环境 | 重新 source ROS2 和 HumanoidNav 后启动 adapter |
| `ros_bridge_not_ready` | ROS bridge 线程未 ready | 看 adapter 日志，确认 fourier/nav2 消息包可 import |
| `map_not_loaded` | adapter 没记录当前地图 | 调 `/slam/relocation` 或 `/robot/map/load` |
| `robot_pose_not_fresh` | `/robot_pose` 没数据或太旧 | 检查 localization、TF、odom |
| `localization_not_good` | `odom_status_code != 2` | 等定位完成或重新设置初始位姿 |
| `health_error` | HumanoidNav health 有 error/fatal | 查 `/GR301AA0025/Humanoid_nav/health` |
| `aurora_unavailable` | Aurora SDK 不可用 | 检查 AuroraCore、SDK、docker 权限 |
| `robot_not_standing` | 机器人未站立 | 调 `/robot/aurora/ensure_stand` |

---

## 8. 测试 Aurora

```bash
curl http://127.0.0.1:8080/robot/aurora/ping
curl http://127.0.0.1:8080/robot/aurora/state
curl -X POST http://127.0.0.1:8080/robot/aurora/ensure_stand
```

如果 Aurora SDK 当前还没接上，但你想先调 HTTP 页面，可以临时：

```bash
export AURORA_MOCK=1
./scripts/run_adapter.sh
```

真机正式联调不建议长期使用 mock。

---

## 9. 保存导航点

机器人站到目标点后：

```bash
curl -X POST http://127.0.0.1:8080/slam/add_nav_point \
  -H "Content-Type: application/json" \
  -d '{"name":"front_desk"}'
```

查看点位：

```bash
curl http://127.0.0.1:8080/slam/nav_points
```

点位会保存到：

```plain
gr3/data/navigation_points.json
```

---

## 10. 测试单点导航

先确认 readiness：

```bash
curl http://127.0.0.1:8080/robot/readiness
```

再导航：

```bash
curl -X POST http://127.0.0.1:8080/slam/navigate_to \
  -H "Content-Type: application/json" \
  -d '{"name":"debug_target","x":1.0,"y":2.0,"yaw":0.0}'
```

查看当前动作：

```bash
curl http://127.0.0.1:8080/robot/navigation/current_action
```

取消：

```bash
curl -X POST http://127.0.0.1:8080/slam/stop_cruise
curl -X POST http://127.0.0.1:8080/robot/navigation/cancel
```

---

## 11. 测试巡航

确保已经保存多个点：

```bash
curl http://127.0.0.1:8080/slam/nav_points
```

启动巡航：

```bash
curl -X POST http://127.0.0.1:8080/slam/start_cruise
```

查看状态：

```bash
curl http://127.0.0.1:8080/slam/nav_status
```

监听事件：

```bash
curl -N http://127.0.0.1:8080/slam/events
```

暂停 / 恢复 / 停止：

```bash
curl -X POST http://127.0.0.1:8080/slam/pause_nav
curl -X POST http://127.0.0.1:8080/slam/resume_nav
curl -X POST http://127.0.0.1:8080/slam/stop_cruise
```

---

## 12. Web 调试页

浏览器打开：

```plain
http://机器人IP:8080/
```

Swagger 打开：

```plain
http://机器人IP:8080/docs
```

Web 页面用于现场快速观察：

- adapter 是否在线。
- ROS bridge 是否 ready。
- Aurora 是否可用。
- 当前地图、定位状态、巡航状态。
- SSE 事件流。
- 保存点位、加载地图、单点导航、巡航。

---

## 13. 最小冒烟测试顺序

如果你只想快速判断链路通不通，按这个最小顺序：

```bash
# 1. adapter 是否活着
curl http://127.0.0.1:8080/healthz

# 2. Unitree 兼容接口是否活着
curl http://127.0.0.1:8080/slam/status

# 3. ROS bridge 是否拿到 HumanoidNav
curl http://127.0.0.1:8080/robot/status

# 4. 看为什么还不能导航
curl http://127.0.0.1:8080/robot/readiness

# 5. 底层 service/action 是否存在
ros2 service list | egrep "/GR301AA0025/(slam/load_map|slam/save_map|cancel_current_action|get_current_action)"
ros2 action list | grep /GR301AA0025/navigate_to_pose

# 6. 定位是否有数据
timeout 5s ros2 topic echo /GR301AA0025/robot_pose --once
timeout 5s ros2 topic echo /GR301AA0025/odom_status_code --once
```

这套顺序比直接点 Web 页面更可靠，因为它能明确定位问题在哪一层。
