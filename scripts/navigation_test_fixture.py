"""Structured navigation result injection for isolated tests only.

This does not publish ROS messages or judge arrival. Tests of nav_status itself
must exercise the real C++ authority instead of using this helper.
"""
import json
from nav_status.msg import NavigationExecution


def navigation_message(node):
    message = NavigationExecution()
    message.stamp = node.get_clock().now().to_msg()
    message.goal.header.frame_id = "map"
    message.goal.header.stamp.sec = node.goal_sent_ns // 1_000_000_000
    message.goal.header.stamp.nanosec = node.goal_sent_ns % 1_000_000_000
    target = node._navigation_target()
    message.goal.pose.position.x = float(target["x"])
    message.goal.pose.position.y = float(target["y"])
    message.goal.pose.orientation.z = float(target["z"])
    message.goal.pose.orientation.w = float(target["w"])
    message.path_stamp = message.goal.header.stamp
    message.execution_id = node.navigation_execution_id
    message.result_json = json.dumps({
        "source": "nav_status", "policy_version": 1, "verified": True,
        "execution_id": message.execution_id, "goal_stamp_ns": node.goal_sent_ns,
        "path_stamp_ns": node.goal_sent_ns, "target": target,
        "observed_pose": target, "position_tolerance": 0.5,
        "linear_speed": 0.0, "stable_stop_seconds": 0.8,
    })
    return message
