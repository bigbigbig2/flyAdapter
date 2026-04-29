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

python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements.txt

source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash
python -c "import numpy; import rclpy; print('PY_ROS_IMPORT_OK')"

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

先看具体错误。如果错误类似：

```plain
ROS2 Python imports unavailable: No module named 'numpy'
```

说明 HumanoidNav 底层已经可能起来了，但 adapter 当前 `.venv` 里缺 ROS2 Python 消息依赖需要的 `numpy`。处理方式：

```bash
cd ~/aurora_ws/gr3
source .venv/bin/activate
pip install -r requirements.txt
python -c "import numpy; print(numpy.__version__)"
```

如果机器人现场没有外网，优先使用系统包并让虚拟环境能看到系统 Python 包：

```bash
sudo apt install python3-numpy
deactivate 2>/dev/null || true
rm -rf .venv
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -r requirements.txt
python -c "import numpy; import rclpy; print('PY_ROS_IMPORT_OK')"
```

然后重启 adapter。

如果不是 `numpy`，再优先检查 adapter 启动前有没有 source：

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

## 6.1 你当前这种输出怎么判断

如果你看到类似下面的组合：

```plain
/robot/status 里 ros.available=false
last_error="ROS2 Python imports unavailable: No module named 'numpy'"

ros2 service list 能看到 /GR301AA0025/slam/load_map
ros2 action list 能看到 /GR301AA0025/navigate_to_pose
ros2 topic echo /GR301AA0025/robot_pose 有数据
ros2 topic echo /GR301AA0025/odom_status_code 显示 data: 1
```

结论是：

- HumanoidNav 底层服务已经起来了。
- namespace `GR301AA0025` 是对的。
- Adapter 没接上 ROS2，不是因为 ROS2 不通，而是因为 adapter 的 Python 虚拟环境缺 `numpy`。
- `odom_status_code=data: 1` 表示定位还在 `INITIALIZING`，还不是 `GOOD`。修好 adapter 后，readiness 仍会等到 code 变为 `2` 才允许正常导航。

处理顺序：

```bash
cd ~/aurora_ws/gr3
source .venv/bin/activate
pip install -r requirements.txt
python -c "import numpy; import rclpy; print('PY_ROS_IMPORT_OK')"

# 停掉旧 adapter 后重启
export ROBOT_NAMESPACE=GR301AA0025
./scripts/run_adapter.sh
```

重启后再测：

```bash
curl http://127.0.0.1:8080/robot/status
curl http://127.0.0.1:8080/robot/readiness
```

这时 `/robot/status` 里应该至少变成：

```plain
ros.available=true
ros.ready=true
```

如果 `odom_status_code` 还是 `1`，继续做地图加载、初始位姿和定位质量排查。

---

## 7. 检查 readiness

```bash
curl http://127.0.0.1:8080/robot/readiness
```

常见 blocker / warning：

| 项目 | 含义 | 处理 |
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

先测 Aurora Agent：

```bash
curl http://127.0.0.1:18080/health
curl http://127.0.0.1:18080/state
```

再测 Adapter 暴露的 Aurora facade：

```bash
curl http://127.0.0.1:8080/robot/aurora/ping
curl http://127.0.0.1:8080/robot/aurora/state
curl -X POST http://127.0.0.1:8080/robot/aurora/ensure_stand
```

如果返回类似：

```json
{
  "connected": false,
  "mock": false,
  "backend": "agent",
  "fsm_state": null,
  "standing": false,
  "error": "Aurora agent unavailable: [Errno 111] Connection refused"
}
```

结论是：主 Adapter 活着，但 Aurora Agent 没启动或 URL 不对。检查：

```bash
export AURORA_AGENT_URL=http://127.0.0.1:18080
curl http://127.0.0.1:18080/health
```

如果 Agent `/health` 返回类似：

```json
{
  "available": false,
  "connected": false,
  "error": "cannot import AuroraClient from candidates: fourier_aurora_client.AuroraClient: No module named 'fourier_msgs.msg.AuroraCmd'"
}
```

结论是：Agent 所在环境仍不是正确的 Aurora SDK 环境。此时不要改主 Adapter，要把 Agent 放到能正确 import Aurora SDK 和 `AuroraCmd` 消息的环境里。当前脚本会默认清理继承来的 HumanoidNav overlay；如果清理后仍失败，看 Agent `/health` 里的 `module_diagnostics`，确认 `fourier_msgs` 实际加载路径是不是还指向 HumanoidNav。

Aurora Agent 启动参数：

```bash
export AURORA_DOMAIN_ID=123
export AURORA_ROBOT_NAME=gr3v233
export AURORA_CLIENT_MODULE=fourier_aurora_client
export AURORA_CLIENT_CLASS=AuroraClient
export AURORA_STAND_FSM_STATE=2
export AURORA_ENV_CLEAN=1
```

如果现场 Aurora SDK 只能在 `fourier_aurora_server` 容器里使用，就在容器里启动 Agent，而不是把主 Adapter 放进去：

```bash
sudo docker exec -it fourier_aurora_server bash
cd /workspace/gr3   # 或现场实际挂载的 gr3 目录
export PYTHONPATH=$PWD:$PYTHONPATH
python -c "from fourier_aurora_client import AuroraClient; print(AuroraClient)"
./scripts/run_aurora_agent.sh
```

Agent 启动后重测 Adapter：

```bash
curl http://127.0.0.1:8080/robot/aurora/state
curl -X POST http://127.0.0.1:8080/robot/aurora/ensure_stand
```

预期返回里会带：

```plain
backend=agent
connected=true
fsm_state=1/2/...
```

### 8.1 临时先调 HTTP / ROS

如果当前目标只是调背包 HTTP、地图、定位、导航，可以先保持：

```bash
export REQUIRE_AURORA=0
```

这种情况下 `/robot/readiness` 会把 `aurora_unavailable` 放在 warnings，不会因为 Aurora Agent 缺失直接阻塞导航。

如果只是想测试 Web 页面的 Aurora 按钮响应，可以临时 mock：

```bash
export AURORA_MOCK=1
./scripts/run_adapter.sh
```

真机正式联调不要长期使用 mock。

### 8.2 SDK 路径或模块名不同

这些变量只给 Aurora Agent 使用：

```bash
export AURORA_SDK_PATH=/path/to/aurora/python
export AURORA_CLIENT_MODULE=fourier_aurora_client
export AURORA_CLIENT_CLASS=AuroraClient
./scripts/run_aurora_agent.sh
```

也可以按实际模块名改成：

```bash
export AURORA_CLIENT_MODULE=aurora_sdk
export AURORA_CLIENT_CLASS=AuroraClient
```

重启 Agent 后再看：

```bash
curl http://127.0.0.1:18080/state
curl http://127.0.0.1:8080/robot/aurora/state
```

预期至少看到：

```plain
connected=true
fsm_state=1/2/3/...
```

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

## 12.1 RViz 看不到 map / TF 的排查

如果 RViz 反复打印：

```plain
无法获取变换: "map" passed to lookupTransform argument target_frame does not exist
Message Filter dropping message: frame 'odom' ...
```

先按下面顺序判断。

第一，确认 TF 话题在 namespace 下有数据：

```bash
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash

timeout 5s ros2 topic echo /GR301AA0025/tf --once
timeout 5s ros2 topic echo /GR301AA0025/tf_static --once
```

第二，用带绝对 topic remap 的 `tf2_echo` 看 `map -> odom` 是否存在：

```bash
ros2 run tf2_ros tf2_echo map odom \
  --ros-args \
  -r tf:=/GR301AA0025/tf \
  -r tf_static:=/GR301AA0025/tf_static
```

如果这里一直查不到 `map -> odom`，说明定位链路还没建立，不是 RViz 页面问题。继续检查：

```bash
timeout 5s ros2 topic echo /GR301AA0025/odom_status_code --once
timeout 5s ros2 topic echo /GR301AA0025/slam/mode_status --once
```

`odom_status_code=1` 是 `INITIALIZING`，RViz 可能还拿不到完整 TF。需要先 `load_map`，必要时设置初始位姿，直到 `odom_status_code=2`。

第三，启动 RViz 时使用绝对 remap：

```bash
rviz2 -d ~/aurora_ws/navigation_view_GR301AA0025.rviz \
  --ros-args \
  -r tf:=/GR301AA0025/tf \
  -r tf_static:=/GR301AA0025/tf_static
```

打开后 Fixed Frame 仍然用：

```plain
map
```

不是 `/GR301AA0025/map`。namespace 是 topic 名称前缀，TF frame 名通常还是 `map`、`odom`、`base_link`、`lidar_link`。

这里保留现场已经验证过的 RViz 写法 `tf:=...` 和 `tf_static:=...`。如果 RViz 仍然提示 `map` frame 不存在，优先排查定位链路是否已经建立 `map -> odom`，不要先改 RViz 启动命令。

RViz 里的 GLSL 报错：

```plain
active samplers with a different type refer to the same texture image unit
```

通常是显卡/OpenGL 驱动和 RViz 地图显示相关的渲染警告。它不是本次链路的主因，主因还是 TF 里暂时没有可用的 `map` frame 或 RViz 没订阅到 namespace 下的 `/tf`。

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
