"""Safe, configurable retention for old plain-text ROS log files."""

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import stat


MAX_LOG_SCAN = 10000


def prune_expired_logs(log_root, retention_days, *, now=None, max_files=MAX_LOG_SCAN):
    """Remove expired regular ``.log`` files below a trusted log root.

    A zero-day retention disables cleanup. Symlinks, non-log files, directories,
    and paths that resolve outside the configured root are always preserved.
    """
    if isinstance(retention_days, bool) or not isinstance(retention_days, int):
        raise ValueError("log retention must be an integer number of days")
    if retention_days < 0:
        raise ValueError("log retention cannot be negative")
    if isinstance(max_files, bool) or not isinstance(max_files, int) or max_files < 1:
        raise ValueError("max_files must be a positive integer")
    if retention_days == 0:
        return []

    root = Path(log_root).expanduser().resolve()
    if not root.is_dir():
        return []
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    cutoff = current_time.astimezone(timezone.utc) - timedelta(days=retention_days)
    removed = []
    scanned = 0

    for current_directory, directories, filenames in os.walk(
        root, topdown=True, followlinks=False
    ):
        current_path = Path(current_directory)
        directories[:] = sorted(
            name
            for name in directories
            if not (current_path / name).is_symlink()
        )
        for filename in sorted(filenames):
            candidate = current_path / filename
            if candidate.suffix != ".log":
                continue
            if scanned >= max_files:
                return removed
            scanned += 1
            try:
                if candidate.is_symlink():
                    continue
                resolved = candidate.resolve(strict=True)
                if not resolved.is_relative_to(root):
                    continue
                metadata = candidate.lstat()
                if not stat.S_ISREG(metadata.st_mode):
                    continue
                modified_at = datetime.fromtimestamp(
                    metadata.st_mtime, timezone.utc
                )
                if modified_at >= cutoff:
                    continue
                candidate.unlink()
                removed.append(str(candidate.relative_to(root)))
            except (OSError, RuntimeError, ValueError):
                continue
    return removed
