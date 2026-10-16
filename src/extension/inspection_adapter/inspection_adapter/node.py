"""ROS 2 transport adapter; detection itself remains external."""

import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

from .contract import ACTION_KINDS, validate_capabilities, validate_request, validate_result


class InspectionAdapter(Node):
    def __init__(self):
        super().__init__("inspection_adapter")
        self.robot_id = os.environ.get("ROBOT_ID", "robot-001")
        self.mode = os.environ.get("INSPECTION_PROVIDER_MODE", "external")
        if self.mode not in ("external", "fixture"):
            raise ValueError("INSPECTION_PROVIDER_MODE must be external or fixture")
        self.capabilities = None
        self.capabilities_seen = 0.0
        self.heartbeat_seen = 0.0
        self.pending = {}
        self.pending_deadline = {}
        self.completed = set()
        self.result_cache = {}
        db_path = os.path.expanduser(os.environ.get(
            "INSPECTION_ADAPTER_DB",
            os.path.join(os.environ.get("ROS_HOME", os.path.expanduser("~/.ros")), "inspection_adapter.sqlite3"),
        ))
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), mode=0o700, exist_ok=True)
        self.db = sqlite3.connect(db_path, timeout=5)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS action_runs(action_run_id TEXT PRIMARY KEY,request_json TEXT NOT NULL,result_json TEXT,updated_at TEXT NOT NULL)")
        self.db.commit()
        for action_run_id, request_json in self.db.execute(
                "SELECT action_run_id,request_json FROM action_runs WHERE result_json IS NULL"):
            try:
                request = validate_request(request_json, self.robot_id)
            except (ValueError, TypeError, KeyError):
                self.get_logger().warning(f"ignored invalid persisted action {action_run_id}")
                continue
            self.pending[action_run_id] = request
            self.pending_deadline[action_run_id] = self._deadline_from_request(request)
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.result_pub = self.create_publisher(String, "/inspection/action/result", 10)
        self.status_pub = self.create_publisher(String, "/inspection/action/status", 10)
        self.provider_request_pub = self.create_publisher(String, "/inspection/provider/action/request", 10)
        self.provider_control_pub = self.create_publisher(String, "/inspection/provider/action/control", 10)
        self.capability_pub = self.create_publisher(String, "/inspection/provider/capabilities", qos)
        self.heartbeat_pub = self.create_publisher(String, "/inspection/provider/heartbeat", 10)
        self.create_subscription(String, "/inspection/provider/capabilities", self.on_capabilities, qos)
        self.create_subscription(String, "/inspection/provider/heartbeat", self.on_heartbeat, 10)
        self.create_subscription(String, "/inspection/action/request", self.on_request, 10)
        self.create_subscription(String, "/inspection/action/control", self.on_control, 10)
        self.create_subscription(String, "/inspection/provider/action/result", self.on_provider_result, 10)
        self.create_subscription(String, "/inspection/provider/action/status", self.on_provider_status, 10)
        self.create_timer(0.2, self.publish_fixture_capabilities)
        self.create_timer(0.2, self.publish_fixture_heartbeat)
        self.create_timer(0.1, self.flush_late_fixture)
        self.create_timer(0.1, self.expire_pending)
        self.delayed = []

    @staticmethod
    def _deadline_from_request(request):
        requested = datetime.fromisoformat(request["requested_at"].replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - requested).total_seconds()
        return time.monotonic() + max(0.0, request["timeout_ms"] / 1000.0 - elapsed)

    def publish_fixture_capabilities(self):
        if self.mode != "fixture":
            return
        payload = {"schema_version": 1, "robot_id": self.robot_id,
                   "provider_id": "fixture-provider", "software_version": "fixture-v1",
                   "source_mode": "fixture", "online": True,
                   "observed_at": datetime.now(timezone.utc).isoformat(),
                   "actions": [{"kind": kind, "supported": True,
                                "detectors": ["fire_smoke"] if kind == "detect" else [],
                                "can_pause": False, "can_cancel": False}
                               for kind in sorted(ACTION_KINDS)]}
        self.capability_pub.publish(String(data=json.dumps(payload)))
        self.capabilities = validate_capabilities(payload, self.robot_id)
        self.capabilities_seen = time.monotonic()

    def publish_fixture_heartbeat(self):
        if self.mode != "fixture":
            return
        self.heartbeat_seen = time.monotonic()
        self.heartbeat_pub.publish(String(data=json.dumps({
            "schema_version": 1, "robot_id": self.robot_id,
            "provider_id": "fixture-provider", "source_mode": "fixture",
            "online": True, "observed_at": datetime.now(timezone.utc).isoformat(),
        }, allow_nan=False)))

    def on_capabilities(self, message):
        if self.mode == "fixture":
            return
        try:
            self.capabilities = validate_capabilities(message.data, self.robot_id)
            self.capabilities_seen = time.monotonic()
        except (ValueError, TypeError, KeyError):
            self.capabilities = None

    def on_heartbeat(self, message):
        if self.mode == "fixture":
            return
        try:
            value = json.loads(message.data)
            if (value.get("schema_version") == 1 and value.get("robot_id") == self.robot_id
                    and value.get("provider_id") == (self.capabilities or {}).get("provider_id")
                    and isinstance(value.get("online"), bool) and value["online"]):
                self.heartbeat_seen = time.monotonic()
            else:
                self.heartbeat_seen = 0.0
        except (ValueError, TypeError, AttributeError):
            self.heartbeat_seen = 0.0

    def on_request(self, message):
        try:
            request = validate_request(message.data, self.robot_id)
        except (ValueError, TypeError, KeyError) as error:
            self.get_logger().warning(f"invalid inspection request: {error}")
            return
        action_run_id = request["action_run_id"]
        request_json = json.dumps(request, allow_nan=False, sort_keys=True, separators=(",", ":"))
        cached = self.db.execute("SELECT request_json,result_json FROM action_runs WHERE action_run_id=?",
                                 (action_run_id,)).fetchone()
        if cached and json.loads(cached[0]) != request:
            self.get_logger().error("action_run_id was reused with different request content")
            return
        if cached and cached[1]:
            self.result_pub.publish(String(data=cached[1]))
            return
        if action_run_id in self.completed or action_run_id in self.pending:
            if action_run_id in self.pending:
                self.publish_action_status(request, "ACCEPTED")
            return
        self.db.execute("INSERT INTO action_runs(action_run_id,request_json,updated_at) VALUES (?,?,?) ON CONFLICT(action_run_id) DO UPDATE SET request_json=excluded.request_json,updated_at=excluded.updated_at",
                        (action_run_id, request_json, datetime.now(timezone.utc).isoformat()))
        self.db.commit()
        if self.mode == "fixture":
            self.publish_action_status(request, "ACCEPTED")
            self.run_fixture(request)
            return
        action = (self.capabilities or {}).get("action_map", {}).get(request["kind"])
        online = bool(self.capabilities)
        heartbeat = self.heartbeat_seen and time.monotonic() - self.heartbeat_seen < 5
        if not online or not heartbeat or not action or not action.get("supported"):
            mode = request.get("source_mode")
            if mode in ("simulation", "hardware"):
                self.publish_unavailable(request)
            else:
                self.get_logger().error("inspection source mode is unknown; withholding result")
            return
        self.pending[action_run_id] = request
        self.pending_deadline[action_run_id] = self._deadline_from_request(request)
        self.provider_request_pub.publish(String(data=json.dumps(request, allow_nan=False)))
        self.publish_action_status(request, "ACCEPTED")

    def publish_action_status(self, request, status):
        self.status_pub.publish(String(data=json.dumps({
            "schema_version": 1, "robot_id": self.robot_id,
            "action_run_id": request["action_run_id"], "task_id": request["task_id"],
            "step_id": request["step_id"], "attempt": request["attempt"],
            "status": status, "observed_at": datetime.now(timezone.utc).isoformat(),
            "source_mode": "fixture" if self.mode == "fixture" else (self.capabilities or {}).get("source_mode"),
        }, allow_nan=False)))

    def on_control(self, message):
        try:
            control = json.loads(message.data)
            if (not isinstance(control, dict) or control.get("schema_version") != 1
                    or control.get("robot_id") != self.robot_id
                    or control.get("command") not in ("cancel", "pause", "resume")):
                return
            request = self.pending.get(control.get("action_run_id"))
            if not request or any(control.get(key) != request.get(key)
                                  for key in ("task_id", "step_id", "attempt")):
                return
            action = (self.capabilities or {}).get("action_map", {}).get(request["kind"], {})
            property_name = {"cancel": "can_cancel", "pause": "can_pause", "resume": "can_pause"}[control["command"]]
            if self.mode != "fixture" and action.get(property_name) is True:
                self.provider_control_pub.publish(String(data=json.dumps(control, allow_nan=False)))
                self.publish_action_status(request, "PAUSE_PENDING" if control["command"] == "pause" else "CANCEL_PENDING" if control["command"] == "cancel" else "RUNNING")
        except (ValueError, TypeError, AttributeError):
            return

    def expire_pending(self):
        now = time.monotonic()
        for action_run_id, deadline in list(self.pending_deadline.items()):
            if deadline > now:
                continue
            request = self.pending.pop(action_run_id, None)
            self.pending_deadline.pop(action_run_id, None)
            if not request:
                continue
            result = {"schema_version": 1, "result_id": str(uuid.uuid4()),
                      "robot_id": self.robot_id, "action_run_id": action_run_id,
                      "mission_id": request["mission_id"], "task_id": request["task_id"],
                      "step_id": request["step_id"], "attempt": request["attempt"],
                      "status": "TIMEOUT", "outcome": "NOT_APPLICABLE",
                      "source_mode": "fixture" if self.mode == "fixture" else request["source_mode"],
                      "observed_at": datetime.now(timezone.utc).isoformat(),
                      "map_id": request["map_id"], "map_version_id": request["map_version_id"],
                      "waypoint_id": request.get("waypoint_id"), "asset_ids": request.get("asset_ids", []),
                      "confidence": None, "evidence": [], "reason_code": "PROVIDER_TIMEOUT"}
            self.emit_result(result)

    def publish_unavailable(self, request):
        result = {"schema_version": 1, "result_id": str(uuid.uuid4()),
                  "robot_id": self.robot_id, "action_run_id": request["action_run_id"],
                  "mission_id": request["mission_id"], "task_id": request["task_id"],
                  "step_id": request["step_id"], "attempt": request["attempt"],
                  "status": "UNAVAILABLE", "outcome": "NOT_APPLICABLE",
                  "source_mode": "fixture" if self.mode == "fixture" else request.get("source_mode"),
                  "observed_at": datetime.now(timezone.utc).isoformat(),
                  "map_id": request["map_id"], "map_version_id": request["map_version_id"],
                  "waypoint_id": request.get("waypoint_id"), "asset_ids": request.get("asset_ids", []),
                  "confidence": None, "evidence": [], "reason_code": "PROVIDER_UNAVAILABLE"}
        self.emit_result(result)

    def run_fixture(self, request):
        scenario = os.environ.get("INSPECTION_FIXTURE_SCENARIO", "inconclusive")
        if scenario == "offline":
            self.publish_unavailable(request)
            return
        if scenario == "timeout":
            return
        outcomes = {"normal": "NORMAL", "abnormal": "ABNORMAL",
                    "inconclusive": "INCONCLUSIVE", "rejected": "NOT_APPLICABLE",
                    "late_result": "INCONCLUSIVE", "duplicate": "INCONCLUSIVE"}
        if scenario not in outcomes:
            scenario = "inconclusive"
        result = {"schema_version": 1, "result_id": f"fixture-{uuid.uuid4()}",
                  "robot_id": self.robot_id, "action_run_id": request["action_run_id"],
                  "mission_id": request["mission_id"], "task_id": request["task_id"],
                  "step_id": request["step_id"], "attempt": request["attempt"],
                  "status": "FAILED" if scenario == "rejected" else "SUCCEEDED",
                  "outcome": outcomes[scenario], "source_mode": "fixture",
                  "observed_at": datetime.now(timezone.utc).isoformat(),
                  "map_id": request["map_id"], "map_version_id": request["map_version_id"],
                  "waypoint_id": request.get("waypoint_id"), "asset_ids": request.get("asset_ids", []),
                  "detector_type": (request.get("detector_types") or [None])[0],
                  "confidence": None, "evidence": [], "fixture_scenario": scenario}
        if scenario == "late_result":
            self.delayed.append((time.monotonic() + request["timeout_ms"] / 1000.0 + 1, result))
        elif scenario == "duplicate":
            serialized = self.emit_result(result)
            self.result_pub.publish(String(data=serialized))
        else:
            self.emit_result(result)

    def emit_result(self, result):
        serialized = json.dumps(result, allow_nan=False, separators=(",", ":"))
        action_run_id = result["action_run_id"]
        self.db.execute("UPDATE action_runs SET result_json=?,updated_at=? WHERE action_run_id=?",
                        (serialized, datetime.now(timezone.utc).isoformat(), action_run_id))
        self.db.commit()
        self.result_cache[action_run_id] = serialized
        self.completed.add(action_run_id)
        self.result_pub.publish(String(data=serialized))
        return serialized

    def flush_late_fixture(self):
        now = time.monotonic()
        ready = [item for item in self.delayed if item[0] <= now]
        self.delayed = [item for item in self.delayed if item[0] > now]
        for _, result in ready:
            self.emit_result(result)

    def on_provider_result(self, message):
        try:
            raw = json.loads(message.data)
            request = self.pending.get(raw.get("action_run_id"))
            if not request:
                return
            result = validate_result(raw, request, self.robot_id)
            if result.get("source_mode") != request["source_mode"]:
                raise ValueError("provider result source_mode does not match the original request")
            self.pending.pop(result["action_run_id"], None)
            self.pending_deadline.pop(result["action_run_id"], None)
            self.emit_result(result)
        except (ValueError, TypeError, KeyError) as error:
            self.get_logger().warning(f"rejected provider result: {error}")

    def on_provider_status(self, message):
        try:
            status = json.loads(message.data)
            request = self.pending.get(status.get("action_run_id"))
            if not request or status.get("robot_id") != self.robot_id:
                return
            if any(status.get(key) != request.get(key) for key in ("task_id", "step_id", "attempt")):
                return
            if status.get("status") not in ("ACCEPTED", "RUNNING", "PAUSE_PENDING", "PAUSED", "CANCEL_PENDING"):
                return
            self.publish_action_status(request, status["status"])
        except (ValueError, TypeError, AttributeError):
            return


def main(args=None):
    rclpy.init(args=args)
    node = InspectionAdapter()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.db.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
