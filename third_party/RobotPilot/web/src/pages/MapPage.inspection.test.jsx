import React from "react";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

const state = vi.hoisted(() => ({
  robot: {
    stale: false,
    error: "",
    snapshot: {
      robot_connection: { online: true, source: "ros" },
      current_map: { map_id: "map-a", map_version_id: "v1" },
      task: { status: "RUNNING", task_id: "task-1" },
      battery: { available: true, percent: 72, source: "simulated" },
      autonomy_ready: true,
    },
  },
  apiFetch: vi.fn(),
}));

vi.mock("../app/App", async () => {
  const ReactModule = await import("react");
  return {
    AuthContext: ReactModule.createContext({ robotId: "robot-001", robotMode: "simulation" }),
    useRos: () => null,
    useRosStatus: () => "connected",
    useRuntimeConfig: () => ({ config: {} }),
  };
});
vi.mock("../shared/auth/roleAccess", () => ({ useRoleAccess: () => ({ allowed: true }) }));
vi.mock("../shared/robot/robotContract", () => ({ INSPECTION_PROFILE: true }));
vi.mock("../shared/i18n/i18n", () => ({
  useT: () => ({ t: (value) => value }), T: ({ children }) => children,
}));
vi.mock("../shared/hooks/useMissionRun", () => ({ default: () => null }));
vi.mock("../shared/hooks/useRobotStatus", () => ({ default: () => state.robot }));
vi.mock("../shared/hooks/useSoftwareStop", () => ({ default: () => ({
  stateFresh: true, robotState: { active: false }, requestState: { status: "idle" },
}) }));
vi.mock("../shared/hooks/useSavedWaypoints", () => ({ default: () => ({
  waypoints: [], addWaypoint: vi.fn(), removeWaypoint: vi.fn(), updateWaypoint: vi.fn(),
  legacyWaypoints: [], importLegacyWaypoints: vi.fn(),
}) }));
vi.mock("../shared/hooks/useKeepoutZones", () => ({ default: () => ({}) }));
vi.mock("../shared/api/apiFetch", () => ({ apiFetch: state.apiFetch }));
vi.mock("../shared/inspection/planningApi", () => ({
  listInspectionMissions: vi.fn(async () => []),
  startInspectionMission: vi.fn(),
}));
vi.mock("../components/Map", () => ({ default: () => <div data-testid="map-canvas" /> }));
vi.mock("../components/Camera", () => ({ default: () => null }));
vi.mock("../components/Joystick", () => ({ default: () => null }));
vi.mock("../components/RobotState", () => ({ default: () => null }));
vi.mock("../components/NavStatus", () => ({ default: () => null }));
vi.mock("../components/MapLayers", () => ({ default: () => null }));
vi.mock("../components/SystemAlerts", () => ({ default: () => null }));
vi.mock("../components/WaypointLibrary", () => ({ default: () => null }));
vi.mock("../shared/ui/Dashboard", () => ({
  MetricCard: () => null,
  DashboardCard: ({ children, ...props }) => <section {...props}>{children}</section>,
}));

import MapPage from "./MapPage";

beforeEach(() => {
  state.robot = {
    stale: false, error: "", snapshot: {
      robot_connection: { online: true, source: "ros" },
      current_map: { map_id: "map-a", map_version_id: "v1" },
      task: { status: "RUNNING", task_id: "task-1" },
      battery: { available: true, percent: 72, source: "simulated" },
      autonomy_ready: true,
    },
  };
  state.apiFetch.mockReset();
  window.NAV2D = { setInspectionAlerts: vi.fn(), setQueuedWaypoints: vi.fn() };
});

afterEach(() => {
  cleanup();
  delete window.NAV2D;
});

test("inspection overview shows live status and loads current-map alerts", async () => {
  const alert = { alert_id: "alert-1", category: "fire_smoke", state: "OPEN",
    map_id: "map-a", map_version_id: "v1",
    position: { frame_id: "map", x: 1, y: 2 } };
  state.apiFetch.mockResolvedValue({ json: async () => ({ alerts: [alert] }) });
  render(<MapPage />);
  const overview = screen.getByLabelText("运行总览");
  expect(within(overview).getByText("在线")).toBeTruthy();
  expect(within(overview).getByText("72%")).toBeTruthy();
  await waitFor(() => {
    expect(state.apiFetch).toHaveBeenCalledWith(expect.stringContaining(
      "map_id=map-a&map_version_id=v1"));
    expect(window.NAV2D.setInspectionAlerts).toHaveBeenCalledWith([alert]);
    expect(within(overview).getByText("fire_smoke")).toBeTruthy();
  });
});

test("stale map status clears pins and marks overview as stale", async () => {
  state.apiFetch.mockResolvedValue({ json: async () => ({ alerts: [] }) });
  const view = render(<MapPage />);
  await waitFor(() => expect(state.apiFetch).toHaveBeenCalledTimes(1));
  state.robot = { ...state.robot, stale: true };
  view.rerender(<MapPage />);
  const overview = screen.getByLabelText("运行总览");
  expect(within(overview).getByText("状态数据已过期")).toBeTruthy();
  expect(within(overview).getByText("地图状态过期")).toBeTruthy();
  expect(window.NAV2D.setInspectionAlerts).toHaveBeenLastCalledWith([]);
});
