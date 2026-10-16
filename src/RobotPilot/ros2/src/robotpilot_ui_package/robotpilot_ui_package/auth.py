"""Local users, server-side sessions, and API authorization for the UI."""

import hashlib
import os
from .data_paths import data_directory, setting
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager

from flask import abort, g, jsonify, make_response, redirect, request


ROLES = ("Viewer", "Operator", "Engineer", "Admin")
ROLE_LEVEL = {role: level for level, role in enumerate(ROLES)}
SESSION_SECONDS = 12 * 60 * 60
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
COOKIE_NAME = "robotpilot_session"
AUTH_SCHEMA_VERSION = 1
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
ROBOT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def validate_bind_host(mode, host):
    """Prevent unauthenticated open mode from binding a remote interface."""
    if mode == "open" and host not in ("127.0.0.1", "::1", "localhost"):
        raise RuntimeError("AUTH_MODE=open requires a loopback appAddress")


def validate_auth_transport(mode, tls_enabled):
    """Secure session cookies require HTTPS in every protected auth mode."""
    if mode == "local" and not tls_enabled:
        raise RuntimeError("AUTH_MODE=local requires a configured TLS certificate and key")


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def password_hash(password):
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${derived.hex()}"


def verify_password(stored, password):
    try:
        algorithm, n, r, p, salt_hex, expected_hex = stored.split("$")
        if algorithm != "scrypt":
            return False
        derived = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=32,
        )
        return secrets.compare_digest(derived, bytes.fromhex(expected_hex))
    except (ValueError, TypeError):
        return False


def require_role(role):
    """Annotate an API view; install_auth checks it on every request."""
    def decorator(view):
        view.required_role = role
        return view
    return decorator


class AuthStore:
    def __init__(self, path):
        self.path = os.path.expanduser(path)
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
            if current_schema > AUTH_SCHEMA_VERSION:
                raise RuntimeError(
                    "Authentication database schema is newer than this "
                    f"RobotPilot build ({current_schema} > {AUTH_SCHEMA_VERSION})."
                )
            os.chmod(self.path, 0o600)
            db.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    robot_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    csrf_token TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_expires_at ON sessions(expires_at);
                CREATE TABLE IF NOT EXISTS login_attempts (
                    key TEXT PRIMARY KEY,
                    attempts INTEGER NOT NULL,
                    window_start INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ros_audit_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    robot_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    timestamp INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ros_audit_time ON ros_audit_entries(timestamp DESC);
            """)
            db.execute(f"PRAGMA user_version = {AUTH_SCHEMA_VERSION}")
        self.schema_version = AUTH_SCHEMA_VERSION

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

    def create_user(self, username, password, role, robot_id):
        if role not in ROLE_LEVEL:
            raise ValueError("unknown role")
        if not isinstance(username, str) or not USERNAME_RE.fullmatch(username):
            raise ValueError("invalid username")
        if not isinstance(password, str) or not 12 <= len(password) <= 1024:
            raise ValueError("username or password is invalid (minimum 12 characters)")
        if not isinstance(robot_id, str) or not ROBOT_ID_RE.fullmatch(robot_id):
            raise ValueError("invalid robot_id")
        encoded_password = password_hash(password)
        with self.connect() as db:
            db.execute(
                "INSERT INTO users(username, password_hash, role, robot_id) VALUES (?, ?, ?, ?)",
                (username, encoded_password, role, robot_id),
            )

    def login(self, username, password, remote_addr=""):
        with self.connect() as db:
            now = int(time.time())
            attempt_key = digest(username + "|" + remote_addr)
            attempt = db.execute("SELECT * FROM login_attempts WHERE key = ?", (attempt_key,)).fetchone()
            if attempt and now - attempt["window_start"] < 900 and attempt["attempts"] >= 10:
                return None
            user = db.execute("SELECT * FROM users WHERE username = ? AND enabled = 1", (username,)).fetchone()
            if user is None or not verify_password(user["password_hash"], password):
                if not attempt or now - attempt["window_start"] >= 900:
                    db.execute(
                        "INSERT INTO login_attempts(key, attempts, window_start) VALUES (?, 1, ?) "
                        "ON CONFLICT(key) DO UPDATE SET attempts = 1, window_start = excluded.window_start",
                        (attempt_key, now),
                    )
                else:
                    db.execute("UPDATE login_attempts SET attempts = attempts + 1 WHERE key = ?", (attempt_key,))
                return None
            db.execute("DELETE FROM login_attempts WHERE key = ?", (attempt_key,))
            token = secrets.token_urlsafe(32)
            csrf = secrets.token_urlsafe(32)
            expires_at = now + SESSION_SECONDS
            db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            db.execute(
                "INSERT INTO sessions(token_hash, user_id, csrf_token, expires_at) VALUES (?, ?, ?, ?)",
                (digest(token), user["id"], csrf, expires_at),
            )
            return {"token": token, "csrf": csrf, "expires_at": expires_at}

    def session(self, token):
        if not token:
            return None
        with self.connect() as db:
            row = db.execute(
                """SELECT s.token_hash, s.csrf_token, s.expires_at,
                          u.id, u.username, u.role, u.robot_id
                   FROM sessions s JOIN users u ON u.id = s.user_id
                   WHERE s.token_hash = ? AND s.expires_at > ? AND u.enabled = 1""",
                (digest(token), int(time.time())),
            ).fetchone()
            return dict(row) if row else None

    def logout(self, token):
        if token:
            with self.connect() as db:
                db.execute("DELETE FROM sessions WHERE token_hash = ?", (digest(token),))

    def audit_ros(self, identity, operation, resource, outcome):
        with self.connect() as db:
            db.execute(
                "INSERT INTO ros_audit_entries(username, robot_id, operation, resource, outcome, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (identity["username"], identity["robot_id"], str(operation)[:40],
                 str(resource)[:200], str(outcome)[:40], int(time.time())),
            )

    def users(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT username, role, robot_id, enabled FROM users ORDER BY username"
            )]

    def update_user(self, username, role, robot_id, enabled):
        if role not in ROLE_LEVEL or not isinstance(robot_id, str) or not ROBOT_ID_RE.fullmatch(robot_id):
            raise ValueError("invalid role or robot_id")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            target = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            if target is None:
                return False
            if target["role"] == "Admin" and target["enabled"] and (role != "Admin" or not enabled):
                admins = db.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'Admin' AND enabled = 1"
                ).fetchone()[0]
                if admins <= 1:
                    raise ValueError("cannot disable the last administrator")
            db.execute(
                "UPDATE users SET role = ?, robot_id = ?, enabled = ? WHERE username = ?",
                (role, robot_id, int(enabled), username),
            )
            if not enabled:
                db.execute("DELETE FROM sessions WHERE user_id = ?", (target["id"],))
            return True


# Explicit policies for the pre-existing Flask routes. A newly added API route
# has no access until it receives @require_role or is listed here.
LEGACY_POLICIES = {
    "auth_status": "Viewer",
    "list_block_programs": "Viewer",
    "get_block_program": "Viewer",
    "save_block_program": "Operator",
    "delete_block_program": "Operator",
    "list_block_locations": "Viewer",
    "save_block_location": "Engineer",
    "delete_block_location": "Engineer",
    "list_block_run_history": "Viewer",
    "save_block_run_history": "Operator",
    "clear_block_run_history": "Engineer",
    "create_voice_plan": "Operator",
    "list_serial_ports": "Engineer",
    "list_recordings": "Viewer",
    "recordings_status": "Viewer",
    "start_recording": "Engineer",
    "stop_recording": "Engineer",
    "delete_recording": "Engineer",
    "download_recording": "Engineer",
    "start_replay": "Engineer",
    "stop_replay": "Engineer",
    "pause_replay": "Engineer",
    "resume_replay": "Engineer",
}


def install_auth(app, mode, db_path, robot_id):
    if mode not in ("open", "local"):
        raise RuntimeError(f"AUTH_MODE={mode!r} is not implemented")
    store = AuthStore(db_path) if mode == "local" else None

    @app.before_request
    def authorize_request():
        supplied_request_id = request.headers.get("X-Request-ID", "")
        g.request_id = (
            supplied_request_id
            if REQUEST_ID_RE.fullmatch(supplied_request_id)
            else str(uuid.uuid4())
        )
        if request.method == "OPTIONS":
            return None
        if mode == "open":
            g.identity = {"username": "local-open", "role": "Admin", "robot_id": robot_id}
            requested_robot = (request.view_args or {}).get("robot_id")
            if requested_robot and requested_robot != robot_id:
                abort(403, "Robot access denied.")
            return None
        if request.endpoint in ("auth_login", "auth_status") or request.path == "/login":
            return None
        token = request.cookies.get(COOKIE_NAME)
        identity = store.session(token)
        if identity is None:
            if request.method == "GET" and not request.path.startswith("/api/"):
                return redirect("/login")
            abort(401, "Login required.")
        g.identity = identity
        if request.path.startswith("/api/"):
            view = app.view_functions.get(request.endpoint)
            required = getattr(view, "required_role", None) if view else None
            if required is None:
                required = LEGACY_POLICIES.get(request.endpoint)
            if required is None or ROLE_LEVEL[identity["role"]] < ROLE_LEVEL[required]:
                abort(403, "Permission denied.")
            requested_robot = (request.view_args or {}).get("robot_id")
            if requested_robot and requested_robot != identity["robot_id"]:
                abort(403, "Robot access denied.")
            if request.method not in SAFE_METHODS:
                csrf = request.headers.get("X-CSRF-Token", "")
                if not csrf or not secrets.compare_digest(csrf, identity["csrf_token"]):
                    abort(403, "Invalid CSRF token.")
        return None

    @app.post("/api/v1/auth/login")
    def auth_login():
        if mode == "open":
            abort(404)
        payload = request.get_json(silent=True) or {}
        username = payload.get("username", "")
        password = payload.get("password", "")
        if (not isinstance(username, str) or len(username) > 80 or
                not isinstance(password, str) or len(password) > 1024):
            abort(400, "Invalid login payload.")
        login = store.login(username, password, request.remote_addr or "")
        if login is None:
            abort(401, "Invalid credentials.")
        response = make_response(jsonify({"csrf_token": login["csrf"], "expires_at": login["expires_at"]}))
        response.set_cookie(
            COOKIE_NAME, login["token"], max_age=SESSION_SECONDS, httponly=True,
            secure=True, samesite="Strict", path="/",
        )
        return response

    @app.get("/api/v1/auth/me")
    @require_role("Viewer")
    def auth_me():
        return jsonify({key: g.identity[key] for key in ("username", "role", "robot_id")})

    @app.get("/api/v1/auth/csrf")
    @require_role("Viewer")
    def auth_csrf():
        return jsonify({"csrf_token": g.identity["csrf_token"] if mode == "local" else None})

    @app.post("/api/v1/auth/logout")
    @require_role("Viewer")
    def auth_logout():
        store.logout(request.cookies.get(COOKIE_NAME))
        response = make_response(jsonify({"ok": True}))
        response.delete_cookie(COOKIE_NAME, path="/")
        return response

    @app.get("/api/v1/users")
    @require_role("Admin")
    def auth_users():
        if store is None:
            abort(404)
        return jsonify({"users": store.users()})

    @app.post("/api/v1/users")
    @require_role("Admin")
    def auth_create_user():
        if store is None:
            abort(404)
        payload = request.get_json(silent=True) or {}
        try:
            store.create_user(
                payload.get("username"), payload.get("password"),
                payload.get("role"), payload.get("robot_id", robot_id),
            )
        except (ValueError, TypeError) as exc:
            abort(400, str(exc))
        except sqlite3.IntegrityError:
            abort(409, "Username already exists.")
        return jsonify({"created": True}), 201

    @app.patch("/api/v1/users/<username>")
    @require_role("Admin")
    def auth_update_user(username):
        if store is None:
            abort(404)
        payload = request.get_json(silent=True) or {}
        current = next((item for item in store.users() if item["username"] == username), None)
        if current is None:
            abort(404, "User not found.")
        try:
            enabled = payload.get("enabled", bool(current["enabled"]))
            if not isinstance(enabled, bool):
                raise ValueError("enabled must be a boolean")
            store.update_user(
                username, payload.get("role", current["role"]),
                payload.get("robot_id", current["robot_id"]), enabled,
            )
        except ValueError as exc:
            abort(409, str(exc))
        return jsonify({"updated": True})

    return store


def main():
    """Create the first local administrator without exposing a bootstrap API."""
    import argparse
    import getpass

    parser = argparse.ArgumentParser(description="Create a local UI user")
    parser.add_argument("username")
    parser.add_argument("--role", choices=ROLES, default="Admin")
    parser.add_argument("--robot-id", default=setting("ROBOT_ID", "robot-001"))
    parser.add_argument("--db", default=setting("AUTH_DB", os.path.join(data_directory(), "auth.sqlite3")))
    args = parser.parse_args()
    password = getpass.getpass("Password (at least 12 characters): ")
    if password != getpass.getpass("Confirm password: "):
        parser.error("passwords do not match")
    store = AuthStore(args.db)
    store.create_user(args.username, password, args.role, args.robot_id)
    print(f"Created {args.role} user {args.username!r} for {args.robot_id}")


if __name__ == "__main__":
    main()
