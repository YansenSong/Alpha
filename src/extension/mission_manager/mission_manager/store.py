"""SQLite storage for mission definitions and execution history."""

import json
import os
import sqlite3
import hashlib
import uuid
from datetime import datetime, timezone


ACTIVE_STATUSES = ("RUNNING", "PAUSED")
MISSION_SCHEMA_VERSION = 5


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class MissionStore:
    def __init__(self, path, robot_id="robot-001"):
        path = os.path.expanduser(path)
        self.robot_id = robot_id
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        current_schema = self.db.execute("PRAGMA user_version").fetchone()[0]
        if current_schema > MISSION_SCHEMA_VERSION:
            self.db.close()
            raise RuntimeError(
                "Mission database schema is newer than this RobotPilot "
                f"build ({current_schema} > {MISSION_SCHEMA_VERSION})."
            )
        self.db.execute("PRAGMA journal_mode=WAL")
        try:
            self.db.executescript(
                """
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS missions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                steps_json TEXT NOT NULL,
                map_id TEXT,
                map_version_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                task_id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                mission_name TEXT NOT NULL,
                steps_json TEXT NOT NULL,
                map_id TEXT,
                map_version_id TEXT,
                status TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                attempt INTEGER NOT NULL,
                arrival_step_index INTEGER NOT NULL DEFAULT -1,
                remaining_seconds REAL NOT NULL,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                ended_at TEXT,
                reason TEXT NOT NULL,
                hold_active INTEGER NOT NULL DEFAULT 0,
                origin_request_id TEXT
            );
            CREATE TABLE IF NOT EXISTS run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                status TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                reason TEXT NOT NULL,
                robot_pose_json TEXT,
                request_id TEXT
            );
            CREATE INDEX IF NOT EXISTS run_events_task_id
                ON run_events(task_id, id);
            CREATE TABLE IF NOT EXISTS schedules (
                robot_id TEXT NOT NULL,
                schedule_id TEXT NOT NULL,
                name TEXT NOT NULL,
                mission_id TEXT NOT NULL,
                recurrence TEXT NOT NULL,
                timezone TEXT NOT NULL,
                local_time TEXT NOT NULL,
                start_date TEXT,
                weekdays_json TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                next_run_at TEXT,
                last_run_at TEXT,
                last_status TEXT,
                misfire_policy TEXT NOT NULL DEFAULT 'skip',
                overlap_policy TEXT NOT NULL DEFAULT 'skip',
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (robot_id, schedule_id)
            );
            CREATE INDEX IF NOT EXISTS schedules_due
                ON schedules(robot_id, enabled, next_run_at);
            CREATE TABLE IF NOT EXISTS schedule_runs (
                robot_id TEXT NOT NULL,
                schedule_id TEXT NOT NULL,
                scheduled_for TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 1,
                task_id TEXT,
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (robot_id, schedule_id, scheduled_for)
            );
            CREATE INDEX IF NOT EXISTS schedule_runs_history
                ON schedule_runs(robot_id, schedule_id, scheduled_for DESC);
            CREATE TABLE IF NOT EXISTS command_results (
                request_id TEXT PRIMARY KEY,
                body_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                ack_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS robot_event_outbox (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                robot_id TEXT NOT NULL,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                acked_at TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(robot_id, seq)
            );
            CREATE INDEX IF NOT EXISTS robot_event_outbox_pending
                ON robot_event_outbox(robot_id, acked_at, seq);
            CREATE TABLE IF NOT EXISTS diagnostic_fault_states (
                name TEXT PRIMARY KEY,
                level INTEGER NOT NULL,
                message TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS inspection_action_runs (
                action_run_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                request_json TEXT NOT NULL,
                result_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS inspection_action_runs_task
                ON inspection_action_runs(task_id, step_id, attempt);
                """
            )
            with self.db:
                columns = {row["name"] for row in self.db.execute("PRAGMA table_info(runs)")}
                if "hold_active" not in columns:
                    self.db.execute("ALTER TABLE runs ADD COLUMN hold_active INTEGER NOT NULL DEFAULT 0")
                if "origin_request_id" not in columns:
                    self.db.execute("ALTER TABLE runs ADD COLUMN origin_request_id TEXT")
                if "arrival_step_index" not in columns:
                    self.db.execute("ALTER TABLE runs ADD COLUMN arrival_step_index INTEGER NOT NULL DEFAULT -1")
                event_columns = {row["name"] for row in self.db.execute("PRAGMA table_info(run_events)")}
                if "request_id" not in event_columns:
                    self.db.execute("ALTER TABLE run_events ADD COLUMN request_id TEXT")
                for table in ("missions", "runs"):
                    columns = {row["name"] for row in self.db.execute(f"PRAGMA table_info({table})")}
                    for column in ("map_id", "map_version_id"):
                        if column not in columns:
                            self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
                self.db.execute(f"PRAGMA user_version = {MISSION_SCHEMA_VERSION}")
        except Exception:
            self.db.rollback()
            self.db.close()
            raise
        self.schema_version = MISSION_SCHEMA_VERSION

    def close(self):
        self.db.close()

    @staticmethod
    def _mission(row):
        if row is None:
            return None
        item = dict(row)
        item["steps"] = json.loads(item.pop("steps_json"))
        return item

    @staticmethod
    def _run(row):
        if row is None:
            return None
        item = dict(row)
        item["steps"] = json.loads(item.pop("steps_json"))
        return item

    def missions(self):
        rows = self.db.execute("SELECT * FROM missions ORDER BY created_at, id")
        return [self._mission(row) for row in rows]

    def mission(self, mission_id):
        row = self.db.execute("SELECT * FROM missions WHERE id = ?", (mission_id,)).fetchone()
        return self._mission(row)

    def save_mission(self, mission):
        now = utc_now()
        with self.db:
            self.db.execute(
                """INSERT INTO missions(id, name, steps_json, map_id, map_version_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     name = excluded.name,
                     steps_json = excluded.steps_json,
                     map_id = excluded.map_id,
                     map_version_id = excluded.map_version_id,
                     updated_at = excluded.updated_at""",
                (mission["id"], mission["name"], json.dumps(mission["steps"]), mission.get("map_id"),
                 mission.get("map_version_id"), now, now),
            )
        return self.mission(mission["id"])

    def delete_mission(self, mission_id):
        with self.db:
            cursor = self.db.execute("DELETE FROM missions WHERE id = ?", (mission_id,))
        return cursor.rowcount > 0

    def new_run(self, task_id, mission, origin_request_id=None, robot_pose=None,
                record_start_event=False):
        now = utc_now()
        with self.db:
            self.db.execute(
                """INSERT INTO runs(task_id, mission_id, mission_name, steps_json, map_id, map_version_id,
                   status, step_index, attempt, remaining_seconds,
                   started_at, updated_at, ended_at, reason, origin_request_id)
                   VALUES (?, ?, ?, ?, ?, ?, 'RUNNING', 0, 1, 0, ?, ?, NULL, 'task started', ?)""",
                (task_id, mission["id"], mission["name"], json.dumps(mission["steps"]), mission.get("map_id"),
                 mission.get("map_version_id"), now, now, origin_request_id),
            )
            if record_start_event:
                self._insert_event(
                    task_id, "RUNNING", 0, "task started", robot_pose,
                    origin_request_id, event_type="task.status_changed",
                )
        return self.run(task_id)

    def run(self, task_id):
        row = self.db.execute("SELECT * FROM runs WHERE task_id = ?", (task_id,)).fetchone()
        return self._run(row)

    def latest_run(self):
        row = self.db.execute("SELECT * FROM runs ORDER BY started_at DESC, rowid DESC LIMIT 1").fetchone()
        return self._run(row)

    def recent_runs(self, limit=20):
        rows = self.db.execute(
            "SELECT * FROM runs ORDER BY started_at DESC, rowid DESC LIMIT ?", (limit,)
        )
        return [self._run(row) for row in rows]

    def update_run(self, task_id, *, status=None, step_index=None, attempt=None,
                   arrival_step_index=None,
                   remaining_seconds=None, reason=None, hold_active=None,
                   event_reason=None, event_pose=None, event_request_id=None):
        current = self.run(task_id)
        if current is None:
            raise ValueError("unknown task_id")
        next_status = status if status is not None else current["status"]
        next_step_index = step_index if step_index is not None else current["step_index"]
        ended_at = utc_now() if next_status in ("SUCCEEDED", "FAILED", "CANCELLED") else None
        with self.db:
            self.db.execute(
                """UPDATE runs SET status = ?, step_index = ?, attempt = ?, arrival_step_index = ?,
                   remaining_seconds = ?, updated_at = ?, ended_at = ?, reason = ?,
                   hold_active = ?
                   WHERE task_id = ?""",
                (
                    next_status,
                    next_step_index,
                    attempt if attempt is not None else current["attempt"],
                    arrival_step_index if arrival_step_index is not None else current["arrival_step_index"],
                    remaining_seconds if remaining_seconds is not None else current["remaining_seconds"],
                    utc_now(),
                    ended_at,
                    reason if reason is not None else current["reason"],
                    int(hold_active) if hold_active is not None else current["hold_active"],
                    task_id,
                ),
            )
            if event_reason is not None:
                self._insert_event(
                    task_id, next_status, next_step_index, event_reason,
                    event_pose, event_request_id,
                    event_type="task.status_changed" if next_status != current["status"] else "task.event",
                )
        return self.run(task_id)

    def add_event(
        self, task_id, status, step_index, reason, robot_pose=None, request_id=None
    ):
        with self.db:
            self._insert_event(task_id, status, step_index, reason, robot_pose, request_id)

    def add_inspection_result(self, run, result, robot_pose=None):
        """Persist an inspection receipt and its business event in the robot outbox."""
        now = result["observed_at"]
        event = {
            "schema_version": 1,
            "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL,
                                  f"inspection:{self.robot_id}:{result['action_run_id']}")),
            "robot_id": self.robot_id, "source": "mission_manager",
            "type": "inspection.result", "occurred_at": now, "recorded_at": utc_now(),
            "simulation": result["source_mode"] in ("fixture", "simulation"),
            "is_test_data": result["source_mode"] == "fixture",
            "correlation": {"task_id": run["task_id"], "mission_id": run["mission_id"],
                            "request_id": run.get("origin_request_id"),
                            "map_id": run.get("map_id"), "map_version_id": run.get("map_version_id")},
            "severity": "WARNING" if result["outcome"] == "ABNORMAL" else "INFO",
            "payload": result,
        }
        with self.db:
            if self.db.execute("SELECT 1 FROM robot_event_outbox WHERE event_id=?",
                               (event["event_id"],)).fetchone():
                return event["event_id"]
            self._insert_event(run["task_id"], run["status"], run["step_index"],
                               f"inspection result {result['result_id']}: {result['outcome']}",
                               robot_pose, run.get("origin_request_id"))
            self._write_outbox(event)
        return event["event_id"]

    def inspection_request(self, action_run_id):
        row = self.db.execute("SELECT request_json FROM inspection_action_runs WHERE action_run_id=?",
                              (action_run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_inspection_request(self, request):
        action_run_id = request["action_run_id"]
        existing = self.inspection_request(action_run_id)
        if existing is not None:
            if existing != request:
                raise ValueError("action_run_id already has a different request")
            return existing
        now = utc_now()
        with self.db:
            self.db.execute(
                """INSERT INTO inspection_action_runs(action_run_id,task_id,step_id,attempt,
                   request_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?)""",
                (action_run_id, request["task_id"], request["step_id"], request["attempt"],
                 json.dumps(request, allow_nan=False, sort_keys=True), now, now),
            )
        return request

    def inspection_result(self, action_run_id):
        row = self.db.execute("SELECT result_json FROM inspection_action_runs WHERE action_run_id=?",
                              (action_run_id,)).fetchone()
        return json.loads(row[0]) if row and row[0] else None

    def save_inspection_result(self, result):
        action_run_id = result["action_run_id"]
        with self.db:
            row = self.db.execute(
                "SELECT request_json,result_json FROM inspection_action_runs WHERE action_run_id=?",
                (action_run_id,),
            ).fetchone()
            if not row:
                raise ValueError("unknown inspection action_run_id")
            existing = json.loads(row["result_json"]) if row["result_json"] else None
            if existing is not None:
                if existing != result:
                    raise ValueError("action_run_id received conflicting results")
                return existing
            self.db.execute(
                "UPDATE inspection_action_runs SET result_json=?,updated_at=? WHERE action_run_id=?",
                (json.dumps(result, allow_nan=False, sort_keys=True), utc_now(), action_run_id),
            )
        return result

    def record_late_inspection_result(self, result):
        """Keep a bounded late provider receipt for audit without task progression."""
        encoded = json.dumps(result, allow_nan=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 65536:
            raise ValueError("late inspection result exceeds 64 KiB")
        event_id = str(uuid.uuid5(uuid.NAMESPACE_URL,
                                  f"late:{result['action_run_id']}:{result['result_id']}"))
        event = {
            "schema_version": 1, "event_id": event_id,
            "robot_id": self.robot_id, "source": "mission_manager",
            "type": "inspection.result.late", "occurred_at": result["observed_at"],
            "recorded_at": utc_now(),
            "simulation": result["source_mode"] in ("fixture", "simulation"),
            "is_test_data": result["source_mode"] == "fixture",
            "correlation": {"task_id": result["task_id"], "mission_id": result.get("mission_id"),
                            "request_id": None, "map_id": result.get("map_id"),
                            "map_version_id": result.get("map_version_id")},
            "severity": "WARNING", "payload": {**result, "late": True},
        }
        with self.db:
            exists = self.db.execute("SELECT 1 FROM robot_event_outbox WHERE event_id=?", (event_id,)).fetchone()
            if exists:
                return event_id
            self._write_outbox(event)
        return event_id

    def _insert_event(self, task_id, status, step_index, reason, robot_pose,
                      request_id, *, event_type="task.event"):
        """Write the run history and its durable outbound event in one transaction."""
        now = utc_now()
        self.db.execute(
            """INSERT INTO run_events(task_id, timestamp, status, step_index,
               reason, robot_pose_json, request_id) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (task_id, now, status, step_index, reason,
             json.dumps(robot_pose) if robot_pose is not None else None, request_id),
        )
        run = self.db.execute(
            "SELECT mission_id, map_id, map_version_id FROM runs WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        event_id = str(uuid.uuid4())
        event = {
            "schema_version": 1, "event_id": event_id,
            "robot_id": self.robot_id, "source": "mission_manager",
            "type": event_type, "occurred_at": now, "recorded_at": now,
            "simulation": os.environ.get("ROBOT_MODE") == "simulation",
            "correlation": {
                "task_id": task_id, "mission_id": run["mission_id"] if run else None,
                "request_id": request_id,
                "map_id": run["map_id"] if run else None,
                "map_version_id": run["map_version_id"] if run else None,
            },
            "severity": "ERROR" if status == "FAILED" else "INFO",
            "payload": {"status": status, "step_index": step_index, "reason": reason,
                        "robot_pose": robot_pose},
        }
        self._write_outbox(event)

    def _write_outbox(self, event):
        now = event["occurred_at"]
        event_id = event["event_id"]
        event_type = event["type"]
        cursor = self.db.execute(
            """INSERT INTO robot_event_outbox
               (event_id, robot_id, source, event_type, occurred_at, payload_json,
                schema_version, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
            (event_id, self.robot_id, event["source"], event_type, now,
             json.dumps(event, separators=(",", ":"), allow_nan=False), now),
        )
        event["source_seq"] = cursor.lastrowid
        self.db.execute(
            "UPDATE robot_event_outbox SET payload_json = ? WHERE seq = ?",
            (json.dumps(event, separators=(",", ":"), allow_nan=False), cursor.lastrowid),
        )

    def observe_fault(self, name, level, message):
        """Persist diagnostic state changes on the robot even when Flask is offline."""
        if not isinstance(name, str) or not name or len(name) > 256:
            raise ValueError("diagnostic name is invalid")
        if isinstance(level, bool) or level not in (0, 1, 2, 3):
            raise ValueError("diagnostic level is invalid")
        message = str(message)[:1024]
        with self.db:
            previous = self.db.execute(
                "SELECT level, message FROM diagnostic_fault_states WHERE name = ?", (name,)
            ).fetchone()
            if previous and previous["level"] == level and previous["message"] == message:
                return None
            now = utc_now()
            self.db.execute(
                """INSERT INTO diagnostic_fault_states(name, level, message, updated_at)
                   VALUES (?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET
                   level = excluded.level, message = excluded.message,
                   updated_at = excluded.updated_at""",
                (name, level, message, now),
            )
            if level == 0 and (previous is None or previous["level"] == 0):
                return None
            event_type = ("fault.resolved" if level == 0 else
                          "fault.updated" if previous and previous["level"] > 0 else
                          "fault.raised")
            current_run = self.latest_run()
            event = {
                "schema_version": 1, "event_id": str(uuid.uuid4()),
                "robot_id": self.robot_id, "source": "mission_manager",
                "type": event_type, "occurred_at": now, "recorded_at": now,
                "simulation": os.environ.get("ROBOT_MODE") == "simulation",
                "correlation": {
                    "task_id": current_run["task_id"] if current_run and current_run["status"] in ACTIVE_STATUSES else None,
                    "request_id": current_run.get("origin_request_id") if current_run and current_run["status"] in ACTIVE_STATUSES else None,
                    "fault_code": "DIAG-" + hashlib.sha1(name.encode()).hexdigest()[:12].upper(),
                },
                "severity": "ERROR" if level >= 2 else "WARNING" if level == 1 else "INFO",
                "payload": {"name": name, "message": message, "level": level},
            }
            self._write_outbox(event)
            return event["event_id"]

    def active_critical_faults(self):
        return [dict(row) for row in self.db.execute(
            "SELECT name, level, message FROM diagnostic_fault_states WHERE level >= 2 ORDER BY name"
        ).fetchall()]

    def reserve_command(self, request_id, command):
        """Persist a claim before execution; a crash leaves an unknown result, never a replay."""
        body_hash = hashlib.sha256(json.dumps(
            command, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        now = utc_now()
        with self.db:
            inserted = self.db.execute(
                """INSERT OR IGNORE INTO command_results
                   (request_id, body_hash, status, ack_json, created_at, updated_at)
                   VALUES (?, ?, 'pending', NULL, ?, ?)""",
                (request_id, body_hash, now, now),
            )
            row = self.db.execute(
                "SELECT body_hash, status, ack_json FROM command_results WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row["body_hash"] != body_hash:
                raise ValueError("request_id was used for a different command")
            return inserted.rowcount == 1, json.loads(row["ack_json"]) if row["ack_json"] else None

    def finish_command(self, request_id, ack):
        with self.db:
            self.db.execute(
                """UPDATE command_results SET status = ?, ack_json = ?, updated_at = ?
                   WHERE request_id = ? AND status = 'pending'""",
                ("accepted" if ack.get("ok") else "rejected",
                 json.dumps(ack, separators=(",", ":")), utc_now(), request_id),
            )

    def pending_events(self, limit=100):
        limit = max(1, min(int(limit), 100))
        with self.db:
            rows = list(self.db.execute(
                """SELECT seq, payload_json FROM robot_event_outbox
                   WHERE robot_id = ? AND acked_at IS NULL ORDER BY seq LIMIT ?""",
                (self.robot_id, limit),
            ))
            if rows:
                self.db.executemany(
                    "UPDATE robot_event_outbox SET retry_count = retry_count + 1 WHERE seq = ?",
                    [(row["seq"],) for row in rows],
                )
        return [json.loads(row["payload_json"]) for row in rows]

    def outbox_status(self):
        row = self.db.execute(
            """SELECT COUNT(*) AS pending_count, MIN(seq) AS oldest_pending_seq,
                      MAX(seq) AS latest_seq, MAX(retry_count) AS max_retry_count
               FROM robot_event_outbox WHERE robot_id = ? AND acked_at IS NULL""",
            (self.robot_id,),
        ).fetchone()
        latest = self.db.execute(
            "SELECT COALESCE(MAX(seq), 0) FROM robot_event_outbox WHERE robot_id = ?",
            (self.robot_id,),
        ).fetchone()[0]
        return {
            "pending_count": row["pending_count"],
            "oldest_pending_seq": row["oldest_pending_seq"],
            "latest_seq": latest,
            "max_retry_count": row["max_retry_count"] or 0,
            "capacity_warning": row["pending_count"] >= 10000,
        }

    def acknowledge_events(self, through_seq):
        if isinstance(through_seq, bool) or not isinstance(through_seq, int) or through_seq < 1:
            raise ValueError("through_seq must be a positive integer")
        with self.db:
            self.db.execute(
                """UPDATE robot_event_outbox SET acked_at = ?
                   WHERE robot_id = ? AND seq <= ? AND acked_at IS NULL""",
                (utc_now(), self.robot_id, through_seq),
            )

    def events(self, task_id, limit=200):
        rows = self.db.execute(
            """SELECT timestamp, status, step_index, reason, robot_pose_json, request_id
               FROM run_events WHERE task_id = ? ORDER BY id DESC LIMIT ?""",
            (task_id, limit),
        )
        return [
            {
                "timestamp": row["timestamp"],
                "status": row["status"],
                "step_index": row["step_index"],
                "reason": row["reason"],
                "robot_pose": json.loads(row["robot_pose_json"]) if row["robot_pose_json"] else None,
                "request_id": row["request_id"],
            }
            for row in reversed(list(rows))
        ]

    @staticmethod
    def _schedule(row):
        if row is None:
            return None
        item = dict(row)
        item["enabled"] = bool(item["enabled"])
        item["weekdays"] = json.loads(item.pop("weekdays_json"))
        return item

    def schedules(self, robot_id):
        rows = self.db.execute(
            "SELECT * FROM schedules WHERE robot_id = ? ORDER BY created_at, schedule_id",
            (robot_id,),
        )
        return [self._schedule(row) for row in rows]

    def schedule(self, robot_id, schedule_id):
        row = self.db.execute(
            "SELECT * FROM schedules WHERE robot_id = ? AND schedule_id = ?",
            (robot_id, schedule_id),
        ).fetchone()
        return self._schedule(row)

    def create_schedule(self, robot_id, value):
        now = utc_now()
        with self.db:
            self.db.execute(
                """INSERT INTO schedules(robot_id, schedule_id, name, mission_id, recurrence,
                   timezone, local_time, start_date, weekdays_json, enabled, next_run_at,
                   misfire_policy, overlap_policy, created_by, created_at, updated_at, revision)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'skip', 'skip', ?, ?, ?, 1)""",
                (robot_id, value["schedule_id"], value["name"], value["mission_id"],
                 value["recurrence"], value["timezone"], value["local_time"], value.get("start_date"),
                 json.dumps(value.get("weekdays", [])), int(value["enabled"]), value.get("next_run_at"),
                 value["created_by"], now, now),
            )
        return self.schedule(robot_id, value["schedule_id"])

    def update_schedule(self, robot_id, schedule_id, value, expected_revision):
        now = utc_now()
        with self.db:
            cursor = self.db.execute(
                """UPDATE schedules SET name = ?, mission_id = ?, recurrence = ?, timezone = ?,
                   local_time = ?, start_date = ?, weekdays_json = ?, enabled = ?, next_run_at = ?,
                   updated_at = ?, revision = revision + 1
                   WHERE robot_id = ? AND schedule_id = ? AND revision = ?""",
                (value["name"], value["mission_id"], value["recurrence"], value["timezone"],
                 value["local_time"], value.get("start_date"), json.dumps(value.get("weekdays", [])),
                 int(value["enabled"]), value.get("next_run_at"), now, robot_id, schedule_id,
                 expected_revision),
            )
            if cursor.rowcount != 1:
                return None
        return self.schedule(robot_id, schedule_id)

    def delete_schedule(self, robot_id, schedule_id, expected_revision):
        with self.db:
            cursor = self.db.execute(
                "DELETE FROM schedules WHERE robot_id = ? AND schedule_id = ? AND revision = ?",
                (robot_id, schedule_id, expected_revision),
            )
        return cursor.rowcount == 1

    def due_schedules(self, robot_id, now):
        rows = self.db.execute(
            """SELECT * FROM schedules WHERE robot_id = ? AND enabled = 1
               AND next_run_at IS NOT NULL AND next_run_at <= ? ORDER BY next_run_at""",
            (robot_id, now),
        )
        return [self._schedule(row) for row in rows]

    def claim_schedule_run(self, robot_id, schedule_id, scheduled_for, next_run_at):
        now = utc_now()
        self.db.execute("BEGIN IMMEDIATE")
        current = self.schedule(robot_id, schedule_id)
        if not current or not current["enabled"] or current["next_run_at"] != scheduled_for:
            self.db.rollback()
            return False
        inserted = self.db.execute(
            """INSERT OR IGNORE INTO schedule_runs(robot_id, schedule_id, scheduled_for,
               status, created_at, updated_at) VALUES (?, ?, ?, 'claimed', ?, ?)""",
            (robot_id, schedule_id, scheduled_for, now, now),
        )
        if inserted.rowcount != 1:
            self.db.rollback()
            return False
        enabled = current["recurrence"] != "once"
        self.db.execute(
            """UPDATE schedules SET enabled = ?, next_run_at = ?, last_run_at = ?,
               last_status = 'claimed', revision = revision + 1, updated_at = ?
               WHERE robot_id = ? AND schedule_id = ?""",
            (int(enabled), next_run_at, scheduled_for, now, robot_id, schedule_id),
        )
        self.db.commit()
        return True

    def finish_schedule_run(self, robot_id, schedule_id, scheduled_for, status, reason="", task_id=None):
        with self.db:
            self.db.execute(
                """UPDATE schedule_runs SET status = ?, reason = ?, task_id = ?, updated_at = ?
                   WHERE robot_id = ? AND schedule_id = ? AND scheduled_for = ?
                   AND status = 'claimed'""",
                (status, reason, task_id, utc_now(), robot_id, schedule_id, scheduled_for),
            )
            self.db.execute(
                """UPDATE schedules SET last_status = ?, updated_at = ?
                   WHERE robot_id = ? AND schedule_id = ?""",
                (status, utc_now(), robot_id, schedule_id),
            )

    def recover_claimed_schedules(self, robot_id):
        with self.db:
            self.db.execute(
                """UPDATE schedule_runs SET status = 'unknown', reason = 'scheduler restarted after claim',
                   updated_at = ? WHERE robot_id = ? AND status = 'claimed'""",
                (utc_now(), robot_id),
            )

    def schedule_history(self, robot_id, schedule_id, limit=100):
        rows = self.db.execute(
            """SELECT * FROM schedule_runs WHERE robot_id = ? AND schedule_id = ?
               ORDER BY scheduled_for DESC LIMIT ?""",
            (robot_id, schedule_id, limit),
        )
        return [dict(row) for row in rows]

    def schedule_runs(self, robot_id, limit=500):
        rows = self.db.execute(
            """SELECT * FROM schedule_runs WHERE robot_id = ?
               ORDER BY scheduled_for DESC LIMIT ?""",
            (robot_id, limit),
        )
        return [dict(row) for row in rows]
