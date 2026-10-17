import { expect, test } from "vitest";
import { agentReducer, initialAgentState } from "./agentReducer";
const apply = (state, event) => agentReducer(state, { type: "event", event });
const snapshot = {
  type: "session.snapshot",
  session_id: "session-a",
  seq: 0,
  status: "idle",
  items: [],
};

test("streams text once and replaces it with the final message", () => {
  let state = apply(initialAgentState, snapshot);
  state = apply(state, {
    type: "agent.message_start",
    session_id: "session-a",
    seq: 1,
    message_id: "m",
  });
  const delta = {
    type: "agent.text_delta",
    session_id: "session-a",
    seq: 2,
    message_id: "m",
    delta: "hello",
  };
  state = apply(state, delta);
  state = apply(state, delta);
  expect(state.items[0].text).toBe("hello");
  state = apply(state, {
    type: "agent.message_end",
    session_id: "session-a",
    seq: 3,
    item: { id: "m", role: "assistant", text: "hello final", status: "done" },
  });
  expect(state.items[0].text).toBe("hello final");
  expect(state.items).toHaveLength(1);
});

test("snapshot reconciles a prompt accepted before disconnection", () => {
  const state = apply(
    { ...initialAgentState, pending: { id: "req", text: "hi" } },
    {
      ...snapshot,
      seq: 5,
      status: "running",
      items: [{ id: "req", role: "user", text: "hi" }],
    },
  );
  expect(state.pending).toBeNull();
  expect(state.lastAccepted.text).toBe("hi");
  expect(state.status).toBe("running");
  expect(
    apply(state, {
      type: "agent.text_delta",
      session_id: "other",
      seq: 6,
      message_id: "req",
      delta: "bad",
    }),
  ).toBe(state);
  expect(apply(state, { ...snapshot, seq: 4 })).toBe(state);
});

test("tool updates replace their card and settlement clears unfinished items", () => {
  let state = apply(initialAgentState, snapshot);
  state = apply(state, {
    type: "agent.tool_start",
    session_id: "session-a",
    seq: 1,
    item: { id: "tool", role: "tool", status: "running" },
  });
  state = apply(state, {
    type: "agent.tool_end",
    session_id: "session-a",
    seq: 2,
    item: { id: "tool", role: "tool", status: "done", text: "mock" },
  });
  expect(state.items).toHaveLength(1);
  expect(state.items[0].text).toBe("mock");
  state = apply(state, {
    type: "agent.message_start",
    session_id: "session-a",
    seq: 3,
    message_id: "partial",
  });
  state = apply(state, {
    type: "agent.settled",
    session_id: "session-a",
    seq: 4,
  });
  expect(state.status).toBe("idle");
  expect(state.items[1].status).toBe("aborted");
});
