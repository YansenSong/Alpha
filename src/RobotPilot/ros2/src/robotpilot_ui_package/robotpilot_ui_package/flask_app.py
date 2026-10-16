import os
import json
import re
import signal
import subprocess
import time
import ipaddress
import urllib.request
import urllib.error
import urllib.parse
import threading
from datetime import datetime, timezone
import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from flask import Flask, Response, abort, g, jsonify, request, send_file, send_from_directory
from ament_index_python.packages import get_package_share_directory
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from .auth import install_auth, require_role, validate_auth_transport, validate_bind_host
from .platform_api import (
    PlatformStore,
    RobotBridge,
    audit_api_response,
    register_platform_api,
)
from .data_paths import data_directory, setting
from .recording_maintenance import prune_finished_recordings


# ─────────────────────────────────────────────────────────────────────────
# AUTH_MODE=open is only for loopback development. local uses server-side
# sessions; external remains unavailable until an OIDC integration exists.
# ─────────────────────────────────────────────────────────────────────────
VALID_AUTH_MODES = {"open", "local", "external"}
IMPLEMENTED_AUTH_MODES = {"open", "local"}

REQUESTED_AUTH_MODE = os.environ.get("AUTH_MODE", "open").strip().lower()
if REQUESTED_AUTH_MODE not in IMPLEMENTED_AUTH_MODES:
    raise RuntimeError(f"AUTH_MODE={REQUESTED_AUTH_MODE!r} is unavailable; refusing to start")
AUTH_MODE = REQUESTED_AUTH_MODE
AUTH_MODE_WARNING = None
DATA_DIR = data_directory()
ROBOT_ID = setting("ROBOT_ID", "robot-001")
AUTH_DB_PATH = setting("AUTH_DB", os.path.join(DATA_DIR, "auth.sqlite3"))
PLATFORM_DB_PATH = setting("PLATFORM_DB", os.path.join(DATA_DIR, "platform.sqlite3"))
PLATFORM_BRIDGE = None
PLATFORM_STORE = None


def is_local_address(addr):
    """如果 addr 是 loopback/private/link-local IP（即“本地网络”）则返回 True。
    仅用于在 AUTH_MODE=open 时向操作员显示提示，不用于访问控制。"""
    if not addr:
        return False
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local)

# React 构建文件由 setup.py 安装到 share/robotpilot_ui_package/static/app/。
SHARE_DIR = get_package_share_directory("robotpilot_ui_package")
REACT_BUILD_DIR = os.path.join(SHARE_DIR, "app")
REACT_STATIC_DIR = os.path.join(REACT_BUILD_DIR, "static")
REACT_ROS_DIR = os.path.join(REACT_BUILD_DIR, "ros")

# 让 Flask 从 CRA 构建目录提供 /static/*。
app = Flask(__name__, static_folder=REACT_STATIC_DIR, static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
if setting("UI_TRUST_PROXY", "") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1)

PROGRAM_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")
BLOCK_PROGRAMS_DIR = os.path.join(
    DATA_DIR, "block_programs"
)
BLOCK_LOCATIONS_FILE = os.path.join(
    DATA_DIR, "block_locations.json"
)
BLOCK_RUN_HISTORY_FILE = os.path.join(
    DATA_DIR, "block_run_history.json"
)
RECORDING_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")
RECORDINGS_DIR = os.path.join(DATA_DIR, "recordings")
RECORDINGS_INDEX_FILE = os.path.join(RECORDINGS_DIR, "index.json")
TOPIC_NAME_RE = re.compile(r"^/[A-Za-z0-9_/]{1,255}$")

# 仅限进程内使用：此 Flask 服务器以单个 Werkzeug 进程运行（threaded=True，而非多 worker），
# 因此在此处使用模块级状态是安全的。
# Flask 重启后这些状态不会保留：如果录制/回放期间发生重启，实际的 `ros2 bag` 操作系统进程可能会成为孤儿进程并继续运行。
# 此问题已标记但尚未解决；参见下方的 _reconcile_recordings_on_startup。
_recording = {"proc": None, "id": None, "name": None, "started_at": None, "topics": None}
_replay = {"proc": None, "id": None, "started_at": None, "paused": False, "rate": 1.0}
RECORDING_RETENTION_DAYS = 0
_last_recording_prune = 0.0
DEFAULT_BLOCK_LOCATIONS = {
    "Home": {"x": 0, "y": 0, "yaw": 0},
    "Charging Station": {"x": 0.5, "y": 0, "yaw": 0},
    "Pickup Point": {"x": 2, "y": 1, "yaw": 1.57},
    "Dropoff Point": {"x": 0, "y": 2, "yaw": 3.14},
}

# Mirrors web/src/shared/constants/index.js AppConfig so the model doesn't
# propose speeds the UI's own plan validation will just reject.
MAX_LINEAR_SPEED = 0.2
MAX_ANGULAR_SPEED = 2

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-sonnet-5"
ANTHROPIC_VERSION = "2023-06-01"

ACTION_TYPES = {
    "navigate",
    "navigate_named",
    "wait",
    "set_speed",
    "drive_for",
    "rotate_for",
    "stop_movement",
    "wait_nav_complete",
    "repeat",
    "battery_below",
    "log",
    "set_mode",
    "dock",
    "undock",
    "stop",
}

# JSON Schema for the tool Claude must call. Mirrors the action union already
# implemented client-side in web/src/features/blocks/blockDefinitions.js
# (blockToAction / planToWorkspace).
ACTION_SCHEMA = {
    "$defs": {
        "action": {
            "oneOf": [
                {
                    "type": "object",
                    "properties": {
                        "type": {"const": "navigate"},
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "yaw": {"type": "number", "description": "radians"},
                    },
                    "required": ["type", "x", "y", "yaw"],
                },
                {
                    "type": "object",
                    "properties": {
                        "type": {"const": "navigate_named"},
                        "location": {"type": "string"},
                    },
                    "required": ["type", "location"],
                },
                {
                    "type": "object",
                    "properties": {
                        "type": {"const": "wait"},
                        "seconds": {"type": "number"},
                    },
                    "required": ["type", "seconds"],
                },
                {
                    "type": "object",
                    "properties": {
                        "type": {"const": "set_speed"},
                        "linear": {"type": "number"},
                        "angular": {"type": "number"},
                    },
                    "required": ["type", "linear", "angular"],
                },
                {
                    "type": "object",
                    "properties": {
                        "type": {"const": "drive_for"},
                        "linear": {"type": "number"},
                        "seconds": {"type": "number"},
                    },
                    "required": ["type", "linear", "seconds"],
                },
                {
                    "type": "object",
                    "properties": {
                        "type": {"const": "rotate_for"},
                        "angular": {"type": "number"},
                        "seconds": {"type": "number"},
                    },
                    "required": ["type", "angular", "seconds"],
                },
                {
                    "type": "object",
                    "properties": {"type": {"const": "stop_movement"}},
                    "required": ["type"],
                },
                {
                    "type": "object",
                    "properties": {
                        "type": {"const": "wait_nav_complete"},
                        "timeout": {"type": "number"},
                    },
                    "required": ["type", "timeout"],
                },
                {
                    "type": "object",
                    "properties": {
                        "type": {"const": "repeat"},
                        "times": {"type": "integer", "minimum": 1},
                        "actions": {
                            "type": "array",
                            "items": {"$ref": "#/$defs/action"},
                        },
                    },
                    "required": ["type", "times", "actions"],
                },
                {
                    "type": "object",
                    "properties": {
                        "type": {"const": "battery_below"},
                        "percent": {"type": "number"},
                        "actions": {
                            "type": "array",
                            "items": {"$ref": "#/$defs/action"},
                        },
                    },
                    "required": ["type", "percent", "actions"],
                },
                {
                    "type": "object",
                    "properties": {
                        "type": {"const": "log"},
                        "message": {"type": "string"},
                    },
                    "required": ["type", "message"],
                },
                {
                    "type": "object",
                    "properties": {
                        "type": {"const": "set_mode"},
                        "mode": {"enum": ["autonomous", "manual", "idle"]},
                    },
                    "required": ["type", "mode"],
                },
                {
                    "type": "object",
                    "properties": {"type": {"const": "dock"}},
                    "required": ["type"],
                },
                {
                    "type": "object",
                    "properties": {"type": {"const": "undock"}},
                    "required": ["type"],
                },
                {
                    "type": "object",
                    "properties": {"type": {"const": "stop"}},
                    "required": ["type"],
                },
            ]
        }
    },
    "type": "object",
    "properties": {
        "actions": {"type": "array", "items": {"$ref": "#/$defs/action"}},
    },
    "required": ["actions"],
}


def build_voice_plan_system_prompt(locations):
    location_names = ", ".join(sorted(locations.keys())) or "(none saved yet)"
    return (
        "You translate a spoken command for a mobile robot into a structured "
        "action plan by calling the build_robot_plan tool. Only use the action "
        "types defined in the tool schema. Prefer navigate_named over navigate "
        "when the command refers to one of the known named locations: "
        f"{location_names}. Keep set_speed/drive_for linear speeds within "
        f"+/-{MAX_LINEAR_SPEED} m/s and set_speed/rotate_for angular speeds "
        f"within +/-{MAX_ANGULAR_SPEED} rad/s. If the command is ambiguous or "
        "unsafe, produce the closest reasonable safe interpretation rather than "
        "refusing. Do not add actions the command didn't ask for."
    )


def call_anthropic_voice_plan(transcript, locations):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        abort(500, "ANTHROPIC_API_KEY is not set on the server.")

    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 2048,
        "system": build_voice_plan_system_prompt(locations),
        "messages": [{"role": "user", "content": transcript}],
        "tools": [
            {
                "name": "build_robot_plan",
                "description": "Return the sequence of robot actions for the spoken command.",
                "input_schema": ACTION_SCHEMA,
            }
        ],
        "tool_choice": {"type": "tool", "name": "build_robot_plan"},
    }

    request_obj = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        },
    )

    try:
        with urllib.request.urlopen(request_obj, timeout=30) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="ignore")
        abort(502, f"Claude API request failed ({error.code}): {detail[:200]}")
    except urllib.error.URLError as error:
        abort(502, f"Could not reach Claude API: {error.reason}")

    for block in body.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "build_robot_plan":
            return block.get("input", {}).get("actions", [])

    abort(502, "Claude did not return a robot plan.")


def generate_voice_plan_actions(transcript, locations):
    return call_anthropic_voice_plan(transcript, locations)


def sanitize_plan_actions(actions):
    if not isinstance(actions, list):
        return []

    sanitized = []
    for action in actions:
        if not isinstance(action, dict) or action.get("type") not in ACTION_TYPES:
            continue

        clean = dict(action)
        if clean["type"] in ("repeat", "battery_below"):
            clean["actions"] = sanitize_plan_actions(clean.get("actions"))
        sanitized.append(clean)

    return sanitized


def ensure_block_programs_dir():
    os.makedirs(BLOCK_PROGRAMS_DIR, exist_ok=True)


def ensure_robotpilot_data_dir():
    os.makedirs(os.path.dirname(BLOCK_LOCATIONS_FILE), exist_ok=True)


def program_path(name: str):
    if not PROGRAM_NAME_RE.match(name):
        abort(
            400,
            "Program names must be 1-64 characters and may use letters, numbers, spaces, dots, underscores, or hyphens.",
        )
    return os.path.join(BLOCK_PROGRAMS_DIR, f"{name}.json")


def validate_name(name: str, entity: str):
    if not PROGRAM_NAME_RE.match(name):
        abort(
            400,
            f"{entity} names must be 1-64 characters and may use letters, numbers, spaces, dots, underscores, or hyphens.",
        )


def parse_float(value, field: str):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        abort(400, f"{field} must be a number.")

    return parsed


def ensure_recordings_dir():
    os.makedirs(RECORDINGS_DIR, exist_ok=True)


def read_recordings_index():
    if not os.path.exists(RECORDINGS_INDEX_FILE):
        return []
    try:
        with open(RECORDINGS_INDEX_FILE, "r", encoding="utf-8") as index_file:
            return json.load(index_file)
    except (OSError, json.JSONDecodeError):
        return []


def write_recordings_index(entries):
    ensure_recordings_dir()
    with open(RECORDINGS_INDEX_FILE, "w", encoding="utf-8") as index_file:
        json.dump(entries, index_file, indent=2, sort_keys=True)


def dir_size_bytes(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for filename in files:
            try:
                total += os.path.getsize(os.path.join(root, filename))
            except OSError:
                pass
    return total


def validate_recording_name(name: str):
    if not RECORDING_NAME_RE.match(name or ""):
        abort(
            400,
            "Recording names must be 1-64 characters and may use letters, numbers, spaces, dots, underscores, or hyphens.",
        )


def validate_topics(topics):
    if topics is None:
        return None
    if not isinstance(topics, list) or not topics:
        abort(400, "topics must be a non-empty array of topic names, or omitted to record everything.")
    for topic in topics:
        if not isinstance(topic, str) or not TOPIC_NAME_RE.match(topic):
            abort(400, f"Invalid topic name: {topic!r}")
    return topics


def _reconcile_recordings_on_startup():
    """Any index entry still marked "recording" means Flask restarted
    mid-recording — the real ros2 bag process, if it's even still alive, is
    now orphaned and un-trackable (a fresh Python process has no handle to
    it). Don't guess whether it's fine; mark it honestly as interrupted."""
    entries = read_recordings_index()
    changed = False
    for entry in entries:
        if entry.get("status") == "recording":
            entry["status"] = "interrupted"
            print(
                f"[robotpilot_ui_package] WARNING: recording '{entry.get('name')}' was still "
                "marked active at startup — Flask must have restarted mid-recording. "
                "Marked interrupted; check whether a leftover ros2 bag process is still running."
            )
            changed = True
    if changed:
        write_recordings_index(entries)


_reconcile_recordings_on_startup()


def _configure_recording_retention():
    global RECORDING_RETENTION_DAYS
    raw_value = setting("RECORDING_RETENTION_DAYS", "0").strip()
    try:
        retention_days = int(raw_value)
        if retention_days < 0:
            raise ValueError("must be zero or a positive number of days")
    except ValueError as error:
        app.logger.error(
            "Invalid ROBOTPILOT_RECORDING_RETENTION_DAYS=%r: %s; "
            "pruning disabled",
            raw_value,
            error,
        )
        retention_days = 0
    RECORDING_RETENTION_DAYS = retention_days
    _prune_recordings_if_due(force=True)


def _prune_recordings_if_due(force=False):
    global _last_recording_prune
    if RECORDING_RETENTION_DAYS <= 0:
        return []
    now_monotonic = time.monotonic()
    if not force and now_monotonic - _last_recording_prune < 3600:
        return []
    _last_recording_prune = now_monotonic
    try:
        removed = prune_finished_recordings(
            RECORDINGS_DIR,
            RECORDINGS_INDEX_FILE,
            RECORDING_RETENTION_DAYS,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        app.logger.error("Rosbag retention cleanup failed: %s", error)
        return []
    if removed:
        app.logger.info("Removed %d expired Rosbag recording(s)", len(removed))
    return removed


_configure_recording_retention()


def read_program_file(path: str):
    with open(path, "r", encoding="utf-8") as program_file:
        return json.load(program_file)


def read_block_locations():
    if not os.path.exists(BLOCK_LOCATIONS_FILE):
        return DEFAULT_BLOCK_LOCATIONS.copy()

    try:
        with open(BLOCK_LOCATIONS_FILE, "r", encoding="utf-8") as locations_file:
            data = json.load(locations_file)
    except (OSError, json.JSONDecodeError):
        return DEFAULT_BLOCK_LOCATIONS.copy()

    if not isinstance(data, dict):
        return DEFAULT_BLOCK_LOCATIONS.copy()

    locations = {}
    for name, pose in data.items():
        if not isinstance(name, str) or not PROGRAM_NAME_RE.match(name):
            continue
        if not isinstance(pose, dict):
            continue

        try:
            locations[name] = {
                "x": float(pose["x"]),
                "y": float(pose["y"]),
                "yaw": float(pose["yaw"]),
            }
        except (KeyError, TypeError, ValueError):
            continue

    return locations or DEFAULT_BLOCK_LOCATIONS.copy()


def write_block_locations(locations):
    ensure_robotpilot_data_dir()
    with open(BLOCK_LOCATIONS_FILE, "w", encoding="utf-8") as locations_file:
        json.dump(locations, locations_file, indent=2, sort_keys=True)


def read_run_history():
    if not os.path.exists(BLOCK_RUN_HISTORY_FILE):
        return []

    try:
        with open(BLOCK_RUN_HISTORY_FILE, "r", encoding="utf-8") as history_file:
            data = json.load(history_file)
    except (OSError, json.JSONDecodeError):
        return []

    return data if isinstance(data, list) else []


def write_run_history(history):
    ensure_robotpilot_data_dir()
    with open(BLOCK_RUN_HISTORY_FILE, "w", encoding="utf-8") as history_file:
        json.dump(history[:100], history_file, indent=2, sort_keys=True)


@app.after_request
def add_api_headers(response):
    if request.path.startswith("/api/"):
        response.headers["X-Request-Id"] = getattr(g, "request_id", "")
        if PLATFORM_STORE is not None and request.method not in ("GET", "HEAD", "OPTIONS"):
            identity = getattr(g, "identity", {})
            response = audit_api_response(
                response,
                PLATFORM_STORE,
                getattr(g, "request_id", ""),
                identity,
                request.method,
                request.path,
                app.logger,
            )
    if request.headers.get("Origin") in ("http://localhost:3000", "http://127.0.0.1:3000"):
        response.headers["Access-Control-Allow-Origin"] = request.headers["Origin"]
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-CSRF-Token, Idempotency-Key, X-Request-ID"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    return response


@app.errorhandler(HTTPException)
def handle_http_error(error):
    if request.path.startswith("/api/"):
        return (
            jsonify(
                {
                    "code": error.code,
                    "message": error.description,
                    "request_id": getattr(g, "request_id", ""),
                }
            ),
            error.code,
        )
    return error


@app.route("/api/auth/status", methods=["GET"])
def auth_status():
    remote_addr = request.remote_addr
    robot_mode = os.environ.get("ROBOT_MODE", "unknown").strip().lower()
    if robot_mode not in ("simulation", "hardware"):
        robot_mode = "unknown"
    return jsonify(
        {
            "mode": AUTH_MODE,
            "robot_mode": robot_mode,
            "robot_id": ROBOT_ID,
            "requestedMode": REQUESTED_AUTH_MODE,
            "implemented": REQUESTED_AUTH_MODE in IMPLEMENTED_AUTH_MODES,
            "warning": AUTH_MODE_WARNING,
            "remoteAddr": remote_addr,
            "isLocalNetwork": is_local_address(remote_addr),
        }
    )


@app.get("/api/camera/stream")
@require_role("Viewer")
def camera_stream():
    topic = request.args.get("topic", "")
    if topic not in ("/depth_camera/image_raw", "/depth_camera/depth/image_raw"):
        abort(400, "Unsupported camera topic.")
    try:
        quality = int(request.args.get("quality", "45"))
        width = int(request.args.get("width", "480"))
        height = int(request.args.get("height", "360"))
    except ValueError:
        abort(400, "Invalid camera settings.")
    if not (1 <= quality <= 90 and 1 <= width <= 1280 and 1 <= height <= 720):
        abort(400, "Camera settings are out of range.")
    # web_video_server in Humble treats the topic parameter literally instead
    # of percent-decoding it. The allowlist above makes raw '/' safe here.
    query = "topic=" + topic + "&" + urllib.parse.urlencode({
        "type": "mjpeg", "quality": quality, "width": width, "height": height,
    })
    try:
        upstream = urllib.request.urlopen(f"http://127.0.0.1:8080/stream?{query}", timeout=5)
    except (OSError, urllib.error.URLError):
        abort(503, "Camera stream is unavailable.")

    def chunks():
        try:
            while True:
                chunk = upstream.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            upstream.close()

    return Response(chunks(), content_type=upstream.headers.get("Content-Type", "multipart/x-mixed-replace"))


@app.route("/api/block-programs", methods=["GET"])
def list_block_programs():
    ensure_block_programs_dir()
    programs = []

    for filename in sorted(os.listdir(BLOCK_PROGRAMS_DIR)):
        if not filename.endswith(".json"):
            continue

        path = os.path.join(BLOCK_PROGRAMS_DIR, filename)
        name = filename[:-5]
        try:
            data = read_program_file(path)
            name = data.get("name", name)
        except (OSError, json.JSONDecodeError):
            pass

        programs.append(
            {
                "name": name,
                "updated_at": datetime.fromtimestamp(
                    os.path.getmtime(path), timezone.utc
                ).isoformat(),
            }
        )

    return jsonify({"programs": programs})


@app.route("/api/block-programs/<path:name>", methods=["GET"])
def get_block_program(name: str):
    path = program_path(name)
    if not os.path.exists(path):
        abort(404, "Block program not found")

    return jsonify(read_program_file(path))


@app.route("/api/block-programs/<path:name>", methods=["POST", "OPTIONS"])
def save_block_program(name: str):
    if request.method == "OPTIONS":
        return ("", 204)

    payload = request.get_json(silent=True) or {}
    workspace = payload.get("workspace")
    plan = payload.get("plan", [])

    if not isinstance(workspace, dict):
        abort(400, "Request body must include a Blockly workspace object.")

    ensure_block_programs_dir()
    saved_at = datetime.now(timezone.utc).isoformat()
    data = {
        "name": name,
        "saved_at": saved_at,
        "workspace": workspace,
        "plan": plan if isinstance(plan, list) else [],
    }

    with open(program_path(name), "w", encoding="utf-8") as program_file:
        json.dump(data, program_file, indent=2, sort_keys=True)

    return jsonify(data), 201


@app.route("/api/block-programs/<path:name>", methods=["DELETE", "OPTIONS"])
def delete_block_program(name: str):
    if request.method == "OPTIONS":
        return ("", 204)

    path = program_path(name)
    if not os.path.exists(path):
        abort(404, "Block program not found")

    os.remove(path)
    return jsonify({"deleted": name})


@app.route("/api/block-locations", methods=["GET"])
def list_block_locations():
    return jsonify({"locations": read_block_locations()})


@app.route("/api/block-locations/<path:name>", methods=["POST", "OPTIONS"])
def save_block_location(name: str):
    if request.method == "OPTIONS":
        return ("", 204)

    validate_name(name, "Location")
    payload = request.get_json(silent=True) or {}
    location = {
        "x": parse_float(payload.get("x"), "x"),
        "y": parse_float(payload.get("y"), "y"),
        "yaw": parse_float(payload.get("yaw"), "yaw"),
    }

    locations = read_block_locations()
    locations[name] = location
    write_block_locations(locations)

    return jsonify({"name": name, "location": location, "locations": locations}), 201


@app.route("/api/block-locations/<path:name>", methods=["DELETE", "OPTIONS"])
def delete_block_location(name: str):
    if request.method == "OPTIONS":
        return ("", 204)

    validate_name(name, "Location")
    locations = read_block_locations()
    if name not in locations:
        abort(404, "Block location not found")

    del locations[name]
    write_block_locations(locations)

    return jsonify({"deleted": name, "locations": locations})


@app.route("/api/block-run-history", methods=["GET"])
def list_block_run_history():
    return jsonify({"history": read_run_history()})


@app.route("/api/block-run-history", methods=["POST", "OPTIONS"])
def save_block_run_history():
    if request.method == "OPTIONS":
        return ("", 204)

    payload = request.get_json(silent=True) or {}
    status = payload.get("status")
    if status not in {"success", "failed", "stopped"}:
        abort(400, "Run history status must be success, failed, or stopped.")

    entry = {
        "program_name": str(payload.get("program_name") or "Untitled Program"),
        "status": status,
        "started_at": str(payload.get("started_at") or ""),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "duration_ms": int(payload.get("duration_ms") or 0),
        "steps_total": int(payload.get("steps_total") or 0),
        "steps_completed": int(payload.get("steps_completed") or 0),
        "error_message": str(payload.get("error_message") or ""),
    }

    history = [entry, *read_run_history()]
    write_run_history(history)

    return jsonify({"entry": entry, "history": history[:100]}), 201


@app.route("/api/block-run-history", methods=["DELETE", "OPTIONS"])
def clear_block_run_history():
    if request.method == "OPTIONS":
        return ("", 204)

    write_run_history([])
    return jsonify({"history": []})


@app.route("/api/voice-plan", methods=["POST", "OPTIONS"])
def create_voice_plan():
    if request.method == "OPTIONS":
        return ("", 204)

    payload = request.get_json(silent=True) or {}
    transcript = str(payload.get("transcript") or "").strip()
    if not transcript:
        abort(400, "Request body must include a non-empty transcript.")

    locations = payload.get("locations")
    if not isinstance(locations, dict):
        locations = {}

    raw_actions = generate_voice_plan_actions(transcript, locations)
    plan = sanitize_plan_actions(raw_actions)

    return jsonify({"plan": plan, "transcript": transcript})


@app.route("/api/devices/serial-ports", methods=["GET"])
def list_serial_ports():
    """Real serial ports currently present on this host (USB/Pi-attached).

    This is genuine detection, not a stand-in for full USB/CAN plug-and-play
    support: it only sees serial devices on the machine running this Flask
    process, via pyserial's udev-backed enumeration. Every Linux box also
    exposes /dev/ttyS0-31 legacy platform serial ports whether or not
    anything is attached to them; pyserial reports hwid "n/a" for those, so
    they're filtered out here to avoid a permanently-populated fake list.
    """
    try:
        from serial.tools import list_ports
    except ImportError:
        return jsonify({"ports": [], "supported": False})

    ports = [
        {
            "device": port.device,
            "description": port.description if port.description != "n/a" else None,
            "manufacturer": port.manufacturer,
            "vid": port.vid,
            "pid": port.pid,
        }
        for port in list_ports.comports()
        if port.hwid and port.hwid != "n/a"
    ]
    return jsonify({"ports": ports, "supported": True})


def _recording_alive():
    return _recording["proc"] is not None and _recording["proc"].poll() is None


def _replay_alive():
    return _replay["proc"] is not None and _replay["proc"].poll() is None


def _finalize_recording(interrupted=False):
    """Common cleanup for a recording that has stopped, one way or another
    — clean Stop request, the subprocess exiting on its own (duration/size
    limit), or a leftover marked interrupted at startup."""
    entries = read_recordings_index()
    for entry in entries:
        if entry.get("id") == _recording["id"]:
            entry["status"] = "interrupted" if interrupted else "complete"
            entry["endedAt"] = datetime.now(timezone.utc).isoformat()
            bag_path = os.path.join(RECORDINGS_DIR, entry["id"])
            entry["sizeBytes"] = dir_size_bytes(bag_path) if os.path.isdir(bag_path) else 0
            break
    write_recordings_index(entries)
    _recording.update({"proc": None, "id": None, "name": None, "started_at": None, "topics": None})


@app.route("/api/recordings", methods=["GET"])
def list_recordings():
    _prune_recordings_if_due()
    # Reap a recording that exited on its own (e.g. hit a size/duration
    # limit) since the last time anyone asked.
    if _recording["id"] and not _recording_alive():
        _finalize_recording()
    return jsonify({"recordings": read_recordings_index()})


@app.route("/api/recordings/status", methods=["GET"])
def recordings_status():
    if _recording["id"] and not _recording_alive():
        _finalize_recording()
    if _replay["id"] and not _replay_alive():
        _replay.update({"proc": None, "id": None, "started_at": None, "paused": False, "rate": 1.0})

    recording = None
    if _recording["id"]:
        recording = {
            "id": _recording["id"],
            "name": _recording["name"],
            "startedAt": _recording["started_at"],
            "topics": _recording["topics"],
        }

    replay = None
    if _replay["id"]:
        replay = {
            "id": _replay["id"],
            "startedAt": _replay["started_at"],
            "paused": _replay["paused"],
            "rate": _replay["rate"],
        }

    return jsonify({"recording": recording, "replay": replay})


@app.route("/api/recordings/start", methods=["POST", "OPTIONS"])
def start_recording():
    if request.method == "OPTIONS":
        return ("", 204)

    if _recording["id"] and _recording_alive():
        abort(409, "A recording is already in progress — stop it before starting another.")

    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name") or "").strip()
    validate_recording_name(name)
    topics = validate_topics(payload.get("topics"))
    description = str(payload.get("description") or "").strip()[:500]

    ensure_recordings_dir()
    recording_id = f"{re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_') or 'recording'}_{int(time.time())}"
    bag_path = os.path.join(RECORDINGS_DIR, recording_id)

    cmd = ["ros2", "bag", "record", "-o", bag_path, "--disable-keyboard-controls"]
    cmd += topics if topics else ["--all-topics"]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        abort(500, "ros2 command not found on this backend — is the ROS environment sourced?")

    started_at = datetime.now(timezone.utc).isoformat()
    _recording.update(
        {"proc": proc, "id": recording_id, "name": name, "started_at": started_at, "topics": topics}
    )

    entries = read_recordings_index()
    entries.append(
        {
            "id": recording_id,
            "name": name,
            "description": description,
            "topics": topics,
            "status": "recording",
            "startedAt": started_at,
            "endedAt": None,
            "sizeBytes": 0,
        }
    )
    write_recordings_index(entries)

    return jsonify({"id": recording_id, "name": name, "startedAt": started_at}), 201


@app.route("/api/recordings/stop", methods=["POST", "OPTIONS"])
def stop_recording():
    if request.method == "OPTIONS":
        return ("", 204)

    if not _recording["id"]:
        abort(409, "No recording is in progress.")

    if _recording_alive():
        _recording["proc"].send_signal(signal.SIGINT)
        try:
            _recording["proc"].wait(timeout=10)
        except subprocess.TimeoutExpired:
            _recording["proc"].kill()

    _finalize_recording()
    return jsonify({"stopped": True})


@app.route("/api/recordings/<recording_id>", methods=["DELETE", "OPTIONS"])
def delete_recording(recording_id):
    if request.method == "OPTIONS":
        return ("", 204)

    if _recording["id"] == recording_id or _replay["id"] == recording_id:
        abort(409, "That recording is currently active — stop it first.")

    entries = read_recordings_index()
    remaining = [entry for entry in entries if entry.get("id") != recording_id]
    if len(remaining) == len(entries):
        abort(404, "Recording not found.")

    bag_path = os.path.join(RECORDINGS_DIR, recording_id)
    if os.path.isdir(bag_path):
        import shutil

        shutil.rmtree(bag_path, ignore_errors=True)

    write_recordings_index(remaining)
    return jsonify({"deleted": recording_id})


@app.route("/api/recordings/<recording_id>/download", methods=["GET"])
def download_recording(recording_id):
    # A rosbag is a directory (metadata.yaml + one or more .db3/.mcap files),
    # so we can't hand back a single file directly — zip the whole bag dir to a
    # temp archive and stream that. The recording must have finished; a bag
    # that's still being written isn't safe to archive.
    entries = read_recordings_index()
    entry = next((e for e in entries if e.get("id") == recording_id), None)
    if not entry:
        abort(404, "Recording not found.")
    if _recording["id"] == recording_id and _recording_alive():
        abort(409, "That recording is still in progress — stop it before downloading.")

    bag_path = os.path.join(RECORDINGS_DIR, recording_id)
    if not os.path.isdir(bag_path):
        abort(404, "Recording files are missing on disk.")

    import shutil
    import tempfile

    tmp_base = os.path.join(tempfile.gettempdir(), f"{recording_id}")
    archive_path = shutil.make_archive(tmp_base, "zip", root_dir=bag_path)

    response = send_file(
        archive_path,
        as_attachment=True,
        download_name=f"{recording_id}.zip",
        mimetype="application/zip",
    )

    # Delete the temp archive once the response has been fully sent — we only
    # needed it to stream; keeping it would leak disk on every download.
    @response.call_on_close
    def _cleanup():
        try:
            os.remove(archive_path)
        except OSError:
            pass

    return response


@app.route("/api/recordings/<recording_id>/replay/start", methods=["POST", "OPTIONS"])
def start_replay(recording_id):
    if request.method == "OPTIONS":
        return ("", 204)

    if _replay["id"] and _replay_alive():
        abort(409, "A replay is already in progress — stop it before starting another.")

    entries = read_recordings_index()
    entry = next((e for e in entries if e.get("id") == recording_id), None)
    if not entry:
        abort(404, "Recording not found.")
    if entry.get("status") not in ("complete", "interrupted"):
        abort(409, "That recording hasn't finished yet.")

    bag_path = os.path.join(RECORDINGS_DIR, recording_id)
    if not os.path.isdir(bag_path):
        abort(404, "Recording files are missing on disk.")

    payload = request.get_json(silent=True) or {}
    rate = parse_float(payload.get("rate", 1.0), "rate")
    if rate <= 0 or rate > 10:
        abort(400, "rate must be between 0 and 10.")

    cmd = ["ros2", "bag", "play", bag_path, "--disable-keyboard-controls", "-r", str(rate)]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        abort(500, "ros2 command not found on this backend — is the ROS environment sourced?")

    started_at = datetime.now(timezone.utc).isoformat()
    _replay.update(
        {"proc": proc, "id": recording_id, "started_at": started_at, "paused": False, "rate": rate}
    )
    return jsonify({"id": recording_id, "startedAt": started_at, "rate": rate}), 201


@app.route("/api/recordings/replay/stop", methods=["POST", "OPTIONS"])
def stop_replay():
    if request.method == "OPTIONS":
        return ("", 204)

    if not _replay["id"]:
        abort(409, "No replay is in progress.")

    if _replay_alive():
        if _replay["paused"]:
            _replay["proc"].send_signal(signal.SIGCONT)
        _replay["proc"].send_signal(signal.SIGINT)
        try:
            _replay["proc"].wait(timeout=10)
        except subprocess.TimeoutExpired:
            _replay["proc"].kill()

    _replay.update({"proc": None, "id": None, "started_at": None, "paused": False, "rate": 1.0})
    return jsonify({"stopped": True})


@app.route("/api/recordings/replay/pause", methods=["POST", "OPTIONS"])
def pause_replay():
    if request.method == "OPTIONS":
        return ("", 204)
    if not _replay["id"] or not _replay_alive():
        abort(409, "No replay is in progress.")
    if not _replay["paused"]:
        _replay["proc"].send_signal(signal.SIGSTOP)
        _replay["paused"] = True
    return jsonify({"paused": True})


@app.route("/api/recordings/replay/resume", methods=["POST", "OPTIONS"])
def resume_replay():
    if request.method == "OPTIONS":
        return ("", 204)
    if not _replay["id"] or not _replay_alive():
        abort(409, "No replay is in progress.")
    if _replay["paused"]:
        _replay["proc"].send_signal(signal.SIGCONT)
        _replay["paused"] = False
    return jsonify({"paused": False})


@app.route("/ros/<path:filename>")
def serve_ros_libs(filename: str):
    # Serve legacy ROS web libs placed under build/ros/
    return send_from_directory(REACT_ROS_DIR, filename)


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_spa(path: str):
    # If someone requests a real file that exists in the build root (e.g., favicon.ico)
    requested = os.path.join(REACT_BUILD_DIR, path)
    if path and os.path.exists(requested) and os.path.isfile(requested):
        return send_from_directory(REACT_BUILD_DIR, path)

    # Otherwise return React index.html (SPA routing)
    return send_from_directory(REACT_BUILD_DIR, "index.html")


AUTH_STORE = install_auth(app, AUTH_MODE, AUTH_DB_PATH, ROBOT_ID)


class _PlatformStoreProxy:
    def __getattr__(self, name):
        if PLATFORM_STORE is None:
            abort(503, "Platform store is not ready.")
        return getattr(PLATFORM_STORE, name)


register_platform_api(app, lambda: PLATFORM_BRIDGE, _PlatformStoreProxy(), ROBOT_ID, AUTH_STORE)


class ParamFlask(Node):
    def __init__(self):
        super().__init__("flask")
        self.declare_parameter("appAddress", "127.0.0.1")
        self.declare_parameter("portApp", 5050)


# Optional for loopback open development; required by AUTH_MODE=local because
# its session cookie is Secure. Set both paths to enable HTTPS.
SSL_CERT_FILE = setting("UI_SSL_CERT", os.path.join(DATA_DIR, "certs", "cert.pem"))
SSL_KEY_FILE = setting("UI_SSL_KEY", os.path.join(DATA_DIR, "certs", "key.pem"))


def main():
    global PLATFORM_BRIDGE, PLATFORM_STORE
    rclpy.init()
    node = ParamFlask()
    executor = None
    try:
        host = node.get_parameter("appAddress").get_parameter_value().string_value
        port = node.get_parameter("portApp").get_parameter_value().integer_value
        validate_bind_host(AUTH_MODE, host)

        ssl_context = None
        if os.path.exists(SSL_CERT_FILE) and os.path.exists(SSL_KEY_FILE):
            ssl_context = (SSL_CERT_FILE, SSL_KEY_FILE)
            node.get_logger().info(f"Serving HTTPS using {SSL_CERT_FILE}")
        validate_auth_transport(AUTH_MODE, ssl_context is not None)

        PLATFORM_STORE = PlatformStore(PLATFORM_DB_PATH)
        PLATFORM_BRIDGE = RobotBridge(PLATFORM_STORE, ROBOT_ID)
        active_platform_config = PLATFORM_STORE.config()
        if active_platform_config:
            PLATFORM_BRIDGE.set_battery_config(active_platform_config)
        executor = MultiThreadedExecutor(num_threads=2)
        executor.add_node(PLATFORM_BRIDGE)
        ros_thread = threading.Thread(target=executor.spin, daemon=True)
        ros_thread.start()

        # threaded=True so one slow/stuck connection (e.g. a browser probing
        # with HTTP against the HTTPS port, or a stalled TLS handshake) cannot
        # block every other client on this single process.
        app.run(host=host, port=port, debug=False, ssl_context=ssl_context, threaded=True)
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if executor is not None:
            executor.shutdown()
        if PLATFORM_BRIDGE is not None:
            PLATFORM_BRIDGE.destroy_node()
            PLATFORM_BRIDGE = None
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
