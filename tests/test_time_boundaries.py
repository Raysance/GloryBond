import datetime
import unittest
from unittest.mock import patch

from local_debugger import import_hok_module


ZTIME = import_hok_module("ztime")


class TimeBoundaryTests(unittest.TestCase):
    def test_relative_post_time_handles_unit_boundaries_and_clock_skew(self):
        now = 1800000000
        with patch.object(ZTIME, 'current_epoch_seconds', return_value=now):
            for age, expected in [(-60, '刚刚'), (0, '刚刚'), (59, '刚刚'), (60, '1分钟前'),
                                  (3599, '59分钟前'), (3600, '1小时前'), (86399, '23小时前'),
                                  (86400, '1天前'), (30 * 86400, '1个月前'), (365 * 86400, '1年前')]:
                with self.subTest(age=age):
                    self.assertEqual(ZTIME.time_ago_text(now - age), expected)
            self.assertEqual(ZTIME.time_ago_text(None), '时间未知')

    def test_minutes_until_window_end_uses_nearest_daily_boundary(self):
        original_time = ZTIME.time_r
        try:
            ZTIME.time_r = lambda: datetime.datetime(2026, 9, 23, 3, 35, 0)
            self.assertEqual(
                ZTIME.minutes_until_daily_window_end(3, 30, window_minutes=10),
                6,
            )

            ZTIME.time_r = lambda: datetime.datetime(2026, 9, 23, 23, 55, 0)
            self.assertEqual(
                ZTIME.minutes_until_daily_window_end(0, 0, window_minutes=10),
                16,
            )
        finally:
            ZTIME.time_r = original_time


if __name__ == "__main__":
    unittest.main()
