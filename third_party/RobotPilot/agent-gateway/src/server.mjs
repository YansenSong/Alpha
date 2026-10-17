import http from "node:http";
import { WebSocketServer } from "ws";
import { GatewaySessions } from "./session-manager.mjs";

const requestIdValid = value => typeof value === "string" && /^[A-Za-z0-9_-]{1,80}$/.test(value) && !["__proto__", "constructor", "prototype"].includes(value);
export async function createGateway({ port = 8769, origins = ["http://localhost:3000", "http://127.0.0.1:3000"], sessions = new GatewaySessions() } = {}) {
  await sessions.init();
  const allowedOrigins = new Set(origins);
  const server = http.createServer((req, res) => {
    if (req.url === "/agent-api/health" && req.method === "GET") {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ status: "ok", mode: "local-development" }));
    } else { res.writeHead(404); res.end(); }
  });
  const wss = new WebSocketServer({ noServer: true, maxPayload: 32768, perMessageDeflate: false });
  let closing = false;
  server.on("upgrade", (req, socket, head) => {
    if (closing || req.url !== "/agent-api/ws" || !allowedOrigins.has(req.headers.origin) || wss.clients.size >= 32) {
      socket.end("HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n");
      return;
    }
    wss.handleUpgrade(req, socket, head, ws => wss.emit("connection", ws, req));
  });
  const operations = new Set();
  wss.on("connection", ws => {
    let bound;
    let pending = 0;
    let chain = Promise.resolve();
    const send = data => { if (ws.readyState === 1) ws.send(JSON.stringify(data)); };
    ws.alive = true;
    ws.on("pong", () => { ws.alive = true; });
    ws.on("error", () => {});
    ws.on("close", () => bound?.clients.delete(ws));
    ws.on("message", (raw, binary) => {
      if (++pending > 32) { ws.close(1008, "Too many pending commands"); return; }
      chain = chain.then(async () => {
        if (closing || ws.readyState !== 1) return;
        let message;
        try {
          if (binary) throw new Error("Text JSON messages required");
          message = JSON.parse(raw.toString());
          if (!message || typeof message !== "object" || !requestIdValid(message.request_id)) throw new Error("Valid request_id required");
          const { type, request_id } = message;
          if (bound?.deleting) bound = undefined;
          if (type === "session.delete") {
            await sessions.delete(message.session_id, message.resume_token);
            send({ type: "session.deleted", request_id, session_id: message.session_id });
          } else if (type === "session.create") {
            if (bound) throw new Error("Already bound; open another connection for another session");
            const { record, token } = await sessions.create();
            bound = record;
            if (ws.readyState !== 1) return;
            bound.clients.add(ws);
            send({ ...sessions.snapshot(bound), request_id, resume_token: token });
          } else if (type === "session.resume") {
            if (bound) throw new Error("Already bound");
            bound = sessions.authorize(message.session_id, message.resume_token);
            bound.clients.add(ws);
            send({ ...sessions.snapshot(bound), request_id });
          } else {
            if (!bound || message.session_id !== bound.state.id) throw new Error("Bind the target session first");
            if (type === "chat.prompt") {
              if (typeof message.text !== "string" || !message.text.trim() || message.text.length > 12000) throw new Error("Prompt must contain 1–12000 characters");
              if (message.text.trimStart().startsWith("/")) throw new Error("Pi slash commands are unavailable in this Gateway");
              const run_id = await sessions.prompt(bound, request_id, message.text);
              send({ type: "request.ack", request_id, session_id: bound.state.id, run_id });
            } else if (type === "chat.abort") {
              // Do not block subsequent connection messages while abort waits for idle.
              void sessions.abort(bound).then(() => send({ type: "request.ack", request_id, session_id: bound.state.id }))
                .catch(() => send({ type: "request.error", request_id, message: "Abort failed" }));
            } else if (type === "session.sync") {
              send({ ...sessions.snapshot(bound), request_id });
            } else throw new Error("Unknown message type");
          }
        } catch (error) {
          send({ type: "request.error", request_id: requestIdValid(message?.request_id) ? message.request_id : undefined,
            message: error.message });
        }
      }).finally(() => { pending--; });
      const operation = chain;
      operations.add(operation);
      void operation.finally(() => operations.delete(operation));
    });
  });
  const heartbeat = setInterval(() => {
    for (const ws of wss.clients) {
      if (!ws.alive) ws.terminate();
      else { ws.alive = false; ws.ping(); }
    }
  }, 30000);
  heartbeat.unref();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", resolve);
  });
  return {
    port: server.address().port,
    async close() {
      closing = true;
      clearInterval(heartbeat);
      for (const ws of wss.clients) ws.terminate();
      await Promise.all(operations);
      await sessions.close();
      await new Promise(resolve => wss.close(resolve));
      await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
    },
  };
}
