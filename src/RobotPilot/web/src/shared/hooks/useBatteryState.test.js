import { describe, expect, it } from "vitest";

import { parseBatteryState } from "./useBatteryState";

describe("authoritative battery telemetry", () => {
  it("preserves simulated source and charging state", () => {
    const state = parseBatteryState({
      percent: 72.5,
      source: "simulated",
      available: true,
      charging: true,
      observed_at: "2026-10-08T00:00:00Z",
    });
    expect(state).toMatchObject({
      percent: 72.5,
      source: "simulated",
      simulated: true,
      charging: true,
      available: true,
    });
  });

  it("retains BMS values and state without coercing absent measurements to zero", () => {
    const state = parseBatteryState({
      percent: 76.5,
      source: "simulated",
      available: true,
      observed_at: "2026-10-08T00:00:00Z",
      voltage_v: 24.7,
      current_a: -1.2,
      charging_state: "discharging",
      low_battery: false,
      return_to_charge_state: "not_available",
      threshold_config_version: 3,
    });
    expect(state).toMatchObject({
      voltage_v: 24.7,
      current_a: -1.2,
      charging_state: "discharging",
      low_battery: false,
      return_to_charge_state: "not_available",
      threshold_config_version: 3,
    });
    expect(
      parseBatteryState({
        percent: null,
        source: "unavailable",
        available: false,
        observed_at: "2026-10-08T00:00:00Z",
        voltage_v: null,
        current_a: null,
      }),
    ).toMatchObject({ voltage_v: null, current_a: null });
  });

  it("accepts unavailable state without inventing a percentage", () => {
    const state = parseBatteryState({
      percent: null,
      source: "unavailable",
      available: false,
      observed_at: "2026-10-08T00:00:00Z",
      reason: "Battery telemetry is disabled",
    });
    expect(state.percent).toBeNull();
    expect(state.available).toBe(false);
    expect(state.reason).toBe("Battery telemetry is disabled");
  });

  it("rejects malformed values and impossible percentages", () => {
    expect(parseBatteryState("not-json")).toBeNull();
    expect(
      parseBatteryState({
        percent: 101,
        source: "hardware",
        available: true,
        observed_at: "2026-10-08T00:00:00Z",
      }),
    ).toBeNull();
  });
});
