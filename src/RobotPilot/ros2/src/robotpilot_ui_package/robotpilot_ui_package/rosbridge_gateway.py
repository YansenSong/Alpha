"""Role-aware WebSocket gateway for the existing ROSLIB browser client."""

import asyncio
import json
import os
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

import websockets

from .data_paths import data_directory, setting
from .auth import AuthStore, COOKIE_NAME, ROLE_LEVEL


READ_REQUEST_TOPICS = {
    "/nav_data_req", "/ackermann/routes/request", "/WP_req",
}
OPERATOR_TOPICS = {
    "/stop",
}
SOFTWARE_STOP_REQUEST_TOPIC = "/safety/software_stop/request"
ENGINEER_TOPICS = {
    "/ui_operation",
    "/ackermann/routes/plan_request", "/ackermann/routes/operation",
    "/area_rules/command",
}
READ_SERVICES = {
    "/rosapi/topics", "/rosapi/topic_type", "/rosapi/services",
    "/rosapi/service_type", "/rosapi/nodes", "/rosapi/publishers",
    "/rosapi/subscribers", "/rosapi/message_details", "/rosapi/service_request_details",
    "/rosapi/get_time", "/rosapi/get_param", "/rosapi/get_param_names",
}


def required_role(message):
    """Return the required role, or None for an unsupported rosbridge operation."""
    if not isinstance(message, dict):
        return None
    operation = message.get("op")
    if operation in ("subscribe", "unsubscribe", "ping"):
        return "Viewer"
    if operation in ("advertise", "unadvertise", "publish"):
        topic = message.get("topic")
        if topic == "/mission/command":
            if operation != "publish":
                return "Viewer"
            try:
                command = json.loads(message.get("msg", {}).get("data", ""))
            except (TypeError, AttributeError, json.JSONDecodeError):
                return None
            return "Viewer" if isinstance(command, dict) and command.get("command") == "query" else None
        if topic == SOFTWARE_STOP_REQUEST_TOPIC and operation in ("advertise", "unadvertise"):
            return "Viewer"
        if topic == SOFTWARE_STOP_REQUEST_TOPIC:
            try:
                payload = message.get("msg", {}).get("data", "")
                action = json.loads(payload).get("action")
            except (AttributeError, TypeError, json.JSONDecodeError):
                return None
            return {
                "get_state": "Viewer",
                "request_stop": "Operator",
                "request_release": "Operator",
            }.get(action)
        if topic in READ_REQUEST_TOPICS:
            return "Viewer"
        if topic in OPERATOR_TOPICS:
            return "Operator"
        if topic in ENGINEER_TOPICS:
            return "Engineer"
        # Manual velocity and all unregistered ROS writes remain disabled.
        return None
    if operation == "call_service":
        service = message.get("service", "")
        if service in READ_SERVICES or service.endswith(("/get_state", "/get_parameters")):
            return "Viewer"
        if service.endswith("/change_state") or service.endswith("/set_parameters"):
            return "Engineer"
        if service == "/navigate_to_pose/_action/cancel_goal":
            return "Operator"
        return None
    return None


def allowed_origin(origin, allowed):
    if not origin:
        return False
    parsed = urlsplit(origin)
    return parsed.scheme in ("http", "https") and origin.rstrip("/") in allowed


async def serve_client(client, store, allowed_origins, upstream_url):
    headers = client.request.headers
    if not allowed_origin(headers.get("Origin"), allowed_origins):
        await client.close(code=4403, reason="Origin denied")
        return
    cookie = SimpleCookie()
    try:
        cookie.load(headers.get("Cookie", ""))
    except Exception:
        pass
    morsel = cookie.get(COOKIE_NAME)
    identity = store.session(morsel.value if morsel else None)
    if identity is None:
        await client.close(code=4401, reason="Login required")
        return
    token = morsel.value

    async def session_guard():
        while True:
            await asyncio.sleep(30)
            current = store.session(token)
            if current is None or any(
                current[key] != identity[key] for key in ("username", "role", "robot_id")
            ):
                await client.close(code=4401, reason="Session expired, revoked, or changed")
                return

    try:
        async with websockets.connect(upstream_url, max_size=8 * 1024 * 1024) as upstream:
            async def client_to_ros():
                async for raw in client:
                    try:
                        message = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        await client.close(code=4400, reason="Invalid JSON")
                        return
                    required = required_role(message)
                    if required is None or ROLE_LEVEL[identity["role"]] < ROLE_LEVEL[required]:
                        resource = message.get("topic", message.get("service", "")) if isinstance(message, dict) else ""
                        store.audit_ros(identity, message.get("op", "invalid") if isinstance(message, dict) else "invalid",
                                        resource, "denied")
                        await client.send(json.dumps({
                            "op": "status", "level": "error", "id": message.get("id") if isinstance(message, dict) else None,
                            "msg": "ROS operation denied by platform policy",
                        }))
                        continue
                    if message.get("op") in ("publish", "call_service"):
                        resource = message.get("topic", message.get("service", ""))
                        if message.get("op") == "publish" and resource == SOFTWARE_STOP_REQUEST_TOPIC:
                            payload = json.loads(message["msg"]["data"])
                            payload["source"] = f"web:{identity['username']}"
                            message["msg"]["data"] = json.dumps(payload, sort_keys=True)
                            raw = json.dumps(message)
                        store.audit_ros(identity, message["op"], resource, "allowed")
                    await upstream.send(raw)

            async def ros_to_client():
                async for raw in upstream:
                    await client.send(raw)

            tasks = [asyncio.create_task(client_to_ros()), asyncio.create_task(ros_to_client()),
                     asyncio.create_task(session_guard())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    except (OSError, websockets.WebSocketException):
        await client.close(code=1011, reason="ROS bridge unavailable")


async def run_gateway():
    db_path = setting("AUTH_DB", os.path.join(data_directory(), "auth.sqlite3"))
    origins = {
        item.strip().rstrip("/") for item in setting(
            "ALLOWED_ORIGINS",
            "http://127.0.0.1:3000,http://localhost:3000,http://127.0.0.1:5050,http://localhost:5050",
        ).split(",") if item.strip()
    }
    store = AuthStore(db_path)
    host = "127.0.0.1"
    port = int(setting("GATEWAY_PORT", "9091"))
    upstream = "ws://127.0.0.1:9090"
    async with websockets.serve(
        lambda client: serve_client(client, store, origins, upstream),
        host, port, max_size=8 * 1024 * 1024,
    ):
        await asyncio.Future()


def main():
    if os.environ.get("AUTH_MODE", "open").strip().lower() != "local":
        raise RuntimeError("rosbridge_gateway is only used with AUTH_MODE=local")
    asyncio.run(run_gateway())


if __name__ == "__main__":
    main()
