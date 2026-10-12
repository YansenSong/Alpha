"""Read a saved ROS occupancy map without changing the active robot map."""

import hashlib
import io
import json
import math
import os
import struct
from pathlib import Path

import yaml
from PIL import Image


def saved_map(root, source, group, name):
    if source == "project":
        directory = root.parent / name
        yaml_file = directory / "map.yaml"
    else:
        directory = root / group
        yaml_file = directory / f"{name}.yaml"
    if directory.is_symlink() or yaml_file.is_symlink() or not yaml_file.is_file():
        raise FileNotFoundError("Saved map was not found")
    config = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
    image_name = config.get("image")
    if not isinstance(image_name, str) or not image_name or Path(image_name).is_absolute() or ".." in Path(image_name).parts:
        raise ValueError("Saved map image path is invalid")
    image_path = directory / image_name
    cursor = directory
    for part in Path(image_name).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("Saved map image path contains a link")
    if not image_path.is_file() or not image_path.resolve().is_relative_to(directory.resolve()):
        raise FileNotFoundError("Saved map image was not found")
    resolution = struct.unpack("f", struct.pack("f", float(config["resolution"])))[0]
    origin = [float(value) for value in config["origin"]]
    if not math.isfinite(resolution) or resolution <= 0 or len(origin) != 3 or not all(map(math.isfinite, origin)):
        raise ValueError("Saved map metadata is invalid")
    with Image.open(image_path) as image:
        image = image.convert("L")
        width, height = image.size
        pixels = image.tobytes()
        output = io.BytesIO()
        image.save(output, format="PNG")
    occupied = float(config.get("occupied_thresh", 0.65))
    free = float(config.get("free_thresh", 0.196))
    negate = int(config.get("negate", 0))
    mode = config.get("mode", "trinary")
    if mode != "trinary" or not 0 <= free < occupied <= 1:
        raise ValueError("Only valid trinary saved maps are supported")
    values = []
    for row in range(height - 1, -1, -1):
        for gray in pixels[row * width:(row + 1) * width]:
            occupancy = (gray if negate else 255 - gray) / 255.0
            values.append(100 if occupancy > occupied else 0 if occupancy < free else -1)
    yaw = origin[2]
    metadata = ("map", width, height, resolution, origin[0], origin[1],
                0.0, 0.0, math.sin(yaw / 2), math.cos(yaw / 2))
    digest = hashlib.sha256(json.dumps(metadata).encode())
    grid_bytes = bytes(value & 255 for value in values)
    digest.update(grid_bytes)
    map_id_values = [width, height, resolution, origin[0], origin[1],
                     math.sin(yaw / 2), math.cos(yaw / 2)]
    map_id_digest = hashlib.sha256(json.dumps(map_id_values, separators=(",", ":")).encode())
    map_id_digest.update(grid_bytes)
    return {
        "width": width, "height": height, "resolution": resolution,
        "origin": origin, "map_key": digest.hexdigest()[:24],
        "map_id": map_id_digest.hexdigest()[:12],
        "image_png": output.getvalue(),
    }


def rule_store_path():
    return Path(os.environ.get("AREA_RULES_STORAGE_PATH", "~/.local/share/ackermann_robot/area_rules.json")).expanduser()
