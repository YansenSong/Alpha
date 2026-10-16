from types import SimpleNamespace

import pytest
import rclpy
from geometry_msgs.msg import Twist
from rclpy.parameter import Parameter
from std_msgs.msg import Bool, String
from motion_interface import command_gate


@pytest.fixture
def gate(monkeypatch):
    rclpy.init()
    node = command_gate.MotionCommandGate()
    now = SimpleNamespace(value=10.0)
    monkeypatch.setattr(command_gate.time, 'monotonic', lambda: now.value)
    messages = []
    node.pub = SimpleNamespace(publish=messages.append)
    node.navigation_rules_required = True
    command = Twist(); command.linear.x = .6; command.angular.z = .2
    node.command_callback(command)
    yield node, now, messages
    node.destroy_node(); rclpy.shutdown()


def ready(node):
    node.area_callback(String(data='{"ready":true,"stop":false,"speed_limit":0.2}'))
    node.rules_callback(Bool(data=False))


def test_waits_for_both_states_and_preserves_steering(gate):
    node, now, messages = gate
    node.timer_callback(); assert messages[-1].linear.x == 0
    ready(node); node.timer_callback()
    assert messages[-1].linear.x == .2
    assert messages[-1].angular.z == .2
    now.value += .6
    node.timer_callback(); assert messages[-1].linear.x == 0


def test_holds_and_invalid_control_stop_motion(gate):
    node, now, messages = gate
    ready(node)
    node.rules_callback(Bool(data=True)); node.timer_callback()
    assert messages[-1].linear.x == 0
    ready(node); node.mission_callback(Bool(data=True)); node.timer_callback()
    assert messages[-1].linear.x == 0
    node.mission_callback(Bool(data=False))
    node.area_callback(String(data='{"ready":true,"stop":false,"speed_limit":NaN}'))
    node.timer_callback(); assert messages[-1].linear.x == 0
    ready(node); node.stop_callback(Bool(data=True)); node.timer_callback()
    assert messages[-1].linear.x == 0
