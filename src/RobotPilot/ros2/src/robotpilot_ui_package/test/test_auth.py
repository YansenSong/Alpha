import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from flask import Flask, g, jsonify

from robotpilot_ui_package.auth import (
    AuthStore, install_auth, require_role, validate_auth_transport, validate_bind_host,
)


class AuthTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.directory.name) / "auth.sqlite3")
        self.app = Flask(__name__)

        @self.app.get("/api/v1/robots/<robot_id>/status")
        @require_role("Viewer")
        def status(robot_id):
            return jsonify({"robot_id": robot_id, "request_id": g.request_id})

        @self.app.post("/api/v1/robots/<robot_id>/tasks")
        @require_role("Operator")
        def create_task(robot_id):
            return jsonify({"ok": True})

        @self.app.post("/api/v1/robots/<robot_id>/config")
        @require_role("Engineer")
        def update_config(robot_id):
            return jsonify({"ok": True})

        @self.app.post("/api/unguarded")
        def unguarded():
            return jsonify({"ok": True})

        self.store = install_auth(self.app, "local", self.db_path, "robot-001")
        self.store.create_user("viewer", "long-password-123", "Viewer", "robot-001")
        self.store.create_user("operator", "long-password-456", "Operator", "robot-001")
        self.client = self.app.test_client()

    def tearDown(self):
        self.directory.cleanup()

    def login(self, username, password):
        response = self.client.post("/api/v1/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200)
        return response.json["csrf_token"]

    def test_login_scope_role_and_csrf(self):
        self.assertEqual(self.client.get("/api/v1/robots/robot-001/status").status_code, 401)
        self.assertEqual(self.client.post("/api/v1/auth/login", json={"username": "viewer", "password": "wrong"}).status_code, 401)
        csrf = self.login("viewer", "long-password-123")
        self.assertEqual(self.client.get("/api/v1/robots/robot-001/status").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/robots/robot-002/status").status_code, 403)
        self.assertEqual(self.client.post("/api/v1/robots/robot-001/tasks", headers={"X-CSRF-Token": csrf}).status_code, 403)

        csrf = self.login("operator", "long-password-456")
        self.assertEqual(self.client.post("/api/v1/robots/robot-001/tasks").status_code, 403)
        self.assertEqual(self.client.post("/api/v1/robots/robot-001/tasks", headers={"X-CSRF-Token": csrf}).status_code, 200)
        self.assertEqual(self.client.post("/api/v1/robots/robot-001/config", headers={"X-CSRF-Token": csrf}).status_code, 403)
        self.assertEqual(self.client.post("/api/unguarded", headers={"X-CSRF-Token": csrf}).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/auth/csrf").json["csrf_token"], csrf)
        self.assertEqual(self.client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 401)

    def test_open_mode_and_invalid_mode(self):
        app = Flask("open-test")
        install_auth(app, "open", self.db_path, "robot-001")
        self.assertEqual(app.test_client().get("/api/v1/auth/me").json["role"], "Admin")
        with self.assertRaises(RuntimeError):
            install_auth(Flask("external-test"), "external", self.db_path, "robot-001")

    def test_request_id_accepts_safe_header_and_replaces_invalid_value(self):
        app = Flask("request-id-test")

        @app.get("/api/request-id")
        def request_id():
            return jsonify({"request_id": g.request_id})

        install_auth(app, "open", self.db_path, "robot-001")
        client = app.test_client()
        accepted = client.get("/api/request-id", headers={"X-Request-ID": "trace-12345678"})
        self.assertEqual(accepted.json["request_id"], "trace-12345678")
        replaced = client.get("/api/request-id", headers={"X-Request-ID": "trace-请求"})
        self.assertRegex(replaced.json["request_id"], r"^[0-9a-f-]{36}$")

    def test_open_mode_only_binds_loopback(self):
        for host in ("127.0.0.1", "::1", "localhost"):
            validate_bind_host("open", host)
        with self.assertRaisesRegex(RuntimeError, "requires a loopback"):
            validate_bind_host("open", "0.0.0.0")
        validate_bind_host("local", "0.0.0.0")

    def test_local_auth_requires_tls_for_secure_session_cookie(self):
        with self.assertRaisesRegex(RuntimeError, "requires a configured TLS"):
            validate_auth_transport("local", False)
        validate_auth_transport("local", True)
        validate_auth_transport("open", False)

    def test_auth_database_schema_version_is_recorded_and_future_schema_rejected(self):
        with sqlite3.connect(self.db_path) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
        future_path = str(Path(self.directory.name) / "future-auth.sqlite3")
        with sqlite3.connect(future_path) as db:
            db.execute("PRAGMA user_version = 2")
        os.chmod(future_path, 0o644)
        with self.assertRaisesRegex(RuntimeError, "schema is newer"):
            AuthStore(future_path)
        self.assertEqual(Path(future_path).stat().st_mode & 0o777, 0o644)

    def test_auth_schema_migration_rolls_back_after_ddl_error(self):
        broken_path = str(Path(self.directory.name) / "broken-auth.sqlite3")
        with sqlite3.connect(broken_path) as db:
            db.execute("CREATE TABLE ros_audit_entries (id INTEGER PRIMARY KEY)")
        with self.assertRaises(sqlite3.OperationalError):
            AuthStore(broken_path)
        with sqlite3.connect(broken_path) as db:
            tables = {
                row[0]
                for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            self.assertNotIn("users", tables)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
