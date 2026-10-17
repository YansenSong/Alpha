import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import useAgentSocket from "./useAgentSocket";

class FakeSocket {
  static OPEN = 1;
  static instances = [];
  readyState = 0;
  sent = [];
  constructor(url) {
    this.url = url;
    FakeSocket.instances.push(this);
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  send(raw) {
    this.sent.push(JSON.parse(raw));
  }
  receive(event) {
    this.onmessage?.({ data: JSON.stringify(event) });
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
}
beforeEach(() => {
  localStorage.clear();
  FakeSocket.instances = [];
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", FakeSocket);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
const setup = () =>
  renderHook(() => useAgentSocket({ enabled: true, storageKey: "agent-test" }));
const bind = (result) => {
  act(() => result.current.createSession());
  const socket = FakeSocket.instances.at(-1);
  act(() => socket.open());
  act(() =>
    socket.receive({
      type: "session.snapshot",
      session_id: "s",
      resume_token: "a".repeat(64),
      seq: 0,
      status: "idle",
      items: [],
    }),
  );
  return socket;
};

test("reconnect resumes with a credential and never replays a prompt", () => {
  const { result } = setup();
  const socket = bind(result);
  act(() => result.current.prompt("hello"));
  const prompt = socket.sent.find((m) => m.type === "chat.prompt");
  expect(prompt.text).toBe("hello");
  act(() => socket.close());
  act(() => vi.advanceTimersByTime(1000));
  const reconnected = FakeSocket.instances.at(-1);
  act(() => reconnected.open());
  expect(reconnected.sent).toHaveLength(1);
  expect(reconnected.sent[0]).toMatchObject({
    type: "session.resume",
    session_id: "s",
    resume_token: "a".repeat(64),
  });
  act(() =>
    reconnected.receive({
      type: "session.snapshot",
      session_id: "s",
      seq: 3,
      status: "running",
      items: [{ id: prompt.request_id, role: "user", text: "hello" }],
    }),
  );
  expect(result.current.lastAccepted.text).toBe("hello");
  expect(result.current.status).toBe("running");
});

test("abort ACK unlocks controls and invalid resume permits explicit new session", () => {
  const { result } = setup();
  const socket = bind(result);
  act(() =>
    socket.receive({
      type: "session.snapshot",
      session_id: "s",
      seq: 1,
      status: "running",
      items: [],
    }),
  );
  act(() => result.current.abort());
  const abort = socket.sent.at(-1);
  act(() =>
    socket.receive({ type: "request.ack", request_id: abort.request_id }),
  );
  expect(result.current.pending).toBeNull();
  act(() => result.current.selectSession("s"));
  const resumed = FakeSocket.instances.at(-1);
  act(() => resumed.open());
  act(() =>
    resumed.receive({ type: "request.error", message: "Invalid credential" }),
  );
  expect(result.current.error).toBe("Invalid credential");
  expect(result.current.connection).not.toBe("ready");
  act(() => result.current.createSession());
  const fresh = FakeSocket.instances.at(-1);
  act(() => fresh.open());
  expect(fresh.sent[0].type).toBe("session.create");
});

test("unmount cancels reconnect and leaves server-side generation untouched", () => {
  const { result, unmount } = setup();
  const socket = bind(result);
  act(() => socket.close());
  const count = FakeSocket.instances.length;
  unmount();
  act(() => vi.advanceTimersByTime(30000));
  expect(FakeSocket.instances).toHaveLength(count);
  expect(socket.sent.some((m) => m.type === "chat.abort")).toBe(false);
});

test("deletion waits for server confirmation before discarding credentials", () => {
  const { result } = setup();
  const socket = bind(result);
  act(() => result.current.deleteSession("s"));
  const request = socket.sent.at(-1);
  expect(request).toMatchObject({
    type: "session.delete",
    session_id: "s",
    resume_token: "a".repeat(64),
  });
  expect(result.current.sessions).toHaveLength(1);
  act(() =>
    socket.receive({
      type: "request.error",
      request_id: request.request_id,
      message: "请先停止生成",
    }),
  );
  expect(result.current.sessions).toHaveLength(1);
  expect(result.current.deletingId).toBeNull();
  act(() => result.current.deleteSession("s"));
  act(() => socket.receive({ type: "session.deleted", session_id: "s" }));
  expect(result.current.sessions).toHaveLength(0);
  expect(JSON.parse(localStorage.getItem("agent-test")).active).toBeNull();
  expect(result.current.sessionId).toBeNull();
});
