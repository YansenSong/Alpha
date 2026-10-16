import { describe, expect, it } from "vitest";

import {
  hasUnavailableStep,
  isExecutableStep,
  missionKind,
} from "./missionPresentation";

describe("mission presentation and execution guards", () => {
  it("labels one-off, scheduled, and operator authored missions", () => {
    expect(missionKind({ id: "manual-123" }, new Set(), true)).toBe(
      "forced_one_off",
    );
    expect(missionKind({ id: "patrol" }, new Set(["patrol"]), true)).toBe(
      "regular_scheduled",
    );
    expect(missionKind({ id: "custom" }, new Set(), true)).toBe(
      "operator_specified",
    );
    expect(missionKind({ id: "custom" }, new Set(), false)).toBe("unavailable");
  });

  it("blocks dock steps without disabling supported navigation steps", () => {
    expect(isExecutableStep("waypoint")).toBe(true);
    expect(isExecutableStep("wait")).toBe(true);
    expect(isExecutableStep("home")).toBe(true);
    expect(isExecutableStep("dock")).toBe(false);
    expect(isExecutableStep("undock")).toBe(false);
    expect(hasUnavailableStep({ steps: [{ type: "dock" }] })).toBe(true);
    expect(hasUnavailableStep({ steps: [{ type: "waypoint" }] })).toBe(false);
  });
});
