#!/usr/bin/env python3
"""Gate planner commands and publish the canonical real-vehicle Ackermann command.

Input contract (default: /neupan_cmd_vel_raw):
  - linear.x: longitudinal speed in m/s
  - angular.z: front-wheel steering angle in radians

Output contract (default: /ackermann_cmd):
  - linear.x: longitudinal speed in m/s
  - angular.z: front-wheel steering angle in radians

The gate provides the centralized /stop override and a ROS-layer command
watchdog. Hardware limits and STM32 protocol encoding belong to the downstream
STM32 bridge in this package.
"""

import copy
import json
import math
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.time import Time
from std_msgs.msg import Bool, String


class MotionCommandGate(Node):
    """Gate planner commands and publish the canonical real-vehicle command."""

    def __init__(self):
        super().__init__('motion_command_gate')

        self.declare_parameter('input_topic', '/neupan_cmd_vel_raw')
        self.declare_parameter('output_topic', '/ackermann_cmd')
        self.declare_parameter('publish_rate', 20.0)
        self.declare_parameter('command_timeout', 0.5)
        self.declare_parameter('navigation_rules_required', False)

        self.input_topic = self.get_parameter('input_topic').value
        self.output_topic = self.get_parameter('output_topic').value
        self.publish_rate = float(self.get_parameter('publish_rate').value)
        self.command_timeout = float(self.get_parameter('command_timeout').value)

        if self.publish_rate <= 0.0:
            raise ValueError('publish_rate must be greater than zero')
        if self.command_timeout <= 0.0:
            raise ValueError('command_timeout must be greater than zero')

        self.pub = self.create_publisher(Twist, self.output_topic, 10)
        self.command_sub = self.create_subscription(
            Twist, self.input_topic, self.command_callback, 10
        )
        self.stop_sub = self.create_subscription(
            Bool, '/stop', self.stop_callback, 10
        )

        self.navigation_rules_required = bool(self.get_parameter('navigation_rules_required').value)
        self.area_control = None
        self.area_received = None
        self.rules_hold = True
        self.rules_received = None
        self.mission_hold = False
        self.create_subscription(String, '/area_rules/control', self.area_callback, 10)
        self.create_subscription(Bool, '/navigation/rules_hold', self.rules_callback, 10)
        self.create_subscription(Bool, '/mission/hold', self.mission_callback, 10)

        self.command_msg: Twist | None = None
        self.last_command_time: Time | None = None
        self.stop_requested = False
        self.timeout_active = False

        self.timer = self.create_timer(1.0 / self.publish_rate, self.timer_callback)

        self.get_logger().info(
            f'Motion command gate: {self.input_topic} + /stop -> '
            f'{self.output_topic} (linear.x=speed, angular.z=steering angle)'
        )

    def command_callback(self, msg: Twist):
        speed = float(msg.linear.x)
        steering = float(msg.angular.z)
        if not math.isfinite(speed) or not math.isfinite(steering):
            self.get_logger().error(
                'Received non-finite Ackermann command; replacing it with stop'
            )
            self.command_msg = Twist()
        else:
            self.command_msg = msg

        self.last_command_time = self.get_clock().now()
        self.timeout_active = False

    def stop_callback(self, msg: Bool):
        requested = bool(msg.data)
        if requested != self.stop_requested:
            if requested:
                self.get_logger().warn('/stop override ACTIVE')
            else:
                self.get_logger().info('/stop override released')
        self.stop_requested = requested

    def area_callback(self, msg):
        try:
            control = json.loads(msg.data)
            if not isinstance(control.get('ready'), bool) or not isinstance(control.get('stop'), bool):
                raise ValueError('invalid area state')
            limit = control.get('speed_limit')
            if limit is not None and (isinstance(limit, bool) or not isinstance(limit, (int, float))
                                      or not math.isfinite(limit) or limit <= 0):
                raise ValueError('invalid speed limit')
        except (ValueError, TypeError, AttributeError):
            self.area_control = None
            return
        self.area_control = control
        self.area_received = time.monotonic()

    def rules_callback(self, msg):
        self.rules_hold = bool(msg.data)
        self.rules_received = time.monotonic()

    def mission_callback(self, msg):
        self.mission_hold = bool(msg.data)

    def navigation_blocked(self):
        now = time.monotonic()
        area_required = self.navigation_rules_required or self.area_received is not None
        rules_required = self.navigation_rules_required or self.rules_received is not None
        return (
            self.mission_hold
            or (area_required and (self.area_control is None or self.area_received is None
                or now - self.area_received > 0.5 or not self.area_control['ready']
                or self.area_control['stop']))
            or (rules_required and (self.rules_received is None
                or now - self.rules_received > 0.5 or self.rules_hold))
        )

    def timer_callback(self):
        if self.stop_requested or self.navigation_blocked():
            command = Twist()
            source = 'stop'
        elif self.command_msg is None or self.last_command_time is None:
            return
        else:
            age = (
                self.get_clock().now() - self.last_command_time
            ).nanoseconds * 1e-9
            if age > self.command_timeout:
                command = Twist()
                source = 'timeout'
                if not self.timeout_active:
                    self.get_logger().warn(
                        f'Ackermann command timeout ({age:.2f}s > '
                        f'{self.command_timeout:.2f}s); publishing stop'
                    )
                    self.timeout_active = True
            else:
                command = self.command_msg
                source = 'planner'
                self.timeout_active = False

        if source == 'planner' and self.area_control is not None:
            limit = self.area_control['speed_limit']
            if limit is not None and abs(command.linear.x) > limit:
                command = copy.deepcopy(command)
                command.linear.x = math.copysign(limit, command.linear.x)
                # angular.z is a steering angle; preserve it when limiting speed.
        self.pub.publish(command)
        self.get_logger().debug(
            f'[{source}] v={command.linear.x:.2f} m/s, '
            f'steer={command.angular.z:.3f} rad',
            throttle_duration_sec=10.0,
        )


def main(args=None):
    rclpy.init(args=args)
    node = MotionCommandGate()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
