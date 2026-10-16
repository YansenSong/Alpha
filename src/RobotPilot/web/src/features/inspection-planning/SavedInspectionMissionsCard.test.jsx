import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

const service = vi.hoisted(() => ({
  listInspectionMissions: vi.fn(),
  startInspectionMission: vi.fn(),
}));

vi.mock("../../app/App", async () => {
  const ReactModule = await import("react");
  return { AuthContext: ReactModule.createContext({ robotId: "robot-1" }) };
});
vi.mock("../../shared/auth/roleAccess", () => ({
  useRoleAccess: () => ({ allowed: true, reason: "" }),
}));
vi.mock("../../shared/inspection/planningApi", () => service);

import SavedInspectionMissionsCard from "./SavedInspectionMissionsCard";

const mission = {
  id: "inspection-mission-1",
  name: "夜间消防巡检",
  map_id: "map-1",
  map_version_id: "v1",
  steps: [
    {
      type: "waypoint",
      waypoint_id: "point-1",
      pose: { x: 1, y: 2, z: 0, w: 1 },
    },
    { type: "inspection_action", action: "camera.capture" },
  ],
};

beforeEach(() => {
  service.listInspectionMissions.mockResolvedValue([mission]);
  service.startInspectionMission.mockResolvedValue({ task_id: "task-1" });
  window.confirm = vi.fn(() => true);
});

test("loads current-map inspection missions, previews, and starts the selected task", async () => {
  const onPreview = vi.fn();
  render(
    <SavedInspectionMissionsCard
      mapId="map-1"
      mapVersionId="v1"
      stale={false}
      active={false}
      onPreview={onPreview}
    />,
  );

  await screen.findByRole("option", { name: mission.name });
  fireEvent.change(screen.getByLabelText("选择已保存巡检任务"), {
    target: { value: mission.id },
  });
  fireEvent.click(screen.getByText("地图预览"));
  expect(onPreview).toHaveBeenCalledWith(mission);

  fireEvent.click(screen.getByText("执行任务"));
  await waitFor(() =>
    expect(service.startInspectionMission).toHaveBeenCalledWith(
      "robot-1",
      mission.id,
    ),
  );
  expect(screen.getByText("执行指令已接收：task-1")).toBeTruthy();
});

test("does not list a task bound to another map version", async () => {
  render(
    <SavedInspectionMissionsCard
      mapId="map-1"
      mapVersionId="v2"
      stale={false}
      active={false}
      onPreview={vi.fn()}
    />,
  );

  await screen.findByRole("link", { name: "巡检任务规划" });
  expect(screen.queryByRole("option", { name: mission.name })).toBeNull();
});
