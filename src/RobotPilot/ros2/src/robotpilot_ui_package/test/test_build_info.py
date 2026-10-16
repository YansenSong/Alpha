import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from robotpilot_ui_package.build_info import get_build_info


class BuildInfoTest(unittest.TestCase):
    def test_reports_release_metadata_and_frontend_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            share = Path(directory)
            static = share / "static" / "app"
            static.mkdir(parents=True)
            (share / "package.xml").write_text(
                "<package><version>1.2.3</version></package>", encoding="utf-8"
            )
            index = static / "index.html"
            index.write_text("<html>build</html>", encoding="utf-8")
            with patch.dict(os.environ, {
                "ROBOTPILOT_BUILD_VERSION": "1.2.3-rc1",
                "ROBOTPILOT_BUILD_COMMIT": "abc1234",
                "ROBOTPILOT_BUILD_TIME": "2026-10-08T00:00:00Z",
                "ROS_DISTRO": "jazzy",
                "ROBOT_MODE": "simulation",
                "BATTERY_SOURCE": "sim",
            }):
                info = get_build_info(share)

        self.assertEqual(info["version"], "1.2.3-rc1")
        self.assertEqual(info["package_version"], "1.2.3")
        self.assertEqual(info["commit"], "abc1234")
        self.assertEqual(info["ros_distro"], "jazzy")
        self.assertEqual(info["robot_mode"], "simulation")
        self.assertEqual(
            info["frontend_build"],
            hashlib.sha256(b"<html>build</html>").hexdigest()[:16],
        )
        self.assertNotIn("path", info)

    def test_missing_artifacts_are_reported_as_unknown(self):
        info = get_build_info()
        self.assertEqual(info["version"], "unknown")
        self.assertEqual(info["frontend_build"], "unknown")
