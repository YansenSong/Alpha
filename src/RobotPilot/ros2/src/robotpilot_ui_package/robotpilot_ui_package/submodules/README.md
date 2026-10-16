# 子模块

多个 ROS 节点需要共用逻辑时，可将 Python 辅助代码放在此处。目前这里只有一个文件 `nodechecker.py`，
其中的 `map_server_check()` 辅助函数会通过 `ros2 node list` 查找 `/lifecycle_manager`。目前软件包中
没有代码导入该函数，因此应将其视为初始代码，而不是已接入运行流程的逻辑。
