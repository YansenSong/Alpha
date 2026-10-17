import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { KeepoutZonesEditor } from "./KeepoutZones";
vi.mock("../shared/hooks/useKeepoutZones", () => ({ default: vi.fn() }));
afterEach(cleanup);
const rule = { id: "private-rule-id", name: "门口", type: "keepout", cx: 0, cy: 0, w: 2, h: 2 };
const props = { rules: [rule], ready: true, canEdit: true, section: "rules", deleteRule: vi.fn() };
test("toggle persists the flag without optimistic changes or exposing IDs", async () => {
  let finish;
  const setRuleEnabled = vi.fn(() => new Promise(resolve => { finish = resolve; }));
  const view = render(<KeepoutZonesEditor {...props} setRuleEnabled={setRuleEnabled} />);
  expect(screen.queryByText("private-rule-id")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "禁用 门口" }));
  expect(setRuleEnabled).toHaveBeenCalledWith(rule.id, false);
  expect(screen.getByText("已启用")).toBeTruthy();
  expect(screen.getByRole("button", { name: "禁用 门口" }).disabled).toBe(true);
  finish(true);
  await waitFor(() => expect(screen.queryByText("保存中…")).toBeNull());
  view.rerender(<KeepoutZonesEditor {...props} rules={[{ ...rule, enabled: false }]} setRuleEnabled={setRuleEnabled} />);
  expect(screen.getByText("已禁用")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "启用 门口" }));
  expect(setRuleEnabled).toHaveBeenLastCalledWith(rule.id, true);
  finish(true);
});
test("each rule type has its own matching badge and type color; disabled is grey", () => {
  const rules = ["keepout", "speed", "wall", "closure"].map((type, index) => ({ ...rule, type, id: `rule-${index}`, name: type }));
  const view = render(<KeepoutZonesEditor {...props} rules={rules} setRuleEnabled={vi.fn()} />);
  const articles = view.container.querySelectorAll("article");
  const colors = [...articles].map(article => {
    const badges = article.querySelectorAll("span[style]");
    expect(badges[0].style.backgroundColor).toBe(badges[1].style.backgroundColor);
    return badges[0].style.backgroundColor;
  });
  expect(new Set(colors).size).toBe(4);
  view.rerender(<KeepoutZonesEditor {...props} rules={[{ ...rule, enabled: false }]} setRuleEnabled={vi.fn()} />);
  expect(view.container.querySelector("article span[style]").style.backgroundColor).toBe("rgb(100, 116, 139)");
});
test("read-only or pending editors cannot toggle rules", () => {
  const action = vi.fn();
  const view = render(<KeepoutZonesEditor {...props} canEdit={false} setRuleEnabled={action} />);
  expect(screen.getByRole("button", { name: "禁用 门口" }).disabled).toBe(true);
  view.rerender(<KeepoutZonesEditor {...props} application="PENDING" setRuleEnabled={action} />);
  fireEvent.click(screen.getByRole("button", { name: "禁用 门口" }));
  expect(action).not.toHaveBeenCalled();
});
