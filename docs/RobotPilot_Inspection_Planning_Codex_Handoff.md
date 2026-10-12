# RobotPilot「巡检任务规划」前端重构 — Codex 执行交接文档

> **任务性质**：基于现有源码的交互、信息架构与必要的数据闭环重构，不是简单换皮。  
> **仓库**：[`YansenSong/Alpha`](https://github.com/YansenSong/Alpha)  
> **代码范围**：`third_party/RobotPilot/web`（主要）；必要时可修改 `third_party/RobotPilot/ros2/.../platform_api.py` 与 `src/extension/mission_manager`（最小化、带测试）  
> **分析基线**：`main`，`29f1a6f6795af30786c3c645be7075cb4931a15f`（2026-10-11 获取）  
> **说明**：此分析基于 GitHub 源码静态阅读，**没有**运行真实机器人或浏览器验收；实现前需由 Codex 在本地复核 HEAD、接口和实际 UI。

## 0. 给 Codex 的直接执行指令（先读）

你现在负责重构 `third_party/RobotPilot/web` 下 `/route`（侧边栏「巡检任务规划」）页面。**请真正修改代码、测试并提交 PR；不要只提供 UI 方案。** 遵循以下文档的目标、契约、验收准则和边界。

1. 先检查当前实际代码、运行项目可执行的前端测试/构建基线，列出可能影响的后端契约，再实现。
2. 页面只保留三个**一级业务大卡片**：①「巡检任务编排与管理」②「巡检点创建与管理」③「执行历史与日志」。地图作为前两个卡片的**一个共享工作区**，不要再制造独立的第四张一级业务卡片，不要创建两份互不一致的地图实例。
3. UI 统一使用「巡检点」这一用户可见概念：**有业务动作的巡检点**、**仅途经的巡检点**；禁止把后者继续作为第三种用户概念「临时航点」平行呈现。保留机器人协议中的 `waypoint` 字段和步骤类型，不要盲目改底层协议名称。
4. 彻底合并现有「本地混合编排草稿」与「只含业务点的任务模板编译」双入口；真正完成“新增/插入、排序、保存、列表管理、重新编辑、执行、查看历史”的闭环。**本地草稿不得冒充机器人端已保存任务。**
5. 兼容现有用户数据、鉴权、地图版本绑定、检测能力检查及旧 API；后端如需改动，仅做必要的兼容性扩展，并增加单元/集成测试。
6. 使用已存在的 React 18、Vite、Tailwind、DashboardCard、apiFetch、角色权限与地图组件；不要引入重型 UI 框架或新状态管理库，除非能够充分证明必要性。
7. 交付 PR 中应包含：代码改动说明、前后交互差异、接口兼容情况、测试与构建结果、至少桌面/平板/移动端截图、尚未实现的依赖和风险。

**完成定义不是“页面看起来整齐”**：必须验证真实保存/读取/编辑、地图选点、多点混合路线、执行前安全校验和日志对应关系。

## 1. 用户目标与范围

用户操作模型：**先建立巡检点 → 再编排巡检任务 → 最后追踪执行结果**。一次任务是一条有序路线；其中某些点到达后执行业务动作（拍照、消防检查等），其他点只用于约束机器人途经路线。三块功能应互相关联，但拥有清晰且唯一的编辑入口。

### 1.1 必须具备的功能

**卡片 A：巡检任务编排与管理**
- 任务列表：查看、新建、打开编辑、保存、另存为/复制、删除；显示任务名称、点位数量、路线顺序、当前地图、状态/最后修改时间（缺失的数据不要伪造）。
- 任务编辑：从已保存巡检点库添加点；点击点与地图相互定位；拖拽或上下移动排序（键盘可操作）；**任意相邻两个点之间插入**「仅途经的巡检点」，包含位置和朝向；删除路线步骤；路线可见地连线并带序号；保存前预览与校验。
- 任务详情清楚呈现每步：`01 入口拍照 · 拍照`、`02 走廊转角 · 仅途经`、`03 消防柜 · 消防识别`。不让使用者猜 `inspection` / `transit` 的内部含义。
- 对已有任务可再次打开、编辑、保存；保存成功后刷新仍能找回；可选择执行任务，明确执行门槛和阻塞原因。
- 默认一次只编辑一个任务；未保存修改在切换/关闭/离开页面时提示；刷新或断线不得悄悄伪装保存成功。

**卡片 B：巡检点创建与管理**
- 点击「地图选择位置」，在共享地图上选择坐标+朝向，明确展示当前地图/版本、所选坐标与选点状态；支持取消与重新选点。
- 输入名称；选择「仅途经」或添加 1 个及以上到点业务动作；动作编辑（拍照、消防设施识别、烟火识别、语音播报、等待等）与当前 action-plan 能力保持兼容。
- 列表支持名称/ID 搜索、业务类型筛选、地图定位、高亮、编辑名称/位置/朝向/启停状态/动作、删除。
- 业务配置暂不可执行时能**保存配置但清晰标明受限**；不允许因 Provider 暂时离线就把正常的点位编辑能力全部禁用。
- 编辑/删除被任务引用的巡检点，必须显示引用关系或冲突处理；不允许隐式破坏已保存任务。创建点位后若动作保存失败，应显示「点已创建，业务动作未保存」并提供重试/继续编辑，不可显示“完全成功”。

**卡片 C：执行历史与日志**
- 统一任务运行记录：筛选任务/状态/时间，查看执行中与历史任务；列表优先显示任务名、开始/结束、状态、进度、失败原因。
- 详情采用步骤时间线并关联检查结果、业务告警、证据元数据（媒体未接入要如实说明）；可从历史定位回对应任务定义，辨别“定义”和“一次执行实例”。
- 切实反映服务器返回的历史范围；现有 API 只携带 MissionManager 近期记录，不可写成“全量归档”，不能伪造更早数据。若需要真正持久化分页历史，则新增相应后端查询能力并覆盖测试。

### 1.2 明确不做

- 不重构 ROS 导航、地图底层渲染算法、避障规划、安全门禁。
- 不擅自移除充电点、避雨点等已有特殊点类型与相关页面能力。
- 不把检测占位能力渲染成已接入真实检测，不改变 simulation/fixture 与真实机器人能力边界。
- 不新增第四个顶层“航点管理”区、不保留两套并行任务编辑器、不把浏览器 localStorage 作为机器人端正式任务库。
- 不将 `point_type: "transit"` 直接写入现有 waypoint API（当前不支持）。

## 2. 源码核查结果（证据位置）

以下路径基于上述基线 commit，可直接在 GitHub 按路径定位。

| 位置 | 当前责任/问题 | Codex 处置 |
|---|---|---|
| `web/src/pages/registry.js` | `/route` → `RoutePage`，这是目标页入口 | 维持路由与导航标签 |
| `web/src/pages/RoutePage.jsx` | 地图、选巡检点/临时航点、嵌套整个 `WaypointActionsPage` 与 `InspectionPage`；主页面之外还有多个重复标题和卡片 | 重建为三个一级卡片 + 一个共享地图交互控制器 |
| `web/src/components/InspectionTaskComposer.jsx` | 支持巡检点与原始坐标混合排序，但 `save()` 仅写 `localStorage` 键 `robotpilot:inspection-composition:${robotId}:${mapId}`，提示「混合任务下发接口尚未接入」 | **废除其“正式保存”表述；将能力迁移到真正持久化的唯一编排器**；旧草稿仅可提示/迁移 |
| `web/src/pages/WaypointActionsPage.jsx` | 同时包含点管理、动作管理、仅巡检点模板编译、单点下发；本身再生成 SectionHeader/大卡片，造成层级混乱 | 拆成点位管理与业务动作面板、任务服务调用等；删除第二套编排入口 |
| `web/src/components/InspectionPointCreate.jsx` | 地图位置＋动作预设创建；先 POST waypoint，再 PUT action-plan；**在动作保存之前即调用 `onCreated`** | 修复分段成功状态及刷新时机，将「仅途经」作为无动作点创建 |
| `web/src/pages/InspectionPage.jsx` | 历史、巡检结果、告警的完整页面直接嵌入目标页；历史可过滤但缺少统一详情视图 | 提炼可嵌入的单一卡片，不再嵌整个 Page |
| `web/src/components/Map.jsx`, `web/public/ros/nav2d.js` | 地图依赖 `window.NAV2D`；选点 callback 与不同页面共享全局状态；`Map` 右键菜单也可复用 | 保持**单实例/单选点模式**；确保挂载/卸载、模式切换清理 callback |
| `web/src/components/MapLayers.jsx` | 默认展开大量图层开关与透明度 | 下沉到地图「图层设置」可折叠区域，默认只显示最关键项 |
| `web/src/shared/hooks/useSavedWaypoints.js` | 另有机器人 waypoint CRUD hook、ROS 地图身份、版本与 stale 逻辑；同时存在旧 localStorage 导入 | 避免在新页面再造冲突的点位缓存，抽取共享可复用能力并以服务器为准 |
| `web/src/shared/missions/taskApi.js` | 存在审计命令 API：GET/POST/DELETE missions、任务启动与控制以及 ACK 等待工具；`startOneOffMission` 能保存常规地图绑定任务 | 复用通信与幂等处理，不把 `POST /missions` 等同于业务编译校验 |
| `web/src/pages/SchedulerPage.jsx` | 调度页读取 `/missions`；依赖可复用 mission，不能被新任务命名/保存破坏 | 保持可调度任务兼容与 `manual-*` 排除语义 |
| `web/src/shared/ui/Dashboard.jsx`, `web/src/shared/styles/global.css` | DashboardCard、状态徽标、空状态、现有设计 token | 复用一致的卡片/按钮/提示视觉语言 |
| `web/src/shared/auth/roleAccess.js` | Viewer < Operator < Engineer < Admin | 按实际 API 权限控制，不用一个 Engineer 权限把所有任务操作锁死 |
| `web/src/pages/MapPage.jsx` | 操控地图页另有 waypoint 库、NAV2D callback、巡检告警图层；告警点击会跳向 `/inspection?alert_id=...`，但当前 `registry.js` 没有注册 `/inspection` | 注意路由联动，避免从地图页跳到不存在的路由；保留 Cockpit 功能 |

**关键诊断**：当前存在两套编排路径：① 浏览器本地保存“巡检点+临时航点”；② `/inspection/tasks` 的 `compile_only` 服务端编译业务点模板。两者**不是同一个可重新打开的真实任务实体**。这才是本次结构重构最必须解决的逻辑重复。

### 2.1 已核实的 API / 数据事实（不得假设）

1. `GET/POST/PATCH/DELETE /api/v1/robots/{robotId}/waypoints`：点位持久化在平台数据库；带 `map_id` / `map_version_id` / revision；创建与修改需 Engineer；当前 `point_type` 限 `inspection | charge | shelter`。PATCH/DELETE 使用 `If-Match` 乐观锁；删除正在被 mission 引用的点会返回 409。
2. `GET/PUT /waypoints/{id}/action-plan`：动作草案另存，`actions` 最多 20 项，现有类型 `wait | capture | detect | broadcast`；GET 未创建时可能返回 404；PUT 使用独立 action-plan revision 和 `If-Match`。
3. `POST /inspection/tasks`：当前 JSON **仅接受** `{name, waypoint_ids, compile_only}`，其中 1–50 个 `waypoint_ids` **必须唯一**，需要 `Idempotency-Key`；`compile_only:true` 真正保存 mission，但不会启动任务；每个点需非空动作计划，且至少有一个非等待类 `inspection_action`；不能把只有纯途经点的混合路线直接交给此接口。
4. `GET /missions`、`GET /missions/{id}`、`POST /missions`、`PUT /missions/{id}`、`DELETE /missions/{id}`、`POST /tasks`：任务定义保存/编辑/删除与任务启动已有通道（Operator）；但“直接传 mission steps”不能替代服务端对业务动作、资产关联、地图身份等的统一编译与验证。
5. MissionManager 校验 `steps`（最多 200 项），其原生可执行 `type: "waypoint"` 带 map-frame `pose:{x,y,z,w}`；其后可紧跟 `type: "wait"`、`type: "inspection_action"`，并用 `waypoint_id` 关联上一个抵达点。**这为统一业务模型提供了落地基础。**
6. `GET /inspection/tasks` 从 MissionManager 当前任务和最近约 10 条历史中过滤巡检任务，通常识别 `inspection-` mission ID 或包含 `inspection_action` 的任务；返回 `history_window_limited`。`GET /inspection/results`、`GET /inspection/alerts` 等已有结果/告警接口。不保证全量历史归档。
7. `useRobotStatus()` 拉 `/status`（轮询并监听事件），点位/任务应绑定**当前地图版本**并尊重 stale 状态；地图/版本改变需禁止误操作并提示迁移或重新选择。

服务端核查点：
- `third_party/RobotPilot/ros2/src/robotpilot_ui_package/robotpilot_ui_package/platform_api.py`：`waypoint_payload`、`platform_*waypoint`、`platform_*mission`、`s1_action_plan`、`s1_create_inspection_task`、`s1_inspection_tasks`。
- `src/extension/mission_manager/mission_manager/node.py`：`validated_mission`、`_start_mission`、`inspection_action_capability_block_reason`。
- `src/extension/mission_manager/mission_manager/store.py`：mission 定义和运行记录实际有 SQLite 存储。

## 3. 最终界面布局与交互

### 3.1 信息架构（**恰好三个一级业务大卡片**）

```text
巡检任务规划                                     当前机器人 / 地图版本 / 连接状态
一行短提示：创建点 → 编排任务 → 查看执行结果

┌──────────────────────────────────────────────────┐ ┌───────────────────────────────┐
│ ① 巡检任务编排与管理                             │ │ ② 巡检点创建与管理              │
│ [任务选择 ▼] [+新建] [复制] [删除]                │ │ [+地图选点] [取消选点]          │
│ 任务名称 [________________] [保存] [执行]         │ │ 位置 (x,y,yaw) · 地图版本       │
│                                                  │ │ 名称 [___________________]     │
│ ┌──────── 同一张地图 ──────────────────────────┐ │ │ 类型：[仅途经] / [到点执行业务]│
│ │ 当前路线编号/连线/选中点定位/地图选点          │ │ │ 动作清单 + 保存点位             │
│ │（模式由全页统一控制，不再显示两个“航点”入口）  │ │ ├───────────────────────────────┤
│ └──────────────────────────────────────────────┘ │ │ 搜索 / 筛选                    │
│ [从点库添加 ▼] [+加入] [在选中步骤之后插入]      │ │ 已保存点位列表                  │
│ 01 拍照点     · 拍照                ↑ ↓ ×         │ │ 仅途经/拍照/消防检查标记        │
│ 02 走廊转角   · 仅途经              ↑ ↓ ×         │ │ [查看] [修改] [删除]            │
│ 03 消防点     · 消防检查            ↑ ↓ ×         │ │                                │
└──────────────────────────────────────────────────┘ └───────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────────────┐
│ ③ 执行历史与日志                                                                    │
│ [任务筛选] [状态] [时间范围] [刷新]                                                    │
│ 运行列表：任务名 | 任务实例 ID | 开始/结束 | 状态 | 进度 | 异常摘要                     │
│ 展开某次执行 → 步骤时间线 / 结果 / 告警 / 证据元数据 / 数据完整性提示                   │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

**视觉约束**：桌面端 2:1 或接近 2:1 的双列，历史整行；中小屏上下堆叠。嵌套内容不是另一个巨型 DashboardCard：用轻量分组、分隔线或抽屉即可。只保留一个页面标题；导航不换名；按钮层级清晰，主按钮在每卡右上或固定操作区；默认隐藏高级图层、调试字段、原始 JSON、内部 ID（可在详情中复制）。大部分用户应能在 3 步内完成“点选→编辑→保存”或“选任务→插点→保存”。

**共享地图实现**：视觉上将地图放在卡片 A 左侧大区域；卡片 B 的“在地图上选择位置”向同一个地图发布 `create-point` 模式，地图头明确显示“正在为巡检点选位”，选完自动返回点位表单。卡片 A 的“在第 N 步后插入仅途经巡检点”发布 `insert-route-point` 模式。不能为了实现“两个卡片都有地图交互”创建两张 ROS 地图。移动端点击卡片 B 选点时应自动滚动/聚焦到地图，选中后返回卡片 B 表单，不能让用户迷路。

### 3.2 统一概念：前端展示模型，非数据库大迁移

```ts
// 仅为 UI/domain 草案，具体命名可调整；业务身份以 waypoint_id 为准。
type InspectionPointView = {
  waypointId: string;
  mapId: string;
  mapVersionId: string;
  name: string;
  pose: { x: number; y: number; yaw: number };
  enabled: boolean;
  actions: ActionPlanAction[];  // [] => 仅途经
  usage: "transit-only" | "business"; // 派生的展示标签，非必需的后端 point_type
  waypointRevision: number;
  actionPlanRevision: number | null;
};

type PlannedStop = {
  uiStepId: string;      // 排序稳定键：同一 waypoint 可以在不同步骤再次出现
  waypointId: string;    // 持久化点位引用
  executeActions: boolean; // false => 仅途经，即使点库原点有业务动作也不执行
};
```

- **所有点在 UI 中都叫巡检点**，有动作的显示「业务点/拍照/消防识别」，无动作的显示「仅途经」。不要给用户暴露新的“航点类型”选择器。
- 两层模型要分清：**点库定义**（坐标、动作、启停）与**任务中的一次步骤引用**（顺序、是否执行业务）。允许同一点在一次路线重复出现时，底层需要按**位置索引**生成唯一 step ID，不能复用当前编译器仅用 `waypoint_id` 生成的 step ID。
- 非业务点保存为合法现有 waypoint（建议 `point_type:"inspection"` + 空/未配置 action-plan），不得发当前 API 不认识的 `transit` 枚举；充电/避雨的特殊类型保留原义。
- 步骤在服务端编译为 `waypoint` (+ 可选 `wait`/`inspection_action`)；业务动作绑定到到达对应点之后；不得在前端自行执行 ROS 导航命令。
- 从旧 localStorage 发现混合编排草稿时，可显示**仅一次性“导入旧草稿”**，在预览后逐项将未持久化坐标转换成点位并请求服务端保存。无网络、无权限、版本不匹配时仅能保留为本地草稿，必须明确区分。

### 3.3 交互状态与错误体验

- 全页一个操作模式：`idle | selecting-new-point | selecting-insert-point | selecting-edit-position`；单个模式设置 `NAV2D.arePointsSettable` 和 `_poseCallback`，模式退出/路由切换/地图卸载**恢复原状态并清理监听**。地图初始化可能是异步的，不可假定第一帧就准备好。
- 路线编排区保存前给出汇总：“共 3 个点，2 个业务点，1 个仅途经点”；有断开的点、地图版本不一致、禁用点、无动作却勾选执行业务的点，逐项高亮并禁用保存或提供可解释的修复。
- 任何 POST/PUT/PATCH/DELETE 都显示进行中/成功/失败；失败不得乐观显示“已保存”；重复点击禁用；显示 409/412 冲突处理与“重新加载”按钮；任务保存按命令 ACK + 回读确认。
- 任务的「定义保存」与「立即执行」分按钮，执行时确认并显示门槛：机器人地图/版本一致、Provider 及心跳、动作能力、运行模式、安全门禁、当前是否已有运行任务；只允许 Operator 执行，只有 Engineer 能维护点及动作。
- 页面数据请求可重试、空态友好；显示加载中、无当前地图、断线/状态过期、无权限、Provider 未连接等状态。
- 历史只显示后端真实 `source`/`outcome`，模拟/Fixture 不得文案伪装真实识别结果。

## 4. 保存与执行：关键技术方案（不能跳过）

### 4.1 推荐的单一数据通路

```
API 机器人点位库 (+ 独立动作计划) → 前端 InspectionPointView
  ↓ 任务编排产生按顺序的 PlannedStop[]
服务端校验并编译 → 持久化 mission definition（含 map_id + map_version_id）
  ↓ 再从 /missions 回读列表、打开编辑 / 另存为 / 删除
任务执行：POST /tasks { mission_id } → MissionManager
  ↓
/inspection/tasks + /inspection/results + /inspection/alerts → 统一历史卡片
```

**推荐在 `platform_api.py` 对既有 `/inspection/tasks` 提供向后兼容的“有序点步骤”编译扩展，或新增版本化编译接口**。新请求示意（**拟议契约，不是现有 API**）：

```json
{
  "name": "一层消防巡检",
  "points": [
    { "waypoint_id": "point-photo", "execute_actions": true },
    { "waypoint_id": "point-corridor", "execute_actions": false },
    { "waypoint_id": "point-fire", "execute_actions": true }
  ],
  "compile_only": true,
  "mission_id": null
}
```

Codex 应根据当前服务端实际模型确定**最小改法**：保持旧 `{name, waypoint_ids, compile_only}` 无破坏；新输入按顺序核验存在、启用、地图版本、动作、关联资产，编译成合法 MissionManager 步骤并持久化；如果提供 `mission_id` 做更新，先确认目标属于可编辑巡检 mission、遵守运行中/调度引用约束，并保证重编译不会悄悄覆盖其他任务。对重复点生成稳定且**唯一**的 step id；限制总点数、总动作数和 200 step 上限；保证幂等请求不会重复创建任务；纯途经路线若支持应存为“导航-only 巡检任务”，如果明确不允许，则要给用户可见、合理的校验说明。

`/missions` 的直接 save/update 可以作为**验证过的实现选择**，但不应绕开或重写现有检查动作编译和资产校验。对每一种方案都要写后端契约测试及前端 service 测试。需要保障已保存任务二次编辑后行为可预测：尤其是**点位坐标/动作改变后，旧任务默认保留已编译快照还是重新同步**，建议保持“任务执行使用保存时快照”，仅用户主动“重新编译/同步最新点位”才更新。UI 需提示此规则。

### 4.2 任务管理与历史的边界

- 列表来源是 `GET /missions`，不是 `localStorage`，也不是 `GET /inspection/tasks`（后者是**运行实例**）。必要时使用 prefix/元数据判定当前巡检业务任务；后端 `validated_mission` 当前会裁剪非约定自定义属性，不能假设能随手增加 `mission_type` 并被保存。
- `GET /inspection/tasks` 是最近历史筛选；现在的历史窗口**不等于**真正数据库完整历史。优先实现诚实展示、分页/`next_offset` 在窗口内工作。若项目目标要求更早全量历史，补一条来自 MissionManager 持久化 `runs` 的查询通路，而不是扩大前端 `limit` 误称归档。
- 针对纯途经任务，若仍使用该历史 API，需确保其 mission ID 约定或服务端判定逻辑能将其识别为巡检任务；否则它可能在执行记录卡片中“消失”。
- 对历史中的结果/告警使用任务 ID 关联；不可简单把所有告警都当成当前任务的结果。

### 4.3 前端模块重组建议（可调整，但职责不可回退）

```text
web/src/features/inspection-planning/
  components/
    TaskPlanningCard.jsx         # 唯一任务编排器 + 管理列表 + 地图预览
    InspectionPointsCard.jsx     # 唯一点位 CRUD + 动作计划编辑
    ExecutionHistoryCard.jsx    # 运行记录、结果/告警抽屉
    PlanningMap.jsx             # Map 的单个共享实例，操作模式受父层控制
    OrderedPointList.jsx        # 有序步骤，插入/移动/聚焦
  hooks/
    usePlanningMapMode.js       # 管理 NAV2D 回调生命周期
    useInspectionPoints.js      # 服务端 CRUD + action plan，统一缓存
    useInspectionMissions.js    # 服务端任务定义 CRUD + 编译/ACK
    useInspectionHistory.js     # 状态/历史/结果独立请求
  api/inspectionPlanningApi.js  # 统一封装现有 apiFetch，明确失败类型
  domain/inspectionPlan.js      # 点位展示模型、计划转换及验证（纯函数）
web/src/pages/RoutePage.jsx     # 仅组装页面三卡、当前机器人/地图上下文
```

允许在旧位置保留 re-export 兼容，但**不得在新页面同时渲染 `WaypointActionsPage` 与另一个任务编排器**。也不要让 `InspectionPage` 直接作为卡片的子页面再次带来自己的一级 SectionHeader。状态提升至共享容器，切换任务/点位后按 ID 关联，清理异步请求过期响应（AbortController / sequence guard）。

## 5. 分阶段实施计划（建议拆为几个可审查提交）

**阶段 P0 — 架构与数据契约核验**
- 运行 `web` 的 `npm ci && npm test && npm run build`（环境适配后）；实际检查 `Map.jsx` / `nav2d.js` 选点生命周期、`/status` 地图身份。
- 对照接口实现确认命令 ACK、动作 revision、地图版本、MissionManager step schema、调度页面现有依赖；记录已有测试基线。
- 决定服务端最小兼容接口方案，并先写混合点编译契约测试。

**阶段 P1 — 点位库统一**
- 整合 `InspectionPointCreate` 与 `WaypointActionsPage` 中分裂的点编辑能力，交给单个点位卡片；统一数据刷新和点位修订冲突反馈。
- 允许只途经（无业务动作）点的创建、编辑和持久化；保留动作顺序、参数和已存在资产关联；处理两阶段保存的部分失败。
- 列表与地图选中联动；Role/Map stale 真实控制；地图只挂一个实例。

**阶段 P2 — 任务编排真正持久化**
- 实现拖拽/键盘可排序列表、任意位置插点、路线预览、点击点高亮及已保存点库选择。
- 合并旧 `InspectionTaskComposer` 和「仅业务点模板」，实现新建/复制/编辑/删除/保存/回读/执行；若后端不支持混合路线，先实现最小后端兼容扩展，不可继续以 localStorage 冒充成功。
- 处理原 mission 兼容、调度引用、点位失效、旧草稿可选导入。

**阶段 P3 — 历史、体验与视觉收尾**
- 把执行历史、结果、证据和告警放入第三张一级大卡片；详情抽屉/折叠面板，不堆叠整页长表单。
- 视觉统一：一个标题、三个大卡片、响应式、地图工具折叠、操作主次、空态/错误/加载态；修正 `/inspection?alert_id` 无路由目标问题。
- 回归 Cockpit 地图、Scheduler、角色权限、告警跳转、地图切换场景。

## 6. 必须补充的自动测试与人工验收

### 6.1 前端测试（Vitest + Testing Library）

- 入口 `/route` 恰好 3 个一级业务卡片；不出现两个任务编排入口/重复 SectionHeader。
- `create-point` 选点、角度、取消、切换 `insert-route-point`、组件卸载都正常清理 `NAV2D` 回调，不污染 `/` Cockpit。
- 只途经点创建成功且 action plan 为空、动作点新增并 PUT 计划；创建成功但动作失败显示部分成功并可重试。
- 列表查找、点位编辑、`If-Match` revision 更新、409/412 冲突、被任务引用删除失败有清晰提示。
- 从现有业务点 A、B 编排，**在 A/B 中间插入仅途经点 C**，保存回读顺序仍 A→C→B；移动顺序、移除中间点、重复点引用场景正确。
- 刷新/跨浏览器重新加载任务仍存在；仅 localStorage 草稿绝不能显示为正式已保存任务。
- 服务端拒绝缺失/跨地图/停用点，禁用保存与运行；保存成功但执行失败必须分别反馈。
- Viewer、Operator、Engineer 功能级鉴权；Provider 离线可以编辑并保存模板，但不能执行需能力的任务；simulation fixture 标识正确。
- 历史中的纯途经、混合业务任务均能检索（如果契约支持）；筛选/展开详情；窗口不足时显示限制，不编造证据或结果。
- RobotId/mapId/mapVersionId 切换后选中项、草稿、路线预览、缓存不会串到另一台机器人或地图。

### 6.2 后端契约测试（若修改平台编译器）

- 旧 `{name, waypoint_ids, compile_only}` 请求行为、错误码、调度功能不变。
- 新有序混合点编译后的合法 `waypoint`/`wait`/`inspection_action` 顺序；无动作点不产生 `inspection_action`；等待类动作映射 `wait`。
- 重复点的唯一步骤 ID；引用当前地图版本/资产校验；禁用点、缺失点、恶意参数、并发更新被拒绝；幂等键重试不重复创建/执行。
- mission 修改、删除、执行安全门禁、运行中限制、已有任务快照的可预期语义。
- 仅途经任务历史可检索；最近 10 条与持久化历史能力边界有契约测试。

### 6.3 用户级验收脚本（人工用真实服务或可信 mock）

1. 打开「巡检任务规划」，界面清楚呈现三个主功能区，地图可见；没有两套“巡检模板/编排草稿”互相竞争。
2. 在地图创建「拍照点 A」（配置拍照）、「消防点 B」（配置消防识别），能够保存、列表可管理。
3. 新建任务，先添加 A、B，再点击 A 后面的「插入巡检点」，地图选择走廊转角 C，设置为「仅途经」。路线显示 A→C→B、C 没有业务动作。
4. 保存任务；刷新页面或重新登录后，任务管理列表仍存在；打开任务查看步骤顺序、编辑并再次保存都有效。
5. Provider 暂离线时仍可保存任务定义，但“执行”给出准确阻断；恢复后尝试执行，查看运行状态与结果（仅基于实际返回）。
6. 历史卡片显示本次任务实例及各步骤事件，失败原因与结果/证据匹配；过去历史不全则明示窗口限制。
7. 切换地图或地图版本，禁止误将旧地图任务/点位下发，并向操作者说明原因；确认 Cockpit 和 Scheduler 未回归。
8. 在 1440px、1024px、768px、390px 宽度检查：无水平溢出、选点步骤可发现、按钮可触达，错误/空态与文本不挤压。

## 7. 优先级、质量门槛与 PR 交付格式

- **P0 必做**：三个一级卡片；共享单地图；统一“巡检点（仅途经/含业务动作）”；统一点位 CRUD/动作编辑；任务混合路线可真保存/回读/编辑/管理；日志历史整合；角色与地图版本安全；相关自动测试。
- **P1 可选增强**：更高质量的拖拽排序（优先保证键盘上下移动可用）、路线点连线/箭头优化、引用影响提示、历史完整归档查询、旧草稿批量导入。
- **不能接受的交付**：只有静态 mock/UI；只改 CSS；隐去旧编排器却没有任务管理；继续把 `localStorage` 当成任务持久化；未经验证添加 `point_type:"transit"`；将不可执行能力写成已支持；地图多份 ROS viewer / 残留全局 callback；直接绕过鉴权/安全门禁。

**PR 描述须包含**：
1. “改前问题→对应解决方案”的简短表；
2. 实际改动文件和后台接口变化（若有），明确旧协议兼容；
3. 三种屏幕尺寸前后截图（至少桌面、平板、手机）及 1 个 A→C→B 示例；
4. `npm test`、`npm run build` 结果与必要后端测试结果；
5. 真实未完成项、风险、人工验收注意事项。

## 8. 阅读顺序 / 源码参考

基线固定链接可由 `https://github.com/YansenSong/Alpha/blob/29f1a6f6795af30786c3c645be7075cb4931a15f/<path>` 拼接；建议先按顺序读：

1. [`RoutePage.jsx`](https://github.com/YansenSong/Alpha/blob/29f1a6f6795af30786c3c645be7075cb4931a15f/third_party/RobotPilot/web/src/pages/RoutePage.jsx)
2. [`InspectionTaskComposer.jsx`](https://github.com/YansenSong/Alpha/blob/29f1a6f6795af30786c3c645be7075cb4931a15f/third_party/RobotPilot/web/src/components/InspectionTaskComposer.jsx)
3. [`WaypointActionsPage.jsx`](https://github.com/YansenSong/Alpha/blob/29f1a6f6795af30786c3c645be7075cb4931a15f/third_party/RobotPilot/web/src/pages/WaypointActionsPage.jsx)
4. [`InspectionPointCreate.jsx`](https://github.com/YansenSong/Alpha/blob/29f1a6f6795af30786c3c645be7075cb4931a15f/third_party/RobotPilot/web/src/components/InspectionPointCreate.jsx)
5. [`InspectionPage.jsx`](https://github.com/YansenSong/Alpha/blob/29f1a6f6795af30786c3c645be7075cb4931a15f/third_party/RobotPilot/web/src/pages/InspectionPage.jsx)
6. [`Map.jsx`](https://github.com/YansenSong/Alpha/blob/29f1a6f6795af30786c3c645be7075cb4931a15f/third_party/RobotPilot/web/src/components/Map.jsx)、[`useSavedWaypoints.js`](https://github.com/YansenSong/Alpha/blob/29f1a6f6795af30786c3c645be7075cb4931a15f/third_party/RobotPilot/web/src/shared/hooks/useSavedWaypoints.js)、[`taskApi.js`](https://github.com/YansenSong/Alpha/blob/29f1a6f6795af30786c3c645be7075cb4931a15f/third_party/RobotPilot/web/src/shared/missions/taskApi.js)
7. [`platform_api.py`](https://github.com/YansenSong/Alpha/blob/29f1a6f6795af30786c3c645be7075cb4931a15f/third_party/RobotPilot/ros2/src/robotpilot_ui_package/robotpilot_ui_package/platform_api.py)、[`mission_manager/node.py`](https://github.com/YansenSong/Alpha/blob/29f1a6f6795af30786c3c645be7075cb4931a15f/src/extension/mission_manager/mission_manager/node.py)

**最终目标**：使用者只需要理解“创建巡检点、把点排成巡检任务、查看任务执行结果”。任何需要解释“本地混合草稿”和“仅巡检点模板”为何不同的操作，都应该在本次重构中被消除。
