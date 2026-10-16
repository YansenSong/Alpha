# 地图

AckermannRobot 集成模式下，UI 管理的地图保存在项目根目录的 `maps/ui/<group>/`。每张地图同时包含供 Maps 页使用的 `<map>.yaml`、`<map>.pgm`，以及可直接供导航脚本使用的 `<map>/GlobalMap.pcd`、`<map>/map.yaml`、`<map>/map.pgm`。

独立运行 UI 且未设置 `ACKERMANN_ROBOT_WS` 时，此目录作为回退位置。

主 Nav2 地图服务器属于机器人或仿真工作区。此 UI 工作区可以保存和管理地图文件；如果平台软件栈已负责
`/map_server`，则不应再启动第二个地图服务器。

当前构建和运行流程请参阅仓库根目录的 `README.md`。
