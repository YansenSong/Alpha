import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import CancelTaskButton from "./CancelTaskButton";
import { AuthContext, useRosStatus } from "../app/App";
import useMissionRun from "../shared/hooks/useMissionRun";
import { useRoleAccess } from "../shared/auth/roleAccess";
import { cancelMissionTask } from "../shared/missions/taskApi";
vi.mock("../app/App", async () => ({
  AuthContext: (await import("react")).createContext({ robotId: "robot-001" }),
  useRosStatus: vi.fn(() => "connected"),
}));
vi.mock("../shared/hooks/useMissionRun", () => ({ default: vi.fn() }));
vi.mock("../shared/auth/roleAccess", () => ({ useRoleAccess: vi.fn(() => ({ allowed: true })) }));
vi.mock("../shared/missions/taskApi", () => ({ cancelMissionTask: vi.fn() }));
vi.mock("../shared/i18n/i18n", () => ({ useT: () => ({ t: text => text }) }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
const paused = () => {
  useMissionRun.mockReturnValue({ taskId: "paused-task", status: "paused" });
  useRosStatus.mockReturnValue("connected");
  useRoleAccess.mockReturnValue({ allowed: true });
};
test("paused task can be cancelled; acceptance waits for authoritative terminal state", async () => {
  paused();
  cancelMissionTask.mockResolvedValue({ status: "accepted" });
  const view = render(<CancelTaskButton />);
  fireEvent.click(screen.getByRole("button", { name: "Cancel task" }));
  await waitFor(() => expect(cancelMissionTask).toHaveBeenCalledWith("robot-001", "paused-task"));
  expect(screen.getByRole("button", { name: "Waiting for cancellation" }).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Waiting for cancellation" }));
  expect(cancelMissionTask).toHaveBeenCalledTimes(1);
  useMissionRun.mockReturnValue({ taskId: "paused-task", status: "cancelled" });
  view.rerender(<CancelTaskButton />);
  expect(screen.queryByRole("button")).toBeNull();
});
test("cancellation errors remain visible and do not claim cancellation", async () => {
  paused();
  cancelMissionTask.mockRejectedValue(new Error("Robot offline"));
  render(<CancelTaskButton />);
  fireEvent.click(screen.getByRole("button", { name: "Cancel task" }));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Robot offline");
  expect(screen.getByRole("button", { name: "Cancel task" }).disabled).toBe(false);
});
test("viewer and disconnected clients cannot dispatch cancellation", () => {
  paused();
  useRoleAccess.mockReturnValue({ allowed: false });
  const view = render(<CancelTaskButton />);
  expect(screen.getByRole("button").disabled).toBe(true);
  useRoleAccess.mockReturnValue({ allowed: true });
  useRosStatus.mockReturnValue("disconnected");
  view.rerender(<CancelTaskButton />);
  fireEvent.click(screen.getByRole("button"));
  expect(cancelMissionTask).not.toHaveBeenCalled();
});
