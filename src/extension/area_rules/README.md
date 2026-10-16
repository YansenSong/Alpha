# 地图规则

`area_rules` 将规则保存在机器人本机的
`~/.local/share/ackermann_robot/area_rules.json`，并按 `/map` 的内容哈希隔离。
在 UI「地图管理 → 已保存的地图」中点击对应地图的「编辑」，然后拖动绘制；也可展开「规则列表与坐标录入」输入坐标并添加。编辑非当前地图时，UI 会先将其加载到机器人；规则会立即发布到：

- `/area_rules/keepout_mask`、`/area_rules/filter_info`：Nav2 全局代价地图的禁行过滤器。
  禁行区、虚拟墙、临时封闭区均写入掩码。掩码外扩 0.84 m，覆盖车辆后轴到车体角点的距离。
- `/area_rules/control`：10 Hz 的行驶许可与速度上限。`cmd_vel_mux` 在规划器和手动命令之间
  统一执行限制；键盘遥控也经 `/cmd_vel` 进入该仲裁器。未收到许可、许可过期、
  定位不可用或车体侵入禁行区域时输出零速度。
- `/area_rules/state`：当前地图规则的可靠、持久 ROS 状态，供浏览器重连读取。

限速区的上限以 m/s 指定，车辆靠近区域边缘时开始限速。临时封闭区到期后自动删除并重新发布掩码。
地图图层开关只影响浏览器显示，不改变机器人约束。切换 `/map` 时仅载入该地图对应的规则。

构建和启动：

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-up-to robot_bringup area_rules --symlink-install
source install/setup.bash
bash scripts/nav_liorf_neupan.sh maps/mini
```

可使用 `ros2 topic echo /area_rules/state --once` 检查当前地图规则，
以及 `ros2 topic echo /area_rules/control --once` 检查实时停车和限速决定。
首次启用时应在安全场地确认规划路线避开禁区，以及手动和自主指令均受限速约束。
