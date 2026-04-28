## fourier_msgs/msg/ActionStatus
### 文件
fourier_msgs/msg/ActionStatus.msg

### 描述
当前动作状态消息，由 `robot_monitor_node` 发布，用于报告导航动作的执行状态。

### 定义
| 元素 | 类型 | 描述 |
| --- | --- | --- |
| action_name | string | 动作名称，例如：`"navigate_to_pose"`<br/>`"follow_path"`<br/>`"spin"`<br/>`"backup"`<br/>`"wait"` |
| status | uint8 | 状态码（见下表） |
| status_description | string | 人类可读的状态描述 |
| stamp | builtin_interfaces/Time | 状态记录的时间戳 |


### 状态码定义
| 状态码 | 常量名 | 描述 |
| --- | --- | --- |
| 0 | STATUS_UNKNOWN | 未知状态 |
| 1 | STATUS_ACCEPTED | 动作已被接受 |
| 2 | STATUS_EXECUTING | 动作执行中 |
| 3 | STATUS_CANCELING | 动作取消中 |
| 4 | STATUS_SUCCEEDED | 动作成功完成 |
| 5 | STATUS_CANCELED | 动作已取消 |
| 6 | STATUS_ABORTED | 动作已中止（失败） |


### 话题信息
+ 话题名: `/action_status`
+ 发布节点: `robot_monitor_node`
+ 发布频率: 1 Hz

### 监控的动作列表
默认监控以下导航动作：

+ `navigate_to_pose` - 导航到目标点
+ `spin` - 原地旋转
+ `backup` - 后退
+ `wait` - 等待







## fourier_msgs/msg/BaseErrorInfo
### 文件
fourier_msgs/msg/BaseErrorInfo.msg

### 描述
基础错误信息消息，用于描述单个错误的详细信息。

### 定义
| 元素 | 类型 | 描述 |
| --- | --- | --- |
| error_code | int32 | 完整的32位错误代码（如 0x02040100） |
| level | int32 | 错误级别 |
| component | int32 | 组件类别 |
| message | string | 错误描述信息 |
| timestamp | int64 | 时间戳 |


### 错误级别定义
| 级别 | 值 | 说明 |
| --- | --- | --- |
| Healthy | 0 | 健康状态 |
| Warn | 1 | 警告 |
| Error | 2 | 错误 |
| Fatal | 4 | 致命错误 |


### 组件类别定义
| 组件 | 值 | 说明 |
| --- | --- | --- |
| System | 1 << 16 | 系统组件 |
| Motion | 2 << 16 | 运动组件 |
| Sensor | 3 << 16 | 传感器组件 |
| Software | 4 << 16 | 软件组件 |


### 已定义的错误码
| 错误码 | 十六进制值 | 级别 | 组件 | 说明 |
| --- | --- | --- | --- | --- |
| SENSOR_ERROR_LIDAR_DISCONNECTED | 0x02030100 | Error | 传感器 | Lidar 已断开连接 |
| SOFTWARE_ERROR_RELOC_FAILED | 0x02040100 | Error | 软件 | 重新定位失败 |
| SOFTWARE_ERROR_LOW_LOCALIZATION_QUALITY | 0x02040300 | Error | 软件 | 定位质量低 |
| SOFTWARE_ERROR_LOCALIZATION_FAILED | 0x02040400 | Error | 软件 | 定位失败 |


### 相关消息
+ [HealthInfo](https://health_info.md) - 聚合健康状态





## fourier_msgs/msg/BaseEventInfo
### 文件
fourier_msgs/msg/BaseEventInfo.msg

### 描述
基础事件信息消息，用于描述单个事件的详细信息。

### 定义
| 元素 | 类型 | 描述 |
| --- | --- | --- |
| event_type | string | 事件类型标识符 |
| message | string | 事件描述信息 |
| source | string | 事件来源组件 |
| timestamp | int64 | 时间戳 |


### 已定义的事件类型
| 事件类型 | 值 | 说明 | 发布组件 | 触发频率 |
| --- | --- | --- | --- | --- |
| SystemEventMapLoopClosure | map_loop_closure | 地图闭环检测 | slam | 事件驱动 |
| SystemEventObstacleBlocked | obstacle_blocked | 路径被障碍物阻挡 | collision_monitor | 实时 |
| SystemEventNearObstacle | near_obstacle | 检测到近处障碍物 | collision_monitor | 每1秒 |
| SystemEventNearObstacleWhenStationary | near_obstacle_when_stationary | 机器人静止时检测到近处障碍物 | collision_monitor | 每1秒 |
| SystemEventOutOfMap | out_of_map | 机器人走出地图边界或进入未知区域 | monitor | 实时 |
| SystemEventEnterForbiddenArea | enter_forbidden_area | 机器人进入禁区 | monitor | 每5秒 |
| SystemEventEnterDangerousArea | enter_dangerous_area | 机器人进入危险区域（限速区） | monitor | 每5秒 |


注意:

+ `enter_forbidden_area` 和 `enter_dangerous_area` 在机器人位于对应区域内时，每5秒触发一次
+ 机器人离开区域时会在日志中记录，但不会触发新事件
+ 事件消息中包含区域ID、速度限制（危险区）和机器人位置信息

### 相关消息
+ [EventsInfo](https://events_info.md) - 聚合事件信息





## fourier_msgs/msg/EventsInfo
### 文件
fourier_msgs/msg/EventsInfo.msg

### 描述
聚合后的系统事件消息，由 `events_node` 发布，包含所有组件的事件汇总。

### 定义
| 元素 | 类型 | 描述 |
| --- | --- | --- |
| events | BaseEventInfo[] | 聚合后的所有事件 |


### 话题信息
+ 话题名: `/Humanoid_nav/events`
+ 发布节点: `events_node`
+ 发布频率: 10 Hz（可配置）

### 相关消息
+ [BaseEventInfo](https://base_event_info.md) - 基础事件信息





## fourier_msgs/msg/HealthInfo
### 文件
fourier_msgs/msg/HealthInfo.msg

### 描述
聚合后的系统健康状态消息，由 `health_node` 发布，包含所有组件的健康信息汇总。

### 定义
| 元素 | 类型 | 描述 |
| --- | --- | --- |
| errors | BaseErrorInfo[] | 所有错误列表 |
| has_warning | bool | 是否存在警告级别错误 |
| has_error | bool | 是否存在错误级别错误 |
| has_fatal | bool | 是否存在致命级别错误 |


### 话题信息
+ 话题名: `/Humanoid_nav/health`
+ 发布节点: `health_node`
+ 发布频率: 10 Hz（可配置）

### 相关消息
+ [BaseErrorInfo](https://base_error_info.md) - 基础错误信息







### UnifiedCameraData 消息
融合相机数据和机器人位姿的统一消息类型

消息类型: `fourier_msgs/msg/UnifiedCameraData`

### 消息定义
```plain
# UnifiedCameraData.msg
 # 融合相机数据和机器人位姿的消息类型
 
 std_msgs/Header header
 # header.stamp: 使用相机数据的时间戳
 # header.frame_id: 点云坐标系（通常是 camera_01_color_optical_frame）
 
 # 相机名称（用于多相机区分）
 string camera_name
 
 # RGB 图像数据
 sensor_msgs/Image rgb_image
 
 # 点云数据（原始点云）
 sensor_msgs/PointCloud2 point_cloud
 
 # 机器人位姿（通过时间戳插值得到）
 geometry_msgs/Pose robot_pose
```

### 字段说明
### header (std_msgs/Header)
消息头，包含时间戳和坐标系信息。

+ stamp: 相机数据采集的时间戳（与 RGB 图像和点云的时间戳一致）
+ frame_id: 点云的坐标系（从点云 header 中读取，通常是 `camera_01_color_optical_frame`）

### camera_name (string)
相机标识名称，用于区分多个相机。例如：`"camera_01"`, `"camera_02"`。

### rgb_image (sensor_msgs/Image)
彩色图像数据，包含：

+ 图像尺寸（width, height）
+ 编码格式（通常是 `rgb8` 或 `bgr8`）
+ 图像数据

### point_cloud (sensor_msgs/PointCloud2)
深度点云数据，特点：

+ 原始点云：未经过滤处理的完整点云
+ 坐标系：保持在相机坐标系下
+ 包含 XYZ 坐标信息

### robot_pose (geometry_msgs/Pose)
机器人位姿，特点：

+ 通过时间戳插值得到，与相机数据时间同步
+ 包含位置（position）和朝向（orientation）
+ 位置：`(x, y, z)` 米
+ 朝向：四元数 `(x, y, z, w)`

### 相关话题
+ 输入话题:
    - `/camera/color/image_raw` - RGB 图像源
    - `/camera/depth/points` - 点云数据源
    - `/robot_pose` - 机器人位姿源
+ 输出话题:
    - `/camera/fused_data` - 本消息类型
    - `/camera/filtered_pointcloud` - 过滤后的点云

### 示例代码
详见 ROS API 文档 - 6.2.1 /camera/fused_data。

