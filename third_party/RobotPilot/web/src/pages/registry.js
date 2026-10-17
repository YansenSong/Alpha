import { lazy } from "react";
import { INSPECTION_PROFILE } from "../shared/robot/robotContract";

const AgentPage = lazy(() => import("./AgentPage"));
const MapPage = lazy(() => import("./MapPage"));
const RoutePage = lazy(() => import("./RoutePage"));
const InfoPage = lazy(() => import("./InfoPage"));
const HealthPage = lazy(() => import("./HealthPage"));
const EventsPage = lazy(() => import("./EventsPage"));
const LogsPage = lazy(() => import("./LogsPage"));
const MapsPage = lazy(() => import("./MapsPage"));
const BmsPage = lazy(() => import("./BmsPage"));
const AssetsPage = lazy(() => import("./AssetsPage"));

/**
 * 所有顶层页面的唯一数据源。Header.jsx 的侧边栏/移动端导航和 pages/index.jsx 的路由都读取此数组，
 * 无需各自维护硬编码列表。添加新页面时，只需在此处追加一项。
 *
 * `path` 始终是导航使用的绝对路径（即 NavLink 的 `to` 值）；pages/index.jsx 会据此生成相对的 <Route path>。
 * `icon` 必须与 Header.jsx 的 NavIcon 中某个分支对应（未注册的名称会回退到通用圆点，避免新条目显示为空白）。
 */
export const PAGE_REGISTRY = [
  { path: "/", label: "Cockpit", icon: "map", component: MapPage },
  {
    path: "/route",
    label: "巡检任务规划",
    icon: "route",
    component: RoutePage,
  },
  { path: "/agent", label: "RoboAgent", icon: "agent", component: AgentPage },
  { path: "/maps", label: "Maps", icon: "maps", component: MapsPage },
  { path: "/info", label: "Status", icon: "status", component: InfoPage },
  { path: "/health", label: "Health", icon: "health", component: HealthPage },
  { path: "/events", label: "Events", icon: "events", component: EventsPage },
  { path: "/assets", label: "Assets", icon: "devices", component: AssetsPage },
  { path: "/logs", label: "Logs", icon: "logs", component: LogsPage },
  {
    path: "/bms",
    label: "Battery management",
    icon: "battery",
    component: BmsPage,
  },
  {
    path: "/scheduler",
    label: "Scheduler",
    icon: "scheduler",
    component: lazy(() => import("./SchedulerPage")),
  },
  ...(!INSPECTION_PROFILE
    ? [
        {
          path: "/devices",
          label: "Devices",
          icon: "devices",
          component: lazy(() => import("./DevicesPage")),
        },
        {
          path: "/console",
          label: "Console",
          icon: "console",
          component: lazy(() => import("./ConsolePage")),
        },
      ]
    : []),
];

export const NAV_REGISTRY = INSPECTION_PROFILE
  ? [...PAGE_REGISTRY]
  : PAGE_REGISTRY;

/** 将页面插件追加到注册表。必须在应用渲染前调用。 */
export function registerPage(entry) {
  PAGE_REGISTRY.push(entry);
}
