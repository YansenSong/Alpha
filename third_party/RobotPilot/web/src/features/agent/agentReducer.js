export const initialAgentState = {
  connection: "connecting",
  sessionId: null,
  seq: 0,
  status: "idle",
  items: [],
  error: "",
  pending: null,
  lastAccepted: null,
};

const upsert = (items, item) =>
  items.some((entry) => entry.id === item.id)
    ? items.map((entry) => (entry.id === item.id ? item : entry))
    : [...items, item];

export function agentReducer(state, action) {
  if (action.type === "reset") return { ...initialAgentState };
  if (action.type === "connection")
    return {
      ...state,
      connection: action.value,
      ...(action.error ? { error: action.error } : {}),
    };
  if (action.type === "pending")
    return { ...state, pending: action.value, error: "" };
  if (action.type === "error")
    return { ...state, error: action.message, pending: null };
  const event = action.event;
  if (!event) return state;
  if (event.type === "request.error")
    return { ...state, error: event.message, pending: null };
  if (event.type === "request.ack") {
    return state.pending?.id === event.request_id &&
      state.pending.type === "chat.abort"
      ? { ...state, pending: null }
      : state;
  }
  if (event.type === "session.snapshot") {
    if (state.sessionId === event.session_id && event.seq < state.seq)
      return state;
    const accepted =
      state.pending && event.items.find((item) => item.id === state.pending.id);
    return {
      ...state,
      connection: "ready",
      sessionId: event.session_id,
      seq: event.seq,
      status: event.status,
      items: event.items,
      error: "",
      pending: null,
      lastAccepted: accepted
        ? { id: accepted.id, text: accepted.text }
        : state.lastAccepted,
    };
  }
  if (
    event.session_id !== state.sessionId ||
    !Number.isInteger(event.seq) ||
    event.seq <= state.seq
  )
    return state;
  const next = { ...state, seq: event.seq };
  if (event.type === "chat.accepted") {
    next.items = upsert(state.items, {
      id: event.request_id,
      role: "user",
      text: event.text,
      status: "done",
    });
    next.status = "running";
    next.pending = null;
    if (state.pending?.id === event.request_id)
      next.lastAccepted = { id: event.request_id, text: event.text };
  } else if (event.type === "agent.message_start") {
    next.status = "running";
    next.items = upsert(state.items, {
      id: event.message_id,
      role: "assistant",
      text: "",
      status: "running",
    });
  } else if (event.type === "agent.text_delta") {
    next.items = state.items.map((item) =>
      item.id === event.message_id
        ? { ...item, text: item.text + event.delta }
        : item,
    );
  } else if (
    ["agent.message_end", "agent.tool_start", "agent.tool_end"].includes(
      event.type,
    )
  ) {
    next.items = upsert(state.items, event.item);
  } else if (event.type === "agent.settled") {
    next.status = "idle";
    next.items = state.items.map((item) =>
      item.status === "running" ? { ...item, status: "aborted" } : item,
    );
  } else if (event.type === "agent.error") next.error = event.message;
  return next;
}
