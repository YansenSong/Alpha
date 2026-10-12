"""Versioned robot API backed by the robot-side mission manager."""

import copy
import base64
import binascii
import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import rclpy
from diagnostic_msgs.msg import DiagnosticArray
from flask import Response, abort, g, jsonify, request, send_file, stream_with_context
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Float32, String
import yaml

try:
    from nav_status.msg import NavigationStatus
except ImportError:
    NavigationStatus = None

from .data_paths import setting
from .auth import COOKIE_NAME, require_role
from .build_info import get_build_info
from .log_maintenance import prune_expired_logs
from .route_tasks import list_saved_routes, route_mission
from .storage_monitor import storage_report
from .saved_map_editor import saved_map, rule_store_path

PLATFORM_SCHEMA_VERSION = 8

try:
    from ament_index_python.packages import get_package_share_directory
except ImportError:
    get_package_share_directory = None


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def inspection_alert_fingerprint(result, category):
    """Group an abnormality by its mapped object, never by category alone."""
    asset_ids = result.get("asset_ids") or []
    if asset_ids:
        target = {"asset_ids": sorted(set(asset_ids))}
    elif result.get("waypoint_id"):
        target = {"waypoint_id": result["waypoint_id"]}
    else:
        # Unknown locations must not merge unrelated observations.
        target = {"result_id": result["result_id"]}
    return json_hash({"category": category, "map_id": result["map_id"],
                      "map_version_id": result["map_version_id"], "target": target})


def inspection_alert_payload(row):
    """Expose alert metadata and only a validated map-frame location."""
    item = dict(row)
    details_json = item.pop("result_details_json", None)
    try:
        details = json.loads(details_json) if details_json else {}
    except (TypeError, ValueError):
        details = {}
    position = details.get("position") if isinstance(details, dict) else None
    valid_position = (
        isinstance(position, dict)
        and isinstance(position.get("frame_id"), str)
        and position["frame_id"].lstrip("/") == "map"
        and isinstance(position.get("x"), (int, float)) and not isinstance(position.get("x"), bool)
        and math.isfinite(position.get("x"))
        and isinstance(position.get("y"), (int, float)) and not isinstance(position.get("y"), bool)
        and math.isfinite(position.get("y"))
        and isinstance(details.get("map_id"), str) and details["map_id"]
        and isinstance(details.get("map_version_id"), str) and details["map_version_id"]
    )
    if valid_position:
        item.update({"map_id": details["map_id"], "map_version_id": details["map_version_id"],
                     "position": {key: position[key] for key in ("frame_id", "x", "y", "yaw", "observed_at")
                                  if key in position}})
    return item


def battery_config_payload(config):
    """Normalize the stored config row for the ROS battery node."""
    values = config.get("config", config)
    return {
        "low_battery_threshold": values["low_battery_threshold"],
        "config_version": config["version"],
    }


def autonomy_readiness(snapshot):
    blockers = []
    if not snapshot.get("mission_online"):
        blockers.append("MissionManager unavailable")
    if not snapshot.get("map_identity_online"):
        blockers.append("current 2D map identity unavailable or stale")
    bundle = snapshot.get("map_bundle")
    if (not snapshot.get("map_bundle_online") or not isinstance(bundle, dict)
            or not bundle.get("ready") or not bundle.get("bundle_id")
            or not bundle.get("globalmap_pcd_sha256")):
        blockers.append("2D/3D map bundle unavailable or unverified")
    elif (bundle.get("map_id") != (snapshot.get("map_identity") or {}).get("map_id")
          or bundle.get("map_version_id") != (snapshot.get("map_identity") or {}).get("map_version_id")):
        blockers.append("active 2D and LIORF 3D maps do not match")
    if not snapshot.get("pose_online"):
        blockers.append("localization pose unavailable or stale")
    stop = snapshot.get("software_stop_state")
    if not snapshot.get("software_stop_online") or not isinstance(stop, dict):
        blockers.append("software stop state unavailable or stale")
    elif stop.get("result") != "confirmed" or not stop.get("durable"):
        blockers.append("software stop state unconfirmed or not durable")
    elif stop.get("active"):
        blockers.append("software stop is active")
    battery = snapshot.get("battery_state")
    if not snapshot.get("battery_online") or not isinstance(battery, dict):
        blockers.append("battery state unavailable or stale")
    elif (os.environ.get("ROBOT_MODE") == "hardware"
          and (battery.get("simulated") is True or battery.get("source") == "simulated")):
        blockers.append("simulated battery cannot authorize hardware motion")
    elif battery.get("low_battery") is not False:
        blockers.append("battery low or charge level unknown")
    elif battery.get("charging") is not False:
        blockers.append("battery charging state is active or unknown")
    if snapshot.get("area_control_seen"):
        if not snapshot.get("area_control_online"):
            blockers.append("area control is stale")
        elif not snapshot.get("area_control", {}).get("ready") or snapshot["area_control"].get("stop"):
            blockers.append("area control blocks motion")
    if any(item.get("level", 0) >= 2 and time.monotonic() - item.get("last_seen", 0) < 5
           for item in snapshot.get("diagnostics", {}).values()):
        blockers.append("critical diagnostics are active")
    if (snapshot.get("mission") or {}).get("event_sync", {}).get("capacity_warning"):
        blockers.append("robot event outbox is above the safe capacity threshold")
    return {"ready": not blockers, "blockers": blockers}


def audit_api_response(
    response, store, request_id, identity, method, path, logger
):
    """Record a write request and preserve uncertain outcomes."""
    try:
        store.audit(
            request_id,
            identity.get("username", "anonymous"),
            identity.get("robot_id"),
            method,
            path,
            response.status_code,
        )
    except sqlite3.Error as error:
        logger.error(
            "Platform audit write failed for request %s: %s",
            request_id,
            error,
        )
        response.status_code = 503
        response.set_data(
            json.dumps({
                "code": "AUDIT_UNAVAILABLE",
                "message": (
                    "The operation may have completed. "
                    "Query its current state before retrying."
                ),
                "request_id": request_id,
                "status": "unknown",
            })
        )
        response.mimetype = "application/json"
        response.headers["X-Request-Id"] = request_id
    return response


class PlatformStore:
    """Audit, faults, and platform settings; mission execution stays in ROS."""

    def __init__(
        self,
        path,
        event_retention_count=None,
        event_retention_days=None,
        audit_retention_days=None,
    ):
        self.path = os.path.expanduser(path)
        self.event_retention_count = self._retention_value(
            event_retention_count, "EVENT_RETENTION_COUNT", 10000, minimum=1
        )
        self.event_retention_days = self._retention_value(
            event_retention_days, "EVENT_RETENTION_DAYS", 0, minimum=0
        )
        self.audit_retention_days = self._retention_value(
            audit_retention_days, "AUDIT_RETENTION_DAYS", 0, minimum=0
        )
        directory = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(directory, mode=0o700, exist_ok=True)
        if not os.path.exists(self.path):
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(descriptor)
            except FileExistsError:
                pass
        with self.connect() as db:
            current_schema = db.execute("PRAGMA user_version").fetchone()[0]
            if current_schema > PLATFORM_SCHEMA_VERSION:
                raise RuntimeError(
                    "Platform database schema is newer than this RobotPilot "
                    f"build ({current_schema} > {PLATFORM_SCHEMA_VERSION})."
                )
            os.chmod(self.path, 0o600)
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS commands (
                    command_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    body_hash TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    robot_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS faults (
                    fault_id TEXT PRIMARY KEY,
                    robot_id TEXT NOT NULL,
                    fault_code TEXT NOT NULL,
                    fault_source TEXT NOT NULL,
                    description TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    resolved_at TEXT,
                    acknowledged_by TEXT,
                    acknowledged_at TEXT,
                    cleared_at TEXT
                );
                CREATE INDEX IF NOT EXISTS faults_robot_time ON faults(robot_id, first_seen DESC);
                CREATE TABLE IF NOT EXISTS config_versions (
                    version INTEGER PRIMARY KEY AUTOINCREMENT,
                    config_json TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 0,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    robot_id TEXT,
                    method TEXT NOT NULL,
                    path TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    timestamp TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS audit_entries_time ON audit_entries(timestamp DESC);
                CREATE TABLE IF NOT EXISTS platform_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    robot_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS platform_events_robot_id ON platform_events(robot_id, id);
                CREATE TABLE IF NOT EXISTS robot_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    robot_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_seq INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    task_id TEXT,
                    request_id TEXT,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    ingested_at TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    UNIQUE(robot_id, source, source_seq)
                );
                CREATE INDEX IF NOT EXISTS robot_events_history
                    ON robot_events(robot_id, id DESC);
                CREATE INDEX IF NOT EXISTS robot_events_task
                    ON robot_events(robot_id, task_id, id DESC);
                CREATE INDEX IF NOT EXISTS robot_events_request
                    ON robot_events(robot_id, request_id, id DESC);
                CREATE TABLE IF NOT EXISTS assets (
                    robot_id TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    map_id TEXT,
                    map_version_id TEXT,
                    name TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (robot_id, asset_id)
                );
                CREATE INDEX IF NOT EXISTS assets_map ON assets(robot_id, map_id, map_version_id);
                CREATE TABLE IF NOT EXISTS inspection_results (
                    robot_id TEXT NOT NULL,
                    inspection_result_id TEXT NOT NULL,
                    asset_id TEXT,
                    mission_id TEXT,
                    task_id TEXT,
                    waypoint_id TEXT,
                    outcome TEXT NOT NULL,
                    source TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (robot_id, inspection_result_id)
                );
                CREATE INDEX IF NOT EXISTS inspection_results_task
                    ON inspection_results(robot_id, task_id, occurred_at DESC);
                CREATE TABLE IF NOT EXISTS inspection_result_assets (
                    robot_id TEXT NOT NULL,
                    inspection_result_id TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    PRIMARY KEY (robot_id, inspection_result_id, asset_id)
                );
                CREATE INDEX IF NOT EXISTS inspection_result_assets_asset
                    ON inspection_result_assets(robot_id, asset_id, inspection_result_id);
                CREATE TABLE IF NOT EXISTS event_evidence (
                    robot_id TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    event_id TEXT,
                    inspection_result_id TEXT,
                    media_type TEXT NOT NULL,
                    uri_or_path TEXT,
                    checksum TEXT,
                    available INTEGER NOT NULL DEFAULT 0,
                    recorded_at TEXT NOT NULL,
                    PRIMARY KEY (robot_id, evidence_id)
                );
                CREATE INDEX IF NOT EXISTS event_evidence_event
                    ON event_evidence(robot_id, event_id);
                CREATE TABLE IF NOT EXISTS inspection_alerts (
                    robot_id TEXT NOT NULL,
                    alert_id TEXT NOT NULL,
                    inspection_result_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'OPEN',
                    note TEXT NOT NULL DEFAULT '',
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    occurrence_count INTEGER NOT NULL DEFAULT 1,
                    revision INTEGER NOT NULL DEFAULT 1,
                    updated_by TEXT,
                    fingerprint TEXT,
                    episode INTEGER NOT NULL DEFAULT 1,
                    map_id TEXT,
                    map_version_id TEXT,
                    waypoint_id TEXT,
                    PRIMARY KEY (robot_id, alert_id)
                );
                CREATE INDEX IF NOT EXISTS inspection_alerts_recent
                    ON inspection_alerts(robot_id, last_seen DESC);
                CREATE TABLE IF NOT EXISTS waypoint_action_plans (
                    robot_id TEXT NOT NULL,
                    waypoint_id TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    actions_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (robot_id, waypoint_id)
                );
                CREATE TABLE IF NOT EXISTS asset_waypoints (
                    robot_id TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    waypoint_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    PRIMARY KEY (robot_id, asset_id, waypoint_id),
                    FOREIGN KEY (robot_id, asset_id) REFERENCES assets(robot_id, asset_id),
                    FOREIGN KEY (robot_id, waypoint_id) REFERENCES waypoints(robot_id, waypoint_id)
                );
                CREATE INDEX IF NOT EXISTS asset_waypoints_waypoint
                    ON asset_waypoints(robot_id, waypoint_id);
                CREATE TABLE IF NOT EXISTS device_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    robot_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    simulated INTEGER NOT NULL,
                    stale INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS device_snapshots_recent
                    ON device_snapshots(robot_id, device_id, id DESC);
                CREATE TABLE IF NOT EXISTS waypoints (
                    robot_id TEXT NOT NULL,
                    waypoint_id TEXT NOT NULL,
                    map_id TEXT NOT NULL,
                    map_version_id TEXT,
                    name TEXT NOT NULL,
                    x REAL NOT NULL,
                    y REAL NOT NULL,
                    yaw REAL NOT NULL,
                    action TEXT NOT NULL DEFAULT 'none',
                    perception_type TEXT,
                    point_type TEXT NOT NULL DEFAULT 'inspection',
                    source TEXT NOT NULL DEFAULT 'operator',
                    valid_from TEXT,
                    valid_until TEXT,
                    wait_time REAL NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (robot_id, waypoint_id),
                    UNIQUE (robot_id, map_id, name)
                );
                CREATE INDEX IF NOT EXISTS waypoints_robot_map ON waypoints(robot_id, map_id, name);
                CREATE TABLE IF NOT EXISTS map_metadata (
                    robot_id TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    map_name TEXT NOT NULL,
                    campus TEXT NOT NULL DEFAULT '',
                    building TEXT NOT NULL DEFAULT '',
                    floor TEXT NOT NULL DEFAULT '',
                    label TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    revision INTEGER NOT NULL DEFAULT 1,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (robot_id, group_name, map_name)
                );
                CREATE TABLE IF NOT EXISTS map_catalog_versions (
                    robot_id TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    map_name TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (robot_id, group_name, map_name, version_id),
                    UNIQUE (robot_id, group_name, map_name, checksum)
                );
            """)
            waypoint_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(waypoints)")
            }
            asset_columns = {row["name"] for row in db.execute("PRAGMA table_info(assets)")}
            if "revision" not in asset_columns:
                db.execute("ALTER TABLE assets ADD COLUMN revision INTEGER NOT NULL DEFAULT 1")
            alert_columns = {row["name"] for row in db.execute("PRAGMA table_info(inspection_alerts)")}
            for column, declaration in (
                ("fingerprint", "TEXT"), ("episode", "INTEGER NOT NULL DEFAULT 1"),
                ("map_id", "TEXT"), ("map_version_id", "TEXT"), ("waypoint_id", "TEXT"),
            ):
                if column not in alert_columns:
                    db.execute(f"ALTER TABLE inspection_alerts ADD COLUMN {column} {declaration}")
            if current_schema < 8:
                db.execute("""INSERT OR IGNORE INTO inspection_result_assets
                    (robot_id,inspection_result_id,asset_id)
                    SELECT robot_id,inspection_result_id,asset_id FROM inspection_results
                    WHERE asset_id IS NOT NULL AND asset_id != ''""")
                for row in db.execute("""SELECT robot_id,inspection_result_id,details_json
                    FROM inspection_results""").fetchall():
                    try:
                        result = json.loads(row["details_json"] or "{}")
                    except (TypeError, ValueError):
                        continue
                    asset_ids = result.get("asset_ids", []) if isinstance(result, dict) else []
                    if not isinstance(asset_ids, list):
                        continue
                    for asset_id in asset_ids:
                        if isinstance(asset_id, str) and 1 <= len(asset_id) <= 128:
                            db.execute("""INSERT OR IGNORE INTO inspection_result_assets
                                (robot_id,inspection_result_id,asset_id) VALUES (?,?,?)""",
                                (row["robot_id"], row["inspection_result_id"], asset_id),
                            )
                for row in db.execute("""SELECT a.robot_id,a.alert_id,a.category,r.details_json
                    FROM inspection_alerts a LEFT JOIN inspection_results r
                    ON r.robot_id=a.robot_id AND r.inspection_result_id=a.inspection_result_id
                    WHERE a.fingerprint IS NULL OR a.map_id IS NULL""").fetchall():
                    try:
                        result = json.loads(row["details_json"] or "{}")
                        fingerprint = inspection_alert_fingerprint(result, row["category"])
                    except (TypeError, ValueError, KeyError):
                        continue
                    db.execute("""UPDATE inspection_alerts SET fingerprint=?,map_id=?,
                        map_version_id=?,waypoint_id=? WHERE robot_id=? AND alert_id=?""",
                        (fingerprint, result["map_id"], result["map_version_id"],
                         result.get("waypoint_id"), row["robot_id"], row["alert_id"]),
                    )
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS inspection_alerts_episode
                ON inspection_alerts(robot_id,fingerprint,episode)
                WHERE fingerprint IS NOT NULL""")
            db.execute("""CREATE INDEX IF NOT EXISTS inspection_alerts_map_recent
                ON inspection_alerts(robot_id,map_id,map_version_id,last_seen DESC)""")
            for column, declaration in (
                ("point_type", "TEXT NOT NULL DEFAULT 'inspection'"),
                ("source", "TEXT NOT NULL DEFAULT 'operator'"),
                ("valid_from", "TEXT"),
                ("valid_until", "TEXT"),
            ):
                if column not in waypoint_columns:
                    db.execute(f"ALTER TABLE waypoints ADD COLUMN {column} {declaration}")
            if db.execute("SELECT COUNT(*) FROM config_versions").fetchone()[0] == 0:
                db.execute(
                    "INSERT INTO config_versions(config_json, active, actor, created_at) VALUES (?, 1, ?, ?)",
                    (json.dumps({"low_battery_threshold": 20}), "system", utc_now()),
                )
            db.execute(f"PRAGMA user_version = {PLATFORM_SCHEMA_VERSION}")
        self.schema_version = PLATFORM_SCHEMA_VERSION

    @staticmethod
    def _retention_value(value, name, default, minimum):
        raw = setting(name, str(default)) if value is None else value
        try:
            parsed = int(raw)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{name} must be an integer") from error
        if parsed < minimum:
            raise ValueError(f"{name} must be at least {minimum}")
        return parsed

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def audit(self, request_id, actor, robot_id, method, path, status_code):
        with self.connect() as db:
            db.execute(
                """INSERT INTO audit_entries(request_id, actor, robot_id, method, path,
                   status_code, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (request_id, actor, robot_id, method, path, status_code, utc_now()),
            )
            if self.audit_retention_days:
                cutoff = (
                    datetime.now(timezone.utc)
                    - timedelta(days=self.audit_retention_days)
                ).isoformat()
                db.execute(
                    "DELETE FROM audit_entries WHERE timestamp < ?", (cutoff,)
                )

    def audit_history(self, robot_id, *, limit=100, before=None, actor=None,
                      request_id=None, method=None, from_time=None, to_time=None):
        query = "SELECT * FROM audit_entries WHERE robot_id = ?"
        values = [robot_id]
        if before is not None:
            query += " AND id < ?"
            values.append(before)
        for column, value in (("actor", actor), ("request_id", request_id), ("method", method)):
            if value:
                query += f" AND {column} = ?"
                values.append(value)
        if from_time:
            query += " AND timestamp >= ?"
            values.append(from_time)
        if to_time:
            query += " AND timestamp <= ?"
            values.append(to_time)
        query += " ORDER BY id DESC LIMIT ?"
        values.append(max(1, min(int(limit), 200)))
        with self.connect() as db:
            return [dict(row) for row in db.execute(query, values)]

    def append_state_event(self, robot_id, payload):
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        fingerprint_payload = dict(payload)
        fingerprint_payload.pop("observed_at", None)
        fingerprint = hashlib.sha256(json.dumps(
            fingerprint_payload, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        with self.connect() as db:
            latest = db.execute(
                "SELECT fingerprint FROM platform_events WHERE robot_id = ? ORDER BY id DESC LIMIT 1",
                (robot_id,),
            ).fetchone()
            if latest and latest["fingerprint"] == fingerprint:
                return None
            return self._append_event(db, robot_id, "robot_state", payload, fingerprint)

    def _append_event(self, db, robot_id, event_type, payload, fingerprint=None):
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if fingerprint is None:
            fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
        cursor = db.execute(
            "INSERT INTO platform_events(robot_id, event_type, fingerprint, payload_json, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (robot_id, event_type, fingerprint, encoded, utc_now()),
        )
        if self.event_retention_days:
            cutoff = (
                datetime.now(timezone.utc)
                - timedelta(days=self.event_retention_days)
            ).isoformat()
            db.execute(
                "DELETE FROM platform_events WHERE robot_id = ? AND timestamp < ?",
                (robot_id, cutoff),
            )
        db.execute(
            "DELETE FROM platform_events WHERE robot_id = ? AND id NOT IN "
            "(SELECT id FROM platform_events WHERE robot_id = ? "
            "ORDER BY id DESC LIMIT ?)",
            (robot_id, robot_id, self.event_retention_count),
        )
        return cursor.lastrowid

    def events_after(self, robot_id, event_id=0):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT id, event_type, payload_json FROM platform_events "
                "WHERE robot_id = ? AND id > ? ORDER BY id ASC LIMIT 1000",
                (robot_id, event_id),
            )]

    def ingest_robot_events(self, robot_id, events):
        """Commit a bounded outbox batch before the bridge acknowledges it."""
        if not isinstance(events, list) or not 1 <= len(events) <= 100:
            raise ValueError("outbox batch must contain 1 to 100 events")
        prepared = []
        previous_seq = None
        batch_source = None
        for event in events:
            if not isinstance(event, dict) or event.get("schema_version") != 1:
                raise ValueError("unsupported robot event schema")
            event = copy.deepcopy(event)
            if event.get("robot_id") != robot_id:
                raise ValueError("robot event belongs to a different robot")
            seq = event.get("source_seq")
            if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
                raise ValueError("robot event source_seq is invalid")
            if previous_seq is not None and seq != previous_seq + 1:
                raise ValueError("robot event batch has a sequence gap")
            previous_seq = seq
            event_id = event.get("event_id")
            source = event.get("source")
            event_type = event.get("type")
            if event_type == "inspection.result":
                event["payload"] = self._sanitize_inspection_payload(event.get("payload"))
            occurred_at = event.get("occurred_at")
            if not isinstance(event_id, str) or not isinstance(source, str) or not isinstance(event_type, str):
                raise ValueError("robot event identity is invalid")
            if not event_id or len(event_id) > 128 or not source or len(source) > 64 or not event_type or len(event_type) > 128:
                raise ValueError("robot event identity is too long")
            if batch_source is None:
                batch_source = source
            elif source != batch_source:
                raise ValueError("robot event batch has mixed sources")
            correlation = event.get("correlation")
            if not isinstance(correlation, dict):
                raise ValueError("robot event correlation must be an object")
            for field in ("task_id", "request_id"):
                value = correlation.get(field)
                if value is not None and (not isinstance(value, str) or len(value) > 128):
                    raise ValueError(f"robot event {field} is invalid")
            if event.get("severity") not in ("INFO", "WARNING", "ERROR"):
                raise ValueError("robot event severity is invalid")
            try:
                timestamp = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
            except (AttributeError, ValueError):
                raise ValueError("robot event occurred_at must be RFC3339") from None
            if timestamp.tzinfo is None:
                raise ValueError("robot event occurred_at must include timezone")
            try:
                encoded = json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False)
            except (TypeError, ValueError):
                raise ValueError("robot event payload is invalid JSON") from None
            if len(encoded.encode("utf-8")) > 65536:
                raise ValueError("robot event exceeds 64 KiB")
            prepared.append((event_id, source, seq, event_type, occurred_at, encoded, event))
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            last_committed_seq = db.execute(
                "SELECT COALESCE(MAX(source_seq), 0) FROM robot_events WHERE robot_id = ? AND source = ?",
                (robot_id, prepared[0][1]),
            ).fetchone()[0]
            for event_id, source, seq, event_type, occurred_at, encoded, event in prepared:
                existing = db.execute(
                    """SELECT event_id, robot_id, source, source_seq, payload_json FROM robot_events
                       WHERE event_id = ? OR (robot_id = ? AND source = ? AND source_seq = ?)""",
                    (event_id, robot_id, source, seq),
                ).fetchone()
                if existing:
                    if ((existing["event_id"], existing["robot_id"], existing["source"], existing["source_seq"]) != (event_id, robot_id, source, seq)
                            or json.loads(existing["payload_json"]) != event):
                        raise ValueError("robot event identity conflicts with existing history")
                    continue
                if seq != last_committed_seq + 1:
                    raise ValueError("robot event batch has an uncommitted sequence gap")
                correlation = event["correlation"]
                db.execute(
                    """INSERT INTO robot_events(event_id, robot_id, source, source_seq,
                       event_type, severity, task_id, request_id, occurred_at,
                       payload_json, ingested_at, schema_version)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                    (event_id, robot_id, source, seq, event_type,
                     str(event.get("severity") or "INFO"),
                     correlation.get("task_id"), correlation.get("request_id"),
                     occurred_at, encoded, utc_now()),
                )
                self._append_event(db, robot_id, "robot_event", event)
                if event_type == "inspection.result":
                    self._ingest_inspection_result(db, robot_id, event)
                last_committed_seq = seq
        return prepared[-1][2]

    @staticmethod
    def _sanitize_inspection_payload(result):
        allowed = {"schema_version", "provider_id", "result_id", "robot_id", "mission_id", "task_id",
                   "step_id", "attempt", "action_run_id", "status", "outcome", "detector_type",
                   "confidence", "observed_at", "source_mode", "model_version", "map_id",
                   "map_version_id", "waypoint_id", "asset_ids", "position", "classifications",
                   "evidence", "fixture_scenario", "reason_code"}
        if not isinstance(result, dict) or set(result) - allowed:
            raise ValueError("inspection result contains unsupported fields")
        evidence = result.get("evidence", [])
        if not isinstance(evidence, list):
            raise ValueError("inspection evidence must be a list")
        evidence_fields = {"evidence_id", "media_type", "checksum", "size_bytes"}
        for item in evidence:
            if not isinstance(item, dict) or set(item) - evidence_fields:
                raise ValueError("inspection evidence may contain metadata only")
        position = result.get("position")
        if position is not None and (not isinstance(position, dict)
                                     or set(position) - {"frame_id", "x", "y", "yaw", "observed_at"}):
            raise ValueError("inspection position metadata is invalid")
        classifications = result.get("classifications", [])
        if not isinstance(classifications, list) or len(classifications) > 100:
            raise ValueError("inspection classifications are invalid")
        classification_fields = {"detector_type", "label", "class_id", "value", "confidence"}
        if any(not isinstance(item, dict) or set(item) - classification_fields for item in classifications):
            raise ValueError("inspection classifications contain unsupported fields")
        if result.get("reason_code") not in (None, "PROVIDER_UNAVAILABLE", "PROVIDER_TIMEOUT", "PROVIDER_FAILED", "PROVIDER_REJECTED"):
            raise ValueError("inspection reason_code is invalid")
        asset_ids = result.get("asset_ids", [])
        if (not isinstance(asset_ids, list) or len(asset_ids) > 100
                or any(not isinstance(value, str) or not 1 <= len(value) <= 128
                       for value in asset_ids)):
            raise ValueError("inspection asset_ids are invalid")
        waypoint_id = result.get("waypoint_id")
        if waypoint_id is not None and (not isinstance(waypoint_id, str)
                                        or not 1 <= len(waypoint_id) <= 128):
            raise ValueError("inspection waypoint_id is invalid")
        return result

    @staticmethod
    def _ingest_inspection_result(db, robot_id, event):
        result = PlatformStore._sanitize_inspection_payload(event.get("payload"))
        if not isinstance(result, dict):
            raise ValueError("inspection result payload must be an object")
        required = ("result_id", "action_run_id", "task_id", "step_id", "status",
                    "outcome", "source_mode", "observed_at", "map_id", "map_version_id")
        if any(not isinstance(result.get(key), str) or not result[key] for key in required):
            raise ValueError("inspection result identity is incomplete")
        if result["source_mode"] not in ("fixture", "simulation", "hardware"):
            raise ValueError("invalid inspection source_mode")
        if result["status"] not in ("SUCCEEDED", "FAILED", "UNAVAILABLE", "TIMEOUT"):
            raise ValueError("invalid inspection action status")
        if result["outcome"] not in ("NORMAL", "ABNORMAL", "INCONCLUSIVE", "NOT_APPLICABLE"):
            raise ValueError("invalid inspection outcome")
        if result["status"] != "SUCCEEDED" and result["outcome"] != "NOT_APPLICABLE":
            raise ValueError("failed actions cannot have a detection outcome")
        stamp = datetime.fromisoformat(result["observed_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("inspection observed_at needs timezone")
        confidence = result.get("confidence")
        if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (int, float))
                                       or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise ValueError("inspection confidence must be in [0,1] or null")
        if result.get("robot_id", robot_id) != robot_id or result["task_id"] != event["correlation"].get("task_id"):
            raise ValueError("inspection result correlation mismatch")
        evidence = result.get("evidence", [])
        if not isinstance(evidence, list) or len(evidence) > 20:
            raise ValueError("inspection evidence list is invalid")
        for item in evidence:
            if not isinstance(item, dict):
                raise ValueError("inspection evidence metadata is invalid")
            evidence_id = item.get("evidence_id")
            media_type = item.get("media_type")
            checksum = item.get("checksum")
            size_bytes = item.get("size_bytes")
            if (not isinstance(evidence_id, str) or not 1 <= len(evidence_id) <= 128
                    or media_type not in ("image/jpeg", "image/png", "image/webp", "video/mp4")
                    or not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", checksum)
                    or isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or not 0 <= size_bytes <= 100 * 1024 * 1024):
                raise ValueError("inspection evidence metadata is invalid")
        db.execute(
            """INSERT INTO inspection_results(robot_id,inspection_result_id,asset_id,mission_id,
               task_id,waypoint_id,outcome,source,occurred_at,details_json)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (robot_id, result["result_id"], (result.get("asset_ids") or [None])[0],
             result.get("mission_id"), result["task_id"], result.get("waypoint_id"),
             result["outcome"], result["source_mode"], result["observed_at"],
             json.dumps(result, allow_nan=False, separators=(",", ":"))),
        )
        for asset_id in set(result.get("asset_ids") or []):
            db.execute("""INSERT OR IGNORE INTO inspection_result_assets
                (robot_id,inspection_result_id,asset_id) VALUES (?,?,?)""",
                (robot_id, result["result_id"], asset_id),
            )
        for item in evidence:
            db.execute(
                """INSERT INTO event_evidence(robot_id,evidence_id,event_id,inspection_result_id,
                   media_type,uri_or_path,checksum,available,recorded_at) VALUES (?,?,?,?,?,?,?,0,?)""",
                (robot_id, item["evidence_id"], event["event_id"], result["result_id"],
                 item["media_type"], None, item["checksum"].lower(), result["observed_at"]),
            )
        if result["outcome"] == "ABNORMAL":
            category = result.get("detector_type") or "other"
            fingerprint = inspection_alert_fingerprint(result, category)
            latest = db.execute("""SELECT alert_id,episode,state FROM inspection_alerts
                WHERE robot_id=? AND fingerprint=? ORDER BY episode DESC LIMIT 1""",
                (robot_id, fingerprint),
            ).fetchone()
            if latest and latest["state"] not in ("RESOLVED", "CLOSED"):
                db.execute("""UPDATE inspection_alerts SET inspection_result_id=?,
                    last_seen=?,occurrence_count=occurrence_count+1,revision=revision+1
                    WHERE robot_id=? AND alert_id=?""",
                    (result["result_id"], result["observed_at"], robot_id, latest["alert_id"]),
                )
            else:
                episode = latest["episode"] + 1 if latest else 1
                alert_id = f"alert-{fingerprint[:32]}-{episode}"
                db.execute(
                    """INSERT INTO inspection_alerts(robot_id,alert_id,inspection_result_id,
                       category,severity,first_seen,last_seen,occurrence_count,fingerprint,
                       episode,map_id,map_version_id,waypoint_id)
                       VALUES (?,?,?,?,?,?,?,1,?,?,?,?,?)""",
                    (robot_id, alert_id, result["result_id"], category, "WARNING",
                     result["observed_at"], result["observed_at"], fingerprint,
                     episode, result["map_id"], result["map_version_id"],
                     result.get("waypoint_id")),
                )

    def robot_event_history(self, robot_id, *, limit=100, before=None,
                            event_type=None, severity=None, task_id=None,
                            request_id=None, from_time=None, to_time=None):
        limit = max(1, min(int(limit), 200))
        with self.connect() as db:
            query = "SELECT id, payload_json, ingested_at FROM robot_events WHERE robot_id = ?"
            values = [robot_id]
            if before is not None:
                query += " AND id < ?"
                values.append(before)
            for column, value in (("event_type", event_type), ("severity", severity),
                                  ("task_id", task_id), ("request_id", request_id)):
                if value:
                    query += f" AND {column} = ?"
                    values.append(value)
            if from_time:
                query += " AND occurred_at >= ?"
                values.append(from_time)
            if to_time:
                query += " AND occurred_at <= ?"
                values.append(to_time)
            query += " ORDER BY id DESC LIMIT ?"
            values.append(limit)
            return [{"cursor": row["id"], "ingested_at": row["ingested_at"],
                     **json.loads(row["payload_json"])} for row in db.execute(query, values)]

    def latest_event_id(self, robot_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT MAX(id) AS event_id FROM platform_events WHERE robot_id = ?", (robot_id,)
            ).fetchone()
            return int(row["event_id"] or 0)

    def reserve_command(
        self, key, body_hash, actor, robot_id, action, origin_request_id=None
    ):
        with self.connect() as db:
            command_id = str(uuid.uuid4())
            now = utc_now()
            result = {
                "command_id": command_id,
                "status": "pending",
                "request_id": command_id,
                "origin_request_id": origin_request_id,
            }
            inserted = db.execute(
                """INSERT OR IGNORE INTO commands(command_id, idempotency_key, body_hash, actor, robot_id,
                   action, status, result_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (command_id, key, body_hash, actor, robot_id, action, "pending", json.dumps(result), now, now),
            )
            row = dict(db.execute("SELECT * FROM commands WHERE idempotency_key = ?", (key,)).fetchone())
            if row["body_hash"] != body_hash or row["actor"] != actor or row["robot_id"] != robot_id:
                raise ValueError("idempotency key was used for a different request")
            return row, inserted.rowcount == 1

    def finish_command(self, command_id, status, result):
        with self.connect() as db:
            db.execute(
                "UPDATE commands SET status = ?, result_json = ?, updated_at = ? WHERE command_id = ?",
                (status, json.dumps(result), utc_now(), command_id),
            )

    def command(self, command_id, robot_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM commands WHERE command_id = ? AND robot_id = ?", (command_id, robot_id)
            ).fetchone()
            return dict(row) if row else None

    def observe_fault(self, robot_id, name, message, level):
        code = "DIAG-" + hashlib.sha1(name.encode()).hexdigest()[:12].upper()
        now = utc_now()
        with self.connect() as db:
            active = db.execute(
                """SELECT fault_id FROM faults WHERE robot_id = ? AND fault_code = ?
                   AND fault_source = ? AND resolved_at IS NULL ORDER BY first_seen DESC LIMIT 1""",
                (robot_id, code, name),
            ).fetchone()
            if level == 0:
                if active:
                    db.execute("UPDATE faults SET resolved_at = ?, last_seen = ? WHERE fault_id = ?",
                               (now, now, active["fault_id"]))
                    row = db.execute("SELECT * FROM faults WHERE fault_id = ?", (active["fault_id"],)).fetchone()
                    self._append_event(db, robot_id, "fault_resolved", {"fault": dict(row)})
                return
            severity = {1: "WARNING", 2: "ERROR", 3: "ERROR"}.get(level, "WARNING")
            if active:
                previous = db.execute("SELECT * FROM faults WHERE fault_id = ?", (active["fault_id"],)).fetchone()
                changed = previous["description"] != message or previous["severity"] != severity
                db.execute("UPDATE faults SET description = ?, severity = ?, last_seen = ? WHERE fault_id = ?",
                           (message, severity, now, active["fault_id"]))
                if changed:
                    row = db.execute("SELECT * FROM faults WHERE fault_id = ?", (active["fault_id"],)).fetchone()
                    self._append_event(db, robot_id, "fault_updated", {"fault": dict(row)})
            else:
                db.execute(
                    """INSERT INTO faults(fault_id, robot_id, fault_code, fault_source,
                       description, severity, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), robot_id, code, name, message, severity, now, now),
                )
                row = db.execute(
                    "SELECT * FROM faults WHERE robot_id = ? AND fault_code = ? AND fault_source = ? "
                    "AND resolved_at IS NULL ORDER BY first_seen DESC LIMIT 1",
                    (robot_id, code, name),
                ).fetchone()
                self._append_event(db, robot_id, "fault_raised", {"fault": dict(row)})

    def faults(self, robot_id, active_only=False, limit=100, offset=0,
               module=None, severity=None, status=None, from_time=None, to_time=None):
        with self.connect() as db:
            query = "SELECT * FROM faults WHERE robot_id = ?"
            values = [robot_id]
            if status == "active" or active_only:
                query += " AND resolved_at IS NULL AND cleared_at IS NULL"
            elif status == "resolved":
                query += " AND resolved_at IS NOT NULL AND cleared_at IS NULL"
            elif status == "cleared":
                query += " AND cleared_at IS NOT NULL"
            if module:
                query += " AND fault_source LIKE ?"
                values.append(f"%{module}%")
            if severity in ("WARNING", "ERROR"):
                query += " AND severity = ?"
                values.append(severity)
            if from_time:
                query += " AND first_seen >= ?"
                values.append(from_time)
            if to_time:
                query += " AND first_seen <= ?"
                values.append(to_time)
            query += " ORDER BY first_seen DESC, fault_id ASC LIMIT ? OFFSET ?"
            values.extend((limit, offset))
            return [dict(row) for row in db.execute(query, values)]

    def fault_count(self, robot_id, **filters):
        query = "SELECT COUNT(*) FROM faults WHERE robot_id = ?"
        values = [robot_id]
        status = filters.get("status")
        if status == "active" or filters.get("active_only"):
            query += " AND resolved_at IS NULL AND cleared_at IS NULL"
        elif status == "resolved":
            query += " AND resolved_at IS NOT NULL AND cleared_at IS NULL"
        elif status == "cleared":
            query += " AND cleared_at IS NOT NULL"
        module = filters.get("module")
        if module:
            query += " AND fault_source LIKE ?"
            values.append(f"%{module}%")
        severity = filters.get("severity")
        if severity in ("WARNING", "ERROR"):
            query += " AND severity = ?"
            values.append(severity)
        if filters.get("from_time"):
            query += " AND first_seen >= ?"
            values.append(filters["from_time"])
        if filters.get("to_time"):
            query += " AND first_seen <= ?"
            values.append(filters["to_time"])
        with self.connect() as db:
            return int(db.execute(query, values).fetchone()[0])

    def fault(self, robot_id, fault_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM faults WHERE robot_id = ? AND fault_id = ?", (robot_id, fault_id)).fetchone()
            return dict(row) if row else None

    def ack_fault(self, robot_id, fault_id, actor):
        with self.connect() as db:
            now = utc_now()
            db.execute(
                "UPDATE faults SET acknowledged_by = ?, acknowledged_at = ? WHERE robot_id = ? AND fault_id = ?",
                (actor, now, robot_id, fault_id),
            )
            row = db.execute("SELECT * FROM faults WHERE robot_id = ? AND fault_id = ?", (robot_id, fault_id)).fetchone()
            if row:
                self._append_event(db, robot_id, "fault_acknowledged", {"fault": dict(row)})

    def clear_fault(self, robot_id, fault_id):
        with self.connect() as db:
            db.execute(
                "UPDATE faults SET cleared_at = ? WHERE robot_id = ? AND fault_id = ? AND resolved_at IS NOT NULL",
                (utc_now(), robot_id, fault_id),
            )
            row = db.execute("SELECT * FROM faults WHERE robot_id = ? AND fault_id = ?", (robot_id, fault_id)).fetchone()
            if row and row["cleared_at"]:
                self._append_event(db, robot_id, "fault_cleared", {"fault": dict(row)})

    def config(self, version=None):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM config_versions WHERE version = ?" if version else
                "SELECT * FROM config_versions WHERE active = 1 ORDER BY version DESC LIMIT 1",
                (version,) if version else (),
            ).fetchone()
            if not row:
                return None
            item = dict(row)
            item["config"] = json.loads(item.pop("config_json"))
            return item

    def config_versions(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT version, active, actor, created_at FROM config_versions ORDER BY version DESC LIMIT 100"
            )]

    def create_config(self, config, actor, expected_version):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            active = db.execute(
                "SELECT version FROM config_versions WHERE active = 1 ORDER BY version DESC LIMIT 1"
            ).fetchone()
            active_version = active[0] if active else None
            if active_version != expected_version:
                raise ValueError("config version changed")
            db.execute("UPDATE config_versions SET active = 0 WHERE active = 1")
            cursor = db.execute(
                "INSERT INTO config_versions(config_json, active, actor, created_at) VALUES (?, 1, ?, ?)",
                (json.dumps(config), actor, utc_now()),
            )
            return cursor.lastrowid

    def activate_config(self, version):
        with self.connect() as db:
            row = db.execute("SELECT version FROM config_versions WHERE version = ?", (version,)).fetchone()
            if not row:
                return False
            db.execute("UPDATE config_versions SET active = 0 WHERE active = 1")
            db.execute("UPDATE config_versions SET active = 1 WHERE version = ?", (version,))
            return True

    def map_metadata(self, robot_id, group_name, map_name):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM map_metadata WHERE robot_id = ? AND group_name = ? AND map_name = ?",
                (robot_id, group_name, map_name),
            ).fetchone()
            return dict(row) if row else None

    def save_map_metadata(self, robot_id, group_name, map_name, values, actor, expected_revision):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT revision FROM map_metadata WHERE robot_id = ? AND group_name = ? AND map_name = ?",
                (robot_id, group_name, map_name),
            ).fetchone()
            current_revision = int(row["revision"]) if row else 0
            if current_revision != expected_revision:
                raise ValueError("map metadata revision changed")
            now = utc_now()
            if row:
                db.execute(
                    "UPDATE map_metadata SET campus=?, building=?, floor=?, label=?, description=?, "
                    "revision=revision+1, actor=?, updated_at=? WHERE robot_id=? AND group_name=? AND map_name=?",
                    (values["campus"], values["building"], values["floor"], values["label"],
                     values["description"], actor, now, robot_id, group_name, map_name),
                )
            else:
                db.execute(
                    "INSERT INTO map_metadata(robot_id,group_name,map_name,campus,building,floor,label,description,"
                    "revision,actor,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,1,?,?,?)",
                    (robot_id, group_name, map_name, values["campus"], values["building"],
                     values["floor"], values["label"], values["description"], actor, now, now),
                )
            self._append_event(db, robot_id, "map_metadata_updated", {
                "group": group_name, "map": map_name, "revision": current_revision + 1,
                "actor": actor, "metadata": values,
            })
            result = db.execute(
                "SELECT * FROM map_metadata WHERE robot_id = ? AND group_name = ? AND map_name = ?",
                (robot_id, group_name, map_name),
            ).fetchone()
            return dict(result)

    def record_map_version(self, robot_id, group_name, map_name, version_id, checksum,
                           manifest, metadata, actor):
        with self.connect() as db:
            inserted = db.execute(
                "INSERT OR IGNORE INTO map_catalog_versions(robot_id,group_name,map_name,version_id,checksum,"
                "manifest_json,metadata_json,actor,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (robot_id, group_name, map_name, version_id, checksum,
                 json.dumps(manifest, sort_keys=True), json.dumps(metadata or {}, sort_keys=True), actor, utc_now()),
            )
            if inserted.rowcount == 1:
                self._append_event(db, robot_id, "map_checksum_version_recorded", {
                    "group": group_name, "map": map_name, "version_id": version_id,
                    "checksum": checksum, "actor": actor,
                })
            row = db.execute(
                "SELECT * FROM map_catalog_versions WHERE robot_id=? AND group_name=? AND map_name=? AND checksum=?",
                (robot_id, group_name, map_name, checksum),
            ).fetchone()
            item = dict(row)
            item["manifest"] = json.loads(item.pop("manifest_json"))
            item["metadata"] = json.loads(item.pop("metadata_json"))
            return item

    def map_versions(self, robot_id, group_name, map_name):
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM map_catalog_versions WHERE robot_id=? AND group_name=? AND map_name=? "
                "ORDER BY created_at DESC, version_id DESC",
                (robot_id, group_name, map_name),
            ).fetchall()
            versions = []
            for row in rows:
                item = dict(row)
                item["manifest"] = json.loads(item.pop("manifest_json"))
                item["metadata"] = json.loads(item.pop("metadata_json"))
                versions.append(item)
            return versions

    @staticmethod
    def _waypoint_dict(row):
        if row is None:
            return None
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        return item

    def waypoints(self, robot_id, map_id):
        with self.connect() as db:
            return [self._waypoint_dict(row) for row in db.execute(
                "SELECT * FROM waypoints WHERE robot_id = ? AND map_id = ? ORDER BY name COLLATE NOCASE",
                (robot_id, map_id),
            )]

    def waypoint(self, robot_id, waypoint_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM waypoints WHERE robot_id = ? AND waypoint_id = ?",
                (robot_id, waypoint_id),
            ).fetchone()
            return self._waypoint_dict(row)

    def create_waypoint(self, robot_id, payload):
        now = utc_now()
        waypoint_id = str(uuid.uuid4())
        with self.connect() as db:
            db.execute(
                """INSERT INTO waypoints(robot_id, waypoint_id, map_id, map_version_id, name, x, y,
                   yaw, action, perception_type, point_type, source, valid_from, valid_until,
                   wait_time, enabled, created_at, updated_at, revision)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (robot_id, waypoint_id, payload["map_id"], payload.get("map_version_id"), payload["name"],
                 payload["x"], payload["y"], payload["yaw"], payload["action"],
                 payload.get("perception_type"), payload["point_type"], payload["source"],
                 payload.get("valid_from"), payload.get("valid_until"), payload["wait_time"],
                 int(payload["enabled"]), now, now),
            )
        return self.waypoint(robot_id, waypoint_id)

    def update_waypoint(self, robot_id, waypoint_id, payload, expected_revision):
        now = utc_now()
        with self.connect() as db:
            cursor = db.execute(
                """UPDATE waypoints SET map_id = ?, map_version_id = ?, name = ?, x = ?, y = ?,
                   yaw = ?, action = ?, perception_type = ?, point_type = ?, source = ?,
                   valid_from = ?, valid_until = ?, wait_time = ?, enabled = ?,
                   updated_at = ?, revision = revision + 1
                   WHERE robot_id = ? AND waypoint_id = ? AND revision = ?""",
                (payload["map_id"], payload.get("map_version_id"), payload["name"], payload["x"], payload["y"],
                 payload["yaw"], payload["action"], payload.get("perception_type"), payload["point_type"],
                 payload["source"], payload.get("valid_from"), payload.get("valid_until"),
                 payload["wait_time"], int(payload["enabled"]), now, robot_id, waypoint_id, expected_revision),
            )
            if cursor.rowcount != 1:
                return None
        return self.waypoint(robot_id, waypoint_id)

    def delete_waypoint(self, robot_id, waypoint_id, expected_revision):
        with self.connect() as db:
            cursor = db.execute(
                "DELETE FROM waypoints WHERE robot_id = ? AND waypoint_id = ? AND revision = ?",
                (robot_id, waypoint_id, expected_revision),
            )
            return cursor.rowcount == 1


class RobotBridge(Node):
    def __init__(self, store, robot_id):
        super().__init__("ui_platform_bridge")
        self.store = store
        self.robot_id = robot_id
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.acks = {}
        self.mission_state = None
        self.mission_seen = 0
        self.heartbeat = None
        self.heartbeat_seen = 0
        self.pose = None
        self.pose_seen = 0
        self.pose_observed_at = None
        self.odom_seen = 0
        self.battery = None
        self.battery_seen = 0
        self.battery_state = None
        self.battery_state_seen = 0
        self.navigation = None
        self.navigation_seen = 0
        self.map_identity = None
        self.map_identity_seen = 0
        self.map_identity_observed_at = None
        self.map_bundle = None
        self.map_bundle_seen = 0
        self.software_stop_state = None
        self.software_stop_seen = 0
        self.diagnostics = {}
        self.area_control = None
        self.area_control_seen = 0
        self.fault_candidates = {}
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.command_pub = self.create_publisher(String, "/mission/command", 10)
        self.outbox_ack_pub = self.create_publisher(String, "/robot/events/ack", 10)
        self.battery_scenario_pub = self.create_publisher(String, "/battery/sim_scenario", 10)
        config_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.battery_config_pub = self.create_publisher(String, "/battery/platform_config", config_qos)
        self.create_subscription(String, "/mission/state", self._mission_state, qos)
        self.create_subscription(String, "/robot/heartbeat", self._heartbeat, 10)
        self.create_subscription(String, "/mission/ack", self._mission_ack, 10)
        self.create_subscription(String, "/robot/events/outbox", self._robot_outbox, 10)
        self.create_subscription(Odometry, "/liorf_localization/mapping/odometry", self._pose, 10)
        self.create_subscription(Odometry, "/odometry/filtered", self._odom, 10)
        # Keep the legacy Float32 topic subscribed for compatibility with
        # existing robot publishers; it is never treated as source-truth data.
        self.create_subscription(Float32, "/battery_status", self._battery, 10)
        self.create_subscription(String, "/battery/state", self._battery_state, 10)
        self.create_subscription(String, "/ackermann/routes/catalog", self._route_catalog, 10)
        self.create_subscription(String, "/localization/map_bundle", self._map_bundle, 10)
        self.create_subscription(String, "/safety/software_stop/state", self._software_stop_state, 10)
        self.create_subscription(String, "/area_rules/control", self._area_control, 10)
        self.create_subscription(DiagnosticArray, "/diagnostics", self._diagnostic, 10)
        if NavigationStatus is not None:
            self.create_subscription(NavigationStatus, "/navigation/state", self._navigation, 10)

    def _navigation(self, message):
        labels = {0: "WAITING_FOR_GOAL", 1: "PLANNING", 2: "MOVING", 3: "ARRIVED", 4: "FAILED"}
        with self.lock:
            self.navigation = {"state": labels.get(message.state, "UNKNOWN"), "detail": message.detail}
            self.navigation_seen = time.monotonic()

    def _route_catalog(self, message):
        try:
            active = json.loads(message.data).get("active_files", {})
        except (ValueError, TypeError, AttributeError):
            return
        map_id = active.get("map_id")
        if not isinstance(map_id, str) or not map_id or map_id == "Null":
            return
        with self.lock:
            self.map_identity = {
                "map_id": map_id,
                "map_version_id": active.get("map_version_id") or map_id,
                "group": active.get("group"),
                "map": active.get("map"),
            }
            self.map_identity_seen = time.monotonic()
            self.map_identity_observed_at = utc_now()

    def _map_bundle(self, message):
        try:
            value = json.loads(message.data)
        except (ValueError, TypeError, AttributeError):
            return
        if (not isinstance(value, dict) or value.get("schema_version") != 1
                or not isinstance(value.get("ready"), bool)):
            return
        with self.lock:
            self.map_bundle = value
            self.map_bundle_seen = time.monotonic()

    def _software_stop_state(self, message):
        try:
            state = json.loads(message.data)
            observed_at = state.get("observed_at")
            if not isinstance(state, dict) or not isinstance(state.get("active"), bool):
                return
            if not isinstance(observed_at, str) or not datetime.fromisoformat(observed_at.replace("Z", "+00:00")).tzinfo:
                return
            if state.get("result") not in {"confirmed", "rejected", "degraded"}:
                return
            if not isinstance(state.get("durable"), bool):
                return
        except (ValueError, TypeError, AttributeError):
            return
        with self.lock:
            self.software_stop_state = state
            self.software_stop_seen = time.monotonic()

    def _area_control(self, message):
        try:
            state = json.loads(message.data)
        except (ValueError, TypeError, AttributeError):
            return
        if not isinstance(state, dict) or not isinstance(state.get("ready"), bool) or not isinstance(state.get("stop"), bool):
            return
        with self.lock:
            self.area_control = state
            self.area_control_seen = time.monotonic()

    def _mission_state(self, message):
        try:
            state = json.loads(message.data)
        except (ValueError, TypeError):
            return
        if isinstance(state, dict) and state.get("schema_version") == 1:
            with self.lock:
                self.mission_state = state
                self.mission_seen = time.monotonic()

    def _heartbeat(self, message):
        try:
            heartbeat = json.loads(message.data)
            if (not isinstance(heartbeat, dict) or heartbeat.get("schema_version") != 1
                    or heartbeat.get("robot_id") != self.robot_id
                    or heartbeat.get("source") != "mission_manager"
                    or isinstance(heartbeat.get("heartbeat_seq"), bool)
                    or not isinstance(heartbeat.get("heartbeat_seq"), int)
                    or heartbeat["heartbeat_seq"] < 1):
                return
            observed_at = datetime.fromisoformat(heartbeat["observed_at"].replace("Z", "+00:00"))
            if observed_at.tzinfo is None:
                return
        except (ValueError, TypeError, AttributeError, KeyError):
            return
        with self.lock:
            if (self.heartbeat and time.monotonic() - self.heartbeat_seen < 6
                    and heartbeat["heartbeat_seq"] <= self.heartbeat["heartbeat_seq"]):
                return
            self.heartbeat = heartbeat
            self.heartbeat_seen = time.monotonic()

    def _mission_ack(self, message):
        try:
            ack = json.loads(message.data)
        except (ValueError, TypeError):
            return
        with self.condition:
            self.acks[ack.get("request_id")] = ack
            self.condition.notify_all()

    def _robot_outbox(self, message):
        try:
            batch = json.loads(message.data)
            if batch.get("schema_version") != 1 or batch.get("robot_id") != self.robot_id:
                raise ValueError("outbox batch identity is invalid")
            through_seq = self.store.ingest_robot_events(self.robot_id, batch.get("events"))
        except (ValueError, TypeError, AttributeError, sqlite3.Error) as error:
            self.get_logger().error(f"Robot event sync failed: {error}")
            return
        self.outbox_ack_pub.publish(String(data=json.dumps({
            "schema_version": 1, "robot_id": self.robot_id, "through_seq": through_seq,
        }, separators=(",", ":"))))

    def _pose(self, message):
        q = message.pose.pose.orientation
        position = message.pose.pose.position
        values = (position.x, position.y, q.x, q.y, q.z, q.w)
        norm = q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w
        if not all(math.isfinite(value) for value in values) or not 0.9 <= norm <= 1.1:
            return
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        with self.lock:
            self.pose = {"x": position.x, "y": position.y, "yaw": yaw, "frame_id": message.header.frame_id}
            self.pose_seen = time.monotonic()
            self.pose_observed_at = utc_now()

    def _odom(self, _message):
        with self.lock:
            self.odom_seen = time.monotonic()

    def _battery(self, message):
        with self.lock:
            self.battery = message.data
            self.battery_seen = time.monotonic()

    def _battery_state(self, message):
        try:
            state = json.loads(message.data)
        except (ValueError, TypeError, AttributeError):
            return
        if not isinstance(state, dict):
            return
        percent = state.get("percent")
        if percent is not None:
            try:
                percent = float(percent)
            except (TypeError, ValueError):
                return
            if not math.isfinite(percent) or not 0 <= percent <= 100:
                return
        source = state.get("source")
        if source not in ("simulated", "hardware", "unavailable"):
            return
        if not isinstance(state.get("available"), bool):
            return
        if not isinstance(state.get("observed_at"), str):
            return
        config_version = state.get("threshold_config_version", 0)
        if isinstance(config_version, bool) or not isinstance(config_version, int) or config_version < 0:
            config_version = 0
        normalized = {
            **state,
            "percent": percent,
            "simulated": source == "simulated",
            "threshold_config_version": config_version,
        }
        with self.lock:
            self.battery_state = normalized
            self.battery_state_seen = time.monotonic()
        if (normalized.get("available") and isinstance(normalized.get("low_battery"), bool)):
            threshold = normalized.get("low_battery_threshold", "unknown")
            self.store.observe_fault(
                self.robot_id,
                "battery/low",
                f"Battery is at or below the low-battery threshold ({threshold}%).",
                1 if normalized["low_battery"] else 0,
            )

    def _diagnostic(self, message):
        now = time.monotonic()
        with self.lock:
            odom_online = now - self.odom_seen < 2
            for entry in message.status:
                level = entry.level[0] if isinstance(entry.level, (bytes, bytearray)) else int(entry.level)
                if (odom_online and entry.name == "ekf_filter_node: odometry/filtered topic status"
                        and entry.message == "No events recorded."):
                    self.store.observe_fault(self.robot_id, entry.name, entry.message, 0)
                    continue
                self.diagnostics[entry.name] = {
                    "level": level, "message": entry.message, "last_seen": now
                }
                if level == 0:
                    self.fault_candidates.pop(entry.name, None)
                    self.store.observe_fault(self.robot_id, entry.name, entry.message, 0)
                else:
                    first, last = self.fault_candidates.get(entry.name, (now, now))
                    if now - last > 5:
                        first = now
                    self.fault_candidates[entry.name] = (first, now)
                    if now - first >= 3:
                        self.store.observe_fault(self.robot_id, entry.name, entry.message, level)

    def snapshot(self):
        with self.lock:
            battery_state_recent = time.monotonic() - self.battery_state_seen < 10
            battery_state = copy.deepcopy(self.battery_state)
            if battery_state is not None:
                battery_state["stale"] = not battery_state_recent
            battery_available = bool(
                battery_state_recent and battery_state and battery_state.get("available")
            )
            return {
                "heartbeat": copy.deepcopy(self.heartbeat),
                "heartbeat_online": self.heartbeat is not None and time.monotonic() - self.heartbeat_seen < 6,
                "mission": copy.deepcopy(self.mission_state),
                "mission_online": time.monotonic() - self.mission_seen < 6,
                "pose": copy.deepcopy(self.pose),
                "pose_online": time.monotonic() - self.pose_seen < 3,
                "pose_observed_at": self.pose_observed_at,
                "odom_online": time.monotonic() - self.odom_seen < 3,
                "battery": battery_state.get("percent") if battery_available else None,
                "battery_online": battery_available,
                "battery_state": battery_state,
                "navigation": copy.deepcopy(self.navigation),
                "navigation_online": time.monotonic() - self.navigation_seen < 3,
                "map_identity": copy.deepcopy(self.map_identity),
                "map_identity_online": self.map_identity is not None and time.monotonic() - self.map_identity_seen < 30,
                "map_identity_observed_at": self.map_identity_observed_at,
                "map_bundle": copy.deepcopy(self.map_bundle),
                "map_bundle_online": self.map_bundle is not None and time.monotonic() - self.map_bundle_seen < 5,
                "software_stop_state": copy.deepcopy(self.software_stop_state),
                "software_stop_online": self.software_stop_state is not None and time.monotonic() - self.software_stop_seen < 3,
                "area_control": copy.deepcopy(self.area_control),
                "area_control_seen": self.area_control_seen > 0,
                "area_control_online": self.area_control is not None and time.monotonic() - self.area_control_seen < 3,
                "diagnostics": copy.deepcopy(self.diagnostics),
            }

    def command(self, command, request_id, timeout=3):
        with self.condition:
            self.acks.pop(request_id, None)
        self.command_pub.publish(String(data=json.dumps({**command, "request_id": request_id})))
        deadline = time.monotonic() + timeout
        with self.condition:
            while request_id not in self.acks:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self.condition.wait(remaining)
            return self.acks.pop(request_id)

    def take_ack(self, request_id):
        """Return a late ACK for a command that initially timed out."""
        with self.condition:
            return self.acks.pop(request_id, None)

    def set_battery_scenario(self, scenario):
        self.battery_scenario_pub.publish(String(data=scenario))

    def set_battery_config(self, config):
        payload = battery_config_payload(config)
        self.battery_config_pub.publish(String(data=json.dumps(payload, separators=(",", ":"))))


def register_platform_api(app, bridge_provider, store, robot_id, auth_store=None):
    prefix = "/api/v1/robots/<robot_id>"
    map_name_pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")

    @app.errorhandler(sqlite3.Error)
    def platform_database_error(error):
        app.logger.error("Platform SQLite operation failed: %s", error)
        if request.path.startswith("/api/"):
            response = jsonify({
                "code": "DATABASE_UNAVAILABLE",
                "message": (
                    "Robot platform storage is temporarily unavailable."
                ),
                "request_id": getattr(g, "request_id", ""),
            })
            response.status_code = 503
            response.headers["X-Request-Id"] = getattr(g, "request_id", "")
            return response
        return "Robot platform storage is temporarily unavailable.", 503

    def maps_root():
        configured = setting("MAP_ROOT", "").strip()
        if configured:
            return Path(configured).expanduser().resolve()
        workspace = os.environ.get("ACKERMANN_ROBOT_WS", "").strip()
        if workspace and Path(workspace).is_dir():
            return (Path(workspace) / "maps" / "ui").resolve()
        if get_package_share_directory is not None:
            try:
                return (Path(get_package_share_directory("robotpilot_ui_package")) / "maps").resolve()
            except Exception:
                pass
        return None

    def map_asset_manifest(group_name, map_name):
        for label, value in (("group", group_name), ("map", map_name)):
            if not isinstance(value, str) or not map_name_pattern.fullmatch(value) or value in {".", ".."}:
                abort(400, f"{label} must be a valid map catalog name.")
        root = maps_root()
        if root is None or not root.is_dir():
            abort(503, "Map catalog root is unavailable.")
        group_dir = root / group_name
        yaml_file = group_dir / f"{map_name}.yaml"
        if group_dir.is_symlink() or not yaml_file.is_file() or yaml_file.is_symlink():
            abort(404, "Saved map assets were not found.")
        paths = [yaml_file]
        try:
            map_yaml = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            abort(409, "Saved map YAML is unreadable or invalid.")
        image_name = map_yaml.get("image") if isinstance(map_yaml, dict) else None
        if not isinstance(image_name, str) or not image_name.strip():
            abort(409, "Saved map YAML does not name an image asset.")
        image_path = Path(image_name)
        if image_path.is_absolute() or ".." in image_path.parts:
            abort(409, "Saved map image path escapes its map group.")
        image_candidate = group_dir / image_path
        cursor = group_dir
        for part in image_path.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                abort(409, "Saved map image path uses a symbolic link.")
        image_file = image_candidate.resolve()
        try:
            image_file.relative_to(group_dir.resolve())
        except ValueError:
            abort(409, "Saved map image path escapes its map group.")
        if not image_file.is_file():
            abort(409, "Saved map image asset is missing or unsafe.")
        paths.append(image_file)
        for suffix in (".pgm", ".png", "_ros.yaml"):
            candidate = group_dir / f"{map_name}{suffix}"
            if candidate.exists():
                if candidate.is_symlink() or not candidate.is_file():
                    abort(409, "Map catalog contains an unsafe linked asset.")
                paths.append(candidate)
        nested = group_dir / map_name
        if nested.exists():
            if nested.is_symlink() or not nested.is_dir():
                abort(409, "Map catalog contains an unsafe map directory.")
            for directory, dirnames, filenames in os.walk(nested, followlinks=False):
                base = Path(directory)
                if any((base / dirname).is_symlink() for dirname in dirnames):
                    abort(409, "Map catalog contains a linked directory.")
                for filename in filenames:
                    path = base / filename
                    if path.is_symlink() or not path.is_file():
                        abort(409, "Map catalog contains an unsafe linked asset.")
                    paths.append(path)
        manifest = []
        for path in sorted(set(paths), key=lambda entry: entry.relative_to(group_dir).as_posix()):
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as stream:
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
            manifest.append({
                "path": path.relative_to(group_dir).as_posix(),
                "size": size,
                "sha256": digest.hexdigest(),
            })
        checksum = json_hash(manifest)
        return manifest, checksum

    def map_metadata_payload(payload, current=None):
        if not isinstance(payload, dict):
            abort(400, "Map metadata body must be a JSON object.")
        allowed = {"campus", "building", "floor", "label", "description"}
        if set(payload) - allowed:
            abort(400, "Unsupported map metadata field.")
        result = {key: (current or {}).get(key, "") for key in allowed}
        result.update(payload)
        limits = {"campus": 100, "building": 100, "floor": 100, "label": 100, "description": 1000}
        for key, maximum in limits.items():
            value = result[key]
            if not isinstance(value, str) or len(value.strip()) > maximum:
                abort(400, f"{key} must be a string of at most {maximum} characters.")
            result[key] = value.strip()
        if result["floor"] and not result["building"]:
            abort(400, "A floor requires a building.")
        if result["building"] and not result["campus"]:
            abort(400, "A building requires a campus.")
        return result

    def bridge_or_503():
        bridge = bridge_provider()
        if bridge is None:
            abort(503, "Robot API is not ready.")
        return bridge

    def mission_snapshot():
        snapshot = bridge_or_503().snapshot()
        if not snapshot["mission_online"]:
            abort(503, "Mission manager is offline.")
        return snapshot["mission"] or {}

    def waypoint_payload(value):
        if not isinstance(value, dict):
            abort(400, "Waypoint body must be a JSON object.")
        map_id = value.get("map_id")
        name = value.get("name")
        if not isinstance(map_id, str) or not map_id.strip() or len(map_id.strip()) > 128:
            abort(400, "map_id must be a non-empty string of at most 128 characters.")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
            abort(400, "name must be a non-empty string of at most 100 characters.")
        numbers = {}
        for field, low, high in (("x", None, None), ("y", None, None), ("yaw", -math.pi, math.pi),
                                 ("wait_time", 0, 86400)):
            raw = value.get(field, 0 if field == "wait_time" else None)
            if isinstance(raw, bool):
                abort(400, f"{field} must be a finite number.")
            try:
                number = float(raw)
            except (TypeError, ValueError):
                abort(400, f"{field} must be a finite number.")
            if not math.isfinite(number) or (low is not None and number < low) or (high is not None and number > high):
                abort(400, f"{field} is outside the supported range.")
            numbers[field] = number
        action = value.get("action", "none")
        perception_type = value.get("perception_type")
        if action != "none" or perception_type is not None:
            abort(400, "Waypoint actions and perception are not available until their robot-side handlers are connected.")
        point_type = value.get("point_type", "inspection")
        if point_type not in ("inspection", "charge", "shelter"):
            abort(400, "point_type must be inspection, charge, or shelter.")
        source = value.get("source", "operator")
        if source not in ("operator", "browser_import", "system"):
            abort(400, "source must be operator, browser_import, or system.")

        def optional_utc(field):
            raw = value.get(field)
            if raw is None:
                return None
            if not isinstance(raw, str) or len(raw) > 64:
                abort(400, f"{field} must be a timezone-aware RFC3339 string or null.")
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                abort(400, f"{field} must be a timezone-aware RFC3339 string or null.")
            if parsed.tzinfo is None:
                abort(400, f"{field} must include a timezone.")
            return parsed.astimezone(timezone.utc).isoformat()

        valid_from = optional_utc("valid_from")
        valid_until = optional_utc("valid_until")
        if valid_from and valid_until and valid_until <= valid_from:
            abort(400, "valid_until must be later than valid_from.")
        map_version_id = value.get("map_version_id")
        if map_version_id is not None and (not isinstance(map_version_id, str) or not map_version_id.strip() or len(map_version_id) > 128):
            abort(400, "map_version_id must be null or a non-empty string of at most 128 characters.")
        enabled = value.get("enabled", True)
        if not isinstance(enabled, bool):
            abort(400, "enabled must be a boolean.")
        return {
            "map_id": map_id.strip(), "map_version_id": map_version_id,
            "name": name.strip(), **numbers, "action": "none",
            "perception_type": None, "point_type": point_type, "source": source,
            "valid_from": valid_from, "valid_until": valid_until, "enabled": enabled,
        }

    def expected_revision(allow_zero=False):
        value = request.headers.get("If-Match", "").strip().strip('"')
        try:
            revision = int(value)
        except ValueError:
            abort(428, "If-Match with the current waypoint revision is required.")
        if revision < (0 if allow_zero else 1):
            abort(400, "If-Match contains an invalid revision.")
        return revision

    def ensure_current_map(robot_id, map_id):
        snapshot = bridge_or_503().snapshot()
        identity = snapshot.get("map_identity")
        if not snapshot.get("map_identity_online") or not identity:
            abort(503, "The robot's current 2D map identity is unavailable.")
        if identity.get("map_id") != map_id:
            abort(409, "Waypoint map_id does not match the robot's current 2D map.")
        return identity

    def dispatch(robot_id, action, command, idempotency_key=None):
        bridge = bridge_or_503()
        key = idempotency_key if idempotency_key is not None else request.headers.get("Idempotency-Key", "")
        if not 8 <= len(key) <= 128:
            abort(400, "Idempotency-Key must be 8–128 characters.")
        body_hash = json_hash({"path": request.path, "command": command})
        try:
            row, is_new = store.reserve_command(
                key, body_hash, g.identity["username"], robot_id, action,
                origin_request_id=g.request_id,
            )
        except ValueError as exc:
            abort(409, str(exc))
        if not is_new:
            return jsonify(json.loads(row["result_json"])), 202 if row["status"] == "pending" else 200
        if not bridge.snapshot()["mission_online"]:
            result = {
                "command_id": row["command_id"], "status": "rejected",
                "origin_request_id": g.request_id,
                "error": "Mission manager offline",
            }
            store.finish_command(row["command_id"], "rejected", result)
            return jsonify(result), 503
        ack = bridge.command(
            {**command, "origin_request_id": g.request_id}, row["command_id"]
        )
        if ack is None:
            result = {
                "command_id": row["command_id"], "status": "pending",
                "request_id": row["command_id"],
                "origin_request_id": g.request_id,
            }
            return jsonify(result), 202
        if not ack.get("ok"):
            result = {
                "command_id": row["command_id"], "status": "rejected",
                "origin_request_id": ack.get("origin_request_id", g.request_id),
                "error": ack.get("error", "Robot rejected command"),
            }
            store.finish_command(row["command_id"], "rejected", result)
            return jsonify(result), 409
        result = {
            "command_id": row["command_id"], "status": "accepted",
            "request_id": row["command_id"],
            "origin_request_id": ack.get("origin_request_id", g.request_id),
        }
        if ack.get("task_id"):
            result["task_id"] = ack["task_id"]
        if ack.get("schedule_id"):
            result["schedule_id"] = ack["schedule_id"]
        store.finish_command(row["command_id"], "accepted", result)
        return jsonify(result), 202

    def offline_map(group_name, map_name):
        source = request.args.get("source", "ui")
        if source not in {"ui", "project"}:
            abort(400, "Invalid map source.")
        for name in (group_name, map_name):
            if not map_name_pattern.fullmatch(name) or name in {".", ".."}:
                abort(400, "Invalid map name.")
        root = maps_root()
        if root is None:
            abort(503, "Map catalog root is unavailable.")
        try:
            return saved_map(root, source, group_name, map_name)
        except FileNotFoundError:
            abort(404, "Saved map was not found.")
        except (ValueError, KeyError, OSError, yaml.YAMLError) as error:
            abort(409, str(error))

    @app.get(prefix + "/maps/saved/<group_name>/<map_name>")
    @require_role("Viewer")
    def platform_saved_map(robot_id, group_name, map_name):
        item = offline_map(group_name, map_name)
        return jsonify({key: value for key, value in item.items() if key != "image_png"})

    @app.get(prefix + "/maps/saved/<group_name>/<map_name>/image")
    @require_role("Viewer")
    def platform_saved_map_image(robot_id, group_name, map_name):
        from io import BytesIO
        item = offline_map(group_name, map_name)
        return send_file(BytesIO(item["image_png"]), mimetype="image/png")

    @app.get(prefix + "/maps/saved/<group_name>/<map_name>/rules")
    @require_role("Viewer")
    def platform_saved_map_rules(robot_id, group_name, map_name):
        from area_rules.rules import RuleStore
        item = offline_map(group_name, map_name)
        return jsonify({"map_key": item["map_key"], "map_id": item["map_id"],
                        **RuleStore(rule_store_path()).state(item["map_key"])})

    @app.post(prefix + "/maps/saved/<group_name>/<map_name>/rules")
    @require_role("Engineer")
    def platform_update_saved_map_rules(robot_id, group_name, map_name):
        from area_rules.rules import RuleStore
        item = offline_map(group_name, map_name)
        store_rules = RuleStore(rule_store_path())
        key = item["map_key"]
        body = request.get_json(silent=True) or {}
        if body.get("map_key") != key:
            abort(409, "Saved map changed; reload before saving rules.")
        try:
            result = store_rules.mutate(key, body.get("expected_version"), body.get("action"), body.get("rule"))
        except ValueError as error:
            abort(409, str(error))
        return jsonify({"map_key": key, **result})

    @app.get(prefix + "/maps/saved/by-id/<map_id>/rules")
    @require_role("Viewer")
    def platform_saved_map_rules_by_id(robot_id, map_id):
        from area_rules.rules import RuleStore
        if not re.fullmatch(r"[0-9a-f]{12}", map_id):
            abort(400, "Invalid map identity.")
        root = maps_root()
        if root is None:
            abort(503, "Map catalog root is unavailable.")
        candidates = []
        if root.is_dir():
            for directory in root.iterdir():
                if directory.is_dir() and not directory.is_symlink() and map_name_pattern.fullmatch(directory.name):
                    for yaml_file in directory.glob("*.yaml"):
                        if yaml_file.stem.endswith("_ros") or not map_name_pattern.fullmatch(yaml_file.stem):
                            continue
                        candidates.append(("ui", directory.name, yaml_file.stem))
        if root.parent.is_dir():
            for directory in root.parent.iterdir():
                if directory.name != "ui" and directory.is_dir() and not directory.is_symlink() and map_name_pattern.fullmatch(directory.name):
                    candidates.append(("project", "maps", directory.name))
        for source, group_name, map_name in candidates:
            try:
                item = saved_map(root, source, group_name, map_name)
            except (FileNotFoundError, ValueError, KeyError, OSError, yaml.YAMLError):
                continue
            if item["map_id"] == map_id:
                return jsonify({"map_id": map_id, "map_key": item["map_key"],
                                "source": source, "group": group_name, "map": map_name,
                                **RuleStore(rule_store_path()).state(item["map_key"])})
        abort(404, "No saved map matches the active map identity.")

    @app.get(prefix + "/maps/catalog")
    @require_role("Viewer")
    def platform_map_catalog(robot_id):
        root = maps_root()
        if root is None or (not root.is_dir() and not root.parent.is_dir()):
            abort(503, "Map catalog root is unavailable.")
        entries = []
        for group_dir in sorted(root.iterdir(), key=lambda item: item.name.lower()) if root.is_dir() else []:
            if group_dir.is_symlink() or not group_dir.is_dir():
                continue
            for yaml_file in sorted(group_dir.glob("*.yaml"), key=lambda item: item.name.lower()):
                map_name = yaml_file.stem
                if map_name.endswith("_ros") or not map_name_pattern.fullmatch(map_name):
                    continue
                try:
                    manifest, checksum = map_asset_manifest(group_dir.name, map_name)
                except Exception:
                    # Keep the existing ROS list available; malformed or unsafe
                    # files are omitted from the metadata API and reported by
                    # their direct detail request.
                    continue
                entries.append({
                    "group": group_dir.name,
                    "map": map_name,
                    "metadata": store.map_metadata(robot_id, group_dir.name, map_name),
                    "checksum": checksum,
                    "version_id": f"sha256:{checksum}",
                    "asset_count": len(manifest),
                    "version_count": len(store.map_versions(robot_id, group_dir.name, map_name)),
                })
        project_entries = []
        project_root = root.parent
        if project_root.is_dir():
            for directory in sorted(project_root.iterdir(), key=lambda item: item.name.lower()):
                if directory.name == "ui" or directory.is_symlink() or not directory.is_dir():
                    continue
                if not map_name_pattern.fullmatch(directory.name):
                    continue
                project_entries.append({"name": directory.name, "loadable": (directory / "map.yaml").is_file()})
        return jsonify({"robot_id": robot_id, "maps": entries, "project_maps": project_entries})

    @app.get(prefix + "/maps/catalog/<group_name>/<map_name>")
    @require_role("Viewer")
    def platform_map_metadata(robot_id, group_name, map_name):
        manifest, checksum = map_asset_manifest(group_name, map_name)
        metadata = store.map_metadata(robot_id, group_name, map_name)
        if metadata is None:
            metadata = {
                "robot_id": robot_id, "group_name": group_name, "map_name": map_name,
                "campus": "", "building": "", "floor": "", "label": "",
                "description": "", "revision": 0, "actor": None,
                "created_at": None, "updated_at": None,
            }
        return jsonify({
            "metadata": metadata,
            "current_checksum": checksum,
            "current_version_id": f"sha256:{checksum}",
            "asset_count": len(manifest),
            "versions": store.map_versions(robot_id, group_name, map_name),
        })

    @app.patch(prefix + "/maps/catalog/<group_name>/<map_name>")
    @require_role("Engineer")
    def platform_update_map_metadata(robot_id, group_name, map_name):
        map_asset_manifest(group_name, map_name)
        try:
            expected_revision = int(request.headers.get("If-Match", "").strip('"'))
        except ValueError:
            abort(428, 'If-Match with the current metadata revision is required.')
        if expected_revision < 0:
            abort(400, "If-Match must be zero or a positive revision.")
        current = store.map_metadata(robot_id, group_name, map_name)
        if expected_revision != (current["revision"] if current else 0):
            abort(412, "Map metadata revision changed; reload before editing.")
        values = map_metadata_payload(request.get_json(silent=True), current)
        try:
            saved = store.save_map_metadata(
                robot_id, group_name, map_name, values, g.identity["username"], expected_revision
            )
        except ValueError:
            abort(412, "Map metadata revision changed; reload before editing.")
        return jsonify(saved)

    @app.get(prefix + "/maps/catalog/<group_name>/<map_name>/versions")
    @require_role("Viewer")
    def platform_map_versions(robot_id, group_name, map_name):
        map_asset_manifest(group_name, map_name)
        return jsonify({"versions": store.map_versions(robot_id, group_name, map_name)})

    @app.post(prefix + "/maps/catalog/<group_name>/<map_name>/versions")
    @require_role("Engineer")
    def platform_create_map_version(robot_id, group_name, map_name):
        manifest, checksum = map_asset_manifest(group_name, map_name)
        existing = next((item for item in store.map_versions(robot_id, group_name, map_name)
                         if item["checksum"] == checksum), None)
        if existing:
            return jsonify({"version": existing, "created": False}), 200
        metadata = store.map_metadata(robot_id, group_name, map_name) or {}
        version = store.record_map_version(
            robot_id, group_name, map_name, f"sha256:{checksum}", checksum,
            manifest, metadata, g.identity["username"],
        )
        return jsonify({"version": version, "created": True}), 201

    @app.get(prefix + "/status")
    @require_role("Viewer")
    def platform_status(robot_id):
        snapshot = bridge_or_503().snapshot()
        mission = snapshot["mission"] or {}
        readiness = autonomy_readiness(snapshot)
        return jsonify({
            "robot_id": robot_id, "observed_at": utc_now(),
            "online": snapshot["pose_online"] or snapshot["odom_online"],
            "robot_connection": {
                **(snapshot.get("heartbeat") or {}),
                "online": bool(snapshot.get("heartbeat_online")),
                "stale": not snapshot.get("heartbeat_online", False),
                "status": "online" if snapshot.get("heartbeat_online") else "stale",
            },
            "pose": {**(snapshot["pose"] or {}), "stale": not snapshot["pose_online"]},
            "localization": {
                "pose": snapshot["pose"], "online": snapshot["pose_online"],
                "stale": not snapshot["pose_online"], "quality": "unknown",
                "observed_at": snapshot["pose_observed_at"],
            },
            "odometry": {"stale": not snapshot["odom_online"]},
            "current_map": {
                **(snapshot["map_identity"] or {}), "stale": not snapshot["map_identity_online"],
                "observed_at": snapshot["map_identity_observed_at"],
            },
            "map_bundle": {
                **(snapshot.get("map_bundle") or {}),
                "stale": not snapshot.get("map_bundle_online", False),
                "ready": bool(snapshot.get("map_bundle_online") and (snapshot.get("map_bundle") or {}).get("ready")),
            },
            "software_stop": {
                **(snapshot["software_stop_state"] or {}),
                "available": snapshot["software_stop_online"],
                "stale": not snapshot["software_stop_online"],
            },
            "area_control": {
                **(snapshot.get("area_control") or {}),
                "available": bool(snapshot.get("area_control_online")),
                "stale": not snapshot.get("area_control_online", False),
            },
            "autonomy_ready": readiness["ready"],
            "readiness_blockers": readiness["blockers"],
            "battery": {
                **(snapshot["battery_state"] or {}),
                "percent": snapshot["battery"],
                "stale": (snapshot["battery_state"] or {}).get("stale", True),
                "available": snapshot["battery_online"],
                "source": (snapshot["battery_state"] or {}).get("source", "unavailable"),
            },
            "navigation": {**(snapshot["navigation"] or {}), "stale": not snapshot["navigation_online"]},
            "task": mission.get("run"), "task_stale": not snapshot["mission_online"],
            "inspection_provider": (
                mission.get("inspection_provider", {"online": False, "stale": True, "actions": []})
                if snapshot["mission_online"] else {"online": False, "stale": True, "actions": []}
            ),
            "event_sync": mission.get("event_sync") if snapshot["mission_online"] else None,
            "fault_counts": {
                "active": len(store.faults(robot_id, active_only=True)),
            },
            "alert_counts": {
                "active": sum(
                    item.get("level", 0) > 0 and time.monotonic() - item.get("last_seen", 0) < 5
                    for item in snapshot["diagnostics"].values()
                ),
            },
        })

    @app.get(prefix + "/inspection/capabilities")
    @require_role("Viewer")
    def s1_inspection_capabilities(robot_id):
        snapshot = bridge_or_503().snapshot()
        if not snapshot.get("mission_online"):
            return jsonify({"online": False, "stale": True, "actions": [],
                            "reason": "MissionManager status is unavailable."}), 503
        provider = (snapshot.get("mission") or {}).get(
            "inspection_provider", {"online": False, "stale": True, "actions": []}
        )
        return jsonify(provider)

    @app.post(prefix + "/battery/scenario")
    @require_role("Engineer")
    def platform_battery_scenario(robot_id):
        # This endpoint is intentionally unavailable outside the explicit local
        # simulation profile. The battery node also ignores commands unless its
        # configured source is `sim`.
        if (os.environ.get("ROBOT_MODE", "unknown").strip().lower() != "simulation"
                or os.environ.get("BATTERY_SOURCE", "disabled").strip().lower() != "sim"):
            abort(409, "Battery scenarios require ROBOT_MODE=simulation and BATTERY_SOURCE=sim.")
        payload = request.get_json(silent=True)
        scenario = payload.get("scenario") if isinstance(payload, dict) else None
        allowed = {"normal_discharge", "low_battery", "simulated_charging", "full",
                   "communication_lost", "charging_fault", "reset"}
        if scenario not in allowed:
            abort(400, "Unknown battery simulation scenario.")
        bridge = bridge_or_503()
        publish_scenario = getattr(bridge, "set_battery_scenario", None)
        if publish_scenario is None:
            abort(503, "Battery scenario control is unavailable.")
        publish_scenario(scenario)
        return jsonify({"status": "accepted", "scenario": scenario, "simulated": True}), 202

    @app.get(prefix + "/health")
    @require_role("Viewer")
    def platform_health(robot_id):
        snapshot = bridge_or_503().snapshot()
        readiness = autonomy_readiness(snapshot)
        data_root = Path(store.path).expanduser().parent
        storage_paths = [
            ("platform_data", data_root),
            ("recordings", data_root / "recordings"),
        ]
        backup_directory = os.environ.get("ROBOTPILOT_BACKUP_DIR")
        if backup_directory:
            storage_paths.append(("backups", backup_directory))
        try:
            storage = storage_report(storage_paths)
            storage_error = None
        except (OSError, ValueError) as error:
            storage = []
            storage_error = str(error)
        return jsonify({
            "robot_id": robot_id, "observed_at": utc_now(),
            "localization_online": snapshot["pose_online"],
            "odometry_online": snapshot["odom_online"],
            "mission_manager_online": snapshot["mission_online"],
            "map_identity": snapshot["map_identity"],
            "map_identity_online": snapshot["map_identity_online"],
            "software_stop_state": snapshot["software_stop_state"],
            "software_stop_online": snapshot["software_stop_online"],
            "robot_connection": {
                **(snapshot.get("heartbeat") or {}),
                "online": bool(snapshot.get("heartbeat_online")),
                "stale": not snapshot.get("heartbeat_online", False),
            },
            "autonomy_ready": readiness["ready"],
            "readiness_blockers": readiness["blockers"],
            "navigation_online": snapshot["navigation_online"],
            "battery_available": snapshot["battery_online"],
            "battery_state": snapshot["battery_state"],
            "storage": storage,
            "storage_error": storage_error,
            "diagnostics": [
                {"name": name, "level": item["level"], "message": item["message"]}
                for name, item in snapshot["diagnostics"].items()
                if time.monotonic() - item["last_seen"] < 5
            ],
        })

    @app.get(prefix + "/build")
    @require_role("Viewer")
    def platform_build_info(robot_id):
        share_directory = None
        if get_package_share_directory is not None:
            try:
                share_directory = get_package_share_directory(
                    "robotpilot_ui_package"
                )
            except Exception:
                app.logger.warning("RobotPilot package share is unavailable")
        return jsonify({
            "robot_id": robot_id,
            **get_build_info(share_directory),
            "schema_versions": {
                "platform": store.schema_version,
                "auth": getattr(auth_store, "schema_version", None),
            },
        })

    @app.get(prefix + "/events")
    @require_role("Viewer")
    def platform_events(robot_id):
        bridge = bridge_or_503()
        session_token = request.cookies.get(COOKIE_NAME)
        try:
            last_event_id = max(0, int(request.headers.get("Last-Event-ID", "0")))
        except ValueError:
            abort(400, "Last-Event-ID must be an integer.")

        def stream():
            cursor = last_event_id
            if cursor == 0:
                latest_id = store.latest_event_id(robot_id)
                if latest_id:
                    cursor = latest_id - 1
            for _ in range(150):
                if auth_store is not None and auth_store.session(session_token) is None:
                    break
                for event in store.events_after(robot_id, cursor):
                    cursor = event["id"]
                    yield (f"id: {cursor}\nevent: {event['event_type']}\n"
                           f"data: {event['payload_json']}\n\n")
                snapshot = bridge.snapshot()
                mission = snapshot["mission"] or {}
                readiness = autonomy_readiness(snapshot)
                active_alerts = sum(
                    item.get("level", 0) > 0 and time.monotonic() - item.get("last_seen", 0) < 5
                    for item in snapshot["diagnostics"].values()
                )
                payload = {
                    "robot_id": robot_id, "observed_at": utc_now(),
                    "pose": snapshot["pose"], "pose_stale": not snapshot["pose_online"],
                    "current_map": snapshot["map_identity"],
                    "map_stale": not snapshot["map_identity_online"],
                    "software_stop": snapshot["software_stop_state"],
                    "software_stop_stale": not snapshot["software_stop_online"],
                    "autonomy_ready": readiness["ready"],
                    "readiness_blockers": readiness["blockers"],
                    "task": mission.get("run"), "task_stale": not snapshot["mission_online"],
                    "navigation": snapshot["navigation"],
                    "navigation_stale": not snapshot["navigation_online"],
                    "battery": snapshot["battery_state"],
                    "battery_stale": not snapshot["battery_online"],
                    "active_alerts": active_alerts,
                    "active_faults": store.faults(robot_id, active_only=True),
                }
                event_id = store.append_state_event(robot_id, payload)
                if event_id is not None:
                    cursor = event_id
                    yield f"id: {event_id}\nevent: robot_state\ndata: {json.dumps(payload)}\n\n"
                elif not store.events_after(robot_id, cursor):
                    yield ": keepalive\n\n"
                time.sleep(2)

        response = Response(stream_with_context(stream()), mimetype="text/event-stream")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Accel-Buffering"] = "no"
        return response

    @app.get(prefix + "/events/history")
    @require_role("Viewer")
    def platform_event_history(robot_id):
        try:
            limit = int(request.args.get("limit", "50"))
            before_raw = request.args.get("before")
            before = int(before_raw) if before_raw else None
        except ValueError:
            abort(400, "limit and before must be integers")
        if not 1 <= limit <= 200 or (before is not None and before < 1):
            abort(400, "limit must be 1–200 and before must be positive")
        filters = {}
        for field in ("type", "severity", "task_id", "request_id", "from", "to"):
            value = request.args.get(field)
            if value is not None:
                if len(value) > 128:
                    abort(400, f"{field} is too long")
                filters[field] = value
        for field in ("from", "to"):
            if filters.get(field):
                try:
                    timestamp = datetime.fromisoformat(filters[field].replace("Z", "+00:00"))
                except ValueError:
                    abort(400, f"{field} must be RFC3339")
                if timestamp.tzinfo is None:
                    abort(400, f"{field} must include timezone")
                filters[field] = timestamp.astimezone(timezone.utc).isoformat()
        events = store.robot_event_history(
            robot_id, limit=limit, before=before,
            event_type=filters.get("type"), severity=filters.get("severity"),
            task_id=filters.get("task_id"), request_id=filters.get("request_id"),
            from_time=filters.get("from"), to_time=filters.get("to"),
        )
        return jsonify({"events": events, "next_before": events[-1]["cursor"] if len(events) == limit else None})

    @app.get(prefix + "/missions")
    @require_role("Viewer")
    def platform_missions(robot_id):
        return jsonify({"missions": mission_snapshot().get("missions", [])})

    @app.get(prefix + "/routes")
    @require_role("Viewer")
    def platform_saved_routes(robot_id):
        return jsonify({"routes": list_saved_routes()})

    @app.post(prefix + "/routes/<map_id>/<route_name>/mission")
    @require_role("Operator")
    def platform_route_mission(robot_id, map_id, route_name):
        try:
            mission = route_mission(map_id, route_name)
        except FileNotFoundError:
            abort(404, "Saved route was not found.")
        except (OSError, ValueError) as error:
            abort(409, str(error))
        # A schedule owns its route snapshot. Creating another schedule from
        # the same route must not rewrite the first schedule's waypoints.
        request_key = request.headers.get("Idempotency-Key", "")
        route_snapshot_key = f"{robot_id}\0{map_id}\0{route_name}\0{request_key}"
        mission["id"] = (
            f"route-{map_id}-{hashlib.sha256(route_snapshot_key.encode()).hexdigest()[:24]}"
        )
        response, status = dispatch(
            robot_id, "mission.save.route", {"command": "save", "mission": mission}
        )
        payload = response.get_json()
        payload["mission_id"] = mission["id"]
        return jsonify(payload), status

    @app.get(prefix + "/missions/<mission_id>")
    @require_role("Viewer")
    def platform_mission(robot_id, mission_id):
        mission = next((item for item in mission_snapshot().get("missions", []) if item.get("id") == mission_id), None)
        if not mission:
            abort(404, "Mission not found.")
        return jsonify(mission)

    @app.get(prefix + "/waypoints")
    @require_role("Viewer")
    def platform_waypoints(robot_id):
        map_id = request.args.get("map_id", "").strip()
        if not map_id or len(map_id) > 128:
            abort(400, "A map_id query parameter is required.")
        return jsonify({"robot_id": robot_id, "map_id": map_id, "waypoints": store.waypoints(robot_id, map_id)})

    @app.post(prefix + "/waypoints")
    @require_role("Engineer")
    def platform_create_waypoint(robot_id):
        payload = waypoint_payload(request.get_json(silent=True))
        identity = ensure_current_map(robot_id, payload["map_id"])
        if payload.get("map_version_id") not in (None, identity.get("map_version_id")):
            abort(409, "Waypoint map_version_id does not match the robot's current 2D map.")
        payload["map_version_id"] = identity.get("map_version_id")
        try:
            waypoint = store.create_waypoint(robot_id, payload)
        except sqlite3.IntegrityError:
            abort(409, "A waypoint with this name already exists on the map.")
        return jsonify(waypoint), 201

    @app.get(prefix + "/waypoints/<waypoint_id>")
    @require_role("Viewer")
    def platform_get_waypoint(robot_id, waypoint_id):
        waypoint = store.waypoint(robot_id, waypoint_id)
        if not waypoint:
            abort(404, "Waypoint not found.")
        return jsonify(waypoint)

    @app.patch(prefix + "/waypoints/<waypoint_id>")
    @require_role("Engineer")
    def platform_update_waypoint(robot_id, waypoint_id):
        current = store.waypoint(robot_id, waypoint_id)
        if not current:
            abort(404, "Waypoint not found.")
        revision = expected_revision()
        if revision != current["revision"]:
            abort(412, "Waypoint revision changed; reload it before editing.")
        updates = request.get_json(silent=True)
        if not isinstance(updates, dict):
            abort(400, "Waypoint patch must be a JSON object.")
        merged = {**current, **updates}
        payload = waypoint_payload(merged)
        identity = ensure_current_map(robot_id, payload["map_id"])
        if payload.get("map_version_id") not in (None, identity.get("map_version_id")):
            abort(409, "Waypoint map_version_id does not match the robot's current 2D map.")
        payload["map_version_id"] = identity.get("map_version_id")
        try:
            updated = store.update_waypoint(robot_id, waypoint_id, payload, revision)
        except sqlite3.IntegrityError:
            abort(409, "A waypoint with this name already exists on the map.")
        if updated is None:
            abort(412, "Waypoint revision changed; reload it before editing.")
        return jsonify(updated)

    @app.delete(prefix + "/waypoints/<waypoint_id>")
    @require_role("Engineer")
    def platform_delete_waypoint(robot_id, waypoint_id):
        current = store.waypoint(robot_id, waypoint_id)
        if not current:
            abort(404, "Waypoint not found.")
        if expected_revision() != current["revision"]:
            abort(412, "Waypoint revision changed; reload it before deleting.")
        snapshot = bridge_or_503().snapshot()
        if not snapshot.get("mission_online"):
            abort(503, "Mission manager state is unavailable; waypoint references cannot be checked.")
        mission_state = snapshot.get("mission") or {}
        referenced = any(
            step.get("waypointId") == waypoint_id
            for mission in mission_state.get("missions", [])
            for step in mission.get("steps", [])
            if isinstance(step, dict)
        )
        if referenced:
            abort(409, "Waypoint is referenced by a saved mission and cannot be deleted.")
        if not store.delete_waypoint(robot_id, waypoint_id, current["revision"]):
            abort(412, "Waypoint revision changed; reload it before deleting.")
        return "", 204

    @app.post(prefix + "/missions")
    @require_role("Operator")
    def platform_save_mission(robot_id):
        mission = request.get_json(silent=True)
        if not isinstance(mission, dict) or not mission.get("id"):
            abort(400, "Mission id is required.")
        return dispatch(robot_id, "mission.save", {"command": "save", "mission": mission})

    @app.put(prefix + "/missions/<mission_id>")
    @require_role("Operator")
    def platform_update_mission(robot_id, mission_id):
        mission = request.get_json(silent=True)
        if not isinstance(mission, dict) or mission.get("id") != mission_id:
            abort(400, "Mission id mismatch.")
        return dispatch(robot_id, "mission.save", {"command": "save", "mission": mission})

    @app.delete(prefix + "/missions/<mission_id>")
    @require_role("Operator")
    def platform_delete_mission(robot_id, mission_id):
        return dispatch(robot_id, "mission.delete", {"command": "delete", "mission_id": mission_id})

    @app.post(prefix + "/tasks")
    @require_role("Operator")
    def platform_start_task(robot_id):
        payload = request.get_json(silent=True) or {}
        mission_id = payload.get("mission_id")
        if not isinstance(mission_id, str) or not mission_id:
            abort(400, "mission_id is required.")
        return dispatch(robot_id, "task.start", {"command": "start", "mission_id": mission_id})

    @app.get(prefix + "/tasks")
    @require_role("Viewer")
    def platform_tasks(robot_id):
        state = mission_snapshot()
        return jsonify({"current": state.get("run"), "history": state.get("history", [])})

    @app.get(prefix + "/tasks/<task_id>")
    @require_role("Viewer")
    def platform_task(robot_id, task_id):
        state = mission_snapshot()
        tasks = [state.get("run")] + state.get("history", [])
        task = next((item for item in tasks if item and item.get("task_id") == task_id), None)
        if not task:
            abort(404, "Task not found.")
        return jsonify(task)

    @app.post(prefix + "/tasks/<task_id>/commands")
    @require_role("Operator")
    def platform_task_command(robot_id, task_id):
        payload = request.get_json(silent=True) or {}
        action = payload.get("action")
        if action not in {"pause", "resume", "cancel", "retry", "skip", "release_hold"}:
            abort(400, "Unsupported task action.")
        return dispatch(robot_id, "task." + action, {"command": action, "task_id": task_id})

    @app.get(prefix + "/schedules")
    @require_role("Viewer")
    def platform_schedules(robot_id):
        state = mission_snapshot()
        return jsonify({"schedules": state.get("schedules", [])})

    @app.get(prefix + "/schedules/<schedule_id>/runs")
    @require_role("Viewer")
    def platform_schedule_runs(robot_id, schedule_id):
        state = mission_snapshot()
        schedules = state.get("schedules", [])
        if not any(item.get("schedule_id") == schedule_id for item in schedules):
            abort(404, "Schedule not found.")
        runs = [
            item for item in state.get("schedule_runs", [])
            if item.get("schedule_id") == schedule_id
        ]
        return jsonify({"schedule_id": schedule_id, "runs": runs})

    @app.post(prefix + "/schedules")
    @require_role("Operator")
    def platform_create_schedule(robot_id):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            abort(400, "Schedule body must be a JSON object.")
        schedule = payload.get("schedule")
        if not isinstance(schedule, dict):
            abort(400, "schedule object is required.")
        command = {
            "command": "schedule.save", "schedule": schedule,
            "created_by": g.identity.get("username", "operator"),
        }
        return dispatch(robot_id, "schedule.create", command)

    @app.patch(prefix + "/schedules/<schedule_id>")
    @require_role("Operator")
    def platform_update_schedule(robot_id, schedule_id):
        state = mission_snapshot()
        current = next(
            (item for item in state.get("schedules", []) if item.get("schedule_id") == schedule_id),
            None,
        )
        if not current:
            abort(404, "Schedule not found.")
        expected = request.headers.get("If-Match", "").strip().strip('"')
        if not expected.isdigit():
            abort(428, "If-Match with the current schedule revision is required.")
        revision = int(expected)
        if revision != current["revision"]:
            abort(412, "Schedule revision changed; reload it before editing.")
        updates = request.get_json(silent=True)
        if not isinstance(updates, dict):
            abort(400, "Schedule patch must be a JSON object.")
        schedule = {key: current[key] for key in (
            "name", "mission_id", "recurrence", "timezone", "local_time", "start_date",
            "weekdays", "enabled",
        )}
        schedule.update(updates)
        command = {
            "command": "schedule.save", "schedule_id": schedule_id,
            "expected_revision": revision, "schedule": schedule,
            "created_by": g.identity.get("username", "operator"),
        }
        return dispatch(robot_id, "schedule.update", command)

    @app.delete(prefix + "/schedules/<schedule_id>")
    @require_role("Operator")
    def platform_delete_schedule(robot_id, schedule_id):
        state = mission_snapshot()
        current = next(
            (item for item in state.get("schedules", []) if item.get("schedule_id") == schedule_id),
            None,
        )
        if not current:
            abort(404, "Schedule not found.")
        expected = request.headers.get("If-Match", "").strip().strip('"')
        if not expected.isdigit():
            abort(428, "If-Match with the current schedule revision is required.")
        revision = int(expected)
        if revision != current["revision"]:
            abort(412, "Schedule revision changed; reload it before deleting.")
        command = {
            "command": "schedule.delete", "schedule_id": schedule_id,
            "expected_revision": revision,
        }
        return dispatch(robot_id, "schedule.delete", command)

    @app.get(prefix + "/commands/<command_id>")
    @require_role("Viewer")
    def platform_command(robot_id, command_id):
        row = store.command(command_id, robot_id)
        if not row:
            abort(404, "Command not found.")
        result = json.loads(row["result_json"])
        if row["status"] == "pending":
            bridge = bridge_or_503()
            ack = bridge.take_ack(command_id) if hasattr(bridge, "take_ack") else None
            if ack:
                if ack.get("ok"):
                    result = {
                        "command_id": command_id, "status": "accepted",
                        "request_id": command_id,
                        "origin_request_id": ack.get("origin_request_id")
                        or result.get("origin_request_id"),
                    }
                    if ack.get("task_id"):
                        result["task_id"] = ack["task_id"]
                    if ack.get("schedule_id"):
                        result["schedule_id"] = ack["schedule_id"]
                    store.finish_command(command_id, "accepted", result)
                else:
                    result = {
                        "command_id": command_id, "status": "rejected",
                        "origin_request_id": ack.get("origin_request_id")
                        or result.get("origin_request_id"),
                        "error": ack.get("error", "Robot rejected command"),
                    }
                    store.finish_command(command_id, "rejected", result)
        return jsonify(result)

    @app.get(prefix + "/audit")
    @require_role("Engineer")
    def platform_audit(robot_id):
        try:
            limit = max(1, min(int(request.args.get("limit", "100")), 200))
            before_text = request.args.get("before")
            before = int(before_text) if before_text else None
            if before is not None and before < 1:
                raise ValueError()
        except ValueError:
            abort(400, "limit and before must be positive integers.")
        rows = store.audit_history(
            robot_id, limit=limit, before=before,
            actor=request.args.get("actor"), request_id=request.args.get("request_id"),
            method=request.args.get("method"), from_time=request.args.get("from"),
            to_time=request.args.get("to"),
        )
        return jsonify({"entries": rows, "next_before": rows[-1]["id"] if len(rows) == limit else None})

    @app.get(prefix + "/faults")
    @require_role("Viewer")
    def platform_faults(robot_id):
        active = request.args.get("active") == "true"
        try:
            limit = min(500, max(1, int(request.args.get("limit", "100"))))
            offset = max(0, int(request.args.get("offset", "0")))
        except ValueError:
            abort(400, "limit and offset must be integers.")
        status = request.args.get("status", "active" if active else "all")
        if status not in {"all", "active", "resolved", "cleared"}:
            abort(400, "Unsupported fault status filter.")
        module = request.args.get("module", "").strip()[:120]
        severity = request.args.get("severity", "").upper()
        if severity not in {"", "WARNING", "ERROR"}:
            abort(400, "Unsupported fault severity filter.")

        def fault_time_filter(name):
            raw = request.args.get(name)
            if not raw:
                return None
            try:
                value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                abort(400, f"{name} must be an RFC3339 timestamp with timezone.")
            if value.tzinfo is None:
                abort(400, f"{name} must include a timezone.")
            return value.astimezone(timezone.utc).isoformat()

        from_time = fault_time_filter("from")
        to_time = fault_time_filter("to")
        if from_time and to_time and to_time < from_time:
            abort(400, "to must be later than from.")
        filters = {
            "module": module or None,
            "severity": severity or None,
            "status": status,
            "from_time": from_time,
            "to_time": to_time,
        }
        total = store.fault_count(robot_id, **filters)
        faults = store.faults(robot_id, limit=limit, offset=offset, **filters)
        return jsonify({
            "faults": faults, "total": total, "limit": limit, "offset": offset,
            "next_offset": offset + limit if offset + limit < total else None,
        })

    @app.get(prefix + "/faults/<fault_id>")
    @require_role("Viewer")
    def platform_fault(robot_id, fault_id):
        fault = store.fault(robot_id, fault_id)
        if not fault:
            abort(404, "Fault not found.")
        return jsonify(fault)

    @app.post(prefix + "/faults/<fault_id>/ack")
    @require_role("Operator")
    def platform_ack_fault(robot_id, fault_id):
        if not store.fault(robot_id, fault_id):
            abort(404, "Fault not found.")
        store.ack_fault(robot_id, fault_id, g.identity["username"])
        return jsonify(store.fault(robot_id, fault_id))

    @app.post(prefix + "/faults/<fault_id>/clear")
    @require_role("Engineer")
    def platform_clear_fault(robot_id, fault_id):
        fault = store.fault(robot_id, fault_id)
        if not fault:
            abort(404, "Fault not found.")
        if fault["resolved_at"] is None:
            abort(409, "Active fault must be resolved on the robot first.")
        if fault["cleared_at"] is not None:
            abort(409, "Fault is already cleared.")
        store.clear_fault(robot_id, fault_id)
        return jsonify(store.fault(robot_id, fault_id))

    @app.get(prefix + "/config")
    @require_role("Viewer")
    def platform_config(robot_id):
        return jsonify({"scope": "platform", **store.config()})

    @app.get(prefix + "/config/versions")
    @require_role("Viewer")
    def platform_config_versions(robot_id):
        return jsonify({"versions": store.config_versions()})

    @app.put(prefix + "/config")
    @require_role("Engineer")
    def platform_create_config(robot_id):
        bridge = bridge_or_503()
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) != {"low_battery_threshold"}:
            abort(400, "Only low_battery_threshold is supported in platform config.")
        threshold = payload["low_battery_threshold"]
        if isinstance(threshold, bool) or not isinstance(threshold, int) or not 1 <= threshold <= 99:
            abort(400, "low_battery_threshold must be an integer from 1 to 99.")
        try:
            expected_version = int(request.headers.get("If-Match", "").strip('"'))
        except ValueError:
            abort(412, "Config version changed; reload before saving.")
        try:
            version = store.create_config(payload, g.identity["username"], expected_version)
        except ValueError:
            abort(412, "Config version changed; reload before saving.")
        config = store.config(version)
        bridge.set_battery_config(config)
        return jsonify({"scope": "platform", "runtime_delivery": "published", **config}), 201

    @app.post(prefix + "/config/versions/<int:version>/activate")
    @require_role("Engineer")
    def platform_activate_config(robot_id, version):
        bridge = bridge_or_503()
        if not store.activate_config(version):
            abort(404, "Config version not found.")
        config = store.config(version)
        bridge.set_battery_config(config)
        return jsonify({"scope": "platform", "runtime_delivery": "published", **config})

    log_root = Path(setting("LOG_ROOT", "~/.ros/log")).expanduser().resolve()
    daily_log_root = log_root / "daily"
    raw_log_retention = setting("LOG_RETENTION_DAYS", "0").strip()
    try:
        log_retention_days = int(raw_log_retention)
        if log_retention_days < 0:
            raise ValueError("must be zero or a positive number of days")
    except ValueError as error:
        app.logger.error(
            "Invalid ROBOTPILOT_LOG_RETENTION_DAYS=%r: %s; pruning disabled",
            raw_log_retention,
            error,
        )
        log_retention_days = 0
    last_log_prune = [0.0]

    def prune_logs_if_due(force=False):
        if log_retention_days <= 0:
            return []
        now_monotonic = time.monotonic()
        if not force and now_monotonic - last_log_prune[0] < 3600:
            return []
        last_log_prune[0] = now_monotonic
        try:
            removed = prune_expired_logs(log_root, log_retention_days)
        except (OSError, ValueError) as error:
            app.logger.error("Log retention cleanup failed: %s", error)
            return []
        if removed:
            app.logger.info("Removed %d expired log file(s)", len(removed))
        return removed

    prune_logs_if_due(force=True)

    def log_id(path):
        relative = str(path.relative_to(log_root)).encode("utf-8")
        return base64.urlsafe_b64encode(relative).decode("ascii").rstrip("=")

    log_level_pattern = re.compile(r"\[(?:DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|CRITICAL|WRN|ERR)\]", re.IGNORECASE)
    ansi_escape_pattern = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

    def log_module(path, snippets):
        """Find the ROS logger name in a console log, with a filename fallback."""
        daily_name = re.fullmatch(r"(.+)_\d{4}-\d{2}-\d{2}", path.stem)
        if daily_name and path.parent == daily_log_root:
            return daily_name.group(1)
        for snippet in snippets:
            for line in snippet.splitlines():
                clean_line = ansi_escape_pattern.sub("", line)
                level = log_level_pattern.search(clean_line)
                if not level:
                    continue
                # ROS console records put the logger name in the last bracket
                # immediately before the message colon; timestamp brackets are
                # ignored by this rule.
                tail = clean_line[level.end():]
                tagged_names = list(re.finditer(r"\[([^\]]+)\]\s*:", tail))
                if tagged_names:
                    return tagged_names[-1].group(1).strip()

        stem = path.stem
        generated_name = re.match(r"^(.+?)_\d+_\d{10,}$", stem)
        if generated_name:
            module_name = generated_name.group(1)
            if module_name.lower() == "python3":
                return "ROS Python node"
            return module_name
        if stem == "launch":
            return "ROS launch"
        return stem or "ROS log"

    def human_log_name(path, module_name, modified_at):
        """Create a stable, human-readable label and download filename."""
        stem = path.stem
        daily_name = re.fullmatch(r".+_(\d{4}-\d{2}-\d{2})", stem)
        if daily_name and path.parent == daily_log_root:
            return f"{module_name.replace('_', ' ')} · {daily_name.group(1)}", path.name
        generated_name = re.match(r"^.+?_\d+_(\d{10,})$", stem)
        started_at = None
        if generated_name:
            raw_timestamp = generated_name.group(1)
            try:
                started_at = datetime.fromtimestamp(int(raw_timestamp) / 1000, timezone.utc)
            except (OverflowError, OSError, ValueError):
                started_at = None
        started_at = started_at or modified_at
        timestamp = started_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        safe_module = re.sub(r"[^A-Za-z0-9._-]+", "_", module_name).strip("._-") or "ros_log"
        compact_timestamp = started_at.astimezone(timezone.utc).strftime("%Y%m%d_%H%M%S")
        readable_module = module_name.replace("_", " ")
        return f"{readable_module} · {timestamp}", f"{safe_module}_{compact_timestamp}.log"

    def log_path(encoded):
        try:
            relative = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8")
            candidate = log_root / relative
            path = candidate.resolve(strict=True)
        except (ValueError, UnicodeDecodeError, binascii.Error):
            abort(404, "Log not found.")
        except OSError:
            abort(404, "Log not found.")
        if candidate.is_symlink() or path.parent != daily_log_root or not path.is_file() or path.suffix != ".log":
            abort(404, "Log not found.")
        return path

    @app.get(prefix + "/logs")
    @require_role("Viewer")
    def platform_logs(robot_id):
        prune_logs_if_due()
        module = request.args.get("module", "")[:100]
        task_id = request.args.get("task_id", "")[:100]
        fault_code = request.args.get("fault_code", "")[:100]
        def time_filter(name):
            raw = request.args.get(name)
            if not raw:
                return None
            try:
                value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                abort(400, f"{name} must be an RFC3339 timestamp with timezone.")
            if value.tzinfo is None:
                abort(400, f"{name} must include a timezone.")
            return value.astimezone(timezone.utc)

        from_time = time_filter("from")
        to_time = time_filter("to")
        if from_time and to_time and to_time < from_time:
            abort(400, "to must be later than from.")
        try:
            limit = int(request.args.get("limit", "50"))
            offset = int(request.args.get("offset", "0"))
        except ValueError:
            abort(400, "limit and offset must be integers.")
        if not 1 <= limit <= 200 or not 0 <= offset <= 100000:
            abort(400, "limit must be 1–200 and offset 0–100000.")
        files = []
        truncated = False
        scanned = 0
        if daily_log_root.is_dir():
            for path in daily_log_root.glob("*.log"):
                if scanned >= 2000:
                    truncated = True
                    break
                scanned += 1
                try:
                    resolved = path.resolve(strict=True)
                    if path.is_symlink() or resolved.parent != daily_log_root or not resolved.is_file():
                        continue
                except OSError:
                    continue
                stat = resolved.stat()
                # Empty files are generated by ROS process launch but contain
                # no output and cannot help with normal operation or diagnosis.
                if stat.st_size == 0:
                    continue
                modified_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
                if from_time and modified_at < from_time:
                    continue
                if to_time and modified_at > to_time:
                    continue
                try:
                    if task_id or fault_code:
                        found_task = not task_id
                        found_fault = not fault_code
                        with resolved.open("r", encoding="utf-8", errors="replace") as stream:
                            for line in stream:
                                found_task = found_task or task_id in line
                                found_fault = found_fault or fault_code in line
                                if found_task and found_fault:
                                    break
                        if not (found_task and found_fault):
                            continue
                        snippets = []
                    else:
                        with resolved.open("rb") as stream:
                            first = stream.read(32768).decode("utf-8", errors="replace")
                            if stat.st_size > 32768:
                                stream.seek(max(0, stat.st_size - 32768))
                            last = stream.read(32768).decode("utf-8", errors="replace")
                        snippets = [first, last]
                except OSError:
                    continue
                module_name = log_module(path, snippets)
                if module and module.lower() not in module_name.lower() and module.lower() not in str(path.relative_to(log_root)).lower():
                    continue
                display_name, download_name = human_log_name(path, module_name, modified_at)
                files.append({
                    "log_id": log_id(path), "name": path.name, "size": stat.st_size,
                    "modified_at": modified_at.isoformat(),
                    "module": module_name, "display_name": display_name,
                    "download_name": download_name,
                })
        files.sort(key=lambda item: item["modified_at"], reverse=True)
        page = files[offset:offset + limit]
        next_offset = offset + len(page) if offset + len(page) < len(files) else None
        return jsonify({
            "logs": page, "total": len(files), "limit": limit, "offset": offset,
            "next_offset": next_offset, "truncated": truncated,
            "time_field": "modified_at",
        })

    @app.get(prefix + "/logs/<log_id>/download")
    @require_role("Operator")
    def platform_download_log(robot_id, log_id):
        path = log_path(log_id)
        stat = path.stat()
        with path.open("rb") as stream:
            first_chunk = stream.read(32768).decode("utf-8", errors="replace")
        module_name = log_module(path, [first_chunk])
        _, download_name = human_log_name(
            path, module_name, datetime.fromtimestamp(stat.st_mtime, timezone.utc)
        )
        return send_file(path, as_attachment=True, download_name=download_name)

    @app.get(prefix + "/assets")
    @require_role("Viewer")
    def s1_assets(robot_id):
        map_id = request.args.get("map_id")
        with store.connect() as db:
            rows = db.execute(
                "SELECT * FROM assets WHERE robot_id=? AND (? IS NULL OR map_id=?) ORDER BY name LIMIT 200",
                (robot_id, map_id, map_id),
            ).fetchall()
            assets = [{**dict(row), "metadata": json.loads(row["metadata_json"])} for row in rows]
            for asset in assets:
                links = db.execute(
                    "SELECT waypoint_id FROM asset_waypoints WHERE robot_id=? AND asset_id=? ORDER BY waypoint_id",
                    (robot_id, asset["asset_id"]),
                ).fetchall()
                asset["waypoint_ids"] = [link["waypoint_id"] for link in links]
        return jsonify({"assets": assets})

    @app.post(prefix + "/assets")
    @require_role("Engineer")
    def s1_create_asset(robot_id):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or not isinstance(body.get("name"), str) or not 1 <= len(body["name"].strip()) <= 100:
            abort(400, "Asset name is required (1–100 characters).")
        if not isinstance(body.get("map_id"), str) or not body["map_id"]:
            abort(400, "Asset map_id is required.")
        metadata = body.get("metadata", {})
        try:
            metadata_size = len(json.dumps(metadata, allow_nan=False))
        except (TypeError, ValueError):
            metadata_size = 8193
        if not isinstance(metadata, dict) or metadata_size > 8192:
            abort(400, "Asset metadata must be a small object.")
        identity = ensure_current_map(robot_id, body["map_id"])
        asset_id = str(uuid.uuid4())
        now = utc_now()
        with store.connect() as db:
            db.execute(
                "INSERT INTO assets(robot_id,asset_id,map_id,map_version_id,name,metadata_json,created_at,updated_at,revision) VALUES (?,?,?,?,?,?,?,?,1)",
                (robot_id, asset_id, body["map_id"], identity.get("map_version_id"), body["name"].strip(),
                 json.dumps(metadata, allow_nan=False), now, now),
            )
        return jsonify({"asset_id": asset_id, "map_id": body["map_id"], "map_version_id": identity.get("map_version_id"), "revision": 1}), 201

    @app.patch(prefix + "/assets/<asset_id>")
    @require_role("Engineer")
    def s1_update_asset(robot_id, asset_id):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) - {"name", "metadata", "map_id", "active"}:
            abort(400, "Unsupported asset fields")
        with store.connect() as db:
            row = db.execute("SELECT * FROM assets WHERE robot_id=? AND asset_id=?", (robot_id, asset_id)).fetchone()
        if not row:
            abort(404, "Asset not found")
        revision = expected_revision()
        if revision != row["revision"]:
            abort(412, "Asset revision changed; reload before editing.")
        current_metadata = json.loads(row["metadata_json"])
        merged_meta = body.get("metadata", current_metadata)
        try:
            metadata_size = len(json.dumps(merged_meta, allow_nan=False))
        except (TypeError, ValueError):
            metadata_size = 8193
        if not isinstance(merged_meta, dict) or metadata_size > 8192:
            abort(400, "Asset metadata must be a small object")
        name = body.get("name", row["name"])
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            abort(400, "Asset name is required (1–100 characters)")
        map_id = body.get("map_id", row["map_id"])
        identity = ensure_current_map(robot_id, map_id)
        merged_meta = {**merged_meta, "active": body.get("active", current_metadata.get("active", True))}
        if not isinstance(merged_meta["active"], bool):
            abort(400, "active must be a boolean")
        with store.connect() as db:
            changed = db.execute("UPDATE assets SET name=?,map_id=?,map_version_id=?,metadata_json=?,updated_at=?,revision=revision+1 WHERE robot_id=? AND asset_id=? AND revision=?",
                                 (name.strip(), map_id, identity.get("map_version_id"), json.dumps(merged_meta, allow_nan=False), utc_now(), robot_id, asset_id, revision)).rowcount
        if not changed:
            abort(412, "Asset revision changed; reload before editing.")
        return jsonify({"asset_id": asset_id, "name": name.strip(), "map_id": map_id,
                        "map_version_id": identity.get("map_version_id"), "metadata": merged_meta,
                        "revision": revision + 1})

    @app.get(prefix + "/assets/<asset_id>/waypoints")
    @require_role("Viewer")
    def s1_asset_waypoints(robot_id, asset_id):
        with store.connect() as db:
            asset = db.execute("SELECT asset_id FROM assets WHERE robot_id=? AND asset_id=?", (robot_id, asset_id)).fetchone()
            if not asset:
                abort(404, "Asset not found")
            rows = db.execute("""SELECT w.*, aw.created_at AS linked_at FROM asset_waypoints aw
                JOIN waypoints w ON w.robot_id=aw.robot_id AND w.waypoint_id=aw.waypoint_id
                WHERE aw.robot_id=? AND aw.asset_id=? ORDER BY w.name""", (robot_id, asset_id)).fetchall()
        return jsonify({"waypoints": [dict(row) for row in rows]})

    @app.put(prefix + "/assets/<asset_id>/waypoints/<waypoint_id>")
    @require_role("Engineer")
    def s1_link_asset_waypoint(robot_id, asset_id, waypoint_id):
        with store.connect() as db:
            asset = db.execute("SELECT map_id,map_version_id FROM assets WHERE robot_id=? AND asset_id=?", (robot_id, asset_id)).fetchone()
            waypoint = db.execute("SELECT map_id,map_version_id FROM waypoints WHERE robot_id=? AND waypoint_id=?", (robot_id, waypoint_id)).fetchone()
            if not asset or not waypoint:
                abort(404, "Asset or waypoint not found")
            if (asset["map_id"], asset["map_version_id"]) != (waypoint["map_id"], waypoint["map_version_id"]):
                abort(409, "Asset and waypoint map versions must match")
            db.execute("INSERT OR IGNORE INTO asset_waypoints(robot_id,asset_id,waypoint_id,created_at,created_by) VALUES (?,?,?,?,?)",
                       (robot_id, asset_id, waypoint_id, utc_now(), g.identity["username"]))
        return jsonify({"asset_id": asset_id, "waypoint_id": waypoint_id, "linked": True}), 201

    @app.delete(prefix + "/assets/<asset_id>/waypoints/<waypoint_id>")
    @require_role("Engineer")
    def s1_unlink_asset_waypoint(robot_id, asset_id, waypoint_id):
        with store.connect() as db:
            changed = db.execute(
                "DELETE FROM asset_waypoints WHERE robot_id=? AND asset_id=? AND waypoint_id=?",
                (robot_id, asset_id, waypoint_id),
            ).rowcount
        if not changed:
            abort(404, "Asset waypoint link not found")
        return "", 204

    @app.get(prefix + "/inspection/results")
    @require_role("Viewer")
    def s1_results(robot_id):
        try:
            limit = int(request.args.get("limit", "50"))
            offset = int(request.args.get("offset", "0"))
        except ValueError:
            abort(400, "limit and offset must be integers")
        if not 1 <= limit <= 200 or not 0 <= offset <= 100000:
            abort(400, "limit must be 1–200 and offset 0–100000")
        filters = {key: request.args.get(key) for key in ("task_id", "waypoint_id", "asset_id", "outcome", "source")}
        if filters["outcome"] and filters["outcome"] not in ("NORMAL", "ABNORMAL", "INCONCLUSIVE", "NOT_APPLICABLE"):
            abort(400, "Invalid inspection outcome filter")
        if filters["source"] and filters["source"] not in ("fixture", "simulation", "hardware"):
            abort(400, "Invalid inspection source filter")
        with store.connect() as db:
            where = ["r.robot_id=?"]
            values = [robot_id]
            for key in ("task_id", "waypoint_id", "outcome", "source"):
                if filters[key]:
                    column = "source" if key == "source" else key
                    where.append(f"r.{column}=?")
                    values.append(filters[key])
            if filters["asset_id"]:
                where.append("""(r.asset_id=? OR EXISTS (
                    SELECT 1 FROM inspection_result_assets ira
                    WHERE ira.robot_id=r.robot_id
                    AND ira.inspection_result_id=r.inspection_result_id AND ira.asset_id=?))""")
                values.extend((filters["asset_id"], filters["asset_id"]))
            rows = db.execute(
                f"SELECT r.* FROM inspection_results r WHERE {' AND '.join(where)} "
                "ORDER BY r.occurred_at DESC,r.inspection_result_id LIMIT ? OFFSET ?",
                (*values, limit, offset),
            ).fetchall()
        return jsonify({"results": [{**dict(row), "details": json.loads(row["details_json"])} for row in rows],
                        "limit": limit, "offset": offset,
                        "next_offset": offset + len(rows) if len(rows) == limit else None})

    @app.get(prefix + "/inspection/results/<result_id>")
    @require_role("Viewer")
    def s1_result_detail(robot_id, result_id):
        with store.connect() as db:
            row = db.execute("SELECT * FROM inspection_results WHERE robot_id=? AND inspection_result_id=?", (robot_id, result_id)).fetchone()
            if not row:
                abort(404, "Inspection result not found")
            evidence = db.execute("""SELECT evidence_id,media_type,checksum,available,recorded_at
                FROM event_evidence WHERE robot_id=? AND inspection_result_id=? ORDER BY recorded_at""",
                                  (robot_id, result_id)).fetchall()
        return jsonify({**dict(row), "details": json.loads(row["details_json"]),
                        "evidence": [dict(item) for item in evidence]})

    @app.get(prefix + "/inspection/tasks")
    @require_role("Viewer")
    def s1_inspection_tasks(robot_id):
        """Search recent inspection runs from the MissionManager authority."""
        try:
            limit = int(request.args.get("limit", "20"))
            offset = int(request.args.get("offset", "0"))
        except ValueError:
            abort(400, "limit and offset must be integers")
        if not 1 <= limit <= 50 or not 0 <= offset <= 500:
            abort(400, "limit must be 1–50 and offset 0–500")
        query = request.args.get("q", "").strip().lower()
        status_filter = request.args.get("status", "").strip().lower()
        allowed_statuses = {"running", "paused", "succeeded", "failed", "cancelled"}
        if status_filter and status_filter not in allowed_statuses:
            abort(400, "Invalid inspection task status filter")

        def parse_time_filter(name):
            raw = request.args.get(name, "").strip()
            if not raw:
                return None
            try:
                value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                abort(400, f"{name} must be an RFC3339 timestamp")
            if value.tzinfo is None:
                abort(400, f"{name} must include a timezone")
            return value.astimezone(timezone.utc)

        since = parse_time_filter("since")
        until = parse_time_filter("until")
        if since and until and since > until:
            abort(400, "since must not be later than until")

        snapshot = bridge_or_503().snapshot()
        if not snapshot.get("mission_online"):
            abort(503, "Mission manager status is unavailable")
        mission_state = snapshot.get("mission") or {}
        candidates = [mission_state.get("run"), *(mission_state.get("history") or [])]
        seen = set()
        inspections = []
        for task in candidates:
            if not isinstance(task, dict):
                continue
            task_id = task.get("task_id") or task.get("taskId")
            if not isinstance(task_id, str) or not task_id or task_id in seen:
                continue
            seen.add(task_id)
            steps = task.get("steps") if isinstance(task.get("steps"), list) else []
            is_inspection = str(task.get("mission_id", task.get("missionId", ""))).startswith("inspection-")
            is_inspection = is_inspection or any(
                isinstance(step, dict) and step.get("type") == "inspection_action" for step in steps
            )
            if not is_inspection:
                continue
            searchable = " ".join((task_id, str(task.get("mission_id", "")),
                                   str(task.get("mission_name", "")))).lower()
            if query and query not in searchable:
                continue
            status = str(task.get("status", "unknown")).lower()
            if status_filter and status != status_filter:
                continue
            started_at = task.get("started_at")
            try:
                started = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
                if started.tzinfo is None:
                    continue
                started = started.astimezone(timezone.utc)
            except (TypeError, ValueError):
                continue
            if since and started < since or until and started > until:
                continue
            inspections.append({
                "task_id": task_id,
                "mission_id": task.get("mission_id", task.get("missionId")),
                "mission_name": task.get("mission_name", ""),
                "status": status,
                "step_index": task.get("step_index", task.get("stepIndex", 0)),
                "steps_total": len(steps),
                "started_at": started_at,
                "updated_at": task.get("updated_at"),
                "ended_at": task.get("ended_at"),
                "reason": task.get("reason", ""),
                "events": task.get("events", []),
            })
        inspections.sort(key=lambda item: item["started_at"], reverse=True)
        page = inspections[offset:offset + limit]
        return jsonify({"tasks": page, "limit": limit, "offset": offset,
                        "next_offset": offset + len(page) if offset + len(page) < len(inspections) else None,
                        "available_history_runs": len(candidates),
                        "history_window_limited": len(mission_state.get("history") or []) >= 10})

    @app.get(prefix + "/inspection/evidence/<evidence_id>")
    @require_role("Viewer")
    def s1_evidence_metadata(robot_id, evidence_id):
        with store.connect() as db:
            row = db.execute("""SELECT evidence_id,inspection_result_id,media_type,checksum,
                available,recorded_at FROM event_evidence WHERE robot_id=? AND evidence_id=?""",
                             (robot_id, evidence_id)).fetchone()
        if not row:
            abort(404, "Evidence metadata not found")
        return jsonify({**dict(row), "media_status": "UNAVAILABLE" if not row["available"] else "AVAILABLE",
                        "media_url": None})

    @app.get(prefix + "/waypoints/<waypoint_id>/action-plan")
    @require_role("Viewer")
    def s1_action_plan(robot_id, waypoint_id):
        with store.connect() as db:
            row = db.execute("SELECT * FROM waypoint_action_plans WHERE robot_id=? AND waypoint_id=?", (robot_id, waypoint_id)).fetchone()
        if not row:
            abort(404, "Action plan not found")
        return jsonify({"waypoint_id": waypoint_id, "revision": row["revision"],
                        "actions": json.loads(row["actions_json"]), "executable": False})

    @app.put(prefix + "/waypoints/<waypoint_id>/action-plan")
    @require_role("Engineer")
    def s1_save_action_plan(robot_id, waypoint_id):
        waypoint = store.waypoint(robot_id, waypoint_id)
        if not waypoint:
            abort(404, "Waypoint not found")
        body = request.get_json(silent=True)
        actions = body.get("actions") if isinstance(body, dict) else None
        if not isinstance(actions, list) or len(actions) > 20:
            abort(400, "Action plan must contain at most 20 actions")
        for action in actions:
            if (not isinstance(action, dict) or action.get("kind") not in ("wait", "capture", "detect", "broadcast")
                    or not isinstance(action.get("timeout_ms"), int) or not 100 <= action["timeout_ms"] <= 120000):
                abort(400, "Action kind or timeout is invalid")
            if set(action) - {"kind", "timeout_ms", "detector_types", "asset_ids", "parameters", "required", "retries"}:
                abort(400, "Unsupported action-plan field")
            if action.get("kind") == "detect" and (not isinstance(action.get("detector_types"), list)
                                                       or not action["detector_types"]
                                                       or any(not isinstance(v, str) or not v or len(v) > 64 for v in action["detector_types"])):
                abort(400, "Detect actions need detector type identifiers")
            if not isinstance(action.get("asset_ids", []), list) or len(action.get("asset_ids", [])) > 100:
                abort(400, "Invalid action asset references")
            parameters = action.get("parameters", {})
            try:
                parameters_size = len(json.dumps(parameters, allow_nan=False))
            except (TypeError, ValueError):
                parameters_size = 4097
            if not isinstance(parameters, dict) or parameters_size > 4096:
                abort(400, "Action parameters must be a small JSON object")
        revision = expected_revision(allow_zero=True)
        with store.connect() as db:
            current = db.execute("SELECT revision FROM waypoint_action_plans WHERE robot_id=? AND waypoint_id=?", (robot_id, waypoint_id)).fetchone()
            if revision != (current["revision"] if current else 0):
                abort(412, "Action plan revision changed")
            new_revision = revision + 1
            db.execute(
                """INSERT INTO waypoint_action_plans(robot_id,waypoint_id,revision,actions_json,updated_at)
                   VALUES (?,?,?,?,?) ON CONFLICT(robot_id,waypoint_id) DO UPDATE SET
                   revision=excluded.revision,actions_json=excluded.actions_json,updated_at=excluded.updated_at""",
                (robot_id, waypoint_id, new_revision, json.dumps(actions, allow_nan=False), utc_now()),
            )
        return jsonify({"waypoint_id": waypoint_id, "revision": new_revision,
                        "actions": actions, "executable": False})

    @app.post(prefix + "/inspection/tasks")
    @require_role("Operator")
    def s1_create_inspection_task(robot_id):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body) - {"name", "waypoint_ids", "points", "compile_only", "mission_id"}:
            abort(400, "Inspection task contains unsupported fields.")
        compile_only = body.get("compile_only", False)
        if not isinstance(compile_only, bool):
            abort(400, "compile_only must be a boolean.")
        name = body.get("name", "指定巡检")
        waypoint_ids = body.get("waypoint_ids")
        ordered_points = body.get("points")
        if ordered_points is not None and waypoint_ids is not None:
            abort(400, "Use either points or waypoint_ids, not both.")
        if ordered_points is None:
            if (not isinstance(waypoint_ids, list) or not 1 <= len(waypoint_ids) <= 50
                    or any(not isinstance(item, str) or not item or len(item) > 128 for item in waypoint_ids)
                    or len(set(waypoint_ids)) != len(waypoint_ids)):
                abort(400, "waypoint_ids must contain 1–50 unique waypoint IDs.")
            ordered_points = [{"waypoint_id": item, "execute_actions": True} for item in waypoint_ids]
        elif (not isinstance(ordered_points, list) or not 1 <= len(ordered_points) <= 50
              or any(not isinstance(item, dict) or set(item) != {"waypoint_id", "execute_actions"}
                     or not isinstance(item["waypoint_id"], str) or not 1 <= len(item["waypoint_id"]) <= 128
                     or not isinstance(item["execute_actions"], bool) for item in ordered_points)):
            abort(400, "points must contain 1–50 ordered waypoint references and execute_actions flags.")
        requested_mission_id = body.get("mission_id")
        if requested_mission_id is not None and (not isinstance(requested_mission_id, str)
                                                 or not requested_mission_id.startswith("inspection-")
                                                 or len(requested_mission_id) > 100):
            abort(400, "mission_id must identify an inspection mission.")
        if requested_mission_id and not compile_only:
            abort(400, "Updating and starting a mission in one request is not supported.")
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
            abort(400, "Inspection task name is required (1–120 characters).")
        idempotency_key = request.headers.get("Idempotency-Key", "")
        if not 8 <= len(idempotency_key) <= 128:
            abort(400, "Idempotency-Key must be 8–128 characters.")

        bridge = bridge_or_503()
        snapshot = bridge.snapshot()
        if not snapshot.get("mission_online"):
            abort(503, "Mission manager is offline.")
        if requested_mission_id:
            mission_state = snapshot.get("mission") or {}
            if not any(item.get("id") == requested_mission_id for item in mission_state.get("missions", [])):
                abort(404, "Inspection mission to update was not found.")
            if any(item.get("mission_id") == requested_mission_id and item.get("status") in ("RUNNING", "PAUSED", "running", "paused")
                   for item in [mission_state.get("run") or {}]):
                abort(409, "A running mission cannot be replaced.")
            if any(item.get("mission_id") == requested_mission_id for item in mission_state.get("schedules", [])):
                abort(409, "A scheduled mission cannot be replaced; remove its schedule first.")
        if not compile_only:
            readiness = autonomy_readiness(snapshot)
            if not readiness["ready"]:
                abort(409, "Inspection task is blocked: " + "; ".join(readiness["blockers"]))
        elif not snapshot.get("map_identity_online"):
            abort(503, "Current map identity is unavailable; template snapshot cannot be bound safely.")
        identity = snapshot.get("map_identity") or {}
        provider = (snapshot.get("mission") or {}).get("inspection_provider") or {}
        if not compile_only:
            if not provider.get("online") or provider.get("stale", True):
                abort(503, "Inspection provider capability or heartbeat is unavailable or stale.")
            runtime_mode = os.environ.get("ROBOT_MODE", "unknown").strip().lower()
            source_mode = provider.get("source_mode")
            if ((source_mode == "fixture" and runtime_mode != "simulation")
                    or (source_mode != "fixture" and source_mode != runtime_mode)):
                abort(409, "Inspection provider source mode does not match the robot runtime mode.")
        capability_map = {
            item.get("kind"): item for item in provider.get("actions", [])
            if isinstance(item, dict) and isinstance(item.get("kind"), str)
        }
        map_id = identity.get("map_id")
        map_version_id = identity.get("map_version_id")
        if not map_id or not map_version_id:
            abort(503, "Current map identity is unavailable.")

        steps = []
        try:
            with store.connect() as db:
                db.execute("BEGIN")
                for point_index, point in enumerate(ordered_points):
                    waypoint_id = point["waypoint_id"]
                    row = db.execute(
                        "SELECT * FROM waypoints WHERE robot_id=? AND waypoint_id=?",
                        (robot_id, waypoint_id),
                    ).fetchone()
                    if not row:
                        abort(404, f"Waypoint {waypoint_id} not found.")
                    if not row["enabled"]:
                        abort(409, f"Waypoint {row['name']} is disabled.")
                    if (row["map_id"], row["map_version_id"]) != (map_id, map_version_id):
                        abort(409, f"Waypoint {row['name']} is bound to a different map version.")
                    point_step_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{idempotency_key}:{point_index}:{waypoint_id}:waypoint"))
                    steps.append({
                        "id": point_step_id, "type": "waypoint",
                        "pose": {"x": row["x"], "y": row["y"],
                                 "z": math.sin(row["yaw"] / 2), "w": math.cos(row["yaw"] / 2)},
                        "waypointId": waypoint_id, "waypoint_id": waypoint_id,
                        "waypointName": row["name"],
                    })
                    if not point["execute_actions"]:
                        continue
                    plan = db.execute(
                        "SELECT actions_json FROM waypoint_action_plans WHERE robot_id=? AND waypoint_id=?",
                        (robot_id, waypoint_id),
                    ).fetchone()
                    if not plan:
                        abort(409, f"Waypoint {row['name']} has no saved action plan.")
                    actions = json.loads(plan["actions_json"])
                    if not actions:
                        abort(409, f"Waypoint {row['name']} has an empty action plan.")
                    linked_assets = [item[0] for item in db.execute(
                        "SELECT asset_id FROM asset_waypoints WHERE robot_id=? AND waypoint_id=? ORDER BY asset_id",
                        (robot_id, waypoint_id),
                    ).fetchall()]
                    for index, action in enumerate(actions):
                        if action.get("required", True) is not True or action.get("retries", 0) != 0:
                            abort(409, "Optional actions and per-action retries are not supported by this mission compiler.")
                        if action["kind"] == "wait":
                            steps.append({
                                "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{idempotency_key}:{point_index}:{waypoint_id}:wait:{index}")),
                                "type": "wait", "seconds": action["timeout_ms"] / 1000,
                                "waypoint_id": waypoint_id,
                            })
                            continue
                        capability = capability_map.get(action["kind"])
                        if not compile_only and (not capability or capability.get("supported") is not True):
                            abort(409, f"Provider does not support action {action['kind']}.")
                        detectors = action.get("detector_types", [])
                        supported_detectors = capability.get("detectors", []) if capability else []
                        if not compile_only and detectors and not set(detectors).issubset(set(supported_detectors)):
                            abort(409, "Provider does not support all configured detector types.")
                        asset_ids = action.get("asset_ids") or linked_assets
                        if any(not isinstance(asset_id, str) or not asset_id for asset_id in asset_ids):
                            abort(400, "Action asset IDs are invalid.")
                        for asset_id in asset_ids:
                            asset = db.execute(
                                "SELECT map_id,map_version_id,metadata_json FROM assets WHERE robot_id=? AND asset_id=?",
                                (robot_id, asset_id),
                            ).fetchone()
                            if not asset:
                                abort(404, f"Asset {asset_id} not found.")
                            metadata = json.loads(asset["metadata_json"])
                            if (asset["map_id"], asset["map_version_id"]) != (map_id, map_version_id):
                                abort(409, f"Asset {asset_id} is bound to a different map version.")
                            if metadata.get("active", True) is not True:
                                abort(409, f"Asset {asset_id} is disabled.")
                        steps.append({
                            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{idempotency_key}:{point_index}:{waypoint_id}:action:{index}")),
                            "type": "inspection_action", "action": action["kind"],
                            "waypoint_id": waypoint_id, "timeout_ms": action["timeout_ms"],
                            "detector_types": detectors, "asset_ids": asset_ids,
                            "parameters": action.get("parameters", {}),
                        })
        except sqlite3.Error as error:
            abort(503, f"Inspection plan could not be read consistently: {error}")
        if len(steps) > 200:
            abort(400, "Compiled inspection task exceeds the 200-step mission limit.")
        if waypoint_ids is not None and not any(step["type"] == "inspection_action" for step in steps):
            abort(409, "Inspection task needs at least one provider action.")

        mission_seed = json_hash({"robot_id": robot_id, "key": idempotency_key, "body": body})
        mission_id = requested_mission_id or "inspection-" + mission_seed[:32]
        mission = {
            "id": mission_id, "name": name.strip(), "steps": steps,
            "map_id": map_id, "map_version_id": map_version_id,
        }
        save_key = hashlib.sha256((idempotency_key + ":mission-save").encode()).hexdigest()
        save_response, save_status = dispatch(
            robot_id, "mission.save", {"command": "save", "mission": mission},
            idempotency_key=save_key,
        )
        save_result = save_response.get_json()
        if save_result.get("status") != "accepted":
            return jsonify({"mission_id": mission_id, "mission": save_result}), save_status
        if compile_only:
            return jsonify({"status": "compiled", "mission_id": mission_id,
                            "task_id": None, "schedule_path": "/scheduler"}), 201
        start_key = hashlib.sha256((idempotency_key + ":task-start").encode()).hexdigest()
        start_response, start_status = dispatch(
            robot_id, "task.start", {"command": "start", "mission_id": mission_id},
            idempotency_key=start_key,
        )
        start_result = start_response.get_json()
        return jsonify({
            "mission_id": mission_id, "task_id": start_result.get("task_id"),
            "status": start_result.get("status"), "command": start_result,
        }), start_status

    @app.get(prefix + "/inspection/alerts")
    @require_role("Viewer")
    def s1_alerts(robot_id):
        map_id = request.args.get("map_id", "").strip()
        map_version_id = request.args.get("map_version_id", "").strip()
        if bool(map_id) != bool(map_version_id):
            abort(400, "map_id and map_version_id must be provided together")
        try:
            limit = int(request.args.get("limit", "100"))
            offset = int(request.args.get("offset", "0"))
        except ValueError:
            abort(400, "limit and offset must be integers")
        if not 1 <= limit <= 200 or not 0 <= offset <= 100000:
            abort(400, "limit must be 1–200 and offset 0–100000")
        with store.connect() as db:
            where = ["a.robot_id=?"]
            values = [robot_id]
            if map_id:
                where.extend(("a.map_id=?", "a.map_version_id=?"))
                values.extend((map_id, map_version_id))
            rows = db.execute("""SELECT a.*,r.details_json AS result_details_json
                FROM inspection_alerts a LEFT JOIN inspection_results r
                ON r.robot_id=a.robot_id AND r.inspection_result_id=a.inspection_result_id
                WHERE """ + " AND ".join(where) +
                " ORDER BY a.last_seen DESC,a.alert_id LIMIT ? OFFSET ?",
                (*values, limit + 1, offset),
            ).fetchall()
        alerts = [inspection_alert_payload(row) for row in rows[:limit]]
        return jsonify({"alerts": alerts, "limit": limit, "offset": offset,
                        "next_offset": offset + limit if len(rows) > limit else None})

    @app.get(prefix + "/inspection/alerts/<alert_id>")
    @require_role("Viewer")
    def s1_alert_detail(robot_id, alert_id):
        with store.connect() as db:
            row = db.execute("""SELECT a.*,r.details_json AS result_details_json
                FROM inspection_alerts a LEFT JOIN inspection_results r
                ON r.robot_id=a.robot_id AND r.inspection_result_id=a.inspection_result_id
                WHERE a.robot_id=? AND a.alert_id=?""", (robot_id, alert_id)).fetchone()
            if not row:
                abort(404, "Inspection alert not found")
            alert = inspection_alert_payload(row)
            evidence = db.execute("""SELECT evidence_id,media_type,checksum,available,recorded_at
                FROM event_evidence WHERE robot_id=? AND inspection_result_id=? ORDER BY recorded_at""",
                (robot_id, alert["inspection_result_id"]),
            ).fetchall()
        return jsonify({"alert": alert, "evidence": [dict(item) for item in evidence]})

    @app.patch(prefix + "/inspection/alerts/<alert_id>")
    @require_role("Operator")
    def s1_update_alert(robot_id, alert_id):
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or body.get("state") not in ("ACKNOWLEDGED", "IN_REVIEW", "RESOLVED", "CLOSED"):
            abort(400, "Invalid alert state")
        note = body.get("note", "")
        if not isinstance(note, str) or len(note) > 2000:
            abort(400, "Invalid alert note")
        revision = expected_revision()
        with store.connect() as db:
            current = db.execute("SELECT state,revision FROM inspection_alerts WHERE robot_id=? AND alert_id=?",
                                 (robot_id, alert_id)).fetchone()
            if not current:
                abort(404, "Inspection alert not found")
            allowed = {"OPEN": {"ACKNOWLEDGED"}, "ACKNOWLEDGED": {"IN_REVIEW", "RESOLVED"},
                       "IN_REVIEW": {"RESOLVED"}, "RESOLVED": {"IN_REVIEW", "CLOSED"}, "CLOSED": set()}
            if revision != current["revision"]:
                abort(412, "Alert revision changed; reload before editing")
            if body["state"] not in allowed.get(current["state"], set()):
                abort(409, "Invalid inspection alert state transition")
            changed = db.execute(
                "UPDATE inspection_alerts SET state=?,note=?,updated_by=?,revision=revision+1 WHERE robot_id=? AND alert_id=? AND revision=?",
                (body["state"], note, g.identity["username"], robot_id, alert_id, revision),
            ).rowcount
            if changed:
                store._append_event(db, robot_id, "inspection_alert_updated", {
                    "alert_id": alert_id, "from_state": current["state"], "state": body["state"],
                    "note": note, "actor": g.identity["username"],
                })
        if not changed:
            abort(412, "Alert revision changed or alert does not exist")
        return jsonify({"alert_id": alert_id, "state": body["state"], "revision": revision + 1})
