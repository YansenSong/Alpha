import json
import os
import tempfile
import unittest
from pathlib import Path

import rclpy
from nav_msgs.msg import OccupancyGrid
from sensor_msgs.msg import PointCloud2

from mission_manager.map_bundle import MapBundleMonitor, make_manifest, occupancy_map_id


class PublisherSpy:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(json.loads(message.data))


class MapBundleTest(unittest.TestCase):
    def test_manifest_binds_file_checksums_and_rejects_missing_pcd(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "map.pgm").write_bytes(b"P5\n1 1\n255\n\xff")
            (root / "map.yaml").write_text("image: map.pgm\n", encoding="utf-8")
            (root / "GlobalMap.pcd").write_bytes(b"pointcloud")
            first = make_manifest(root / "map.yaml", root / "GlobalMap.pcd", "abcdef123456")
            (root / "GlobalMap.pcd").write_bytes(b"changed pointcloud")
            second = make_manifest(root / "map.yaml", root / "GlobalMap.pcd", "abcdef123456")
            self.assertNotEqual(first["bundle_id"], second["bundle_id"])
            (root / "GlobalMap.pcd").unlink()
            with self.assertRaises(FileNotFoundError):
                make_manifest(root / "map.yaml", root / "GlobalMap.pcd", "abcdef123456")

    def test_monitor_requires_manifest_2d_identity_and_loaded_3d_topic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "map.pgm").write_bytes(b"P5\n1 1\n255\n\xff")
            map_yaml = root / "map.yaml"
            map_yaml.write_text("image: map.pgm\n", encoding="utf-8")
            pcd = root / "GlobalMap.pcd"
            pcd.write_bytes(b"pointcloud")
            grid = OccupancyGrid()
            grid.info.width = 2
            grid.info.height = 2
            grid.info.resolution = 0.05
            grid.info.origin.orientation.w = 1.0
            grid.data = [0, 100, -1, 0]
            map_id = occupancy_map_id(grid)
            manifest = make_manifest(map_yaml, pcd, map_id)
            map_yaml.with_suffix(".bundle.json").write_text(json.dumps(manifest), encoding="utf-8")
            previous_log_dir = os.environ.get("ROS_LOG_DIR")
            os.environ["ROS_LOG_DIR"] = directory
            rclpy.init(args=["--ros-args", "-p", f"map_yaml:={map_yaml}",
                             "-p", f"globalmap_pcd:={pcd}"])
            node = MapBundleMonitor()
            node.pub = PublisherSpy()
            try:
                node.on_map(grid)
                node.publish_status()
                self.assertFalse(node.pub.messages[-1]["ready"])
                cloud = PointCloud2()
                cloud.header.frame_id = "map"
                cloud.width = 1000
                cloud.height = 1
                node.on_global_map(cloud)
                node.get_publishers_info_by_topic = lambda _: [object()]
                node.publish_status()
                self.assertTrue(node.pub.messages[-1]["ready"])
                grid.data[0] = 100
                node.on_map(grid)
                node.publish_status()
                self.assertFalse(node.pub.messages[-1]["ready"])
                self.assertIn("active 2D map", node.pub.messages[-1]["reason"])
            finally:
                node.destroy_node()
                rclpy.shutdown()
                if previous_log_dir is None:
                    os.environ.pop("ROS_LOG_DIR", None)
                else:
                    os.environ["ROS_LOG_DIR"] = previous_log_dir
