#!/usr/bin/env python3
"""Store route-editor waypoints against the occupancy map currently in use."""

import csv
import hashlib
import json
import math
import os
import signal
import shutil
from pathlib import Path

import rclpy
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from nav_msgs.msg import OccupancyGrid
from nav2_msgs.action import ComputePathToPose
from robotpilot_ui_msgs.msg import ArrayPoseStampedWithCovariance
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Empty, String


class RouteStore(Node):
    """Manage named route files without loading maps or invoking Nav2 execution."""

    ROUTE_REQUEST_TOPIC = "/ackermann/routes/request"
    ROUTE_RESPONSE_TOPIC = "/ackermann/routes/catalog"
    PLAN_REQUEST_TOPIC = "/ackermann/routes/plan_request"
    PLAN_RESPONSE_TOPIC = "/ackermann/routes/plan_response"

    def __init__(self):
        super().__init__("route_store")
        ros_home = Path(os.environ.get("ROS_HOME", "~/.ros")).expanduser()
        self.routes_root = ros_home / "ackermann_robot" / "routes"
        self.routes_root.mkdir(parents=True, exist_ok=True)

        self.map_name = ""
        self.map_group = "Simulation"
        self.map_key = ""
        self.pending_map_identity = None
        self.waypoints = []
        self.identity_file = self.routes_root / "map_identities.json"
        self.map_identities = self._load_map_identities()

        map_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.map_sub = self.create_subscription(
            OccupancyGrid, "/map", self._on_map, map_qos
        )
        self.create_subscription(Empty, self.ROUTE_REQUEST_TOPIC, self._on_request, 10)
        self.create_subscription(String, "/ui_operation", self._on_operation, 10)
        self.create_subscription(String, "/nav_data_resp", self._on_map_catalog, 10)
        self.create_subscription(String, self.PLAN_REQUEST_TOPIC, self._on_plan_request, 10)
        self.plan_response_pub = self.create_publisher(String, self.PLAN_RESPONSE_TOPIC, 10)
        self.plan_client = ActionClient(self, ComputePathToPose, "/compute_path_to_pose")
        self.create_subscription(
            PoseWithCovarianceStamped,
            "/new_way_point",
            self._on_new_waypoint,
            10,
        )
        self.nav_data_pub = self.create_publisher(String, self.ROUTE_RESPONSE_TOPIC, 10)
        self.ui_message_pub = self.create_publisher(String, "/ui_message", 10)
        self.create_timer(5.0, self._publish_catalog)
        self.waypoints_pub = self.create_publisher(
            ArrayPoseStampedWithCovariance, "/WayPoints_topic", 1
        )
        self.get_logger().info(
            f"Route storage: {self.routes_root} (routes follow the active /map)"
        )

    def _load_map_identities(self) -> dict:
        try:
            values = json.loads(self.identity_file.read_text(encoding="utf-8"))
            return values if isinstance(values, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_map_identities(self) -> None:
        temporary = self.identity_file.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self.map_identities, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.identity_file)

    def _set_map_identity(self, group: str, name: str, key: str = "") -> None:
        if not group or not name or group == "Null" or name == "Null":
            return
        target_key = key or self.map_key
        if not target_key:
            return
        self.map_group = group
        self.map_name = name
        self.map_identities[target_key] = {"group": group, "map": name}
        self._save_map_identities()

    def _delete_map_routes(self, group: str, name: str = "") -> None:
        keys = [
            key
            for key, identity in self.map_identities.items()
            if identity.get("group") == group
            and (not name or identity.get("map") == name)
        ]
        if (
            self.map_key
            and (self.map_group, self.map_name) == (group, name or self.map_name)
            and self.map_key not in keys
        ):
            keys.append(self.map_key)

        for key in keys:
            shutil.rmtree(self.routes_root / key, ignore_errors=True)
            self.map_identities.pop(key, None)

        if self.map_key in keys:
            self.waypoints = []
            self.map_group = "Simulation"
            self.map_name = f"Map_{self.map_key}"
            self._publish_waypoints()

        if keys:
            self._save_map_identities()
        self._publish_catalog()

    def _on_map(self, msg: OccupancyGrid) -> None:
        info = msg.info
        signature = hashlib.sha256()
        signature.update(
            json.dumps(
                [
                    info.width,
                    info.height,
                    info.resolution,
                    info.origin.position.x,
                    info.origin.position.y,
                    info.origin.orientation.z,
                    info.origin.orientation.w,
                ],
                separators=(",", ":"),
            ).encode("utf-8")
        )
        signature.update(bytes((value & 0xFF) for value in msg.data))
        next_key = signature.hexdigest()[:12]
        if next_key == self.map_key:
            return

        self.map_key = next_key
        if self.pending_map_identity and self.pending_map_identity["from_key"] != next_key:
            pending = self.pending_map_identity
            self._set_map_identity(pending["group"], pending["map"], next_key)
            self.pending_map_identity = None
        else:
            identity = self.map_identities.get(next_key)
            if identity:
                self.map_group = identity.get("group", "Simulation")
                self.map_name = identity.get("map", f"Map_{next_key}")
            else:
                self.map_group = "Simulation"
                self.map_name = f"Map_{next_key}"
        self._map_dir().mkdir(parents=True, exist_ok=True)
        self.waypoints = []
        self._publish_waypoints()
        self.get_logger().info(f"Active simulation map identified as {self.map_name}")
        self._publish_catalog()

    def _on_map_catalog(self, msg: String) -> None:
        """Join the active map manager identity to the current occupancy map."""
        try:
            active = json.loads(msg.data or "{}").get("active_files", {})
        except (json.JSONDecodeError, AttributeError):
            return
        group = str(active.get("group", ""))
        name = str(active.get("map", ""))
        if not self.map_key or not group or not name or group == "Null" or name == "Null":
            return

        if self.pending_map_identity:
            return

        identity = {"group": group, "map": name}
        if self.map_identities.get(self.map_key) != identity:
            self._set_map_identity(group, name)
            self._publish_catalog()

    def _map_dir(self) -> Path:
        return self.routes_root / self.map_key if self.map_key else self.routes_root / "unavailable"

    def _active_file(self) -> Path:
        return self._map_dir() / ".active_route"

    def _active_route(self) -> str:
        try:
            route = self._active_file().read_text(encoding="utf-8").strip()
        except OSError:
            return "Null"
        return route if route and (self._map_dir() / f"{route}.csv").is_file() else "Null"

    def _route_name(self, value) -> str:
        route = str(value or "").strip()
        if not route or route in {".", ".."} or "/" in route or "\\" in route:
            raise ValueError("Route name must be a non-empty filename")
        if route.endswith(".csv"):
            route = route[:-4]
        if not route or route in {".", ".."}:
            raise ValueError("Route name must be a non-empty filename")
        return route

    def _publish_catalog(self) -> None:
        routes = sorted(
            path.name
            for path in self._map_dir().glob("*.csv")
            if path.is_file()
        ) if self.map_key else []
        response = {
            "structure": (
                [{self.map_group: [{self.map_name: routes}]}] if self.map_key else []
            ),
            "active_files": {
                "group": self.map_group if self.map_key else "Null",
                "map": self.map_name if self.map_key else "Null",
                "map_id": self.map_key if self.map_key else "Null",
                "map_version_id": self.map_key if self.map_key else "Null",
                "route": self._active_route() if self.map_key else "Null",
            },
        }
        self.nav_data_pub.publish(String(data=json.dumps(response)))

    def _publish_waypoints(self) -> None:
        message = ArrayPoseStampedWithCovariance()
        for row in self.waypoints:
            pose = PoseWithCovarianceStamped()
            pose.header.frame_id = "map"
            pose.pose.pose.position.x = row[0]
            pose.pose.pose.position.y = row[1]
            pose.pose.pose.position.z = row[2]
            pose.pose.pose.orientation.x = row[3]
            pose.pose.pose.orientation.y = row[4]
            pose.pose.pose.orientation.z = row[5]
            pose.pose.pose.orientation.w = row[6]
            for index, value in enumerate(row[7:10]):
                pose.pose.covariance[index] = value
            message.poses.append(pose)
        self.waypoints_pub.publish(message)

    def _on_request(self, _msg: Empty) -> None:
        self._publish_catalog()

    def _publish_plan_response(self, request_id: str, **result) -> None:
        self.plan_response_pub.publish(String(data=json.dumps({"id": request_id, **result})))

    @staticmethod
    def _plan_pose(values: dict) -> PoseStamped:
        pose = PoseStamped()
        pose.header.frame_id = "map"
        position = values["position"]
        orientation = values["orientation"]
        pose.pose.position.x = float(position["x"])
        pose.pose.position.y = float(position["y"])
        pose.pose.position.z = float(position.get("z", 0))
        pose.pose.orientation.x = float(orientation.get("x", 0))
        pose.pose.orientation.y = float(orientation.get("y", 0))
        pose.pose.orientation.z = float(orientation.get("z", 0))
        pose.pose.orientation.w = float(orientation.get("w", 1))
        return pose

    def _on_plan_request(self, message: String) -> None:
        request_id = ""
        try:
            request = json.loads(message.data)
            request_id = str(request["id"])
            if not self.plan_client.wait_for_server(timeout_sec=0.2):
                raise RuntimeError("Global planner action is unavailable")
            goal = ComputePathToPose.Goal()
            goal.start = self._plan_pose(request["start"])
            goal.goal = self._plan_pose(request["goal"])
            goal.planner_id = "GridBased"
            goal.use_start = True
            future = self.plan_client.send_goal_async(goal)
            future.add_done_callback(
                lambda done, key=request_id: self._on_plan_goal(done, key)
            )
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            self._publish_plan_response(request_id, error=str(exc))

    def _on_plan_goal(self, future, request_id: str) -> None:
        try:
            handle = future.result()
            if not handle.accepted:
                raise RuntimeError("Global planner rejected the request")
            result_future = handle.get_result_async()
            result_future.add_done_callback(
                lambda done, key=request_id: self._on_plan_result(done, key)
            )
        except Exception as exc:
            self._publish_plan_response(request_id, error=str(exc))

    def _on_plan_result(self, future, request_id: str) -> None:
        try:
            result = future.result().result
            if not result.path.poses:
                raise RuntimeError(
                    getattr(result, "error_msg", "") or
                    f"Global planner returned no path (code {result.error_code})"
                )
            poses = [
                {
                    "pose": {
                        "position": {
                            "x": pose.pose.position.x,
                            "y": pose.pose.position.y,
                            "z": pose.pose.position.z,
                        },
                        "orientation": {
                            "x": pose.pose.orientation.x,
                            "y": pose.pose.orientation.y,
                            "z": pose.pose.orientation.z,
                            "w": pose.pose.orientation.w,
                        },
                    },
                }
                for pose in result.path.poses
            ]
            self._publish_plan_response(request_id, poses=poses)
        except Exception as exc:
            self._publish_plan_response(request_id, error=str(exc))

    def _on_new_waypoint(self, msg: PoseWithCovarianceStamped) -> None:
        if not self.map_key:
            self._publish_message("Waiting for the active simulation map before saving route points.")
            return
        pose = msg.pose.pose
        row = [
            pose.position.x,
            pose.position.y,
            pose.position.z,
            pose.orientation.x,
            pose.orientation.y,
            pose.orientation.z,
            pose.orientation.w,
            msg.pose.covariance[0],
            msg.pose.covariance[1],
            msg.pose.covariance[2],
        ]
        if row not in self.waypoints:
            self.waypoints.append(row)
            self._publish_waypoints()
            count = len(self.waypoints)
            self._publish_message(f"{count} route point{'s' if count != 1 else ''} ready to save.")

    def _read_route(self, route: str) -> None:
        path = self._map_dir() / f"{route}.csv"
        self.waypoints = []
        with path.open("r", encoding="utf-8", newline="") as stream:
            for line_number, values in enumerate(csv.reader(stream), start=1):
                if len(values) < 10:
                    self.get_logger().warning(f"Skipping short route row {line_number}: {path}")
                    continue
                try:
                    self.waypoints.append([float(value.strip()) for value in values[:10]])
                except ValueError:
                    self.get_logger().warning(f"Skipping invalid route row {line_number}: {path}")

    def _publish_message(self, text: str) -> None:
        self.ui_message_pub.publish(String(data=text))

    def _on_operation(self, msg: String) -> None:
        operation, _, payload = msg.data.partition("/")
        try:
            data = json.loads(payload) if payload else {}
            if operation == "clear_route":
                self.waypoints = []
                self._publish_waypoints()
                self._publish_message("Route points cleared.")
            elif operation == "replace_route":
                points = data.get("waypoints")
                if not isinstance(points, list):
                    raise ValueError("waypoints must be a list")
                replacement = []
                for index, point in enumerate(points):
                    if not isinstance(point, list) or len(point) < 10:
                        raise ValueError(f"waypoint {index + 1} must contain 10 values")
                    row = [float(value) for value in point[:10]]
                    if not all(math.isfinite(value) for value in row):
                        raise ValueError(f"waypoint {index + 1} contains a non-finite value")
                    replacement.append(row)
                self.waypoints = replacement
                self._publish_waypoints()
                self._publish_message(f"Updated route points ({len(self.waypoints)}).")
            elif operation == "save_route":
                route = self._route_name(data.get("route"))
                if not self.map_key:
                    raise ValueError("The simulation has not published an active map yet")
                if data.get("group") != self.map_group or data.get("map") != self.map_name:
                    raise ValueError("The active map changed; reload the route page before saving")
                with (self._map_dir() / f"{route}.csv").open(
                    "w", encoding="utf-8", newline=""
                ) as stream:
                    writer = csv.writer(stream)
                    for row in self.waypoints:
                        writer.writerow([*row, 1])
                self._active_file().write_text(route, encoding="utf-8")
                self._publish_message(f"Saved route '{route}' with {len(self.waypoints)} points.")
                self._publish_catalog()
            elif operation in {"edit_route", "change_route"}:
                route = self._route_name(data.get("route"))
                self._read_route(route)
                self._active_file().write_text(route, encoding="utf-8")
                self._publish_waypoints()
                self._publish_catalog()
            elif operation == "rename_route":
                old_route = self._route_name(data.get("route_old"))
                new_route = self._route_name(data.get("route_new"))
                (self._map_dir() / f"{old_route}.csv").rename(
                    self._map_dir() / f"{new_route}.csv"
                )
                if self._active_route() == old_route:
                    self._active_file().write_text(new_route, encoding="utf-8")
                self._publish_catalog()
            elif operation == "delete_route":
                route = self._route_name(data.get("route"))
                was_active = self._active_route() == route
                (self._map_dir() / f"{route}.csv").unlink()
                if was_active:
                    self._active_file().unlink(missing_ok=True)
                    self.waypoints = []
                    self._publish_waypoints()
                self._publish_catalog()
            elif operation == "save_map":
                # The folder handler publishes the map catalog after the file is saved.
                # Do not attach an identity before map_saver_cli has succeeded.
                pass
            elif operation == "change_map":
                group = str(data.get("group", ""))
                name = str(data.get("map", ""))
                if group and name and group != "Null" and name != "Null":
                    self.pending_map_identity = {
                        "group": group,
                        "map": name,
                        "from_key": self.map_key,
                    }
            elif operation == "change_project_map":
                # The folder handler publishes the confirmed maps/<name>
                # selection after map_server accepts it.
                pass
            elif operation == "rename_map":
                group = str(data.get("group", ""))
                old_name = str(data.get("map_old", ""))
                new_name = str(data.get("map_new", ""))
                updated = False
                for key, identity in self.map_identities.items():
                    if identity.get("group") == group and identity.get("map") == old_name:
                        self.map_identities[key] = {"group": group, "map": new_name}
                        updated = True
                if self.map_key and data.get("active"):
                    self._set_map_identity(group, new_name)
                    updated = True
                elif self.map_key and (self.map_group, self.map_name) == (group, old_name):
                    self.map_group = group
                    self.map_name = new_name
                    self.map_identities[self.map_key] = {"group": group, "map": new_name}
                    updated = True
                if updated:
                    self._save_map_identities()
                    self._publish_catalog()
            elif operation == "delete_map":
                group = str(data.get("group", ""))
                name = str(data.get("map", ""))
                if group and name:
                    self._delete_map_routes(group, name)
            elif operation == "delete_group":
                group = str(data.get("group", ""))
                if group:
                    self._delete_map_routes(group)
            else:
                self.get_logger().warning(f"Ignoring unsupported route operation: {operation}")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.get_logger().error(f"Route operation '{operation}' failed: {exc}")
            self._publish_message(f"Route operation failed: {exc}")


def main() -> None:
    rclpy.init()
    node = RouteStore()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
