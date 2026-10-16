# RobotPilot UI

基于 React 的 ROS 2 机器人浏览器界面。本仓库包含前端和 UI 侧 ROS 工作区；
不包含机器人驱动、Nav2、定位组件或仿真器。

## 使用 Demo Mode 运行前端

需要 Node.js `20.19+` 或 `22.12+`（支持 Node 24）以及 npm。

```bash
cd web
npm ci
npm run dev
```

打开 `http://localhost:3000/` 访问前端。实时机器人状态需要可用的 ROS 连接；使用 Flask
`/api/*` 路由的功能还需要启动 UI 后端。

## 同时启动前端和后端

完成前端依赖安装和 ROS 工作区构建后，在 AckermannRobot 项目根目录运行：

```bash
bash scripts/run_robotpilot.sh
```

前端地址为 `http://localhost:3000/`，ROS 后端地址为 `http://127.0.0.1:5050/`。
该脚本仅用于本机开发，使用仅允许 loopback 监听的 `AUTH_MODE=open`，并把 Vite 绑定到 `127.0.0.1`。它会拒绝 `AUTH_MODE=local`，避免在无 TLS 的 Vite 开发服务器中误用安全 Cookie。可通过 `ROS_SETUP` 指定 ROS 环境脚本。按 `Ctrl+C` 会同时停止前后端。

Maps 页不启动建图节点。在 AckermannRobot 项目根目录运行 `bash scripts/mapping_mini.sh`，保持 LIO-SAM 运行，再在 Maps 页保存。保存会调用 `/lio_sam/save_map` 并运行已构建的 `third_party/pcd2pgm/build/pcd2gridmap`；结果保存在 `maps/ui/<group>/<map>/`，可作为 `bash scripts/nav_liorf_neupan.sh maps/ui/<group>/<map>` 的输入。Maps 页的 Switch 只切换 2D map_server 地图，不会热切换 LIORF 点云地图。

## 构建并运行 UI 后端

当前 AckermannRobot 集成工作区已在 ROS 2 Humble 上构建验证。安装 ROS 依赖后，从 AckermannRobot 仓库根目录构建：

```bash
source /opt/ros/humble/setup.bash
cd src/RobotPilot/web
npm ci
npm run build
cd ../../..
bash scripts/check_s0.sh
source /tmp/alpha-s0-check/install/setup.bash
ros2 launch robotpilot_ui_package new_ui_launch.py
```

上述命令启动 UI 后端；开发页面仍建议使用根目录 `bash scripts/run_robotpilot.sh` 启动 Vite 与后端。若要从后端 `http://127.0.0.1:5050/` 提供最新打包页面，需要先运行 `bash src/RobotPilot/scripts/sync_frontend_to_ros.sh` 同步构建产物；该同步脚本会替换 `static/app` 内旧资源，应单独检查其文件改动。UI launch 会启动 Flask 和面向浏览器的 ROS 节点；
如果已安装相应软件包，还会启动 `rosbridge_server`、`rosapi` 和
`web_video_server`。它不会启动机器人驱动、Nav2、定位组件、传感器或仿真器；
如需实时数据，请另行启动兼容的机器人或仿真器 ROS 工作区。

当前检出版本没有 Dockerfile 或 Docker Compose 配置。S0 检查可运行 `bash scripts/check_s0.sh`；前端开发与构建步骤见
[web/README.md](web/README.md)。

`AUTH_MODE=local` 已支持登录、角色、CSRF 和带角色检查的 rosbridge gateway。局域网试运行仍需按部署环境配置 Flask HTTPS、反向代理 `/rosbridge`、Origin allowlist、ROS_DOMAIN_ID、地图与数据库路径和防火墙；步骤见[启动 Profiles](../../docs/deployment/run-profiles.md)。首次启动后执行 `AUTH_MODE=local python3 -m robotpilot_ui_package.auth <用户名> --role Admin` 创建管理员。仓库未自动安装 systemd service，也不会修改网络或证书。

## 仓库目录结构

- `web/` — React 应用、Vite 配置、浏览器端 ROS 库和前端依赖。
- `ros2/src/robotpilot_ui_package/` — Flask API、ROS launch 文件、中继节点、参数、地图和路线数据。
- `ros2/src/robotpilot_ui_bringup/` — UI 顶层启动包。
- `ros2/src/robotpilot_ui_msgs/` — 自定义 ROS 消息包。
- `scripts/` — 前端构建与同步、ROS 构建与运行脚本。
- [部署与数据文档](../../docs/deployment/run-profiles.md) — 启动 profiles、备份任务和 SQLite 升级/回滚说明。

前端使用的 ROS topic 名称定义在
[`web/src/shared/constants/index.js`](web/src/shared/constants/index.js).
连接其他机器人软件栈之前，请对照 ROS graph 核实 topic 名称和消息类型。

## 文档

- [启动 Profiles](../../docs/deployment/run-profiles.md)
- [SQLite schema 升级与回滚](../../docs/web-storage-migration.md)
