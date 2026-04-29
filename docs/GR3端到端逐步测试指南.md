# GR3 端到端逐步测试指南

本文档用于在 Aurora Agent、HumanoidNav、GR3 Adapter 都已经能启动的前提下，按层验证整条链路是否可用于背包接入。

默认命名空间统一为：

```bash
GR301AA0025
```

建议按顺序测试，不要跳步。每一步都先看“预期结果”，不符合预期时先停在当前层排查。

---

## 0. 终端约定

建议开 4 个终端：

```plain
终端 1：AuroraCore
终端 2：HumanoidNav
终端 3：Aurora Agent
终端 4：GR3 Adapter / curl 测试
```

如果工程实际目录不是 `~/aurora_ws/gr3`，把下面命令里的目录替换成现场真实目录。不要在 `cd` 失败后继续执行。

---

## 1. 启动 AuroraCore

终端 1：

```bash
sudo docker start fourier_aurora_server
sudo docker exec -it fourier_aurora_server bash

cd /workspace || exit 1
grep -E "DomainID|RobotName|RunType" config/config.yaml

AuroraCore --config config/config.yaml
```

预期结果：

- AuroraCore 持续运行，不退出。
- `RobotName` 与后续 `AURORA_ROBOT_NAME` 一致。
- `DomainID` 与后续 `AURORA_DOMAIN_ID` 一致。

如果后面 Agent 报 `Timeout waiting for subscribers to be matched`，第一优先回来检查这里。

---

## 2. 启动 HumanoidNav

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

预期结果：

- 进程持续运行。
- 不要混用其他 namespace。

---

## 3. 检查 HumanoidNav ROS2 接口

终端 4：

```bash
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash
export NS=/GR301AA0025

ros2 service list | egrep "$NS/(slam/set_mode|slam/load_map|slam/save_map|cancel_current_action|get_current_action)"
ros2 action list | grep "$NS/navigate_to_pose"
ros2 topic list | egrep "$NS/(robot_pose|odom_status_code|odom_status_score|slam/mode_status|map|scan)"
```

预期至少看到：

```plain
/GR301AA0025/slam/set_mode
/GR301AA0025/slam/load_map
/GR301AA0025/slam/save_map
/GR301AA0025/navigate_to_pose
/GR301AA0025/robot_pose
/GR301AA0025/odom_status_code
```

继续检查关键 topic 是否有数据：

```bash
timeout 5s ros2 topic echo /GR301AA0025/robot_pose --once
timeout 5s ros2 topic echo /GR301AA0025/odom_status_code --once
timeout 5s ros2 topic echo /GR301AA0025/slam/mode_status --once
```

预期结果：

- `robot_pose` 能输出位姿。
- `odom_status_code` 有输出。
- `slam/mode_status` 有输出。

---

## 4. 启动 Aurora Agent

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

预期结果：

```plain
[aurora-agent] fourier_msgs.msg.AuroraCmd: ...
[aurora-agent] starting on 127.0.0.1:18080
```

单独检查：

```bash
curl http://127.0.0.1:18080/health
curl http://127.0.0.1:18080/state
curl http://127.0.0.1:18080/diagnostics
```

预期结果：

- `import_attempts` 里有 `fourier_aurora_client.AuroraClient: ok`。
- `connected=true` 更理想。
- 如果短时间内 `connected=false` 但有 `connect_retry_after_sec`，说明 Agent 在退避重试。

如果出现：

```plain
Timeout waiting for subscribers to be matched
Unmatched subscriber: rt/aurora_state
```

说明 Python SDK 已经 OK，但 DDS 没匹配到 AuroraCore。检查 AuroraCore 是否运行、`DomainID`/`RobotName` 是否一致、Agent 是否应该放进同一个 docker 容器运行。

修正后可重置 Agent 客户端：

```bash
curl -X POST http://127.0.0.1:18080/reset
```

---

## 5. 启动 GR3 Adapter

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

预期结果：

- Adapter 监听 `0.0.0.0:8080`。
- 没有 `ROS2 Python imports unavailable`。

---

## 6. Adapter 基础冒烟测试

另开一个测试终端：

```bash
curl http://127.0.0.1:8080/healthz
curl http://127.0.0.1:8080/slam/status
curl http://127.0.0.1:8080/robot/status
curl http://127.0.0.1:8080/robot/readiness
```

预期结果：

- `/healthz` 返回 `ok=true`。
- `/slam/status` 能返回兼容背包的状态。
- `/robot/status` 里：
  - `ros.available=true`
  - `ros.ready=true`
  - `aurora.backend=agent`
  - `adapter.namespace=/GR301AA0025`

如果 `/robot/readiness.ready=false`，不要急着认为服务坏了，先看 `blockers`：

```plain
localization_not_good    定位还没 GOOD
robot_pose_not_fresh     robot_pose 没新数据
aurora_unavailable       Aurora Agent / AuroraCore 未连通
```

---

## 7. Aurora 控制测试

先看状态：

```bash
curl http://127.0.0.1:8080/robot/aurora/state
```

测试站立：

```bash
curl -X POST http://127.0.0.1:8080/robot/aurora/ensure_stand
```

测试停止运动：

```bash
curl -X POST http://127.0.0.1:8080/robot/aurora/stop_motion
```

预期结果：

- `success=true` 表示 Agent 已成功调用 Aurora SDK。
- `fsm_state=2` 或 `standing=true` 表示站立状态正常。
- 如果 AuroraCore 重启过，先执行：

```bash
curl -X POST http://127.0.0.1:8080/robot/aurora/reset
curl http://127.0.0.1:8080/robot/aurora/state?force_refresh=true
```

---

## 8. 地图和定位测试

先加载地图进入定位：

```bash
curl -X POST http://127.0.0.1:8080/robot/map/load \
  -H "Content-Type: application/json" \
  -d '{
    "map_path": "/opt/fftai/nav/map",
    "x": 0,
    "y": 0,
    "z": 0,
    "yaw": 0,
    "wait_for_localization": true
  }'
```

检查定位：

```bash
curl http://127.0.0.1:8080/robot/localization/status
curl http://127.0.0.1:8080/robot/readiness
```

预期结果：

- `slam_mode` 应该是 `localization` 或类似定位模式。
- `pose_age_sec` 小于 3 秒。
- `odom_status_code=2` 表示定位 GOOD。

如果 `odom_status_code` 不是 2，先不要测导航，先处理地图、初始位姿、定位质量。

---

## 9. 导航预检

```bash
curl -X POST http://127.0.0.1:8080/robot/navigation/precheck \
  -H "Content-Type: application/json" \
  -d '{"force": false}'
```

预期结果：

```json
{
  "ok": true
}
```

如果 `ok=false`，看 `readiness.blockers`，常见处理：

| blocker | 处理 |
| --- | --- |
| `localization_not_good` | 等定位变好或重新加载地图/设置初始位姿 |
| `robot_pose_not_fresh` | 检查 `/GR301AA0025/robot_pose` |
| `aurora_unavailable` | 检查 Aurora Agent / AuroraCore |
| `robot_not_standing` | 调 `/robot/aurora/ensure_stand` |

---

## 10. 保存当前点位

站到一个安全位置后保存点位：

```bash
curl -X POST http://127.0.0.1:8080/slam/add_nav_point \
  -H "Content-Type: application/json" \
  -d '{"name":"test_point_1"}'
```

查看点位：

```bash
curl http://127.0.0.1:8080/slam/nav_points
curl http://127.0.0.1:8080/robot/poi/list
```

预期结果：

- 能看到 `test_point_1`。
- 点位坐标来自当前 `robot_pose`。

---

## 11. 单点导航测试

建议先选近距离、安全、无遮挡目标。

按 POI 名称导航：

```bash
curl -X POST http://127.0.0.1:8080/robot/navigation/goto_poi \
  -H "Content-Type: application/json" \
  -d '{"name":"test_point_1","force":false}'
```

查看导航状态：

```bash
curl http://127.0.0.1:8080/slam/nav_status
curl http://127.0.0.1:8080/robot/navigation/current_action
```

取消导航：

```bash
curl -X POST http://127.0.0.1:8080/robot/navigation/cancel
```

预期结果：

- `goto_poi` 返回 `status=success` 或底层 action accepted。
- `current_action` 能看到当前 action 状态。
- `cancel` 后机器人停止导航，并触发 Aurora `stop_motion` 兜底。

---

## 12. 背包兼容接口测试

背包主要会走 Unitree 兼容接口，单独测：

```bash
curl http://127.0.0.1:8080/slam/status
curl http://127.0.0.1:8080/slam/nav_status
curl http://127.0.0.1:8080/slam/nav_points
```

启动巡航前至少准备 2 个点位，然后：

```bash
curl -X POST http://127.0.0.1:8080/slam/start_nav
curl http://127.0.0.1:8080/slam/nav_status
curl -X POST http://127.0.0.1:8080/slam/stop_nav
```

预期结果：

- `/slam/status` 字段保持背包兼容。
- `start_nav` 会按本地导航点顺序执行。
- `stop_nav` 能取消底层导航并停止机体运动。

---

## 13. Web 和 Swagger 测试

浏览器打开：

```plain
http://<robot-ip>:8080/
http://<robot-ip>:8080/docs
```

重点看：

- Swagger 接口中文描述是否正常。
- Web 调试页状态是否能刷新。
- Aurora 按钮、地图加载、POI、导航状态是否能正常返回。

---

## 14. 最小合格标准

整条链路算通过，需要满足：

```plain
1. Aurora Agent 能 import SDK，且 /state connected=true
2. ROS2 service/action/topic 都在 /GR301AA0025 下可见
3. Adapter /healthz、/slam/status、/robot/status 都正常
4. /robot/readiness 没有 blocker，或 blocker 原因明确
5. 地图加载成功，定位 GOOD：odom_status_code=2
6. /robot/aurora/ensure_stand success=true
7. 单点导航能 accepted，cancel 能停止
8. /slam/... 兼容接口可供背包调用
```

