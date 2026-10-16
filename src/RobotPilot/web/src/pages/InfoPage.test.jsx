import { act, cleanup, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../components/Camera", () => ({ default: () => null }));
vi.mock("../components/RobotState", () => ({ default: () => null }));
vi.mock("../components/SystemHealth", () => ({ default: () => null }));
vi.mock("../shared/api/apiFetch", () => ({
  apiFetch: vi.fn(async () => ({ json: async () => ({}) })),
}));
vi.mock("../shared/hooks/useBatteryState", () => ({
  default: () => ({ state: null, stale: true, usable: false }),
}));
vi.mock("../shared/hooks/useRobotStatus", () => ({
  default: () => ({ snapshot: null, stale: true, error: "" }),
}));

import { AuthContext } from "../app/App";
import InfoPage from "./InfoPage";

const wrapper = ({ children }) =>
  createElement(
    AuthContext.Provider,
    { value: { robotId: "robot-001" } },
    children,
  );

describe("InfoPage", () => {
  afterEach(() => cleanup());

  it("renders the status page when robot telemetry is unavailable", async () => {
    render(createElement(InfoPage), { wrapper });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByRole("heading", { level: 1 })).toBeTruthy();
    expect(screen.getByText("软件停车", { exact: false })).toBeTruthy();
    expect(screen.getByText("暂无电池数据")).toBeTruthy();
  });
});
