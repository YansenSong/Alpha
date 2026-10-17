import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { WebSocket } from "ws";
import { createGateway } from "./server.mjs";
import { GatewaySessions } from "./session-manager.mjs";

if (!process.argv.includes("--trust-project")) throw new Error("Pass --trust-project to load project resources");
const directory = await mkdtemp(path.join(os.tmpdir(), "robotpilot-live-gateway-"));
let gateway;
let ws;
const connect = async port => {
  const socket = new WebSocket(`ws://127.0.0.1:${port}/agent-api/ws`, { origin: "http://localhost:3000" });
  const events = [];
  socket.on("message", raw => events.push(JSON.parse(raw)));
  await new Promise((resolve, reject) => { socket.once("open", resolve); socket.once("error", reject); });
  const wait = async predicate => {
    const deadline = Date.now() + 90000;
    while (Date.now() < deadline) {
      const error = events.find(e => ["request.error", "agent.error"].includes(e.type));
      if (error) throw new Error(error.message);
      const event = events.find(predicate);
      if (event) return event;
      await new Promise(resolve => setTimeout(resolve, 20));
    }
    throw new Error("Gateway verification timed out");
  };
  return { socket, events, wait, send: message => socket.send(JSON.stringify(message)) };
};
try {
  gateway = await createGateway({ port: 0, sessions: new GatewaySessions({ directory }) });
  const client = await connect(gateway.port); ws = client.socket;
  client.send({ type: "session.create", request_id: "create" });
  const created = await client.wait(e => e.type === "session.snapshot");
  client.send({ type: "chat.prompt", request_id: "prompt", session_id: created.session_id,
    text: "请调用 get_alpha_info，然后用一句中文说明当前模式。" });
  await client.wait(e => e.type === "agent.settled");
  assert.ok(client.events.some(e => e.type === "agent.text_delta"));
  assert.ok(client.events.some(e => e.type === "agent.tool_end" && e.item.status === "done"));
  console.log("PASS real WebSocket streaming, tool execution and settlement");
  ws.terminate();
  await gateway.close();
  gateway = await createGateway({ port: 0, sessions: new GatewaySessions({ directory }) });
  const resumed = await connect(gateway.port); ws = resumed.socket;
  resumed.send({ type: "session.resume", request_id: "resume", session_id: created.session_id, resume_token: created.resume_token });
  const snapshot = await resumed.wait(e => e.type === "session.snapshot");
  assert.ok(snapshot.items.some(i => i.role === "assistant" && i.text));
  assert.equal(snapshot.status, "idle");
  // A second model request proves Pi JSONL context can be reopened after restart.
  resumed.send({ type: "chat.prompt", request_id: "second", session_id: created.session_id,
    text: "根据刚才的工具结果，用一句话说明是否连接了真实机器人。" });
  await resumed.wait(e => e.type === "agent.settled");
  assert.ok(resumed.events.some(e => e.type === "agent.message_end" && e.item.text));
  console.log("PASS Gateway restart, persisted Pi history and second turn");
} finally {
  ws?.terminate();
  await gateway?.close();
  await rm(directory, { recursive: true, force: true });
}
