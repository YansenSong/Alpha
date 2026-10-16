"""Explicit 2D/3D map pairing and runtime attestation for cold navigation starts."""

import argparse
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import rclpy
import yaml
from nav_msgs.msg import OccupancyGrid
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import PointCloud2
from std_msgs.msg import String


MAP_ID_RE = re.compile(r"^[0-9a-f]{12}$")


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def occupancy_map_id(message):
    """Use the exact route_store map identity algorithm."""
    info = message.info
    values = (info.width, info.height, info.resolution,
              info.origin.position.x, info.origin.position.y,
              info.origin.orientation.z, info.origin.orientation.w)
    if not all(math.isfinite(value) for value in values) or info.width < 1 or info.height < 1:
        raise ValueError("occupancy grid metadata is invalid")
    if len(message.data) != info.width * info.height:
        raise ValueError("occupancy grid size does not match metadata")
    signature = hashlib.sha256()
    signature.update(json.dumps(list(values), separators=(",", ":")).encode("utf-8"))
    signature.update(bytes((value & 0xFF) for value in message.data))
    return signature.hexdigest()[:12]


def bundle_paths(map_yaml, globalmap_pcd):
    yaml_path = Path(map_yaml).expanduser().resolve(strict=True)
    pcd_path = Path(globalmap_pcd).expanduser().resolve(strict=True)
    if not yaml_path.is_file() or not pcd_path.is_file() or pcd_path.stat().st_size == 0:
        raise ValueError("2D YAML or 3D PCD is missing or empty")
    metadata = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    image_name = metadata.get("image") if isinstance(metadata, dict) else None
    if not isinstance(image_name, str) or not image_name or Path(image_name).is_absolute():
        raise ValueError("map YAML image must be a relative path")
    image_path = (yaml_path.parent / image_name).resolve(strict=True)
    if not image_path.is_file() or not image_path.is_relative_to(yaml_path.parent):
        raise ValueError("map image is missing or escapes its directory")
    if not (pcd_path.parent == yaml_path.parent or pcd_path.parent == yaml_path.parent / yaml_path.stem):
        raise ValueError("3D PCD must belong to the 2D map directory")
    return yaml_path, image_path, pcd_path


def make_manifest(map_yaml, globalmap_pcd, map_id):
    if not isinstance(map_id, str) or not MAP_ID_RE.fullmatch(map_id):
        raise ValueError("map_id must be the 12-digit hash reported by route_store")
    yaml_path, image_path, pcd_path = bundle_paths(map_yaml, globalmap_pcd)
    files = {
        "map_yaml": sha256_file(yaml_path),
        "map_image": sha256_file(image_path),
        "globalmap_pcd": sha256_file(pcd_path),
    }
    bundle_id = hashlib.sha256(json.dumps(
        {"map_id": map_id, "files": files}, sort_keys=True,
        separators=(",", ":"),
    ).encode()).hexdigest()
    return {
        "schema_version": 1,
        "map_id": map_id,
        "map_version_id": map_id,
        "bundle_id": bundle_id,
        "files": files,
    }


class MapBundleMonitor(Node):
    def __init__(self):
        super().__init__("map_bundle_monitor")
        self.declare_parameter("map_yaml", "")
        self.declare_parameter("globalmap_pcd", "")
        self.map_yaml = self.get_parameter("map_yaml").value
        self.globalmap_pcd = self.get_parameter("globalmap_pcd").value
        self.map_id = None
        self.global_map_seen = False
        self.manifest = None
        self.files = None
        self.error = "map bundle manifest is unavailable"
        try:
            yaml_path, image_path, pcd_path = bundle_paths(self.map_yaml, self.globalmap_pcd)
            manifest_path = yaml_path.with_suffix(".bundle.json")
            self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected = make_manifest(yaml_path, pcd_path, self.manifest.get("map_id"))
            if self.manifest != expected:
                raise ValueError("map bundle manifest or file checksum does not match")
            self.files = [(path, path.stat().st_size, path.stat().st_mtime_ns)
                          for path in (yaml_path, image_path, pcd_path, manifest_path)]
            self.error = "waiting for 2D and loaded 3D map topics"
        except (OSError, ValueError, TypeError, yaml.YAMLError) as error:
            self.error = str(error)
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                         durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.pub = self.create_publisher(String, "/localization/map_bundle", qos)
        self.create_subscription(OccupancyGrid, "/map", self.on_map, qos)
        self.create_subscription(PointCloud2, "/liorf_localization/localization/global_map",
                                 self.on_global_map, qos)
        self.create_timer(2.0, self.publish_status)
        self.publish_status()

    def on_map(self, message):
        try:
            self.map_id = occupancy_map_id(message)
        except ValueError:
            self.map_id = None
        self.publish_status()

    def on_global_map(self, message):
        if message.header.frame_id == "map" and message.width * message.height >= 1000:
            self.global_map_seen = True
        self.publish_status()

    def publish_status(self):
        reason = self.error
        if self.manifest and self.files:
            if any(not path.is_file() or path.stat().st_size != size or
                   path.stat().st_mtime_ns != mtime for path, size, mtime in self.files):
                reason = "map bundle files changed after verification"
            elif self.map_id != self.manifest["map_id"]:
                reason = "active 2D map does not match the 2D/3D bundle"
            elif not self.global_map_seen or not self.get_publishers_info_by_topic(
                    "/liorf_localization/localization/global_map"):
                reason = "LIORF loaded 3D map is unavailable"
            else:
                reason = ""
        ready = reason == ""
        self.pub.publish(String(data=json.dumps({
            "schema_version": 1, "ready": ready,
            "map_id": self.map_id if ready else None,
            "map_version_id": self.manifest["map_version_id"] if ready else None,
            "bundle_id": self.manifest["bundle_id"] if ready else None,
            "globalmap_pcd_sha256": self.manifest["files"]["globalmap_pcd"] if ready else None,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "source": "map_bundle_monitor", "reason": reason,
        }, separators=(",", ":"))))


def monitor_main():
    rclpy.init()
    node = MapBundleMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def manifest_main():
    parser = argparse.ArgumentParser(description="Bind a saved 2D map to its 3D LIORF PCD")
    parser.add_argument("--map-yaml", required=True)
    parser.add_argument("--globalmap-pcd", required=True)
    parser.add_argument("--map-id", required=True,
                        help="12-character ID from /ackermann/routes/catalog after loading this 2D map")
    args = parser.parse_args()
    manifest = make_manifest(args.map_yaml, args.globalmap_pcd, args.map_id)
    target = Path(args.map_yaml).expanduser().resolve().with_suffix(".bundle.json")
    target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(target)
