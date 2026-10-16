"""Validation, storage, and geometry for map-bound navigation rules."""

import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from datetime import datetime, timezone


ROBOT_RADIUS = 0.84  # Rear axle to the furthest padded footprint corner, metres.
BLOCKING_TYPES = {"keepout", "wall", "closure"}
RULE_TYPES = BLOCKING_TYPES | {"speed"}


def finite(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def expiry(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError
        return dt.astimezone(timezone.utc)
    except (AttributeError, ValueError) as exc:
        raise ValueError("expires_at must be an ISO 8601 time with timezone") from exc


def validate_rule(raw):
    if not isinstance(raw, dict) or raw.get("type") not in RULE_TYPES:
        raise ValueError("unknown rule type")
    rule_id = raw.get("id")
    if not isinstance(rule_id, str) or not 1 <= len(rule_id) <= 80:
        raise ValueError("id must be 1–80 characters")
    name = raw.get("name", "")
    if not isinstance(name, str) or len(name) > 100:
        raise ValueError("name must be at most 100 characters")
    rule = {"id": rule_id, "name": name.strip(), "type": raw["type"]}
    fields = ("x1", "y1", "x2", "y2", "width") if rule["type"] == "wall" else ("cx", "cy", "w", "h")
    for field in fields:
        rule[field] = finite(raw.get(field), field)
    if rule["type"] == "wall":
        if math.hypot(rule["x2"] - rule["x1"], rule["y2"] - rule["y1"]) < 0.01:
            raise ValueError("wall must have length")
        if not 0.01 <= rule["width"] <= 5:
            raise ValueError("wall width must be 0.01–5 m")
    elif not (0.01 <= rule["w"] <= 1000 and 0.01 <= rule["h"] <= 1000):
        raise ValueError("rectangle size must be 0.01–1000 m")
    if rule["type"] == "speed":
        rule["limit_mps"] = finite(raw.get("limit_mps"), "limit_mps")
        if not 0.01 <= rule["limit_mps"] <= 5:
            raise ValueError("speed limit must be 0.01–5 m/s")
    if rule["type"] == "closure":
        if "duration_seconds" in raw:
            duration = finite(raw["duration_seconds"], "duration_seconds")
            if not 1 <= duration <= 86400:
                raise ValueError("closure duration must be 1–86400 seconds")
            from datetime import timedelta
            expires = datetime.now(timezone.utc) + timedelta(seconds=duration)
        else:
            expires = expiry(raw.get("expires_at"))
        if expires <= datetime.now(timezone.utc):
            raise ValueError("closure expiry must be in the future")
        rule["expires_at"] = expires.isoformat()
    return rule


def active(rule, now=None):
    return rule["type"] != "closure" or expiry(rule["expires_at"]) > (now or datetime.now(timezone.utc))


def map_key(grid):
    info = grid.info
    origin = info.origin
    metadata = (grid.header.frame_id, info.width, info.height, info.resolution,
                origin.position.x, origin.position.y, origin.orientation.x,
                origin.orientation.y, origin.orientation.z, origin.orientation.w)
    digest = hashlib.sha256(json.dumps(metadata).encode())
    digest.update(bytes((int(value) & 255 for value in grid.data)))
    return digest.hexdigest()[:24]


def occupancy_map_id(grid):
    """Match route_store/map_bundle_monitor's 2D content identity exactly."""
    info = grid.info
    values = (info.width, info.height, info.resolution,
              info.origin.position.x, info.origin.position.y,
              info.origin.orientation.z, info.origin.orientation.w)
    digest = hashlib.sha256(json.dumps(list(values), separators=(",", ":")).encode())
    digest.update(bytes((int(value) & 255 for value in grid.data)))
    return digest.hexdigest()[:12]


def yaw_of(quat):
    return math.atan2(2 * (quat.w * quat.z + quat.x * quat.y),
                      1 - 2 * (quat.y * quat.y + quat.z * quat.z))


def grid_to_world(info, gx, gy):
    yaw = yaw_of(info.origin.orientation)
    x, y = (gx + 0.5) * info.resolution, (gy + 0.5) * info.resolution
    return (info.origin.position.x + math.cos(yaw) * x - math.sin(yaw) * y,
            info.origin.position.y + math.sin(yaw) * x + math.cos(yaw) * y)


def world_to_grid(info, x, y):
    yaw = yaw_of(info.origin.orientation)
    dx, dy = x - info.origin.position.x, y - info.origin.position.y
    return ((math.cos(yaw) * dx + math.sin(yaw) * dy) / info.resolution,
            (-math.sin(yaw) * dx + math.cos(yaw) * dy) / info.resolution)


def covers(rule, x, y, padding=0):
    if rule["type"] == "wall":
        ax, ay, bx, by = rule["x1"], rule["y1"], rule["x2"], rule["y2"]
        length2 = (bx - ax) ** 2 + (by - ay) ** 2
        t = min(1, max(0, ((x - ax) * (bx - ax) + (y - ay) * (by - ay)) / length2))
        return math.hypot(x - (ax + t * (bx - ax)), y - (ay + t * (by - ay))) <= rule["width"] / 2 + padding
    return (abs(x - rule["cx"]) <= rule["w"] / 2 + padding and
            abs(y - rule["cy"]) <= rule["h"] / 2 + padding)


def bounds(rule, padding):
    if rule["type"] == "wall":
        margin = rule["width"] / 2 + padding
        return (min(rule["x1"], rule["x2"]) - margin, min(rule["y1"], rule["y2"]) - margin,
                max(rule["x1"], rule["x2"]) + margin, max(rule["y1"], rule["y2"]) + margin)
    return (rule["cx"] - rule["w"] / 2 - padding, rule["cy"] - rule["h"] / 2 - padding,
            rule["cx"] + rule["w"] / 2 + padding, rule["cy"] + rule["h"] / 2 + padding)


def rasterize(info, rules, padding=ROBOT_RADIUS):
    mask = [0] * (info.width * info.height)
    for rule in rules:
        if rule["type"] not in BLOCKING_TYPES or not active(rule):
            continue
        left, bottom, right, top = bounds(rule, padding)
        corners = [world_to_grid(info, x, y) for x in (left, right) for y in (bottom, top)]
        x0 = max(0, math.floor(min(p[0] for p in corners)) - 1)
        x1 = min(info.width, math.ceil(max(p[0] for p in corners)) + 1)
        y0 = max(0, math.floor(min(p[1] for p in corners)) - 1)
        y1 = min(info.height, math.ceil(max(p[1] for p in corners)) + 1)
        for gy in range(y0, y1):
            for gx in range(x0, x1):
                x, y = grid_to_world(info, gx, gy)
                if covers(rule, x, y, padding):
                    mask[gy * info.width + gx] = 100
    return mask


class RuleStore:
    def __init__(self, path):
        self.path = Path(path).expanduser()
        try:
            self.maps = json.loads(self.path.read_text(encoding="utf-8")).get("maps", {})
        except FileNotFoundError:
            self.maps = {}
        self._loaded_mtime = self.path.stat().st_mtime_ns if self.path.exists() else None

    def _refresh(self):
        mtime = self.path.stat().st_mtime_ns if self.path.exists() else None
        if mtime != self._loaded_mtime:
            self.maps = json.loads(self.path.read_text(encoding="utf-8")).get("maps", {}) if mtime else {}
            self._loaded_mtime = mtime

    def state(self, key):
        self._refresh()
        saved = self.maps.get(key, {"version": 0, "rules": []})
        return {"version": saved["version"], "rules": [r for r in saved["rules"] if active(r)]}

    def mutate(self, key, version, action, raw):
        if not isinstance(version, int) or isinstance(version, bool):
            raise ValueError("expected_version is required")
        current = self.state(key)
        if current["version"] != version:
            raise ValueError("rules changed; refresh and retry")
        rules = current["rules"]
        if action == "upsert":
            rule = validate_rule(raw)
            rules = [old for old in rules if old["id"] != rule["id"]] + [rule]
        elif action == "delete":
            rule_id = raw.get("id") if isinstance(raw, dict) else None
            if not any(rule["id"] == rule_id for rule in rules):
                raise ValueError("rule not found")
            rules = [rule for rule in rules if rule["id"] != rule_id]
        else:
            raise ValueError("unknown action")
        old = self.maps.get(key)
        self.maps[key] = {"version": version + 1, "rules": rules}
        try:
            self._save()
        except OSError:
            if old is None:
                del self.maps[key]
            else:
                self.maps[key] = old
            raise
        return self.state(key)

    def expire(self, key):
        old = self.maps.get(key)
        if old and len(self.state(key)["rules"]) != len(old["rules"]):
            self.maps[key] = {"version": old["version"] + 1, "rules": self.state(key)["rules"]}
            try:
                self._save()
            except OSError:
                self.maps[key] = old
                raise
            return True
        return False

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".area-rules-", delete=False) as file:
                tmp = file.name
                os.chmod(tmp, 0o600)
                json.dump({"maps": self.maps}, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(tmp, self.path)
            self._loaded_mtime = self.path.stat().st_mtime_ns
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)
