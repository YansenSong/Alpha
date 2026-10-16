"""Configurable retention for completed Rosbag recordings."""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import tempfile


RECORDING_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
# An interrupted recording may still have an orphaned ros2 bag process writing
# to its directory, so automatic retention only removes known stopped runs.
FINISHED_STATUSES = {"complete", "failed"}


def _recording_time(entry):
    value = entry.get("endedAt") or entry.get("startedAt")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _write_index(index_path, entries):
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{index_path.name}.", suffix=".tmp", dir=index_path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(entries, stream, indent=2, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, index_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def prune_finished_recordings(
    recordings_dir, index_path, retention_days, now=None
):
    """Delete only old, finished bags listed in the recordings index.

    A zero-day retention disables pruning. Invalid entries, active recordings,
    symbolic links, and invalid timestamps are preserved.
    """
    if isinstance(retention_days, bool) or not isinstance(retention_days, int):
        raise ValueError(
            "recording retention must be an integer number of days"
        )
    if retention_days < 0:
        raise ValueError("recording retention cannot be negative")
    if retention_days == 0:
        return []

    root = Path(recordings_dir).expanduser().resolve()
    index = Path(index_path).expanduser()
    if index.is_symlink():
        raise ValueError("recordings index must not be a symbolic link")
    index = index.absolute()
    if index.parent.resolve() != root:
        raise ValueError(
            "recordings index must be inside the recordings directory"
        )
    if not index.is_file():
        return []

    with index.open("r", encoding="utf-8") as stream:
        entries = json.load(stream)
    if not isinstance(entries, list):
        raise ValueError("recordings index must contain a JSON array")

    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    cutoff = current_time.astimezone(timezone.utc) - timedelta(
        days=retention_days
    )
    kept = []
    removed = []

    for entry in entries:
        if (
            not isinstance(entry, dict)
            or entry.get("status") not in FINISHED_STATUSES
        ):
            kept.append(entry)
            continue
        recording_id = entry.get("id")
        ended_at = _recording_time(entry)
        if (
            not isinstance(recording_id, str)
            or not RECORDING_ID_RE.fullmatch(recording_id)
            or ended_at is None
            or ended_at >= cutoff
        ):
            kept.append(entry)
            continue

        bag_path = root / recording_id
        if bag_path.is_symlink():
            kept.append(entry)
            continue
        try:
            bag_path.resolve().relative_to(root)
            if bag_path.exists():
                if not bag_path.is_dir():
                    kept.append(entry)
                    continue
                shutil.rmtree(bag_path)
            removed.append(recording_id)
        except (OSError, ValueError):
            kept.append(entry)

    if removed:
        _write_index(index, kept)
    return removed
