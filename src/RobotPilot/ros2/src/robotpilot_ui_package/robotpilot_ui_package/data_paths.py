"""RobotPilot settings with compatibility for existing OpenAMR installs."""

import os
from pathlib import Path


def data_directory():
    configured = setting("DATA_DIR", "").strip()
    if configured:
        return str(Path(configured).expanduser())
    current = Path.home() / ".robotpilot_ui"
    legacy = Path.home() / ".openamr_ui"
    if current.exists() or not legacy.exists():
        return str(current)
    return str(legacy)


def setting(name, default):
    return os.environ.get(
        f"ROBOTPILOT_{name}", os.environ.get(f"OPENAMR_{name}", default)
    )
