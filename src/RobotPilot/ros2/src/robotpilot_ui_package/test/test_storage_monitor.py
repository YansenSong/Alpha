import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from robotpilot_ui_package.storage_monitor import storage_report


class StorageMonitorTest(unittest.TestCase):
    def test_reports_capacity_and_uses_configured_thresholds(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "robotpilot_ui_package.storage_monitor.os.statvfs"
            ) as statvfs:
                statvfs.return_value.f_blocks = 100
                statvfs.return_value.f_frsize = 100
                statvfs.return_value.f_bfree = 15
                statvfs.return_value.f_bavail = 10
                result = storage_report(
                    [("data", directory)], warning_percent=80,
                    critical_percent=85,
                )[0]

        self.assertEqual(result["used_percent"], 90.0)
        self.assertEqual(result["available_bytes"], 1000)
        self.assertEqual(result["level"], "critical")

    def test_missing_configured_directory_uses_existing_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-created" / "data"
            with patch(
                "robotpilot_ui_package.storage_monitor.os.statvfs"
            ) as statvfs:
                statvfs.return_value.f_blocks = 100
                statvfs.return_value.f_frsize = 1
                statvfs.return_value.f_bfree = 100
                statvfs.return_value.f_bavail = 90
                result = storage_report([("data", path)])[0]

        statvfs.assert_called_once_with(Path(directory))
        self.assertEqual(result["path"], str(path))
        self.assertEqual(result["level"], "ok")

    def test_rejects_invalid_threshold_order(self):
        with self.assertRaises(ValueError):
            storage_report([], warning_percent=90, critical_percent=90)


if __name__ == "__main__":
    unittest.main()
