"""Checked SQLite backup and restore helpers.

These helpers operate on the RobotPilot platform store.
"""

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile


SNAPSHOT_NAME_RE = re.compile(
    r"^platform-store-\d{8}T\d{12}Z\.sqlite3$"
)


def _checked_path(value, label):
    path = Path(value).expanduser()
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symbolic link")
    return path.absolute()


def integrity_check(path):
    """Return errors from integrity_check, or an empty list when valid."""
    database_path = _checked_path(path, "database")
    if not database_path.is_file():
        raise FileNotFoundError(database_path)
    connection = sqlite3.connect(
        f"{database_path.as_uri()}?mode=ro", uri=True, timeout=5
    )
    try:
        return [
            row[0]
            for row in connection.execute("PRAGMA integrity_check")
            if row[0] != "ok"
        ]
    finally:
        connection.close()


def _backup_to_temp(source, temp_path):
    source_path = _checked_path(source, "source database")
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    source_db = sqlite3.connect(
        f"{source_path.as_uri()}?mode=ro", uri=True, timeout=5
    )
    target_db = sqlite3.connect(temp_path, timeout=5)
    try:
        source_db.backup(target_db)
        target_db.commit()
    finally:
        target_db.close()
        source_db.close()


def backup_database(source, destination):
    """Create a consistent, integrity-checked SQLite snapshot atomically."""
    source_path = _checked_path(source, "source database")
    destination_path = _checked_path(destination, "backup destination")
    if source_path == destination_path:
        raise ValueError("source and backup destination must differ")
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    destination_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination_path.name}.",
        suffix=".tmp",
        dir=destination_path.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        _backup_to_temp(source_path, temporary_path)
        failures = integrity_check(temporary_path)
        if failures:
            message = "backup integrity check failed: " + "; ".join(failures)
            raise sqlite3.DatabaseError(message)
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, destination_path)
        return destination_path
    finally:
        temporary_path.unlink(missing_ok=True)


def snapshot_database(source, directory, keep_last=30, now=None):
    """Create a timestamped platform snapshot and rotate owned snapshots."""
    if isinstance(keep_last, bool) or not isinstance(keep_last, int) or keep_last < 1:
        raise ValueError("keep_last must be a positive integer")
    output_directory = Path(directory).expanduser()
    if output_directory.is_symlink():
        raise ValueError("snapshot directory must not be a symbolic link")
    output_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    timestamp = timestamp.astimezone(timezone.utc)
    name = f"platform-store-{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}.sqlite3"
    output = backup_database(source, output_directory / name)

    snapshots = sorted(
        (
            path
            for path in output_directory.iterdir()
            if SNAPSHOT_NAME_RE.fullmatch(path.name)
            and not path.is_symlink()
            and path.is_file()
        ),
        key=lambda path: path.name,
        reverse=True,
    )
    removed = []
    for expired in snapshots[keep_last:]:
        expired.unlink()
        removed.append(expired)
    return output, removed


def restore_database(backup, destination):
    """Restore a checked backup, preserving the pre-restore database first."""
    backup_path = _checked_path(backup, "backup database")
    destination_path = _checked_path(destination, "restore destination")
    if backup_path == destination_path:
        raise ValueError("backup and restore destination must differ")
    failures = integrity_check(backup_path)
    if failures:
        message = "backup integrity check failed: " + "; ".join(failures)
        raise sqlite3.DatabaseError(message)

    safety_copy = None
    if destination_path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        safety_copy = destination_path.with_name(
            f"{destination_path.name}.pre-restore-{stamp}"
        )
        backup_database(destination_path, safety_copy)

    destination_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination_path.name}.",
        suffix=".restore",
        dir=destination_path.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        _backup_to_temp(backup_path, temporary_path)
        failures = integrity_check(temporary_path)
        if failures:
            message = (
                "restored database integrity check failed: "
                + "; ".join(failures)
            )
            raise sqlite3.DatabaseError(message)
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, destination_path)
        return destination_path, safety_copy
    finally:
        temporary_path.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Safely back up or restore the RobotPilot SQLite platform store."
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser(
        "backup", help="create a consistent SQLite backup"
    )
    backup.add_argument("source")
    backup.add_argument("destination")
    snapshot = commands.add_parser(
        "snapshot", help="create a timestamped snapshot with count-based rotation"
    )
    snapshot.add_argument("source")
    snapshot.add_argument("directory")
    snapshot.add_argument("--keep-last", type=int, default=30)
    check = commands.add_parser("check", help="run SQLite integrity_check")
    check.add_argument("database")
    restore = commands.add_parser(
        "restore", help="restore after stopping RobotPilot UI backend"
    )
    restore.add_argument("backup")
    restore.add_argument("destination")
    restore.add_argument(
        "--confirm-backend-stopped", action="store_true", required=True
    )
    args = parser.parse_args(argv)

    try:
        if args.command == "backup":
            output = backup_database(args.source, args.destination)
            print(f"Backup created and verified: {output}")
        elif args.command == "snapshot":
            output, removed = snapshot_database(
                args.source, args.directory, args.keep_last
            )
            print(f"Snapshot created and verified: {output}")
            if removed:
                print(f"Removed {len(removed)} expired snapshot(s)")
        elif args.command == "check":
            failures = integrity_check(args.database)
            if failures:
                print(
                    "Integrity check failed: " + "; ".join(failures),
                    file=sys.stderr,
                )
                return 2
            database_path = Path(args.database).expanduser()
            print(f"Integrity check passed: {database_path}")
        else:
            output, safety_copy = restore_database(
                args.backup, args.destination
            )
            print(f"Restore completed and verified: {output}")
            if safety_copy:
                print(f"Pre-restore database preserved at: {safety_copy}")
    except (
        OSError,
        sqlite3.Error,
        ValueError,
    ) as error:
        print(f"Database operation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
