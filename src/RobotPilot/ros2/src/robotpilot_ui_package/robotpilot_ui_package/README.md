# Python 软件包

此目录包含 `robotpilot_ui_package` 的 Python ROS 节点。

- `flask_app.py`：编译后的 React 应用使用的 Flask 服务器。
- `map_relay.py`：将 `/map` 转发到 `/ui/map` 的 QoS 中继节点。
- `nav_relays.py`：AMCL 和 action 状态中继节点。
- `folders_handler.py`：地图、分组、路线和 waypoint 文件操作。
- `route_store.py`：路线编辑页的当前地图识别和路线持久化节点。路线目录通过 `/ackermann/routes/*` 与前端通信，地图管理页仍使用 `/nav_data_*`；地图内容指纹作为稳定内部键，地图分组和名称存于 `~/.ros/ackermann_robot/routes/map_identities.json`，地图重命名后路线目录会显示新名称。
- `static/app/`：从 `web/build/` 复制的 React 生产构建文件。
