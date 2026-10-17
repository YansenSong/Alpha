import asyncio
import json
import unittest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from alpha_mcp.readonly_bridge import relay


class ReadonlyTransportTest(unittest.IsolatedAsyncioTestCase):
    async def test_denied_writes_never_reach_upstream(self):
        received = []
        async def upstream(socket):
            async for raw in socket:
                received.append(json.loads(raw))
                await socket.send(raw)
        async with serve(upstream, "127.0.0.1", 0) as source:
            url = f"ws://127.0.0.1:{source.sockets[0].getsockname()[1]}"
            async with serve(lambda socket: relay(socket, url), "127.0.0.1", 0) as bridge:
                async with connect(f"ws://127.0.0.1:{bridge.sockets[0].getsockname()[1]}") as client:
                    for payload in [
                        {"op": "publish", "topic": "/cmd_vel"},
                        {"op": "call_service", "service": "/set_parameters"},
                        {"op": "subscribe", "topic": "/points_raw"},
                    ]:
                        await client.send(json.dumps(payload))
                        reply = json.loads(await asyncio.wait_for(client.recv(), 2))
                        self.assertFalse(reply["result"])
                    query = {"op": "call_service", "service": "/rosapi/nodes", "id": "read"}
                    await client.send(json.dumps(query))
                    self.assertEqual(json.loads(await asyncio.wait_for(client.recv(), 2)), query)
                    self.assertEqual(received, [query])
