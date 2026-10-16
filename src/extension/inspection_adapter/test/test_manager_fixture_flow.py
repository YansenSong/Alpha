import json
import os
import sys
import tempfile
import time
import unittest

import rclpy
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from nav_status.msg import NavigationStatus
from std_msgs.msg import String

from inspection_adapter.node import InspectionAdapter
from mission_manager.node import MissionManager


class MissionFixtureFlowTest(unittest.TestCase):
    def test_arrival_action_fixture_result_is_durable_and_advances_robot_mission(self):
        with tempfile.TemporaryDirectory() as directory:
            keys = ("ROS_LOG_DIR", "ROS_DOMAIN_ID", "ROBOT_MODE", "INSPECTION_PROVIDER_MODE",
                    "INSPECTION_FIXTURE_SCENARIO", "INSPECTION_ADAPTER_DB", "ROBOTPILOT_MISSION_DB")
            old = {key: os.environ.get(key) for key in keys}
            os.environ.update({"ROS_LOG_DIR": directory, "ROS_DOMAIN_ID": "73", "ROBOT_MODE": "simulation",
                               "INSPECTION_PROVIDER_MODE": "fixture", "INSPECTION_FIXTURE_SCENARIO": "inconclusive",
                               "INSPECTION_ADAPTER_DB": os.path.join(directory, "adapter.sqlite3"),
                               "ROBOTPILOT_MISSION_DB": os.path.join(directory, "missions.sqlite3")})
            rclpy.init()
            mission = MissionManager()
            adapter = InspectionAdapter()
            try:
                capability_deadline = time.monotonic() + 1.0
                while not mission.inspection_provider_snapshot()["online"] and time.monotonic() < capability_deadline:
                    rclpy.spin_once(adapter, timeout_sec=0.02)
                    rclpy.spin_once(mission, timeout_sec=0.02)
                self.assertTrue(mission.inspection_provider_snapshot()["online"])
                mission.on_software_stop_state(String(data=json.dumps({
                    "active": False, "result": "confirmed", "durable": True,
                    "observed_at": "2026-10-10T00:00:00Z"})))
                pose = Odometry()
                pose.pose.pose.orientation.w = 1.0
                pose.header.frame_id = "odom"
                mission.on_odom(pose)
                mission.on_ekf_odom(pose)
                mission.on_battery_state(String(data=json.dumps({
                    "available": True, "low_battery": False, "charging": False,
                    "source": "sim", "simulation": True})))
                mission.on_route_catalog(String(data=json.dumps({"active_files": {
                    "map_id": "map-fixture", "map_version_id": "map-v1"}})))
                mission.on_map_bundle(String(data=json.dumps({
                    "schema_version": 1, "ready": True, "map_id": "map-fixture",
                    "map_version_id": "map-v1", "bundle_id": "bundle-fixture",
                    "globalmap_pcd_sha256": "fixture-checksum"})))
                mission.on_command(String(data=json.dumps({"command": "save", "mission": {
                    "id": "fixture-mission", "name": "Fixture patrol", "map_id": "map-fixture",
                    "map_version_id": "map-v1", "steps": [
                        {"id": "wp-step", "type": "waypoint", "waypoint_id": "wp-fixture",
                         "pose": {"x": 1.0, "y": 1.0, "z": 0.0, "w": 1.0}},
                        {"id": "detect-step", "type": "inspection_action", "action": "detect",
                         "detector_types": ["fire_smoke"], "asset_ids": [], "timeout_ms": 3000},
                    ]}})))
                mission.on_command(String(data=json.dumps({"command": "start", "mission_id": "fixture-mission"})))
                status = NavigationStatus()
                status.stamp.sec = mission.goal_sent_ns // 1_000_000_000
                status.stamp.nanosec = mission.goal_sent_ns % 1_000_000_000
                status.state = NavigationStatus.PLANNING
                status.detail = "new goal received; waiting for global plan"
                mission.on_nav(status)
                status.state = NavigationStatus.ARRIVED
                mission.on_nav(status)
                mission.on_odom(pose)
                mission.on_ekf_odom(pose)
                mission.tick()
                time.sleep(0.51)
                mission.on_odom(pose)
                mission.on_ekf_odom(pose)
                mission.tick()
                deadline = time.monotonic() + 3
                while mission.run["status"] == "RUNNING" and time.monotonic() < deadline:
                    rclpy.spin_once(mission, timeout_sec=0.01)
                    rclpy.spin_once(adapter, timeout_sec=0.01)
                self.assertEqual(mission.run["status"], "SUCCEEDED")
                result_events = [event for event in mission.store.pending_events()
                                 if event["type"] == "inspection.result"]
                self.assertEqual(len(result_events), 1)
                self.assertEqual(result_events[0]["payload"]["outcome"], "INCONCLUSIVE")
                self.assertEqual(result_events[0]["payload"]["source_mode"], "fixture")
                self.assertTrue(result_events[0]["simulation"])
                self.assertTrue(result_events[0]["is_test_data"])
                self.assertEqual(result_events[0]["payload"]["waypoint_id"], "wp-fixture")
                sys.path.insert(0, os.path.abspath("third_party/RobotPilot/ros2/src/robotpilot_ui_package"))
                from robotpilot_ui_package.platform_api import PlatformStore
                platform_store = PlatformStore(os.path.join(directory, "platform.sqlite3"))
                robot_events = mission.store.pending_events()
                self.assertEqual(platform_store.ingest_robot_events("robot-001", robot_events), robot_events[-1]["source_seq"])
                self.assertEqual(platform_store.ingest_robot_events("robot-001", robot_events), robot_events[-1]["source_seq"])
                with platform_store.connect() as db:
                    stored = db.execute("SELECT outcome,source FROM inspection_results WHERE inspection_result_id=?",
                                        (result_events[0]["payload"]["result_id"],)).fetchone()
                self.assertEqual(tuple(stored), ("INCONCLUSIVE", "fixture"))
            finally:
                mission.destroy_node()
                adapter.db.close()
                adapter.destroy_node()
                rclpy.shutdown()
                for key, value in old.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
