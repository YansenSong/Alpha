"""Exercise real control generation without constructing a ROS node or publishing."""
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from geometry_msgs.msg import TransformStamped
from rclpy.time import Time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from area_rules.node import AreaRules


class DisabledControlTest(unittest.TestCase):
    def test_disabled_blocking_and_speed_rules_do_not_affect_control(self):
        transform = TransformStamped()
        transform.header.stamp.sec = 1
        transform.transform.rotation.w = 1.
        messages = []
        node = SimpleNamespace(
            rules=[{"id": "block", "type": "keepout", "cx": 0., "cy": 0., "w": 2., "h": 2.},
                   {"id": "slow", "type": "speed", "cx": 0., "cy": 0., "w": 2., "h": 2., "limit_mps": .2}],
            key="m", navigation_applied=lambda: True, actual_speed=.1,
            odom_received_at=time.monotonic(), robot_frame="base_link",
            grid=SimpleNamespace(header=SimpleNamespace(frame_id="map")),
            tf_buffer=SimpleNamespace(lookup_transform=lambda *args: transform),
            get_clock=lambda: SimpleNamespace(now=lambda: Time.from_msg(transform.header.stamp)),
            get_parameter=lambda name: SimpleNamespace(value=.5),
            control_pub=SimpleNamespace(publish=lambda msg: messages.append(json.loads(msg.data))),
        )
        AreaRules.publish_control(node)
        self.assertTrue(messages[-1]["stop"])
        self.assertEqual(messages[-1]["configured_speed_limit_mps"], .2)
        for rule in node.rules: rule["enabled"] = False
        AreaRules.publish_control(node)
        self.assertTrue(messages[-1]["ready"])
        self.assertFalse(messages[-1]["stop"])
        self.assertIsNone(messages[-1]["speed_limit"])
        self.assertIsNone(messages[-1]["configured_speed_limit_mps"])
