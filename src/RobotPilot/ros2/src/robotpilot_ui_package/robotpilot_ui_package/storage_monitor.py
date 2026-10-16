"""Read-only filesystem capacity checks for operator health reporting."""

import os
from pathlib import Path


def _threshold(value, name):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer percentage") from None
    if not 1 <= parsed <= 100:
        raise ValueError(f"{name} must be between 1 and 100")
    return parsed


def storage_report(paths, warning_percent=None, critical_percent=None):
    """Return filesystem usage for labeled paths and threshold status."""
    warning = _threshold(
        warning_percent if warning_percent is not None else os.environ.get(
            "ROBOTPILOT_STORAGE_WARNING_PERCENT", "80"
        ),
        "ROBOTPILOT_STORAGE_WARNING_PERCENT",
    )
    critical = _threshold(
        critical_percent if critical_percent is not None else os.environ.get(
            "ROBOTPILOT_STORAGE_CRITICAL_PERCENT", "90"
        ),
        "ROBOTPILOT_STORAGE_CRITICAL_PERCENT",
    )
    if critical <= warning:
        raise ValueError("storage critical threshold must exceed warning threshold")

    report = []
    for label, value in paths:
        path = Path(value).expanduser()
        probe = path
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        stats = os.statvfs(probe)
        total = stats.f_blocks * stats.f_frsize
        available = stats.f_bavail * stats.f_frsize
        used = max(0, total - available)
        percent = round((used / total) * 100, 1) if total else 0.0
        level = "critical" if percent >= critical else (
            "warning" if percent >= warning else "ok"
        )
        report.append({
            "label": str(label),
            "path": str(path),
            "total_bytes": total,
            "available_bytes": available,
            "used_bytes": used,
            "used_percent": percent,
            "level": level,
            "warning_percent": warning,
            "critical_percent": critical,
        })
    return report
