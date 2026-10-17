"""Robot-side sequential mission executor and JSON rosbridge interface."""

import json
import math
import os
import re
import signal
import time
import uuid
from datetime import datetime, timezone

import rclpy
from diagnostic_msgs.msg import DiagnosticArray
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from nav_status.msg import NavigationExecution as NavigationStatus
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool, String

from .store import MissionStore, utc_now
from .scheduler import next_run_at, parse_utc


NAV_TIMEOUT = 600.0
DOCK_TIMEOUT = 120.0
ACTIVE = ("RUNNING", "PAUSED")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def validated_mission(raw):
    if not isinstance(raw, dict):
        raise ValueError("mission must be an object")
    mission_id = str(raw.get("id", "")).strip()
    name = str(raw.get("name", "")).strip()
    steps = raw.get("steps")
    if not mission_id or len(mission_id) > 100 or not name or len(name) > 120:
        raise ValueError("mission id/name is missing or too long")
    if not isinstance(steps, list) or len(steps) > 200:
        raise ValueError("mission steps must be a list of at most 200 items")
    result = []
    active_waypoint_id = None
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError(f"step {index + 1} must be an object")
        kind = step.get("type")
        item = {"id": str(step.get("id") or uuid.uuid4()), "type": kind}
        if kind == "waypoint":
            pose = step.get("pose")
            if not isinstance(pose, dict):
                raise ValueError(f"step {index + 1} has no waypoint pose")
            values = {key: float(pose.get(key, default)) for key, default in
                      (("x", None), ("y", None), ("z", 0), ("w", 1))}
            if not all(math.isfinite(value) for value in values.values()):
                raise ValueError(f"step {index + 1} has an invalid pose")
            if abs(values["z"] ** 2 + values["w"] ** 2 - 1) > 0.1:
                raise ValueError(f"step {index + 1} has an invalid orientation")
            item.update(pose=values, waypointId=step.get("waypointId"),
                        waypointName=str(step.get("waypointName", ""))[:120],
                        waypoint_id=step.get("waypoint_id", step.get("waypointId")))
        elif kind == "wait":
            seconds = float(step.get("seconds", 0))
            if not math.isfinite(seconds) or seconds <= 0 or seconds > 86400:
                raise ValueError(f"step {index + 1} has invalid wait seconds")
            item["seconds"] = seconds
            if "waypoint_id" in step:
                waypoint_id = step["waypoint_id"]
                if not isinstance(waypoint_id, str) or not 1 <= len(waypoint_id.strip()) <= 128:
                    raise ValueError(f"step {index + 1} has invalid waypoint_id")
                item["waypoint_id"] = waypoint_id.strip()
        elif kind == "inspection_action":
            action = step.get("action")
            if action not in ("capture", "detect", "broadcast"):
                raise ValueError(f"step {index + 1} has an unsupported inspection action")
            timeout_ms = step.get("timeout_ms", 15000)
            if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or not 100 <= timeout_ms <= 120000:
                raise ValueError(f"step {index + 1} has an invalid inspection timeout")
            detector_types = step.get("detector_types", [])
            asset_ids = step.get("asset_ids", [])
            parameters = step.get("parameters", {})
            if (not isinstance(detector_types, list) or len(detector_types) > 20
                    or any(not isinstance(value, str) or not value or len(value) > 64 for value in detector_types)):
                raise ValueError(f"step {index + 1} has invalid detector types")
            if (not isinstance(asset_ids, list) or len(asset_ids) > 100
                    or any(not isinstance(value, str) or not value or len(value) > 128 for value in asset_ids)):
                raise ValueError(f"step {index + 1} has invalid asset ids")
            if not isinstance(parameters, dict) or len(json.dumps(parameters, allow_nan=False)) > 4096:
                raise ValueError(f"step {index + 1} has invalid parameters")
            if action == "detect" and not detector_types:
                raise ValueError(f"step {index + 1} needs at least one detector type")
            item.update(action=action, timeout_ms=timeout_ms,
                        detector_types=detector_types, asset_ids=asset_ids,
                        parameters=parameters)
            if "waypoint_id" in step:
                waypoint_id = step["waypoint_id"]
                if not isinstance(waypoint_id, str) or not 1 <= len(waypoint_id.strip()) <= 128:
                    raise ValueError(f"step {index + 1} has invalid waypoint_id")
                item["waypoint_id"] = waypoint_id.strip()
        elif kind not in ("home", "dock", "undock"):
            raise ValueError(f"step {index + 1} has unknown type")
        if kind == "waypoint":
            active_waypoint_id = item.get("waypoint_id")
        elif kind in ("wait", "inspection_action"):
            if "waypoint_id" in item and item["waypoint_id"] != active_waypoint_id:
                raise ValueError(f"step {index + 1} waypoint_id does not match its waypoint")
        else:
            active_waypoint_id = None
        result.append(item)
    map_id = raw.get("map_id")
    map_version_id = raw.get("map_version_id")
    if map_id is not None and (not isinstance(map_id, str) or not map_id.strip() or len(map_id) > 128):
        raise ValueError("mission map_id is invalid")
    if map_version_id is not None and (
        not isinstance(map_version_id, str) or not map_version_id.strip() or len(map_version_id) > 128
    ):
        raise ValueError("mission map_version_id is invalid")
    if (map_id is None) != (map_version_id is None):
        raise ValueError("mission map_id and map_version_id must be provided together")
    return {
        "id": mission_id, "name": name, "steps": result,
        "map_id": map_id.strip() if map_id else None,
        "map_version_id": map_version_id.strip() if map_version_id else None,
    }


def mission_database_path():
    """Resolve MissionStore from explicit configuration or the ROS data root."""
    configured = os.environ.get("ROBOTPILOT_MISSION_DB") or os.environ.get(
        "OPENAMR_MISSION_DB"
    )
    if configured:
        return os.path.expanduser(configured)
    default_ros_home = os.path.join(os.path.expanduser("~"), ".ros")
    ros_home = os.environ.get("ROS_HOME", default_ros_home)
    return os.path.join(os.path.expanduser(ros_home), "ackermann_missions.sqlite3")


class MissionManager(Node):
    def __init__(self):
        super().__init__("mission_manager")
        default_db = mission_database_path()
        self.declare_parameter("database_path", default_db)
        self.robot_id = os.environ.get("ROBOT_ID", "robot-001")
        self.store = MissionStore(self.get_parameter("database_path").value, self.robot_id)
        self.run = self.store.latest_run()
        self.active_request_id = None
        self.navigation_execution_id = None
        self.pose = None
        self.pose_received_at = None
        self.ekf_odom_received_at = None
        self.deadline = None
        self.step_started = None
        self.nav_seen_active = False
        self.navigation_result = None
        self.rule_replan_pending_at = None
        self.goal_sent_ns = None
        self.linear_speed = None
        self.linear_speed_received_at = None
        self.action_status = None
        self.inspection_capabilities = None
        self.inspection_capabilities_seen = 0.0
        self.inspection_heartbeat_seen = 0.0
        self.inspection_provider_observed_at = None
        self.action_request_pub = self.create_publisher(String, "/inspection/action/request", 10)
        self.action_control_pub = self.create_publisher(String, "/inspection/action/control", 10)
        self.create_subscription(
            String, "/inspection/provider/capabilities", self.on_inspection_capabilities,
            QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                       durability=DurabilityPolicy.TRANSIENT_LOCAL),
        )
        self.create_subscription(String, "/inspection/provider/heartbeat",
                                 self.on_inspection_provider_heartbeat, 10)
        self.create_subscription(String, "/inspection/action/result", self.on_inspection_result, 10)
        self.create_subscription(String, "/inspection/action/status", self.on_inspection_status, 10)
        self.owned_goals = set()
        self.last_wait_persist = 0.0
        self.stop_owned = False
        self.software_stop_state = None
        self.software_stop_received_at = None
        self.map_identity = None
        self.map_identity_received_at = None
        self.map_bundle = None
        self.map_bundle_received_at = None
        self.fault_candidates = {}
        self.battery_state = None
        self.battery_received_at = None
        self.area_control = None
        self.area_control_received_at = None
        self.heartbeat_seq = 0
        self.last_sent_seq = 0
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.state_pub = self.create_publisher(String, "/mission/state", qos)
        self.ack_pub = self.create_publisher(String, "/mission/ack", 10)
        self.outbox_pub = self.create_publisher(String, "/robot/events/outbox", 10)
        self.heartbeat_pub = self.create_publisher(String, "/robot/heartbeat", 10)
        self.goal_pub = self.create_publisher(PoseStamped, "/goal_pose", 10)
        self.hold_pub = self.create_publisher(Bool, "/mission/hold", 10)
        self.dock_pub = self.create_publisher(Bool, "/dock_trigger", 10)
        self.undock_pub = self.create_publisher(Bool, "/undock_robot", 10)
        self.create_subscription(String, "/mission/command", self.on_command, 10)
        self.create_subscription(String, "/robot/events/ack", self.on_outbox_ack, 10)
        self.create_subscription(
            String, "/safety/software_stop/state", self.on_software_stop_state, 10
        )
        self.create_subscription(String, "/ackermann/routes/catalog", self.on_route_catalog, 10)
        self.create_subscription(String, "/localization/map_bundle", self.on_map_bundle, 10)
        self.create_subscription(DiagnosticArray, "/diagnostics", self.on_diagnostics, 10)
        self.create_subscription(String, "/battery/state", self.on_battery_state, 10)
        self.create_subscription(String, "/area_rules/control", self.on_area_control, 10)
        self.create_subscription(NavigationStatus, "/navigation/execution_state", self.on_nav, 10)
        self.create_subscription(PoseStamped, "/goal_pose", self.on_goal, 10)
        self.create_subscription(String, "/dock_trigger_status", self.on_dock, 10)
        self.create_subscription(Odometry, "/liorf_localization/mapping/odometry", self.on_odom, 10)
        self.create_subscription(Odometry, "/odometry/filtered", self.on_ekf_odom, 10)
        self.create_timer(0.2, self.tick)
        self.create_timer(2.0, self.publish_state)
        self.create_timer(5.0, self.publish_outbox)
        self.create_timer(2.0, self.publish_heartbeat)
        self.store.recover_claimed_schedules(self.robot_id)
        self.create_timer(1.0, self.scheduler_tick)
        if self.run and (self.run["status"] in ACTIVE or self.run["hold_active"]):
            self._stop_motion()
            if self.run["status"] == "RUNNING":
                self._transition("PAUSED", "mission manager restarted; resume required")
        self.publish_heartbeat()
        self.publish_state()

    def _event(self, reason):
        self.store.add_event(self.run["task_id"], self.run["status"],
                             self.run["step_index"], reason, self.pose,
                             request_id=(
                                 self.active_request_id
                                 or self.run.get("origin_request_id")
                             ))

    def _transition(self, status, reason, **fields):
        self.run = self.store.update_run(
            self.run["task_id"], status=status, reason=reason,
            event_reason=reason, event_pose=self.pose,
            event_request_id=(self.active_request_id or self.run.get("origin_request_id")),
            **fields,
        )
        self.publish_state()

    def publish_outbox(self):
        events = self.store.pending_events(limit=100)
        if events:
            self.last_sent_seq = events[-1]["source_seq"]
            self.outbox_pub.publish(String(data=json.dumps({
                "schema_version": 1, "robot_id": self.robot_id, "events": events,
            }, separators=(",", ":"))))

    def publish_heartbeat(self):
        self.heartbeat_seq += 1
        self.heartbeat_pub.publish(String(data=json.dumps({
            "schema_version": 1, "robot_id": self.robot_id,
            "source": "mission_manager", "heartbeat_seq": self.heartbeat_seq,
            "observed_at": utc_now(),
            "robot_mode": os.environ.get("ROBOT_MODE", "unknown"),
            "network_transport": "simulated" if os.environ.get("ROBOT_MODE") == "simulation" else "unknown",
            "status": "online",
        }, separators=(",", ":"))))

    def on_outbox_ack(self, message):
        try:
            ack = json.loads(message.data)
            if ack.get("schema_version") != 1 or ack.get("robot_id") != self.robot_id:
                return
            if (isinstance(ack.get("through_seq"), bool)
                    or not isinstance(ack.get("through_seq"), int)
                    or ack["through_seq"] > self.last_sent_seq):
                return
            self.store.acknowledge_events(ack.get("through_seq"))
        except (ValueError, TypeError, AttributeError, json.JSONDecodeError):
            return

    def on_diagnostics(self, message):
        now = time.monotonic()
        for item in message.status:
            if not item.name or len(item.name) > 256:
                continue
            level = item.level[0] if isinstance(item.level, (bytes, bytearray)) else int(item.level)
            if level not in (0, 1, 2, 3):
                continue
            # robot_localization's topic frequency diagnostic can report no
            # events while its actual filtered odometry is arriving. Trust the
            # observed stream only for this exact contradictory diagnostic.
            if (item.name == "ekf_filter_node: odometry/filtered topic status"
                    and item.message == "No events recorded."
                    and self.ekf_odom_received_at is not None
                    and now - self.ekf_odom_received_at < 2.0):
                level = 0
            if level == 0:
                self.fault_candidates.pop(item.name, None)
                self.store.observe_fault(item.name, 0, item.message)
                continue
            candidate = self.fault_candidates.get(item.name)
            if candidate is None or candidate[0:2] != (level, item.message) or now - candidate[2] > 5:
                self.fault_candidates[item.name] = (level, item.message, now)
                continue
            if now - candidate[2] >= 3:
                self.store.observe_fault(item.name, level, item.message)

    def _stop_motion(self):
        self.hold_pub.publish(Bool(data=True))
        self.stop_owned = True
        if self.run and not self.run["hold_active"]:
            self.run = self.store.update_run(self.run["task_id"], hold_active=True)

    def _release_motion(self):
        if self.stop_owned:
            self.hold_pub.publish(Bool(data=False))
            self.stop_owned = False
            if self.run and self.run["hold_active"]:
                self.run = self.store.update_run(self.run["task_id"], hold_active=False)

    def on_software_stop_state(self, message):
        try:
            state = json.loads(message.data)
        except (json.JSONDecodeError, TypeError, AttributeError):
            return
        if not isinstance(state, dict) or not isinstance(state.get("active"), bool):
            return
        self.software_stop_state = state
        self.software_stop_received_at = time.monotonic()
        # Clearing /stop only releases the command-velocity latch. A paused
        # mission is resumed exclusively by an explicit operator command.

    def on_battery_state(self, message):
        try:
            state = json.loads(message.data)
        except (json.JSONDecodeError, TypeError, AttributeError):
            return
        if not isinstance(state, dict) or not isinstance(state.get("available"), bool):
            return
        self.battery_state = state
        self.battery_received_at = time.monotonic()

    def on_area_control(self, message):
        try:
            state = json.loads(message.data)
        except (json.JSONDecodeError, TypeError, AttributeError):
            return
        if not isinstance(state, dict) or not isinstance(state.get("ready"), bool) or not isinstance(state.get("stop"), bool):
            return
        self.area_control = state
        self.area_control_received_at = time.monotonic()

    def motion_guard_block_reason(self):
        if (
            self.software_stop_state is None
            or self.software_stop_received_at is None
            or time.monotonic() - self.software_stop_received_at > 3.0
        ):
            return "software stop state is unavailable or stale"
        if self.software_stop_state.get("result") != "confirmed":
            return "software stop state is not confirmed"
        if not self.software_stop_state.get("durable", False):
            return "software stop state is not durable"
        if self.software_stop_state["active"]:
            return "software stop is active"
        if (
            self.battery_state is None
            or self.battery_received_at is None
            or time.monotonic() - self.battery_received_at > 5.0
        ):
            return "battery state is unavailable or stale"
        if not self.battery_state["available"]:
            return "battery is unavailable"
        if (os.environ.get("ROBOT_MODE") == "hardware"
                and (self.battery_state.get("simulated") is True
                     or self.battery_state.get("source") == "simulated")):
            return "simulated battery cannot authorize hardware motion"
        if self.battery_state.get("low_battery") is not False:
            return "battery is low or its charge level is unknown"
        if self.battery_state.get("charging") is not False:
            return "battery is charging or charge state is unknown"
        if self.area_control_received_at is not None:
            if time.monotonic() - self.area_control_received_at > 3.0:
                return "area control is stale"
            if not self.area_control["ready"] or self.area_control["stop"]:
                return "area control blocks motion"
        if self.store.active_critical_faults():
            return "critical diagnostics are active"
        if self.store.outbox_status()["capacity_warning"]:
            return "robot event outbox is above the safe capacity threshold"
        if (
            self.pose is None
            or self.pose_received_at is None
            or time.monotonic() - self.pose_received_at > 3.0
        ):
            return "localization pose is unavailable or stale"
        return ""

    def on_route_catalog(self, message):
        try:
            active = json.loads(message.data).get("active_files", {})
        except (json.JSONDecodeError, TypeError, AttributeError):
            return
        map_id = active.get("map_id")
        map_version_id = active.get("map_version_id") or map_id
        if not isinstance(map_id, str) or not map_id or map_id == "Null":
            return
        if not isinstance(map_version_id, str) or not map_version_id:
            return
        self.map_identity = {"map_id": map_id, "map_version_id": map_version_id}
        self.map_identity_received_at = time.monotonic()

    def on_map_bundle(self, message):
        try:
            bundle = json.loads(message.data)
        except (json.JSONDecodeError, TypeError, AttributeError):
            return
        if (not isinstance(bundle, dict) or bundle.get("schema_version") != 1
                or not isinstance(bundle.get("ready"), bool)):
            return
        self.map_bundle = bundle
        self.map_bundle_received_at = time.monotonic()

    def map_binding_block_reason(self, map_id, map_version_id):
        if (self.map_bundle is None or self.map_bundle_received_at is None
                or time.monotonic() - self.map_bundle_received_at > 5.0
                or not self.map_bundle.get("ready")):
            return "2D/3D map bundle is unavailable or unverified"
        if (
            not self.map_identity
            or self.map_identity_received_at is None
            or time.monotonic() - self.map_identity_received_at > 30.0
        ):
            return "current 2D map identity is unavailable or stale"
        if not map_id or not map_version_id:
            return "mission has no bound map identity"
        if map_id != self.map_identity["map_id"]:
            return "mission map_id does not match the current 2D map"
        if map_version_id != self.map_identity["map_version_id"]:
            return "mission map_version_id does not match the current 2D map version"
        if (self.map_bundle.get("map_id") != self.map_identity["map_id"]
                or self.map_bundle.get("map_version_id") != self.map_identity["map_version_id"]
                or not self.map_bundle.get("bundle_id")
                or not self.map_bundle.get("globalmap_pcd_sha256")):
            return "active 2D and LIORF 3D maps do not match the verified bundle"
        return ""

    def publish_state(self):
        run = dict(self.run) if self.run else None
        if run:
            run["events"] = self.store.events(run["task_id"])
            run["missionId"] = run["mission_id"]
            run["stepIndex"] = run["step_index"]
            run["taskId"] = run["task_id"]
            run["status"] = run["status"].lower()
            if run["steps"] and run["step_index"] < len(run["steps"]):
                active_step = run["steps"][run["step_index"]]
                if active_step.get("type") == "inspection_action":
                    run["active_action"] = {
                        "action_run_id": getattr(self, "action_run_id", None),
                        "step_id": active_step["id"], "status": self.action_status or "QUEUED",
                        "kind": active_step["action"],
                    }
        history = self.store.recent_runs(10)
        for item in history:
            item["events"] = self.store.events(item["task_id"], limit=50)
        provider = self.inspection_provider_snapshot()
        payload = {"schema_version": 1, "online": True, "server_time": utc_now(),
                   "missions": self.store.missions(), "run": run,
                   "inspection_provider": provider,
                   "event_sync": self.store.outbox_status(),
                   "history": history, "schedules": self.store.schedules(self.robot_id),
                   "schedule_runs": self.store.schedule_runs(self.robot_id, limit=500)}
        self.state_pub.publish(String(data=json.dumps(payload)))

    def _validated_schedule(self, raw, *, created_by, schedule_id=None):
        if not isinstance(raw, dict):
            raise ValueError("schedule must be an object")
        name = str(raw.get("name", "")).strip()
        mission_id = str(raw.get("mission_id", "")).strip()
        if not name or len(name) > 120:
            raise ValueError("schedule name is missing or too long")
        mission = self.store.mission(mission_id)
        if not mission or not mission.get("steps"):
            raise ValueError("schedule mission is missing or has no steps")
        recurrence = raw.get("recurrence")
        timezone_name = raw.get("timezone")
        local_time = raw.get("local_time")
        start_date = raw.get("start_date")
        weekdays = raw.get("weekdays", [])
        enabled = raw.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("schedule enabled must be a boolean")
        if not isinstance(weekdays, list):
            raise ValueError("schedule weekdays must be a list")
        now = datetime.now(timezone.utc)
        next_run = (
            next_run_at(now, recurrence, timezone_name, local_time, start_date, weekdays)
            if enabled else None
        )
        if enabled and next_run is None:
            raise ValueError("schedule has no future run time")
        return {
            "schedule_id": schedule_id or str(raw.get("schedule_id") or uuid.uuid4()),
            "name": name,
            "mission_id": mission_id,
            "recurrence": recurrence,
            "timezone": timezone_name,
            "local_time": local_time,
            "start_date": start_date,
            "weekdays": weekdays,
            "enabled": enabled,
            "next_run_at": next_run,
            "created_by": created_by,
        }

    def scheduler_tick(self):
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        for schedule in self.store.due_schedules(self.robot_id, now_iso):
            scheduled_for = schedule["next_run_at"]
            following = next_run_at(
                now, schedule["recurrence"], schedule["timezone"], schedule["local_time"],
                schedule.get("start_date"), schedule.get("weekdays"),
            )
            if not self.store.claim_schedule_run(
                self.robot_id, schedule["schedule_id"], scheduled_for, following,
            ):
                continue
            lag = (now - parse_utc(scheduled_for)).total_seconds()
            if lag > 60:
                self.store.finish_schedule_run(
                    self.robot_id, schedule["schedule_id"], scheduled_for,
                    "skipped", "misfire exceeded 60 seconds",
                )
                self.publish_state()
                continue
            reason = self.motion_guard_block_reason()
            mission = self.store.mission(schedule["mission_id"])
            if reason:
                status = "skipped"
            elif self.run and self.run["status"] in ACTIVE:
                reason, status = "another mission is active", "skipped"
            elif not mission:
                reason, status = "scheduled mission no longer exists", "rejected"
            else:
                reason = self.map_binding_block_reason(
                    mission.get("map_id"), mission.get("map_version_id")
                )
                status = "skipped" if reason else "started"
            task_id = None
            if not reason:
                try:
                    task_id = self._start_mission(schedule["mission_id"])
                except ValueError as exc:
                    reason, status = str(exc), "rejected"
            self.store.finish_schedule_run(
                self.robot_id, schedule["schedule_id"], scheduled_for,
                status, reason, task_id,
            )
            self.publish_state()

    def _start_mission(self, mission_id, origin_request_id=None):
        if self.run and self.run["status"] in ACTIVE:
            raise ValueError("a mission is already active")
        mission = self.store.mission(str(mission_id))
        if not mission or not mission["steps"]:
            raise ValueError("mission is missing or has no steps")
        block_reason = self.motion_guard_block_reason()
        if block_reason:
            raise ValueError(block_reason)
        block_reason = self.map_binding_block_reason(
            mission.get("map_id"), mission.get("map_version_id")
        )
        if block_reason:
            raise ValueError(block_reason)
        block_reason = self.inspection_mission_block_reason(mission)
        if block_reason:
            raise ValueError(block_reason)
        self.run = self.store.new_run(
            str(uuid.uuid4()), mission, origin_request_id=origin_request_id,
            robot_pose=self.pose, record_start_event=True,
        )
        self._release_motion()
        self.owned_goals.clear()
        self._begin_step()
        return self.run["task_id"]

    def on_command(self, message):
        request_id = None
        origin_request_id = None
        reserved_request_id = None
        try:
            command = json.loads(message.data)
            if not isinstance(command, dict):
                raise ValueError("command must be an object")
            request_id = command.get("request_id")
            action = command.get("command")
            if action != "query" and request_id is not None:
                if not isinstance(request_id, str) or not REQUEST_ID_RE.fullmatch(request_id):
                    raise ValueError("request_id is invalid")
                is_new, prior_ack = self.store.reserve_command(request_id, command)
                if not is_new:
                    ack = prior_ack or {
                        "request_id": request_id, "ok": False,
                        "error": "command result is unknown after interruption; inspect robot state",
                        "status": "unknown",
                    }
                    self.ack_pub.publish(String(data=json.dumps(ack)))
                    return
                reserved_request_id = request_id
            candidate_origin = command.get("origin_request_id")
            if isinstance(candidate_origin, str) and REQUEST_ID_RE.fullmatch(candidate_origin):
                origin_request_id = candidate_origin
            self.active_request_id = origin_request_id
            if action in {"start", "resume", "retry", "skip", "release_hold"}:
                block_reason = self.motion_guard_block_reason()
                if block_reason:
                    raise ValueError(block_reason)
            if action == "save":
                mission = validated_mission(command.get("mission"))
                if mission.get("map_id") is not None:
                    block_reason = self.map_binding_block_reason(
                        mission.get("map_id"), mission.get("map_version_id")
                    )
                    if block_reason:
                        raise ValueError(block_reason)
                self.store.save_mission(mission)
            elif action == "delete":
                mission_id = str(command.get("mission_id", ""))
                if not self.store.delete_mission(mission_id):
                    raise ValueError("unknown mission")
            elif action == "start":
                self._start_mission(
                    str(command.get("mission_id", "")), origin_request_id
                )
            elif action == "schedule.save":
                schedule_id = command.get("schedule_id")
                existing = self.store.schedule(self.robot_id, schedule_id) if schedule_id else None
                expected_revision = command.get("expected_revision")
                if existing and expected_revision != existing["revision"]:
                    raise ValueError("schedule revision changed")
                schedule = self._validated_schedule(
                    command.get("schedule"),
                    created_by=str(command.get("created_by") or "operator"),
                    schedule_id=schedule_id,
                )
                if existing:
                    result_schedule = self.store.update_schedule(
                        self.robot_id, schedule_id, schedule, expected_revision
                    )
                    if result_schedule is None:
                        raise ValueError("schedule revision changed")
                else:
                    result_schedule = self.store.create_schedule(self.robot_id, schedule)
                command["_schedule_id"] = result_schedule["schedule_id"]
            elif action == "schedule.delete":
                schedule_id = str(command.get("schedule_id", ""))
                expected_revision = command.get("expected_revision")
                existing = self.store.schedule(self.robot_id, schedule_id)
                if not existing:
                    raise ValueError("unknown schedule")
                if expected_revision != existing["revision"]:
                    raise ValueError("schedule revision changed")
                if not self.store.delete_schedule(self.robot_id, schedule_id, expected_revision):
                    raise ValueError("schedule revision changed")
            elif action in ("pause", "resume", "cancel", "retry", "skip", "release_hold"):
                self._control(action, command)
            elif action != "query":
                raise ValueError("unknown command")
            self.publish_state()
            ack = {
                "request_id": request_id,
                "origin_request_id": origin_request_id,
                "ok": True,
            }
            if action == "start":
                ack["task_id"] = self.run["task_id"]
            if action == "schedule.save":
                ack["schedule_id"] = command["_schedule_id"]
            if reserved_request_id:
                self.store.finish_command(reserved_request_id, ack)
            self.ack_pub.publish(String(data=json.dumps(ack)))
        except (ValueError, TypeError, KeyError, OverflowError, json.JSONDecodeError) as exc:
            ack = {"request_id": request_id, "origin_request_id": origin_request_id,
                   "ok": False, "error": str(exc)}
            if reserved_request_id:
                self.store.finish_command(reserved_request_id, ack)
            self.ack_pub.publish(String(data=json.dumps(ack)))
        finally:
            self.active_request_id = None

    def _control(self, action, command):
        if not self.run or command.get("task_id") != self.run["task_id"]:
            raise ValueError("unknown or stale task_id")
        status = self.run["status"]
        if action in ("resume", "retry", "skip"):
            block_reason = self.map_binding_block_reason(
                self.run.get("map_id"), self.run.get("map_version_id")
            )
            if block_reason:
                raise ValueError(block_reason)
        if action == "pause" and status == "RUNNING":
            if self._kind() == "inspection_action":
                self.publish_action_control("pause")
            remaining = (max(0.0, self.deadline - time.monotonic())
                         if self.deadline and self._kind() in ("wait", "inspection_action") else 0.0)
            self._stop_motion()
            self.deadline = None
            self._transition("PAUSED", "paused by operator", remaining_seconds=remaining)
        elif action == "resume" and status == "PAUSED":
            self._release_motion()
            self._transition("RUNNING", "resumed by operator")
            self._begin_step(resume=True)
        elif action == "cancel" and status in ACTIVE:
            if self._kind() == "inspection_action":
                self.publish_action_control("cancel")
                queued_result = self.store.inspection_result(self._current_action_run_id())
                if queued_result is not None:
                    self.store.record_late_inspection_result(queued_result)
            self._stop_motion()
            self.deadline = None
            self._transition("CANCELLED", "cancelled by operator")
        elif action == "retry" and status == "FAILED":
            self._release_motion()
            self._transition("RUNNING", "retry requested", attempt=self.run["attempt"] + 1)
            self._begin_step()
        elif action == "skip" and status in ("RUNNING", "PAUSED", "FAILED"):
            was_paused = status == "PAUSED"
            self._stop_motion()
            self.deadline = None
            self._event("step skipped by operator")
            if self.run["step_index"] + 1 >= len(self.run["steps"]):
                self._transition("SUCCEEDED", "last step skipped")
            else:
                self._transition("PAUSED" if was_paused else "RUNNING", "next step",
                                 step_index=self.run["step_index"] + 1,
                                 remaining_seconds=0.0)
                if not was_paused:
                    self._release_motion()
                    self._begin_step()
        elif action == "release_hold" and status in ("SUCCEEDED", "FAILED", "CANCELLED") and self.run["hold_active"]:
            self._release_motion()
            self._event("drive hold released by operator")
        else:
            raise ValueError(f"cannot {action} a {status.lower()} task")

    def _kind(self):
        return self.run["steps"][self.run["step_index"]]["type"]

    def _arrival_waypoint(self):
        """Return the waypoint reached for the current contiguous business steps."""
        for index in range(self.run["step_index"] - 1, -1, -1):
            step = self.run["steps"][index]
            if step["type"] == "waypoint":
                return index, step.get("waypoint_id") or step.get("waypointId")
            if step["type"] not in ("wait", "inspection_action"):
                break
        return None, None

    def publish_action_control(self, action):
        action_run_id = self._current_action_run_id()
        if not action_run_id:
            return
        self.action_control_pub.publish(String(data=json.dumps({
            "schema_version": 1, "robot_id": self.robot_id,
            "task_id": self.run["task_id"], "step_id": self.run["steps"][self.run["step_index"]]["id"],
            "attempt": self.run["attempt"], "action_run_id": action_run_id,
            "command": action, "requested_at": utc_now(),
        }, allow_nan=False)))

    def _current_action_run_id(self):
        if not self.run or self._kind() != "inspection_action":
            return None
        step_id = self.run["steps"][self.run["step_index"]]["id"]
        action_run_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
            f"{self.robot_id}:{self.run['task_id']}:{step_id}:{self.run['attempt']}"))
        return action_run_id if self.store.inspection_request(action_run_id) else None

    def _begin_step(self, resume=False):
        step = self.run["steps"][self.run["step_index"]]
        kind = step["type"]
        self.step_started = time.monotonic()
        self.nav_seen_active = False
        self.goal_sent_ns = None
        self._event(f"step {self.run['step_index'] + 1} started: {kind}")
        if kind == "wait":
            seconds = self.run["remaining_seconds"] if resume else step["seconds"]
            self.deadline = time.monotonic() + seconds
            self.last_wait_persist = 0.0
            self.run = self.store.update_run(self.run["task_id"], remaining_seconds=seconds)
        elif kind in ("waypoint", "home"):
            pose = step["pose"] if kind == "waypoint" else {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
            goal = PoseStamped()
            goal.header.frame_id = "map"
            goal.header.stamp = self.get_clock().now().to_msg()
            self.goal_sent_ns = goal.header.stamp.sec * 1000000000 + goal.header.stamp.nanosec
            self.navigation_execution_id = f"{goal.header.stamp.sec}:{goal.header.stamp.nanosec}"
            self.navigation_result = None
            goal.pose.position.x = pose["x"]
            goal.pose.position.y = pose["y"]
            goal.pose.orientation.z = pose["z"]
            goal.pose.orientation.w = pose["w"]
            self.owned_goals.add(self._goal_key(goal))
            self.deadline = time.monotonic() + NAV_TIMEOUT
            self.goal_pub.publish(goal)
        elif kind == "inspection_action":
            step_id = step["id"]
            action_run_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
                f"{self.robot_id}:{self.run['task_id']}:{step_id}:{self.run['attempt']}"))
            self.action_run_id = action_run_id
            self.action_step_id = step_id
            if resume:
                queued_result = self.store.inspection_result(action_run_id)
                if queued_result is not None:
                    self._apply_inspection_result(queued_result)
                    return
            reason = self.inspection_start_block_reason()
            if reason:
                self._fail(f"inspection action blocked: {reason}")
                return
            request = self.store.inspection_request(action_run_id)
            if request is None:
                request = {
                    "schema_version": 1, "action_run_id": action_run_id,
                    "robot_id": self.robot_id, "mission_id": self.run["mission_id"],
                    "task_id": self.run["task_id"], "step_id": step_id,
                    "attempt": self.run["attempt"], "map_id": self.run.get("map_id"),
                    "map_version_id": self.run.get("map_version_id"),
                    "waypoint_id": self._arrival_waypoint()[1],
                    "asset_ids": step["asset_ids"],
                    "kind": step["action"], "detector_types": step["detector_types"],
                    "parameters": step["parameters"], "requested_at": utc_now(),
                    "timeout_ms": step["timeout_ms"],
                    "source_mode": os.environ.get("ROBOT_MODE", "unknown"),
                }
                self.store.save_inspection_request(request)
            if resume and self.run["remaining_seconds"] > 0:
                remaining = self.run["remaining_seconds"]
            elif resume:
                requested_at = datetime.fromisoformat(request["requested_at"].replace("Z", "+00:00"))
                remaining = max(0.0, request["timeout_ms"] / 1000.0
                                - (datetime.now(timezone.utc) - requested_at).total_seconds())
            else:
                remaining = request["timeout_ms"] / 1000.0
            self.deadline = time.monotonic() + max(0.0, remaining)
            self.action_status = "DISPATCHED"
            self.action_request_pub.publish(String(data=json.dumps(request, allow_nan=False)))
            if resume:
                self.publish_action_control("resume")
        else:
            self.deadline = time.monotonic() + DOCK_TIMEOUT
            (self.dock_pub if kind == "dock" else self.undock_pub).publish(Bool(data=True))
        self.publish_state()

    def _complete_step(self):
        if self._kind() in ("waypoint", "home"):
            if not self.navigation_result:
                return
            # Persist the authority's observations; never rejudge navigation.
            self.store.record_navigation_evidence({
                **self.navigation_result,
                "task_id": self.run["task_id"], "step_index": self.run["step_index"],
                "attempt": self.run["attempt"], "map_id": self.run.get("map_id"),
                "map_version_id": self.run.get("map_version_id"), "recorded_at": utc_now(),
            })
        self._event(f"step {self.run['step_index'] + 1} completed")
        self.deadline = None
        arrival_index = (self.run["step_index"] if self._kind() == "waypoint"
                         else self.run["arrival_step_index"])
        if self.run["step_index"] + 1 >= len(self.run["steps"]):
            self._transition("SUCCEEDED", "all steps completed", remaining_seconds=0.0,
                             arrival_step_index=arrival_index)
            return
        self._transition("RUNNING", "next step", step_index=self.run["step_index"] + 1,
                         remaining_seconds=0.0, arrival_step_index=arrival_index)
        self._begin_step()

    def _fail(self, reason):
        self._stop_motion()
        self.deadline = None
        self._transition("FAILED", reason)

    def tick(self):
        if not self.run or self.run["status"] != "RUNNING" or self.deadline is None:
            return
        guard_reason = self.motion_guard_block_reason() or self.map_binding_block_reason(
            self.run.get("map_id"), self.run.get("map_version_id")
        )
        if guard_reason:
            remaining = (max(0.0, self.deadline - time.monotonic())
                         if self._kind() in ("wait", "inspection_action") else 0.0)
            if self._kind() == "inspection_action":
                self.publish_action_control("pause")
            self._stop_motion()
            self.deadline = None
            self._transition("PAUSED", f"safety guard: {guard_reason}",
                             remaining_seconds=remaining)
            return
        if self.rule_replan_pending_at is not None and self._kind() in ("waypoint", "home"):
            now = time.monotonic()
            self.deadline += max(0.0, now - self.rule_replan_pending_at)
            self.rule_replan_pending_at = now
            return
        if self._kind() in ("waypoint", "home") and self.navigation_result:
            self._complete_step()
            return
        if self._kind() == "wait" and time.monotonic() - self.last_wait_persist >= 1.0:
            self.run = self.store.update_run(
                self.run["task_id"], remaining_seconds=max(0.0, self.deadline - time.monotonic()))
            self.last_wait_persist = time.monotonic()
        if time.monotonic() >= self.deadline:
            if self._kind() == "wait":
                self._complete_step()
            else:
                self._fail(f"{self._kind()} timed out")

    def on_goal(self, message):
        if not self.run or self.run["status"] != "RUNNING" or self.deadline is None:
            return
        if self._goal_key(message) not in self.owned_goals:
            self._fail("external navigation goal interrupted mission")

    @staticmethod
    def _goal_key(message):
        p = message.pose
        s = message.header.stamp
        return (s.sec, s.nanosec, p.position.x, p.position.y,
                p.orientation.z, p.orientation.w)

    def on_nav(self, message):
        if not self.run or self.run["status"] != "RUNNING" or self.deadline is None or self._kind() not in ("waypoint", "home"):
            return
        stamp_ns = message.goal.header.stamp.sec * 1000000000 + message.goal.header.stamp.nanosec
        goal = message.goal.pose
        target = self._navigation_target()
        if (stamp_ns != self.goal_sent_ns or message.execution_id != self.navigation_execution_id
                or message.goal.header.frame_id != "map"
                or {"x": goal.position.x, "y": goal.position.y,
                    "z": goal.orientation.z, "w": goal.orientation.w} != target):
            return
        if message.state in (NavigationStatus.PLANNING, NavigationStatus.MOVING):
            self.nav_seen_active = True
            if message.held:
                self.rule_replan_pending_at = self.rule_replan_pending_at or time.monotonic()
            else:
                self.rule_replan_pending_at = None
        elif self.nav_seen_active and message.state == NavigationStatus.ARRIVED:
            try:
                result = json.loads(message.result_json)
            except (ValueError, TypeError):
                return
            if (not isinstance(result, dict) or result.get("source") != "nav_status"
                    or result.get("policy_version") != 1 or result.get("verified") is not True
                    or result.get("execution_id") != self.navigation_execution_id
                    or result.get("goal_stamp_ns") != self.goal_sent_ns
                    or result.get("path_stamp_ns") != message.path_stamp.sec * 1000000000 + message.path_stamp.nanosec
                    or result.get("target") != target):
                return
            self.navigation_result = result
            self.rule_replan_pending_at = None
        elif message.state == NavigationStatus.FAILED:
            self._fail(message.detail or "navigation failed")

    def on_dock(self, message):
        if not self.run or self.run["status"] != "RUNNING" or self.deadline is None or self._kind() not in ("dock", "undock"):
            return
        status = message.data.lower()
        if status == ("docked" if self._kind() == "dock" else "idle"):
            self._complete_step()
        elif status == "failed":
            self._fail("dock controller reported failure")

    def _navigation_target(self):
        step = self.run["steps"][self.run["step_index"]]
        return step["pose"] if step["type"] == "waypoint" else {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}

    def on_odom(self, message):
        p = message.pose.pose
        values = {"x": p.position.x, "y": p.position.y,
                  "z": p.orientation.z, "w": p.orientation.w}
        if (
            all(math.isfinite(value) for value in values.values())
            and abs(values["z"] ** 2 + values["w"] ** 2 - 1.0) <= 0.1
        ):
            self.pose = values
            self.pose_received_at = time.monotonic()

    def on_ekf_odom(self, message):
        twist = message.twist.twist
        speed = math.hypot(twist.linear.x, twist.linear.y)
        if (message.header.frame_id == "odom"
                and math.isfinite(message.pose.pose.position.x)
                and math.isfinite(message.pose.pose.position.y)
                and math.isfinite(speed)):
            self.ekf_odom_received_at = time.monotonic()
            self.linear_speed = speed
            self.linear_speed_received_at = self.ekf_odom_received_at

    def inspection_start_block_reason(self):
        now = time.monotonic()
        arrival_index, waypoint_id = self._arrival_waypoint()
        if arrival_index is None or self.run.get("arrival_step_index") != arrival_index:
            return "inspection actions must follow a waypoint arrival in the mission"
        configured_waypoint_id = self.run["steps"][self.run["step_index"]].get("waypoint_id")
        if configured_waypoint_id and configured_waypoint_id != waypoint_id:
            return "inspection action waypoint_id does not match the reached waypoint"
        if self.pose_received_at is None or now - self.pose_received_at > 1.0:
            return "localization pose is unavailable or stale"
        if self.linear_speed_received_at is None or now - self.linear_speed_received_at > 1.0:
            return "odometry speed is unavailable or stale"
        if self.linear_speed is None or self.linear_speed > 0.05:
            return "robot is not confirmed stationary"
        if self.map_binding_block_reason(self.run.get("map_id"), self.run.get("map_version_id")):
            return "map bundle identity is not current"
        block_reason = self.inspection_action_capability_block_reason(
            self.run["steps"][self.run["step_index"]]
        )
        if block_reason:
            return block_reason
        return ""

    def on_inspection_capabilities(self, message):
        try:
            value = json.loads(message.data)
            if (not isinstance(value, dict) or value.get("schema_version") != 1
                    or value.get("robot_id") != self.robot_id
                    or not isinstance(value.get("provider_id"), str) or not value["provider_id"]
                    or value.get("source_mode") not in ("fixture", "simulation", "hardware")
                    or value.get("online") is not True or not isinstance(value.get("actions"), list)):
                raise ValueError("capability identity is invalid")
            actions = {}
            for item in value["actions"]:
                if (not isinstance(item, dict) or item.get("kind") not in ("capture", "detect", "broadcast")
                        or not isinstance(item.get("supported"), bool)):
                    raise ValueError("capability action is invalid")
                detectors = item.get("detectors", [])
                if not isinstance(detectors, list) or any(not isinstance(v, str) or not v for v in detectors):
                    raise ValueError("capability detector list is invalid")
                actions[item["kind"]] = {
                    "kind": item["kind"], "supported": item["supported"],
                    "detectors": detectors,
                    "can_pause": item.get("can_pause") is True,
                    "can_cancel": item.get("can_cancel") is True,
                }
            observed_at = value.get("observed_at")
            if observed_at is not None:
                stamp = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError("capability observed_at needs timezone")
            self.inspection_capabilities = {
                "provider_id": value["provider_id"], "source_mode": value["source_mode"],
                "software_version": str(value.get("software_version", ""))[:128],
                "actions": list(actions.values()), "action_map": actions,
            }
            self.inspection_capabilities_seen = time.monotonic()
            self.inspection_provider_observed_at = observed_at
        except (ValueError, TypeError, AttributeError, KeyError, json.JSONDecodeError):
            self.inspection_capabilities = None
            self.inspection_capabilities_seen = 0.0
            self.inspection_heartbeat_seen = 0.0

    def on_inspection_provider_heartbeat(self, message):
        try:
            value = json.loads(message.data)
            capabilities = self.inspection_capabilities
            if (not isinstance(value, dict) or value.get("schema_version") != 1
                    or value.get("robot_id") != self.robot_id or not capabilities
                    or value.get("provider_id") != capabilities["provider_id"]
                    or value.get("source_mode") != capabilities["source_mode"]
                    or value.get("online") is not True):
                self.inspection_heartbeat_seen = 0.0
                return
            observed_at = value.get("observed_at")
            if not isinstance(observed_at, str) or datetime.fromisoformat(
                    observed_at.replace("Z", "+00:00")).tzinfo is None:
                self.inspection_heartbeat_seen = 0.0
                return
            self.inspection_heartbeat_seen = time.monotonic()
            self.inspection_provider_observed_at = observed_at
        except (ValueError, TypeError, AttributeError):
            self.inspection_heartbeat_seen = 0.0

    def inspection_provider_snapshot(self):
        capabilities = self.inspection_capabilities or {}
        capability_fresh = bool(capabilities)
        heartbeat_fresh = (self.inspection_heartbeat_seen > 0
                           and time.monotonic() - self.inspection_heartbeat_seen < 5.0)
        online = capability_fresh and heartbeat_fresh
        return {
            "online": online, "stale": not online,
            "provider_id": capabilities.get("provider_id"),
            "source_mode": capabilities.get("source_mode"),
            "software_version": capabilities.get("software_version"),
            "actions": capabilities.get("actions", []),
            "observed_at": self.inspection_provider_observed_at if online else None,
        }

    def inspection_action_capability_block_reason(self, step):
        provider = self.inspection_provider_snapshot()
        if not provider["online"]:
            return "inspection provider capability or heartbeat is unavailable or stale"
        robot_mode = os.environ.get("ROBOT_MODE", "unknown")
        if provider["source_mode"] == "fixture":
            if robot_mode != "simulation":
                return "fixture inspection provider is allowed in simulation mode only"
        elif provider["source_mode"] != robot_mode:
            return "inspection provider source mode does not match robot mode"
        action = self.inspection_capabilities["action_map"].get(step.get("action"))
        if not action or not action["supported"]:
            return f"inspection provider does not support {step.get('action')}"
        required_detectors = set(step.get("detector_types", []))
        if required_detectors and not required_detectors.issubset(set(action["detectors"])):
            return "inspection provider does not support all configured detector types"
        return ""

    def inspection_mission_block_reason(self, mission):
        for step in mission.get("steps", []):
            if step.get("type") == "inspection_action":
                reason = self.inspection_action_capability_block_reason(step)
                if reason:
                    return reason
        return ""

    def on_inspection_result(self, message):
        try:
            result = json.loads(message.data)
            if (not isinstance(result, dict) or result.get("schema_version") != 1
                    or result.get("robot_id") != self.robot_id):
                return
            allowed_fields = {"schema_version", "provider_id", "result_id", "robot_id", "mission_id",
                              "task_id", "step_id", "attempt", "action_run_id", "status", "outcome",
                              "detector_type", "confidence", "observed_at", "source_mode", "model_version",
                              "map_id", "map_version_id", "waypoint_id", "asset_ids", "position",
                              "classifications", "evidence", "fixture_scenario", "reason_code"}
            if set(result) - allowed_fields:
                return
            evidence = result.get("evidence", [])
            if (not isinstance(evidence, list) or len(evidence) > 20
                    or any(not isinstance(item, dict) or set(item) -
                           {"evidence_id", "media_type", "checksum", "size_bytes"} for item in evidence)):
                return
            for item in evidence:
                if (not isinstance(item.get("evidence_id"), str) or not item["evidence_id"]
                        or item.get("media_type") not in ("image/jpeg", "image/png", "image/webp", "video/mp4")
                        or not isinstance(item.get("checksum"), str)
                        or not re.fullmatch(r"[0-9a-fA-F]{64}", item["checksum"])
                        or isinstance(item.get("size_bytes"), bool)
                        or not isinstance(item.get("size_bytes"), int)
                        or not 0 <= item["size_bytes"] <= 100 * 1024 * 1024):
                    return
            if (not isinstance(result.get("result_id"), str) or not result["result_id"]
                    or not isinstance(result.get("action_run_id"), str)
                    or not isinstance(result.get("step_id"), str)
                    or not isinstance(result.get("task_id"), str)
                    or result.get("source_mode") not in ("fixture", "simulation", "hardware")
                    or result.get("status") not in ("SUCCEEDED", "FAILED", "UNAVAILABLE", "TIMEOUT")
                    or result.get("outcome") not in ("NORMAL", "ABNORMAL", "INCONCLUSIVE", "NOT_APPLICABLE")
                    or result.get("reason_code") not in (None, "PROVIDER_UNAVAILABLE", "PROVIDER_TIMEOUT", "PROVIDER_FAILED", "PROVIDER_REJECTED")
                    or not isinstance(result.get("mission_id"), str)
                    or not isinstance(result.get("map_id"), str)
                    or not isinstance(result.get("map_version_id"), str)
                    or not isinstance(result.get("observed_at"), str)):
                return
            attempt = result.get("attempt")
            if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
                return
            if result["status"] != "SUCCEEDED" and result["outcome"] != "NOT_APPLICABLE":
                return
            confidence = result.get("confidence")
            if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                                           or not math.isfinite(confidence) or not 0 <= confidence <= 1):
                return
            position = result.get("position")
            if position is not None and (not isinstance(position, dict)
                                         or set(position) - {"frame_id", "x", "y", "yaw", "observed_at"}):
                return
            classifications = result.get("classifications", [])
            if (not isinstance(classifications, list) or len(classifications) > 100
                    or any(not isinstance(item, dict) or set(item) -
                           {"detector_type", "label", "class_id", "value", "confidence"} for item in classifications)):
                return
            observed_at = datetime.fromisoformat(result["observed_at"].replace("Z", "+00:00"))
            if observed_at.tzinfo is None:
                return
            expected = self.run["steps"][self.run["step_index"]] if self.run and self.run.get("steps") else {}
            if (not self.run or self.run["status"] not in ACTIVE or expected.get("type") != "inspection_action"
                    or result.get("action_run_id") != self._current_action_run_id()):
                self.store.record_late_inspection_result(result)
                return
            if (result.get("task_id") != self.run["task_id"]
                    or result.get("step_id") != expected.get("id")
                    or result.get("attempt") != self.run["attempt"]):
                return
            if (not isinstance(result.get("result_id"), str) or not result["result_id"]
                    or result.get("source_mode") not in ("fixture", "simulation", "hardware")
                    or result.get("mission_id") != self.run["mission_id"]
                    or result.get("map_id") != self.run.get("map_id")
                    or result.get("map_version_id") != self.run.get("map_version_id")):
                return
            original_request = self.store.inspection_request(result["action_run_id"])
            if (not original_request
                    or result.get("waypoint_id") not in (None, original_request.get("waypoint_id"))
                    or result.get("asset_ids") not in (None, original_request.get("asset_ids"))):
                return
            result["waypoint_id"] = original_request.get("waypoint_id")
            result["asset_ids"] = original_request.get("asset_ids", [])
            if result["status"] != "SUCCEEDED" and result["outcome"] != "NOT_APPLICABLE":
                return
            self.store.save_inspection_result(result)
            if self.run["status"] == "PAUSED":
                self.action_status = "RESULT_READY"
                self.publish_state()
                return
            self._apply_inspection_result(result)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return

    def _apply_inspection_result(self, result):
        self.store.add_inspection_result(self.run, result, self.pose)
        self.deadline = None
        if result["status"] == "SUCCEEDED":
            self._complete_step()
        else:
            self._fail(f"inspection action {result['status'].lower()}")

    def on_inspection_status(self, message):
        try:
            status = json.loads(message.data)
            if (not isinstance(status, dict) or status.get("schema_version") != 1
                    or status.get("robot_id") != self.robot_id or not self.run
                    or self.run["status"] != "RUNNING" or self._kind() != "inspection_action"
                    or status.get("action_run_id") != self._current_action_run_id()
                    or status.get("task_id") != self.run["task_id"]
                    or status.get("step_id") != self.run["steps"][self.run["step_index"]]["id"]
                    or status.get("attempt") != self.run["attempt"]
                    or status.get("status") not in ("ACCEPTED", "RUNNING", "PAUSE_PENDING", "PAUSED", "CANCEL_PENDING")):
                return
            self.action_status = status["status"]
            self.publish_state()
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return

    def destroy_node(self):
        if self.run and self.run["status"] == "RUNNING":
            self._stop_motion()
            self._transition("PAUSED", "mission manager stopped; resume required")
        self.store.close()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = MissionManager()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
