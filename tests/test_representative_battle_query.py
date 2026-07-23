import datetime
import unittest

from local_debugger import import_hok_module


ZFUNC = import_hok_module("zfunc")
ZTIME = import_hok_module("ztime")


class RepresentativeBattleQueryTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.datetime(2026, 7, 23, 12, 0, 0)

    def test_natural_language_relative_dates(self):
        cases = {
            "代表局": "2026-07-23",
            "今日代表局": "2026-07-23",
            "昨天的代表局": "2026-07-22",
            "前天代表局": "2026-07-21",
            "大前天代表局": "2026-07-20",
            "三天前代表局": "2026-07-20",
            "12天前的代表局": "2026-07-11",
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                self.assertEqual(
                    ZTIME.parse_representative_battle_date(query, now=self.now),
                    expected,
                )

    def test_natural_language_explicit_dates(self):
        cases = {
            "查询2026年4月9日代表局": "2026-04-09",
            "2026-4-9代表局": "2026-04-09",
            "2026/04/09的代表局": "2026-04-09",
            "7月2号代表局": "2026-07-02",
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                self.assertEqual(
                    ZTIME.parse_representative_battle_date(query, now=self.now),
                    expected,
                )

    def test_invalid_explicit_date_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "无效日期"):
            ZTIME.parse_representative_battle_date("2026年2月30日代表局", now=self.now)

    def test_public_query_drops_debug_payload(self):
        original_getter = ZFUNC.get_daily_representative_battle
        original_parser = ZTIME.parse_representative_battle_date
        try:
            ZTIME.parse_representative_battle_date = lambda query: "2026-07-22"
            ZFUNC.get_daily_representative_battle = lambda target_date: (
                "正式文字",
                "/tmp/representative.png",
                {"debug": "不得返回"},
            )

            result = ZFUNC.representative_battle_query_impl("昨天代表局")

            self.assertEqual(
                result,
                {
                    "target_date": "2026-07-22",
                    "found": True,
                    "text": "正式文字",
                    "image_path": "/tmp/representative.png",
                },
            )
        finally:
            ZFUNC.get_daily_representative_battle = original_getter
            ZTIME.parse_representative_battle_date = original_parser


if __name__ == "__main__":
    unittest.main()
