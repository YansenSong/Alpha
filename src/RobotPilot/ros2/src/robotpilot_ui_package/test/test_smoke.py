import unittest
import tempfile
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch


class PackageSmokeTest(unittest.TestCase):
    def test_static_modules_import(self):
        import robotpilot_ui_package.flask_app  # noqa: F401
        import robotpilot_ui_package.map_relay  # noqa: F401
        import robotpilot_ui_package.nav_relays  # noqa: F401
        import robotpilot_ui_package.route_store  # noqa: F401
        import robotpilot_ui_package.folders_handler  # noqa: F401

    def test_ui_launch_starts_map_handler_without_route_ownership_or_browser(self):
        from launch_ros.actions import Node

        launch_file = Path(__file__).parents[1] / "launch" / "new_ui_launch.py"
        spec = spec_from_file_location("robotpilot_ui_new_launch", launch_file)
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        description = module.generate_launch_description()
        nodes = [action for action in description.entities if isinstance(action, Node)]

        self.assertTrue(any(node.node_executable == "route_store" for node in nodes))
        handler = next(node for node in nodes if node.node_executable == "handler")
        parameters = {
            key[0].text: value
            for key, value in handler._Node__parameters[0].items()
        }
        self.assertEqual(
            parameters,
            {"map_management_only": True, "open_browser": False},
        )


class FlaskApiTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

        import robotpilot_ui_package.flask_app as flask_app

        self.flask_app = flask_app
        flask_app.BLOCK_PROGRAMS_DIR = f"{self.tmpdir.name}/block_programs"
        flask_app.BLOCK_LOCATIONS_FILE = f"{self.tmpdir.name}/block_locations.json"
        flask_app.BLOCK_RUN_HISTORY_FILE = (
            f"{self.tmpdir.name}/block_run_history.json"
        )
        flask_app.app.config.update(TESTING=True)
        self.client = flask_app.app.test_client()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_block_program_api_round_trip(self):
        response = self.client.post(
            "/api/block-programs/Test Program",
            json={"workspace": {"blocks": []}, "plan": [{"type": "wait"}]},
        )
        self.assertEqual(response.status_code, 201)

        response = self.client.get("/api/block-programs")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["programs"][0]["name"], "Test Program")

        response = self.client.get("/api/block-programs/Test Program")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["workspace"], {"blocks": []})

        response = self.client.delete("/api/block-programs/Test Program")
        self.assertEqual(response.status_code, 200)

    def test_block_location_api_round_trip(self):
        response = self.client.post(
            "/api/block-locations/Dock",
            json={"x": 1.2, "y": 3.4, "yaw": 1.57},
        )
        self.assertEqual(response.status_code, 201)

        response = self.client.get("/api/block-locations")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["locations"]["Dock"]["x"], 1.2)

        response = self.client.delete("/api/block-locations/Dock")
        self.assertEqual(response.status_code, 200)

    def test_block_run_history_api_round_trip(self):
        response = self.client.post(
            "/api/block-run-history",
            json={
                "program_name": "Safe Motion Test",
                "status": "success",
                "started_at": "2026-01-01T00:00:00+00:00",
                "duration_ms": 1000,
                "steps_total": 1,
                "steps_completed": 1,
            },
        )
        self.assertEqual(response.status_code, 201)

        response = self.client.get("/api/block-run-history")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["history"][0]["status"], "success")

        response = self.client.delete("/api/block-run-history")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["history"], [])

    def test_camera_proxy_keeps_ros_topic_slashes_for_web_video_server(self):
        class Upstream:
            headers = {"Content-Type": "multipart/x-mixed-replace;boundary=frame"}

            def __init__(self):
                self.reads = 0

            def read(self, _size):
                self.reads += 1
                return b"--frame\r\n" if self.reads == 1 else b""

            def close(self):
                pass

        with patch.object(self.flask_app.urllib.request, "urlopen", return_value=Upstream()) as open_stream:
            response = self.client.get("/api/camera/stream?topic=/depth_camera/image_raw")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b"--frame\r\n")
            url = open_stream.call_args.args[0]
            self.assertIn("topic=/depth_camera/image_raw", url)
            self.assertNotIn("%2Fdepth_camera", url)


if __name__ == "__main__":
    unittest.main()
