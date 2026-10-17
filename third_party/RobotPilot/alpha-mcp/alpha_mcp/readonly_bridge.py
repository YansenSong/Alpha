"""Capability-filtered rosbridge transport for the inspection MCP process."""
import asyncio
import json
import os
import threading
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

READ_SERVICES = {"/rosapi/" + name for name in (
    "nodes", "node_details", "topics", "topic_type", "services", "service_type",
    "publishers", "subscribers", "action_servers", "get_time")}
READ_TOPICS = {"/navigation/state", "/safety/software_stop/state", "/battery/state", "/diagnostics"}

def allowed(message):
    if not isinstance(message, dict):
        return False
    op = message.get("op")
    if op == "call_service":
        return message.get("service") in READ_SERVICES
    if op in {"subscribe", "unsubscribe"}:
        return message.get("topic") in READ_TOPICS or message.get("topic") == "/navigate_to_pose/_action/status"
    return op == "ping"

async def relay(client, upstream_url):
    async with connect(upstream_url, max_size=1_000_000, open_timeout=5) as upstream:
        async def requests():
            async for raw in client:
                try:
                    message = json.loads(raw)
                except (ValueError, TypeError):
                    await client.close(1008, "JSON required")
                    return
                if not isinstance(message, dict):
                    await client.close(1008, "JSON object required")
                    return
                if not allowed(message):
                    await client.send(json.dumps({"op": "service_response", "id": message.get("id"),
                        "service": message.get("service"), "result": False,
                        "values": {"error": "Alpha inspection transport denies this operation"}}))
                    continue
                await upstream.send(raw)
        async def replies():
            async for raw in upstream:
                await client.send(raw)
        tasks = [asyncio.create_task(requests()), asyncio.create_task(replies())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

class InspectionBridge:
    def __init__(self, upstream_url):
        self.upstream_url = upstream_url
        self.ready = threading.Event()
        self.port = None
        self.error = None
    def start(self):
        def run():
            try:
                asyncio.run(self._run())
            except Exception as error:
                self.error = error
                self.ready.set()
        threading.Thread(target=run, daemon=True, name="readonly-rosbridge").start()
        if not self.ready.wait(5) or self.error:
            raise RuntimeError("Cannot start read-only rosbridge relay")
        return self.port
    async def _run(self):
        async with serve(lambda client: relay(client, self.upstream_url), "127.0.0.1", 0, max_size=65536) as server:
            self.port = server.sockets[0].getsockname()[1]
            self.ready.set()
            await asyncio.Future()

def main():
    bridge = InspectionBridge(os.environ.get("ALPHA_ROSBRIDGE_URL", "ws://127.0.0.1:9090"))
    bridge.start()
    threading.Event().wait()
