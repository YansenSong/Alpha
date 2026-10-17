"""Exercise the real publisher method without loading the GPU planner runtime."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
import numpy as np
from builtin_interfaces.msg import Time
from geometry_msgs.msg import Quaternion
from nav_status.msg import ControllerFeedback
from std_msgs.msg import Bool

source = Path(__file__).resolve().parents[1] / "neupan_ros2/neupan_node.py"
parsed = ast.parse(source.read_text())
node_class = next(node for node in parsed.body if isinstance(node, ast.ClassDef) and node.name == "NeupanCore")
method = next(node for node in node_class.body if isinstance(node, ast.FunctionDef) and node.name == "_publish_planning_results")
module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), method], type_ignores=[])
namespace = {"ControllerFeedback": ControllerFeedback, "Bool": Bool,
             "yaw_to_quat": lambda yaw: Quaternion(w=1.)}
exec(compile(ast.fix_missing_locations(module), str(source), "exec"), namespace)
publish_results = namespace["_publish_planning_results"]


class FeedbackIdentityTest(unittest.TestCase):
    def fixture(self):
        outputs = {key: [] for key in ["plan_pub", "ref_state_pub", "vel_pub", "arrival_pub", "feedback_pub"]}
        node = SimpleNamespace(**{key: SimpleNamespace(publish=value.append) for key, value in outputs.items()})
        node.execution_path_stamp = Time(sec=3)
        node.map_frame = "map"
        node.get_clock = lambda: SimpleNamespace(now=lambda: SimpleNamespace(to_msg=lambda: Time(sec=5)))
        node.generate_path_msg = lambda path: path
        node.generate_twist_msg = lambda *args: args
        node.viz_manager = SimpleNamespace(publish_visualization=lambda *args: None)
        node.neupan_planner = None
        node.robot_state = None
        info = {"execution_path_stamp": Time(sec=3), "arrive": True, "stop": False,
                "opt_state_list": [], "ref_state_list": [], "observed_state": np.array([[1.], [2.], [0.]]),
                "position_tolerance": .5, "observed_stamp": Time(sec=4)}
        return node, info, outputs

    def test_obsolete_path_result_does_not_publish_control_or_arrival(self):
        node, info, outputs = self.fixture()
        node.execution_path_stamp = Time(sec=7)
        publish_results(node, None, info)
        self.assertTrue(all(not messages for messages in outputs.values()))

    def test_feedback_carries_computation_identity_and_original_pose_time(self):
        node, info, outputs = self.fixture()
        publish_results(node, None, info)
        feedback = outputs["feedback_pub"][0]
        self.assertEqual(feedback.path_stamp, Time(sec=3))
        self.assertEqual(feedback.observed_pose.header.stamp, Time(sec=4))
        self.assertEqual(feedback.stamp, Time(sec=5))
        self.assertEqual(feedback.position_tolerance, .5)
        self.assertTrue(feedback.arrived)
