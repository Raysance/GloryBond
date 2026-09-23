import datetime
import unittest

from local_debugger import import_hok_module


ZTIME = import_hok_module("ztime")


class TimeBoundaryTests(unittest.TestCase):
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
