import unittest

from local_debugger import import_hok_module


ZFILE = import_hok_module("zfile")
ZFUNC = import_hok_module("zfunc")


class PeakRankTests(unittest.TestCase):
    def setUp(self):
        self.original_dates = ZFILE.list_history_dates_descending
        self.original_reader = ZFILE.read_history_date
        self.requested_start_date = None

        def fake_dates(start_date=None):
            self.requested_start_date = start_date
            return ["2026-08-20", "2026-08-19"]

        ZFILE.list_history_dates_descending = fake_dates

    def tearDown(self):
        ZFILE.list_history_dates_descending = self.original_dates
        ZFILE.read_history_date = self.original_reader

    def test_uses_each_players_latest_local_peak_score(self):
        payloads = {
            "2026-08-20": [
                {
                    "key": "alpha",
                    "nickname": "Alpha Game Name",
                    "details": [
                        {"PeakGradeAfterGame": 1600, "GameTime_Timestamp": 10},
                        {"PeakGradeAfterGame": 1580, "GameTime_Timestamp": 20},
                    ],
                },
                {"key": "beta", "details": [{"PeakGradeAfterGame": -1}]},
            ],
            "2026-08-19": [
                {
                    "key": "alpha",
                    "details": [{"PeakGradeAfterGame": 2200, "GameTime_Timestamp": 99}],
                },
                {
                    "key": "beta",
                    "nickname": "Beta",
                    "details": [{"PeakGradeAfterGame": "1900", "GameTime_Timestamp": 30}],
                },
            ],
        }
        ZFILE.read_history_date = lambda target_date: payloads[target_date]

        result = ZFUNC.peak_rank_process(player_names=["alpha", "beta"])

        self.assertIn("1. Beta  1900", result)
        self.assertIn("2. Alpha Game Name  1580", result)
        self.assertNotIn("2200", result)
        self.assertNotIn("仅本地记录", result)
        self.assertNotIn("2026-08", result)
        self.assertEqual(self.requested_start_date, ZFUNC.this_season_start_date)

    def test_ignores_invalid_values_and_reports_empty_local_data(self):
        ZFILE.read_history_date = lambda target_date: [
            {
                "key": "alpha",
                "details": [
                    {"PeakGradeAfterGame": -1},
                    {"PeakGradeAfterGame": None},
                    {"PeakGradeAfterGame": "not-a-score"},
                ],
            }
        ]

        result = ZFUNC.peak_rank_process(player_names=["alpha"])

        self.assertEqual(result, "【巅峰排名】\n本地历史 JSON 中暂无有效巅峰数据")


if __name__ == "__main__":
    unittest.main()
