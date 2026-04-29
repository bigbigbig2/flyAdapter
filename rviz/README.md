# GR3 RViz 配置

本目录放 GR3 适配工程专用 RViz2 配置，统一使用命名空间 `GR301AA0025`。

## 建图

```bash
cd ~/aurora_ws/gr3 || exit 1
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
cd ~/aurora_ws/gr3 || exit 1
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

## TF Remap

启动脚本会自动使用：

```bash
-r tf:=/GR301AA0025/tf
-r tf_static:=/GR301AA0025/tf_static
```

Fixed Frame 仍然是 `map`，不是 `/GR301AA0025/map`。
