from datetime import datetime, timezone
import json
import tempfile
import unittest
from pathlib import Path

from robotpilot_ui_package.recording_maintenance import (
    prune_finished_recordings,
)


class RecordingMaintenanceTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name) / "recordings"
        self.root.mkdir()
        self.index = self.root / "index.json"
        self.now = datetime(2026, 10, 8, tzinfo=timezone.utc)

    def tearDown(self):
        self.directory.cleanup()

    def _write_index(self, entries):
        self.index.write_text(json.dumps(entries), encoding="utf-8")

    def test_prunes_only_expired_finished_indexed_recordings(self):
        entries = [
            {
                "id": "old-complete",
                "status": "complete",
                "endedAt": "2026-01-01T00:00:00+00:00",
            },
            {
                "id": "recent",
                "status": "complete",
                "endedAt": "2026-10-01T00:00:00+00:00",
            },
            {
                "id": "active",
                "status": "recording",
                "startedAt": "2025-01-01T00:00:00+00:00",
            },
            {
                "id": "interrupted",
                "status": "interrupted",
                "startedAt": "2025-01-01T00:00:00+00:00",
            },
            {"id": "bad-time", "status": "complete", "endedAt": "unknown"},
            {
                "id": "../../outside",
                "status": "complete",
                "endedAt": "2026-01-01T00:00:00+00:00",
            },
        ]
        self._write_index(entries)
        old_bag = self.root / "old-complete"
        old_bag.mkdir()
        (old_bag / "metadata.yaml").write_text("ok", encoding="utf-8")
        recent_bag = self.root / "recent"
        recent_bag.mkdir()

        removed = prune_finished_recordings(
            self.root, self.index, 30, now=self.now
        )

        self.assertEqual(removed, ["old-complete"])
        self.assertFalse(old_bag.exists())
        self.assertTrue(recent_bag.is_dir())
        self.assertEqual(
            [entry["id"] for entry in json.loads(self.index.read_text())],
            ["recent", "active", "interrupted", "bad-time", "../../outside"],
        )
        self.assertEqual(self.index.stat().st_mode & 0o777, 0o600)

    def test_symlinked_bag_and_disabled_policy_are_preserved(self):
        outside = Path(self.directory.name) / "outside"
        outside.mkdir()
        marker = outside / "keep.txt"
        marker.write_text("preserve", encoding="utf-8")
        bag_link = self.root / "linked"
        bag_link.symlink_to(outside, target_is_directory=True)
        entry = {
            "id": "linked",
            "status": "complete",
            "endedAt": "2026-01-01T00:00:00+00:00",
        }
        self._write_index([entry])

        self.assertEqual(
            prune_finished_recordings(self.root, self.index, 30, now=self.now),
            [],
        )
        self.assertTrue(marker.exists())
        self.assertEqual(json.loads(self.index.read_text()), [entry])

        self.assertEqual(
            prune_finished_recordings(self.root, self.index, 0, now=self.now),
            [],
        )
        self.assertTrue(bag_link.is_symlink())

    def test_invalid_retention_and_index_path_are_rejected(self):
        with self.assertRaises(ValueError):
            prune_finished_recordings(self.root, self.index, -1, now=self.now)

        external_index = Path(self.directory.name) / "index.json"
        external_index.write_text("[]", encoding="utf-8")
        with self.assertRaises(ValueError):
            prune_finished_recordings(
                self.root, external_index, 30, now=self.now
            )


if __name__ == "__main__":
    unittest.main()
