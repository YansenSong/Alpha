import { randomUUID, randomBytes, createHash, timingSafeEqual } from "node:crypto";
import { mkdir, readdir, readFile, writeFile, rename, rm } from "node:fs/promises";
import path from "node:path";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { createProjectSession, disposeProjectSession, projectRoot, robotTools } from "./pi-host.mjs";

const textOf = message => typeof message.content === "string" ? message.content :
  (message.content ?? []).filter(c => c.type === "text").map(c => c.text).join("");
const digest = token => createHash("sha256").update(token).digest();
const validId = value => typeof value === "string" && /^[0-9a-f-]{36}$/.test(value);
export class GatewaySessions {
  constructor({ directory, hostFactory = createProjectSession, limit = 16 } = {}) {
    this.directory = directory ?? path.join(projectRoot, "third_party/RobotPilot/agent-gateway/.runtime/sessions");
    this.hostFactory = hostFactory;
    this.limit = limit;
    this.records = new Map();
    this.closed = false;
  }
  async init() {
    await mkdir(this.directory, { recursive: true, mode: 0o700 });
    for (const name of await readdir(this.directory)) {
      if (/^[0-9a-f-]{36}\.deleted$/.test(name)) {
        await rm(path.join(this.directory, name.slice(0, -8)), { recursive: true, force: true });
        await rm(path.join(this.directory, name), { force: true });
        continue;
      }
      if (!/^[0-9a-f-]{36}\.json$/.test(name)) continue;
      const state = JSON.parse(await readFile(path.join(this.directory, name), "utf8"));
      if (!validId(state.id) || name !== `${state.id}.json`) throw new Error("Invalid saved session");
      // An interrupted process cannot resume physical/agent execution from history.
      if (state.status === "running") {
        state.status = "interrupted";
        for (const item of state.items) if (item.status === "running") item.status = "interrupted";
      }
      this.records.set(state.id, { state, clients: new Set(), writes: Promise.resolve() });
    }
  }
  persist(record) {
    if (record.deleting) return record.writes;
    const data = JSON.stringify(record.state);
    const target = path.join(this.directory, `${record.state.id}.json`);
    record.writes = record.writes.then(async () => {
      await writeFile(`${target}.tmp`, data, { mode: 0o600 });
      await rename(`${target}.tmp`, target);
    });
    return record.writes;
  }
  async create() {
    if (this.closed || this.records.size >= this.limit) throw new Error("Session limit reached");
    const token = randomBytes(32).toString("hex");
    const state = { id: randomUUID(), tokenHash: digest(token).toString("hex"), seq: 0,
      status: "idle", run_id: null, items: [], requests: {} };
    const record = { state, clients: new Set(), writes: Promise.resolve() };
    this.records.set(state.id, record);
    try { await this.host(record); await this.persist(record); }
    catch (error) { this.records.delete(state.id); throw error; }
    return { record, token };
  }
  authorize(id, token) {
    const record = this.records.get(id);
    if (!record || record.deleting || typeof token !== "string" || token.length !== 64 ||
      !timingSafeEqual(digest(token), Buffer.from(record.state.tokenHash, "hex"))) {
      throw new Error("Session unavailable or invalid credential");
    }
    return record;
  }
  async host(record) {
    if (record.session) return record.session;
    if (!record.loading) record.loading = (async () => {
      const piDir = path.join(this.directory, record.state.id);
      await mkdir(piDir, { recursive: true, mode: 0o700 });
      const saved = (await readdir(piDir)).filter(name => name.endsWith(".jsonl"));
      if (saved.length > 1) throw new Error("Ambiguous Pi session storage");
      const sessionManager = saved.length
        ? SessionManager.open(path.join(piDir, saved[0]), piDir, projectRoot)
        : SessionManager.create(projectRoot, piDir);
      const { session } = await this.hostFactory({ trustProject: true, live: true, sessionManager });
      record.session = session;
      record.unsubscribe = session.subscribe(event => this.onEvent(record, event));
      return session;
    })();
    try { return await record.loading; } finally { record.loading = null; }
  }
  snapshot(record) {
    const { id, seq, status, run_id, items } = record.state;
    return { type: "session.snapshot", session_id: id, seq, status, run_id, items };
  }
  emit(record, type, fields = {}) {
    const event = { type, session_id: record.state.id, run_id: record.state.run_id,
      seq: ++record.state.seq, ...fields };
    // Snapshot state and event sequence are changed synchronously before broadcasting.
    void this.persist(record).catch(() => {
      record.state.status = "error";
      for (const client of record.clients) client.close(1011, "Session persistence failed");
    });
    for (const client of record.clients) {
      if (client.readyState === 1) {
        if (client.bufferedAmount > 1024 * 1024) client.close(1013, "Slow client; reconnect for snapshot");
        else client.send(JSON.stringify(event));
      }
    }
  }
  onEvent(record, event) {
    if (record.deleting) return;
    const state = record.state;
    if (event.type === "message_start" && event.message.role === "assistant") {
      record.messageId = randomUUID();
      state.items.push({ id: record.messageId, role: "assistant", text: "", status: "running" });
      this.emit(record, "agent.message_start", { message_id: record.messageId });
    }
    if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
      const item = state.items.find(i => i.id === record.messageId);
      if (!item) return;
      const delta = event.assistantMessageEvent.delta;
      item.text += delta;
      this.emit(record, "agent.text_delta", { message_id: item.id, delta });
    }
    if (event.type === "message_end" && event.message.role === "assistant") {
      const item = state.items.find(i => i.id === record.messageId);
      if (!item) return;
      item.text = textOf(event.message);
      item.status = event.message.stopReason === "error" ? "error" : event.message.stopReason === "aborted" ? "aborted" : "done";
      this.emit(record, "agent.message_end", { item });
      if (item.status === "error") this.emit(record, "agent.error", { message: "Model request failed; check provider authentication and availability" });
    }
    if (event.type === "tool_execution_start") {
      const item = { id: event.toolCallId, role: "tool", name: event.toolName, status: "running" };
      state.items.push(item);
      this.emit(record, "agent.tool_start", { item });
    }
    if (event.type === "tool_execution_end") {
      const item = state.items.find(i => i.id === event.toolCallId);
      if (!item) return;
      item.status = event.isError ? "error" : "done";
      // Only the explicitly approved static tool's text is exposed to the browser.
      item.text = (event.toolName === "get_alpha_info" || robotTools.includes(event.toolName)) ? textOf(event.result).slice(0, 8000) : "Result withheld";
      this.emit(record, "agent.tool_end", { item });
    }
    // prompt() resolution also covers errors before agent_start and extension handling.
    // Keep the per-session execution lock until that promise settles.
  }
  async prompt(record, requestId, text) {
    if (this.closed) throw new Error("Gateway shutting down");
    if (record.deleting || !this.records.has(record.state.id)) throw new Error("Session was deleted");
    if (Object.hasOwn(record.state.requests, requestId)) {
      if (record.state.requests[requestId].textHash !== digest(text).toString("hex")) throw new Error("Request ID reused with different content");
      return record.state.requests[requestId].run_id;
    }
    if (record.state.status === "running") throw new Error("Session busy; stop or wait for the current response");
    if (Object.keys(record.state.requests).length >= 500) throw new Error("Conversation limit reached; create a new session");
    const runId = randomUUID();
    record.state.status = "running"; // Acquire before awaiting SDK initialization.
    record.state.run_id = runId;
    record.state.requests[requestId] = { run_id: runId, textHash: digest(text).toString("hex") };
    record.state.items.push({ id: requestId, role: "user", text, status: "done" });
    record.cancelRequested = false;
    const accepted = this.persist(record);
    record.task = (async () => {
      try {
        await accepted;
        this.emit(record, "chat.accepted", { request_id: requestId, text });
        const session = await this.host(record);
        if (record.cancelRequested) return;
        await session.prompt(text, { expandPromptTemplates: false });
      } catch {
        this.emit(record, "agent.error", { message: "Agent request failed; check Gateway configuration and model availability" });
      } finally {
        record.state.status = "idle";
        for (const item of record.state.items) if (item.status === "running") item.status = "aborted";
        this.emit(record, "agent.settled");
      }
    })();
    await accepted;
    return runId;
  }
  async abort(record) {
    if (record.state.status !== "running") return;
    record.cancelRequested = true;
    const session = await this.host(record);
    await session.abort();
    await record.task;
  }
  async delete(id, token) {
    const record = this.authorize(id, token);
    if (record.state.status === "running") throw new Error("请先停止生成，再删除会话。");
    record.deleting = true;
    const tombstone = path.join(this.directory, `${id}.deleted`);
    try {
      await record.writes;
      // A tombstone prevents recovery of half-deleted history after a crash.
      await rename(path.join(this.directory, `${id}.json`), tombstone);
    } catch (error) { record.deleting = false; throw error; }
    this.records.delete(id);
    record.unsubscribe?.();
    await disposeProjectSession(record.session);
    const event = JSON.stringify({ type: "session.deleted", session_id: id });
    for (const client of record.clients) if (client.readyState === 1) client.send(event);
    record.clients.clear();
    await rm(path.join(this.directory, id), { recursive: true, force: true });
    await rm(tombstone, { force: true });
  }
  async close() {
    this.closed = true;
    await Promise.all([...this.records.values()].map(async record => {
      await this.abort(record);
      record.unsubscribe?.();
      await disposeProjectSession(record.session);
      await record.writes;
    }));
  }
}
