"""Business adapter. MissionManager remains authoritative; this journal only deduplicates submissions."""
import asyncio
import hashlib
import json
import math
import os
import re
import sqlite3
import uuid
from pathlib import Path
from urllib.parse import quote, urlsplit
import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

ROOT = Path(__file__).resolve().parents[4]
KEY = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")

def identifier(value):
    if not isinstance(value, str) or not value or len(value) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", value):
        raise ValueError("Invalid task/operation identifier")
    return quote(value, safe="")

class Journal:
    def __init__(self, filename):
        Path(filename).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(filename, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE IF NOT EXISTS operations (key TEXT PRIMARY KEY, body TEXT NOT NULL, result TEXT NOT NULL)")
        self.db.commit()
        os.chmod(filename, 0o600)
    def reserve(self, key, body):
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise ValueError("idempotency_key must contain 8–128 letters, digits, . _ : or -")
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":"))
        pending = {"operation_id": key, "status": "unknown", "completed": False, "verified": False,
                   "type": body["type"], "message": "Submission reserved; query robot state before retrying with any new key"}
        with self.db:
            cursor = self.db.execute("INSERT OR IGNORE INTO operations VALUES (?,?,?)", (key, encoded, json.dumps(pending)))
            row = self.db.execute("SELECT * FROM operations WHERE key=?", (key,)).fetchone()
            if row["body"] != encoded:
                raise ValueError("Idempotency key already belongs to a different request")
        return cursor.rowcount == 1, json.loads(row["result"])
    def save(self, key, result):
        with self.db:
            self.db.execute("UPDATE operations SET result=? WHERE key=?", (json.dumps(result), key))
        return result
    def get(self, key):
        row = self.db.execute("SELECT result FROM operations WHERE key=?", (key,)).fetchone()
        if not row: raise ValueError("Unknown operation_id")
        return json.loads(row[0])

class Platform:
    def __init__(self, base_url=None, robot_id=None, journal=None, client=None, stop_sender=None):
        self.url = base_url or os.environ.get("ALPHA_PLATFORM_URL", "http://127.0.0.1:5050")
        parsed = urlsplit(self.url)
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.scheme != "http" or parsed.username or parsed.password or parsed.path not in {"", "/"}:
            raise ValueError("Alpha development adapter requires a loopback HTTP platform URL")
        self.robot = robot_id or os.environ.get("ROBOT_ID", "robot-001")
        identifier(self.robot)
        self.prefix = f"/api/v1/robots/{self.robot}"
        self.client = client or httpx.AsyncClient(base_url=self.url, timeout=6, follow_redirects=False, trust_env=False)
        self.journal = journal or Journal(str(ROOT / "third_party/RobotPilot/alpha-mcp/.runtime/operations.sqlite3"))
        self.stop_sender = stop_sender or self._send_stop
    async def request(self, method, path, body=None, key=None):
        headers = {"X-Request-ID": key or str(uuid.uuid4())}
        if key: headers["Idempotency-Key"] = key
        response = await self.client.request(method, path, json=body, headers=headers)
        response.raise_for_status()
        return response.json()
    async def authorize_motion(self):
        auth = await self.request("GET", "/api/auth/status")
        if auth.get("robot_id") != self.robot or auth.get("mode") != "open" or auth.get("isLocalNetwork") is not True:
            raise PermissionError("Agent execution currently requires the existing loopback open development mode")
        if auth.get("robot_mode") != "simulation" or os.environ.get("ALPHA_ALLOW_MOTION") != "simulation":
            raise PermissionError("Motion tools require ALPHA_ALLOW_MOTION=simulation and a simulation backend; hardware is not enabled")
    async def get_robot_status(self):
        return await self.request("GET", self.prefix + "/status")
    async def list_navigation_locations(self):
        state = await self.get_robot_status()
        current = state.get("current_map", {})
        if current.get("stale") or not current.get("map_id") or not current.get("map_version_id"):
            return {"locations": [], "status": "unknown", "reason": "Current map identity unavailable"}
        data = await self.request("GET", self.prefix + "/waypoints?map_id=" + quote(current["map_id"], safe=""))
        return {"map_id": current["map_id"], "map_version_id": current["map_version_id"], "locations": [
            {k: item.get(k) for k in ("waypoint_id", "name", "x", "y", "yaw", "revision")}
            for item in data.get("waypoints", []) if item.get("enabled") and item.get("map_version_id") == current["map_version_id"]]}
    async def navigate_to_location(self, location, idempotency_key):
        await self.authorize_motion()
        if not isinstance(location, str) or not 1 <= len(location) <= 100:
            raise ValueError("Location must be an existing name of at most 100 characters")
        fresh, result = self.journal.reserve(idempotency_key, {"type": "navigate", "robot": self.robot, "location": location})
        if not fresh: return await self.get_task_status(operation_id=idempotency_key)
        submitted = False
        try:
            state = await self.get_robot_status()
            if not state.get("autonomy_ready"):
                raise ValueError("Navigation blocked: " + "; ".join(state.get("readiness_blockers", ["robot not ready"])))
            catalog = await self.list_navigation_locations()
            matches = [item for item in catalog["locations"] if item["name"] == location]
            if len(matches) != 1: raise ValueError("Location is not an enabled, uniquely named point on the current map")
            point = matches[0]
            if not all(isinstance(point[k], (int, float)) and math.isfinite(point[k]) for k in ("x", "y", "yaw")):
                raise ValueError("Saved location pose is invalid")
            digest = hashlib.sha256((self.robot + ":" + idempotency_key).encode()).hexdigest()[:32]
            mission_id = "agent-" + digest
            result.update(mission_id=mission_id, target=location)
            self.journal.save(idempotency_key, result)
            mission = {"id": mission_id, "name": "RoboAgent → " + location, "map_id": catalog["map_id"],
                "map_version_id": catalog["map_version_id"], "steps": [{"id": "navigate", "type": "waypoint",
                "waypoint_id": point["waypoint_id"], "waypointName": location,
                "pose": {"x": point["x"], "y": point["y"], "z": math.sin(point["yaw"]/2), "w": math.cos(point["yaw"]/2)}}]}
            submitted = True
            saved = await self.request("POST", self.prefix + "/missions", mission, "agent-save-" + digest)
            if saved.get("status") != "accepted":
                result.update(command_id=saved.get("command_id"), message="Mission save is not yet confirmed; no start command was sent")
                return self.journal.save(idempotency_key, result)
            started = await self.request("POST", self.prefix + "/tasks", {"mission_id": mission_id}, "agent-start-" + digest)
            result.update(status=started.get("status", "unknown"), task_id=started.get("task_id"),
                command_id=started.get("command_id"), message="Task submission result; accepted is not arrival")
        except ValueError as error:
            result.update(status="unknown" if submitted else "rejected", message=str(error))
        except httpx.HTTPStatusError as error:
            result.update(status="rejected" if error.response.status_code in {400,401,403,404,409} else "unknown",
                          message="Robot API rejected the request" if error.response.status_code < 500 else "Robot API outcome unknown; do not resubmit")
        except (httpx.HTTPError, OSError):
            result.update(status="unknown", message="Transport interrupted; do not issue a replacement navigation until reconciled")
        return self.journal.save(idempotency_key, result)
    async def get_task_status(self, task_id=None, operation_id=None):
        try:
            return await self._get_task_status(task_id, operation_id)
        except (httpx.HTTPError, OSError, json.JSONDecodeError):
            result = self.journal.get(operation_id) if operation_id else {"task_id": task_id}
            return {**result, "status": "unknown", "completed": False, "verified": False,
                    "message": "Robot state unavailable; reconcile before any replacement command"}
    async def _get_task_status(self, task_id=None, operation_id=None):
        result = self.journal.get(operation_id) if operation_id else {"task_id": task_id}
        task_id = result.get("task_id") or task_id
        if not task_id and result.get("command_id"):
            command = await self.request("GET", self.prefix + "/commands/" + identifier(result["command_id"]))
            command_result = command.get("result", command)
            task_id = command_result.get("task_id")
        if not task_id and result.get("mission_id"):
            tasks = await self.request("GET", self.prefix + "/tasks")
            match = next((item for item in [tasks.get("current")] + tasks.get("history", []) if item and item.get("mission_id") == result["mission_id"]), None)
            task_id = match.get("task_id") if match else None
        if not task_id:
            if result.get("type") == "stop" and result.get("request_id"):
                state = (await self.get_robot_status()).get("software_stop", {})
                if state.get("request_id") == result["request_id"] and not state.get("stale", True):
                    result.update(status="confirmed" if state.get("active") is True and state.get("result") == "confirmed" and state.get("durable") else "unknown", software_stop=state)
            return {**result, "completed": False, "verified": False}
        try:
            task = await self.request("GET", self.prefix + "/tasks/" + identifier(task_id))
            state = await self.get_robot_status()
        except httpx.HTTPError:
            return {**result, "task_id": task_id, "status": "unknown", "completed": False, "verified": False}
        status = str(task.get("status", "unknown")).lower()
        steps = task.get("steps", [])
        evidence = task.get("navigation_evidence", [])
        verified = bool(steps) and all(any(e.get("task_id") == task_id and e.get("step_index") == index
            and e.get("verified") is True and e.get("source") == "nav_status"
            and e.get("map_version_id") == task.get("map_version_id") and e.get("map_id") == task.get("map_id")
            and e.get("attempt") == task.get("attempt") and e.get("target") == step.get("pose")
            for e in evidence) for index, step in enumerate(steps) if step.get("type") == "waypoint")
        verified = verified and any(step.get("type") == "waypoint" for step in steps)
        verified = verified and status == "succeeded" and not state.get("task_stale", True)
        output = {**result, "task_id": task_id, "mission_id": task.get("mission_id"), "status": status,
            "completed": status == "succeeded" and verified, "verified": verified,
            "reason": task.get("reason"), "events": task.get("events", [])[-20:], "evidence": evidence,
            "message": "Mission succeeded without verified arrival evidence" if status == "succeeded" and not verified else "Robot-side task status"}
        if operation_id: self.journal.save(operation_id, output)
        return output
    async def cancel_navigation(self, task_id, idempotency_key):
        await self.authorize_motion()
        fresh, result = self.journal.reserve(idempotency_key, {"type": "cancel", "robot": self.robot, "task_id": task_id})
        if not fresh: return result
        try:
            reply = await self.request("POST", self.prefix + "/tasks/" + identifier(task_id) + "/commands", {"action": "cancel"}, idempotency_key)
            result.update(task_id=task_id, command_id=reply.get("command_id"), status=reply.get("status", "unknown"),
                          message="Cancellation requested; query task status. This is not proof of a stationary robot.")
        except httpx.HTTPError:
            result.update(status="unknown", message="Cancellation outcome unknown; query task before any retry")
        return self.journal.save(idempotency_key, result)
    async def request_software_stop(self, idempotency_key):
        await self.authorize_motion()
        fresh, result = self.journal.reserve(idempotency_key, {"type": "stop", "robot": self.robot})
        if not fresh: return result
        request_id = str(uuid.uuid5(uuid.NAMESPACE_URL, self.robot + ":stop:" + idempotency_key))
        try:
            state = await self.stop_sender(request_id)
            confirmed = state.get("request_id") == request_id and state.get("active") is True and state.get("result") == "confirmed" and state.get("durable") is True
            result.update(status="confirmed" if confirmed else "unknown", software_stop=state,
                          request_id=request_id, stationary_verified=False,
                          message="Software stop latch feedback; not a physical emergency stop or proof of stationary motion")
        except (OSError, TimeoutError, WebSocketException, json.JSONDecodeError):
            result.update(status="unknown", request_id=request_id, message="Stop request outcome unknown; inspect robot feedback")
        return self.journal.save(idempotency_key, result)
    async def _send_stop(self, request_id):
        async with connect(os.environ.get("ALPHA_ROSBRIDGE_URL", "ws://127.0.0.1:9090"), open_timeout=3) as ws:
            await ws.send(json.dumps({"op": "subscribe", "topic": "/safety/software_stop/state", "type": "std_msgs/msg/String"}))
            await ws.send(json.dumps({"op": "advertise", "topic": "/safety/software_stop/request", "type": "std_msgs/msg/String"}))
            await ws.send(json.dumps({"op": "publish", "topic": "/safety/software_stop/request", "msg": {"data": json.dumps({"action": "request_stop", "request_id": request_id})}}))
            async def feedback():
                async for raw in ws:
                    data = json.loads(raw)
                    if data.get("topic") == "/safety/software_stop/state":
                        state = json.loads(data["msg"]["data"])
                        if state.get("request_id") == request_id: return state
            return await asyncio.wait_for(feedback(), timeout=4)
        return {}
