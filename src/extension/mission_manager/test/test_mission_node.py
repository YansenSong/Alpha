import json
import os
import tempfile
import time
import unittest

import rclpy
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from nav_status.msg import NavigationStatus
from std_msgs.msg import String

from mission_manager.node import MissionManager


class PublisherSpy:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class MissionNodeTest(unittest.TestCase):
    @staticmethod
    def software_stop(node, *, active=False, result="confirmed", durable=True):
        node.on_software_stop_state(String(data=json.dumps({
            "active": active,
            "result": result,
            "durable": durable,
            "observed_at": "2026-10-08T00:00:00+00:00",
        })))
        odometry = Odometry()
        odometry.pose.pose.orientation.w = 1.0
        node.on_odom(odometry)
        node.on_battery_state(String(data=json.dumps({
            "available": True, "low_battery": False, "charging": False,
            "source": "sim", "simulation": True,
        })))

    @staticmethod
    def current_map(node, map_id="grid-1", map_version_id="grid-1"):
        node.on_route_catalog(String(data=json.dumps({
            "active_files": {"map_id": map_id, "map_version_id": map_version_id},
        })))
        node.on_map_bundle(String(data=json.dumps({
            "schema_version": 1, "ready": True,
            "map_id": map_id, "map_version_id": map_version_id,
            "bundle_id": "bundle-test", "globalmap_pcd_sha256": "test-pcd",
        })))

    @staticmethod
    def fixture_provider(node):
        capability = {
            "schema_version": 1, "robot_id": node.robot_id, "provider_id": "fixture-provider",
            "source_mode": "fixture", "online": True, "software_version": "fixture-v1",
            "observed_at": "2026-10-10T00:00:00Z",
            "actions": [
                {"kind": "capture", "supported": True, "detectors": []},
                {"kind": "detect", "supported": True, "detectors": ["fire_smoke"]},
                {"kind": "broadcast", "supported": True, "detectors": []},
            ],
        }
        node.on_inspection_capabilities(String(data=json.dumps(capability)))
        node.on_inspection_provider_heartbeat(String(data=json.dumps({
            "schema_version": 1, "robot_id": node.robot_id, "provider_id": "fixture-provider",
            "source_mode": "fixture", "online": True, "observed_at": "2026-10-10T00:00:00Z",
        })))

    def test_ekf_no_events_fault_requires_missing_filtered_odom(self):
        with tempfile.TemporaryDirectory() as directory:
            previous_log_dir = os.environ.get("ROS_LOG_DIR")
            os.environ["ROS_LOG_DIR"] = directory
            rclpy.init(args=["--ros-args", "-p",
                             f"database_path:={os.path.join(directory, 'missions.sqlite3')}"])
            node = MissionManager()
            try:
                name = "ekf_filter_node: odometry/filtered topic status"
                node.store.observe_fault(name, 2, "No events recorded.")
                self.assertTrue(node.store.active_critical_faults())
                odom = Odometry()
                odom.header.frame_id = "odom"
                node.on_ekf_odom(odom)
                status = DiagnosticStatus()
                status.name = name
                status.level = b"\x02"
                status.message = "No events recorded."
                diag = DiagnosticArray()
                diag.status = [status]
                node.on_diagnostics(diag)
                self.assertFalse(node.store.active_critical_faults())
                node.ekf_odom_received_at = time.monotonic() - 3
                node.store.observe_fault(name, 2, "No events recorded.")
                node.on_diagnostics(diag)
                self.assertTrue(node.store.active_critical_faults())
            finally:
                node.destroy_node()
                rclpy.shutdown()
                if previous_log_dir is None:
                    os.environ.pop("ROS_LOG_DIR", None)
                else:
                    os.environ["ROS_LOG_DIR"] = previous_log_dir

    def test_motion_guard_checks_battery_area_and_critical_faults(self):
        with tempfile.TemporaryDirectory() as directory:
            previous_log_dir = os.environ.get("ROS_LOG_DIR")
            os.environ["ROS_LOG_DIR"] = directory
            rclpy.init(args=["--ros-args", "-p",
                             f"database_path:={os.path.join(directory, 'missions.sqlite3')}"])
            node = MissionManager()
            try:
                self.software_stop(node)
                self.assertEqual(node.motion_guard_block_reason(), "")
                node.on_battery_state(String(data=json.dumps({
                    "available": True, "low_battery": True, "charging": False,
                })))
                self.assertIn("battery is low", node.motion_guard_block_reason())
                node.on_battery_state(String(data=json.dumps({
                    "available": True, "low_battery": False, "charging": True,
                })))
                self.assertEqual(node.motion_guard_block_reason(), "battery is charging or charge state is unknown")
                self.software_stop(node)
                node.battery_received_at = time.monotonic() - 6
                self.assertIn("stale", node.motion_guard_block_reason())
                self.software_stop(node)
                node.on_area_control(String(data=json.dumps({"ready": True, "stop": True})))
                self.assertEqual(node.motion_guard_block_reason(), "area control blocks motion")
                node.on_area_control(String(data=json.dumps({"ready": True, "stop": False})))
                node.store.observe_fault("motor", 2, "fault")
                self.assertEqual(node.motion_guard_block_reason(), "critical diagnostics are active")
                node.store.observe_fault("motor", 0, "ok")
                self.assertEqual(node.motion_guard_block_reason(), "")
            finally:
                node.destroy_node()
                rclpy.shutdown()
                if previous_log_dir is None:
                    os.environ.pop("ROS_LOG_DIR", None)
                else:
                    os.environ["ROS_LOG_DIR"] = previous_log_dir

    def test_outbox_ack_cannot_advance_past_published_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            previous_log_dir = os.environ.get("ROS_LOG_DIR")
            os.environ["ROS_LOG_DIR"] = directory
            rclpy.init(args=["--ros-args", "-p",
                             f"database_path:={os.path.join(directory, 'missions.sqlite3')}"])
            node = MissionManager()
            node.outbox_pub = PublisherSpy()
            try:
                node.store.observe_fault("laser", 2, "offline")
                node.on_outbox_ack(String(data=json.dumps({
                    "schema_version": 1, "robot_id": node.robot_id, "through_seq": 999,
                })))
                self.assertEqual(node.store.outbox_status()["pending_count"], 1)
                node.publish_outbox()
                node.on_outbox_ack(String(data=json.dumps({
                    "schema_version": 1, "robot_id": node.robot_id, "through_seq": 1,
                })))
                self.assertEqual(node.store.outbox_status()["pending_count"], 0)
            finally:
                node.destroy_node()
                rclpy.shutdown()
                if previous_log_dir is None:
                    os.environ.pop("ROS_LOG_DIR", None)
                else:
                    os.environ["ROS_LOG_DIR"] = previous_log_dir

    def test_autonomy_guard_requires_fresh_localization(self):
        with tempfile.TemporaryDirectory() as directory:
            previous_log_dir = os.environ.get("ROS_LOG_DIR")
            os.environ["ROS_LOG_DIR"] = directory
            rclpy.init(args=["--ros-args", "-p",
                           f"database_path:={os.path.join(directory, 'missions.sqlite3')}"])
            node = MissionManager()
            try:
                node.on_software_stop_state(String(data=json.dumps({
                    "active": False, "result": "confirmed", "durable": True,
                })))
                node.on_battery_state(String(data=json.dumps({
                    "available": True, "low_battery": False, "charging": False,
                })))
                self.assertEqual(
                    node.motion_guard_block_reason(),
                    "localization pose is unavailable or stale",
                )
                odometry = Odometry()
                odometry.pose.pose.orientation.w = 1.0
                node.on_odom(odometry)
                node.on_battery_state(String(data=json.dumps({
                    "available": True, "low_battery": False, "charging": False,
                })))
                self.assertEqual(node.motion_guard_block_reason(), "")
                node.pose_received_at = time.monotonic() - 4
                self.assertEqual(
                    node.motion_guard_block_reason(),
                    "localization pose is unavailable or stale",
                )
            finally:
                node.destroy_node()
                rclpy.shutdown()
                if previous_log_dir is None:
                    os.environ.pop("ROS_LOG_DIR", None)
                else:
                    os.environ["ROS_LOG_DIR"] = previous_log_dir

    def test_wait_can_resume_after_manager_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "missions.sqlite3")
            previous_log_dir = os.environ.get("ROS_LOG_DIR")
            os.environ["ROS_LOG_DIR"] = directory
            rclpy.init(args=["--ros-args", "-p", f"database_path:={path}"])
            node = MissionManager()
            node.ack_pub = PublisherSpy()
            self.software_stop(node)
            self.current_map(node)
            try:
                def command(value):
                    node.on_command(String(data=json.dumps(value)))

                command({"command": "save", "mission": {
                    "id": "m", "name": "Wait mission",
                    "map_id": "grid-1", "map_version_id": "grid-1",
                    "steps": [{"type": "wait", "seconds": 0.2}]}})
                command({
                    "command": "start", "mission_id": "m",
                    "request_id": "robot-command-123",
                    "origin_request_id": "web-request-123456",
                })
                task_id = node.run["task_id"]
                self.assertEqual(node.run["status"], "RUNNING")
                self.assertEqual(node.run["origin_request_id"], "web-request-123456")
                self.assertEqual(
                    json.loads(node.ack_pub.messages[-1].data)["origin_request_id"],
                    "web-request-123456",
                )
                self.assertEqual(
                    node.store.events(task_id)[0]["request_id"], "web-request-123456"
                )
                original_event_count = len(node.store.events(task_id))
                command({
                    "command": "start", "mission_id": "m",
                    "request_id": "robot-command-123",
                    "origin_request_id": "web-request-123456",
                })
                self.assertEqual(node.run["task_id"], task_id)
                self.assertEqual(len(node.store.events(task_id)), original_event_count)
                self.assertEqual(json.loads(node.ack_pub.messages[-1].data)["task_id"], task_id)
                command({"command": "pause", "task_id": task_id})
                self.assertEqual(node.run["status"], "PAUSED")
                self.assertEqual(node.run["hold_active"], 1)
                self.assertGreater(node.run["remaining_seconds"], 0)
                self.assertEqual(
                    node.store.events(task_id)[-1]["request_id"], "web-request-123456"
                )
                node.destroy_node()

                node = MissionManager()
                self.software_stop(node)
                self.current_map(node)
                self.assertEqual(node.run["status"], "PAUSED")
                self.assertTrue(node.stop_owned)
                command({"command": "resume", "task_id": task_id})
                self.assertEqual(node.run["hold_active"], 0)
                time.sleep(0.25)
                node.tick()
                self.assertEqual(node.run["status"], "SUCCEEDED")
                self.assertTrue(all(event["step_index"] == 0 for event in node.store.events(task_id)))
            finally:
                node.destroy_node()
                rclpy.shutdown()
                if previous_log_dir is None:
                    os.environ.pop("ROS_LOG_DIR", None)
                else:
                    os.environ["ROS_LOG_DIR"] = previous_log_dir

    def test_waypoint_waits_for_current_navigation_arrival(self):
        with tempfile.TemporaryDirectory() as directory:
            previous_log_dir = os.environ.get("ROS_LOG_DIR")
            os.environ["ROS_LOG_DIR"] = directory
            rclpy.init(args=["--ros-args", "-p",
                             f"database_path:={os.path.join(directory, 'missions.sqlite3')}"])
            node = MissionManager()
            self.software_stop(node)
            self.current_map(node)
            try:
                node.on_command(String(data=json.dumps({"command": "save", "mission": {
                    "id": "m", "name": "Go", "map_id": "grid-1", "map_version_id": "grid-1",
                    "steps": [{"type": "waypoint",
                    "pose": {"x": 1, "y": 2, "z": 0, "w": 1}}]}})))
                node.on_command(String(data=json.dumps({"command": "start", "mission_id": "m"})))
                self.assertEqual(node.run["status"], "RUNNING")
                status = NavigationStatus()
                status.stamp.sec = node.goal_sent_ns // 1000000000
                status.stamp.nanosec = node.goal_sent_ns % 1000000000
                status.state = NavigationStatus.ARRIVED
                node.on_nav(status)
                self.assertEqual(node.run["status"], "RUNNING")
                status.state = NavigationStatus.PLANNING
                status.detail = "new goal received; waiting for global plan"
                node.on_nav(status)
                status.state = NavigationStatus.ARRIVED
                node.on_nav(status)
                self.assertEqual(node.run["status"], "RUNNING")
                stable = Odometry()
                stable.header.frame_id = "odom"
                stable.pose.pose.orientation.w = 1.0
                node.on_odom(stable)
                node.on_ekf_odom(stable)
                node.tick()
                time.sleep(0.51)
                node.on_odom(stable)
                node.on_ekf_odom(stable)
                node.tick()
                self.assertEqual(node.run["status"], "SUCCEEDED")
                node.on_command(String(data=json.dumps({"command": "start", "mission_id": "m"})))
                external = PoseStamped()
                external.pose.position.x = 99.0
                external.pose.orientation.w = 1.0
                node.on_goal(external)
                self.assertEqual(node.run["status"], "FAILED")
                self.assertEqual(node.run["hold_active"], 1)
                node.on_command(String(data=json.dumps({"command": "release_hold",
                                                       "task_id": node.run["task_id"]})))
                self.assertEqual(node.run["hold_active"], 0)
                node.on_command(String(data=json.dumps({"command": "save", "mission": {
                    "id": "home", "name": "Home", "map_id": "grid-1", "map_version_id": "grid-1",
                    "steps": [{"type": "home"}]}})))
                node.on_command(String(data=json.dumps({"command": "start", "mission_id": "home"})))
                self.assertEqual(node.run["status"], "RUNNING")
            finally:
                node.destroy_node()
                rclpy.shutdown()
                if previous_log_dir is None:
                    os.environ.pop("ROS_LOG_DIR", None)
                else:
                    os.environ["ROS_LOG_DIR"] = previous_log_dir

    def test_inspection_action_is_requested_after_stable_arrival_and_result_advances_task(self):
        with tempfile.TemporaryDirectory() as directory:
            previous_log_dir = os.environ.get("ROS_LOG_DIR")
            previous_robot_mode = os.environ.get("ROBOT_MODE")
            os.environ["ROS_LOG_DIR"] = directory
            os.environ["ROBOT_MODE"] = "simulation"
            rclpy.init(args=["--ros-args", "-p", f"database_path:={os.path.join(directory, 'missions.sqlite3')}"])
            node = MissionManager()
            node.action_request_pub = PublisherSpy()
            self.software_stop(node)
            self.current_map(node)
            self.fixture_provider(node)
            stable = Odometry()
            stable.header.frame_id = "odom"
            stable.pose.pose.orientation.w = 1.0
            node.on_ekf_odom(stable)
            try:
                node.on_command(String(data=json.dumps({"command": "save", "mission": {
                    "id": "inspect", "name": "Inspect", "map_id": "grid-1", "map_version_id": "grid-1",
                    "steps": [
                        {"id": "nav-1", "type": "waypoint", "waypoint_id": "wp-1",
                         "pose": {"x": 1, "y": 2, "z": 0, "w": 1}},
                        {"id": "detect-1", "type": "inspection_action", "action": "detect",
                         "detector_types": ["fire_smoke"], "asset_ids": ["asset-1"], "timeout_ms": 5000},
                    ]}})))
                node.on_command(String(data=json.dumps({"command": "start", "mission_id": "inspect"})))
                self.assertEqual(node.run["status"], "RUNNING")
                self.assertEqual(node.action_request_pub.messages, [])
                nav = NavigationStatus()
                nav.stamp.sec = node.goal_sent_ns // 1000000000
                nav.stamp.nanosec = node.goal_sent_ns % 1000000000
                nav.state = NavigationStatus.PLANNING
                nav.detail = "new goal received; waiting for global plan"
                node.on_nav(nav)
                nav.state = NavigationStatus.ARRIVED
                node.on_nav(nav)
                node.on_odom(stable)
                node.on_ekf_odom(stable)
                node.tick()
                self.assertEqual(node.action_request_pub.messages, [])
                time.sleep(0.51)
                node.on_odom(stable)
                node.on_ekf_odom(stable)
                node.tick()
                self.assertEqual(len(node.action_request_pub.messages), 1)
                request = json.loads(node.action_request_pub.messages[0].data)
                self.assertEqual(request["waypoint_id"], "wp-1")
                self.assertEqual(request["detector_types"], ["fire_smoke"])
                node.on_inspection_result(String(data=json.dumps({
                    "schema_version": 1, "result_id": "result-fixture-1", "robot_id": "robot-001",
                    "mission_id": "inspect", "task_id": node.run["task_id"],
                    "step_id": "detect-1", "attempt": 1,
                    "action_run_id": request["action_run_id"], "status": "SUCCEEDED",
                    "outcome": "INCONCLUSIVE", "source_mode": "fixture",
                    "observed_at": "2026-10-10T00:00:00Z", "map_id": "grid-1",
                    "map_version_id": "grid-1", "confidence": None,
                })))
                self.assertEqual(node.run["status"], "SUCCEEDED")
                outbox = node.store.pending_events()
                self.assertIn("inspection.result", [item["type"] for item in outbox])
            finally:
                node.destroy_node()
                rclpy.shutdown()
                if previous_log_dir is None:
                    os.environ.pop("ROS_LOG_DIR", None)
                else:
                    os.environ["ROS_LOG_DIR"] = previous_log_dir
                if previous_robot_mode is None:
                    os.environ.pop("ROBOT_MODE", None)
                else:
                    os.environ["ROBOT_MODE"] = previous_robot_mode

    def test_business_steps_keep_arrival_context_across_waits_and_actions(self):
        previous_mode = os.environ.get("ROBOT_MODE")
        os.environ["ROBOT_MODE"] = "simulation"
        try:
            for kinds in (("wait", "detect"), ("capture", "detect"),
                          ("wait", "detect", "wait", "capture")):
                with self.subTest(kinds=kinds), tempfile.TemporaryDirectory() as directory:
                    rclpy.init(args=["--ros-args", "-p",
                                     f"database_path:={os.path.join(directory, 'missions.sqlite3')}"])
                    node = MissionManager()
                    node.action_request_pub = PublisherSpy()
                    try:
                        self.software_stop(node)
                        self.current_map(node)
                        self.fixture_provider(node)
                        stable = Odometry()
                        stable.header.frame_id = "odom"
                        stable.pose.pose.orientation.w = 1.0
                        node.on_ekf_odom(stable)
                        steps = [{"id": "nav", "type": "waypoint", "waypoint_id": "wp-1",
                                  "pose": {"x": 1, "y": 2, "z": 0, "w": 1}}]
                        for index, kind in enumerate(kinds):
                            step = {"id": f"business-{index}", "waypoint_id": "wp-1"}
                            if kind == "wait":
                                step.update(type="wait", seconds=0.1)
                            else:
                                step.update(type="inspection_action", action=kind,
                                            timeout_ms=5000,
                                            detector_types=["fire_smoke"] if kind == "detect" else [])
                            steps.append(step)
                        node.on_command(String(data=json.dumps({"command": "save", "mission": {
                            "id": "sequence", "name": "Sequence", "map_id": "grid-1",
                            "map_version_id": "grid-1", "steps": steps}})))
                        node.on_command(String(data=json.dumps({"command": "start", "mission_id": "sequence"})))
                        nav = NavigationStatus()
                        nav.stamp.sec = node.goal_sent_ns // 1000000000
                        nav.stamp.nanosec = node.goal_sent_ns % 1000000000
                        nav.state = NavigationStatus.PLANNING
                        nav.detail = "new goal received; waiting for global plan"
                        node.on_nav(nav)
                        nav.state = NavigationStatus.ARRIVED
                        node.on_nav(nav)
                        node.on_odom(stable)
                        node.on_ekf_odom(stable)
                        node.tick()
                        time.sleep(0.51)
                        node.on_odom(stable)
                        node.on_ekf_odom(stable)
                        node.tick()
                        self.assertEqual(node.run["arrival_step_index"], 0)
                        for kind in kinds:
                            node.on_odom(stable)
                            node.on_ekf_odom(stable)
                            if kind == "wait":
                                self.assertEqual(node._kind(), "wait")
                                node.deadline = time.monotonic() - 0.01
                                node.tick()
                                continue
                            request = json.loads(node.action_request_pub.messages[-1].data)
                            self.assertEqual(request["waypoint_id"], "wp-1")
                            self.assertEqual(request["kind"], kind)
                            node.on_inspection_result(String(data=json.dumps({
                                "schema_version": 1, "result_id": f"result-{request['step_id']}",
                                "robot_id": node.robot_id, "mission_id": "sequence",
                                "task_id": node.run["task_id"], "step_id": request["step_id"],
                                "attempt": 1, "action_run_id": request["action_run_id"],
                                "status": "SUCCEEDED", "outcome": "INCONCLUSIVE",
                                "source_mode": "fixture", "observed_at": "2026-10-10T00:00:00Z",
                                "map_id": "grid-1", "map_version_id": "grid-1",
                                "waypoint_id": "wp-1", "confidence": None,
                            })))
                        self.assertEqual(node.run["status"], "SUCCEEDED")
                        if kinds == ("wait", "detect"):
                            node.on_command(String(data=json.dumps({"command": "save", "mission": {
                                "id": "orphan", "name": "Orphan action", "map_id": "grid-1",
                                "map_version_id": "grid-1", "steps": [
                                    {"id": "orphan-wait", "type": "wait", "seconds": 0.1},
                                    {"id": "orphan-detect", "type": "inspection_action",
                                     "action": "detect", "detector_types": ["fire_smoke"]},
                                ]}})))
                            node.on_command(String(data=json.dumps({"command": "start", "mission_id": "orphan"})))
                            node.deadline = time.monotonic() - 0.01
                            node.tick()
                            self.assertEqual(node.run["status"], "FAILED")
                            self.assertIn("waypoint arrival", node.run["reason"])
                    finally:
                        node.destroy_node()
                        rclpy.shutdown()
        finally:
            if previous_mode is None:
                os.environ.pop("ROBOT_MODE", None)
            else:
                os.environ["ROBOT_MODE"] = previous_mode

    def test_paused_inspection_result_is_reconciled_and_request_is_immutable(self):
        previous_mode = os.environ.get("ROBOT_MODE")
        os.environ["ROBOT_MODE"] = "simulation"
        try:
            for result_while_paused, restart_before_resume in (
                    (True, False), (False, False), (True, True), (False, True)):
                with self.subTest(result_while_paused=result_while_paused,
                                  restart_before_resume=restart_before_resume), tempfile.TemporaryDirectory() as directory:
                    rclpy.init(args=["--ros-args", "-p",
                                     f"database_path:={os.path.join(directory, 'missions.sqlite3')}"])
                    node = MissionManager()
                    node.action_request_pub = PublisherSpy()
                    node.action_control_pub = PublisherSpy()
                    try:
                        self.software_stop(node)
                        self.current_map(node)
                        self.fixture_provider(node)
                        odom = Odometry()
                        odom.header.frame_id = "odom"
                        odom.pose.pose.orientation.w = 1.0
                        node.on_odom(odom)
                        node.on_ekf_odom(odom)
                        mission = node.store.save_mission({
                            "id": "pause-inspect", "name": "Pause inspect", "map_id": "grid-1",
                            "map_version_id": "grid-1", "steps": [
                                {"id": "nav", "type": "waypoint", "waypoint_id": "wp-1",
                                 "pose": {"x": 1, "y": 2, "z": 0, "w": 1}},
                                {"id": "detect", "type": "inspection_action", "action": "detect",
                                 "waypoint_id": "wp-1", "detector_types": ["fire_smoke"],
                                 "asset_ids": [], "parameters": {}, "timeout_ms": 5000},
                            ],
                        })
                        node.run = node.store.new_run("pause-task", mission)
                        node.run = node.store.update_run("pause-task", step_index=1,
                                                         arrival_step_index=0)
                        node._begin_step()
                        first_request = json.loads(node.action_request_pub.messages[-1].data)
                        result = {"schema_version": 1, "result_id": "pause-result",
                                  "robot_id": node.robot_id, "mission_id": "pause-inspect",
                                  "task_id": "pause-task", "step_id": "detect", "attempt": 1,
                                  "action_run_id": first_request["action_run_id"],
                                  "status": "SUCCEEDED", "outcome": "INCONCLUSIVE",
                                  "source_mode": "fixture", "observed_at": "2026-10-10T00:00:00Z",
                                  "map_id": "grid-1", "map_version_id": "grid-1",
                                  "waypoint_id": "wp-1", "confidence": None}
                        node._control("pause", {"task_id": "pause-task"})
                        self.assertEqual(node.run["status"], "PAUSED")
                        if result_while_paused:
                            node.on_inspection_result(String(data=json.dumps(result)))
                            self.assertEqual(node.run["status"], "PAUSED")
                        if restart_before_resume:
                            node.destroy_node()
                            node = MissionManager()
                            node.action_request_pub = PublisherSpy()
                            node.action_control_pub = PublisherSpy()
                            self.software_stop(node)
                            self.current_map(node)
                            self.fixture_provider(node)
                        node.on_odom(odom)
                        node.on_ekf_odom(odom)
                        node._control("resume", {"task_id": "pause-task"})
                        if not result_while_paused:
                            self.assertEqual(json.loads(node.action_request_pub.messages[-1].data), first_request)
                            node.on_inspection_result(String(data=json.dumps(result)))
                        self.assertEqual(node.run["status"], "SUCCEEDED")
                        node.on_inspection_result(String(data=json.dumps(result)))
                        self.assertEqual(len([event for event in node.store.pending_events()
                                              if event["type"] == "inspection.result"]), 1)
                    finally:
                        node.destroy_node()
                        rclpy.shutdown()
        finally:
            if previous_mode is None:
                os.environ.pop("ROBOT_MODE", None)
            else:
                os.environ["ROBOT_MODE"] = previous_mode

    def test_cancelled_result_stays_late_and_retry_changes_action_identity(self):
        previous_mode = os.environ.get("ROBOT_MODE")
        os.environ["ROBOT_MODE"] = "simulation"
        with tempfile.TemporaryDirectory() as directory:
            rclpy.init(args=["--ros-args", "-p",
                             f"database_path:={os.path.join(directory, 'missions.sqlite3')}"])
            node = MissionManager()
            node.action_request_pub = PublisherSpy()
            try:
                self.software_stop(node)
                self.current_map(node)
                self.fixture_provider(node)
                odom = Odometry()
                odom.header.frame_id = "odom"
                odom.pose.pose.orientation.w = 1.0
                node.on_odom(odom)
                node.on_ekf_odom(odom)
                mission = node.store.save_mission({
                    "id": "action", "name": "Action", "map_id": "grid-1",
                    "map_version_id": "grid-1", "steps": [
                        {"id": "nav", "type": "waypoint", "waypoint_id": "wp-1",
                         "pose": {"x": 1, "y": 2, "z": 0, "w": 1}},
                        {"id": "detect", "type": "inspection_action", "action": "detect",
                         "waypoint_id": "wp-1", "detector_types": ["fire_smoke"],
                         "asset_ids": [], "parameters": {}, "timeout_ms": 5000},
                    ],
                })
                node.run = node.store.new_run("cancel-task", mission)
                node.run = node.store.update_run("cancel-task", step_index=1,
                                                 arrival_step_index=0)
                node._begin_step()
                cancelled_request = json.loads(node.action_request_pub.messages[-1].data)
                node._control("cancel", {"task_id": "cancel-task"})
                result = {"schema_version": 1, "result_id": "cancel-result",
                          "robot_id": node.robot_id, "mission_id": "action",
                          "task_id": "cancel-task", "step_id": "detect", "attempt": 1,
                          "action_run_id": cancelled_request["action_run_id"],
                          "status": "SUCCEEDED", "outcome": "INCONCLUSIVE",
                          "source_mode": "fixture", "observed_at": "2026-10-10T00:00:00Z",
                          "map_id": "grid-1", "map_version_id": "grid-1", "confidence": None}
                node.on_inspection_result(String(data=json.dumps(result)))
                self.assertEqual(node.run["status"], "CANCELLED")
                self.assertEqual(len([item for item in node.store.pending_events()
                                      if item["type"] == "inspection.result.late"]), 1)
                node.run = node.store.new_run("retry-task", mission)
                node.run = node.store.update_run("retry-task", step_index=1,
                                                 arrival_step_index=0)
                node._begin_step()
                first_request = json.loads(node.action_request_pub.messages[-1].data)
                node._fail("provider unavailable")
                node.on_odom(odom)
                node.on_ekf_odom(odom)
                node._control("retry", {"task_id": "retry-task"})
                retry_request = json.loads(node.action_request_pub.messages[-1].data)
                self.assertEqual(retry_request["attempt"], 2)
                self.assertNotEqual(first_request["action_run_id"], retry_request["action_run_id"])
            finally:
                node.destroy_node()
                rclpy.shutdown()
                if previous_mode is None:
                    os.environ.pop("ROBOT_MODE", None)
                else:
                    os.environ["ROBOT_MODE"] = previous_mode

    def test_inspection_mission_requires_fresh_matching_provider_capability(self):
        with tempfile.TemporaryDirectory() as directory:
            previous_log_dir = os.environ.get("ROS_LOG_DIR")
            previous_robot_mode = os.environ.get("ROBOT_MODE")
            os.environ["ROS_LOG_DIR"] = directory
            os.environ["ROBOT_MODE"] = "simulation"
            rclpy.init(args=["--ros-args", "-p", f"database_path:={os.path.join(directory, 'missions.sqlite3')}"])
            node = MissionManager()
            try:
                mission = {"steps": [{"type": "inspection_action", "action": "detect",
                                      "detector_types": ["fire_smoke"]}]}
                self.assertIn("capability or heartbeat", node.inspection_mission_block_reason(mission))
                self.fixture_provider(node)
                self.assertEqual(node.inspection_mission_block_reason(mission), "")
                unsupported = {"steps": [{"type": "inspection_action", "action": "detect",
                                          "detector_types": ["water"]}]}
                self.assertIn("does not support all", node.inspection_mission_block_reason(unsupported))
                node.inspection_heartbeat_seen = time.monotonic() - 6
                self.assertIn("capability or heartbeat", node.inspection_mission_block_reason(mission))
            finally:
                node.destroy_node()
                rclpy.shutdown()
                if previous_log_dir is None:
                    os.environ.pop("ROS_LOG_DIR", None)
                else:
                    os.environ["ROS_LOG_DIR"] = previous_log_dir
                if previous_robot_mode is None:
                    os.environ.pop("ROBOT_MODE", None)
                else:
                    os.environ["ROBOT_MODE"] = previous_robot_mode

    def test_motion_commands_fail_closed_on_unknown_or_active_software_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            previous_log_dir = os.environ.get("ROS_LOG_DIR")
            os.environ["ROS_LOG_DIR"] = directory
            rclpy.init(args=["--ros-args", "-p",
                             f"database_path:={os.path.join(directory, 'missions.sqlite3')}"])
            node = MissionManager()
            node.ack_pub = PublisherSpy()
            self.current_map(node)
            try:
                save = {"command": "save", "mission": {
                    "id": "m", "name": "Wait", "map_id": "grid-1", "map_version_id": "grid-1",
                    "steps": [{"type": "wait", "seconds": 1}]}}
                node.on_command(String(data=json.dumps(save)))
                node.on_command(String(data=json.dumps({"command": "start", "mission_id": "m"})))
                self.assertIn("unavailable or stale", json.loads(node.ack_pub.messages[-1].data)["error"])
                self.assertIsNone(node.run)

                self.software_stop(node, active=True)
                node.on_command(String(data=json.dumps({"command": "start", "mission_id": "m"})))
                self.assertEqual(json.loads(node.ack_pub.messages[-1].data)["error"], "software stop is active")
                self.assertIsNone(node.run)

                self.software_stop(node, durable=False)
                node.on_command(String(data=json.dumps({"command": "start", "mission_id": "m"})))
                self.assertEqual(json.loads(node.ack_pub.messages[-1].data)["error"], "software stop state is not durable")
                self.assertIsNone(node.run)

                self.software_stop(node)
                node.on_command(String(data=json.dumps({"command": "start", "mission_id": "m"})))
                task_id = node.run["task_id"]
                node.on_command(String(data=json.dumps({"command": "pause", "task_id": task_id})))
                self.software_stop(node, active=True)
                node.on_command(String(data=json.dumps({"command": "resume", "task_id": task_id})))
                self.assertEqual(json.loads(node.ack_pub.messages[-1].data)["error"], "software stop is active")
                self.assertEqual(node.run["status"], "PAUSED")
            finally:
                node.destroy_node()
                rclpy.shutdown()
                if previous_log_dir is None:
                    os.environ.pop("ROS_LOG_DIR", None)
                else:
                    os.environ["ROS_LOG_DIR"] = previous_log_dir

    def test_start_and_resume_require_matching_map_identity_and_version(self):
        with tempfile.TemporaryDirectory() as directory:
            previous_log_dir = os.environ.get("ROS_LOG_DIR")
            os.environ["ROS_LOG_DIR"] = directory
            rclpy.init(args=["--ros-args", "-p",
                             f"database_path:={os.path.join(directory, 'missions.sqlite3')}"])
            node = MissionManager()
            node.ack_pub = PublisherSpy()
            self.software_stop(node)
            self.current_map(node)
            try:
                node.on_command(String(data=json.dumps({"command": "save", "mission": {
                    "id": "map-task", "name": "Map bound", "map_id": "grid-1",
                    "map_version_id": "grid-1", "steps": [{"type": "wait", "seconds": 1}],
                }})))
                node.map_bundle = None
                node.on_command(String(data=json.dumps({"command": "start", "mission_id": "map-task"})))
                self.assertIn("map bundle is unavailable or unverified",
                              json.loads(node.ack_pub.messages[-1].data)["error"])
                self.current_map(node)
                self.current_map(node, "grid-2", "grid-2")
                node.on_command(String(data=json.dumps({"command": "start", "mission_id": "map-task"})))
                self.assertEqual(
                    json.loads(node.ack_pub.messages[-1].data)["error"],
                    "mission map_id does not match the current 2D map",
                )
                self.assertIsNone(node.run)

                self.current_map(node)
                node.on_command(String(data=json.dumps({"command": "start", "mission_id": "map-task"})))
                task_id = node.run["task_id"]
                node.on_command(String(data=json.dumps({"command": "pause", "task_id": task_id})))
                self.current_map(node, "grid-1", "revision-2")
                node.on_command(String(data=json.dumps({"command": "resume", "task_id": task_id})))
                self.assertEqual(
                    json.loads(node.ack_pub.messages[-1].data)["error"],
                    "mission map_version_id does not match the current 2D map version",
                )
                self.assertEqual(node.run["status"], "PAUSED")
            finally:
                node.destroy_node()
                rclpy.shutdown()
                if previous_log_dir is None:
                    os.environ.pop("ROS_LOG_DIR", None)
                else:
                    os.environ["ROS_LOG_DIR"] = previous_log_dir

    def test_active_mission_pauses_when_map_bundle_becomes_unverified(self):
        with tempfile.TemporaryDirectory() as directory:
            previous_log_dir = os.environ.get("ROS_LOG_DIR")
            os.environ["ROS_LOG_DIR"] = directory
            rclpy.init(args=["--ros-args", "-p",
                             f"database_path:={os.path.join(directory, 'missions.sqlite3')}"])
            node = MissionManager()
            self.software_stop(node)
            self.current_map(node)
            try:
                node.on_command(String(data=json.dumps({"command": "save", "mission": {
                    "id": "map-task", "name": "Map bound", "map_id": "grid-1",
                    "map_version_id": "grid-1", "steps": [{"type": "wait", "seconds": 30}],
                }})))
                node.on_command(String(data=json.dumps({"command": "start", "mission_id": "map-task"})))
                self.assertEqual(node.run["status"], "RUNNING")
                node.on_map_bundle(String(data=json.dumps({
                    "schema_version": 1, "ready": False, "reason": "active 2D map changed",
                })))
                node.tick()
                self.assertEqual(node.run["status"], "PAUSED")
                self.assertEqual(node.run["hold_active"], 1)
                self.assertIn("map bundle", node.run["reason"])
                self.assertGreater(node.run["remaining_seconds"], 0)
            finally:
                node.destroy_node()
                rclpy.shutdown()
                if previous_log_dir is None:
                    os.environ.pop("ROS_LOG_DIR", None)
                else:
                    os.environ["ROS_LOG_DIR"] = previous_log_dir

    def test_schedule_crud_is_robot_persisted_and_revision_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            previous_log_dir = os.environ.get("ROS_LOG_DIR")
            os.environ["ROS_LOG_DIR"] = directory
            rclpy.init(args=["--ros-args", "-p",
                             f"database_path:={os.path.join(directory, 'missions.sqlite3')}"])
            node = MissionManager()
            node.ack_pub = PublisherSpy()
            self.software_stop(node)
            self.current_map(node)
            try:
                node.on_command(String(data=json.dumps({"command": "save", "mission": {
                    "id": "scheduled", "name": "Scheduled", "map_id": "grid-1",
                    "map_version_id": "grid-1", "steps": [{"type": "wait", "seconds": 1}],
                }})))
                schedule_body = {
                    "name": "Tomorrow", "mission_id": "scheduled", "recurrence": "once",
                    "timezone": "UTC", "local_time": "10:00", "start_date": "2099-01-01",
                    "weekdays": [], "enabled": True,
                }
                node.on_command(String(data=json.dumps({
                    "command": "schedule.save", "schedule": schedule_body,
                    "created_by": "operator-a", "request_id": "save-1",
                })))
                ack = json.loads(node.ack_pub.messages[-1].data)
                self.assertTrue(ack["ok"])
                schedule_id = ack["schedule_id"]
                saved = node.store.schedule("robot-001", schedule_id)
                self.assertEqual(saved["created_by"], "operator-a")
                self.assertEqual(saved["revision"], 1)
                self.assertEqual(saved["recurrence"], "once")

                node.on_command(String(data=json.dumps({
                    "command": "schedule.save", "schedule_id": schedule_id,
                    "expected_revision": 1,
                    "schedule": {**schedule_body, "enabled": False},
                    "request_id": "update-1",
                })))
                self.assertTrue(json.loads(node.ack_pub.messages[-1].data)["ok"])
                self.assertEqual(node.store.schedule("robot-001", schedule_id)["revision"], 2)

                node.on_command(String(data=json.dumps({
                    "command": "schedule.delete", "schedule_id": schedule_id,
                    "expected_revision": 1, "request_id": "stale-delete",
                })))
                self.assertFalse(json.loads(node.ack_pub.messages[-1].data)["ok"])
                self.assertIsNotNone(node.store.schedule("robot-001", schedule_id))
            finally:
                node.destroy_node()
                rclpy.shutdown()
                if previous_log_dir is None:
                    os.environ.pop("ROS_LOG_DIR", None)
                else:
                    os.environ["ROS_LOG_DIR"] = previous_log_dir

    def test_due_schedule_starts_mission_once_and_records_task_id(self):
        with tempfile.TemporaryDirectory() as directory:
            previous_log_dir = os.environ.get("ROS_LOG_DIR")
            os.environ["ROS_LOG_DIR"] = directory
            rclpy.init(args=["--ros-args", "-p",
                           f"database_path:={os.path.join(directory, 'missions.sqlite3')}"])
            node = MissionManager()
            self.software_stop(node)
            self.current_map(node)
            try:
                mission = {
                    "id": "scheduled", "name": "Scheduled", "map_id": "grid-1",
                    "map_version_id": "grid-1", "steps": [{"type": "wait", "seconds": 30}],
                }
                node.store.save_mission(mission)
                from datetime import datetime, timedelta, timezone
                due = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
                node.store.create_schedule("robot-001", {
                    "schedule_id": "schedule-due", "name": "Due now", "mission_id": "scheduled",
                    "recurrence": "once", "timezone": "UTC", "local_time": "00:00",
                    "start_date": "2026-10-08", "weekdays": [], "enabled": True,
                    "next_run_at": due, "created_by": "test",
                })

                node.scheduler_tick()
                history = node.store.schedule_history("robot-001", "schedule-due")
                self.assertEqual(history[0]["status"], "started")
                self.assertEqual(history[0]["task_id"], node.run["task_id"])
                self.assertEqual(node.run["mission_id"], "scheduled")
                self.assertFalse(node.store.schedule("robot-001", "schedule-due")["enabled"])
                node.scheduler_tick()
                self.assertEqual(len(node.store.schedule_history("robot-001", "schedule-due")), 1)
            finally:
                node.destroy_node()
                rclpy.shutdown()
                if previous_log_dir is None:
                    os.environ.pop("ROS_LOG_DIR", None)
                else:
                    os.environ["ROS_LOG_DIR"] = previous_log_dir


if __name__ == "__main__":
    unittest.main()
