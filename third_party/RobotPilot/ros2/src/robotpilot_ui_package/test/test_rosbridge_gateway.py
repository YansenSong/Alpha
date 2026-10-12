import unittest

import json

from robotpilot_ui_package.rosbridge_gateway import allowed_origin, required_role


class GatewayPolicyTest(unittest.TestCase):
    def test_default_deny_and_role_categories(self):
        self.assertEqual(required_role({"op": "subscribe", "topic": "/mission/state"}), "Viewer")
        self.assertIsNone(required_role({"op": "publish", "topic": "/mission/command"}))
        self.assertEqual(required_role({"op": "publish", "topic": "/mission/command",
                                        "msg": {"data": '{"command":"query"}'}}), "Viewer")
        self.assertIsNone(required_role({"op": "publish", "topic": "/mission/command",
                                        "msg": {"data": '{"command":"start"}'}}))
        for topic in ("/initialpose", "/goal_pose", "/dock_trigger", "/undock_robot",
                      "/periphery_operation"):
            self.assertIsNone(required_role({"op": "publish", "topic": topic}))
        self.assertIsNone(required_role({"op": "publish", "topic": "/cmd_vel"}))
        self.assertIsNone(required_role({"op": "publish", "topic": "/unknown"}))
        self.assertIsNone(required_role({"op": "call_service", "service": "/rosapi/set_param"}))
        self.assertIsNone(required_role({"op": "advertise_service", "service": "/fake"}))

    def test_software_stop_requests_use_action_specific_roles(self):
        def message(action):
            return {
                "op": "publish",
                "topic": "/safety/software_stop/request",
                "msg": {"data": json.dumps({"action": action, "request_id": "request-1"})},
            }

        self.assertEqual(required_role(message("get_state")), "Viewer")
        self.assertEqual(required_role(message("request_stop")), "Operator")
        self.assertEqual(required_role(message("request_release")), "Operator")
        self.assertIsNone(required_role(message("anything_else")))
        self.assertEqual(required_role({
            "op": "advertise", "topic": "/safety/software_stop/request",
        }), "Viewer")
        self.assertIsNone(required_role({
            "op": "publish", "topic": "/safety/software_stop/request",
            "msg": {"data": "not-json"},
        }))

    def test_origin_must_match(self):
        allowed = {"https://robot.example"}
        self.assertTrue(allowed_origin("https://robot.example", allowed))
        self.assertFalse(allowed_origin("https://robot.example.evil", allowed))
        self.assertFalse(allowed_origin(None, allowed))


if __name__ == "__main__":
    unittest.main()
