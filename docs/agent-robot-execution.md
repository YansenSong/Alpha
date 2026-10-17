# RoboAgent：ROS 查询与受控任务执行

Pi/Web 沿用已有实现。项目 `.pi/mcp.json` 加载两个独立 stdio MCP：

- `ros_inspect`：复用 `ros-mcp==3.1.2` 的 ROSAPI 查询实现，通过独立只读 rosbridge 转发器连接真实 ROS Graph。
- `alpha`：六个业务工具，复用 RobotPilot Platform API、MissionManager 和车辆侧软件停车请求协议。没有第二套任务调度器。

## 安装与启动

```bash
uv sync --locked --project third_party/RobotPilot/alpha-mcp
npm ci --prefix third_party/RobotPilot/agent-gateway
# 先按原流程启动 RobotPilot、MissionManager、rosbridge 与 rosapi。
PI_AGENT_PROVIDER=deepseek PI_AGENT_MODEL=deepseek-flash \
  bash scripts/run_pi_gateway.sh --trust-project
```

默认只允许查询。启用开发环境的仿真任务提交，需要在 Gateway 进程环境中显式设置：

```bash
ALPHA_ALLOW_MOTION=simulation PI_AGENT_PROVIDER=deepseek PI_AGENT_MODEL=deepseek-flash \
  bash scripts/run_pi_gateway.sh --trust-project
```

适配器再次校验后端报告的 `robot_mode=simulation`、open 本地开发认证、正确 robot ID 和实际 readiness。硬件运动入口目前不开放；不修改全局 Pi 安装、认证或默认工具权限。默认地址为 `ALPHA_PLATFORM_URL=http://127.0.0.1:5050`、`ALPHA_ROSBRIDGE_URL=ws://127.0.0.1:9090`、`ROBOT_ID=robot-001`。Platform URL 只接受 loopback HTTP，不跟随重定向。部署到多用户或非本机环境前，需要接入已有 local 认证的服务凭证；当前实现明确拒绝该模式的 Agent 控制请求。

新增工具由 Pi SDK 的 `createMcpExtension()` 显式注册，只加载项目 MCP 配置，不继承全局 MCP 配置。启动等待全部工具注册并校验精确允许列表；扩展初始化失败不会回退到 bash/edit/write。退出会发出 extension `session_shutdown`，关闭 MCP 子进程。

## 可用能力与边界

只读工具：`get_nodes`、`get_node_details`、`get_topics`、`get_topic_type`、`get_services`、`get_actions`、`get_action_status`、`subscribe_once`。消息读取限 `/navigation/state`、`/safety/software_stop/state`、`/battery/state`、`/diagnostics`，结果限制大小。状态消息可能并非 JSON 对象，工具保留受限摘要。

转发器在协议层拒绝 publish、advertise、Action 写入和任意 Service 调用，仅允许指定 ROSAPI 查询及少量状态订阅。其上游 rosbridge 地址固定，不提供给模型修改。该隔离覆盖 inspection 服务的连接，不是主机进程或整个 DDS 网络的安全沙箱；现有 9090 端口仍应限定可信本机进程访问。

业务工具：`get_robot_status`、`list_navigation_locations`、`navigate_to_location`、`get_task_status`、`request_software_stop`、`cancel_navigation`。

导航只能使用当前地图版本下已启用且名称唯一的巡检点。没有 Home 时不会把原点当 Home。机器人 readiness（含电量、定位、地图和停车条件）仍由现有执行链校验。

## 任务、幂等与结果证据

Pi Session 保存对话；MissionManager 保存任务及状态；MCP 本地 SQLite 日志只保存操作键和提交映射，不接管机器人任务生命周期。日志位于 `third_party/RobotPilot/alpha-mcp/.runtime/operations.sqlite3`，已忽略 Git。

每次业务操作必须带 8–128 字符的稳定 `idempotency_key`。操作在发送前持久化预留，确定性生成 mission/command ID；重复或重启后的相同请求不会再次发送目标。相同键不能换参数。超时、断线、进程中断后返回 `unknown`，只能查询并核对状态，不能自动换键重发。保存 mission 未确认时不发送 start。

`accepted` 只代表接收。`get_task_status` 只有在机器人权威状态为 SUCCEEDED、状态新鲜且任务/地图版本/步骤/attempt/目标均匹配完成证据时，才返回 `completed=true, verified=true`。旧任务成功但没有新证据时仍不宣称已验证到达。

MissionManager 数据库 schema 从 5 升为 6，增加 `navigation_evidence` 表；升级按原 Store migration 自动执行。部署前备份任务 SQLite 数据，并在无活动任务时重启 MissionManager。若工作区使用普通安装而非 symlink-install，需要重新构建：

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select nav_status smac_neupan_bridge neupan_ros2 mission_manager --symlink-install
source install/setup.bash
```

导航完成只有一个对外判定入口：`nav_status`。NeuPAN 核心仍负责控制器内部的路径末端判断（使用当前机器人 planner.yaml 中的 `ipath.arrive_threshold`，vehicle 当前为 0.5m）；`nav_status` 使用该反馈与新鲜轮速里程计，按 `stopped_speed_threshold=0.05m/s`、`arrival_hold_time=0.8s` 判定稳定到达。没有额外的 0.35m、朝向阈值或任务侧停车等待。

结构化链路为：

```text
/goal_pose (PoseStamped，目标时间戳在本次运行中唯一)
  → smac_neupan_bridge /navigation/planner_state (NavigationExecution)
  → NeuPAN 安装 /plan，并返回带路径时间戳的 ControllerFeedback
  → nav_status /navigation/execution_state (NavigationExecution，权威结果)
  → MissionManager 关联任务/步骤并持久化原始结果
  → Alpha MCP 返回任务状态和证据
```

`NavigationExecution` 携带原始目标（位姿、frame、goal stamp）、路径安装 stamp、execution_id、结构化状态、held、detail 和 result_json。execution_id 使用 `goal_stamp.sec:goal_stamp.nanosec`；它是现有 PoseStamped 导航链路的运行期关联键，不是原生 ROS Action UUID。规划桥保留原始目标，在每次路径安装时生成路径标识；控制器反馈携带计算使用的路径标识，旧路径计算结果不会被新路径冒领。重规划同一目标时，目标标识保持，路径标识更新。

`nav_status` 只接受当前目标的规划状态和当前安装路径的反馈，并检查反馈、定位观测与轮速时间新鲜度。稳定到达后将结果冻结为终态证据，heartbeat 只重发，不重新生成证据。规划桥消费这个终态，清理已结束目标，避免后续规则更新重新执行旧目标；失败后保持导航规则停车，需明确的新目标进入处理。

MissionManager 不再判断导航距离、朝向或稳定停车，也不解析 detail 文本。它只核对目标标识、目标内容及结构化结果关联，保存 `source=nav_status` 的原始结果并补充 task_id、step_index、attempt 和地图版本，随后推进任务。既有任务安全暂停、取消和巡检动作前置条件仍由任务层管理。Alpha MCP 只检查任务与证据关联，不重新计算物理到达。旧 `source=mission_manager` 证据保留历史记录，但不作为新契约的已验证结果。

`/navigation/state` 保留原消息类型、状态值，作为同一个权威状态的兼容投影，供原有 Web 和诊断使用。旧 `/neupan/arrived` Bool、`/global_plan/status` String 保留兼容发布，但不参与权威导航结果判定。升级后应在无活动任务时一起重启规划桥、NeuPAN、nav_status 和 MissionManager，不能只升级任务层。

软件停车使用车辆侧 `/safety/software_stop/request` 的 `request_stop`，等待匹配 request_id 的 durable confirmed latch 反馈。不提供释放工具。软件停车激活或任务取消都不等于物理急停或已证明车体静止。

## Web 界面

RoboAgent 不显示独立机器人任务状态栏。机器人状态和任务进展仍可通过 Agent 调用 MCP 工具查询，后台任务执行、幂等与完成证据校验保持可用。

## 验证

```bash
third_party/RobotPilot/alpha-mcp/.venv/bin/python -m unittest discover \
  -s third_party/RobotPilot/alpha-mcp/tests -p 'test_*.py'
# 隔离 ROS_DOMAIN_ID=186，临时数据库，仅在隔离域发布测试目标，不连接仿真或实车；反馈为测试注入。
third_party/RobotPilot/alpha-mcp/.venv/bin/python \
  third_party/RobotPilot/alpha-mcp/tests/verify_closed_loop.py
source /opt/ros/humble/setup.bash
source install/setup.bash
ROS_DOMAIN_ID=186 PYTHONPATH="$PWD/src/extension/mission_manager:${PYTHONPATH:-}" \
  /usr/bin/python3 -m pytest src/extension/mission_manager/test -q
ROS_DOMAIN_ID=187 /usr/bin/python3 -m pytest src/extension/nav_status/test \
  src/control/neupan_ros2/test/test_feedback_identity.py -q
npm test --prefix third_party/RobotPilot/agent-gateway
npm test --prefix third_party/RobotPilot/web -- --run
npm run build --prefix third_party/RobotPilot/web
# 需要现有模型认证和运行中的 ROS；只读，不发送运动/停车请求。
PI_AGENT_PROVIDER=deepseek PI_AGENT_MODEL=deepseek-flash \
  npm run verify:robot --prefix third_party/RobotPilot/agent-gateway
npm run verify:ui --prefix third_party/RobotPilot/agent-gateway
```

闭环测试经过真实 MCP 调用、真实 Flask Platform API、真实 C++ nav_status 和真实 MissionManager，但控制器/定位反馈是隔离测试注入，不能当作实机到达验收。验证覆盖：accepted 不算完成、错误位置不完成、正确匹配反馈完成、重复提交仅一个目标、重启幂等、超时未知、停车旧反馈拒绝、只读协议层拒绝写入、取消后旧到达不完成。

现场验收前先保存真实巡检点并满足 readiness，再通过用户明确任务执行观察真实反馈。不要为演示清除低电量、软件停车或地图保护。多点规划、自主重试、巡检视觉与硬件授权暂未开放。
