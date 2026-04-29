# GR3 RViz 配置

本目录放 GR3 适配工程专用 RViz2 配置，统一使用命名空间 `GR301AA0025`。

## 建图

```bash
cd ~/aurora_ws/flyAdapter || exit 1
./scripts/open_rviz.sh mapping
```

对应配置：

```plain
rviz/mapping_GR301AA0025.rviz
```

主要显示：

- `/GR301AA0025/map`
- `/GR301AA0025/scan`
- `/GR301AA0025/cloud_registered_gravity`
- `/GR301AA0025/odom`

## 定位 / 重定位

```bash
cd ~/aurora_ws/flyAdapter || exit 1
./scripts/open_rviz.sh relocation
```

对应配置：

```plain
rviz/relocation_GR301AA0025.rviz
```

主要显示：

- `/GR301AA0025/map`
- `/GR301AA0025/scan`
- `/GR301AA0025/odom`
- `/GR301AA0025/plan`

## Map Update Topic

两个 RViz 配置都不能把 `Update Topic` 留空。空字符串在 RViz2 里会被当成非法 topic，并报：

```plain
Error subscribing: Invalid topic name: topic name must not be empty string
```

当前配置使用：

```plain
/GR301AA0025/map_updates
/GR301AA0025/optimize_map_updates
```

如果现场没有发布 map update topic，RViz 只是收不到增量更新，不影响订阅 `/GR301AA0025/map` 全量地图。

## TF Remap

启动脚本会自动使用：

```bash
-r tf:=/GR301AA0025/tf
-r tf_static:=/GR301AA0025/tf_static
```

Fixed Frame 仍然是 `map`，不是 `/GR301AA0025/map`。`map` 是 TF frame 名，`/GR301AA0025/map` 是 topic 名，两者不要混在一起。

## Map 报红 / GLSL 报错

如果 RViz 左侧 `Map` 报红，并且终端出现：

```plain
active samplers with a different type refer to the same texture image unit
```

这通常是 RViz Map 插件和显卡 OpenGL 驱动的渲染兼容问题。`scripts/open_rviz.sh` 默认会开启软件渲染：

```plain
LIBGL_ALWAYS_SOFTWARE=1
QT_X11_NO_MITSHM=1
```

如果现场显卡驱动正常，想关闭软件渲染：

```bash
GR3_RVIZ_SOFTWARE=0 ./scripts/open_rviz.sh mapping
GR3_RVIZ_SOFTWARE=0 ./scripts/open_rviz.sh relocation
```

如果开启软件渲染后 Map 仍然报红，再检查 topic 和 TF：

```bash
ros2 topic info -v /GR301AA0025/map
timeout 5s ros2 topic echo /GR301AA0025/map --once
ros2 topic echo /GR301AA0025/tf --once
ros2 topic echo /GR301AA0025/tf_static --once
```
