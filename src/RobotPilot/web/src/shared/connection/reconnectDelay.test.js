import { describe, expect, it } from "vitest";

import { createReconnectController, getReconnectDelay } from "./reconnectDelay";

describe("getReconnectDelay", () => {
  const noJitter = () => 0.5;

  it("doubles retry intervals up to the configured maximum", () => {
    expect(
      [0, 1, 2, 3, 4, 5].map((attempt) =>
        getReconnectDelay(attempt, 1000, 30000, noJitter),
      ),
    ).toEqual([1000, 2000, 4000, 8000, 16000, 30000]);
  });

  it("applies bounded jitter and handles invalid attempts", () => {
    expect(getReconnectDelay(-1, 1000, 30000, () => 0)).toBe(800);
    expect(getReconnectDelay(Number.NaN, 1000, 30000, () => 1)).toBe(1200);
    expect(getReconnectDelay(10, 1000, 30000, () => 1)).toBe(30000);
  });

  it("deduplicates close/error retries and resets after connection", () => {
    const timers = [];
    const cleared = [];
    let connectCount = 0;
    const reconnect = createReconnectController({
      connect: () => {
        connectCount += 1;
      },
      random: noJitter,
      setTimer: (callback, delay) => {
        const timer = { callback, delay };
        timers.push(timer);
        return timer;
      },
      clearTimer: (timer) => cleared.push(timer),
    });

    expect(reconnect.schedule()).toBe(1000);
    expect(reconnect.schedule()).toBeNull();
    timers[0].callback();
    expect(connectCount).toBe(1);
    expect(reconnect.schedule()).toBe(2000);
    reconnect.connected();
    expect(cleared).toEqual([timers[1]]);
    expect(reconnect.schedule()).toBe(1000);
    reconnect.dispose();
    expect(reconnect.schedule()).toBeNull();
  });
});
