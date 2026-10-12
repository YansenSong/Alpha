# Alpha 地图规则与导航联动——源码分析及 Codex 实施方案

> 分析范围：`YansenSong/Alpha` 当前 `main`，主要涉及 `third_party/RobotPilot/web`、`src/extension/area_rules`、`src/bringup`、`src/planning/smac_neupan_bridge`、`src/control`、`src/extension/mission_manager`、`src/extension/nav_status`。
>
> 性质：源码审查与实施方案。**没有在 ROS2/Gazebo/实车环境运行，不能把代码存在视为已通过集成验证。**

## 1. 目标、范围与原则

**目标：** 在地图管理的地图编辑页创建禁行区、限速区、虚拟墙、临时封闭区；规则在对应地图上持久保存；对全局路径规划、当前在途路径、实时速度命令、任务执行产生可追踪且安全的实际影响。

**不是**重新做一套地图库，也不是把限制绘制在浏览器即可。优先复用 `area_rules` 的 ROS2 服务、Nav2 CostmapFilter、现有 Smac + NeuPAN + cmd_vel_mux；必要时最小扩展桥接、状态、后端认证入口。

验收总原则：**保存成功 ≠ 规则已经应用到规划器 ≠ 当前路径已安全 ≠ 车辆已经受到限制。** 四者需要独立确认、关联和反馈。

## 2. 已核实源码及现状

| 链路 | 文件 | 已有行为 / 主要缺口 |
|---|---|---|
| 地图入口 | `third_party/RobotPilot/web/src/pages/MapsPage.jsx` | 「编辑」页面嵌入 `AreaRulesEditor`；编辑未加载地图前会先切换 2D 地图；地图页也明确写了切换不等于重载 LIORF 3D 先验 |
| 绘制 | `third_party/RobotPilot/web/src/components/AreaRulesEditor.jsx`、`src/components/Map.jsx` | 四类规则、矩形/线段画法已存在；鼠标抬起就发送规则，缺少确认/预览/回退；笔和鼠标允许绘制、touch 未接入 |
| 管理 | `third_party/RobotPilot/web/src/components/KeepoutZones.jsx` | 查看、删除和坐标新增已具备；修改现有规则、激活状态、几何编辑、筛选仍需完善 |
| ROS 同步 | `third_party/RobotPilot/web/src/shared/hooks/useKeepoutZones.js` | `/area_rules/{command,ack,state}`、`map_key`、`expected_version` 已存在；ack 仅反映机器人规则命令被接受，不等于 Nav2 已吸收掩码 |
| 规则权威 | `src/extension/area_rules/area_rules/node.py`、`rules.py` | `~/.local/share/ackermann_robot/area_rules.json`，基于 OccupancyGrid 内容 hash 隔离；发布 `/area_rules/keepout_mask`、`/area_rules/filter_info`、`/area_rules/control`；临时封闭按秒检查到期 |
| Nav2 配置 | `src/bringup/config/smac_planner.yaml` | `global_costmap.filters: [area_keepout_filter]`，`nav2_costmap_2d::KeepoutFilter` 读取 `/area_rules/filter_info`。没有项目内证据证明运行时过滤掩码确实进入当前 costmap，需集成测试 |
| 导航启动 | `src/bringup/launch/navigation.launch.py`、`planning.launch.py`、`navigation_sim.launch.py`、`scripts/nav_liorf_neupan.sh` | 启动 `area_rules`、Smac、mux，并设 `area_rules_required=True`；应检查实际运行部署是否走这套入口 |
| Smac 桥接 | `src/planning/smac_neupan_bridge/src/smac_neupan_bridge.cpp` | 收 `/goal_pose` 后请求 ComputePathToPose、成功发布 `/plan_path` 和 `/plan`；**不订阅地图规则变化，无自动路径失效与重规划链路** |
| NeuPAN | `src/control/neupan_ros2/neupan_ros2/neupan_node.py`、`src/control/neupan_ros2/config/robots/vehicle/robot.yaml` | 跟踪 `/plan`；车辆配置中 `refresh_initial_path: true`，可接受后续新路径；`path_callback` 对空路径直接返回，不能借发送空路径保证旧轨迹已清除 |
| 速度仲裁 | `src/control/vehicle_control/cmd_vel_mux.py` | 订阅 `/area_rules/control`；按 0.5s 新鲜度失联停车；输出零速度或限速后的底盘参考速度。无端到端速度/制动距离验证 |
| 任务状态 | `src/extension/mission_manager/mission_manager/node.py`、`src/extension/nav_status/src/nav_status_node.cpp` | 任务发布 `/goal_pose`；导航状态有 PLANNING/MOVING/ARRIVED/FAILED，尚无「规则更新导致等待重规划」明确语义 |
| 地图配对 | `src/extension/mission_manager/mission_manager/map_bundle.py` | 对 2D map、LIORF 3D 配对有可信监测；地图管理的 2D 切换不足以建立完整导航就绪条件 |

### 对现有能力的准确判断

1. **禁行区、虚拟墙、临时封闭区：** 规则存储→掩码生成→Nav2 KeepoutFilter 配置已经贯通于代码；启动后应能对新规划起作用，但仍需真实 costmap/规划结果测试。
2. **限速区：** `area_rules` 基于当前位姿和前方采样输出 `speed_limit`；`cmd_vel_mux` 对手动及 NeuPAN 统一限速。不能仅凭此断言极限工况实际车速符合要求。
3. **动态封闭关键缺口：** 在已经下发旧路径后新增阻挡规则，并**不会自动触发 Smac 重新规划**。NeuPAN 可能仍跟随旧路径直到靠近禁区被停住。这不满足「动态封路时主动绕行」。
4. **规则生效状态缺口：** `/area_rules/ack` 是规则写入/发布层 ack，缺少 Nav2 过滤应用、当前路径有效性、底盘限速实际输出的可验证状态。
5. **地图管理风险：** 切换 2D 地图不意味着 LIORF 3D 定位同步切换；实际导航前必须验证完整地图包匹配。
6. **几何安全边界：** 当前 `ROBOT_RADIUS = 0.84` 圆形外扩并在规划和实时保护使用，需要实车标定；对于前进/后退、转弯、制动距离、占据栅格量化应做系统测试，不能盲目缩小。
7. **认证边界：** 浏览器调用 ROS `/area_rules/command`，前端有 Engineer 禁用逻辑但不应视作服务端权限校验；检查 ROSBridge/网关隔离，优先新增受鉴权保护的写入路径。

## 3. 四类规则的期望语义

| 类型 | 用户意义 | 全局规划 | 当前执行路径/局部控制 | 生效与生命周期 |
|---|---|---|---|---|
| `keepout` 禁行区 | 持续禁止通行的区域 | 不得规划进入（含车体安全包络） | 新增规则切断当前路径时停车、重规划；无解时保持安全停车 | 按地图长期保存，显式启停或删除 |
| `wall` 虚拟墙 | 线段形式的不可跨越边界，可设物理/规划宽度 | 作为禁止穿越的带状栅格 | 同禁行区；不可只渲染紫色线 | 按地图长期保存；方向默认双向禁止 |
| `closure` 临时封闭区 | 施工/人员作业造成的有时效不可通行区域 | 到期前阻挡、到期后恢复 | 激活时检查当前路径；到期后可按需重新规划，但不得未经安全校验自动恢复执行 | **服务器时钟**产生 `expires_at`，到期自动撤销掩码并产生状态事件 |
| `speed` 限速区 | 区域内最高线速度 | 一般不要求对路径改变；可选未来按时间代价选路 | 进入前提前减速、前后退双向限速、多个区域取最严格值 | 实时生效；退出后按加速度限制恢复，不可速度突变 |

`wall` 本质上是线形几何，`keepout/closure/speed` 初版保留现有轴对齐矩形。任意多边形等高级几何可放第二阶段，避免混入导航安全闭环的首次交付。

## 4. 建议的目标架构

```text
地图管理 → 地图编辑（统一规则列表/地图预览/属性编辑）
           │
           ├─ 地图与 LIORF 配对/版本校验
           └─ 经认证写入+请求 ID / 预期版本 / 规则确认
                     ↓
          area_rules（机器人规则权威）
          ├─持久规则集 / map_id + map_version_id + 内容hash
          ├─禁行掩码 + 版本号 / 规则 hash
          ├─速度策略 + 带前瞻的实时区域检查
          └─规则应用过程状态（待应用/已生效/失败）
               ↓                         ↓
         Nav2 KeepoutFilter          cmd_vel_mux / 运动保护
               ↓                         ↓
      Smac 实际代价地图              底盘参考速度限幅或停车
               ↓
      在途路径监控/重规划协调器
      ├─规则变化 + 当前路径冲突检测
      ├─暂停旧路径安全执行
      ├─请求 Smac 对当前目标重新规划
      └─新路径+地图版本核验通过才解除规则暂停
               ↓
       NeuPAN 重新接收新 `/plan`
               ↓
      MissionManager/NavStatus/前端显示结果
```

**不要让前端直接发布底盘 `cmd_vel` 来实现禁行或限速；运动保护必须在机器人侧统一仲裁并能够失联安全停车。** 不要复用 `/mission/hold` 为多个节点相互覆盖的独立布尔开关，建议加入带来源独立维护的 `/navigation/rules_hold`，mux 对多个停机来源做 OR 合并；也可做经过审查的统一 Safety Gate。

## 5. 最小实施方案：四个阶段

### P0：先补安全底座（不改变 UI 主框架）

**P0.1 地图身份一致性。** 在规则应用前确认 `map_id`、`map_version_id`、OccupancyGrid 内容哈希与 `/localization/map_bundle` 配对状态属于同一次地图快照。若 2D 切换但 LIORF 3D 尚未配对，允许在明确的离线编辑模式中准备草稿，但**不得标识为导航已生效**；在线激活和任务启动均应受限。避免直接用 2D 活动地图切换来模拟安全的全套导航地图切换。

**P0.2 规则写入认证与确认。** 推荐在 `third_party/RobotPilot/ros2/src/robotpilot_ui_package/robotpilot_ui_package/platform_api.py` 增加 Engineer 认证且基于 `apiFetch` 的规则写接口；保留/封装 ROS 内部命令和版本冲突语义。应支持 request_id、map_id、map_version_id、expected_version、idempotency 与返回机器人 ack；根据可用性返回“已保存 / 已发布 / 已被导航层应用”。限制 ROSBridge 未授权发写命令。

**P0.3 规则生效状态。** `area_rules` 发布带 `rules_version`、`mask_generation`、`map_key` 的状态；Nav2 实际消费应增加独立验证（例如观测 global_costmap 最终代价或受控测试组件校验），在不能确认时显示未生效且保持需要的导航安全 hold。对因服务不可用、地图变更、TF 失效造成的数据过期继续 fail-closed。

**P0.4 制动与区域碰撞。** 复查当前基于 `(当前位置, 前方 0.2/0.4m)`、`0.84m` 半径的策略；加入真实车体旋转 footprint、反向行驶、速度方向、反应时间与制动距离相关的提前限速/停车，使用底盘实际反馈验证，不能仅以目标 `Twist` 为证据。对「在机器人当前位置直接绘制禁区」给出明确操作限制或受控人工恢复机制，不应放行自动越禁区。

### P1：实现动态地图规则 → 当前路径闭环（本需求的关键）

建议优先扩展 `src/planning/smac_neupan_bridge` 或引入职责明确、带测试的导航规则协调组件，而不是直接在 React 调 `/goal_pose`。

1. 监听规则版本/地图标识/实际过滤后的 costmap 更新，识别禁行、墙、临时封闭的新增、删除或改变。
2. 保存**当前目标、当前路径、当前路径所属规则版本**，对路径完整折线以及车辆 footprint sweep 做冲突检测；**不能只看终点是否在禁区，也不能只看路径采样点而忽略两点之间穿越线墙。**
3. 对新增阻挡且旧路径被影响的变更，首先保持输出零速/导航规则 hold。规划未完成前，不得继续跟踪旧路径。当前 RobotPilot/NeuPAN 对空 `/plan` 直接忽略；不要依赖发布空路径作为唯一停机手段。
4. 确认 Nav2 已应用对应版本规则后，以同一个目标从当前安全位姿重新向 Smac 计算路径；用 `goal_generation` 或请求序号拒绝过期结果。拒绝不匹配地图、旧规则版本、穿越禁区的规划返回。
5. 新路径验证通过后发布新的 `/plan`，确认 NeuPAN 已安装新路径（需要明确的确认机制），再解除导航规则 hold。未收到确认、规划无解、目标落入禁区、定位状态过期都应保持停车且报告可解释状态。
6. 对预先存在且不受变更影响的在途路径，可以继续运动，但前提是导航已应用版本被验证，安全仲裁仍有效。
7. 任务级状态需表达 `RULE_REPLAN_PENDING / RULE_BLOCKED / RULE_REPLAN_SUCCEEDED / RULE_REPLAN_FAILED`（名称仅为建议）；交由 MissionManager / NavStatus 以非终态处理规划等待，不要错误地将「规则等待重规划」当作「抵达」或无条件失败，也不得突破原有暂停、取消和 software stop 状态。
8. 规则删除、临时封闭到期后的路径优化是可选；**不可**因为规则消失就自动解除操作员的软件急停或原本暂停的任务。

### P2：强化限速与运动控制闭环

1. 保留 `cmd_vel_mux` 对 `/cmd_vel` 和 `/neupan_cmd_vel` 的统一约束；禁止绕过 mux 的底盘指令路径，实机核查实际 topic remapping。
2. 限速考虑双向行驶、车体长度、未来轨迹、实际 `odom`、加速度/减速度上限，提前减速以保证**进入区边界前**符合限速。现有仅乘比例限制 `Twist` 是基础防线，不构成制动距离证明。
3. 多个限速区域重叠时取最小上限；退出区域应有平滑加速度恢复；区域超时/TF 过期时不得默默恢复全速。
4. 导航 UI 区分 `配置限速`、`当前约束速度`、`实际反馈速度`；超速时告警及停止策略须由实车测试明确。
5. 禁行触发不要在高速进入包络后才停车；必要时加入速度相关的远端预测和障碍前保护。

### P3：地图编辑 UI 的精简与可用性

建议只保留一个地图编辑工作区，桌面采用左地图右规则面板：

- 顶部：当前地图、2D/3D 配对、地图版本、规则服务状态、规则已应用状态。状态不可混淆。
- 左侧：现有 Map Canvas，不重复创建地图。色彩区分禁行（红）、限速（黄）、墙（紫）、临时封闭（橙）；显示规划路径、机器人轮廓/安全包络、当前目标与受影响路段。
- 右侧：四种类型选择 → 名称/参数 → 地图绘制 → **预览编辑** → 二次确认应用；有规则列表、筛选、选中高亮、修改、禁用/启用、删除。危险操作显示对当前任务的影响。
- 临时封闭：优先传时长，由机器人服务端计算过期时间，展示剩余时间；列表中区分有效/即将到期/已到期。
- 当规则与当前路径冲突：明确展示「当前任务需要重新规划」「正在停车并规划」「无可行路线，保持停车」等状态。
- 指针操作支持鼠标、触控笔和触屏，绘制完成自动退出绘制模式；支持取消、坐标修正、撤销当前预览（不是越权撤销已应用规则）。
- 规则提交后采用 `PENDING → STORED → APPLIED/FAILED` 状态机。没有后端确认时不得把规则标成「已生效」。支持错误原因、重试、重新加载，保持旧规则直至新规则验证通过。
- 继续使用既有 React 18、Tailwind、`DashboardCard`、Map 及 `apiFetch`，不要做独立于现有主题和权限体系的新页面。

## 6. 建议数据契约

保留旧 JSON 字段兼容，同时在权威状态增加（示意；具体字段由 Codex 在改造时确定）：

```json
{
  "request_id": "uuid",
  "map_id": "map-2d-id",
  "map_version_id": "version-2d-id",
  "map_key": "occupancy-grid-hash",
  "expected_version": 12,
  "action": "upsert",
  "rule": {
    "id": "zone-a",
    "type": "closure",
    "name": "临时施工封闭",
    "cx": 3.0,
    "cy": 6.0,
    "w": 2.0,
    "h": 1.5,
    "duration_seconds": 1800
  }
}
```

这里的 `duration_seconds` 是**建议新增的服务端接口字段**，不是仓库现有 `area_rules` 命令支持的字段。旧接口目前要求 `expires_at`，需通过兼容适配转换并让服务器/机器人时钟成为权威，不能把这段示意 JSON 原样发送到旧代码。`map_key` 目前是关键，不能直接用 `map_id` 替代内容验证。

规则状态建议提供：`stored_version`、`applied_mask_version`、`navigation_hold_reason`、`active_path_rule_version`、`navigation_replan_status`、`speed_limit_mps`、`source_timestamp`。发布频率和可靠 QoS 应根据 ROS2 生命周期确定；没有实测闭环前不得虚报应用成功。

## 7. 按文件划分的 Codex 改动建议

**必须重点修改：**

- `src/planning/smac_neupan_bridge/src/smac_neupan_bridge.cpp` / `include/...hpp`：监听规则状态、维护当前路径/目标、冲突检测、重规划、过期结果处理、故障报告。若复杂度过大可建独立 `navigation_rule_guard`，但要避免重复控制源。
- `src/control/vehicle_control/cmd_vel_mux.py`：规则导航 hold 源、停止互锁、按实际运行方向提前限速，保持原 software stop 安全优先级。
- `src/extension/area_rules/area_rules/node.py`、`rules.py`：权威地图关联、规则版本/掩码版本、激活确认与状态、服务器端临时规则 TTL、制动包络计算。
- `src/extension/nav_status/src/nav_status_node.cpp`、`src/extension/mission_manager/mission_manager/node.py`：在途重规划状态，任务暂停/恢复/失败的协调，不破坏现有巡检执行语义。
- `third_party/RobotPilot/web/src/pages/MapsPage.jsx`、`src/components/AreaRulesEditor.jsx`、`KeepoutZones.jsx`、`Map.jsx`、`src/shared/hooks/useKeepoutZones.js`：真正可操作的规则编辑和反馈。
- `src/bringup/config/smac_planner.yaml`、`src/bringup/launch/{navigation,planning}.launch.py`：检查或接入规则守护组件、实际 Nav2 costmap、生命周期与 QoS；不得误改 NeuPAN 话题及安全开关。

**可选最小新增：**

- 平台受保护地图规则 API：`third_party/RobotPilot/ros2/src/robotpilot_ui_package/robotpilot_ui_package/platform_api.py`；改动之前先核查现有 ROSBridge 访问控制，避免与既有前端权限机制冲突。
- 独立纯函数模块做路径与规则几何冲突检测，并配 unit tests；不要把所有规则策略写在巨型 ROS node 回调里。

## 8. 必须覆盖的测试

### 单元测试

1. 4 种规则合法/非法参数、边界/零宽/墙过短、重叠规则、旋转 OccupancyGrid、地图切换与持久化。
2. 路径**线段**与禁区/墙相交、车辆 footprint 扫掠、逆向移动、地图原点/分辨率变化、目标在封闭区内。
3. 并发编辑、旧 `expected_version`、重复请求/超时 ack、机器人重启规则恢复，错误 map_version 拒绝激活。
4. 规则 TTL 到期移除、时钟不一致、保存失败、不允许因结束封闭解除人工急停。
5. `cmd_vel_mux` 对手动/自动源以及规则 hold、stop、TF/规则服务失联的 fail-closed；限速进出区域和负速度。
6. 新规划结果到来后旧 generation 不得覆盖；空 `/plan` 不视作已成功取消旧路线。

### 集成/仿真

A. 静态禁行：先画禁区 → Smac 计算路径 → 路径绕行且 costmap 中有相应不可通行值。

B. 动态禁区：机器人沿既有路径运行 → 在前方新增禁区/虚拟墙 → 停止旧路径、重新规划后绕行 → 到达目标；若无解则停住并明确报告阻断。

C. 临时封闭：在途封闭 → 生效 → 到期或授权删除 → 掩码更新；不得无条件恢复暂停/软件停机中的任务。

D. 限速：在进入区之前减速，在区内实测速度不超过要求（加测后退、重叠、边界和失联情况）；离开后按上限加速度恢复。

E. 地图切换：仅切换 2D / map bundle 不匹配时拒绝导航激活；配对地图正式加载后才允许规则应用。

F. 生效确认：模拟 area_rules publish 成功但 Nav2 filter 没有消费，前端必须显示「未确认生效」，导航不能误报安全。

G. 跨重启：规则持久保存、临时封闭未过期才恢复、地图 A 的规则不污染地图 B。

H. ROSBridge 权限：Viewer/Operator 不能绕过后端直接变更规则。

测试建议：对应 `src/extension/area_rules/test`、`src/control/vehicle_control/test`、`src/bringup/test`、`third_party/RobotPilot/web` 的 Vitest。真实 ROS2/仿真场景无法从纯文件代码核查完成，需要 Codex 或现场验证记录日志、topic、costmap 可视化和车辆速度测量。

## 9. 风险与实施顺序

- **高风险**：动态更新时继续跟踪旧路径、Nav2 未消费新 mask 却自动放行、地图 2D/3D 错配、覆盖车辆当前位置的禁区、限速触发太晚或反向未覆盖、不同节点重复写 `/mission/hold`。
- **优先级**：先完成 P0 地图身份/规则生效/独立停机互锁；再完成 P1 当前路径失效与重新规划；再 P2 速度实测闭环；最后 P3 交互优化。**前端好看不算完成。**
- **明确边界**：软件限速/禁区是运行约束，不能替代真实急停、传感器避障和底盘硬件安全控制。

## 10. 可直接给 Codex 的执行指令

请在仓库源码中实施《Alpha 地图规则与导航联动——源码分析及 Codex 实施方案》。优先复用已有 `area_rules`/Nav2 CostmapFilter/Smac/NeuPAN/cmd_vel_mux。先核查现有实际启动和话题，逐阶段改动 P0→P1→P2→P3；每阶段都要附代码 diff、测试日志和不可验证项说明。**强制验收**：机器人在跟随旧路径时新增禁行/虚拟墙/临时封闭，不得继续沿旧路线进入新禁区；应安全停止、核实规则应用、重新规划、验证路径与当前地图版本，再恢复。限速必须同时约束手动和自动控制，并有前瞻/制动距离及实测验证。禁止仅调整地图前端图层、以本地保存或 ROS ack 冒充导航已生效。不可破坏原有 `/route` 任务规划、MissionManager、软件急停、map bundle 校验和现有 API 的兼容性。最终提交 PR、测试报告和仿真/实际复现步骤。

## 11. 参考文件链接

- [地图规则组件](https://github.com/YansenSong/Alpha/blob/main/third_party/RobotPilot/web/src/components/AreaRulesEditor.jsx)
- [地图规则 Hook](https://github.com/YansenSong/Alpha/blob/main/third_party/RobotPilot/web/src/shared/hooks/useKeepoutZones.js)
- [规则 ROS2 节点](https://github.com/YansenSong/Alpha/blob/main/src/extension/area_rules/area_rules/node.py)
- [规则几何与存储](https://github.com/YansenSong/Alpha/blob/main/src/extension/area_rules/area_rules/rules.py)
- [Nav2 参数](https://github.com/YansenSong/Alpha/blob/main/src/bringup/config/smac_planner.yaml)
- [Smac → NeuPAN 桥接](https://github.com/YansenSong/Alpha/blob/main/src/planning/smac_neupan_bridge/src/smac_neupan_bridge.cpp)
- [NeuPAN path_callback](https://github.com/YansenSong/Alpha/blob/main/src/control/neupan_ros2/neupan_ros2/neupan_node.py)
- [速度仲裁](https://github.com/YansenSong/Alpha/blob/main/src/control/vehicle_control/cmd_vel_mux.py)
- [地图包校验](https://github.com/YansenSong/Alpha/blob/main/src/extension/mission_manager/mission_manager/map_bundle.py)
