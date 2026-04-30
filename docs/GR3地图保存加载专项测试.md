# GR3 地图保存加载专项测试

本文档专门用于排查 GR3 Adapter 的地图保存、地图加载、保存路径和 HumanoidNav 官方脚本之间的差异。

核心结论先放前面：

```plain
MAP_ROOT=/home/gr301ab0113/aurora_ws/flyAdapter/data/maps
DEFAULT_MAP_NAME=map
map_name=xxx  =>  /home/gr301ab0113/aurora_ws/flyAdapter/data/maps/xxx
map_name=map  =>  /home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map
```

`DEFAULT_MAP_NAME=map` 不是“把新地图保存到 `.../maps/map/xxx` 下面”，而是“默认地图名叫 `map`”。当前 Adapter 把 `MAP_ROOT` 当作地图集合根目录，因此传 `map_name=mmmmmmap` 时，目标路径就是 `/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/mmmmmmap`。

统一约定：Adapter 默认保存、加载、地图列表、打点关联和巡航关联都走 `/home/gr301ab0113/aurora_ws/flyAdapter/data/maps`。只有临时兼容旧目录时才传绝对 `map_path`。

---

## 1. 路径规则

Adapter 里有两种地图输入：

| 输入 | Adapter 解析后的目标路径 | 说明 |
| --- | --- | --- |
| `map_name=map` | `/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map` | 默认地图 |
| `map_name=mmmmmmap` | `/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/mmmmmmap` | 与 `map` 同级的新地图 |
| `map_path=/some/absolute/path` | `/some/absolute/path` | 绝对路径，绕过 `MAP_ROOT/map_name` 规则 |

当前 `map_name` 只允许单级名称，不允许带 `/`。也就是说不能传：

```json
{"map_name":"map/xxx"}
```

如果要嵌套路径，只能用：

```json
{"map_path":"/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map/xxx"}
```

---

## 2. 保存时 `map_file` 和 `save_map_id` 的区别

保存地图时有两个概念：

| 字段 | 含义 |
| --- | --- |
| `map_file` | Adapter 认为这张地图后续应该从哪里加载 |
| `save_map_id` | 实际发给 HumanoidNav `SaveMap.map_id` 的值 |

`MAP_SAVE_ID_MODE` 决定 `save_map_id` 怎么发：

| 配置 | 请求 | `map_file` | `save_map_id` |
| --- | --- | --- | --- |
| `name` | `{"map_name":"xxx"}` | `/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/xxx` | `xxx` |
| `path` | `{"map_name":"xxx"}` | `/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/xxx` | `/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/xxx` |
| 任意 | `{"map_path":"/some/absolute/path"}` | `/some/absolute/path` | `/some/absolute/path` |

现场默认应使用绝对路径模式，避免 HumanoidNav 将相对 `map_id` 写入无权限的 `./data/...`：

```bash
export MAP_SAVE_ID_MODE=path
```

或者保存时直接传 `map_path`。

---

## 3. 测试前确认

先确认 HumanoidNav 和 Adapter 使用同一个 namespace：

```bash
export NS=/GR301AA0025

ros2 service list | egrep "$NS/(slam/set_mode|slam/load_map|slam/save_map)"
ros2 topic list | egrep "$NS/(robot_pose|slam/mode_status|odom_status_code)"
```

Adapter 状态：

```bash
curl http://127.0.0.1:8080/robot/status
curl http://127.0.0.1:8080/robot/map/config
```

重点看：

```plain
map_root=/home/gr301ab0113/aurora_ws/flyAdapter/data/maps
default_map_name=map
default_map_path=/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map
save_id_mode=name 或 path
```

---

## 4. 加载已有地图测试

先用 HumanoidNav 官方脚本验证底层能加载：

```bash
cd /opt/fftai/humanoidnav || exit 1
source /opt/ros/humble/setup.bash
source /opt/fftai/humanoidnav/install/setup.bash

./scripts/load_map.sh \
  --map-path /home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map/ \
  --namespace GR301AA0025
```

注意：`load_map.sh` 是 HumanoidNav 工程里的脚本，不在 `~/aurora_ws/flyAdapter/scripts/` 下。必须先 `cd /opt/fftai/humanoidnav`，否则会出现：

```plain
bash: ./scripts/load_map.sh: No such file or directory
```

如果脚本输出是：

```plain
[load_map] Calling /slam/load_map service...
waiting for service to become available...
```

说明这次脚本没有使用 `GR301AA0025` 命名空间，正在等非命名空间的 `/slam/load_map`。现场服务通常在 `/GR301AA0025/slam/load_map`，必须加：

```bash
--namespace GR301AA0025
```

正确输出应当显示正在调用 `/GR301AA0025/slam/load_map`，或者至少能在同一终端看到：

```bash
ros2 service list | grep /GR301AA0025/slam/load_map
```

如果脚本输出是：

```plain
[load_map] Calling /GR301AA0025/slam/load_map service...
waiting for service to become available...
requester: making request: fourier_msgs.srv.LoadMap_Request(...)

response:
fourier_msgs.srv.LoadMap_Response(result=0, message='Successfully loaded map and switched to localization mode')
```

这是成功。`waiting for service to become available...` 只是 `ros2 service call` 在等待匹配服务，后面出现 `requester` 和 `response result=0` 才是最终结果。

然后用 Adapter 走同一张地图：

```bash
curl -X POST http://127.0.0.1:8080/slam/relocation \
  -H "Content-Type: application/json" \
  -d '{"map_path":"/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map/","x":0,"y":0,"z":0,"yaw":0,"wait_for_localization":false}'
```

预期：

```plain
result.success=true
result.map_file=/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map
result.map_name=map
slam_mode 变成 localization 或定位相关状态
```

如果 Adapter 返回 timeout，但官方脚本很快成功，重点对比 Adapter 进程和官方脚本终端的 ROS 环境：

```bash
echo $ROS_DOMAIN_ID
echo $RMW_IMPLEMENTATION
ps -ef | grep -E "uvicorn|run_adapter|gr3_adapter" | grep -v grep
curl http://127.0.0.1:8080/robot/status
```

---

## 5. 保存新地图到 `/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/xxx`

这是当前 Adapter 的默认目录模型。

启动 Adapter 时建议：

```bash
export ROBOT_NAMESPACE=GR301AA0025
export MAP_ROOT=/home/gr301ab0113/aurora_ws/flyAdapter/data/maps
export DEFAULT_MAP_NAME=map
export MAP_SAVE_ID_MODE=path
export MAP_LOAD_TIMEOUT_SEC=10
export MAP_SAVE_TIMEOUT_SEC=10
```

开始建图：

```bash
curl -X POST http://127.0.0.1:8080/slam/start_mapping \
  -H "Content-Type: application/json" \
  -d '{"map_name":"test_save_001"}'
```

检查状态：

```bash
curl http://127.0.0.1:8080/slam/status
curl http://127.0.0.1:8080/robot/readiness/mapping
```

完成建图运动后保存：

```bash
curl -X POST http://127.0.0.1:8080/slam/stop_mapping \
  -H "Content-Type: application/json" \
  -d '{"map_name":"test_save_001"}'
```

预期：

```plain
result.success=true
result.map_file=/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/test_save_001
result.save_map_id=/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/test_save_001
```

检查文件：

```bash
ls -lah /home/gr301ab0113/aurora_ws/flyAdapter/data/maps/test_save_001
curl http://127.0.0.1:8080/robot/map/list
```

---

## 6. 保存新地图到 `/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map/xxx`

如果现场明确要求保存到 `/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map/xxx`，不要用 `map_name`，直接用绝对 `map_path`：

```bash
curl -X POST http://127.0.0.1:8080/slam/start_mapping \
  -H "Content-Type: application/json" \
  -d '{"map_path":"/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map/test_save_001"}'
```

保存：

```bash
curl -X POST http://127.0.0.1:8080/slam/stop_mapping \
  -H "Content-Type: application/json" \
  -d '{"map_path":"/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map/test_save_001"}'
```

预期：

```plain
result.map_file=/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map/test_save_001
result.save_map_id=/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map/test_save_001
```

检查：

```bash
ls -lah /home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map/test_save_001
```

注意：`/robot/map/list` 当前只扫描 `MAP_ROOT` 的一级子目录。如果 `MAP_ROOT=/home/gr301ab0113/aurora_ws/flyAdapter/data/maps`，它不会把 `/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map/test_save_001` 当作一级地图列出来。要让列表以 `/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map` 为根，需要启动 Adapter 时改：

```bash
export MAP_ROOT=/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map
export DEFAULT_MAP_NAME=test_save_001
```

但这会改变整个系统对地图根目录的理解，必须同步检查加载、POI、巡航文件里的地图路径。

---

## 7. 加载刚保存的地图

如果地图在 `/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/test_save_001`：

```bash
curl -X POST http://127.0.0.1:8080/slam/relocation \
  -H "Content-Type: application/json" \
  -d '{"map_path":"/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/test_save_001","x":0,"y":0,"z":0,"yaw":0,"wait_for_localization":false}'
```

如果地图在 `/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map/test_save_001`：

```bash
curl -X POST http://127.0.0.1:8080/slam/relocation \
  -H "Content-Type: application/json" \
  -d '{"map_path":"/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map/test_save_001","x":0,"y":0,"z":0,"yaw":0,"wait_for_localization":false}'
```

检查定位：

```bash
curl http://127.0.0.1:8080/robot/localization/status
curl http://127.0.0.1:8080/robot/readiness/poi
```

---

## 8. 直接 ROS2 对照测试

Adapter 保存失败时，用 ROS2 直接隔离问题。

切 mapping：

```bash
ros2 service call /GR301AA0025/slam/set_mode fourier_msgs/srv/SetMode "{mode: 'mapping'}"
```

保存到绝对路径：

```bash
ros2 service call /GR301AA0025/slam/save_map fourier_msgs/srv/SaveMap "{map_id: '/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/test_save_001'}"
```

加载地图：

```bash
ros2 service call /GR301AA0025/slam/load_map fourier_msgs/srv/LoadMap \
  "{map_path: '/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/test_save_001', x: 0.0, y: 0.0, z: 0.0, yaw: 0.0}"
```

如果 ROS2 直接调用成功，但 Adapter 不成功，问题在 Adapter 进程的 ROS 环境或调用参数。  
如果 ROS2 直接调用也失败，问题在 HumanoidNav 当前状态、地图数据、权限、目标路径或底层服务。

---

## 9. 常见现象解释

| 现象 | 含义 |
| --- | --- |
| `start_mapping` 返回成功但目录没创建 | 正常。开始建图只切模式，不写文件 |
| `current_map=/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/xxx` 但 `ls` 没有目录 | 只说明 Adapter 记录了目标路径，不代表保存成功 |
| `service unavailable` | Adapter client 没发现对应 ROS service |
| `service timeout` | Adapter 已发起调用，但底层服务在超时时间内没返回 |
| `save_map` timeout 后 `load_map` 又 unavailable | 底层保存可能仍在运行或 HumanoidNav 服务端临时不可用；不要立刻重试保存/加载，先确认 service client ready、`robot_pose` 新鲜 |
| 页面 `lastResponse` 里还有 `result.action=stop_mapping` | 这是上一次保存操作响应，不一定是当前自动刷新状态；自动刷新不会主动清空 lastResponse |
| 点“重试保存地图”也出现 `action=stop_mapping` | 正常。该按钮调用 `/robot/map/save`，后端复用 `stop_mapping()` 调底层 save_map |
| `robot_pose_not_fresh` | Adapter 没收到新 `/robot_pose`，会影响 readiness，但保存失败仍以 `result.message` 为准 |
| `map_name=xxx` 保存到 `/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/xxx` | 当前设计如此，因为 `MAP_ROOT=/home/gr301ab0113/aurora_ws/flyAdapter/data/maps` |
| 想保存到 `/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map/xxx` | 用绝对 `map_path`，或改 `MAP_ROOT=/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map` |

---

## 10. 建议现场统一口径

推荐默认使用一级地图目录：

```plain
/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map
/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/test_save_001
/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/site_a_20260430
```

这样 `/robot/map/list`、`map_name`、`MAP_ROOT` 的语义都最简单。

如果必须使用嵌套目录：

```plain
/home/gr301ab0113/aurora_ws/flyAdapter/data/maps/map/test_save_001
```

请全程使用绝对 `map_path`，不要混用 `map_name`。
