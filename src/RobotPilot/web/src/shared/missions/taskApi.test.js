import { afterEach, describe, expect, it, vi } from "vitest";
import { sendStoredMissionCommand, startOneOffMission } from "./taskApi";

const response = (payload, status = 200) =>
  new Response(JSON.stringify(payload), { status });

describe("startOneOffMission", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("saves a map-bound mission before starting it through the task API", async () => {
    const calls = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url, options = {}) => {
        if (String(url).endsWith("/auth/csrf"))
          return response({ csrf_token: "csrf" });
        calls.push({ url: String(url), options });
        if (String(url).endsWith("/missions"))
          return response({ command_id: "save-1", status: "accepted" }, 202);
        return response(
          { command_id: "start-1", task_id: "task-1", status: "accepted" },
          202,
        );
      }),
    );

    const result = await startOneOffMission({
      robotId: "robot-001",
      mapId: "grid-a",
      mapVersionId: "grid-a",
      name: "Manual route",
      steps: [{ type: "waypoint", pose: { x: 1, y: 2, z: 0, w: 1 } }],
    });

    expect(result.task_id).toBe("task-1");
    expect(calls).toHaveLength(2);
    expect(calls[0].url).toContain("/missions");
    expect(calls[1].url).toContain("/tasks");
    const savedMission = JSON.parse(calls[0].options.body);
    expect(savedMission.map_version_id).toBe("grid-a");
    expect(savedMission.steps).toHaveLength(1);
    expect(
      calls.every(({ options }) =>
        new Headers(options.headers).get("Idempotency-Key"),
      ),
    ).toBe(true);
  });
});

describe("sendStoredMissionCommand", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("routes saved mission controls through the platform task API", async () => {
    const calls = [];
    vi.stubGlobal("fetch", vi.fn(async (url, options = {}) => {
      if (String(url).endsWith("/auth/csrf")) return response({ csrf_token: "csrf" });
      calls.push({ url: String(url), options });
      return response({ command_id: `cmd-${calls.length}`, status: "accepted" }, 202);
    }));

    await sendStoredMissionCommand("robot-001", { command: "save", mission: { id: "m" } });
    await sendStoredMissionCommand("robot-001", { command: "start", mission_id: "m" });
    await sendStoredMissionCommand("robot-001", { command: "pause", task_id: "t" });
    await sendStoredMissionCommand("robot-001", { command: "delete", mission_id: "m" });

    expect(calls.map(({ url }) => url)).toEqual([
      "/api/v1/robots/robot-001/missions",
      "/api/v1/robots/robot-001/tasks",
      "/api/v1/robots/robot-001/tasks/t/commands",
      "/api/v1/robots/robot-001/missions/m",
    ]);
    expect(JSON.parse(calls[2].options.body)).toEqual({ action: "pause" });
    expect(calls[3].options.method).toBe("DELETE");
    expect(calls.every(({ options }) => new Headers(options.headers).get("Idempotency-Key"))).toBe(true);
  });
});
