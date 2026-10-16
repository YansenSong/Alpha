# UI launch 文件

- `new_ui_launch.py` 启动 Flask、rosbridge、rosapi、视频服务和浏览器所需的地图、TF、导航状态中继。
- `robotpilot_ui_bringup/launch/ui.launch.py` 组合上述 UI 服务、地图目录管理和路线编辑存储。

建图和导航由 AckermannRobot 工作区负责。建图使用项目根目录的 `bash scripts/mapping_mini.sh`；Maps 页保存命令调用运行中的 `/lio_sam/save_map` 并将 PCD 转换为 2D 地图。UI launch 不启动 SLAM、AMCL、Nav2 或机器人驱动。
