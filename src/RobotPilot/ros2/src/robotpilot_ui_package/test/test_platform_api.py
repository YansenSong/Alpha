import tempfile
import sqlite3
import os
import json
import base64
import math
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask, Response

from robotpilot_ui_package.auth import install_auth
from robotpilot_ui_package.platform_api import (
    PlatformStore,
    RobotBridge,
    audit_api_response,
    battery_config_payload,
    register_platform_api,
)
from mission_manager.store import MissionStore


class FakeBridge:
    def __init__(self):
        self.calls = []
        self.battery_scenarios = []
        self.battery_configs = []
        self.late_acks = {}

    def snapshot(self):
        return {
            "mission_online": True,
            "mission": {
                "missions": [{"id": "patrol", "name": "Patrol", "steps": []}],
                "inspection_provider": {
                    "online": True, "stale": False, "provider_id": "fixture-provider",
                    "source_mode": "fixture", "software_version": "fixture-v1",
                    "actions": [
                        {"kind": "capture", "supported": True, "detectors": []},
                        {"kind": "detect", "supported": True, "detectors": ["fire_smoke"]},
                        {"kind": "broadcast", "supported": True, "detectors": []},
                    ],
                },
                "run": None, "history": [],
                "schedules": [{
                    "schedule_id": "schedule-1", "name": "Morning", "mission_id": "patrol",
                    "recurrence": "daily", "timezone": "UTC", "local_time": "08:00",
                    "start_date": None, "weekdays": [], "enabled": True, "revision": 1,
                }],
                "schedule_runs": [{"schedule_id": "schedule-1", "status": "started"}],
            },
            "pose": {"x": 1, "y": 2, "yaw": 0},
            "pose_observed_at": "2026-10-08T00:00:00+00:00",
            "pose_online": True,
            "odom_online": True,
            "battery": 80,
            "battery_online": True,
            "battery_state": {
                "percent": 80,
                "source": "simulated",
                "simulated": True,
                "available": True,
                "charging": False,
                "low_battery": False,
                "observed_at": "2026-10-08T00:00:00+00:00",
                "stale": False,
            },
            "navigation": {"state": "WAITING_FOR_GOAL", "detail": ""},
            "navigation_online": True,
            "map_identity": {
                "map_id": "simulation/map-a", "map_version_id": "simulation/map-a",
                "group": "Simulation", "map": "map-a",
            },
            "map_identity_online": True,
            "map_identity_observed_at": "2026-10-08T00:00:00+00:00",
            "map_bundle": {"schema_version": 1, "ready": True,
                           "map_id": "simulation/map-a", "map_version_id": "simulation/map-a",
                           "bundle_id": "test-bundle", "globalmap_pcd_sha256": "test-pcd"},
            "map_bundle_online": True,
            "software_stop_state": {
                "active": False, "result": "confirmed", "durable": True,
                "observed_at": "2026-10-08T00:00:00+00:00",
            },
            "software_stop_online": True,
            "diagnostics": {},
        }

    def command(self, command, request_id):
        self.calls.append((command, request_id))
        if command.get("command") == "schedule.save":
            return {"request_id": request_id, "ok": True, "schedule_id": "schedule-new"}
        return {"request_id": request_id, "ok": True, "task_id": "task-123"}

    def take_ack(self, request_id):
        return self.late_acks.pop(request_id, None)

    def set_battery_scenario(self, scenario):
        self.battery_scenarios.append(scenario)

    def set_battery_config(self, config):
        self.battery_configs.append(config)


class PlatformApiTest(unittest.TestCase):
    @staticmethod
    def inspection_event(seq, *, result_id=None, waypoint_id="wp-1", asset_ids=None,
                         map_id="map-a", map_version_id="v1", outcome="ABNORMAL",
                         source="mission_manager"):
        observed_at = (datetime(2026, 10, 10, tzinfo=timezone.utc)
                       + timedelta(seconds=seq)).isoformat()
        result_id = result_id or f"result-{source}-{seq}"
        return {
            "schema_version": 1, "event_id": f"event-{source}-{seq}",
            "robot_id": "robot-001", "source": source, "source_seq": seq,
            "type": "inspection.result", "severity": "WARNING",
            "occurred_at": observed_at,
            "correlation": {"task_id": f"task-{source}-{seq}", "request_id": None},
            "payload": {
                "result_id": result_id, "action_run_id": f"action-{source}-{seq}",
                "task_id": f"task-{source}-{seq}", "step_id": f"step-{seq}",
                "status": "SUCCEEDED", "outcome": outcome, "source_mode": "fixture",
                "observed_at": observed_at, "map_id": map_id,
                "map_version_id": map_version_id, "waypoint_id": waypoint_id,
                "asset_ids": asset_ids or [], "detector_type": "fire_smoke",
            },
        }

    def test_alerts_are_scoped_to_waypoint_and_closed_episode_stays_traceable(self):
        self.store.ingest_robot_events("robot-001", [self.inspection_event(1, waypoint_id="wp-a")])
        self.store.ingest_robot_events("robot-001", [self.inspection_event(2, waypoint_id="wp-b")])
        alerts = self.client.get(self.base + "/inspection/alerts").json["alerts"]
        self.assertEqual(len(alerts), 2)
        self.store.ingest_robot_events("robot-001", [self.inspection_event(3, waypoint_id="wp-a")])
        alerts = self.client.get(self.base + "/inspection/alerts").json["alerts"]
        original = next(item for item in alerts if item["waypoint_id"] == "wp-a")
        self.assertEqual(original["occurrence_count"], 2)
        for revision, state in enumerate(("ACKNOWLEDGED", "RESOLVED", "CLOSED"),
                                         start=original["revision"]):
            response = self.client.patch(self.base + f"/inspection/alerts/{original['alert_id']}",
                                         json={"state": state},
                                         headers={"If-Match": f'"{revision}"'})
            self.assertEqual(response.status_code, 200)
        self.store.ingest_robot_events("robot-001", [self.inspection_event(4, waypoint_id="wp-a")])
        alerts = self.client.get(self.base + "/inspection/alerts").json["alerts"]
        self.assertEqual(len(alerts), 3)
        reopened = next(item for item in alerts if item["waypoint_id"] == "wp-a"
                        and item["state"] == "OPEN")
        self.assertNotEqual(reopened["alert_id"], original["alert_id"])
        self.assertEqual(reopened["occurrence_count"], 1)
        closed = self.client.get(self.base + f"/inspection/alerts/{original['alert_id']}").json["alert"]
        self.assertEqual(closed["state"], "CLOSED")
        self.assertEqual(closed["occurrence_count"], 2)

    def test_results_filter_every_linked_asset_once(self):
        event = self.inspection_event(1, asset_ids=["asset-a", "asset-b", "asset-b"],
                                      outcome="INCONCLUSIVE")
        self.store.ingest_robot_events("robot-001", [event])
        for asset_id in ("asset-a", "asset-b"):
            rows = self.client.get(self.base + f"/inspection/results?asset_id={asset_id}").json["results"]
            self.assertEqual([item["inspection_result_id"] for item in rows],
                             [event["payload"]["result_id"]])

    def test_concurrent_same_object_alert_ingest_has_one_active_episode(self):
        barrier = threading.Barrier(2)
        errors = []

        def ingest(source):
            try:
                barrier.wait()
                self.store.ingest_robot_events("robot-001", [
                    self.inspection_event(1, source=source, waypoint_id="wp-shared")])
            except Exception as error:
                errors.append(error)

        workers = [threading.Thread(target=ingest, args=(name,))
                   for name in ("provider-a", "provider-b")]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=10)
        self.assertFalse(errors)
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        alerts = self.client.get(self.base + "/inspection/alerts").json["alerts"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["occurrence_count"], 2)

    def test_map_alert_filter_runs_before_limit_and_supports_pagination(self):
        self.store.ingest_robot_events("robot-001", [self.inspection_event(
            1, map_id="target-map", map_version_id="target-v1")])
        other = [self.inspection_event(seq, waypoint_id=f"other-wp-{seq}",
                                       asset_ids=[f"asset-{seq}"],
                                       map_id="other-map", map_version_id="other-v1")
                 for seq in range(2, 103)]
        self.store.ingest_robot_events("robot-001", other[:100])
        self.store.ingest_robot_events("robot-001", other[100:])
        response = self.client.get(self.base +
                                   "/inspection/alerts?map_id=target-map&map_version_id=target-v1&limit=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["alerts"]), 1)
        self.assertEqual(response.json["alerts"][0]["map_id"], "target-map")
        self.assertIsNone(response.json["next_offset"])

    def test_schema_7_inspection_rows_migrate_without_losing_closed_alerts(self):
        path = str(Path(self.directory.name) / "legacy-inspection.sqlite3")
        old_event = self.inspection_event(1, asset_ids=["asset-a", "asset-b"])
        result = old_event["payload"]
        with sqlite3.connect(path) as db:
            db.executescript("""
                CREATE TABLE inspection_results (
                    robot_id TEXT NOT NULL,inspection_result_id TEXT NOT NULL,asset_id TEXT,
                    mission_id TEXT,task_id TEXT,waypoint_id TEXT,outcome TEXT NOT NULL,
                    source TEXT NOT NULL,occurred_at TEXT NOT NULL,details_json TEXT NOT NULL,
                    PRIMARY KEY(robot_id,inspection_result_id));
                CREATE TABLE inspection_alerts (
                    robot_id TEXT NOT NULL,alert_id TEXT NOT NULL,
                    inspection_result_id TEXT NOT NULL,category TEXT NOT NULL,
                    severity TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'OPEN',
                    note TEXT NOT NULL DEFAULT '',first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,occurrence_count INTEGER NOT NULL DEFAULT 1,
                    revision INTEGER NOT NULL DEFAULT 1,updated_by TEXT,
                    PRIMARY KEY(robot_id,alert_id));
                PRAGMA user_version = 7;
            """)
            db.execute("""INSERT INTO inspection_results VALUES (?,?,?,?,?,?,?,?,?,?)""",
                       ("robot-001", result["result_id"], "asset-a", None, result["task_id"],
                        result["waypoint_id"], "ABNORMAL", "fixture",
                        result["observed_at"], json.dumps(result)))
            db.execute("""INSERT INTO inspection_alerts
                (robot_id,alert_id,inspection_result_id,category,severity,state,
                 first_seen,last_seen) VALUES (?,?,?,?,?,?,?,?)""",
                ("robot-001", "alert-legacy", result["result_id"], "fire_smoke",
                 "WARNING", "CLOSED", result["observed_at"], result["observed_at"]),
            )
        upgraded = PlatformStore(path)
        self.assertEqual(upgraded.schema_version, 8)
        with upgraded.connect() as db:
            linked = db.execute("""SELECT asset_id FROM inspection_result_assets
                WHERE robot_id=? AND inspection_result_id=? ORDER BY asset_id""",
                ("robot-001", result["result_id"])).fetchall()
            self.assertEqual([row[0] for row in linked], ["asset-a", "asset-b"])
        fresh = self.inspection_event(1, source="migration", asset_ids=["asset-a", "asset-b"])
        upgraded.ingest_robot_events("robot-001", [fresh])
        with upgraded.connect() as db:
            alerts = db.execute("SELECT alert_id,state,episode FROM inspection_alerts ORDER BY episode").fetchall()
        self.assertEqual([(row["state"], row["episode"]) for row in alerts],
                         [("CLOSED", 1), ("OPEN", 2)])
        self.assertEqual(alerts[0]["alert_id"], "alert-legacy")
    def test_offline_robot_outbox_replays_once_after_both_stores_restart(self):
        robot_path = str(Path(self.directory.name) / "robot-missions.sqlite3")
        robot = MissionStore(robot_path, "robot-001")
        mission = robot.save_mission({
            "id": "mission-1", "name": "Patrol", "steps": [],
            "map_id": "map-1", "map_version_id": "map-v1",
        })
        robot.new_run("task-1", mission, record_start_event=True)
        robot.update_run("task-1", status="FAILED", reason="offline failure",
                         event_reason="offline failure")
        robot.observe_fault("sensor", 2, "offline")
        robot.observe_fault("sensor", 0, "restored")
        robot.close()

        robot = MissionStore(robot_path, "robot-001")
        batch = robot.pending_events()
        self.assertEqual([event["source_seq"] for event in batch], [1, 2, 3, 4])
        self.assertEqual(self.store.robot_event_history("robot-001"), [])
        self.assertEqual(self.store.ingest_robot_events("robot-001", batch), 4)
        # Simulate the platform transaction committing and the ACK being lost.
        self.assertEqual(self.store.ingest_robot_events("robot-001", batch), 4)
        self.assertEqual(len(self.store.robot_event_history("robot-001")), 4)
        robot.close()

        robot = MissionStore(robot_path, "robot-001")
        self.assertEqual(len(robot.pending_events()), 4)
        robot.acknowledge_events(4)
        self.assertEqual(robot.pending_events(), [])
        robot.close()

    def test_heartbeat_rejects_wrong_robot_and_non_increasing_sequence(self):
        bridge = SimpleNamespace(
            robot_id="robot-001", lock=threading.RLock(), heartbeat=None, heartbeat_seen=0,
        )
        heartbeat = {
            "schema_version": 1, "robot_id": "robot-001", "source": "mission_manager",
            "heartbeat_seq": 1, "observed_at": "2026-10-09T10:00:00+00:00",
        }
        RobotBridge._heartbeat(bridge, SimpleNamespace(data=json.dumps(heartbeat)))
        self.assertEqual(bridge.heartbeat["heartbeat_seq"], 1)
        RobotBridge._heartbeat(bridge, SimpleNamespace(data=json.dumps({
            **heartbeat, "robot_id": "other", "heartbeat_seq": 2,
        })))
        self.assertEqual(bridge.heartbeat["heartbeat_seq"], 1)
        RobotBridge._heartbeat(bridge, SimpleNamespace(data=json.dumps({
            **heartbeat, "observed_at": "2026-10-09T11:00:00+00:00",
        })))
        self.assertEqual(bridge.heartbeat["observed_at"], heartbeat["observed_at"])

    def test_audit_history_is_robot_scoped_and_filterable(self):
        self.store.audit("req-1", "engineer", "robot-001", "POST", "/tasks", 202)
        self.store.audit("req-2", "viewer", "robot-001", "GET", "/status", 200)
        self.store.audit("req-3", "engineer", "other", "POST", "/tasks", 202)
        rows = self.store.audit_history("robot-001", actor="engineer")
        self.assertEqual([row["request_id"] for row in rows], ["req-1"])
        response = self.client.get(self.base + "/audit?request_id=req-1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["request_id"] for row in response.json["entries"]], ["req-1"])
        self.assertEqual(self.client.get(self.base + "/audit?before=bad").status_code, 400)

    def test_robot_outbox_ingest_is_idempotent_and_history_is_queryable(self):
        event = {
            "schema_version": 1, "event_id": "event-1", "robot_id": "robot-001",
            "source": "mission_manager", "source_seq": 1,
            "type": "task.status_changed", "occurred_at": "2026-10-09T10:00:00+00:00",
            "recorded_at": "2026-10-09T10:00:00+00:00", "simulation": True,
            "severity": "INFO", "correlation": {"task_id": "task-1", "request_id": "req-1"},
            "payload": {"status": "RUNNING", "reason": "task started"},
        }
        self.assertEqual(self.store.ingest_robot_events("robot-001", [event]), 1)
        self.assertEqual(self.store.ingest_robot_events("robot-001", [event]), 1)
        history = self.store.robot_event_history("robot-001", task_id="task-1")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["event_id"], "event-1")
        self.assertEqual(self.store.robot_event_history("robot-001", task_id="other"), [])
        response = self.client.get(self.base + "/events/history?task_id=task-1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["events"][0]["event_id"], "event-1")
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.store.ingest_robot_events("robot-001", [{**event, "event_id": "event-2"}])
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.store.ingest_robot_events("robot-001", [{**event, "payload": {"status": "FAILED"}}])
        with self.assertRaisesRegex(ValueError, "correlation"):
            self.store.ingest_robot_events("robot-001", [{**event, "correlation": []}])
        with self.assertRaisesRegex(ValueError, "sequence gap"):
            self.store.ingest_robot_events("robot-001", [{**event, "event_id": "event-3", "source_seq": 3}])
        self.assertEqual(len(self.store.robot_event_history("robot-001")), 1)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.previous_log_root = os.environ.get("ROBOTPILOT_LOG_ROOT")
        self.previous_map_root = os.environ.get("ROBOTPILOT_MAP_ROOT")
        self.previous_robot_mode = os.environ.get("ROBOT_MODE")
        self.previous_battery_source = os.environ.get("BATTERY_SOURCE")
        self.log_directory = Path(self.directory.name) / "logs"
        self.log_directory.mkdir()
        self.map_root = Path(self.directory.name) / "maps" / "ui"
        map_group = self.map_root / "Campus-A"
        map_assets = map_group / "Office"
        map_assets.mkdir(parents=True)
        (map_group / "Office.yaml").write_text(
            "image: Office.pgm\nresolution: 0.05\norigin: [0, 0, 0]\n",
            encoding="utf-8",
        )
        (map_group / "Office.pgm").write_bytes(b"P5\\n1 1\\n255\\n\\x00")
        (map_assets / "cloud.pcd").write_text("version 0.7\n", encoding="utf-8")
        os.environ["ROBOTPILOT_LOG_ROOT"] = str(self.log_directory)
        os.environ["ROBOTPILOT_MAP_ROOT"] = str(self.map_root)
        os.environ["ROBOT_MODE"] = "simulation"
        os.environ["BATTERY_SOURCE"] = "sim"
        self.app = Flask(__name__)
        self.bridge = FakeBridge()
        self.store = PlatformStore(str(Path(self.directory.name) / "platform.sqlite3"))
        register_platform_api(self.app, lambda: self.bridge, self.store, "robot-001")
        install_auth(self.app, "open", str(Path(self.directory.name) / "auth.sqlite3"), "robot-001")
        self.client = self.app.test_client()
        self.base = "/api/v1/robots/robot-001"

    def tearDown(self):
        if self.previous_log_root is None:
            os.environ.pop("ROBOTPILOT_LOG_ROOT", None)
        else:
            os.environ["ROBOTPILOT_LOG_ROOT"] = self.previous_log_root
        if self.previous_map_root is None:
            os.environ.pop("ROBOTPILOT_MAP_ROOT", None)
        else:
            os.environ["ROBOTPILOT_MAP_ROOT"] = self.previous_map_root
        for key, value in (("ROBOT_MODE", self.previous_robot_mode), ("BATTERY_SOURCE", self.previous_battery_source)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.directory.cleanup()

    def test_platform_schema_migration_rolls_back_after_ddl_error(self):
        broken_path = Path(self.directory.name) / "broken-platform.sqlite3"
        with sqlite3.connect(broken_path) as db:
            db.execute(
                "CREATE VIEW waypoints AS "
                "SELECT 1 AS robot_id, 1 AS map_id, 1 AS name"
            )
        with self.assertRaises(sqlite3.OperationalError):
            PlatformStore(str(broken_path))
        with sqlite3.connect(broken_path) as db:
            tables = {
                row[0]
                for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            self.assertNotIn("commands", tables)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)

    def test_log_retention_runs_when_platform_api_is_registered(self):
        log_root = Path(self.directory.name) / "retained-logs"
        log_root.mkdir()
        expired = log_root / "expired.log"
        expired.write_text("expired", encoding="utf-8")
        old_mtime = time.time() - 31 * 86400
        os.utime(expired, (old_mtime, old_mtime))
        recent = log_root / "recent.log"
        recent.write_text("recent", encoding="utf-8")

        app = Flask("log-retention-test")
        with patch.dict(os.environ, {
            "ROBOTPILOT_LOG_ROOT": str(log_root),
            "ROBOTPILOT_LOG_RETENTION_DAYS": "30",
        }):
            register_platform_api(
                app,
                FakeBridge,
                PlatformStore(str(Path(self.directory.name) / "retention.sqlite3")),
                "robot-001",
            )

        self.assertFalse(expired.exists())
        self.assertTrue(recent.exists())

    def test_task_command_is_idempotent_and_correlated(self):
        headers = {
            "Idempotency-Key": "start-patrol-001",
            "X-Request-ID": "start-patrol-001",
        }
        first = self.client.post(self.base + "/tasks", json={"mission_id": "patrol"}, headers=headers)
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json["task_id"], "task-123")
        self.assertEqual(first.json["origin_request_id"], "start-patrol-001")
        self.assertEqual(self.bridge.calls[-1][0]["origin_request_id"], "start-patrol-001")
        second = self.client.post(self.base + "/tasks", json={"mission_id": "patrol"}, headers=headers)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(self.bridge.calls), 1)
        changed = self.client.post(self.base + "/tasks", json={"mission_id": "other"}, headers=headers)
        self.assertEqual(changed.status_code, 409)
        command_id = first.json["command_id"]
        self.assertEqual(self.client.get(self.base + "/commands/" + command_id).json["task_id"], "task-123")

    def test_battery_config_payload_accepts_stored_and_flat_config_shapes(self):
        expected = {"low_battery_threshold": 35, "config_version": 4}
        self.assertEqual(
            battery_config_payload({
                "version": 4,
                "config": {"low_battery_threshold": 35},
            }),
            expected,
        )
        self.assertEqual(
            battery_config_payload({"version": 4, **expected}),
            expected,
        )

    def test_late_robot_ack_completes_pending_command_query(self):
        self.bridge.command = lambda _command, _request_id: None
        pending = self.client.post(
            self.base + "/tasks", json={"mission_id": "patrol"},
            headers={"Idempotency-Key": "late-task-command"},
        )
        self.assertEqual(pending.status_code, 202)
        command_id = pending.json["command_id"]
        self.bridge.late_acks[command_id] = {
            "request_id": command_id, "ok": True, "task_id": "task-late",
        }
        result = self.client.get(self.base + "/commands/" + command_id)
        self.assertEqual(result.json["status"], "accepted")
        self.assertEqual(result.json["task_id"], "task-late")
        self.assertEqual(result.json["origin_request_id"], pending.json["origin_request_id"])

    def test_schedule_endpoints_dispatch_commands_and_require_revision(self):
        created = self.client.post(
            self.base + "/schedules",
            json={"schedule": {"name": "Morning", "mission_id": "patrol"}},
            headers={"Idempotency-Key": "schedule-create-1"},
        )
        self.assertEqual(created.status_code, 202)
        self.assertEqual(created.json["schedule_id"], "schedule-new")
        self.assertEqual(self.bridge.calls[-1][0]["command"], "schedule.save")

        self.assertEqual(self.client.get(self.base + "/schedules").json["schedules"][0]["schedule_id"],
                         "schedule-1")
        runs = self.client.get(self.base + "/schedules/schedule-1/runs")
        self.assertEqual(runs.status_code, 200)
        self.assertEqual(runs.json["runs"][0]["status"], "started")

        missing_revision = self.client.patch(
            self.base + "/schedules/schedule-1", json={"enabled": False},
            headers={"Idempotency-Key": "schedule-patch-1"},
        )
        self.assertEqual(missing_revision.status_code, 428)
        stale_revision = self.client.patch(
            self.base + "/schedules/schedule-1", json={"enabled": False},
            headers={"Idempotency-Key": "schedule-patch-2", "If-Match": '"2"'},
        )
        self.assertEqual(stale_revision.status_code, 412)
        updated = self.client.patch(
            self.base + "/schedules/schedule-1", json={"enabled": False},
            headers={"Idempotency-Key": "schedule-patch-3", "If-Match": '"1"'},
        )
        self.assertEqual(updated.status_code, 202)
        self.assertEqual(self.bridge.calls[-1][0]["schedule"]["enabled"], False)

        deleted = self.client.delete(
            self.base + "/schedules/schedule-1",
            headers={"Idempotency-Key": "schedule-delete-1", "If-Match": '"1"'},
        )
        self.assertEqual(deleted.status_code, 202)
        self.assertEqual(self.bridge.calls[-1][0]["command"], "schedule.delete")

    def test_robot_scope_faults_and_config_versions(self):
        self.assertEqual(self.client.get("/api/v1/robots/other/status").status_code, 403)
        self.assertTrue(self.client.get(self.base + "/status").json["online"])
        status = self.client.get(self.base + "/status").json
        self.assertTrue(status["autonomy_ready"])
        self.assertEqual(status["current_map"]["map_id"], "simulation/map-a")
        self.assertFalse(status["software_stop"]["stale"])
        battery = self.client.get(self.base + "/status").json["battery"]
        self.assertEqual(battery["source"], "simulated")
        self.assertTrue(battery["simulated"])
        self.store.observe_fault("robot-001", "lidar", "disconnected", 2)
        fault = self.client.get(self.base + "/faults?active=true").json["faults"][0]
        self.assertEqual(self.client.post(self.base + "/faults/" + fault["fault_id"] + "/clear").status_code, 409)
        self.store.observe_fault("robot-001", "lidar", "connected", 0)
        self.assertEqual(self.client.post(self.base + "/faults/" + fault["fault_id"] + "/clear").status_code, 200)
        self.assertEqual(self.client.put(self.base + "/config", json={"low_battery_threshold": 30}).status_code, 412)
        result = self.client.put(
            self.base + "/config", json={"low_battery_threshold": 30}, headers={"If-Match": '"1"'}
        )
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.json["runtime_delivery"], "published")
        self.assertEqual(self.bridge.battery_configs[-1]["config"], {"low_battery_threshold": 30})
        self.assertEqual(result.json["active"], 1)
        current = self.client.get(self.base + "/config")
        self.assertEqual(current.json["version"], 2)
        self.assertEqual(current.json["config"]["low_battery_threshold"], 30)

        second = self.client.put(
            self.base + "/config", json={"low_battery_threshold": 31}, headers={"If-Match": '"2"'}
        )
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.json["active"], 1)
        current = self.client.get(self.base + "/config")
        self.assertEqual(current.json["version"], 3)
        self.assertEqual(current.json["config"]["low_battery_threshold"], 31)

        rollback = self.client.post(self.base + "/config/versions/2/activate")
        self.assertEqual(rollback.json["config"]["low_battery_threshold"], 30)
        self.assertEqual(self.bridge.battery_configs[-1]["version"], 2)
        saved_after_rollback = self.client.put(
            self.base + "/config", json={"low_battery_threshold": 32}, headers={"If-Match": '"2"'}
        )
        self.assertEqual(saved_after_rollback.status_code, 201)
        self.assertEqual(saved_after_rollback.json["version"], 4)
        self.assertEqual(self.client.get(self.base + "/config").json["version"], 4)
        stale = self.client.put(
            self.base + "/config", json={"low_battery_threshold": 33}, headers={"If-Match": '"2"'}
        )
        self.assertEqual(stale.status_code, 412)

    def test_health_endpoint_reports_storage_thresholds(self):
        previous_warning = os.environ.get("ROBOTPILOT_STORAGE_WARNING_PERCENT")
        previous_critical = os.environ.get("ROBOTPILOT_STORAGE_CRITICAL_PERCENT")
        os.environ["ROBOTPILOT_STORAGE_WARNING_PERCENT"] = "70"
        os.environ["ROBOTPILOT_STORAGE_CRITICAL_PERCENT"] = "85"
        try:
            response = self.client.get(self.base + "/health")
        finally:
            for key, value in (
                ("ROBOTPILOT_STORAGE_WARNING_PERCENT", previous_warning),
                ("ROBOTPILOT_STORAGE_CRITICAL_PERCENT", previous_critical),
            ):
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["storage_error"], None)
        self.assertEqual(
            {item["label"] for item in response.json["storage"]},
            {"platform_data", "recordings"},
        )
        self.assertEqual(
            response.json["storage"][0]["warning_percent"], 70
        )

    def test_build_endpoint_exposes_non_secret_release_identity(self):
        response = self.client.get(self.base + "/build")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["package"], "robotpilot_ui_package")
        self.assertIn("version", response.json)
        self.assertIn("commit", response.json)
        self.assertIn("frontend_build", response.json)
        self.assertEqual(response.json["schema_versions"]["platform"], 8)
        self.assertIsNone(response.json["schema_versions"]["auth"])
        self.assertNotIn("path", response.json)

    def test_battery_scenario_is_limited_to_simulation_profile(self):
        response = self.client.post(self.base + "/battery/scenario", json={"scenario": "low_battery"})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.bridge.battery_scenarios, ["low_battery"])
        bad = self.client.post(self.base + "/battery/scenario", json={"scenario": "unknown"})
        self.assertEqual(bad.status_code, 400)
        os.environ["ROBOT_MODE"] = "hardware"
        blocked = self.client.post(self.base + "/battery/scenario", json={"scenario": "reset"})
        self.assertEqual(blocked.status_code, 409)

    def test_map_catalog_metadata_and_checksum_versions(self):
        catalog = self.client.get(self.base + "/maps/catalog")
        self.assertEqual(catalog.status_code, 200)
        self.assertEqual(catalog.json["maps"][0]["map"], "Office")
        self.assertEqual(catalog.json["maps"][0]["asset_count"], 3)

        detail_path = self.base + "/maps/catalog/Campus-A/Office"
        initial = self.client.get(detail_path)
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.json["metadata"]["revision"], 0)

        invalid_hierarchy = self.client.patch(
            detail_path,
            json={"building": "Building-A"},
            headers={"If-Match": '"0"'},
        )
        self.assertEqual(invalid_hierarchy.status_code, 400)

        created = self.client.patch(
            detail_path,
            json={"campus": "North", "building": "Building-A", "floor": "2", "label": "Office"},
            headers={"If-Match": '"0"'},
        )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(created.json["revision"], 1)

        stale = self.client.patch(
            detail_path,
            json={"description": "stale"},
            headers={"If-Match": '"0"'},
        )
        self.assertEqual(stale.status_code, 412)
        updated = self.client.patch(
            detail_path,
            json={"description": "north office"},
            headers={"If-Match": '"1"'},
        )
        self.assertEqual(updated.json["revision"], 2)

        version_path = detail_path + "/versions"
        first_version = self.client.post(version_path)
        self.assertEqual(first_version.status_code, 201)
        self.assertEqual(first_version.json["version"]["metadata"]["revision"], 2)
        duplicate = self.client.post(version_path)
        self.assertEqual(duplicate.status_code, 200)
        self.assertFalse(duplicate.json["created"])

        with (self.map_root / "Campus-A" / "Office.pgm").open("ab") as image:
            image.write(b"changed")
        second_version = self.client.post(version_path)
        self.assertEqual(second_version.status_code, 201)
        self.assertNotEqual(
            first_version.json["version"]["checksum"],
            second_version.json["version"]["checksum"],
        )
        versions = self.client.get(version_path)
        self.assertEqual(versions.status_code, 200)
        self.assertEqual(len(versions.json["versions"]), 2)
        event_types = [event["event_type"] for event in self.store.events_after("robot-001", 0)]
        self.assertEqual(
            event_types,
            ["map_metadata_updated", "map_metadata_updated", "map_checksum_version_recorded",
             "map_checksum_version_recorded"],
        )

    def test_map_catalog_rejects_traversal_and_symlinked_image(self):
        detail_path = self.base + "/maps/catalog/Campus-A/Office"
        self.assertEqual(self.client.get(self.base + "/maps/catalog/../Office").status_code, 400)
        yaml_path = self.map_root / "Campus-A" / "Office.yaml"
        yaml_path.write_text("image: ../../outside.pgm\n", encoding="utf-8")
        self.assertEqual(self.client.get(detail_path).status_code, 409)
        yaml_path.write_text("image: Office.pgm\n", encoding="utf-8")
        image_path = self.map_root / "Campus-A" / "Office.pgm"
        image_path.unlink()
        image_path.symlink_to(Path(self.directory.name) / "outside.pgm")
        self.assertEqual(self.client.get(detail_path).status_code, 409)

    def test_sqlite_failures_return_correlated_service_unavailable(self):
        def unavailable(*_args, **_kwargs):
            raise sqlite3.OperationalError("database is locked")

        self.store.config = unavailable
        response = self.client.get(self.base + "/config")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["code"], "DATABASE_UNAVAILABLE")
        self.assertTrue(response.json["request_id"])
        self.assertIn("X-Request-Id", response.headers)

    def test_audit_failure_marks_write_result_unknown_instead_of_success(self):
        def audit_unavailable(*_args, **_kwargs):
            raise sqlite3.OperationalError("database is full")

        self.store.audit = audit_unavailable
        response = Response('{"created":true}', status=201)
        result = audit_api_response(
            response,
            self.store,
            "request-audit-failure",
            {"username": "operator", "robot_id": "robot-001"},
            "POST",
            self.base + "/tasks",
            self.app.logger,
        )

        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.get_json()["code"], "AUDIT_UNAVAILABLE")
        self.assertEqual(result.get_json()["status"], "unknown")
        self.assertEqual(result.get_json()["request_id"], "request-audit-failure")

    def test_event_and_audit_retention_are_configurable(self):
        store = PlatformStore(
            str(Path(self.directory.name) / "retention.sqlite3"),
            event_retention_count=2,
            audit_retention_days=1,
        )
        for value in range(4):
            store.append_state_event("robot-001", {"state": value})

        events = store.events_after("robot-001", 0)
        self.assertEqual(len(events), 2)
        self.assertEqual([json.loads(event["payload_json"]) for event in events],
                         [{"state": 2}, {"state": 3}])

        with store.connect() as db:
            db.execute(
                "INSERT INTO audit_entries(request_id,actor,method,path,status_code,timestamp) "
                "VALUES (?,?,?,?,?,?)",
                ("old", "operator", "POST", "/old", 200, "2000-01-01T00:00:00+00:00"),
            )
        store.audit("new", "operator", "robot-001", "POST", "/new", 200)
        with store.connect() as db:
            audit_ids = [row[0] for row in db.execute(
                "SELECT request_id FROM audit_entries ORDER BY id"
            )]
        self.assertEqual(audit_ids, ["new"])

    def test_fault_lifecycle_is_filterable_and_emits_persistent_transition_events(self):
        self.store.observe_fault("robot-001", "lidar/front", "disconnected", 2)
        raised = self.client.get(self.base + "/faults?status=active&severity=ERROR&module=lidar").json
        fault = raised["faults"][0]
        self.assertEqual(raised["total"], 1)
        self.assertTrue(fault["fault_code"].startswith("DIAG-"))

        ack = self.client.post(self.base + f"/faults/{fault['fault_id']}/ack")
        self.assertEqual(ack.status_code, 200)
        self.assertTrue(ack.json["acknowledged_at"])

        self.store.observe_fault("robot-001", "lidar/front", "connected", 0)
        resolved = self.client.get(self.base + "/faults?status=resolved&limit=1&offset=0").json
        self.assertEqual(resolved["faults"][0]["fault_id"], fault["fault_id"])
        self.assertIsNone(resolved["next_offset"])

        clear = self.client.post(self.base + f"/faults/{fault['fault_id']}/clear")
        self.assertEqual(clear.status_code, 200)
        self.assertTrue(clear.json["cleared_at"])
        events = self.store.events_after("robot-001", 0)
        event_types = [event["event_type"] for event in events]
        self.assertEqual(
            event_types,
            ["fault_raised", "fault_acknowledged", "fault_resolved", "fault_cleared"],
        )
        stream = self.client.get(
            self.base + "/events", headers={"Last-Event-ID": "3"}, buffered=False,
        )
        first_event = next(stream.response).decode()
        self.assertIn("event: fault_cleared", first_event)
        stream.close()

    def test_fault_listing_paginates_and_rejects_invalid_filters(self):
        for name in ("camera", "lidar", "motor"):
            self.store.observe_fault("robot-001", name, "failed", 1)
        page = self.client.get(self.base + "/faults?status=all&limit=2&offset=0")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.json["total"], 3)
        self.assertEqual(page.json["next_offset"], 2)
        self.assertEqual(self.client.get(self.base + "/faults?status=invalid").status_code, 400)
        first_seen = page.json["faults"][0]["first_seen"]
        filtered = self.client.get(
            self.base
            + "/faults?status=all&from="
            + first_seen.replace("+", "%2B")
            + "&to="
            + first_seen.replace("+", "%2B")
        )
        self.assertEqual(filtered.json["total"], 1)
        self.assertEqual(self.client.get(self.base + "/faults?from=invalid").status_code, 400)

    def test_local_auth_role_matrix_csrf_and_robot_scope(self):
        app = Flask("local-platform-auth")
        store = PlatformStore(str(Path(self.directory.name) / "local-platform.sqlite3"))
        register_platform_api(app, lambda: self.bridge, store, "robot-001")
        auth = install_auth(
            app, "local", str(Path(self.directory.name) / "local-auth.sqlite3"), "robot-001"
        )
        for role in ("Viewer", "Operator", "Engineer", "Admin"):
            auth.create_user(role.lower(), f"long-password-{role.lower()}", role, "robot-001")
        client = app.test_client()
        base = "/api/v1/robots/robot-001"
        store.observe_fault("robot-001", "local-test", "test fault", 2)
        fault_id = store.faults("robot-001")[0]["fault_id"]

        def login(role):
            response = client.post(
                "/api/v1/auth/login",
                json={"username": role.lower(), "password": f"long-password-{role.lower()}"},
            )
            self.assertEqual(response.status_code, 200)
            return response.json["csrf_token"]

        viewer_csrf = login("Viewer")
        self.assertEqual(client.get(base + "/status").status_code, 200)
        self.assertEqual(client.get(base + "/audit").status_code, 403)
        self.assertEqual(client.get("/api/v1/robots/robot-002/status").status_code, 403)
        self.assertEqual(
            client.post(base + "/waypoints", json={"map_id": "simulation/map-a", "name": "A", "x": 0, "y": 0, "yaw": 0},
                        headers={"X-CSRF-Token": viewer_csrf}).status_code,
            403,
        )
        self.assertEqual(client.post(base + "/tasks", json={"mission_id": "patrol"}).status_code, 403)
        self.assertEqual(
            client.post(
                base + "/schedules", json={"schedule": {"name": "Blocked", "mission_id": "patrol"}},
                headers={"X-CSRF-Token": viewer_csrf, "Idempotency-Key": "viewer-schedule"},
            ).status_code,
            403,
        )
        self.assertEqual(client.put(base + "/config", json={}).status_code, 403)
        self.assertEqual(
            client.post(base + f"/faults/{fault_id}/ack", headers={"X-CSRF-Token": viewer_csrf}).status_code,
            403,
        )

        operator_csrf = login("Operator")
        self.assertEqual(client.get(base + "/audit").status_code, 403)
        self.assertEqual(
            client.post(base + "/waypoints", json={"map_id": "simulation/map-a", "name": "A", "x": 0, "y": 0, "yaw": 0},
                        headers={"X-CSRF-Token": operator_csrf}).status_code,
            403,
        )
        self.assertEqual(client.post(base + "/tasks", json={"mission_id": "patrol"}).status_code, 403)
        self.assertEqual(
            client.post(
                base + "/tasks", json={"mission_id": "patrol"},
                headers={"X-CSRF-Token": operator_csrf, "Idempotency-Key": "local-task"},
            ).status_code,
            202,
        )
        self.assertEqual(
            client.post(
                base + "/schedules",
                json={"schedule": {"name": "Daily", "mission_id": "patrol"}},
                headers={"X-CSRF-Token": operator_csrf, "Idempotency-Key": "operator-schedule"},
            ).status_code,
            202,
        )
        self.assertEqual(
            client.put(base + "/config", json={}, headers={"X-CSRF-Token": operator_csrf}).status_code,
            403,
        )
        self.assertEqual(
            client.post(base + f"/faults/{fault_id}/ack", headers={"X-CSRF-Token": operator_csrf}).status_code,
            200,
        )
        self.assertEqual(
            client.post(base + f"/faults/{fault_id}/clear", headers={"X-CSRF-Token": operator_csrf}).status_code,
            403,
        )

        engineer_csrf = login("Engineer")
        waypoint_response = client.post(
            base + "/waypoints",
            json={"map_id": "simulation/map-a", "name": "A", "x": 0, "y": 0, "yaw": 0},
            headers={"X-CSRF-Token": engineer_csrf},
        )
        self.assertEqual(waypoint_response.status_code, 201)
        store.observe_fault("robot-001", "local-test", "recovered", 0)
        self.assertEqual(
            client.post(base + f"/faults/{fault_id}/clear", headers={"X-CSRF-Token": engineer_csrf}).status_code,
            200,
        )
        self.assertEqual(
            client.put(
                base + "/config", json={"low_battery_threshold": 30},
                headers={"X-CSRF-Token": engineer_csrf},
            ).status_code,
            412,
        )
        admin_csrf = login("Admin")
        self.assertEqual(
            client.put(
                base + "/config", json={"low_battery_threshold": 25},
                headers={"X-CSRF-Token": admin_csrf, "If-Match": '"1"'},
            ).status_code,
            201,
        )
        self.assertNotEqual(viewer_csrf, operator_csrf)
        self.assertNotEqual(operator_csrf, engineer_csrf)

    def test_ros_diagnostic_level_bytes_are_normalized(self):
        bridge = SimpleNamespace(
            lock=threading.RLock(), odom_seen=0, store=self.store,
            robot_id="robot-001", diagnostics={}, fault_candidates={},
        )
        message = SimpleNamespace(status=[SimpleNamespace(
            name="camera", message="OK", level=b"\x00",
        )])
        RobotBridge._diagnostic(bridge, message)
        self.assertEqual(bridge.diagnostics["camera"]["level"], 0)
        self.assertEqual(bridge.fault_candidates, {})

    def test_route_catalog_tracks_current_2d_map_identity(self):
        bridge = SimpleNamespace(lock=threading.RLock(), map_identity=None, map_identity_seen=0)
        RobotBridge._route_catalog(bridge, SimpleNamespace(data=(
            '{"active_files":{"map_id":"grid-hash","map_version_id":"grid-hash",'
            '"group":"Simulation","map":"Map A"}}'
        )))
        self.assertEqual(bridge.map_identity["map_id"], "grid-hash")
        self.assertEqual(bridge.map_identity["map_version_id"], "grid-hash")

    def test_software_stop_state_is_parsed_and_unknown_state_blocks_readiness(self):
        bridge = SimpleNamespace(
            lock=threading.RLock(), software_stop_state=None, software_stop_seen=0,
        )
        RobotBridge._software_stop_state(bridge, SimpleNamespace(data=(
            '{"active":false,"result":"confirmed","durable":true,'
            '"observed_at":"2026-10-08T00:00:00+00:00"}'
        )))
        self.assertFalse(bridge.software_stop_state["active"])
        from robotpilot_ui_package.platform_api import autonomy_readiness
        ready = autonomy_readiness({
            "mission_online": True, "map_identity_online": True, "pose_online": True,
            "map_identity": {"map_id": "grid-1", "map_version_id": "grid-1"},
            "map_bundle_online": True, "map_bundle": {"ready": True, "map_id": "grid-1",
                                                     "map_version_id": "grid-1",
                                                     "bundle_id": "test-bundle",
                                                     "globalmap_pcd_sha256": "test-pcd"},
            "software_stop_online": True, "software_stop_state": bridge.software_stop_state,
            "battery_online": True,
            "battery_state": {"available": True, "low_battery": False, "charging": False},
        })
        self.assertTrue(ready["ready"])
        blocked = autonomy_readiness({
            "mission_online": True, "map_identity_online": True, "pose_online": True,
            "software_stop_online": True, "software_stop_state": bridge.software_stop_state,
            "battery_online": True,
            "battery_state": {"available": True, "low_battery": True, "charging": False},
            "area_control_seen": True, "area_control_online": True,
            "area_control": {"ready": True, "stop": True},
            "diagnostics": {"motor": {"level": 2, "last_seen": time.monotonic()}},
        })
        self.assertFalse(blocked["ready"])
        self.assertIn("battery low or charge level unknown", blocked["blockers"])
        self.assertIn("area control blocks motion", blocked["blockers"])
        self.assertIn("critical diagnostics are active", blocked["blockers"])
        with patch.dict(os.environ, {"ROBOT_MODE": "hardware"}):
            simulated = autonomy_readiness({
                "mission_online": True, "map_identity_online": True, "pose_online": True,
                "software_stop_online": True, "software_stop_state": bridge.software_stop_state,
                "battery_online": True,
                "battery_state": {"available": True, "low_battery": False,
                                  "charging": False, "source": "simulated"},
            })
        self.assertIn("simulated battery cannot authorize hardware motion", simulated["blockers"])
        bridge.software_stop_seen = 0
        stopped = autonomy_readiness({
            "mission_online": True, "map_identity_online": True, "pose_online": True,
            "software_stop_online": False, "software_stop_state": None,
        })
        self.assertFalse(stopped["ready"])
        self.assertIn("software stop state unavailable or stale", stopped["blockers"])

    def test_authoritative_battery_state_validates_source_and_percent(self):
        bridge = SimpleNamespace(
            lock=threading.RLock(), battery_state=None, battery_state_seen=0,
        )
        RobotBridge._battery_state(bridge, SimpleNamespace(data=(
            '{"percent":73,"source":"simulated","available":true,'
            '"observed_at":"2026-10-08T00:00:00+00:00"}'
        )))
        self.assertEqual(bridge.battery_state["source"], "simulated")
        self.assertTrue(bridge.battery_state["simulated"])
        valid_state = bridge.battery_state

        RobotBridge._battery_state(bridge, SimpleNamespace(data=(
            '{"percent":1000,"source":"hardware","available":true,'
            '"observed_at":"2026-10-08T00:00:00+00:00"}'
        )))
        self.assertEqual(bridge.battery_state, valid_state)

    def test_low_battery_state_raises_and_resolves_persistent_fault(self):
        bridge = SimpleNamespace(
            lock=threading.RLock(), battery_state=None, battery_state_seen=0,
            store=self.store, robot_id="robot-001",
        )
        RobotBridge._battery_state(bridge, SimpleNamespace(data=(
            '{"percent":10,"source":"simulated","available":true,"low_battery":true,'
            '"low_battery_threshold":20,"observed_at":"2026-10-08T00:00:00+00:00"}'
        )))
        active = self.store.faults("robot-001", active_only=True)
        self.assertEqual(active[0]["fault_source"], "battery/low")
        RobotBridge._battery_state(bridge, SimpleNamespace(data=(
            '{"percent":24,"source":"simulated","available":true,"low_battery":false,'
            '"low_battery_threshold":20,"observed_at":"2026-10-08T00:00:02+00:00"}'
        )))
        self.assertEqual(self.store.faults("robot-001", active_only=True), [])

    def test_s1_result_ingest_is_atomic_and_idempotent(self):
        result = {
            "result_id": "result-fixture-1", "action_run_id": "action-1",
            "task_id": "task-1", "step_id": "step-1", "status": "SUCCEEDED",
            "outcome": "ABNORMAL", "source_mode": "fixture",
            "observed_at": "2026-10-10T00:00:00Z", "map_id": "map-a",
            "map_version_id": "v1", "waypoint_id": "wp-fixture",
            "detector_type": "fire_smoke",
            "position": {"frame_id": "map", "x": 1.25, "y": -0.5, "yaw": 0.2,
                         "observed_at": "2026-10-10T00:00:00Z"},
            "evidence": [{"evidence_id": "evidence-1", "media_type": "image/jpeg",
                          "checksum": "a" * 64, "size_bytes": 32}],
        }
        event = {
            "schema_version": 1, "event_id": "event-fixture-1", "robot_id": "robot-001",
            "source": "mission_manager", "source_seq": 1,
            "type": "inspection.result", "severity": "WARNING",
            "occurred_at": "2026-10-10T00:00:00Z",
            "correlation": {"task_id": "task-1", "request_id": None},
            "payload": result,
        }
        self.assertEqual(self.store.ingest_robot_events("robot-001", [event]), 1)
        self.assertEqual(self.store.ingest_robot_events("robot-001", [event]), 1)
        self.assertEqual(len(self.client.get(self.base + "/inspection/results").json["results"]), 1)
        self.assertEqual(len(self.client.get(self.base + "/inspection/alerts").json["alerts"]), 1)
        alert = self.client.get(self.base + "/inspection/alerts").json["alerts"][0]
        self.assertEqual(alert["map_id"], "map-a")
        self.assertEqual(alert["map_version_id"], "v1")
        self.assertEqual(alert["position"]["frame_id"], "map")
        self.assertEqual(alert["position"]["x"], 1.25)
        filtered = self.client.get(self.base + "/inspection/alerts?map_id=map-a&map_version_id=v1")
        self.assertEqual(len(filtered.json["alerts"]), 1)
        stale_map = self.client.get(self.base + "/inspection/alerts?map_id=map-a&map_version_id=v2")
        self.assertEqual(stale_map.json["alerts"], [])
        self.assertEqual(self.client.get(self.base + "/inspection/alerts?map_id=map-a").status_code, 400)
        alert_detail = self.client.get(self.base + f"/inspection/alerts/{alert['alert_id']}")
        self.assertEqual(alert_detail.status_code, 200)
        self.assertEqual(alert_detail.json["alert"]["alert_id"], alert["alert_id"])
        self.assertEqual(alert_detail.json["evidence"][0]["evidence_id"], "evidence-1")
        self.assertNotIn("uri_or_path", alert_detail.json["evidence"][0])
        self.assertNotIn("result_details_json", alert_detail.json["alert"])
        ack = self.client.patch(self.base + f"/inspection/alerts/{alert['alert_id']}",
                                json={"state": "ACKNOWLEDGED", "note": "review started"},
                                headers={"If-Match": '"1"'})
        self.assertEqual(ack.status_code, 200)
        invalid_transition = self.client.patch(self.base + f"/inspection/alerts/{alert['alert_id']}",
                                               json={"state": "CLOSED"},
                                               headers={"If-Match": '"2"'})
        self.assertEqual(invalid_transition.status_code, 409)
        evidence_response = self.client.get(self.base + "/inspection/evidence/evidence-1")
        self.assertEqual(evidence_response.status_code, 200)
        self.assertEqual(evidence_response.json["media_status"], "UNAVAILABLE")
        self.assertIsNone(evidence_response.json["media_url"])
        repeated = {**event, "event_id": "event-fixture-2", "source_seq": 2,
                    "payload": {**result, "result_id": "result-fixture-2", "evidence": []}}
        self.store.ingest_robot_events("robot-001", [repeated])
        alert = self.client.get(self.base + "/inspection/alerts").json["alerts"][0]
        self.assertEqual(alert["occurrence_count"], 2)
        self.assertEqual(alert["state"], "ACKNOWLEDGED")
        bad = {**event, "event_id": "event-fixture-3", "source_seq": 3,
               "payload": {**result, "result_id": "result-fixture-3", "confidence": float("nan")}}
        with self.assertRaises(ValueError):
            self.store.ingest_robot_events("robot-001", [bad])
        unsafe = {**event, "event_id": "event-fixture-4", "source_seq": 4,
                  "payload": {**result, "result_id": "result-fixture-4",
                              "evidence": [{"evidence_id": "unsafe", "path": "/private/a.jpg"}]}}
        with self.assertRaisesRegex(ValueError, "metadata only"):
            self.store.ingest_robot_events("robot-001", [unsafe])
        self.assertEqual(len(self.client.get(self.base + "/inspection/results").json["results"]), 2)

    def test_inspection_task_search_filters_mission_manager_history(self):
        snapshot = self.bridge.snapshot()
        snapshot["mission"]["run"] = {
            "task_id": "task-live-001", "mission_id": "inspection-live-001",
            "mission_name": "West wing patrol", "status": "running", "step_index": 1,
            "started_at": "2026-10-10T00:00:00Z", "steps": [
                {"type": "waypoint"}, {"type": "inspection_action"},
            ], "events": [],
        }
        snapshot["mission"]["history"] = [{
            "task_id": "task-old-001", "mission_id": "inspection-old-001",
            "mission_name": "North patrol", "status": "FAILED", "step_index": 0,
            "started_at": "2026-10-08T00:00:00Z", "steps": [{"type": "inspection_action"}],
            "events": [{"status": "FAILED"}],
        }, {
            "task_id": "navigation-001", "mission_id": "navigation-001",
            "mission_name": "Navigate home", "status": "SUCCEEDED",
            "started_at": "2026-10-09T00:00:00Z", "steps": [{"type": "waypoint"}],
        }]
        self.bridge.snapshot = lambda: snapshot
        all_tasks = self.client.get(self.base + "/inspection/tasks")
        self.assertEqual([item["task_id"] for item in all_tasks.json["tasks"]], [
            "task-live-001", "task-old-001",
        ])
        failed = self.client.get(self.base + "/inspection/tasks?status=failed&q=north")
        self.assertEqual([item["task_id"] for item in failed.json["tasks"]], ["task-old-001"])
        self.assertEqual(self.client.get(self.base + "/inspection/tasks?status=unknown").status_code, 400)

    def test_asset_waypoint_link_requires_matching_map_versions(self):
        wp = self.client.post(self.base + "/waypoints", json={
            "map_id": "simulation/map-a", "name": "Asset Check", "x": 1, "y": 2, "yaw": 0,
        })
        self.assertEqual(wp.status_code, 201)
        asset = self.client.post(self.base + "/assets", json={
            "map_id": "simulation/map-a", "name": "Cabinet A", "metadata": {"kind": "fire_safety"},
        })
        self.assertEqual(asset.status_code, 201)
        asset_id = asset.json["asset_id"]
        waypoint_id = wp.json["waypoint_id"]
        linked = self.client.put(self.base + f"/assets/{asset_id}/waypoints/{waypoint_id}")
        self.assertEqual(linked.status_code, 201)
        self.assertEqual(len(self.client.get(self.base + f"/assets/{asset_id}/waypoints").json["waypoints"]), 1)
        listed_asset = next(item for item in self.client.get(self.base + "/assets").json["assets"]
                            if item["asset_id"] == asset_id)
        self.assertEqual(listed_asset["waypoint_ids"], [waypoint_id])
        self.assertEqual(self.client.delete(self.base + f"/assets/{asset_id}/waypoints/{waypoint_id}").status_code, 204)
        self.assertEqual(self.client.get(self.base + f"/assets/{asset_id}/waypoints").json["waypoints"], [])
        self.assertEqual(self.client.put(self.base + f"/assets/{asset_id}/waypoints/{waypoint_id}").status_code, 201)
        updated = self.client.patch(self.base + f"/assets/{asset_id}",
                                    json={"name": "Cabinet A", "metadata": {"kind": "fire_safety"}, "active": False},
                                    headers={"If-Match": '"1"'})
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json["revision"], 2)
        self.assertEqual(self.client.patch(self.base + f"/assets/{asset_id}", json={"name": "stale"},
                                           headers={"If-Match": '"1"'}).status_code, 412)

    def test_waypoint_action_plan_is_versioned_and_never_executable_without_adapter(self):
        waypoint = self.client.post(self.base + "/waypoints", json={
            "map_id": "simulation/map-a", "name": "Action Draft", "x": 0, "y": 0, "yaw": 0,
        }).json
        path = self.base + f"/waypoints/{waypoint['waypoint_id']}/action-plan"
        saved = self.client.put(path, json={"actions": [{"kind": "detect", "timeout_ms": 15000,
                                                          "detector_types": ["fire_smoke"]}]},
                                headers={"If-Match": '"0"'})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json["revision"], 1)
        self.assertFalse(saved.json["executable"])
        self.assertEqual(self.client.put(path, json={"actions": []}, headers={"If-Match": '"0"'}).status_code, 412)

    def test_inspection_task_compiles_current_snapshots_and_dispatches_idempotently(self):
        self.assertTrue(self.client.get(self.base + "/inspection/capabilities").json["online"])
        waypoint = self.client.post(self.base + "/waypoints", json={
            "map_id": "simulation/map-a", "name": "Fire Cabinet", "x": 1.5, "y": -2.0, "yaw": 1.0,
        }).json
        asset = self.client.post(self.base + "/assets", json={
            "map_id": "simulation/map-a", "name": "Cabinet A", "metadata": {"kind": "fire_safety"},
        }).json
        self.client.put(self.base + f"/assets/{asset['asset_id']}/waypoints/{waypoint['waypoint_id']}")
        plan_path = self.base + f"/waypoints/{waypoint['waypoint_id']}/action-plan"
        self.assertEqual(self.client.put(plan_path, json={"actions": [{
            "kind": "detect", "timeout_ms": 5000, "detector_types": ["fire_smoke"],
            "parameters": {"camera_id": "front"},
        }]}, headers={"If-Match": '"0"'}).status_code, 200)
        headers = {"Idempotency-Key": "inspection-run-0001"}
        body = {"name": "Cabinet patrol", "waypoint_ids": [waypoint["waypoint_id"]]}
        result = self.client.post(self.base + "/inspection/tasks", json=body, headers=headers)
        self.assertEqual(result.status_code, 202)
        self.assertEqual(result.json["status"], "accepted")
        self.assertEqual(len(self.bridge.calls), 2)
        mission = self.bridge.calls[0][0]["mission"]
        self.assertEqual(mission["map_version_id"], "simulation/map-a")
        self.assertEqual(mission["steps"][0]["waypoint_id"], waypoint["waypoint_id"])
        self.assertAlmostEqual(mission["steps"][0]["pose"]["z"], math.sin(0.5))
        self.assertEqual(mission["steps"][1]["type"], "inspection_action")
        self.assertEqual(mission["steps"][1]["asset_ids"], [asset["asset_id"]])
        self.assertEqual(mission["steps"][1]["parameters"], {"camera_id": "front"})
        duplicate = self.client.post(self.base + "/inspection/tasks", json=body, headers=headers)
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(duplicate.json["mission_id"], result.json["mission_id"])
        self.assertEqual(len(self.bridge.calls), 2)
        changed = self.client.post(self.base + "/inspection/tasks",
                                   json={**body, "name": "Changed"}, headers=headers)
        self.assertEqual(changed.status_code, 409)

    def test_inspection_template_compiles_offline_and_can_be_scheduled(self):
        waypoint = self.client.post(self.base + "/waypoints", json={
            "map_id": "simulation/map-a", "name": "Template Point", "x": 1, "y": 2, "yaw": 0,
        }).json
        plan_path = self.base + f"/waypoints/{waypoint['waypoint_id']}/action-plan"
        self.assertEqual(self.client.put(plan_path, json={"actions": [{
            "kind": "capture", "timeout_ms": 5000,
        }]}, headers={"If-Match": '"0"'}).status_code, 200)
        snapshot = self.bridge.snapshot()
        snapshot["pose_online"] = False
        snapshot["mission"]["inspection_provider"] = {"online": False, "stale": True, "actions": []}
        self.bridge.snapshot = lambda: snapshot
        compiled = self.client.post(self.base + "/inspection/tasks", json={
            "name": "Daily template", "waypoint_ids": [waypoint["waypoint_id"]], "compile_only": True,
        }, headers={"Idempotency-Key": "inspection-template-0001"})
        self.assertEqual(compiled.status_code, 201)
        self.assertEqual(compiled.json["status"], "compiled")
        self.assertEqual([call[0]["command"] for call in self.bridge.calls], ["save"])
        mission = self.bridge.calls[0][0]["mission"]
        self.assertEqual(mission["id"], compiled.json["mission_id"])
        self.assertEqual(mission["steps"][1]["type"], "inspection_action")
        scheduled = self.client.post(self.base + "/schedules", json={
            "schedule": {"name": "Daily template", "mission_id": compiled.json["mission_id"]},
        }, headers={"Idempotency-Key": "inspection-template-schedule-01"})
        self.assertEqual(scheduled.status_code, 202)
        self.assertEqual(self.bridge.calls[-1][0]["command"], "schedule.save")

    def test_ordered_inspection_points_compile_business_transit_business_and_repeat(self):
        points = [self.client.post(self.base + "/waypoints", json={
            "map_id": "simulation/map-a", "name": name, "x": index, "y": 0, "yaw": 0,
        }).json for index, name in enumerate(("Photo", "Corner", "Fire"))]
        for point in (points[0], points[2]):
            self.assertEqual(self.client.put(
                self.base + f"/waypoints/{point['waypoint_id']}/action-plan",
                json={"actions": [{"kind": "capture", "timeout_ms": 1000}]},
                headers={"If-Match": '"0"'},
            ).status_code, 200)
        ordered = [{"waypoint_id": point["waypoint_id"], "execute_actions": index != 1}
                   for index, point in enumerate(points)]
        ordered.append({"waypoint_id": points[0]["waypoint_id"], "execute_actions": False})
        response = self.client.post(self.base + "/inspection/tasks", json={
            "name": "Mixed", "points": ordered, "compile_only": True,
        }, headers={"Idempotency-Key": "ordered-inspection-0001"})
        self.assertEqual(response.status_code, 201)
        mission = self.bridge.calls[-1][0]["mission"]
        self.assertEqual([step["type"] for step in mission["steps"]],
                         ["waypoint", "inspection_action", "waypoint", "waypoint",
                          "inspection_action", "waypoint"])
        self.assertEqual([step["waypoint_id"] for step in mission["steps"] if step["type"] == "waypoint"],
                         [item["waypoint_id"] for item in points] + [points[0]["waypoint_id"]])
        self.assertEqual(len({step["id"] for step in mission["steps"]}), len(mission["steps"]))
        call_count = len(self.bridge.calls)
        self.assertEqual(self.client.post(self.base + "/inspection/tasks", json={
            "name": "Mixed", "points": ordered, "compile_only": True,
        }, headers={"Idempotency-Key": "ordered-inspection-0001"}).status_code, 201)
        self.assertEqual(len(self.bridge.calls), call_count)
        self.assertEqual(self.client.post(self.base + "/inspection/tasks", json={
            "name": "Invalid", "points": [{"waypoint_id": "missing", "execute_actions": False}],
            "compile_only": True,
        }, headers={"Idempotency-Key": "ordered-inspection-0002"}).status_code, 404)
        transit_only = self.client.post(self.base + "/inspection/tasks", json={
            "name": "Transit route", "points": [{"waypoint_id": points[1]["waypoint_id"], "execute_actions": False}],
            "compile_only": True,
        }, headers={"Idempotency-Key": "ordered-inspection-0003"})
        self.assertEqual(transit_only.status_code, 201)
        self.assertEqual([step["type"] for step in self.bridge.calls[-1][0]["mission"]["steps"]], ["waypoint"])
        disabled = self.client.patch(self.base + f"/waypoints/{points[1]['waypoint_id']}",
                                     json={"enabled": False}, headers={"If-Match": '"1"'})
        self.assertEqual(disabled.status_code, 200)
        self.assertEqual(self.client.post(self.base + "/inspection/tasks", json={
            "name": "Disabled", "points": [{"waypoint_id": points[1]["waypoint_id"], "execute_actions": False}],
            "compile_only": True,
        }, headers={"Idempotency-Key": "ordered-inspection-0004"}).status_code, 409)
        self.assertEqual(self.client.patch(self.base + f"/waypoints/{points[1]['waypoint_id']}",
                                           json={"enabled": True}, headers={"If-Match": '"2"'}).status_code, 200)

        snapshot = self.bridge.snapshot()
        snapshot["mission"]["missions"].append(mission)
        self.bridge.snapshot = lambda: snapshot
        updated = self.client.post(self.base + "/inspection/tasks", json={
            "name": "Mixed updated", "points": ordered[:3], "compile_only": True,
            "mission_id": mission["id"],
        }, headers={"Idempotency-Key": "ordered-inspection-update-01"})
        self.assertEqual(updated.status_code, 201)
        self.assertEqual(self.bridge.calls[-1][0]["mission"]["id"], mission["id"])
        snapshot["mission"]["schedules"].append({"mission_id": mission["id"]})
        self.assertEqual(self.client.post(self.base + "/inspection/tasks", json={
            "name": "Forbidden update", "points": ordered[:3], "compile_only": True,
            "mission_id": mission["id"],
        }, headers={"Idempotency-Key": "ordered-inspection-update-02"}).status_code, 409)

    def test_inspection_task_blocks_without_fresh_capabilities(self):
        waypoint = self.client.post(self.base + "/waypoints", json={
            "map_id": "simulation/map-a", "name": "Blocked", "x": 0, "y": 0, "yaw": 0,
        }).json
        self.client.put(self.base + f"/waypoints/{waypoint['waypoint_id']}/action-plan",
                        json={"actions": [{"kind": "capture", "timeout_ms": 1000}]},
                        headers={"If-Match": '"0"'})
        fake = FakeBridge()
        fake_snapshot = fake.snapshot()
        fake_snapshot["mission"]["inspection_provider"] = {
            "online": False, "stale": True, "actions": [],
        }
        self.bridge.snapshot = lambda: fake_snapshot
        result = self.client.post(self.base + "/inspection/tasks",
                                  json={"waypoint_ids": [waypoint["waypoint_id"]]},
                                  headers={"Idempotency-Key": "inspection-block-01"})
        self.assertEqual(result.status_code, 503)
        self.assertEqual(self.bridge.calls, [])

    def test_waypoints_are_persistent_robot_scoped_and_revision_checked(self):
        body = {
            "map_id": "simulation/map-a", "name": "Inspection A", "x": 1.25,
            "y": -0.8, "yaw": 1.57, "wait_time": 2.0,
        }
        created = self.client.post(self.base + "/waypoints", json=body)
        self.assertEqual(created.status_code, 201)
        waypoint = created.json
        self.assertEqual(waypoint["revision"], 1)
        self.assertEqual(waypoint["action"], "none")
        self.assertEqual(waypoint["point_type"], "inspection")
        self.assertEqual(waypoint["source"], "operator")
        self.assertEqual(self.client.get(self.base + "/waypoints?map_id=simulation/map-a").json["waypoints"], [waypoint])
        self.assertEqual(self.client.get(self.base + "/waypoints?map_id=other").json["waypoints"], [])
        self.assertEqual(self.client.get("/api/v1/robots/other/waypoints?map_id=simulation/map-a").status_code, 403)

        updated = self.client.patch(
            self.base + "/waypoints/" + waypoint["waypoint_id"],
            json={
                "name": "Inspection A2",
                "point_type": "charge",
                "valid_from": "2026-10-08T09:00:00+08:00",
                "valid_until": "2026-10-08T17:00:00+08:00",
            }, headers={"If-Match": '"1"'},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json["revision"], 2)
        self.assertEqual(updated.json["point_type"], "charge")
        self.assertEqual(updated.json["valid_from"], "2026-10-08T01:00:00+00:00")
        self.assertEqual(updated.json["valid_until"], "2026-10-08T09:00:00+00:00")
        conflict = self.client.patch(
            self.base + "/waypoints/" + waypoint["waypoint_id"],
            json={"name": "stale edit"}, headers={"If-Match": '"1"'},
        )
        self.assertEqual(conflict.status_code, 412)

        restarted_store = PlatformStore(str(Path(self.directory.name) / "platform.sqlite3"))
        self.assertEqual(restarted_store.waypoint("robot-001", waypoint["waypoint_id"])["name"], "Inspection A2")
        deleted = self.client.delete(
            self.base + "/waypoints/" + waypoint["waypoint_id"], headers={"If-Match": '"2"'},
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get(self.base + "/waypoints/" + waypoint["waypoint_id"]).status_code, 404)

    def test_waypoint_type_columns_migrate_existing_rows(self):
        legacy_path = str(Path(self.directory.name) / "legacy-platform.sqlite3")
        with sqlite3.connect(legacy_path) as db:
            db.execute("""CREATE TABLE waypoints (
                robot_id TEXT NOT NULL, waypoint_id TEXT NOT NULL, map_id TEXT NOT NULL,
                map_version_id TEXT, name TEXT NOT NULL, x REAL NOT NULL, y REAL NOT NULL,
                yaw REAL NOT NULL, action TEXT NOT NULL DEFAULT 'none', perception_type TEXT,
                wait_time REAL NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (robot_id, waypoint_id), UNIQUE (robot_id, map_id, name)
            )""")
            db.execute(
                "INSERT INTO waypoints(robot_id, waypoint_id, map_id, name, x, y, yaw, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("robot-001", "legacy-wp", "grid-a", "Legacy", 1, 2, 0, "created", "updated"),
            )

        migrated = PlatformStore(legacy_path).waypoint("robot-001", "legacy-wp")
        self.assertEqual(migrated["point_type"], "inspection")
        self.assertEqual(migrated["source"], "operator")
        self.assertIsNone(migrated["valid_from"])
        self.assertIsNone(migrated["valid_until"])
        with sqlite3.connect(legacy_path) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 8)
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )}
            self.assertTrue({"assets", "inspection_results", "event_evidence",
                             "device_snapshots", "robot_events"} <= tables)

    def test_platform_database_rejects_future_schema_before_mutation(self):
        future_path = str(Path(self.directory.name) / "future-platform.sqlite3")
        with sqlite3.connect(future_path) as db:
            db.execute("PRAGMA user_version = 9")
        os.chmod(future_path, 0o644)
        with self.assertRaisesRegex(RuntimeError, "schema is newer"):
            PlatformStore(future_path)
        self.assertEqual(Path(future_path).stat().st_mode & 0o777, 0o644)
        with sqlite3.connect(future_path) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 9)

    def test_waypoint_payload_rejects_invalid_values_duplicate_and_unsupported_action(self):
        body = {"map_id": "simulation/map-a", "name": "A", "x": 0, "y": 0, "yaw": 0}
        self.assertEqual(self.client.post(self.base + "/waypoints", json={**body, "x": float("nan")}).status_code, 400)
        self.assertEqual(self.client.post(self.base + "/waypoints", json={**body, "yaw": 4}).status_code, 400)
        self.assertEqual(self.client.post(self.base + "/waypoints", json={**body, "action": "dock"}).status_code, 400)
        self.assertEqual(self.client.post(self.base + "/waypoints", json={**body, "point_type": "dock"}).status_code, 400)
        self.assertEqual(self.client.post(self.base + "/waypoints", json={**body, "valid_until": "2026-10-08T12:00:00"}).status_code, 400)
        self.assertEqual(self.client.post(self.base + "/waypoints", json=body).status_code, 201)
        self.assertEqual(self.client.post(self.base + "/waypoints", json=body).status_code, 409)

    def test_logs_filter_by_modified_time_paginate_and_reject_traversal(self):
        daily_directory = self.log_directory / "daily"
        daily_directory.mkdir()
        first = daily_directory / "navigation_node_1970-01-01.log"
        second = daily_directory / "mission_manager_1970-01-01.log"
        first.write_text("task_id=task-a fault_code=FAULT-7", encoding="utf-8")
        second.write_text("task_id=task-b", encoding="utf-8")
        os.utime(first, (1000, 1000))
        os.utime(second, (2000, 2000))

        page = self.client.get(self.base + "/logs?module=navigation&task_id=task-a&fault_code=FAULT-7&from=1970-01-01T00:16:00Z&to=1970-01-01T00:17:00Z")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.json["time_field"], "modified_at")
        self.assertEqual(page.json["total"], 1)
        self.assertEqual(page.json["logs"][0]["name"], first.name)

        full = self.client.get(self.base + "/logs?limit=1")
        self.assertEqual(full.json["total"], 2)
        self.assertEqual(full.json["next_offset"], 1)
        next_page = self.client.get(self.base + "/logs?limit=1&offset=1")
        self.assertEqual(next_page.json["logs"][0]["name"], first.name)
        self.assertEqual(self.client.get(self.base + "/logs?from=bad").status_code, 400)

        traversal = base64.urlsafe_b64encode(b"../../etc/passwd").decode().rstrip("=")
        self.assertEqual(
            self.client.get(self.base + "/logs/" + traversal + "/download").status_code,
            404,
        )
        symlink = daily_directory / "linked.log"
        try:
            symlink.symlink_to(first)
        except OSError:
            return
        self.assertNotIn("linked.log", [entry["name"] for entry in self.client.get(self.base + "/logs").json["logs"]])

    def test_waypoint_writes_require_current_robot_map_identity(self):
        body = {"map_id": "different-map", "name": "A", "x": 0, "y": 0, "yaw": 0}
        self.assertEqual(self.client.post(self.base + "/waypoints", json=body).status_code, 409)
        self.bridge.snapshot = lambda: {
            **FakeBridge().snapshot(), "map_identity": None, "map_identity_online": False,
        }
        body["map_id"] = "simulation/map-a"
        self.assertEqual(self.client.post(self.base + "/waypoints", json=body).status_code, 503)

    def test_referenced_waypoint_cannot_be_deleted(self):
        waypoint = self.client.post(self.base + "/waypoints", json={
            "map_id": "simulation/map-a", "name": "Referenced", "x": 0, "y": 0, "yaw": 0,
        }).json
        original_snapshot = self.bridge.snapshot
        self.bridge.snapshot = lambda: {
            **original_snapshot(),
            "mission": {
                **original_snapshot()["mission"],
                "missions": [{"id": "patrol", "steps": [{"type": "waypoint", "waypointId": waypoint["waypoint_id"]}]}],
            },
        }
        response = self.client.delete(
            self.base + "/waypoints/" + waypoint["waypoint_id"],
            headers={"If-Match": '"1"'},
        )
        self.assertEqual(response.status_code, 409)

    def test_schedule_api_returns_robot_records_and_uses_idempotent_operator_command(self):
        self.assertEqual(self.client.get(self.base + "/schedules").json["schedules"][0]["schedule_id"], "schedule-1")
        self.assertEqual(self.client.get(self.base + "/schedules/schedule-1/runs").json["runs"][0]["status"], "started")
        response = self.client.post(
            self.base + "/schedules",
            json={"schedule": {"name": "Evening", "mission_id": "patrol"}},
            headers={"Idempotency-Key": "schedule-create-01"},
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json["schedule_id"], "schedule-new")
        self.assertEqual(self.bridge.calls[-1][0]["created_by"], "local-open")


if __name__ == "__main__":
    unittest.main()
