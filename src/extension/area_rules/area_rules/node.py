"""ROS bridge for persistent map rules, Nav2 keepout mask, and drive interlock."""

import copy
import json
import math
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

import rclpy
from nav2_msgs.msg import CostmapFilterInfo
from nav_msgs.msg import OccupancyGrid, Odometry
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from std_msgs.msg import String
from tf2_ros import Buffer, TransformException, TransformListener

from .rules import BLOCKING_TYPES, ROBOT_RADIUS, RuleStore, active, covers, map_key, occupancy_map_id, rasterize, yaw_of


LATCHED = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                     durability=DurabilityPolicy.TRANSIENT_LOCAL)


class AreaRules(Node):
    def __init__(self):
        super().__init__("area_rules")
        default_path = Path.home() / ".local/share/ackermann_robot/area_rules.json"
        self.declare_parameter("storage_path", str(default_path))
        self.declare_parameter("robot_frame", "rear_axle_link")
        self.store = RuleStore(self.get_parameter("storage_path").value)
        self.robot_frame = self.get_parameter("robot_frame").value
        self.grid = None
        self.key = None
        self.grid_map_id = None
        self.map_id = None
        self.map_version_id = None
        self.map_bundle = None
        self.bundle_received_at = None
        self.mask_generation = 0
        self.mask_stamp = None
        self.navigation_status = None
        self.navigation_status_at = None
        self.processed_requests = {}
        self.actual_speed = None
        self.odom_received_at = None
        self.declare_parameter("reaction_seconds", 0.3)
        self.declare_parameter("braking_deceleration_mps2", 0.8)
        self.declare_parameter("odom_topic", "/odom_wheel")
        self.rules = []
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.mask_pub = self.create_publisher(OccupancyGrid, "/area_rules/keepout_mask", LATCHED)
        self.info_pub = self.create_publisher(CostmapFilterInfo, "/area_rules/filter_info", LATCHED)
        self.state_pub = self.create_publisher(String, "/area_rules/state", LATCHED)
        self.ack_pub = self.create_publisher(String, "/area_rules/ack", 10)
        self.control_pub = self.create_publisher(String, "/area_rules/control", 10)
        self.create_subscription(OccupancyGrid, "/map", self.on_map, LATCHED)
        self.create_subscription(String, "/ackermann/routes/catalog", self.on_catalog, 10)
        self.create_subscription(String, "/localization/map_bundle", self.on_bundle, LATCHED)
        self.create_subscription(String, "/area_rules/command", self.on_command, 10)
        self.create_subscription(String, "/navigation/rules_status", self.on_navigation_status, 10)
        self.create_subscription(Odometry, self.get_parameter("odom_topic").value, self.on_odom, 10)
        self.create_timer(0.1, self.publish_control)
        self.create_timer(0.25, self.check_expiry)
        self.create_timer(1.0, self.publish_state)
        self.publish_state()
        self.get_logger().info(f"area rules loaded from {self.store.path}")

    def on_map(self, grid):
        key = map_key(grid)
        if key == self.key:
            return
        self.grid = grid
        self.key = key
        self.grid_map_id = occupancy_map_id(grid)
        self.rules = self.store.state(key)["rules"]
        self.publish_mask()
        self.publish_state()
        self.get_logger().info(f"map {key}: {len(self.rules)} active rules")

    def publish_state(self):
        state = self.store.state(self.key) if self.key else {"version": 0, "rules": []}
        self.state_pub.publish(String(data=json.dumps({
            "ready": self.identity_ready(),
            "map_key": self.key,
            "map_id": self.map_id,
            "map_version_id": self.map_version_id,
            "grid_map_id": self.grid_map_id,
            "bundle_id": self.map_bundle.get("bundle_id") if self.map_bundle else None,
            "rules_version": state["version"],
            "mask_generation": self.mask_generation,
            "mask_stamp": self.mask_stamp,
            "navigation_applied": self.navigation_applied(),
            "navigation_hold": self.navigation_status.get("hold") if self.navigation_status else True,
            "navigation_hold_reason": self.navigation_status.get("reason") if self.navigation_status else "WAITING_RULES",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            **state,
        })))

    def identity_ready(self):
        bundle = self.map_bundle
        return bool(
            self.grid is not None and self.key and self.grid_map_id
            and self.map_id == self.grid_map_id and self.map_version_id
            and bundle and self.bundle_received_at is not None
            and time.monotonic() - self.bundle_received_at <= 5.0
            and bundle.get("schema_version") == 1 and bundle.get("ready") is True
            and bundle.get("map_id") == self.map_id
            and bundle.get("map_version_id") == self.map_version_id
            and bundle.get("bundle_id") and bundle.get("globalmap_pcd_sha256")
        )

    def navigation_applied(self):
        status = self.navigation_status
        return bool(self.identity_ready() and status and self.navigation_status_at is not None
                    and time.monotonic() - self.navigation_status_at <= 0.5
                    and status.get("applied") is True
                    and status.get("map_key") == self.key
                    and status.get("map_id") == self.map_id
                    and status.get("map_version_id") == self.map_version_id
                    and status.get("rules_version") == self.store.state(self.key)["version"]
                    and status.get("mask_generation") == self.mask_generation)

    def on_navigation_status(self, message):
        try:
            status = json.loads(message.data)
            self.navigation_status = status if isinstance(status, dict) else None
            self.navigation_status_at = time.monotonic()
        except (ValueError, TypeError):
            self.navigation_status = None
            self.navigation_status_at = None

    def on_odom(self, message):
        speed = message.twist.twist.linear.x
        self.actual_speed = speed if math.isfinite(speed) else None
        self.odom_received_at = time.monotonic()

    def on_bundle(self, message):
        try:
            bundle = json.loads(message.data)
            if not isinstance(bundle, dict):
                raise ValueError("invalid map bundle")
            self.map_bundle = bundle
            self.bundle_received_at = time.monotonic()
        except (ValueError, TypeError, AttributeError):
            self.map_bundle = None
            self.bundle_received_at = None
        self.publish_state()

    def on_catalog(self, message):
        try:
            active = json.loads(message.data or "{}").get("active_files", {})
            map_id = active.get("map_id")
            if not isinstance(map_id, str) or not map_id or map_id == "Null":
                map_id = None
            map_version_id = active.get("map_version_id") or map_id
            if (map_id, map_version_id) == (self.map_id, self.map_version_id):
                return
            self.map_id = map_id
            self.map_version_id = map_version_id
            self.publish_state()
        except (json.JSONDecodeError, AttributeError, TypeError):
            self.map_id = None
            self.map_version_id = None
            self.publish_state()

    def publish_mask(self):
        if self.grid is None:
            return
        mask = OccupancyGrid()
        mask.header.frame_id = self.grid.header.frame_id or "map"
        mask.header.stamp = self.get_clock().now().to_msg()
        mask.info = copy.deepcopy(self.grid.info)
        mask.data = rasterize(mask.info, self.rules)
        self.mask_pub.publish(mask)
        self.mask_stamp = {"sec": mask.header.stamp.sec, "nanosec": mask.header.stamp.nanosec}
        self.navigation_status = None
        info = CostmapFilterInfo()
        info.header = mask.header
        info.type = 0  # Nav2 keepout mask
        info.filter_mask_topic = "/area_rules/keepout_mask"
        info.base = 0.0
        info.multiplier = 1.0
        self.info_pub.publish(info)
        self.mask_generation += 1

    def on_command(self, message):
        request_id = None
        try:
            command = json.loads(message.data)
            request_id = command.get("request_id")
            if request_id is not None:
                if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
                    raise ValueError("request_id must be a nonempty string up to 128 characters")
                previous = self.processed_requests.get(request_id)
                if previous:
                    if previous[0] != message.data:
                        raise ValueError("request_id reused with different command")
                    self.ack_pub.publish(String(data=json.dumps(previous[1])))
                    return
            if not self.identity_ready():
                raise ValueError("2D/3D map bundle is not verified or is stale")
            if command.get("map_key") != self.key:
                raise ValueError("map changed or is not ready; refresh rules")
            if command.get("map_id", self.map_id) != self.map_id or (
                command.get("map_version_id", self.map_version_id) != self.map_version_id
            ):
                raise ValueError("map identity changed; refresh rules")
            self.store.mutate(self.key, command.get("expected_version"),
                              command.get("action"), command.get("rule"))
            self.rules = self.store.state(self.key)["rules"]
            self.publish_mask()
            self.publish_state()
            result = {"request_id": request_id, "ok": True,
                      "stored_version": self.store.state(self.key)["version"],
                      "mask_generation": self.mask_generation,
                      "navigation_applied": False}
        except (ValueError, TypeError, KeyError, AttributeError, OSError, json.JSONDecodeError) as exc:
            result = {"request_id": request_id, "ok": False, "error": str(exc)}
            self.get_logger().warn(f"area rule command rejected: {exc}")
        if request_id and result.get("ok"):
            self.processed_requests[request_id] = (message.data, result)
            if len(self.processed_requests) > 1024:
                self.processed_requests.pop(next(iter(self.processed_requests)))
        self.ack_pub.publish(String(data=json.dumps(result)))

    def check_expiry(self):
        if not self.key:
            return
        expired = self.store.expire(self.key)
        current_rules = self.store.state(self.key)["rules"]
        if expired or current_rules != self.rules:
            self.rules = current_rules
            self.publish_mask()
            self.publish_state()

    def publish_control(self):
        active_rules = [rule for rule in self.rules if active(rule)]
        control = {"ready": False, "stop": True, "speed_limit": None, "map_key": self.key}
        if self.navigation_applied() and self.actual_speed is not None and (
            self.odom_received_at is not None and time.monotonic() - self.odom_received_at <= 0.5
        ):
            try:
                transform = self.tf_buffer.lookup_transform(
                    self.grid.header.frame_id or "map", self.robot_frame, Time())
                stamp = Time.from_msg(transform.header.stamp)
                now = self.get_clock().now()
                if now.nanoseconds > 0 and stamp.nanoseconds > 0 and (
                    abs((now - stamp).nanoseconds) > 1_000_000_000
                ):
                    self.control_pub.publish(String(data=json.dumps(control)))
                    return
                position = transform.transform.translation
                heading = yaw_of(transform.transform.rotation)
                reaction = max(0.0, float(self.get_parameter("reaction_seconds").value))
                decel = max(0.01, float(self.get_parameter("braking_deceleration_mps2").value))
                speed = abs(self.actual_speed)
                directions = (-1, 1)
                horizon = max(1.0, speed * reaction + speed * speed / (2.0 * decel) + 0.5)
                points = [(offset, position.x + direction * offset * math.cos(heading),
                           position.y + direction * offset * math.sin(heading))
                          for direction in directions
                          for offset in (i * 0.1 for i in range(int(horizon / 0.1) + 2))]
                stop = any(covers(rule, x, y, ROBOT_RADIUS)
                           and distance <= speed * reaction + speed * speed / (2.0 * decel) + 0.2
                           for rule in active_rules if rule["type"] in BLOCKING_TYPES
                           for distance, x, y in points)
                limits = []
                for rule in active_rules:
                    if rule["type"] != "speed":
                        continue
                    first = next((distance for distance, x, y in points
                                  if covers(rule, x, y, ROBOT_RADIUS)), None)
                    if first is not None:
                        available = max(0.0, first - speed * reaction)
                        limits.append(math.sqrt(rule["limit_mps"] ** 2 + 2 * decel * available))
                control.update(ready=True, stop=stop,
                               speed_limit=min(limits) if limits else None,
                               actual_speed_mps=self.actual_speed,
                               configured_speed_limit_mps=min(
                                   (rule["limit_mps"] for rule in active_rules if rule["type"] == "speed"
                                    and covers(rule, position.x, position.y, ROBOT_RADIUS)),
                                   default=None))
            except TransformException:
                pass
        self.control_pub.publish(String(data=json.dumps(control)))


def main(args=None):
    rclpy.init(args=args)
    node = AreaRules()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
