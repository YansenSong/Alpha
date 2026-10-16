# RobotPilot UI 软件包

此 ROS 2 软件包包含 RobotPilot 浏览器 UI 使用的 Flask 服务器、rosbridge 启动集成、相机网页串流启动集成、
地图/导航中继节点，以及可选的地图/路线辅助节点。

工作区设置、构建和运行命令、端口、topic 及故障排查的权威说明请参阅仓库根目录的 `../../../README.md`。

## Launch 文件

- `launch/new_ui_launch.py`：启动 Web UI 服务和适用于浏览器的中继节点。
- 建图由 AckermannRobot 的 `scripts/mapping_mini.sh` 启动；UI 不启动机器人建图或导航节点。
- Maps 页保存命令调用 `/lio_sam/save_map`，再用 AckermannRobot 的 `pcd2gridmap` 生成 2D 地图。

## 运行时组件

- `flask_app.py`：提供编译后的 React 应用。
- `map_relay.py`：以适合浏览器的 QoS 将 `/map` 重新发布到 `/ui/map`。
- `nav_relays.py`：将 AMCL 和导航/对接 action 状态重新发布到 `/ui/*`。
- `folders_handler.py`：处理地图、分组、路线和 waypoint 文件命令。
- `route_store.py`：路线编辑页的仿真适配节点，按当前 `/map` 保存可复用路线到 `~/.ros/ackermann_robot/routes/`。
- `battery.py`：按 `BATTERY_SOURCE=sim|serial|disabled` 选择模拟、串口或关闭；`/battery/state` 是带来源的权威状态，旧 `/battery_status` 仅用于兼容。
- `daily_log_collector.py`：订阅 `/rosout`，按本地日期追加写入 `~/.ros/log/daily/<节点>_YYYY-MM-DD.log`。日志中心只列出该目录中的每日文件；ROS 原生按进程生成的日志仍保留在原位置。可用 `ROBOTPILOT_LOG_ROOT` 覆盖根目录。

本仓库的 `scripts/run_robotpilot.sh` 面向本地仿真，默认显式设置 `ROBOT_MODE=simulation` 与 `BATTERY_SOURCE=sim`。直接运行 `new_ui_launch.py` 时电池源默认关闭。串口失败会报告 `unavailable`，不会退回模拟值。

模拟电池可通过 ROS 参数复现状态：`sim_initial_percent`、`sim_drain_rate_percent_per_second`、`sim_charge_rate_percent_per_second`、`sim_charging` 和 `sim_available`。例如：

```bash
ros2 param set /battery_monitor sim_charging true
ros2 param set /battery_monitor sim_available false
```

## Voice Command API 密钥

`flask_app.py` 会从环境变量中读取 `ANTHROPIC_API_KEY`，供 `/api/voice-plan` endpoint
（Blockly 的 Voice Command 功能）使用。将本目录中的 `.env.example` 复制为 `.env` 并设置密钥。
`.env` 已加入 Git 忽略列表；`launch/new_ui_launch.py` 会读取它，并且只将密钥传给 `flask_app` 节点进程，
因此无需在 shell 中执行 `export`。详情请参阅 [launch/README.md](launch/README.md)。

## 静态应用

React 源码位于仓库根目录的 `web/` 中。生产资源构建后会复制到：

```text
robotpilot_ui_package/static/app/
```

请使用仓库根目录的脚本：

```bash
cd ~/robotpilot-ui
bash scripts/build_frontend.sh
bash scripts/sync_frontend_to_ros.sh
```

然后在 `ros2/` 工作区中构建 ROS 2 工作区：

```bash
cd ~/robotpilot-ui/ros2
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
```

也可以在仓库根目录使用辅助脚本：

```bash
cd ~/robotpilot-ui
source /opt/ros/jazzy/setup.bash
bash scripts/build_ros.sh
source ros2/install/setup.bash
```

加载环境后，确认软件包已安装：

```bash
ros2 pkg prefix robotpilot_ui_package
```

运行推荐的 UI launch：

```bash
ros2 launch robotpilot_ui_bringup ui.launch.py
```

在浏览器中打开：

```text
http://127.0.0.1:5050/
```
