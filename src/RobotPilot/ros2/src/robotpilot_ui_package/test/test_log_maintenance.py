from datetime import datetime, timezone
import os
import tempfile
import unittest
from pathlib import Path

from robotpilot_ui_package.log_maintenance import prune_expired_logs


class LogMaintenanceTest(unittest.TestCase):
    def test_prunes_only_expired_regular_logs_under_the_root(self):
        now = datetime(2026, 10, 8, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "logs"
            root.mkdir()
            old_log = root / "old.log"
            old_log.write_text("expired", encoding="utf-8")
            os.utime(old_log, (now.timestamp() - 40 * 86400,) * 2)
            recent_log = root / "recent.log"
            recent_log.write_text("recent", encoding="utf-8")
            other_file = root / "old.txt"
            other_file.write_text("keep", encoding="utf-8")
            os.utime(other_file, (now.timestamp() - 40 * 86400,) * 2)

            outside = Path(directory) / "outside.log"
            outside.write_text("outside", encoding="utf-8")
            os.utime(outside, (now.timestamp() - 40 * 86400,) * 2)
            (root / "linked.log").symlink_to(outside)
            outside_directory = Path(directory) / "outside-directory"
            outside_directory.mkdir()
            (outside_directory / "linked-dir.log").write_text("keep", encoding="utf-8")
            (root / "linked-directory").symlink_to(
                outside_directory, target_is_directory=True
            )

            removed = prune_expired_logs(root, 30, now=now)

            self.assertEqual(removed, ["old.log"])
            self.assertFalse(old_log.exists())
            self.assertTrue(recent_log.exists())
            self.assertTrue(other_file.exists())
            self.assertTrue(outside.exists())
            self.assertTrue((root / "linked.log").is_symlink())
            self.assertTrue((outside_directory / "linked-dir.log").exists())

    def test_disabled_retention_and_scan_limit_preserve_remaining_files(self):
        now = datetime(2026, 10, 8, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "a.log"
            first.write_text("old", encoding="utf-8")
            second = root / "b.log"
            second.write_text("old", encoding="utf-8")
            old = now.timestamp() - 40 * 86400
            os.utime(first, (old, old))
            os.utime(second, (old, old))

            self.assertEqual(prune_expired_logs(root, 0, now=now), [])
            self.assertEqual(
                prune_expired_logs(root, 30, now=now, max_files=1), ["a.log"]
            )
            self.assertTrue(second.exists())

    def test_rejects_invalid_retention_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                prune_expired_logs(directory, -1)
            with self.assertRaises(ValueError):
                prune_expired_logs(directory, 30, max_files=0)


if __name__ == "__main__":
    unittest.main()
