## fourier_msgs/srv/CancelCurrentAction
### 文件
fourier_msgs/srv/CancelCurrentAction.srv

### 描述
取消当前正在执行的导航动作。

### 请求
无（空请求）

### 响应
| 元素 | 类型 | 描述 |
| --- | --- | --- |
| success | bool | 取消操作是否成功 |
| message | string | 结果描述信息 |


### 适用场景
+ 紧急停止导航任务
+ 用户手动中断机器人移动
+ 切换到新的导航目标前取消当前任务

### 注意事项
+ 取消动作后，机器人会停止当前运动
+ 如果没有正在执行的动作，服务仍会返回成功





## fourier_msgs/srv/GetCurrentAction
### 文件
fourier_msgs/srv/GetCurrentAction.srv

### 描述
获取当前正在执行的导航动作信息。

### 请求
无（空请求）

### 响应
| 元素 | 类型 | 描述 |
| --- | --- | --- |
| success | bool | 是否成功获取信息 |
| action_name | string | 当前动作名称，例如：`"navigate_to_pose"`<br/>`"follow_path"`<br/>`"spin"`<br/>`"backup"` |
| goal_status | action_msgs/GoalStatus | ROS2标准目标状态，包含：- goal_info（目标ID和时间戳）- status（状态码） |
| status_description | string | 人类可读的状态描述 |


### 目标状态码
| 状态码 | 名称 | 描述 |
| --- | --- | --- |
| 0 | STATUS_UNKNOWN | 未知状态 |
| 1 | STATUS_ACCEPTED | 已接受 |
| 2 | STATUS_EXECUTING | 执行中 |
| 3 | STATUS_CANCELING | 取消中 |
| 4 | STATUS_SUCCEEDED | 成功完成 |
| 5 | STATUS_CANCELED | 已取消 |
| 6 | STATUS_ABORTED | 已中止 |


## fourier_msgs/srv/LoadMap
### 文件
fourier_msgs/srv/LoadMap.srv

### 描述
加载指定地图并自动切换到定位模式。系统将：

1. 停止当前建图或定位模式
2. 加载指定地图
3. 设置初始位姿
4. 启动定位模式

### 请求
| 元素 | 类型 | 描述 |
| --- | --- | --- |
| map_path | string | 地图路径，支持：   绝对路径: 以 `/` 开头   相对路径: 相对于默认地图目录   地图目录应包含 `global.pcd` 和 `map.yaml`/`map.pgm` |
| x | float64 | 初始 x 位置（米） |
| y | float64 | 初始 y 位置（米） |
| z | float64 | 初始 z 位置（米） |
| yaw | float64 | 初始 yaw 角度（弧度） |


### 响应
| 元素 | 类型 | 描述 |
| --- | --- | --- |
| result | uint32 | 结果码：   `0`: 成功   `1`: 地图未找到   `2`: 地图加载失败   `3`: 模式切换失败 |
| message | string | 结果描述信息 |


### 地图文件结构
加载的地图目录应包含以下文件：

```plain
map_directory/
├── global.pcd        # 3D点云地图（必需）
├── map.yaml          # 2D地图配置文件
└── map.pgm           # 2D占用栅格图像
```







## fourier_msgs/srv/SaveMap
### 文件
fourier_msgs/srv/SaveMap.srv

### 描述
保存当前3D点云地图。仅在建图模式下可用。

### 请求
| 元素 | 类型 | 描述 |
| --- | --- | --- |
| map_id | string | 地图标识符或保存路径：绝对路径: 以 `/`<br/> 开头，直接保存到指定路径相对路径: 保存到 `./data/{map_id}/`<br/>目录不存在时会自动创建 |


### 响应
| 元素 | 类型 | 描述 |
| --- | --- | --- |
| response | uint32 | 结果码：`0`<br/>: 成功`1`<br/>: 保存操作已在运行`2`<br/>: 图像渲染重置失败`3`<br/>: 地图数据为空，无法保存`4`<br/>: 扩图定位失败 |


### 保存内容
执行保存后，地图目录将包含：

| 文件 | 格式 | 描述 |
| --- | --- | --- |
| global.pcd | PCL二进制压缩 | 3D点云地图 |
| *.bin | 二进制 | 分块地图数据（可选） |


### 注意事项
+ 仅在建图模式下可用
+ 如果目标目录已存在，会先删除再重建
+ 2D地图需要使用 `nav2_map_server` 的 `map_saver_cli` 单独保存

## fourier_msgs/srv/SetMode
### 文件
fourier_msgs/srv/SetMode.srv

### 描述
用于在建图（mapping）和定位（localization）模式之间切换。

### 请求
| 元素 | 类型 | 描述 |
| --- | --- | --- |
| mode | string | 目标模式，支持以下值：   建图模式: `"mapping"`, `"slam"`, `"0"`   定位模式: `"localization"`, `"loc"`, `"1"`   （大小写不敏感） |


### 响应
| 元素 | 类型 | 描述 |
| --- | --- | --- |
| success | bool | 操作是否成功 |
| result | uint32 | 结果码：   `0`: 成功切换到目标模式   `1`: 已处于目标模式（无需切换）   `2`: 模式名称无效   `3`: 切换失败 |
| message | string | 结果描述信息 |


### 切换逻辑
从建图模式切换到定位模式:

1. 保存当前地图
2. 加载为定位模式
3. 设置机器人初始姿态

从定位模式切换到建图模式:

1. 清除缓存地图数据
2. 重启建图模块
3. 重置Octomap

