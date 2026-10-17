"""Real C++ authority under isolated DDS, with synthetic controller/odom inputs."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import rclpy
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry
from nav_status.msg import NavigationExecution, ControllerFeedback, NavigationStatus
from std_msgs.msg import Bool, String
from rclpy.qos import QoSProfile, DurabilityPolicy

ROOT = Path(__file__).resolve().parents[4]


class NavigationContractTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, ROS_LOG_DIR=self.directory.name)
        self.output = open(self.directory.name + "/node.log", "w+")
        self.process = subprocess.Popen([str(ROOT / "install/nav_status/lib/nav_status/nav_status_node"), "--ros-args", "-p", "arrival_hold_time:=0.12", "-p", "input_timeout:=0.5", "-p", "status_heartbeat_rate:=20.0"], env=self.env, stdout=self.output, stderr=self.output)
        rclpy.init()
        self.node = rclpy.create_node("navigation_contract_fixture")
        self.results = []
        qos = QoSProfile(depth=10, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.node.create_subscription(NavigationExecution, "/navigation/execution_state", self.results.append, qos)
        self.goal_pub = self.node.create_publisher(PoseStamped, "/goal_pose", 10)
        self.planner_pub = self.node.create_publisher(NavigationExecution, "/navigation/planner_state", qos)
        self.feedback_pub = self.node.create_publisher(ControllerFeedback, "/neupan/controller_feedback", 10)
        self.odom_pub = self.node.create_publisher(Odometry, "/odom_wheel", 10)
        self.wait(lambda: bool(self.results), 4)
        self.goal = PoseStamped()
        self.goal.header.frame_id = "map"
        self.goal.header.stamp = self.node.get_clock().now().to_msg()
        self.goal.pose.position.x = 1.
        self.goal.pose.position.y = 2.
        self.goal.pose.orientation.w = 1.
        self.goal_pub.publish(self.goal)
        self.wait(lambda: self.results[-1].goal == self.goal)
        self.install()

    def tearDown(self):
        self.node.destroy_node()
        rclpy.shutdown()
        self.process.terminate()
        self.process.wait(timeout=5)
        self.output.close()
        self.directory.cleanup()

    def wait(self, predicate, timeout=2):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            rclpy.spin_once(self.node, timeout_sec=.02)
        if not predicate():
            self.output.flush(); self.output.seek(0)
            self.fail("Navigation contract timed out: " + self.output.read())

    def install(self, held=False):
        execution = NavigationExecution()
        execution.stamp = self.node.get_clock().now().to_msg()
        execution.goal = copy.deepcopy(self.goal)
        execution.path_stamp = self.node.get_clock().now().to_msg()
        execution.state = execution.PLANNING if held else execution.MOVING
        execution.held = held
        self.planner_pub.publish(execution)
        self.wait(lambda: self.results[-1].state == execution.state and self.results[-1].held == held)
        self.path = execution.path_stamp

    def feed(self, duration=.22, *, speed=0., old_path=False, old_time=False, old_odom=False, arrived=True):
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            stamp = self.node.get_clock().now().to_msg()
            odom = Odometry()
            odom.header.stamp = copy.deepcopy(stamp)
            if old_odom: odom.header.stamp.sec -= 2
            odom.twist.twist.linear.x = speed
            self.odom_pub.publish(odom)
            feedback = ControllerFeedback()
            feedback.stamp = copy.deepcopy(stamp)
            if old_time: feedback.stamp.sec -= 2
            feedback.path_stamp = copy.deepcopy(self.path)
            if old_path: feedback.path_stamp.nanosec = (feedback.path_stamp.nanosec + 1) % 1000000000
            feedback.arrived = arrived
            feedback.position_tolerance = .5
            feedback.observed_pose = copy.deepcopy(self.goal)
            feedback.observed_pose.header.stamp = stamp
            feedback.observed_pose.pose.position.x += .4
            self.feedback_pub.publish(feedback)
            rclpy.spin_once(self.node, timeout_sec=.02)
        rclpy.spin_once(self.node, timeout_sec=.02)

    def test_result_uses_controller_tolerance_and_is_immutable(self):
        self.feed()
        self.wait(lambda: self.results[-1].state == NavigationExecution.ARRIVED)
        result = json.loads(self.results[-1].result_json)
        self.assertEqual(result["source"], "nav_status")
        self.assertEqual(result["position_tolerance"], .5)
        self.assertGreaterEqual(result["stable_stop_seconds"], .12)
        snapshot = self.results[-1].result_json
        self.feed(speed=1., arrived=False)
        self.assertEqual(self.results[-1].result_json, snapshot)

    def test_wrong_path_and_stale_controller_cannot_arrive(self):
        self.feed(old_path=True)
        self.assertNotEqual(self.results[-1].state, NavigationExecution.ARRIVED)
        self.feed(old_time=True)
        self.assertNotEqual(self.results[-1].state, NavigationExecution.ARRIVED)

    def test_moving_vehicle_cannot_arrive(self):
        self.feed(speed=.2)
        self.assertNotEqual(self.results[-1].state, NavigationExecution.ARRIVED)
        self.feed()
        self.wait(lambda: self.results[-1].state == NavigationExecution.ARRIVED)

    def test_replan_does_not_reuse_old_path_arrival(self):
        previous = copy.deepcopy(self.path)
        self.install(held=True)
        self.install()
        current = self.path
        self.path = previous
        self.feed()
        self.assertNotEqual(self.results[-1].state, NavigationExecution.ARRIVED)
        self.path = current
        self.feed()
        self.wait(lambda: self.results[-1].state == NavigationExecution.ARRIVED)

    def test_stale_odometry_cannot_arrive(self):
        self.feed(old_odom=True)
        self.assertNotEqual(self.results[-1].state, NavigationExecution.ARRIVED)

    def test_legacy_bool_and_string_cannot_change_execution_result(self):
        legacy = self.node.create_publisher(Bool, "/neupan/arrived", 10)
        status = self.node.create_publisher(String, "/global_plan/status", 10)
        legacy.publish(Bool(data=True))
        status.publish(String(data="succeeded"))
        self.feed(arrived=False)
        self.assertNotEqual(self.results[-1].state, NavigationExecution.ARRIVED)

    def test_new_goal_identity_is_not_ordered_by_wall_vs_ros_time(self):
        self.goal.header.stamp.sec -= 1000
        self.goal_pub.publish(self.goal)
        self.wait(lambda: self.results[-1].goal == self.goal)
        self.install()
        self.feed()
        self.wait(lambda: self.results[-1].state == NavigationExecution.ARRIVED)

    def test_planner_event_before_goal_is_buffered_without_starting_it(self):
        new_goal = copy.deepcopy(self.goal)
        new_goal.header.stamp = self.node.get_clock().now().to_msg()
        execution = NavigationExecution()
        execution.stamp = self.node.get_clock().now().to_msg()
        execution.goal = new_goal
        execution.path_stamp = execution.stamp
        execution.state = execution.MOVING
        self.planner_pub.publish(execution)
        self.feed(arrived=False, duration=.1)
        self.assertEqual(self.results[-1].goal, self.goal)
        self.goal = new_goal
        self.goal_pub.publish(self.goal)
        self.wait(lambda: self.results[-1].goal == new_goal and self.results[-1].state == execution.MOVING)
        self.path = execution.path_stamp
        self.feed()
        self.wait(lambda: self.results[-1].state == NavigationExecution.ARRIVED)

    def test_new_goal_ignores_old_planner_metadata(self):
        old_goal, old_path = copy.deepcopy(self.goal), copy.deepcopy(self.path)
        self.goal.header.stamp = self.node.get_clock().now().to_msg()
        self.goal_pub.publish(self.goal)
        self.wait(lambda: self.results[-1].goal == self.goal)
        old = NavigationExecution(goal=old_goal, path_stamp=old_path, state=NavigationExecution.MOVING)
        self.planner_pub.publish(old)
        self.feed(old_path=True)
        self.assertEqual(self.results[-1].state, NavigationExecution.PLANNING)
        self.assertEqual(self.results[-1].goal, self.goal)

if __name__ == "__main__": unittest.main()
