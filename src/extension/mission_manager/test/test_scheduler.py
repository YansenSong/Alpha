import unittest

from mission_manager.scheduler import next_run_at


class ScheduleTimeTest(unittest.TestCase):
    def test_daily_schedule_uses_named_timezone(self):
        self.assertEqual(
            next_run_at("2026-10-07T23:59:00Z", "daily", "Asia/Shanghai", "08:00"),
            "2026-10-08T00:00:00+00:00",
        )

    def test_weekly_schedule_selects_next_configured_weekday(self):
        self.assertEqual(
            next_run_at(
                "2026-10-08T00:00:00Z", "weekly", "Asia/Shanghai", "08:00",
                weekdays=[0],
            ),
            "2026-10-12T00:00:00+00:00",
        )

    def test_once_schedule_does_not_replay_a_past_date(self):
        self.assertIsNone(
            next_run_at(
                "2026-10-08T00:00:00Z", "once", "Asia/Shanghai", "08:00",
                start_date="2026-10-07",
            )
        )

    def test_nonexistent_dst_wall_time_is_skipped(self):
        self.assertEqual(
            next_run_at(
                "2026-03-08T00:00:00Z", "daily", "America/New_York", "02:30",
            ),
            "2026-03-09T06:30:00+00:00",
        )

    def test_ambiguous_dst_wall_time_uses_first_occurrence(self):
        self.assertEqual(
            next_run_at(
                "2026-11-01T00:00:00Z", "daily", "America/New_York", "01:30",
            ),
            "2026-11-01T05:30:00+00:00",
        )

    def test_unknown_timezone_and_bad_weekdays_fail_validation(self):
        with self.assertRaises(ValueError):
            next_run_at("2026-10-08T00:00:00Z", "daily", "Mars/Olympus", "08:00")
        with self.assertRaises(ValueError):
            next_run_at(
                "2026-10-08T00:00:00Z", "weekly", "UTC", "08:00", weekdays=[7]
            )


if __name__ == "__main__":
    unittest.main()
