import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch
import rclpy
from nav_msgs.msg import Odometry
from nav_status.msg import NavigationExecution
from std_msgs.msg import String
from mission_manager.node import MissionManager
from mission_manager.store import MissionStore
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "scripts"))
from navigation_test_fixture import navigation_message


class NavigationEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"ROS_LOG_DIR": self.directory.name})
        self.env.start()
        self.path = self.directory.name + "/mission.sqlite3"
        rclpy.init(args=["--ros-args", "-p", f"database_path:={self.path}"])
        self.node = MissionManager()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.env.stop)
        self.addCleanup(rclpy.shutdown)
        self.addCleanup(self.node.destroy_node)
        node = self.node
        for handler, payload in [
            (node.on_software_stop_state, {"active": False, "result": "confirmed", "durable": True, "observed_at": "2026-10-17T00:00:00Z"}),
            (node.on_battery_state, {"available": True, "low_battery": False, "charging": False}),
            (node.on_route_catalog, {"active_files": {"map_id": "m", "map_version_id": "v"}}),
            (node.on_map_bundle, {"schema_version": 1, "ready": True, "map_id": "m", "map_version_id": "v", "bundle_id": "b", "globalmap_pcd_sha256": "hash"}),
        ]:
            handler(String(data=json.dumps(payload)))
        initial = Odometry()
        initial.pose.pose.orientation.w = 1.
        node.on_odom(initial)
        node.on_command(String(data=json.dumps({"command": "save", "mission": {"id": "test", "name": "Test", "map_id": "m", "map_version_id": "v", "steps": [{"type": "waypoint", "pose": {"x": 1., "y": 2., "z": 0., "w": 1.}}]}})))
        node.on_command(String(data=json.dumps({"command": "start", "mission_id": "test"})))
        self.assertEqual(node.run["status"], "RUNNING")

    def activate(self):
        message = navigation_message(self.node)
        message.state = message.MOVING
        self.node.on_nav(message)
        return message

    def test_mismatched_execution_target_and_path_cannot_complete(self):
        message = self.activate()
        message.state = message.ARRIVED
        for field in ("goal", "execution_id", "path_stamp", "result_json"):
            bad = copy.deepcopy(message)
            if field == "goal": bad.goal.header.stamp.nanosec += 1
            elif field == "execution_id": bad.execution_id = "old"
            elif field == "path_stamp": bad.path_stamp.nanosec += 1
            else: bad.result_json = "[]"
            self.node.on_nav(bad)
            self.node.tick()
            self.assertEqual(self.node.run["status"], "RUNNING")
        self.node.on_nav(message)
        self.node.tick()
        self.assertEqual(self.node.run["status"], "SUCCEEDED")
        evidence = self.node.store.run(self.node.run["task_id"])["navigation_evidence"][0]
        self.assertEqual(evidence["source"], "nav_status")
        self.assertEqual(evidence["execution_id"], self.node.navigation_execution_id)
        with_source = json.loads(message.result_json)
        self.assertTrue(all(evidence[k] == v for k, v in with_source.items()))
        reopened = MissionStore(self.path)
        self.assertEqual(reopened.run(self.node.run["task_id"])["navigation_evidence"][0], evidence)
        reopened.close()

    def test_manager_does_not_rejudge_authoritative_geometry_or_add_hold(self):
        message = self.activate()
        message.state = message.ARRIVED
        # Authority already applied the controller's configured tolerance.
        result = json.loads(message.result_json)
        result["observed_pose"]["x"] = 1.4
        message.result_json = json.dumps(result)
        self.node.on_nav(message)
        self.node.tick()
        self.assertEqual(self.node.run["status"], "SUCCEEDED")
        self.assertFalse(hasattr(self.node, "_verified_arrival"))

    def test_cancelled_task_ignores_late_arrival(self):
        message = self.activate()
        self.node.on_command(String(data=json.dumps({"command": "cancel", "task_id": self.node.run["task_id"]})))
        message.state = message.ARRIVED
        self.node.on_nav(message)
        self.node.tick()
        self.assertEqual(self.node.run["status"], "CANCELLED")
        self.assertEqual(self.node.store.run(self.node.run["task_id"])["navigation_evidence"], [])
