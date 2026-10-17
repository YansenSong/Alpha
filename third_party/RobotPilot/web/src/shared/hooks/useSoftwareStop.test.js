import { act, cleanup, renderHook } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  canStartMission,
  softwareStopNeeded,
  isSoftwareStopStateFresh,
  parseSoftwareStopState,
  softwareStopCapabilities,
} from "./useSoftwareStop";
import { AuthContext, RosContext, RosStatusContext } from "../../app/App";
import useSoftwareStop from "./useSoftwareStop";
import { setRun } from "../missions/missionClient";

class FakeTopic {
  static instances = [];

  constructor({ name }) {
    this.name = name;
    FakeTopic.instances.push(this);
  }

  subscribe(callback) {
    this.callback = callback;
  }

  publish() {}

  unsubscribe() {}

  unadvertise() {}
}

const wrapper = ({ children }) =>
  createElement(
    AuthContext.Provider,
    { value: { mode: "open", identity: null } },
    createElement(
      RosStatusContext.Provider,
      { value: "connected" },
      createElement(RosContext.Provider, { value: {} }, children),
    ),
  );

describe("software stop state contract", () => {
  it("disables stop only for a confirmed idle robot without an active task", () => {
    const idle = { receivedAt: 2000, stationary: true, stationarySince: 1000 };
    for (const status of ["cancelled", "succeeded", "failed", undefined]) {
      expect(softwareStopNeeded({ status }, idle, 2100)).toBe(false);
    }
    for (const status of ["running", "paused"]) {
      expect(softwareStopNeeded({ status }, idle, 2100)).toBe(true);
    }
    expect(softwareStopNeeded(null, { ...idle, stationary: false }, 2100)).toBe(true);
    expect(softwareStopNeeded(null, idle, 3501)).toBe(true);
    expect(softwareStopNeeded(null, null, 2100)).toBe(true);
  });

  it("guards the actual click after cancellation, and keeps manual-motion stop available", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(1000);
    window.ROSLIB = { Topic: FakeTopic, Message: class { constructor(value) { Object.assign(this, value); } } };
    FakeTopic.instances = [];
    setRun({ taskId: "cancelled-task", status: "cancelled" });
    const { result, unmount } = renderHook(() => useSoftwareStop(), { wrapper });
    const odom = FakeTopic.instances.find(topic => topic.name === "/odometry/filtered");
    const stopped = { twist: { twist: {
      linear: { x: 0, y: 0, z: 0 }, angular: { x: 0, y: 0, z: 0 },
    } } };
    act(() => odom.callback(stopped));
    await act(async () => vi.advanceTimersByTimeAsync(600));
    act(() => odom.callback(stopped));
    expect(result.current.canRequestStop).toBe(false);
    expect(result.current.stopUnavailableReason).toBe("No active task and robot is stationary");
    expect(result.current.requestStop()).toBeNull();
    act(() => odom.callback({ twist: { twist: {
      ...stopped.twist.twist, angular: { x: 0, y: 0, z: .2 },
    } } }));
    expect(result.current.canRequestStop).toBe(true);
    act(() => odom.callback(stopped));
    await act(async () => vi.advanceTimersByTimeAsync(600));
    act(() => odom.callback(stopped));
    expect(result.current.canRequestStop).toBe(false);
    await act(async () => vi.advanceTimersByTimeAsync(1501));
    expect(result.current.canRequestStop).toBe(true);
    unmount();
  });

  it("expires robot state at the freshness deadline", () => {
    const state = { receivedAt: 1000 };
    expect(isSoftwareStopStateFresh(state, 4000)).toBe(true);
    expect(isSoftwareStopStateFresh(state, 4001)).toBe(false);
    expect(isSoftwareStopStateFresh(null, 1000)).toBe(false);
  });

  it("allows mission motion only with a fresh inactive state and no pending request", () => {
    expect(
      canStartMission({
        stateFresh: true,
        robotState: { active: false },
        requestState: null,
      }),
    ).toBe(true);
    expect(
      canStartMission({
        stateFresh: false,
        robotState: { active: false },
        requestState: null,
      }),
    ).toBe(false);
    expect(
      canStartMission({
        stateFresh: true,
        robotState: { active: true },
        requestState: null,
      }),
    ).toBe(false);
    expect(
      canStartMission({
        stateFresh: true,
        robotState: { active: false },
        requestState: { status: "pending" },
      }),
    ).toBe(false);
  });

  it("uses Operator permission for stop and navigation recovery", () => {
    expect(softwareStopCapabilities("local", { role: "Viewer" })).toEqual({
      requestStop: false,
      releaseStop: false,
    });
    expect(softwareStopCapabilities("local", { role: "Operator" })).toEqual({
      requestStop: true,
      releaseStop: true,
    });
    expect(softwareStopCapabilities("local", { role: "Engineer" })).toEqual({
      requestStop: true,
      releaseStop: true,
    });
    expect(softwareStopCapabilities("open", null)).toEqual({
      requestStop: true,
      releaseStop: true,
    });
  });

  it("accepts a robot-confirmed active state with provenance and hardware boundary", () => {
    const state = parseSoftwareStopState({
      active: true,
      source: "web:operator",
      reason: "Operator request",
      request_id: "request-123",
      observed_at: "2026-10-08T12:00:00Z",
      result: "confirmed",
      durable: true,
      physical_estop: { available: false, active: null },
    });

    expect(state).toMatchObject({
      active: true,
      source: "web:operator",
      request_id: "request-123",
      result: "confirmed",
      durable: true,
      physical_estop: { available: false, active: null },
    });
    expect(state.receivedAt).toEqual(expect.any(Number));
  });

  it("rejects malformed or un-timestamped state instead of treating it as confirmation", () => {
    expect(parseSoftwareStopState("not-json")).toBeNull();
    expect(parseSoftwareStopState({ active: true })).toBeNull();
    expect(
      parseSoftwareStopState({
        active: "true",
        observed_at: "2026-10-08T12:00:00Z",
      }),
    ).toBeNull();
  });

  it("keeps degraded persistence distinguishable from confirmed state", () => {
    const state = parseSoftwareStopState({
      active: true,
      observed_at: "2026-10-08T12:00:00Z",
      result: "degraded",
      durable: false,
    });
    expect(state.result).toBe("degraded");
    expect(state.durable).toBe(false);
  });

  it("re-renders as unknown when the state heartbeat expires", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(1000);
    window.ROSLIB = {
      Topic: FakeTopic,
      Message: class Message {
        constructor(properties) {
          Object.assign(this, properties);
        }
      },
    };
    FakeTopic.instances = [];

    const { result, unmount } = renderHook(() => useSoftwareStop(), {
      wrapper,
    });
    const stateTopic = FakeTopic.instances.find(
      (topic) => topic.name === "/safety/software_stop/state",
    );
    await act(async () => {
      stateTopic.callback({
        data: JSON.stringify({
          active: false,
          observed_at: new Date(1000).toISOString(),
          result: "confirmed",
          durable: true,
        }),
      });
    });
    expect(result.current.stateFresh).toBe(true);

    await act(async () => vi.advanceTimersByTimeAsync(3000));
    expect(result.current.stateFresh).toBe(true);
    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(result.current.stateFresh).toBe(false);

    unmount();
    vi.useRealTimers();
  });
});

afterEach(() => {
  cleanup();
  setRun(null);
  vi.useRealTimers();
  delete window.ROSLIB;
});
