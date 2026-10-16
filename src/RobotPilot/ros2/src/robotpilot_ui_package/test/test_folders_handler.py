import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import yaml

from nav2_msgs.srv import LoadMap
from robotpilot_ui_package.folders_handler import UIFoldersHandler


class FakeFuture:
    def add_done_callback(self, callback):
        self.callback = callback

    def result(self):
        return self.response

    def complete(self, response):
        self.response = response
        self.callback(self)


class FolderHandlerMapSafetyTest(unittest.TestCase):
    def test_project_map_directories_are_listed_and_loaded_after_acknowledgement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            maps = root / "maps"
            mini = maps / "mini"
            mini.mkdir(parents=True)
            (mini / "map.yaml").write_text("image: map.pgm\n")
            (mini / "map.pgm").write_bytes(b"map")
            (mini / "GlobalMap.pcd").write_bytes(b"point cloud")
            incomplete = maps / "incomplete"
            incomplete.mkdir()
            (incomplete / "GlobalMap.pcd").write_bytes(b"point cloud")
            (maps / "linked").symlink_to(mini, target_is_directory=True)
            current = root / "current.yaml"
            current.write_text(yaml.safe_dump({"map_file": "", "route_file": ""}))

            handler = object.__new__(UIFoldersHandler)
            handler.project_maps_folder = str(maps)
            handler.maps_folder = str(maps / "ui")
            handler.routs_folder = str(root / "routes")
            handler.route_store_folder = str(root / "stored_routes")
            handler.current_files = str(current)
            handler.dict_cmd = {"map": "mini"}
            handler._map_switch_pending = False
            handler._pub = Mock()
            handler._pub_nav_data = Mock()
            handler.WP_req_callback = Mock()
            handler.get_logger = Mock(return_value=Mock())
            future = FakeFuture()
            handler.change_map_cli = Mock()
            handler.change_map_cli.service_is_ready.return_value = True
            handler.change_map_cli.call_async.return_value = future

            catalog = json.loads(handler.get_paths())
            self.assertEqual(catalog["project_maps"], [
                {"name": "incomplete", "loadable": False, "has_point_cloud": True},
                {"name": "mini", "loadable": True, "has_point_cloud": True},
            ])
            self.assertTrue(handler.change_project_map_func())
            self.assertEqual(yaml.safe_load(current.read_text())["map_file"], "")
            self.assertEqual(handler.change_map_cli.call_async.call_args.args[0].map_url,
                             str(mini / "map.yaml"))

            response = LoadMap.Response()
            response.result = LoadMap.Response.RESULT_SUCCESS
            future.complete(response)
            self.assertEqual(yaml.safe_load(current.read_text())["map_file"],
                             str(mini / "map.yaml"))
            self.assertEqual(json.loads(handler.get_paths())["active_files"]["project_map"],
                             "mini")

            handler.dict_cmd = {"map": "incomplete"}
            self.assertFalse(handler.change_project_map_func())
            handler.dict_cmd = {"map": "../mini"}
            self.assertFalse(handler.change_project_map_func())

    def test_map_selection_changes_only_after_server_acknowledgement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            maps = root / "maps"
            routes = root / "routes"
            (maps / "office").mkdir(parents=True)
            (maps / "office" / "floor-2.yaml").write_text("image: floor-2.pgm\n")
            route_dir = routes / "office" / "floor-2"
            route_dir.mkdir(parents=True)
            (route_dir / "route-a.csv").write_text("0,0,0\n")
            (maps / "office" / "floor-3.yaml").write_text("image: floor-3.pgm\n")
            current = root / "current.yaml"
            previous_map = str(maps / "office" / "floor-1.yaml")
            current.write_text(
                yaml.safe_dump({"map_file": previous_map, "route_file": "old.csv"})
            )

            handler = object.__new__(UIFoldersHandler)
            handler.maps_folder = str(maps)
            handler.routs_folder = str(routes)
            handler.current_files = str(current)
            handler.dict_cmd = {"group": "office", "map": "floor-2"}
            handler._map_switch_pending = False
            handler._pub = Mock()
            handler._pub_nav_data = Mock()
            handler.WP_req_callback = Mock()
            handler.get_logger = Mock(return_value=Mock())
            future = FakeFuture()
            handler.change_map_cli = Mock()
            handler.change_map_cli.service_is_ready.return_value = True
            handler.change_map_cli.call_async.return_value = future

            self.assertTrue(handler.change_map_func())
            self.assertEqual(yaml.safe_load(current.read_text())["map_file"], previous_map)

            response = LoadMap.Response()
            response.result = LoadMap.Response.RESULT_SUCCESS
            future.complete(response)
            selection = yaml.safe_load(current.read_text())
            self.assertEqual(selection["map_file"], str(maps / "office" / "floor-2.yaml"))
            self.assertEqual(selection["route_file"], str(route_dir / "route-a.csv"))

            failed_future = FakeFuture()
            handler.dict_cmd = {"group": "office", "map": "floor-3"}
            handler.change_map_cli.call_async.return_value = failed_future
            self.assertTrue(handler.change_map_func())
            response = LoadMap.Response()
            response.result = LoadMap.Response.RESULT_INVALID_MAP_DATA
            failed_future.complete(response)
            selection = yaml.safe_load(current.read_text())
            self.assertEqual(selection["map_file"], str(maps / "office" / "floor-2.yaml"))
            self.assertEqual(selection["route_file"], str(route_dir / "route-a.csv"))

    def test_active_map_cannot_be_renamed_or_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            maps = root / "maps"
            routes = root / "routes"
            map_group = maps / "office"
            map_group.mkdir(parents=True)
            (map_group / "floor-1.yaml").write_text("image: floor-1.pgm\n")
            (map_group / "floor-1.pgm").write_bytes(b"map")
            route_map = routes / "office" / "floor-1"
            route_map.mkdir(parents=True)
            current = root / "current.yaml"
            current.write_text(yaml.safe_dump({"map_file": str(map_group / "floor-1.yaml")}))

            handler = object.__new__(UIFoldersHandler)
            handler.maps_folder = str(maps)
            handler.routs_folder = str(routes)
            handler.current_files = str(current)
            handler.dict_cmd = {"group": "office", "map_old": "floor-1", "map_new": "renamed"}
            handler._pub = Mock()
            handler.get_logger = Mock(return_value=Mock())

            self.assertFalse(handler.rename_map_func())
            self.assertTrue((map_group / "floor-1.yaml").is_file())

            handler.dict_cmd = {"group": "office", "map": "floor-1"}
            self.assertFalse(handler.delete_map_func())
            self.assertTrue((map_group / "floor-1.yaml").is_file())
            self.assertIn("Map deletion failed:", handler._pub.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
