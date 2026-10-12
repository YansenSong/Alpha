import React from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

vi.mock("../app/App", async () => {
  const ReactModule = await import("react");
  return { AuthContext: ReactModule.createContext({ robotId: "robot-1" }) };
});
vi.mock("../shared/hooks/useRobotStatus", () => ({
  default: () => ({
    stale: false,
    snapshot: {
      current_map: { map_id: "map-a", map_version_id: "v1", stale: false },
    },
  }),
}));
vi.mock("../shared/auth/roleAccess", () => ({
  useRoleAccess: () => ({ allowed: true }),
}));
vi.mock("../shared/i18n/i18n", () => ({ useT: () => ({ t: (text) => text }) }));
vi.mock("../components/Map", () => ({
  default: () => <div data-testid="shared-map" />,
}));
vi.mock("../components/MapLayers", () => ({ default: () => <div>图层</div> }));
vi.mock("../shared/inspection/planningApi", () => ({
  listInspectionMissions: vi.fn(async () => []),
  listInspectionPoints: vi.fn(async () => []),
  missionStops: vi.fn(() => []),
  compileInspectionMission: vi.fn(),
  deleteInspectionMission: vi.fn(),
  startInspectionMission: vi.fn(),
  saveInspectionPoint: vi.fn(),
  deleteInspectionPoint: vi.fn(),
}));
vi.mock("../shared/api/apiFetch", () => ({
  apiFetch: vi.fn(async () => ({
    json: async () => ({ tasks: [], results: [], alerts: [] }),
  })),
}));

import RoutePage from "./RoutePage";

beforeEach(() => {
  window.NAV2D = { setSavedWaypoints: vi.fn(), setQueuedWaypoints: vi.fn() };
});
afterEach(() => {
  cleanup();
  delete window.NAV2D;
});

test("route page has three business cards and one shared map", async () => {
  render(<RoutePage />);
  await waitFor(() => expect(screen.getByTestId("planning-card")).toBeTruthy());
  expect(screen.getByTestId("points-card")).toBeTruthy();
  expect(screen.getByTestId("history-card")).toBeTruthy();
  expect(screen.getAllByTestId("shared-map")).toHaveLength(1);
  expect(
    screen
      .getByText("图层")
      .compareDocumentPosition(screen.getByTestId("points-card")) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    screen
      .getByTestId("shared-map")
      .compareDocumentPosition(screen.getByTestId("planning-card")) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    screen
      .getByTestId("points-card")
      .compareDocumentPosition(screen.getByTestId("planning-card")) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(screen.queryByText("保存编排草稿")).toBeNull();
});

test("map selection callback is cleared on cancellation and unmount", async () => {
  const view = render(<RoutePage />);
  fireEvent.click(screen.getByText("在地图上选择位置"));
  await waitFor(() =>
    expect(typeof window.NAV2D._poseCallback).toBe("function"),
  );
  expect(window.NAV2D.arePointsSettable).toBe(true);
  fireEvent.click(screen.getByText("取消选点"));
  await waitFor(() => expect(window.NAV2D._poseCallback).toBeNull());
  fireEvent.click(screen.getByText("在地图上选择位置"));
  view.unmount();
  expect(window.NAV2D._poseCallback).toBeNull();
  expect(window.NAV2D.arePointsSettable).toBe(false);
});
