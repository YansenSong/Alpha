import { beforeEach, expect, test, vi } from "vitest";
import { apiFetch } from "../api/apiFetch";
import {
  compileInspectionMission,
  missionStops,
  saveInspectionPoint,
} from "./planningApi";

vi.mock("../api/apiFetch", () => ({ apiFetch: vi.fn() }));
const json = (value) => ({ json: async () => value });

beforeEach(() => {
  vi.clearAllMocks();
});

test("reconstructs ordered and repeated point references from a saved mission", () => {
  const stops = missionStops({
    steps: [
      { id: "a", type: "waypoint", waypoint_id: "photo" },
      { id: "b", type: "inspection_action", waypoint_id: "photo" },
      { id: "c", type: "waypoint", waypoint_id: "corner" },
      { id: "d", type: "waypoint", waypoint_id: "photo" },
    ],
  });
  expect(
    stops.map(({ waypoint_id, execute_actions }) => [
      waypoint_id,
      execute_actions,
    ]),
  ).toEqual([
    ["photo", true],
    ["corner", false],
    ["photo", false],
  ]);
});

test("saves A-C-B to the compiler and confirms the ordered server readback", async () => {
  const stops = [
    { waypoint_id: "A", execute_actions: true },
    { waypoint_id: "C", execute_actions: false },
    { waypoint_id: "B", execute_actions: true },
  ];
  apiFetch.mockImplementation(async (path, options) => {
    if (path.endsWith("/inspection/tasks")) {
      expect(JSON.parse(options.body).points).toEqual(stops);
      return json({ status: "compiled", mission_id: "inspection-123" });
    }
    return json({
      missions: [
        {
          id: "inspection-123",
          name: "巡检",
          steps: [
            { type: "waypoint", waypoint_id: "A" },
            { type: "inspection_action" },
            { type: "waypoint", waypoint_id: "C" },
            { type: "waypoint", waypoint_id: "B" },
            { type: "inspection_action" },
          ],
        },
      ],
    });
  });
  const mission = await compileInspectionMission("robot-1", {
    name: "巡检",
    stops,
  });
  expect(mission.id).toBe("inspection-123");
  expect(apiFetch).toHaveBeenCalledTimes(2);
});

test("a point remains identifiable when its action plan save fails", async () => {
  const saved = { waypoint_id: "point-1", name: "消防柜", revision: 1 };
  apiFetch
    .mockResolvedValueOnce(json(saved))
    .mockRejectedValueOnce(new Error("action conflict"));
  await expect(
    saveInspectionPoint(
      "robot-1",
      { map_id: "map-a", name: "消防柜", x: 1, y: 2, yaw: 0 },
      [{ kind: "capture", timeout_ms: 1000 }],
    ),
  ).rejects.toMatchObject({ pointSaved: saved });
  expect(apiFetch).toHaveBeenCalledTimes(2);
});
