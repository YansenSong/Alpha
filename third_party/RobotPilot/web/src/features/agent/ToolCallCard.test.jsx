import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import ToolCallCard from "./ToolCallCard";
afterEach(cleanup);

test("compact tool row preserves explicit disclosure while its state changes", () => {
  const item = {
    id: "tool",
    name: "get_alpha_info",
    status: "running",
    text: "",
  };
  const view = render(<ToolCallCard item={item} />);
  const button = screen.getByRole("button");
  expect(button.getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(button);
  view.rerender(
    <ToolCallCard
      item={{ ...item, status: "done", text: '{"mode":"mock"}' }}
    />,
  );
  expect(button.getAttribute("aria-expanded")).toBe("true");
  expect(
    screen.getByLabelText("get_alpha_info 执行结果").textContent,
  ).toContain('  "mode": "mock"');
  fireEvent.click(button);
  expect(
    document.getElementById(button.getAttribute("aria-controls")).hidden,
  ).toBe(true);
});

test("failed tools expose diagnostics by default", () => {
  render(
    <ToolCallCard
      item={{
        id: "failed",
        name: "get_alpha_info",
        status: "error",
        text: "Tool failed",
      }}
    />,
  );
  expect(screen.getByRole("button").getAttribute("aria-expanded")).toBe("true");
  expect(screen.getByText("Tool failed")).toBeTruthy();
});
