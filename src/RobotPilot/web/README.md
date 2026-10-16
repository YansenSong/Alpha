# Web 前端

本目录包含 React 应用和 Vite 配置。ROS 启动流程见[仓库 README](../README.md)。

## 本地开发

使用 Node.js `20.19+` 或 `22.12+`（支持 Node 24）：

```bash
npm ci
npm run dev
```

Vite 在 `http://localhost:3000/` 提供服务，并绑定到 `0.0.0.0`。要查看实时
ROS 数据，必须能通过配置的主机和端口访问 rosbridge。

Vite 服务器不提供 Flask `/api/*` endpoint。要使用相关功能，需单独运行 ROS UI 后端。ROS 连接使用
页面主机名和默认端口；本地开发时主机名来自
[`src/shared/constants/index.js`](src/shared/constants/index.js)。浏览器侧的速度限制与通知偏好保存在本地运行配置中。

开发时如需显示 inspection 导航配置：

```bash
VITE_UI_PROFILE=inspection_demo npm run dev
```

也接受 `REACT_APP_UI_PROFILE=inspection_demo`。如需在生产构建中使用相同配置，请在运行
`npm run build` 前设置该变量。

## 前端生产构建

From the repository root, run:

```bash
bash scripts/build_frontend.sh
bash scripts/sync_frontend_to_ros.sh
```

第一个脚本会安装 lockfile 锁定的 npm 依赖，并将构建结果放到 `web/build/`；第二个脚本会将结果复制到
ROS 软件包的 `static/app/` 目录。之后请构建 ROS 工作区，以便已安装的软件包提供更新后的前端。

## 源码目录

- `src/app/` — 应用框架、共享 ROS 连接和 providers。
- `src/components/` — 共用面板和控件。
- `src/features/` — 设备、录制等功能模块。
- `src/pages/` — 路由页面和 `registry.js` 导航注册表。
- `src/shared/` — 常量、hooks、样式和共用辅助工具。
- `public/ros/` — 应用构建时包含的浏览器端 ROS 库。

Topic 名称集中定义在 `src/shared/constants/index.js`；消息类型和订阅在各组件中声明。
使用实时数据前，请对照机器人侧 ROS graph 核实 topic 契约。
