import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import os from "node:os";
import path from "node:path";
import { WebSocket } from "ws";
import { createGateway } from "./server.mjs";
import { GatewaySessions } from "./session-manager.mjs";
import { checkUiModules } from "./ui-module-check.mjs";
import { projectRoot } from "./pi-host.mjs";

if (!process.argv.includes("--trust-project")) throw new Error("Pass --trust-project to load project resources");
const webRoot = path.join(projectRoot, "third_party/RobotPilot/web");
const requireWeb = createRequire(path.join(webRoot, "package.json"));
const { createServer } = await import(pathToFileURL(requireWeb.resolve("vite")));
const directory = await mkdtemp(path.join(os.tmpdir(), "robotpilot-web-proxy-"));
let gateway;
let vite;
let ws;
try {
  gateway = await createGateway({ port: 0, sessions: new GatewaySessions({ directory }) });
  vite = await createServer({
    root: webRoot, configFile: path.join(webRoot, "vite.config.mjs"),
    server: { host: "127.0.0.1", port: 0, strictPort: false, open: false,
      proxy: { "/agent-api": { target: `http://127.0.0.1:${gateway.port}`, ws: true } } },
  });
  await vite.listen();
  const port = vite.httpServer.address().port;
  const page = await fetch(`http://127.0.0.1:${port}/agent`);
  assert.equal(page.status, 200);
  assert.ok((await page.text()).includes("RobotPilot"));
  await checkUiModules(`http://127.0.0.1:${port}`);
  const health = await fetch(`http://127.0.0.1:${port}/agent-api/health`);
  assert.equal((await health.json()).status, "ok");
  const events = [];
  ws = new WebSocket(`ws://127.0.0.1:${port}/agent-api/ws`, { origin: "http://localhost:3000" });
  ws.on("message", raw => events.push(JSON.parse(raw)));
  await new Promise((resolve, reject) => { ws.once("open", resolve); ws.once("error", reject); });
  const wait = async predicate => {
    const deadline = Date.now() + 90000;
    while (Date.now() < deadline) {
      const error = events.find(e => ["request.error", "agent.error"].includes(e.type));
      if (error) throw new Error(error.message);
      const event = events.find(predicate);
      if (event) return event;
      await new Promise(resolve => setTimeout(resolve, 20));
    }
    throw new Error("Vite proxy verification timed out");
  };
  ws.send(JSON.stringify({ type: "session.create", request_id: "create" }));
  const created = await wait(e => e.type === "session.snapshot");
  ws.send(JSON.stringify({ type: "chat.prompt", request_id: "prompt", session_id: created.session_id,
    text: "请调用 get_alpha_info 工具，然后用一句中文说明当前运行模式。" }));
  await wait(e => e.type === "agent.settled");
  assert.ok(events.some(e => e.type === "agent.text_delta"));
  assert.ok(events.some(e => e.type === "agent.tool_end" && e.item.status === "done"));
  console.log("PASS /agent response, Vite HTTP/WebSocket proxy and real Pi streaming/tool events");
} finally {
  ws?.terminate();
  await vite?.close();
  await gateway?.close();
  await rm(directory, { recursive: true, force: true });
}
