"""Reuse upstream ros-mcp 3.1.2 tools behind an independently enforced read filter."""
import functools
import os
import threading
from fastmcp import FastMCP
from ros_mcp.tools.nodes import register_node_tools
from ros_mcp.tools.topics import register_topic_tools
from ros_mcp.tools.services import register_service_tools
from ros_mcp.tools.actions import register_action_tools
from ros_mcp.utils.websocket import WebSocketManager
from .readonly_bridge import InspectionBridge, READ_TOPICS

ALLOWED_TOOLS = {"get_nodes", "get_node_details", "get_topics", "get_topic_type",
                 "get_services", "get_actions", "get_action_status"}

class Collector:
    def __init__(self): self.tools = {}
    def tool(self, **metadata):
        def register(fn):
            if fn.__name__ in ALLOWED_TOOLS:
                self.tools[fn.__name__] = (fn, metadata)
            return fn
        return register

def build_server():
    port = InspectionBridge(os.environ.get("ALPHA_ROSBRIDGE_URL", "ws://127.0.0.1:9090")).start()
    manager = WebSocketManager("127.0.0.1", port, default_timeout=3)
    collector = Collector()
    for register in (register_node_tools, register_topic_tools, register_service_tools, register_action_tools):
        register(collector, manager)
    mcp = FastMCP("Alpha read-only ROS inspection")
    lock = threading.RLock()
    def serialized(fn):
        @functools.wraps(fn)
        def call(*args, **kwargs):
            with lock:
                return fn(*args, **kwargs)
        return call
    for fn, metadata in collector.tools.values():
        mcp.tool(**metadata)(serialized(fn))
    @mcp.tool(description="Read one approved small state topic. Never reads camera, point cloud or arbitrary topics.")
    def subscribe_once(topic: str) -> dict:
        if topic not in READ_TOPICS:
            raise ValueError("Topic is not in Alpha's inspection allowlist")
        with lock, manager:
            result = manager.request({"op": "subscribe", "topic": topic, "id": "alpha-state-once", "queue_length": 1})
        # Bound payload size before exposing it to the model.
        if not isinstance(result, dict) or result.get("topic") != topic or "msg" not in result:
            return {"topic": topic, "status": "unknown", "error": "No correlated topic sample received"}
        import json
        encoded = json.dumps(result)
        if len(encoded) > 8000:
            return {"topic": topic, "truncated": True, "summary": encoded[:8000]}
        return {"topic": topic, "message": result}
    return mcp

def main():
    build_server().run(transport="stdio", show_banner=False)

if __name__ == "__main__": main()
