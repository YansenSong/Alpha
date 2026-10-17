import React, { createContext } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import AgentPage from "./AgentPage";
import { AuthContext } from "../app/App";
import useAgentSocket from "../features/agent/useAgentSocket";

vi.mock("../app/App", () => ({
  AuthContext: createContext({ mode: "open", robotId: "test" }),
}));
vi.mock("../features/agent/useAgentSocket", () => ({ default: vi.fn() }));
let agent;
beforeEach(() => {
  vi.clearAllMocks();
  agent = {
    connection: "ready",
    sessionId: "test-session",
    seq: 0,
    status: "idle",
    items: [],
    sessions: [],
    pending: null,
    lastAccepted: null,
    error: "",
    prompt: vi.fn(),
    abort: vi.fn(),
    createSession: vi.fn(),
    selectSession: vi.fn(),
    deleteSession: vi.fn(),
  };
  useAgentSocket.mockImplementation(() => agent);
});
afterEach(cleanup);

test("retains a draft until acceptance and respects Chinese IME composition", () => {
  const view = render(<AgentPage />);
  const input = screen.getByLabelText("发送给 Pi");
  fireEvent.change(input, { target: { value: "你好" } });
  fireEvent.keyDown(input, { key: "Enter", isComposing: true });
  expect(agent.prompt).not.toHaveBeenCalled();
  fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
  expect(agent.prompt).not.toHaveBeenCalled();
  fireEvent.keyDown(input, { key: "Enter" });
  expect(agent.prompt).toHaveBeenCalledWith("你好");
  expect(input.value).toBe("你好");
  agent = { ...agent, lastAccepted: { id: "req", text: "你好" } };
  view.rerender(<AgentPage />);
  expect(input.value).toBe("");
});

test("shows tool result, connection failure, and stop control", () => {
  agent = {
    ...agent,
    status: "running",
    items: [
      {
        id: "tool",
        role: "tool",
        name: "get_alpha_info",
        status: "done",
        text: "Mock result",
      },
    ],
  };
  const view = render(<AgentPage />);
  fireEvent.click(screen.getByRole("button", { name: "停止生成" }));
  expect(agent.abort).toHaveBeenCalledTimes(1);
  expect(screen.getByText("get_alpha_info")).toBeTruthy();
  expect(screen.getByText("Mock result")).toBeTruthy();
  agent = { ...agent, connection: "disconnected", error: "Gateway 未启动" };
  view.rerender(<AgentPage />);
  expect(screen.getByRole("alert").textContent).toContain("Gateway 未启动");
  expect(screen.getByRole("button", { name: "停止生成" }).disabled).toBe(true);
});

test("does not connect local-authenticated users to the open development gateway", () => {
  render(
    <AuthContext.Provider value={{ mode: "local", robotId: "test" }}>
      <AgentPage />
    </AuthContext.Provider>,
  );
  expect(screen.getByText(/本机 Vite 开发服务/)).toBeTruthy();
  expect(useAgentSocket).not.toHaveBeenCalled();
});

test("tool-only assistant messages do not create an empty reply or duplicate author", () => {
  const toolOnly = {
    id: "tool-call-message",
    role: "assistant",
    status: "running",
    text: "",
  };
  agent = { ...agent, status: "running", items: [toolOnly] };
  const view = render(<AgentPage />);
  expect(screen.getByText("正在思考…")).toBeTruthy();
  const finalItems = [
    { ...toolOnly, status: "done", text: " \n" },
    {
      id: "tool",
      role: "tool",
      name: "get_alpha_info",
      status: "done",
      text: "Mock result",
    },
    {
      id: "reply",
      role: "assistant",
      status: "done",
      text: "你好！当前为 Mock 模式。",
    },
  ];
  agent = { ...agent, status: "idle", items: finalItems };
  view.rerender(<AgentPage />);
  expect(screen.queryByText("正在思考…")).toBeNull();
  expect(screen.queryByText("本条消息没有文本内容")).toBeNull();
  expect(view.container.querySelectorAll("article.agent-message")).toHaveLength(
    1,
  );
  expect(view.container.querySelectorAll(".agent-avatar")).toHaveLength(1);
  expect(view.container.querySelectorAll(".agent-author")).toHaveLength(1);
  expect(screen.getByText("get_alpha_info")).toBeTruthy();
  const toolCard = screen.getByText("get_alpha_info").closest(".agent-tool");
  const reply = screen.getByText("你好！当前为 Mock 模式。");
  const author = view.container.querySelector(".agent-author");
  expect(toolCard.closest("article")).toBe(reply.closest("article"));
  expect(
    author.compareDocumentPosition(toolCard) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(
    toolCard.compareDocumentPosition(reply) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  // A fresh mount covers restoring the same records from a snapshot after refresh.
  view.unmount();
  const restored = render(<AgentPage />);
  expect(restored.container.querySelectorAll(".agent-avatar")).toHaveLength(1);
  expect(screen.queryByText("本条消息没有文本内容")).toBeNull();
});

test("multiple tools share one author per response and never cross user turns", () => {
  agent = {
    ...agent,
    items: [
      { id: "u1", role: "user", text: "查询能力", status: "done" },
      {
        id: "t1",
        role: "tool",
        name: "get_alpha_info",
        text: "first",
        status: "done",
      },
      {
        id: "t2",
        role: "tool",
        name: "get_alpha_info",
        text: "second",
        status: "done",
      },
      { id: "a1", role: "assistant", text: "第一轮回复", status: "done" },
      { id: "u2", role: "user", text: "继续", status: "done" },
      { id: "a2", role: "assistant", text: "第二轮回复", status: "done" },
    ],
  };
  const view = render(<AgentPage />);
  expect(view.container.querySelectorAll(".agent-avatar")).toHaveLength(2);
  const firstReply = screen.getByText("第一轮回复").closest("article");
  expect(firstReply.querySelectorAll(".agent-tool")).toHaveLength(2);
  expect(screen.getByText("第二轮回复").closest("article")).not.toBe(
    firstReply,
  );
});

test("session deletion is confirmed, and composer keeps only its embedded action", () => {
  agent.sessions = [{ id: "test-session", label: "测试会话" }];
  const view = render(<AgentPage />);
  fireEvent.click(screen.getByRole("button", { name: "删除测试会话" }));
  expect(agent.deleteSession).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(screen.queryByRole("button", { name: "确认删除" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "删除测试会话" }));
  fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
  expect(agent.deleteSession).toHaveBeenCalledWith("test-session");
  const input = screen.getByLabelText("发送给 Pi");
  const send = screen.getByRole("button", { name: "发送消息" });
  expect(input.closest(".agent-input-frame")).toBe(
    send.closest(".agent-input-frame"),
  );
  expect(input.labels[0].className).toBe("sr-only");
  expect(view.container.querySelector("#agent-prompt-help")).toBeNull();
  expect(screen.queryByText(/12000/)).toBeNull();
});
