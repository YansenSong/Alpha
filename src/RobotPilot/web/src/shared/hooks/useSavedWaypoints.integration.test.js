import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockRos = {};
const responseListeners = new Set();
const topicNames = [];
let activeMapId = "grid-a";
let activeMapVersionId = "grid-a";

vi.mock("../api/apiFetch", () => ({ apiFetch: vi.fn() }));

import { AuthContext, RosContext, RosStatusContext } from "../../app/App";
import { apiFetch } from "../api/apiFetch";
import useSavedWaypoints from "./useSavedWaypoints";

class FakeTopic {
  constructor({ name }) {
    this.name = name;
    topicNames.push(name);
  }

  subscribe(callback) {
    if (this.name === "/ackermann/routes/catalog")
      responseListeners.add(callback);
  }

  unsubscribe(callback) {
    responseListeners.delete(callback);
  }

  publish() {
    if (this.name === "/ackermann/routes/request") {
      queueMicrotask(() => {
        for (const callback of responseListeners) {
          callback({
            data: JSON.stringify({
              active_files: {
                map_id: activeMapId,
                map_version_id: activeMapVersionId,
              },
            }),
          });
        }
      });
    }
  }
}

const wrapper = ({ children }) =>
  createElement(
    AuthContext.Provider,
    { value: { robotId: "robot-001" } },
    createElement(
      RosStatusContext.Provider,
      { value: "connected" },
      createElement(RosContext.Provider, { value: mockRos }, children),
    ),
  );

describe("useSavedWaypoints robot API integration", () => {
  let persisted;

  beforeEach(() => {
    responseListeners.clear();
    topicNames.length = 0;
    activeMapId = "grid-a";
    activeMapVersionId = "grid-a";
    persisted = [];
    window.ROSLIB = { Topic: FakeTopic };
    window.NAV2D = { setSavedWaypoints: vi.fn() };
    apiFetch.mockImplementation(async (path, options = {}) => {
      if (options.method === "POST") {
        const body = JSON.parse(options.body);
        const item = { ...body, waypoint_id: "wp-1", revision: 1 };
        persisted = [item];
        return { json: async () => item };
      }
      if (options.method === "DELETE") {
        persisted = [];
        return { ok: true };
      }
      return { json: async () => ({ waypoints: persisted }) };
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("loads by active map hash, writes normalized yaw, and deletes with revision", async () => {
    const { result } = renderHook(() => useSavedWaypoints(), { wrapper });
    expect(topicNames).toEqual([
      "/ackermann/routes/catalog",
      "/ackermann/routes/request",
    ]);

    await waitFor(() => expect(result.current.mapId).toBe("grid-a"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(apiFetch).toHaveBeenCalledWith(
      "/api/v1/robots/robot-001/waypoints?map_id=grid-a",
    );

    await act(async () => {
      await result.current.addWaypoint(
        "Dock",
        {
          position: { x: 1.25, y: -0.8 },
          orientation: { z: Math.sin(Math.PI / 4), w: Math.cos(Math.PI / 4) },
        },
        "charge",
      );
    });
    const createCall = apiFetch.mock.calls.find(
      ([, options = {}]) => options.method === "POST",
    );
    const body = JSON.parse(createCall[1].body);
    expect(body).toMatchObject({
      map_id: "grid-a",
      map_version_id: "grid-a",
      point_type: "charge",
      name: "Dock",
    });
    expect(body.yaw).toBeCloseTo(Math.PI / 2);
    expect(result.current.waypoints[0].revision).toBe(1);

    await act(async () => result.current.removeWaypoint("wp-1"));
    const deleteCall = apiFetch.mock.calls.find(
      ([, options = {}]) => options.method === "DELETE",
    );
    expect(deleteCall[1].headers["If-Match"]).toBe('"1"');
    expect(result.current.waypoints).toEqual([]);
  });

  it("filters older map versions and keeps the last snapshot visibly stale offline", async () => {
    activeMapVersionId = "grid-a-v2";
    persisted = [
      {
        waypoint_id: "old",
        map_id: "grid-a",
        map_version_id: "grid-a-v1",
        name: "Old map point",
        x: 1,
        y: 1,
        yaw: 0,
      },
      {
        waypoint_id: "current",
        map_id: "grid-a",
        map_version_id: "grid-a-v2",
        name: "Current map point",
        x: 2,
        y: 2,
        yaw: 0,
      },
    ];
    const { result } = renderHook(() => useSavedWaypoints(), { wrapper });

    await waitFor(() => expect(result.current.mapVersionId).toBe("grid-a-v2"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.waypoints.map(({ id }) => id)).toEqual(["current"]);
    expect(result.current.stale).toBe(false);

    apiFetch.mockRejectedValueOnce(new Error("offline"));
    await act(async () => result.current.refresh());
    expect(result.current.waypoints.map(({ id }) => id)).toEqual(["current"]);
    expect(result.current.stale).toBe(true);
    expect(result.current.observedAt).toBeTruthy();
  });
});
