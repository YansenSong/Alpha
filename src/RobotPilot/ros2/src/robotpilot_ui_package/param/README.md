# 参数

此目录包含 UI 软件包的 ROS 参数文件。

- `config.yaml`：当前 UI 服务配置，包括 Flask、rosbridge 和 web video server 的端口。

当前地图和路线写入 `~/.ros/ackermann_robot/current_map_route.yaml`（或 `$ROS_HOME/ackermann_robot/current_map_route.yaml`），不修改仓库文件。

当前端口和 launch 流程请参阅仓库根目录的 `README.md`。
