import React from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import AssistantMessage from "./AssistantMessage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("renders headings, lists, quotes, tables and task lists as structured content", () => {
  const text =
    "# 项目能力\n\n**定位**与 `ROS2`\n\n> 当前是 Mock 模式\n\n1. 查询状态\n2. 查看模块\n\n- [x] SDK 接入\n\n| 模块 | 状态 |\n| --- | --- |\n| 导航 | 可用 |";
  const { container } = render(<AssistantMessage text={text} status="done" />);
  expect(screen.getByRole("heading", { name: "项目能力" })).toBeTruthy();
  expect(container.querySelector("strong").textContent).toBe("定位");
  expect(container.querySelector("blockquote").textContent).toContain("Mock");
  expect(container.querySelectorAll("ol > li")).toHaveLength(2);
  expect(screen.getByRole("checkbox").checked).toBe(true);
  expect(screen.getByRole("table")).toBeTruthy();
  expect(screen.getByRole("region", { name: "回复中的表格" }).tabIndex).toBe(0);
});

test("highlights fenced code and copies the exact code or full Markdown source", async () => {
  const writeText = vi.fn().mockResolvedValue();
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  const source = '示例：\n\n```python\nprint("hello")\n```';
  const { container } = render(
    <AssistantMessage text={source} status="done" />,
  );
  expect(container.querySelector(".hljs-string").textContent).toBe('"hello"');
  fireEvent.click(screen.getByRole("button", { name: "复制代码" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith('print("hello")'));
  expect(await screen.findByRole("button", { name: "复制代码" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "复制回复" }));
  await waitFor(() => expect(writeText).toHaveBeenCalledWith(source));
});

test("keeps incomplete fences readable during streaming and unknown languages as plain text", () => {
  const view = render(
    <AssistantMessage text={'```python\nprint("he'} status="running" />,
  );
  expect(screen.getByLabelText("python代码").textContent).toBe('print("he');
  expect(screen.getByText("正在生成")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "复制回复" })).toBeNull();
  view.rerender(
    <AssistantMessage
      text={'```unknownlang\n<img onerror="bad">\n```'}
      status="done"
    />,
  );
  expect(screen.getByLabelText("unknownlang代码").textContent).toBe(
    '<img onerror="bad">',
  );
  expect(view.container.querySelector("img")).toBeNull();
});

test("does not execute raw HTML or render unsafe links and remote image requests", () => {
  const source =
    "<script>alert(1)</script>\n\n[危险](javascript:alert%281%29)\n\n[文档](https://example.com/docs)\n\n![图](https://example.com/image.png)\n\n```html\n<img src=x onerror=alert(1)>\n```";
  const { container } = render(
    <AssistantMessage text={source} status="done" />,
  );
  expect(container.querySelector("script, img")).toBeNull();
  expect(screen.getByText("危险").closest("a")).toBeNull();
  const link = screen.getByRole("link", { name: "文档" });
  expect(link.getAttribute("rel")).toBe("noopener noreferrer");
  expect(link.getAttribute("target")).toBe("_blank");
  expect(
    screen.getByRole("link", { name: "图片：图" }).getAttribute("href"),
  ).toBe("https://example.com/image.png");
});

test("reports clipboard failures without pretending a copy succeeded", async () => {
  vi.stubGlobal("navigator", {
    clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
  });
  render(<AssistantMessage text="reply" status="done" />);
  fireEvent.click(screen.getByRole("button", { name: "复制回复" }));
  expect(await screen.findByText("复制失败，请手动选择文本")).toBeTruthy();
});

test("code wrapping and expanded tables retain the original content", () => {
  const source =
    '```python\nprint("hello")\n```\n\n| A | B |\n| --- | --- |\n| one | two |';
  const { container } = render(
    <AssistantMessage text={source} status="done" />,
  );
  const wrap = screen.getByRole("button", { name: "代码自动换行" });
  fireEvent.click(wrap);
  expect(wrap.getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByLabelText("python代码").className).toContain(
    "agent-code-wrap",
  );
  fireEvent.click(screen.getByRole("button", { name: "展开表格" }));
  expect(container.querySelector(".agent-table-expanded")).toBeTruthy();
  expect(screen.getByRole("cell", { name: "two" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "收起表格" }));
  expect(container.querySelector(".agent-table-expanded")).toBeNull();
});
