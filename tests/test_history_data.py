import unittest

from local_debugger import import_hok_module


HISTORY_DATA = import_hok_module("business.history_data")
ZFUNC = import_hok_module("zfunc")


class HistoryDataTests(unittest.TestCase):
    def test_fetch_history_prefers_postgres_with_normalized_range(self):
        original_fetch = HISTORY_DATA.zdb.fetch_history
        calls = []
        expected = ({"alice": [{"GameSeq": "1"}]}, 1)
        HISTORY_DATA.zdb.fetch_history = lambda **kwargs: calls.append(kwargs) or expected
        try:
            result = ZFUNC.fetch_history(
                userid=1001,
                start_date=HISTORY_DATA.ztime.str_to_time("2026-09-01"),
                end_date=HISTORY_DATA.ztime.str_to_time("2026-09-02"),
                filter_official=False,
            )
        finally:
            HISTORY_DATA.zdb.fetch_history = original_fetch

        self.assertEqual(result, expected)
        self.assertEqual(calls[0]["userid"], 1001)
        self.assertFalse(calls[0]["filter_official"])

    def test_database_failure_aggregates_json_archives_and_filters_player(self):
        originals = {
            "fetch": HISTORY_DATA.zdb.fetch_history,
            "dates": HISTORY_DATA.zfile.list_history_archive_dates_descending,
            "read": HISTORY_DATA.zfile.read_history_archive_date,
            "official": ZFUNC.check_btl_official,
            "log": ZFUNC.log_message,
            "users": HISTORY_DATA.userlist,
        }
        archives = {
            "2026-09-22": [
                {
                    "key": "alice",
                    "details": [
                        {"GameSeq": "old", "MapName": "排位赛"},
                        {"GameSeq": "new", "MapName": "娱乐模式"},
                    ],
                },
                {
                    "key": "bob",
                    "details": [{"GameSeq": "bob", "MapName": "排位赛"}],
                },
            ],
            "2026-09-21": [
                {
                    "key": "alice",
                    "details": [{"GameSeq": "older", "MapName": "巅峰赛"}],
                }
            ],
        }
        HISTORY_DATA.zdb.fetch_history = lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("database unavailable")
        )
        HISTORY_DATA.zfile.list_history_archive_dates_descending = lambda: list(
            archives
        )
        HISTORY_DATA.zfile.read_history_archive_date = lambda target_date: archives[
            target_date
        ]
        ZFUNC.check_btl_official = lambda map_name: map_name != "娱乐模式"
        ZFUNC.log_message = lambda *args, **kwargs: None
        HISTORY_DATA.userlist = {"alice": 1001, "bob": 1002}
        try:
            result, duration = ZFUNC.fetch_history(
                userid=1001,
                start_date=HISTORY_DATA.ztime.str_to_time("2026-09-20"),
                end_date=HISTORY_DATA.ztime.str_to_time("2026-09-23"),
            )
        finally:
            HISTORY_DATA.zdb.fetch_history = originals["fetch"]
            HISTORY_DATA.zfile.list_history_archive_dates_descending = originals["dates"]
            HISTORY_DATA.zfile.read_history_archive_date = originals["read"]
            ZFUNC.check_btl_official = originals["official"]
            ZFUNC.log_message = originals["log"]
            HISTORY_DATA.userlist = originals["users"]

        self.assertEqual(duration, 2)
        self.assertEqual(
            [item["GameSeq"] for item in result["alice"]],
            ["old", "older"],
        )
        self.assertNotIn("bob", result)


if __name__ == "__main__":
    unittest.main()
