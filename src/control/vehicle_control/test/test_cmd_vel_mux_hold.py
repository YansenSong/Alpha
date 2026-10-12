"""Mission hold and the independently controlled /stop latch stay separate."""

import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from builtin_interfaces.msg import Time
from geometry_msgs.msg import Twist
from std_msgs.msg import Bool, String


SCRIPT = Path(__file__).resolve().parents[1] / "cmd_vel_mux.py"
SPEC = importlib.util.spec_from_file_location("cmd_vel_mux", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakePublisher:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message)


class FakeLogger:
    def warn(self, *_args):
        pass

    def debug(self, *_args, **_kwargs):
        pass

    def error(self, *_args):
        pass


class FakeClock:
    def now(self):
        return self

    def to_msg(self):
        return Time()


class FakeMux(MODULE.CmdVelMux):
    stop_requested = False
    mission_hold_requested = False
    manual_msg = None
    neupan_msg = None
    manual_received_at = None
    manual_cmd_timeout = 0.5
    neupan_received_at = None
    neupan_cmd_timeout = 0.5
    area_rules_required = True
    area_control_timeout = 0.5
    area_control = None
    area_control_received_at = None
    rules_hold_required = False
    rules_hold_timeout = 0.5
    rules_hold = True
    rules_hold_received_at = None
    max_acceleration = 100.0

    def __init__(self):
        self.pub = FakePublisher()
        self.software_stop_state_pub = FakePublisher()
        self.software_stop_state_file = Path(tempfile.mkdtemp()) / "software_stop.json"
        self.software_stop_state = {
            "active": False, "source": "startup", "reason": "",
            "request_id": "", "observed_at": "", "result": "confirmed",
            "durable": True,
        }
        self.last_stop_state_publish = 0.0
        self.last_output_speed = 0.0
        self.last_output_at = time.monotonic() - 1.0

    def get_logger(self):
        return FakeLogger()

    def get_clock(self):
        return FakeClock()


class MissionHoldTest(unittest.TestCase):
    def test_repeated_stop_requests_are_idempotent_and_remain_durable(self):
        mux = FakeMux()
        for request_id in ("stop-1", "stop-2"):
            MODULE.CmdVelMux.software_stop_request_callback(
                mux,
                String(data=json.dumps({
                    "action": "request_stop",
                    "request_id": request_id,
                    "source": "web:operator",
                })),
            )

        persisted = json.loads(mux.software_stop_state_file.read_text())
        self.assertTrue(mux.stop_requested)
        self.assertTrue(persisted["active"])
        self.assertTrue(persisted["durable"])
        self.assertEqual(persisted["request_id"], "stop-2")

    def test_releasing_mission_hold_does_not_release_operator_stop(self):
        mux = FakeMux()
        MODULE.CmdVelMux.stop_callback(mux, Bool(data=True))
        MODULE.CmdVelMux.mission_hold_callback(mux, Bool(data=True))
        MODULE.CmdVelMux.mission_hold_callback(mux, Bool(data=False))
        MODULE.CmdVelMux.timer_callback(mux)
        self.assertTrue(mux.stop_requested)
        self.assertEqual(len(mux.pub.messages), 1)
        self.assertEqual(mux.pub.messages[0].twist.linear.x, 0.0)

    def test_rules_hold_blocks_both_sources_and_stale_heartbeat(self):
        for source in ('manual', 'neupan'):
            mux = FakeMux()
            mux.area_rules_required = False
            mux.rules_hold_required = True
            command = Twist()
            command.linear.x = 0.4
            getattr(mux, f'{source}_callback')(command)
            MODULE.CmdVelMux.timer_callback(mux)
            self.assertEqual(mux.pub.messages[-1].twist.linear.x, 0.0)
            MODULE.CmdVelMux.rules_hold_callback(mux, Bool(data=False))
            mux.last_output_at -= 1.0
            MODULE.CmdVelMux.timer_callback(mux)
            self.assertEqual(mux.pub.messages[-1].twist.linear.x, 0.4)
            mux.rules_hold_received_at -= 1.0
            MODULE.CmdVelMux.timer_callback(mux)
            self.assertEqual(mux.pub.messages[-1].twist.linear.x, 0.0)

    def test_stop_false_releases_persistent_stop(self):
        mux = FakeMux()
        MODULE.CmdVelMux.stop_callback(mux, Bool(data=True))
        MODULE.CmdVelMux.stop_callback(mux, Bool(data=False))
        self.assertFalse(mux.stop_requested)
        self.assertFalse(json.loads(mux.software_stop_state_file.read_text())["active"])

    def test_stop_latch_survives_mux_restart(self):
        mux = FakeMux()
        MODULE.CmdVelMux.set_software_stop(
            mux, active=True, source="web:operator", reason="test stop", request_id="req-1"
        )
        recovered = FakeMux()
        recovered.software_stop_state_file = mux.software_stop_state_file
        recovered.software_stop_state = MODULE.CmdVelMux.load_software_stop_state(recovered)
        recovered.stop_requested = recovered.software_stop_state["active"]
        self.assertTrue(recovered.stop_requested)
        self.assertEqual(recovered.software_stop_state["request_id"], "req-1")

    def test_corrupt_stop_state_fails_closed(self):
        mux = FakeMux()
        mux.software_stop_state_file.write_text("broken", encoding="utf-8")
        state = MODULE.CmdVelMux.load_software_stop_state(mux)
        self.assertTrue(state["active"])
        self.assertFalse(state["durable"])
        self.assertEqual(state["result"], "degraded")

    def test_failed_stop_persistence_keeps_in_memory_latch_and_reports_degraded(self):
        mux = FakeMux()
        with patch.object(mux, "persist_software_stop_state", side_effect=OSError("disk full")):
            MODULE.CmdVelMux.set_software_stop(
                mux, active=True, source="test", reason="stop", request_id="stop-1"
            )
        self.assertTrue(mux.stop_requested)
        self.assertFalse(mux.software_stop_state["durable"])
        self.assertEqual(mux.software_stop_state["result"], "degraded")

    def test_release_succeeds_while_motion_command_is_fresh(self):
        mux = FakeMux()
        mux.area_rules_required = False
        MODULE.CmdVelMux.set_software_stop(
            mux, active=True, source="test", reason="stop", request_id="stop-1"
        )
        active = Twist()
        active.linear.x = 0.3
        MODULE.CmdVelMux.manual_callback(mux, active)
        request = String(data=json.dumps({
            "action": "request_release", "request_id": "release-1"
        }))
        MODULE.CmdVelMux.software_stop_request_callback(mux, request)
        self.assertFalse(mux.stop_requested)
        self.assertEqual(mux.software_stop_state["result"], "confirmed")

    def test_release_does_not_require_area_safety_precheck(self):
        mux = FakeMux()
        MODULE.CmdVelMux.set_software_stop(
            mux, active=True, source="test", reason="stop", request_id="stop-1"
        )
        request = String(data=json.dumps({
            "action": "request_release", "request_id": "release-1"
        }))
        MODULE.CmdVelMux.software_stop_request_callback(mux, request)
        self.assertFalse(mux.stop_requested)
        self.assertEqual(mux.software_stop_state["result"], "confirmed")

    def test_task_hold_and_area_stop_do_not_block_stop_release(self):
        for hold, area_json in (
            (True, '{"ready": true, "stop": false}'),
            (False, '{"ready": true, "stop": true}'),
        ):
            mux = FakeMux()
            mux.mission_hold_requested = hold
            MODULE.CmdVelMux.area_control_callback(mux, String(data=area_json))
            MODULE.CmdVelMux.set_software_stop(
                mux, active=True, source="test", reason="stop", request_id="stop-1"
            )
            MODULE.CmdVelMux.software_stop_request_callback(
                mux,
                String(data=json.dumps({
                    "action": "request_release", "request_id": "release-1"
                })),
            )
            self.assertFalse(mux.stop_requested)
            self.assertEqual(mux.software_stop_state["result"], "confirmed")

    def test_state_query_returns_correlated_robot_state(self):
        mux = FakeMux()
        MODULE.CmdVelMux.software_stop_request_callback(
            mux,
            String(data=json.dumps({
                "action": "get_state", "request_id": "query-123"
            })),
        )
        response = json.loads(mux.software_stop_state_pub.messages[-1].data)
        self.assertEqual(response["request_id"], "query-123")
        self.assertFalse(response["active"])
        self.assertEqual(response["physical_estop"], {"available": False, "active": None})

    def test_authorized_release_succeeds_after_motion_and_area_conditions_clear(self):
        mux = FakeMux()
        mux.area_rules_required = False
        MODULE.CmdVelMux.set_software_stop(
            mux, active=True, source="test", reason="stop", request_id="stop-1"
        )
        request = String(data=json.dumps({
            "action": "request_release", "request_id": "release-1"
        }))
        MODULE.CmdVelMux.software_stop_request_callback(mux, request)
        self.assertFalse(mux.stop_requested)
        persisted = json.loads(mux.software_stop_state_file.read_text())
        self.assertFalse(persisted["active"])
        self.assertEqual(persisted["request_id"], "release-1")

    def test_neupan_command_expires_instead_of_replaying_after_stop_release(self):
        mux = FakeMux()
        mux.area_rules_required = False
        command = Twist()
        command.linear.x = 0.4
        MODULE.CmdVelMux.neupan_callback(mux, command)
        mux.neupan_received_at -= 1.0
        MODULE.CmdVelMux.timer_callback(mux)
        self.assertEqual(len(mux.pub.messages), 0)

    def test_area_heartbeat_and_speed_limit_constrain_manual_command(self):
        mux = FakeMux()
        mux.manual_msg = Twist()
        mux.manual_msg.linear.x = 0.8
        mux.manual_msg.angular.z = 0.4
        MODULE.CmdVelMux.manual_callback(mux, mux.manual_msg)
        MODULE.CmdVelMux.timer_callback(mux)
        self.assertEqual(mux.pub.messages[-1].twist.linear.x, 0.0)
        MODULE.CmdVelMux.area_control_callback(mux, String(data=(
            '{"ready": true, "stop": false, "speed_limit": 0.2}')))
        mux.last_output_at -= 1.0
        MODULE.CmdVelMux.timer_callback(mux)
        self.assertAlmostEqual(mux.pub.messages[-1].twist.linear.x, 0.2)
        self.assertAlmostEqual(mux.pub.messages[-1].twist.angular.z, 0.1)
        self.assertAlmostEqual(mux.manual_msg.linear.x, 0.8)
        mux.area_control_received_at -= 1.0
        MODULE.CmdVelMux.timer_callback(mux)
        self.assertEqual(mux.pub.messages[-1].twist.linear.x, 0.0)

    def test_acceleration_limit_applies_to_reverse_and_forward(self):
        for requested in (0.8, -0.8):
            mux = FakeMux()
            mux.area_rules_required = False
            mux.max_acceleration = 0.5
            mux.last_output_at = time.monotonic() - 0.1
            command = Twist()
            command.linear.x = requested
            MODULE.CmdVelMux.manual_callback(mux, command)
            MODULE.CmdVelMux.timer_callback(mux)
            self.assertLessEqual(abs(mux.pub.messages[-1].twist.linear.x), 0.051)


if __name__ == "__main__":
    unittest.main()
