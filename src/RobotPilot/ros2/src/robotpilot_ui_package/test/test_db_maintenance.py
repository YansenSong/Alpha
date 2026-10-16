import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from robotpilot_ui_package.db_maintenance import (
    backup_database,
    integrity_check,
    main,
    restore_database,
    snapshot_database,
)


class DatabaseMaintenanceTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.source = self.root / "platform.sqlite3"
        self.backup = self.root / "backups" / "platform.snapshot.sqlite3"
        self._create_database(self.source, "before")

    def tearDown(self):
        self.directory.cleanup()

    @staticmethod
    def _create_database(path, value):
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS sample (value TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO sample(value) VALUES (?)", (value,)
            )
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _values(path):
        connection = sqlite3.connect(path)
        try:
            return [
                row[0]
                for row in connection.execute(
                    "SELECT value FROM sample ORDER BY rowid"
                )
            ]
        finally:
            connection.close()

    def test_online_backup_captures_wal_data_and_checks_integrity(self):
        self._create_database(self.source, "after")
        output = backup_database(self.source, self.backup)

        self.assertEqual(output, self.backup)
        self.assertEqual(self._values(self.backup), ["before", "after"])
        self.assertEqual(integrity_check(self.backup), [])
        self.assertEqual(self.backup.stat().st_mode & 0o777, 0o600)

    def test_restore_validates_backup_and_preserves_pre_restore_database(self):
        backup_database(self.source, self.backup)
        self._create_database(self.source, "after-backup")

        restored, safety_copy = restore_database(self.backup, self.source)

        self.assertEqual(restored, self.source)
        self.assertIsNotNone(safety_copy)
        self.assertEqual(self._values(self.source), ["before"])
        self.assertEqual(self._values(safety_copy), ["before", "after-backup"])
        self.assertEqual(integrity_check(self.source), [])

    def test_invalid_backup_does_not_replace_destination(self):
        self.backup.parent.mkdir()
        self.backup.write_text("not a sqlite database", encoding="utf-8")

        with self.assertRaises(sqlite3.DatabaseError):
            restore_database(self.backup, self.source)

        self.assertEqual(self._values(self.source), ["before"])
        self.assertEqual(list(self.root.glob("*.pre-restore-*")), [])

    def test_restore_cli_requires_explicit_confirmation(self):
        with self.assertRaises(SystemExit) as raised:
            main(["restore", str(self.backup), str(self.source)])

        self.assertEqual(raised.exception.code, 2)

    def test_snapshot_rotation_keeps_newest_owned_files_only(self):
        directory = self.root / "snapshots"
        directory.mkdir()
        older = directory / "platform-store-20261006T120000000000Z.sqlite3"
        newer = directory / "platform-store-20261007T120000000000Z.sqlite3"
        unrelated = directory / "keep-me.sqlite3"
        older.write_text("old", encoding="utf-8")
        newer.write_text("new", encoding="utf-8")
        unrelated.write_text("unrelated", encoding="utf-8")
        timestamp = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)

        output, removed = snapshot_database(
            self.source, directory, keep_last=2, now=timestamp
        )

        self.assertEqual(output.name, "platform-store-20261008T120000000000Z.sqlite3")
        self.assertEqual(removed, [older])
        self.assertFalse(older.exists())
        self.assertTrue(newer.exists())
        self.assertTrue(unrelated.exists())
        self.assertEqual(integrity_check(output), [])
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_snapshot_rejects_invalid_retention_count(self):
        with self.assertRaises(ValueError):
            snapshot_database(self.source, self.root / "snapshots", keep_last=0)


if __name__ == "__main__":
    unittest.main()
