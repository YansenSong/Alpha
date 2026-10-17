import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { WebSocket } from "ws";
import { createGateway } from "../src/server.mjs";
import { GatewaySessions } from "../src/session-manager.mjs";

function fakeHostFactory(counter) {
  return async () => {
    const listeners = new Set();
    let finish;
    let current;
    const emit = event => { for (const listener of listeners) listener(event); };
    return { session: {
      subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
      async prompt(text) {
        counter.calls++;
        emit({ type: "message_start", message: { role: "assistant" } });
        emit({ type: "message_update", assistantMessageEvent: { type: "text_delta", delta: "hello" } });
        if (text === "hold") {
          current = new Promise(resolve => { finish = resolve; });
          await current;
        }
        emit({ type: "tool_execution_start", toolCallId: "tool-1", toolName: "get_alpha_info" });
        emit({ type: "tool_execution_end", toolCallId: "tool-1", toolName: "get_alpha_info", result: { content: [{ type: "text", text: "mock" }] } });
        emit({ type: "message_end", message: { role: "assistant", content: [{ type: "text", text: "hello final" }], stopReason: "stop" } });
        emit({ type: "agent_settled" });
      },
      async abort() { finish?.(); await current; },
      dispose() {},
    } };
  };
}
async function client(port, origin = "http://localhost:3000") {
  const ws = new WebSocket(`ws://127.0.0.1:${port}/agent-api/ws`, { origin });
  const events = [];
  ws.on("message", raw => events.push(JSON.parse(raw)));
  await new Promise((resolve, reject) => { ws.once("open", resolve); ws.once("error", reject); });
  return {
    ws, events,
    send(message) { ws.send(JSON.stringify(message)); },
    async wait(predicate) {
      const end = Date.now() + 4000;
      while (Date.now() < end) {
        const found = events.find(predicate);
        if (found) return found;
        await new Promise(resolve => setTimeout(resolve, 5));
      }
      throw new Error(`Timed out; events: ${JSON.stringify(events)}`);
    },
  };
}

test("WebSocket protocol: isolation, deduplication, resume, abort and restart", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "pi-gateway-test-"));
  const counter = { calls: 0 };
  const makeSessions = () => new GatewaySessions({ directory, hostFactory: fakeHostFactory(counter) });
  let gateway = await createGateway({ port: 0, sessions: makeSessions() });
  const clients = [];
  try {
    const a = await client(gateway.port); clients.push(a);
    a.send({ type: "session.create", request_id: "create-a" });
    const created = await a.wait(e => e.type === "session.snapshot");
    const id = created.session_id;
    const token = created.resume_token;
    assert.ok(token);
    const b = await client(gateway.port); clients.push(b);
    b.send({ type: "session.resume", request_id: "bad-resume", session_id: id, resume_token: "0".repeat(64) });
    await b.wait(e => e.type === "request.error");
    b.send({ type: "session.create", request_id: "create-b" });
    const other = await b.wait(e => e.type === "session.snapshot");
    assert.notEqual(other.session_id, id);
    a.send({ type: "chat.prompt", request_id: "prompt-1", session_id: id, text: "hello" });
    await a.wait(e => e.type === "agent.settled");
    assert.ok(a.events.some(e => e.type === "agent.text_delta"));
    assert.ok(a.events.some(e => e.type === "agent.tool_end"));
    assert.equal(b.events.some(e => e.type === "agent.text_delta"), false);
    a.send({ type: "chat.prompt", request_id: "prompt-1", session_id: id, text: "hello" });
    await a.wait(e => e.type === "request.ack");
    a.send({ type: "session.sync", request_id: "sync-1", session_id: id });
    const snapshot = await a.wait(e => e.request_id === "sync-1");
    assert.equal(counter.calls, 1);
    assert.equal(snapshot.items.filter(i => i.role === "assistant")[0].text, "hello final");
    const sequenced = a.events.filter(e => e.seq && e.type !== "session.snapshot").map(e => e.seq);
    assert.deepEqual(sequenced, [...new Set(sequenced)].sort((x, y) => x-y));
    a.send({ type: "chat.prompt", request_id: "hold-1", session_id: id, text: "hold" });
    await a.wait(e => e.type === "chat.accepted" && e.request_id === "hold-1");
    a.send({ type: "chat.prompt", request_id: "busy", session_id: id, text: "another" });
    await a.wait(e => e.type === "request.error" && e.request_id === "busy");
    a.ws.terminate();
    const resumed = await client(gateway.port); clients.push(resumed);
    resumed.send({ type: "session.resume", request_id: "resume", session_id: id, resume_token: token });
    const running = await resumed.wait(e => e.type === "session.snapshot");
    assert.equal(running.status, "running");
    assert.equal(running.items.filter(i => i.role === "assistant").at(-1).text, "hello");
    resumed.send({ type: "chat.abort", request_id: "abort", session_id: id });
    await resumed.wait(e => e.type === "agent.settled");
    assert.equal(counter.calls, 2);
    await gateway.close();
    gateway = await createGateway({ port: 0, sessions: makeSessions() });
    const restarted = await client(gateway.port); clients.push(restarted);
    restarted.send({ type: "session.resume", request_id: "restart", session_id: id, resume_token: token });
    const recovered = await restarted.wait(e => e.type === "session.snapshot");
    assert.equal(recovered.status, "idle");
    assert.ok(recovered.seq > snapshot.seq);
    assert.equal(recovered.items.filter(i => i.role === "user").length, 2);
    restarted.send({ type: "chat.prompt", request_id: "prompt-1", session_id: id, text: "hello" });
    await restarted.wait(e => e.type === "request.ack");
    assert.equal(counter.calls, 2);
  } finally {
    for (const c of clients) c.ws.terminate();
    await gateway.close();
    await rm(directory, { recursive: true, force: true });
  }
});

test("rejects unapproved WebSocket origins", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "pi-origin-test-"));
  const gateway = await createGateway({ port: 0, sessions: new GatewaySessions({ directory }) });
  try { await assert.rejects(client(gateway.port, "https://untrusted.example"), /403/); }
  finally { await gateway.close(); await rm(directory, { recursive: true, force: true }); }
});

test("abort before prompt initialization completes does not start the model", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "pi-early-abort-"));
  const counter = { calls: 0 };
  const sessions = new GatewaySessions({ directory, hostFactory: fakeHostFactory(counter) });
  try {
    await sessions.init();
    const { record } = await sessions.create();
    const accepted = sessions.prompt(record, "early", "hold");
    const aborted = sessions.abort(record);
    await Promise.all([accepted, aborted]);
    assert.equal(counter.calls, 0);
    assert.equal(record.state.status, "idle");
  } finally { await sessions.close(); await rm(directory, { recursive: true, force: true }); }
});

test("interrupted work is shown as interrupted after process recovery", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "pi-interrupted-"));
  const sessions = new GatewaySessions({ directory, hostFactory: fakeHostFactory({ calls: 0 }) });
  let recovered;
  try {
    await sessions.init();
    const { record, token } = await sessions.create();
    record.state.status = "running";
    record.state.items.push({ id: "partial", role: "assistant", text: "partial", status: "running" });
    await sessions.persist(record);
    recovered = new GatewaySessions({ directory, hostFactory: async () => { throw new Error("Must not restart interrupted work"); } });
    await recovered.init();
    const snapshot = recovered.snapshot(recovered.authorize(record.state.id, token));
    assert.equal(snapshot.status, "interrupted");
    assert.equal(snapshot.items[0].status, "interrupted");
    record.state.status = "idle";
  } finally {
    await sessions.close(); await recovered?.close();
    await rm(directory, { recursive: true, force: true });
  }
});

test("session deletion requires ownership, rejects active runs, removes history and survives restart", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "pi-delete-test-"));
  const sessions = new GatewaySessions({ directory, hostFactory: fakeHostFactory({ calls: 0 }) });
  const gateway = await createGateway({ port: 0, sessions });
  let socket;
  try {
    const { record, token } = await sessions.create();
    const id = record.state.id;
    socket = await client(gateway.port);
    socket.send({ type: "session.delete", request_id: "bad-delete", session_id: id, resume_token: "0".repeat(64) });
    await socket.wait(e => e.request_id === "bad-delete" && e.type === "request.error");
    assert.ok(sessions.authorize(id, token));
    await sessions.prompt(record, "hold", "hold");
    await assert.rejects(sessions.delete(id, token), /停止生成/);
    await sessions.abort(record);
    socket.send({ type: "session.delete", request_id: "delete", session_id: id, resume_token: token });
    await socket.wait(e => e.request_id === "delete" && e.type === "session.deleted");
    assert.throws(() => sessions.authorize(id, token));
    const { readdir } = await import("node:fs/promises");
    assert.equal((await readdir(directory)).some(name => name.startsWith(id)), false);
    const restarted = new GatewaySessions({ directory });
    await restarted.init();
    assert.equal(restarted.records.size, 0);
    await restarted.close();
  } finally { socket?.ws.terminate(); await gateway.close(); await rm(directory, { recursive: true, force: true }); }
});

test("a deletion interrupted by process exit finishes cleanup during recovery", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "pi-delete-recovery-"));
  const sessions = new GatewaySessions({ directory, hostFactory: fakeHostFactory({ calls: 0 }) });
  try {
    await sessions.init();
    const { record } = await sessions.create();
    const id = record.state.id;
    const { rename } = await import("node:fs/promises");
    await rename(path.join(directory, `${id}.json`), path.join(directory, `${id}.deleted`));
    const restarted = new GatewaySessions({ directory });
    await restarted.init();
    assert.equal(restarted.records.size, 0);
    const { readdir } = await import("node:fs/promises");
    assert.deepEqual(await readdir(directory), []);
    await restarted.close();
  } finally { await sessions.close(); await rm(directory, { recursive: true, force: true }); }
});
