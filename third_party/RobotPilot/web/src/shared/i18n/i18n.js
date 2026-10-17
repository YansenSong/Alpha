import { useEffect, useState } from "react";

// 英文原文作为翻译键。页面展示文案应通过 t() 查询中文译文。

// New key makes Chinese the default even for browsers that stored the old
// English default; choices made after this change remain persistent.
const STORAGE_KEY = "robotpilotLangV2";

const ZH = {
  Map: "地图",
  Cockpit: "驾驶舱",
  "Robot connection": "机器人连接",
  "Last snapshot": "最近快照",
  "Autonomy readiness": "自主任务就绪状态",
  "Quality unknown": "定位质量未知",
  Live: "实时",
  "Current task": "当前任务",
  "No active task": "无活动任务",
  "Battery management": "电池管理",
  "Battery telemetry with explicit source, freshness, and simulation controls.":
    "查看电池数据来源、更新时间和仿真场景。",
  "Simulation mode · simulated battery data": "仿真模式 · 仿真电池数据",
  "State of charge": "当前电量",
  "Stale / unavailable": "数据已过期 / 不可用",
  Source: "数据来源",
  Voltage: "电压",
  Current: "电流",
  "Platform threshold": "平台阈值",
  "Threshold runtime sync": "阈值运行状态",
  "Waiting for battery node": "等待电池节点同步",
  "Data freshness": "数据时效",
  "Up to date": "数据正常",
  "Not available": "暂无数据",
  Discharging: "放电中",
  Simulation: "仿真",
  Yes: "是",
  No: "否",
  "Waiting for battery status data.": "等待电池状态数据。",
  "Battery telemetry is disabled": "电池遥测已禁用",
  "Battery reading unavailable": "电池数据不可用",
  "Simulated battery communication is unavailable": "仿真电池通信不可用",
  "Battery serial port unavailable": "电池串口不可用",
  "Simulated charging failed": "仿真充电故障",
  "Battery status abnormal": "电池状态异常",
  "Simulation scenarios": "仿真场景",
  "Normal discharge": "正常放电",
  "Simulated charging": "仿真充电",
  "Full charge": "充满电",
  "Communication lost": "通信中断",
  "Charging fault": "充电故障",
  "Reset scenario": "重置场景",
  "Scenario controls are available only when the robot and battery source both report simulation. No physical charging or docking is performed.":
    "仅当机器人和电池数据源都处于仿真模式时，才能使用这些场景控制。此处不会执行真实充电或停靠操作。",
  "Scenario was not accepted.": "场景请求未被接受。",
  "Scenario request failed.": "场景请求失败。",
  "Engineer permission is required to change simulation scenarios.":
    "更改仿真场景需要工程师权限。",
  "Sending…": "正在发送…",
  Charging: "充电中",
  "Not charging": "未充电",
  Navigation: "导航状态",
  Alarms: "告警",
  "Active faults": "活跃故障",
  "Active alerts": "活跃告警",
  Routes: "路线",
  "Route planning": "路线规划",
  "Task planning": "任务规划",
  Status: "状态",
  Devices: "设备",
  Health: "健康",
  Metrics: "指标",
  Recordings: "录制",
  Events: "事件",
  Logs: "日志中心",
  Operations: "运维",
  Module: "模块",
  "Task ID": "任务 ID",
  "Fault code": "故障代码",
  "First seen after": "首次出现时间起",
  "First seen before": "首次出现时间止",
  "Fault time filter uses first_seen in UTC.":
    "故障时间筛选使用首次出现时间（UTC）。",
  "Export JSON": "导出 JSON",
  "Fault export failed": "导出故障记录失败",
  "Modified after": "修改时间起",
  "Modified before": "修改时间止",
  "Robot runtime logs are collected into one file per node and local day.":
    "机器人运行日志按节点和本地日期归档，每个节点每天一个文件。",
  "Time filter uses file modified_at in UTC.":
    "时间筛选使用文件修改时间（UTC）。",
  files: "个文件",
  "Scan limit reached; narrow filters to see more.":
    "已达到扫描上限，请缩小筛选范围。",
  "Loading logs…": "正在读取日志…",
  "No matching logs": "没有符合条件的日志",
  "No logs yet": "暂无日志",
  Log: "日志",
  File: "文件",
  Modified: "修改时间",
  Size: "大小",
  Action: "操作",
  Download: "下载",
  Previous: "上一页",
  Next: "下一页",
  "Page offset": "分页偏移",
  "Log downloads require Operator permission.": "下载日志需要操作员权限。",
  "Rosbag recordings": "Rosbag 录制",
  "Log download failed": "日志下载失败",
  "Browser-only joystick command limits. They are not a robot-side speed safety limit and are not shared with other operators.":
    "仅限制本浏览器发送的摇杆速度，不是机器人侧安全限速，也不会与其他操作员共享。",
  "Browser notification threshold": "浏览器通知阈值",
  "This browser shows a notification at or below this percentage; it does not change robot battery policy.":
    "仅此浏览器在电量低于该百分比时通知，不会更改机器人电池策略。",
  "Platform business configuration": "平台业务配置",
  "This value is stored on the robot platform with a version and operator. It is not currently published as a runtime battery-node parameter.":
    "此值持久保存在机器人平台并记录版本与操作者；当前不会下发为电池节点运行参数。",
  "Platform low-battery threshold": "平台低电量阈值",
  "1–99%, stored as a platform business policy": "1–99%，作为平台业务策略保存",
  "Active version": "当前版本",
  Operator: "操作者",
  "Saved at": "保存时间",
  "Save platform policy": "保存平台策略",
  "Recent platform configuration versions": "近期平台配置版本",
  "Activate version": "启用此版本",
  "Activate this platform configuration version?": "启用此平台配置版本？",
  "Platform configuration version activated": "已启用平台配置版本",
  "Platform configuration activation failed": "启用平台配置版本失败",
  "Platform configuration unavailable": "平台配置不可用",
  "Platform low-battery threshold must be 1–99%":
    "平台低电量阈值必须在 1–99% 之间",
  "Platform configuration saved": "平台配置已保存",
  "Platform configuration save failed": "平台配置保存失败",
  "Robot readiness": "机器人就绪状态",
  Ready: "已就绪",
  "Not ready": "未就绪",
  Unknown: "未知",
  "Current map": "当前地图",
  Localization: "定位状态",
  Online: "在线",
  Inactive: "未激活",
  "Autonomy blocked": "自主任务被阻止",
  Unavailable: "不可用",
  Fault: "故障",
  Active: "活跃",
  Resolved: "已恢复",
  Cleared: "已清除",
  All: "全部",
  Module: "模块",
  Total: "总数",
  Previous: "上一页",
  "Previous page": "上一页",
  "Next page": "下一页",
  Acknowledged: "已确认",
  "Export CSV": "导出 CSV",
  "Filter by module": "按模块筛选",
  "Could not load faults": "无法加载故障记录",
  "Loading faults": "正在加载故障记录",
  "Fault operation failed": "故障操作失败",
  "No faults": "没有故障记录",
  "No robot faults match the selected filters.":
    "没有符合当前筛选条件的机器人故障。",
  "Persistent robot fault history, shared across browsers. Live diagnostic snapshots remain on the Health page.":
    "机器人故障历史由后端持久保存并在浏览器间共享；Health 页面展示实时诊断快照。",
  "Clear this resolved fault from the active list?":
    "要从当前故障列表清除这条已恢复记录吗？",
  Console: "控制台",
  Parameters: "参数",
  Maps: "地图管理",
  Scheduler: "计划",
  Missions: "任务",
  Inspection: "巡检任务",
  Config: "配置",
  Connected: "已连接",
  Offline: "离线",
  Error: "错误",
  "Still active": "仍存在",
  Recovered: "已恢复",
  Batt: "电池",
  "E-STOP": "急停",
  Language: "语言",
  "Robot connected": "机器人已连接",
  "Robot offline": "机器人离线",
  "Connection error": "连接错误",
  "Software Stop (not physical E-STOP)": "软件停车（非物理急停）",
  "Software stop confirmed": "软件停车已确认",
  "Software stop active but persistence is unavailable":
    "软件停车已生效，但持久化状态不可用",
  "Software stop active; state is stale": "软件停车仍生效，但状态已过期",
  "Software stop remains active": "软件停车仍处于生效状态",
  "Software stop request pending": "软件停车请求中",
  "Software stop state unknown": "软件停车状态未知",
  "Resume navigation": "恢复导航",
  "Release software stop": "解除软件停车",
  "No active task and robot is stationary": "当前无活动任务，车辆已静止",
  "Software stop already active": "软件停车已生效",
  "Cancel task": "取消任务",
  "Waiting for cancellation": "等待取消确认",
  "Cancel the current task without releasing software stop": "取消当前任务，保持软件停车",
  "Resume navigation and continue the current task": "恢复导航并继续当前任务",
  "Cannot send navigation goal while software stop state is unknown or active":
    "软件停车状态未知或已生效，无法发送导航目标",
  "Software stop requested; navigation task is retained":
    "软件停车已请求，当前导航任务会保留",
  Manual: "手动控制",
  "Max Speed": "最高速度",
  "Software Stop": "软件停车",
  "Manual control interface not configured": "手动控制接口未配置",
  "Manual control is available in simulation mode only.": "手动控制目前仅在仿真模式下开放。",
  "Manual control is unavailable.": "手动控制当前不可用。",
  "Software stop state is unknown or active.": "软件停车状态未知或已激活，无法手动控制。",
  "Software stop request is pending.": "软件停车请求处理中，暂不能手动控制。",
  "Stop the active task before manual control.": "请先停止正在运行的任务，再使用手动控制。",
  "Project navigation and localization interfaces are unconfigured. Status: UNKNOWN.":
    "项目导航与定位接口尚未配置。状态：未知。",
  Autonomy: "自主任务",
  "New mission": "新建任务",
  Create: "创建",
  steps: "个步骤",
  "No steps added": "尚未添加步骤",
  "Run (moves robot)": "运行（机器人将移动）",
  "Mission definitions and execution records live on the robot. Running tasks continue when this browser closes.":
    "任务定义和执行记录保存在机器人端。关闭浏览器后，运行中的任务仍会继续。",
  "Import browser mission drafts": "导入浏览器中的旧任务草稿",
  "Recent task executions": "最近的任务执行记录",
  "remaining steps": "个剩余步骤",
  "Forced one-off": "强制单次",
  "Regular scheduled": "常规周期",
  "Operator specified": "人工指定",
  "Type unavailable": "类型不可用",
  forced_one_off: "强制单次",
  regular_scheduled: "常规周期",
  operator_specified: "人工指定",
  unavailable: "类型不可用",
  "This mission includes dock/undock steps, but no robot-side docking executor is connected. Execution and retry are disabled.":
    "任务包含停靠/离开步骤，但机器人侧未连接对接执行器，已禁用任务启动和重试。",
  "Dock and undock execution is unavailable: no robot-side controller is connected.":
    "停靠/离开功能不可用：机器人侧未连接对接控制器。",
  "execution unavailable": "执行器未接入",
  "Current step": "当前步骤",
  "Mission drive hold is active after the task ended.":
    "任务结束后仍保持车辆速度锁定。",
  "Release mission drive hold? Confirm the vehicle is safe to move.":
    "确认车辆可以安全移动后，解除任务速度锁定？",
  "Release drive hold": "解除速度锁定",
  Retry: "重试",
  running: "运行中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
  "Create one below, then add executable waypoint, wait, or home steps.":
    "在下方新建任务并添加可执行的巡检点、等待或返回原点步骤。",
  "Go to waypoint": "前往巡检点",
  "Go home": "返回原点",
  Wait: "等待",
  Dock: "停靠",
  Undock: "离开充电座",
  "No saved waypoints yet — add one from the Map page first.":
    "暂无巡检点，请先在地图页面添加。",
  "e.g. Evening patrol": "例如：夜间巡检",
  "No missions yet": "暂无任务",
  "No steps yet — add one below.": "暂无步骤，请在下方添加。",
  "Choose a waypoint…": "选择巡检点…",
  "+ Add step": "+ 添加步骤",
  "Saved Waypoints": "已保存的巡检点",
  "Save here": "保存当前位置",
  "e.g. Dock, Loading bay": "例如：充电座、装卸区",
  "Waiting for pose…": "等待位置数据…",
  "No saved waypoints yet — drive somewhere and save it, or right-click the map.":
    "暂无巡检点。可在地图上右键保存位置。",
  Settings: "设置",
  Configuration: "配置",
  Audit: "审计",
  "System overview": "系统概览",
  "Health Centre": "系统健康",
  Unknown: "未知",
  Storage: "磁盘空间",
  platform_data: "平台数据",
  recordings: "录制文件",
  backups: "备份文件",
  critical: "严重",
  warning: "警告",
  ok: "正常",
  "Loading storage health…": "正在读取磁盘状态…",
  "Storage health unavailable": "磁盘状态不可用",
  "Storage usage is above the warning threshold.": "磁盘使用量已超过警告阈值。",
  "Storage usage is above the critical threshold.":
    "磁盘使用量已超过严重阈值。",
  "No storage paths configured.": "没有配置存储路径。",
  "available of": "可用，共",
  "Robot status": "机器人状态",
  Environments: "环境",
  "Route authoring": "路线编辑",
  "Plan reusable robot routes": "规划可复用的机器人路线",
  "Browser speed limits and notifications are saved locally. Platform battery policy is stored on the robot.":
    "浏览器速度限制和通知设置保存在本地；电池策略保存在机器人端。",
  "A persisted timeline of navigation, docking, battery and safety events — reviewable after the fact. Kept locally in the browser.":
    "导航、停靠、电池与安全相关事件的时间线，保存在本地浏览器中。",
  "Combines connection status, sensor data, navigation health, hardware, battery, and robot model into one ready/not-ready check.":
    "汇总连接、传感器、导航、硬件、电池和机器人模型状态。",
  "Live camera, telemetry, power, and ROS health in one operational view.":
    "集中查看实时画面、遥测、电源和 ROS 状态。",
  "Save, switch, rename and organise the robot's maps. Switching a map reloads it on the robot immediately.":
    "保存、切换、重命名和整理地图。切换地图会立即在机器人端重新加载。",
  "Place, edit, and manage waypoint sequences for the active map.":
    "为当前地图添加、编辑和管理航点序列。",
  "Create and manage reusable routes for the map currently loaded in the Ackermann simulation.":
    "为当前 Ackermann 仿真加载的地图创建和管理可复用路线。",
  "Waiting for the active simulation map.": "正在等待仿真地图加载。",
  "Saved Routes": "已保存路线",
  "Select a saved route…": "选择已保存的路线…",
  "Loading route…": "正在加载路线…",
  "Execute Route": "执行路线",
  "Create and save a route on the Routes page first.":
    "请先在“路线”页面创建并保存路线。",
  "Select a saved route first.": "请先选择一条已保存的路线。",
  "Route service is not connected.": "路线服务未连接。",
  "The selected route has no waypoints.": "所选路线没有航点。",
  "Executing route": "正在执行路线",
  "Timed out while loading the selected route.": "加载所选路线超时。",
  "Queue stopped": "队列已停止。",
  "Choose a route saved on the Routes page under Saved Routes, then Execute Route to follow its waypoints in order.":
    "在“已保存路线”中选择“路线”页面保存的路线，然后点击“执行路线”按顺序前往各航点。",
  "Select and execute saved routes from the Map page.":
    "在“地图”页面选择并执行已保存的路线。",
  "No events recorded yet": "暂无事件",
  "No events match the filters": "没有符合筛选条件的事件",
  "No devices registered": "尚未注册设备",
  "Register hardware on the Devices page to see it here.":
    "请在设备页面注册硬件。",
  "No battery telemetry": "暂无电池数据",
  "Waiting for the configured battery topic to publish.":
    "等待已配置的电池 topic 发布数据。",
  "No maps yet": "暂无地图",
  "Build and save a map above to see it here.": "请先在上方创建并保存地图。",
  Connection: "连接",
  "Manual-drive safety limits": "手动驾驶速度限制",
  Notifications: "通知",
  "Keep-out zones": "禁行区域",
  "Save settings": "保存设置",
  "Reset to defaults": "恢复默认设置",
  "Max linear speed": "最大线速度",
  "Max angular speed": "最大角速度",
  "Low battery threshold": "低电量阈值",
  "This is the network address the app uses to talk to the robot. Leave blank to auto-use this page’s own host (the normal case once deployed on the robot).":
    "用于连接机器人的网络地址。留空时自动使用当前网页的主机地址。",
  "Port used to stream the camera feed.": "相机视频流使用的端口。",
  "Notify once battery drops to or below this level, %":
    "电量降至此百分比或以下时通知。",
  Export: "导出",
  "Clear all events": "清空所有事件",
  Type: "类型",
  Severity: "严重程度",
  all: "全部",
  navigation: "导航",
  docking: "停靠",
  battery: "电池",
  safety: "安全",
  system: "系统",
  info: "信息",
  success: "成功",
  warning: "警告",
  error: "错误",
  "This permanently deletes all recorded events, even if you're currently viewing a filtered list. This can't be undone. Continue?":
    "这将永久删除全部事件记录，包括当前筛选未显示的记录，且无法撤销。继续吗？",
  "Navigation, docking and battery events will appear here as they happen.":
    "导航、停靠和电池事件发生后会显示在这里。",
  "Try widening the type or severity filter.": "请放宽类型或严重程度筛选条件。",
  Refresh: "刷新",
  "Build a new map": "创建新地图",
  "Launches mapping mode and stops navigation. Drive the robot around the space, then save below.":
    "启动建图模式并停止导航。完成建图后在下方保存。",
  "Start mapping": "开始建图",
  "Save current map": "保存当前地图",
  Group: "分组",
  "Map name": "地图名称",
  Save: "保存",
  "Saved maps": "已保存的地图",
  "New group": "新建分组",
  "Add group": "添加分组",
  "delete group": "删除分组",
  "No maps in this group.": "此分组暂无地图。",
  active: "当前使用",
  configured: "启动配置",
  "route(s)": "条路线",
  Cancel: "取消",
  Loaded: "已加载",
  Configured: "启动配置",
  Switch: "切换",
  Rename: "重命名",
  live: "实时",
  offline: "离线",
  "Project localization interface is unconfigured. Status: UNKNOWN.":
    "项目定位接口尚未配置。状态：未知。",
  "Battery level": "电池电量",
  "Recent trend": "近期趋势",
  "(last ~10 min)": "（近约 10 分钟）",
  "Charging station": "充电座",
  "Robot is connected to external power.": "机器人已连接外部电源。",
  "Robot is not connected to the dock.": "机器人未连接充电座。",
  "Not connected": "未连接",
  Critical: "严重",
  "Every checked signal is nominal.": "所有已检查信号均正常。",
  Online: "在线",
  "No status topic": "无状态 topic",
  "RobotPilot map dashboard": "RobotPilot 地图控制台",
  "Robot workspace": "机器人工作台",
  "Open full Health Centre →": "打开系统健康页面 →",
  "Maximum joystick and map speed settings. Changes apply to new manual commands.":
    "摇杆和地图页面的最高速度设置，修改后应用于新的手动命令。",
  "Browser notifications for navigation, docking, and low battery require browser permission.":
    "导航、停靠和低电量的浏览器通知需要通知权限。",
  Enabled: "已启用",
  Disabled: "已禁用",
  "Permission granted": "权限已授予",
  "Permission blocked — check browser settings": "权限被阻止，请检查浏览器设置",
  "Request permission": "请求权限",
  "These zones are visual markers only. They do not stop the robot. Confirm obstacle avoidance with the integrator.":
    "这些区域只是视觉标记，不能自行阻止机器人运动。请向集成方确认避障能力。",
  "Rectangular no-go areas are drawn on the map. Toggle them with the Zones layer.":
    "矩形禁行区域绘制在地图上，可通过“区域规则”图层切换显示。",
  "Browser notifications enabled": "浏览器通知已启用",
  "Notification permission was not granted": "未获得浏览器通知权限",
  "Settings saved": "设置已保存",
  "Settings reset to defaults": "设置已恢复默认值",
  "Reset browser speed limits and low-battery notification settings to defaults?":
    "要将浏览器速度限制和低电量通知设置恢复为默认值吗？",
  Alerts: "警报",
  Notice: "提示",
  "Map not received": "尚未收到地图",
  "Localization pose missing": "缺少定位位置数据",
  "No planned path yet": "暂无规划路径",
  "Robot connection lost": "机器人连接已断开",
  Layers: "图层",
  Laser: "激光",
  Path: "路径",
  Goal: "目标",
  Waypoints: "航点",
  Zones: "区域规则",
  "Area rules": "区域规则",
  Trail: "轨迹",
  Reset: "重置",
  Camera: "相机",
  Color: "彩色",
  "RGB Sim": "RGB 仿真",
  Low: "低",
  Balanced: "均衡",
  High: "高",
  Start: "启动",
  Stop: "停止",
  Full: "全屏",
  "Camera is paused": "相机已暂停",
  "Start the video feed to see what the robot sees.":
    "启动视频流以查看机器人视野。",
  "Start camera": "启动相机",
  "Camera unavailable": "相机不可用",
  "Current route": "当前路线",
  "Route operations": "路线操作",
  "Route selection": "路线选择",
  "Edit and save": "编辑与保存",
  "Path planning": "路径规划",
  "Manage saved route": "管理已保存路线",
  "Choose a saved route to edit": "选择要编辑的已保存路线",
  "Route waypoints": "路线航点",
  "Apply edits": "应用修改",
  "X (m)": "X 坐标（米）",
  "Y (m)": "Y 坐标（米）",
  "Stop hours": "停留小时",
  "Stop minutes": "停留分钟",
  "Remove waypoint": "删除航点",
  "Editing route": "正在编辑路线",
  "View mode": "查看模式",
  "Click the map to add or adjust waypoints, then save your changes.":
    "点击地图添加或调整航点，然后保存更改。",
  "Choose an operation to begin editing the current route or create a new one.":
    "选择操作以编辑当前路线或创建新路线。",
  "Cancel edit": "取消编辑",
  "Edit route": "编辑路线",
  "Switch route": "切换路线",
  "Switch map": "切换地图",
  "Auto-plan": "自动规划",
  "Clear waypoints": "清空航点",
  Delete: "删除",
  Hardware: "硬件",
  "Detected serial ports": "检测到的串口",
  "Register a device": "登记设备",
  "Register device": "登记设备",
  "Registered devices": "已登记设备",
  Name: "名称",
  "Connection type": "连接类型",
  "Connection target": "连接目标",
  "Status topic (optional)": "状态 topic（可选）",
  "Status message type (optional)": "状态消息类型（可选）",
  "Notes (optional)": "备注（可选）",
  "No devices registered yet": "尚未登记设备",
  "Add one above to start tracking it here.":
    "请在上方登记设备，以便在此查看。",
  "Checking…": "检查中…",
  "Serial port detection isn't available on this robot's computer.":
    "此机器人计算机不支持串口检测。",
  "No USB-serial devices currently detected on this host.":
    "此计算机目前未检测到 USB 串口设备。",
  "Use this port as the new device's connection target":
    "将此端口用作新设备的连接目标",
  "e.g. Gripper controller": "例如：夹爪控制器",
  "Driver package, firmware version, anything worth remembering":
    "驱动包、固件版本等备注",
  "Manually registered external hardware — USB, CAN, network, and Raspberry-Pi-attached devices — with live status wherever a ROS topic is available. There's no plug-and-play auto-detection here: register what's connected, and point it at the topic its driver publishes.":
    "手动登记 USB、CAN、网络和树莓派连接的设备。有 ROS 状态 topic 时可查看实时状态；其他设备也可登记留存。",
  "Real serial ports (e.g. USB-serial adapters, Arduino-style boards) currently exposed on this robot's computer. This won't see CAN interfaces, network devices, or hardware attached to a different Raspberry Pi than the one hosting this UI.":
    "列出运行本 UI 的计算机当前可见的串口，包括 USB 转串口设备。此列表不会检测 CAN、网络设备或其他树莓派上的硬件。",
  "Status is optional — leave it blank for a device you're just keeping a record of, or point it at the ROS topic its driver publishes to get a live online/offline badge.":
    "状态信息可选。只需登记时可留空；填写驱动发布的 ROS topic 后可显示在线或离线状态。",
  "Wherever the device shows up — e.g. a USB port path, network address, or vehicle-bus name. (Serial path, CAN interface name, or host:port — whatever identifies it.)":
    "填写设备的串口路径、CAN 接口名或主机地址与端口等连接标识。",
  "The status channel this device's software reports to when it's running (ask your integrator if unsure).":
    "设备软件运行时发布状态的 topic；不确定时可咨询集成方。",
  "Leave blank unless your device's status messages use a non-text format.":
    "除非设备状态消息使用非文本格式，否则留空。",
  "Combines connection status, sensor data, navigation health, hardware, and battery into one ready/not-ready check.":
    "汇总连接、传感器、导航、硬件和电池状态。",
  Battery: "电池",
  Diagnostics: "诊断信息",
  "No battery telemetry.": "暂无电池数据。",
  "Full telemetry →": "查看完整遥测 →",
  "Manage devices →": "管理设备 →",
  "No warning/error-level diagnostics reported.":
    "暂无警告或错误级别的诊断消息。",
  "Expected topics": "预期的 topics",
  "Track record": "运行记录",
  "Derived from live telemetry and kept locally. Counters accumulate across sessions until reset.":
    "根据实时遥测统计并保存在本地；重置前会跨会话累积。",
  "Reset counters": "重置计数",
  "Distance travelled": "行驶距离",
  "Current speed": "当前速度",
  "Session uptime": "本次会话时长",
  "Trips completed": "完成的行程",
  Trips: "行程",
  Completed: "已完成",
  Failed: "失败",
  "Stopped early": "提前停止",
  Docking: "停靠",
  Success: "成功",
  Rate: "比率",
  Tuning: "参数调整",
  "Read all": "全部读取",
  Node: "节点",
  Parameter: "参数",
  Value: "值",
  "Decimal number": "小数",
  "Whole number": "整数",
  "On/Off": "开关",
  Text: "文本",
  Read: "读取",
  Set: "设置",
  "+ Add parameter": "+ 添加参数",
  "Remove row": "移除一行",
  "Nav2 is the robot's navigation software — these settings control things like how fast it drives and how close it gets to obstacles before adjusting course. Read and set Nav2 parameters on running nodes. Runtime-only — values revert when the related software restarts.":
    "读取或设置运行中的 Nav2 节点参数，例如速度与避障距离。修改仅在运行期间有效，节点重启后会恢复。",
  "Debugging & lessons": "调试与学习",
  "Record a session of everything the robot sensed and did, so you can play it back later — useful for debugging, demos, and training data. Replayed telemetry is always clearly labeled; it's never presented as a live robot.":
    "录制机器人感知与运行数据，供后续回放、调试和数据分析。回放数据会明确标记，不会显示为实时数据。",
  Recording: "录制中",
  "Stop recording": "停止录制",
  "Description (optional)": "说明（可选）",
  "Record all topics": "录制所有 topics",
  "Start recording": "开始录制",
  Replaying: "回放中",
  "Saved recordings": "已保存的录制",
  "No recordings yet": "暂无录制",
  "Start one above to see it here.": "请在上方开始录制。",
  Replay: "回放",
  Download: "下载",
  elapsed: "已用时间",
  "e.g. Warehouse loop demo": "例如：仓库路线录制",
  "What this recording is for": "填写录制用途",
  "Trigger navigation at set times. Runs while a browser tab is open — it is not robot-side cron, so keep a tab running for schedules to fire.":
    "按设定时间触发导航。计划在浏览器标签页打开时运行，请保持页面开启。",
  "No schedules": "暂无计划",
  "Schedules are stored and triggered by the robot. The robot checks stop state, task activity and map binding before each run.":
    "计划保存在机器人端并由机器人触发。每次执行前会检查软件停车、任务占用和地图绑定。",
  "Add a mission schedule below.": "在下方添加任务计划。",
  "Loading schedules": "正在加载计划",
  "Could not load schedules": "无法加载计划",
  "Schedule operation failed": "计划操作失败",
  "Select mission": "选择任务",
  "Select a saved task…": "选择已保存的任务…",
  "No routes have been saved in Task planning.": "“任务规划”中暂无已保存路线。",
  "A schedule uses the saved route as it exists when the schedule is created. Recreate the schedule after editing that route.":
    "计划使用创建时保存的路线；修改路线后需重新创建该计划。",
  Weekly: "每周",
  "Robot time zone": "机器人计划时区",
  "Next run": "下次运行",
  None: "无",
  "Legacy browser schedules found": "发现旧版浏览器计划",
  "Legacy schedules never run in this browser. Supported daily mission schedules can be imported; other entries remain in the saved backup for manual review.":
    "旧版计划不会再由浏览器触发。支持导入每日任务计划；其他条目会保存在备份中供手动检查。",
  "Can import": "可导入",
  "Requires manual review": "需要手动检查",
  "Back up and import supported schedules": "备份并导入支持的计划",
  "Imported schedules": "已导入计划",
  "Task accepted": "任务已受理",
  "Task could not be started": "任务无法启动",
  "Task stop requested": "已请求停止任务",
  "Task could not be stopped": "无法停止任务",
  "Current task": "当前任务",
  "Stop Task": "停止任务",
  "Single navigation": "单次导航",
  "Manual route": "手动路线",
  "Navigate to": "前往",
  "Navigate home": "返回原点",
  "Route execution is controlled by MissionManager.":
    "路线由 MissionManager 统一执行和追踪。",
  "Another task is already active.": "已有任务正在运行。",
  "A task is paused. Use Resume navigation to continue it.": "当前任务已暂停，可恢复导航或取消任务。",
  Mon: "周一",
  Tue: "周二",
  Wed: "周三",
  Thu: "周四",
  Fri: "周五",
  Sat: "周六",
  Sun: "周日",
  "Add one below — e.g. send the robot to its dock every evening.":
    "在下方新增计划，例如每天晚上返回充电座。",
  "Add schedule": "新增计划",
  Daily: "每天",
  Once: "一次",
  "Mission:": "任务：",
  Add: "添加",
  "Targets are saved waypoints (add them on the Map page), home, or a whole mission (build one on the Missions page).":
    "目标可以是已保存的航点、原点或完整任务；可在地图或任务页面创建。",
  "Name (e.g. Nightly dock)": "名称（例如：夜间停靠）",
  "Page not found": "页面不存在",
  "This workspace does not contain the requested screen.":
    "此工作区没有请求的页面。",
  "Return to map": "返回地图",
  "Live ROS logs and raw topic inspection":
    "查看实时 ROS 日志和 topic 原始消息",
  "Not connected to the robot — logs and topic echo will start streaming once the connection is live. Check the robot network and UI backend.":
    "尚未连接机器人。连接恢复后日志和 topic 消息将开始显示；请检查机器人网络和界面后端服务。",
  Home: "原点",
  "⌂ Go Home": "⌂ 返回原点",
  "Waypoint Queue (": "航点队列（",
  Clear: "清空",
  "Stop Queue": "停止队列",
  "Execute Queue": "执行队列",
  "Move up": "上移",
  "Move down": "下移",
  "Remove step": "移除步骤",
  seconds: "秒",
  "Open console": "打开控制台",
  "Hide console": "隐藏控制台",
  "Use light theme": "切换浅色主题",
  "Use dark theme": "切换深色主题",
  "Open navigation": "打开导航",
  "Close navigation": "关闭导航",
  "Primary navigation": "主导航",
  "Mobile navigation": "移动端导航",
  Navigation: "导航",
  Skip: "跳过",
  "Close help": "关闭帮助",
  Help: "帮助",
  "Take the tour": "查看引导",
  "Replay mode": "回放模式",
  "— you're viewing recorded telemetry, not a live robot.":
    "— 当前显示的是录制数据，并非机器人实时状态。",
  Messages: "消息",
  "No messages": "暂无消息",
  "Send goal here": "在此发送目标点",
  "Save waypoint here": "在此保存航点",
  "Correct robot's position here": "在此修正机器人位置",
  "Waypoint name": "航点名称",
  Localization: "定位",
  "Set pose": "设置位置",
  "What does this mean?": "这是什么意思？",
  "Have the robot search the whole map for its position again (drive to help it converge)":
    "让机器人重新在全图定位；可通过移动帮助定位收敛。",
  Lifecycle: "生命周期",
  "What do these states mean?": "这些状态是什么意思？",
  "Position tracking": "位置跟踪",
  "Time since the last update / how often it's updating":
    "距离上次更新的时间／更新频率",
  "System Health": "系统健康",
  Robot: "机器人",
  "System Log": "系统日志",
  Follow: "自动跟随",
  "shown ·": "已显示 ·",
  buffered: "条已缓存",
  "Topic Echo": "Topic 回显",
  "Select a currently active topic to inspect its messages.":
    "选择当前正在发布的话题，查看其实时消息。",
  "Topic name": "话题名称",
  "Select a topic": "选择话题",
  "Loading available topics…": "正在加载话题列表…",
  "ROS bridge is disconnected": "ROS Bridge 未连接",
  "Topic list unavailable": "无法获取话题列表",
  "No active topics found": "当前没有可用话题",
  "Refresh topics": "刷新话题列表",
  Echo: "查看",
  "Select a topic and press Echo to stream its messages.":
    "选择话题并点击查看，即可接收其实时消息。",
  "Subscribed to": "已订阅",
  "— waiting for a message…": "— 等待消息…",
  msgs: "条消息",
  Topics: "Topics",
  "Coming soon!": "即将推出！",
  "Recent Dock Events": "近期停靠事件",
  Dismiss: "关闭",
  "⚓ Dock": "⚓ 停靠",
  "↩ Undock": "↩ 离开充电座",
  "Linear velocity": "线速度",
  Angular: "角速度",
  "Robot position": "机器人位置",
  "Robot coordinates": "机器人坐标",
  "Robot heading": "机器人朝向",
  "Distance to target": "距目标点距离",
  "X / Y coordinates": "X / Y 坐标",
  Heading: "朝向",
  "Radians per second — how fast the robot is turning in place":
    "弧度每秒，表示机器人原地旋转速度",
  "This robot's controls are reachable from outside your local network with no authentication (AUTH_MODE=open) — anyone who can reach this address can operate the robot. Restrict network access, or set AUTH_MODE once a supported mode is available.":
    "此机器人的控制界面可从本地网络外访问，且未启用身份验证（AUTH_MODE=open）。能访问此地址的人都可操作机器人，请限制网络访问。",
  "Dismiss warning": "关闭警告",
  "Gamepad connected — left stick drives": "手柄已连接，可用左摇杆驾驶",
  "Add zone": "添加区域",
  "Name and connection target are both required": "名称和连接目标均为必填项",
  Registered: "已登记",
  Remove: "移除",
  'Remove "{name}" from the device list?': "要从设备列表移除“{name}”吗？",
  "CAN bus": "CAN 总线",
  Network: "网络",
  "Raspberry Pi (attached)": "树莓派（已连接）",
  Other: "其他",
  "hostname or IP address": "主机名或 IP 地址",
  "connection target": "连接目标",
  "Enter a name for this recording": "请填写录制名称",
  "Select at least one topic, or record all topics":
    "请选择至少一个 topic，或录制所有 topics",
  "Recording started": "录制已开始",
  "Recording stopped": "录制已停止",
  "Recording in progress": "正在录制",
  "Start a recording": "开始录制",
  "Delete this recording? This can't be undone.":
    "要删除此录制吗？此操作无法撤销。",
  Deleted: "已删除",
  "Replay stopped": "回放已停止",
  "topic(s)": "个 topic",
  "All topics": "所有 topics",
  Paused: "已暂停",
  Resume: "继续",
  Pause: "暂停",
  "Stop replay": "停止回放",
  "Stopping… this can take a few seconds.": "正在停止回放，可能需要几秒钟…",
  Complete: "已完成",
  "Didn't finish cleanly": "未正常完成",
  "Laser scan": "激光扫描",
  Odometry: "里程计",
  "LIO-RF pose": "LIO-RF 位姿",
  "The robot pose estimated against the prior map":
    "机器人相对于先验地图估计的位姿",
  "Nav status": "导航状态",
  "Joint states": "关节状态",
  "TF static": "静态 TF",
  "Raw distance readings from the robot's laser sensor":
    "机器人激光传感器的原始距离数据",
  "The robot's estimated position and speed from its wheels/motors":
    "根据车轮或电机估计的机器人位置与速度",
  "The map the robot is navigating on": "机器人当前导航使用的地图",
  "Where the robot thinks it is": "机器人估计的自身位置",
  "Navigation progress and outcome": "导航进度和结果",
  "Battery charge level and status": "电池电量与状态",
  "Position of movable robot parts": "机器人可动部件的位置",
  "How the robot's parts are positioned relative to each other":
    "机器人各部件之间的相对位置",
  "Fixed robot geometry (rarely changes)": "固定的机器人几何结构（很少变化）",
  "Reset all totals below back to zero? This can't be undone.":
    "要将下方所有统计值重置为零吗？此操作无法撤销。",
  Peak: "峰值",
  "No goals yet": "暂无目标任务",
  "Success rate": "成功率",
  daily: "每天",
  once: "一次",
  "Run mission": "运行任务",
  "Run mission (missing)": "运行任务（任务不存在）",
  "Navigate to": "导航至",
  "Navigate to (missing waypoint)": "导航（航点不存在）",
  "All expected topics are present in the ROS graph.":
    "ROS 图中已包含所有预期 topics。",
  "Checked once the robot connection is established.": "建立机器人连接后检查。",
  "Edit in Config": "在配置中修改",
  "Top turning speed (rad/s)": "最高转向速度（rad/s）",
  "Acceleration limit (m/s²)": "加速度限制（m/s²）",
  "Top driving speed (m/s)": "最高行驶速度（m/s）",
  "How close counts as close enough (m)": "到达判定距离（m）",
  "Distance (m)": "距离（m）",
  "Read failed": "读取失败",
  "Set {param} to {value} on the robot right now?":
    "现在将机器人参数 {param} 设为 {value} 吗？",
  Applied: "已应用",
  Rejected: "已拒绝",
  unknown: "未知",
  "Set failed": "设置失败",
  reading: "读取中",
  "not-set": "未设置",
  read: "已读取",
  applying: "应用中",
  applied: "已应用",
  rejected: "已拒绝",
  Step: "第",
  of: "/",
  "Skip tour": "跳过引导",
  Back: "上一步",
  Done: "完成",
  Next: "下一步",
  "Skip to main content": "跳至主要内容",
  "System diagnostics console": "系统诊断控制台",
  "System Diagnostics Console": "系统诊断控制台",
  Close: "关闭",
  "No page-specific help is available here yet.": "此页面暂无专门的帮助说明。",
  "The main operational view: the live occupancy map, the robot's position, and every control to drive or send it somewhere.":
    "主要操作视图：查看实时栅格地图、机器人位置，以及驾驶和发送目标的控件。",
  "Drag with the left mouse button to pan; scroll or pinch to zoom.":
    "按住鼠标左键拖动可平移地图；滚动滚轮或双指捏合可缩放。",
  "Layer toggles above the map control what's drawn — laser scan, planned path, saved waypoints, zones, and the robot's trail.":
    "地图上方的图层开关控制激光扫描、规划路径、已存航点、区域规则和机器人轨迹的显示。",
  "Goal Mode / Set Pose / Add Waypoint / Go Home change what a click on the map does, or send it straight to the origin.":
    "发送目标、设置位姿和添加航点会改变点击地图时的操作；返回原点会直接发送目标。",
  "Right-click the map for a quick menu — send a goal, save a waypoint, or set the initial pose — without switching modes first.":
    "右键点击地图可直接发送目标、保存航点或设置初始位姿，无需先切换模式。",
  "The joystick drives the robot manually at any time; the max-speed slider caps how fast, and STOP halts it and cancels any active goal.":
    "摇杆可手动驾驶；最高速度滑块限制速度，停止按钮会发送停车指令并取消当前目标。",
  "Linear and angular velocity update live next to the joystick.":
    "摇杆旁实时更新线速度和角速度。",
  "Dock/Undock trigger the robot's charging-dock behaviors, when supported.":
    "机器人支持时，停靠与离开充电座按钮会触发相应动作。",
  "Author reusable waypoint sequences for the currently active map, separate from one-off goals sent from the Map page.":
    "为当前地图创建可复用的航点路线，与地图页面的一次性目标分开管理。",
  "Pick a group and map at the top, then Create or Edit a route.":
    "先在顶部选择分组和地图，再创建或编辑路线。",
  "While editing, click the map to add points — Save when you're happy with the sequence.":
    "编辑时点击地图添加航点，确认顺序后保存。",
  "Auto-plan uses the global planner to draw a path from the robot's current position through each waypoint in order.":
    "自动规划会调用全局规划器，依次绘制机器人当前位置到第一个航点、以及各航点之间的路径。",
  "A live operational readout: camera feed, pose/velocity telemetry, battery, and system health — the page to glance at while the robot is doing something.":
    "实时查看相机、位置与速度遥测、电池和系统健康状态。",
  "The camera panel is paused by default to save bandwidth — press Start when you need to actually see through it.":
    "相机默认暂停以节省带宽；需要查看画面时点击启动。",
  "The battery trend sparkline shows the last several readings, not just the instantaneous value.":
    "电池趋势图显示近期读数，不只显示当前值。",
  "A manual registry of external hardware — USB, CAN, network, and Raspberry-Pi-attached devices — with live status wherever a ROS topic is available.":
    "手工登记 USB、CAN、网络和树莓派连接的设备；有 ROS 状态 topic 时可查看实时状态。",
  "There's no plug-and-play auto-detection here (that needs OS-level access this app doesn't have) — register what's connected yourself.":
    "这里不会自动发现所有设备；请手动登记已连接的硬件。",
  "The detected-serial-ports list is real, though: it reads actual USB-serial devices present on the machine running the backend.":
    "检测到的串口列表来自运行后端的计算机上的真实 USB 串口设备。",
  "A device only shows Online if its status topic is actively publishing — a device is never assumed connected just because you registered it.":
    "只有状态 topic 正在发布时才显示设备在线；登记记录本身不代表设备已连接。",
  'One place to answer "is the whole robot ready?" — an overall rollup built from every other page\'s live signals.':
    "汇总各页面的实时信号，帮助判断机器人是否就绪。",
  "Click any listed issue to jump straight to the page where it can actually be fixed.":
    "点击问题可跳转到相关页面查看详情。",
  "Ready with warnings means nothing is broken, but something (low battery, a missing topic, an offline device) is worth a look.":
    "“就绪但有警告”表示仍需检查低电量、缺失 topic 或离线设备等情况。",
  "Record real rosbag sessions and replay them later — useful for debugging, demos, lessons, and dataset collection.":
    "录制真实 rosbag 会话以供之后回放，可用于调试、教学和数据收集。",
  "Replayed telemetry is always clearly labeled (a Replay mode banner appears on every page) — it's never shown as if it were a live robot.":
    "回放期间各页面会显示回放横幅，录制数据不会冒充实时状态。",
  "Stopping a replay can take several seconds — ros2 bag play needs a moment to shut down cleanly, that's expected, not a stuck button.":
    "停止回放可能需要数秒，因为 ros2 bag play 需要时间正常退出。",
  "Recording all topics is the safest default if you're not sure what you'll need later.":
    "若不确定后续需要哪些数据，可以录制所有 topics。",
  "Browser speed limits and notification preferences. Platform battery policy is managed on the robot.":
    "浏览器速度限制和通知设置；电池策略在机器人端管理。",
  "Speed limits apply to manual commands sent from this browser.":
    "速度限制仅应用于此浏览器发送的手动控制命令。",
  "Get around": "浏览页面",
  "Connection status": "连接状态",
  "Map layers": "地图图层",
  "The map itself": "地图区域",
  "Goal, pose, and waypoints": "目标、位姿和航点",
  "Manual drive": "手动驾驶",
  "This is the main navigation — every page in the app is one click away from here.":
    "这里是主导航，可从此处打开各页面。",
  "Shows whether this browser is connected to the robot.":
    "显示此浏览器是否已连接机器人。",
  "Toggle what's drawn on the map — laser scan, planned path, saved waypoints, zones, and the robot's trail — and adjust opacity.":
    "切换激光扫描、规划路径、航点、区域规则和轨迹等图层，并调整透明度。",
  "Drag to pan, scroll or pinch to zoom. Right-click anywhere for a quick menu — send a goal, save a waypoint, or set the initial pose.":
    "拖动平移、滚动或双指缩放地图。右键点击可发送目标、保存航点或设置初始位姿。",
  "Switch what a click on the map does: send a navigation goal, set the robot's initial pose, or drop a saved waypoint — or jump straight home.":
    "选择点击地图后的操作：发送导航目标、设置初始位姿或保存航点；也可直接返回原点。",
  "Drive the robot directly at any time, cap its speed, or hit STOP to halt it and cancel any active goal — live velocity and position show alongside.":
    "可直接驾驶机器人、限制最高速度，或使用停止按钮取消当前目标；旁边显示实时速度和位置。",
  "Something went wrong": "发生错误",
  "The interface hit an unexpected error and couldn't continue. This doesn't affect the robot itself — its ROS stack keeps running independently of this UI.":
    "界面发生意外错误，无法继续显示。机器人端的 ROS 系统仍独立运行，请确认机器人实际状态。",
  "Return to dashboard": "返回控制台",
  "Battery charge": "电池电量",
  "What does this status mean?": "这个状态是什么意思？",
  "TF chain": "TF 变换链",
  "node…": "节点…",
  "search text…": "搜索文本…",
  "Re-localizing…": "正在重新定位…",
  "Re-localize": "重新定位",
  "Waiting for /rosout…": "等待 /rosout 消息…",
  "No messages match the filters": "没有符合筛选条件的消息",
  "Building…": "正在生成…",
  "Export support package": "导出支持资料包",
  "(paused)": "（已暂停）",
  "Support package downloaded": "支持资料包已下载",
  "Couldn't build support package": "无法生成支持资料包",
  Unknown: "未知",
  Accepted: "已接受",
  Navigating: "导航中",
  Canceling: "取消中",
  Succeeded: "已成功",
  Canceled: "已取消",
  remaining: "剩余",
  "No goal has been sent yet, or its status hasn't arrived. Send a goal from the map.":
    "尚未发送目标，或目标状态尚未到达。可在地图上发送目标。",
  "The robot's navigation system accepted the goal and is about to start planning and moving.":
    "导航系统已接受目标，即将开始规划并移动。",
  "The robot is actively following a path toward the goal.":
    "机器人正沿规划路径前往目标。",
  "A cancel request was sent; the robot is stopping the current goal.":
    "已发送取消请求，机器人正在停止当前目标。",
  'The robot reached the goal — within the distance that counts as "close enough."':
    "机器人已到达目标允许的误差范围内。",
  "The goal was stopped before completion — by the Cancel button or a new goal overriding it. Not an error; send a new goal to continue.":
    "目标在完成前被取消，可能由取消按钮或新目标触发。可发送新目标继续。",
  "The robot's navigation system couldn't complete the goal — usually no valid path was found, it tried to recover and couldn't, or the robot wasn't sure enough of its position to navigate safely. Check that the robot's position estimate looks accurate and the goal isn't inside an obstacle, then retry.":
    "导航系统未能完成目标。请检查定位是否可靠、目标是否位于障碍物内，以及是否存在可行路径。",
  Localized: "定位正常",
  Uncertain: "定位不确定",
  Lost: "定位丢失",
  "No data": "无数据",
  Stale: "数据已过期",
  "The robot is confident about its position — its location estimate has converged and is reliable.":
    "机器人定位估计已收敛，位置可信。",
  "Localization is usable but the estimate is loose. Drive slowly past distinctive features, or set the pose manually to tighten it.":
    "定位仍可用，但误差较大。可缓慢经过明显特征，或手动设置位姿。",
  "The robot isn't sure exactly where it is yet. Tell it to figure out its position from scratch, then drive around to help it narrow down — or set its position manually on the map.":
    "机器人尚无法确定自身位置。可重新定位并移动以帮助收敛，或在地图上手动设置位姿。",
  "No position data received yet. The localization system may not be running, or the robot hasn't been told where it currently is.":
    "尚未收到位置数据。定位系统可能未运行，或机器人尚未设置初始位姿。",
  "The robot has stopped sending a position estimate — the last reading is stale. Check that localization is still running, on the Health page.":
    "机器人已停止发送位置估计，最近数据已过期。请在系统健康页面检查定位系统。",
  'Loading "{map}" — set the initial pose after it loads; old localization won\'t match.':
    "正在加载“{map}”。加载后请重新设置初始位姿，旧定位结果不再适用。",
  "Pick a group and a name for the map": "请选择分组并填写地图名称",
  'Saving current map as "{name}"…': "正在将当前地图保存为“{name}”…",
  "Start a new mapping session? This shuts down localization/navigation and launches mapping mode — the robot must be driven around to build the map. Save it here when done.":
    "要开始新的建图会话吗？这会停止定位和导航并启动建图模式。请驾驶机器人探索环境，完成后在此保存地图。",
  "Mapping started — drive the robot around the space, then save the map.":
    "建图已开始。请驾驶机器人探索环境，然后保存地图。",
  'Delete map "{map}" and its routes? This cannot be undone.':
    "要删除地图“{map}”及其路线吗？此操作无法撤销。",
  'Deleted "{name}"': "已删除“{name}”",
  'Deleting "{name}"…': "正在删除“{name}”…",
  'Renamed to "{name}"': "已重命名为“{name}”",
  'Created group "{name}"': "已创建分组“{name}”",
  'Delete group "{name}" and everything in it?':
    "要删除分组“{name}”及其中所有内容吗？",
  'Deleted group "{name}"': "已删除分组“{name}”",
  'Deleting group "{name}"…': "正在删除分组“{name}”…",
  "Robot's position estimate updated": "机器人位置估计已更新",
  Waypoint: "航点",
  "All waypoints complete!": "所有航点已完成！",
  "Queue stopped: goal was canceled or failed": "队列已停止：目标已取消或失败",
  "Navigating to": "正在导航至",
  Saved: "已保存",
  "Initial pose set": "初始位姿已设置",
  added: "已添加",
  "Navigation canceled": "导航已取消",
  "Navigating to home position (0, 0) m": "正在导航至原点 (0, 0) m",
  Executing: "正在执行",
  waypoints: "个航点",
  Position: "位置",
  Motion: "运动",
  Locate: "定位",
  Navigate: "导航",
  "Laser Scan": "激光扫描",
  Obstacles: "障碍物",
  Plan: "路径规划",
  "Path Plan": "规划路径",
  "Global Costmap": "全局代价地图",
  "Position tracking (TF)": "位置跟踪（TF）",
  "Localization (AMCL)": "定位（AMCL）",
  "Navigation (Nav2)": "导航（Nav2）",
  "Map alignment": "地图对齐",
  "Motion tracking": "运动跟踪",
  "Sensor mounting": "传感器安装",
  online: "在线",
  disconnected: "已断开",
  connected: "已连接",
  "Robot connection is offline — nothing else here can be verified.":
    "机器人连接离线，其他状态暂无法核实。",
  "Position tracking is broken — the robot doesn't know where it is. Navigation won't work until this is fixed.":
    "位置跟踪异常，机器人当前位置未知；恢复前无法导航。",
  paused: "已暂停",
  "not set up yet": "尚未配置",
  "not responding": "无响应",
  inactive: "未激活",
  unconfigured: "未配置",
  Ready: "就绪",
  "Ready with warnings": "就绪，但有警告",
  "Needs attention": "需要处理",
  "Not ready": "未就绪",
  "Map loaded — set the robot's initial pose before navigating; its old localization no longer matches the new map.":
    "地图已加载。导航前请重新设置机器人的初始位姿；旧定位结果不再适用。",
  "Robot connection is offline!": "机器人连接已断开！",
  "Please click 'Edit' or 'Create' first to enable path planning!":
    "请先点击“编辑”或“创建”以启用路径规划。",
  "Waiting for the robot's current position — make sure it's localized on the map, then try again.":
    "正在等待机器人当前位置。请确认机器人已在地图上完成定位后重试。",
  "Add or load route waypoints first.": "请先添加或载入路线航点。",
  "Planning route…": "正在规划路线…",
  "Planning segment {current} / {total}…":
    "正在规划第 {current} / {total} 段路径…",
  "Planned {count} route segments with the global planner.":
    "已使用全局规划器完成 {count} 段路径规划。",
  "Global planner request failed for segment {segment}.":
    "第 {segment} 段全局路径规划请求失败。",
  "Global route planning failed.": "全局路线规划失败。",
  "Nav2 planner rejected the path request.": "Nav2 规划器拒绝了路径请求。",
  "Couldn't find a route to that point.": "找不到通往该点的路线。",
  "Failed to retrieve the planned path from Nav2.":
    "无法从 Nav2 获取规划路径。",
  "Couldn't reach the robot's navigation system — is it turned on?":
    "无法连接机器人导航系统，请确认其已启动。",
  "Enter new route name": "输入新路线名称",
  "Enter route new name": "输入路线的新名称",
  "Select route you want to browse": "选择要查看的路线",
  "Select map you want to load": "选择要加载的地图",
  "Name...": "名称…",
  "Scheduled: running mission": "定时任务：正在运行任务",
  "Scheduled: navigating to": "定时任务：正在导航至",
  "A mission is already running — stop it first.":
    "已有任务正在运行，请先停止该任务。",
  "That mission has no steps to run.": "该任务没有可运行的步骤。",
  'Mission "{name}" failed at step {step}: {label}':
    "任务“{name}”在第 {step} 步失败：{label}",
  'Mission "{name}" complete': "任务“{name}”已完成",
  "Enter a name for this waypoint": "请输入航点名称",
  "No localized position yet — waiting for localization":
    "尚未获得定位位置，正在等待定位数据。",
  Tracking: "正在跟踪",
  "Navigation status": "导航状态",
  "Waiting for goal": "等待目标",
  Planning: "正在规划",
  Moving: "正在移动",
  Arrived: "已到达",
  "No status data": "无状态数据",
  "node started; waiting for goal": "节点已启动，正在等待目标",
  "new goal received; waiting for global plan":
    "已收到新目标，正在等待全局路径",
  "global plan available; navigation active": "全局路径已生成，导航进行中",
  "goal reached and vehicle stopped": "已到达目标且车辆已停止",
  "failed: global planning timed out": "失败：全局路径规划超时",
  "failed: odometry input timed out": "失败：里程计输入超时",
  "failed: NeuPAN arrival input timed out": "失败：NeuPAN 到达信号超时",
  "failed: planner action server unavailable": "失败：规划动作服务器不可用",
  "failed: planner rejected goal": "失败：规划器拒绝了目标",
  "failed: planner returned no path": "失败：规划器未返回路径",
  "LIO-RF is publishing a current map-relative pose. This localization source does not provide confidence covariance, so confidence is unknown.":
    "LIO-RF 正在发布当前的地图相对位姿。该定位源未提供置信度协方差，因此定位置信度未知。",
  "This will start moving the robot through this mission's steps. Continue?":
    "运行任务将使机器人按步骤移动。是否继续？",
  "Enter route name": "请输入路线名称",
  "This name is reserved": "此名称已被保留",
  "Symbol '_' is forbidden": "名称不能包含下划线“_”",
  "Route with passed name is already exist": "同名路线已存在",
  "Enter hours and minutes": "请输入小时和分钟",
  "Hours can't be less then 0 and more then 23": "小时必须在 0 到 23 之间",
  "Minutes can't be less then 0 and more then 59": "分钟必须在 0 到 59 之间",
  "Waypoint wait time": "航点等待时间",
  "How long should the robot pause here before continuing? Leave both at 0 for no pause.":
    "机器人在此处等待多久后继续？小时和分钟均为 0 表示不等待。",
  Hours: "小时",
  Minutes: "分钟",
  "hours...": "小时…",
  "minutes...": "分钟…",
  "No routes available": "暂无路线",
  "No files available": "暂无文件",
  "Group with current name is already exist": "同名分组已存在",
  Idle: "空闲",
  "Final approach": "最后靠近",
  "Aligning to dock": "正在对准充电座",
  Docked: "已停靠",
  "Sequence complete": "流程已完成",
  "Undocking…": "正在离开充电座…",
  "Backing out": "正在倒车退出",
  "To standby…": "正在前往待命位置…",
  "Navigating clear": "正在驶离充电座",
  "Check tag and logs": "请检查标记和日志",
  "Searching tag": "正在查找标记",
  "Dock requested": "已请求停靠",
  "Reverse maneuver requested": "已请求倒车退出",
  "○ Send Goal": "○ 发送目标",
  "● Click to Send Goal": "● 点击发送目标",
  "● Goal": "● 目标",
  "⊕ Correct Robot's Position": "⊕ 修正机器人位置",
  "Fix Position": "修正位置",
  "● Click to Correct Position": "● 点击修正位置",
  "● Fixing": "● 正在修正",
  "＋ Add Waypoint": "＋ 添加航点",
  "● Adding Waypoints": "● 正在添加航点",
  "● Adding": "● 添加中",
  "Click map to navigate. Drag before releasing to set heading.":
    "点击地图发送导航目标。松开前拖动可设置朝向。",
  "Click the map to tell the robot where it currently is. Drag to set heading. One-shot.":
    "点击地图设置机器人当前位置。拖动可设置朝向；此操作仅生效一次。",
  "Each click adds a waypoint. Drag to set heading. Execute all below.":
    "每次点击添加一个航点。拖动可设置朝向，随后在下方执行队列。",
  "Select a mode above to interact with the map.": "请在上方选择地图操作模式。",
  "Waypoint Queue": "航点队列",
  "Exit fullscreen": "退出全屏",
  Fullscreen: "全屏",
  Auto: "自动",
  "Configured and running normally.": "已配置，运行正常。",
  "Configured but idle — call Activate to bring it online.":
    "已配置但未激活；点击启动以投入运行。",
  "Not configured yet — call Configure, or it's a fresh restart. Normal right after Nav2 launches, before activation.":
    "尚未配置。Nav2 刚启动、激活前出现此状态属正常；可点击准备。",
  "We couldn't check this system's status — it may be off, or the robot's connection may be down.":
    "无法检查系统状态；系统可能未运行，或机器人连接已断开。",
  "Map data": "地图数据",
  "Driving control": "驾驶控制",
  "Path planning": "路径规划",
  "Navigation logic": "导航逻辑",
  Prepare: "准备",
  Prep: "准备",
  "Load configuration for every navigation system so it's ready to start.":
    "加载各导航节点的配置，为启动做好准备。",
  "Start every navigation system running.": "启动所有导航节点。",
  "Pause every navigation system. The robot will not respond to drive commands until it's started again.":
    "暂停所有导航节点；再次启动前机器人不会响应驾驶指令。",
  "Reset every navigation system back to unconfigured. The robot will not respond to drive commands until it's prepared and started again.":
    "将所有导航节点重置为未配置状态；重新准备并启动前机器人不会响应驾驶指令。",
  "Pause navigation on every system? The robot will not respond to drive commands until it's started again.":
    "要暂停所有导航节点吗？再次启动前机器人不会响应驾驶指令。",
  "Reset navigation on every system back to unconfigured? The robot will not respond to drive commands until it's prepared and started again.":
    "要将所有导航节点重置为未配置状态吗？重新准备并启动前机器人不会响应驾驶指令。",
};

let lang = load();
const listeners = new Set();
if (typeof document !== "undefined") document.documentElement.lang = lang;

function load() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "en" || stored === "zh-CN" ? stored : "zh-CN";
  } catch {
    return "zh-CN";
  }
}

export function getLang() {
  return lang;
}

export function setLang(next) {
  if (next !== "en" && next !== "zh-CN") return;
  lang = next;
  if (typeof document !== "undefined") document.documentElement.lang = next;
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // ignore
  }
  listeners.forEach((fn) => fn(lang));
}

export function translate(key) {
  if (lang !== "zh-CN" || typeof key !== "string") return key;
  if (Object.hasOwn(ZH, key)) return ZH[key];

  // 健康页的这些消息包含实时设备名或数值，保留原始标识并翻译固定部分。
  let match = key.match(/^(.+) has gone silent\.$/);
  if (match) return `${translate(match[1])} 已停止发送数据。`;
  match = key.match(/^(.+) isn't sending data right now\.$/);
  if (match) return `${translate(match[1])} 当前没有发送数据。`;
  match = key.match(/^Battery critically low \(([^)]+)\)\.$/);
  if (match) return `电池电量严重不足（${match[1]}）。`;
  match = key.match(/^Battery low \(([^)]+)\)\.$/);
  if (match) return `电池电量偏低（${match[1]}）。`;
  match = key.match(
    /^(.+) is (paused|not set up yet|not responding|inactive|unconfigured)\.$/,
  );
  if (match) return `${translate(match[1])}${translate(match[2])}。`;
  match = key.match(/^(.+) is offline\.$/);
  if (match) return `${match[1]} 已离线。`;
  return key;
}

// React binding: re-renders subscribers when the language changes.
export function useT() {
  const [current, setCurrent] = useState(lang);
  useEffect(() => {
    const fn = (l) => setCurrent(l);
    listeners.add(fn);
    return () => listeners.delete(fn);
  }, []);
  return { t: translate, lang: current, setLang };
}

/** 可在没有现成 useT() 调用的组件中翻译静态文字。 */
export function T({ children }) {
  const { t } = useT();
  return t(children);
}
