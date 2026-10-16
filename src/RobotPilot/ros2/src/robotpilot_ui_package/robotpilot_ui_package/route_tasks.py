"""Expose saved route files as map-bound mission definitions for schedules."""

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re


MAP_ID_PATTERN = re.compile(r"[0-9a-f]{12}")


def routes_root():
    ros_home = Path(os.environ.get("ROS_HOME", "~/.ros")).expanduser()
    return ros_home / "ackermann_robot" / "routes"


def route_selection_key(map_id, route_name):
    digest = hashlib.sha256(route_name.encode("utf-8")).hexdigest()[:20]
    return f"route-{map_id}-{digest}"


def route_file(map_id, route_name):
    if not isinstance(map_id, str) or not MAP_ID_PATTERN.fullmatch(map_id):
        raise ValueError("Invalid route map identifier")
    if (
        not isinstance(route_name, str) or not route_name or
        route_name in {".", ".."} or "/" in route_name or "\\" in route_name or
        route_name.endswith(".csv")
    ):
        raise ValueError("Invalid saved route name")
    root = routes_root()
    map_directory = root / map_id
    path = map_directory / f"{route_name}.csv"
    if map_directory.is_symlink() or path.is_symlink() or not path.is_file():
        raise FileNotFoundError("Saved route was not found")
    if path.resolve().parent != map_directory.resolve():
        raise ValueError("Saved route path is unsafe")
    return path


def list_saved_routes():
    root = routes_root()
    if not root.is_dir():
        return []
    try:
        identities = json.loads((root / "map_identities.json").read_text(encoding="utf-8"))
        if not isinstance(identities, dict):
            identities = {}
    except (OSError, ValueError):
        identities = {}
    routes = []
    for map_directory in root.iterdir():
        map_id = map_directory.name
        if not MAP_ID_PATTERN.fullmatch(map_id) or map_directory.is_symlink() or not map_directory.is_dir():
            continue
        identity = identities.get(map_id, {})
        if not isinstance(identity, dict):
            identity = {}
        for path in map_directory.glob("*.csv"):
            name = path.stem
            try:
                route_file(map_id, name)
            except (FileNotFoundError, OSError, ValueError):
                continue
            routes.append({
                "name": name,
                "map_id": map_id,
                "map": str(identity.get("map") or map_id),
                "group": str(identity.get("group") or ""),
                "route_key": route_selection_key(map_id, name),
            })
    return sorted(routes, key=lambda route: (
        route["map"].casefold(), route["name"].casefold(), route["map_id"]
    ))


def route_mission(map_id, route_name):
    path = route_file(map_id, route_name)
    steps = []
    with path.open("r", encoding="utf-8", newline="") as stream:
        for number, values in enumerate(csv.reader(stream), start=1):
            if len(values) < 10:
                raise ValueError(f"Saved route row {number} is incomplete")
            try:
                row = [float(value) for value in values[:10]]
            except ValueError as error:
                raise ValueError(f"Saved route row {number} is invalid") from error
            if not all(math.isfinite(value) for value in row):
                raise ValueError(f"Saved route row {number} contains invalid numbers")
            if abs(row[5] ** 2 + row[6] ** 2 - 1) > 0.1:
                raise ValueError(f"Saved route row {number} has an invalid orientation")
            steps.append({
                "type": "waypoint",
                "pose": {"x": row[0], "y": row[1], "z": row[5], "w": row[6]},
                "waypointName": f"{route_name} {number}",
            })
            if not 0 <= row[8] <= 23 or not 0 <= row[9] <= 59:
                raise ValueError(f"Saved route row {number} has an invalid wait time")
            wait_seconds = row[8] * 3600 + row[9] * 60
            if wait_seconds:
                if not 0 < wait_seconds <= 86400:
                    raise ValueError(f"Saved route row {number} has an invalid wait time")
                steps.append({"type": "wait", "seconds": wait_seconds})
            if len(steps) > 200:
                raise ValueError("Saved route exceeds the 200-step task limit")
    if not steps:
        raise ValueError("Saved route has no waypoints")
    return {
        "id": route_selection_key(map_id, route_name),
        "name": route_name[:120],
        "steps": steps,
        "map_id": map_id,
        "map_version_id": map_id,
    }
