import unittest

from local_debugger import import_hok_module


ZFUNC = import_hok_module("zfunc")


class DailyNotificationTests(unittest.TestCase):
    def setUp(self):
        self.originals = {
            "rank": ZFUNC.rnk_process,
            "representative": ZFUNC.get_daily_representative_battle,
            "log": ZFUNC.log_message,
        }
        self.logs = []
        ZFUNC.log_message = lambda message, *args: self.logs.append(message)

    def tearDown(self):
        ZFUNC.rnk_process = self.originals["rank"]
        ZFUNC.get_daily_representative_battle = self.originals["representative"]
        ZFUNC.log_message = self.originals["log"]

    def test_keeps_report_then_representative_tuple_order(self):
        ZFUNC.rnk_process = lambda **kwargs: ["排行正文", set(), ""]
        ZFUNC.get_daily_representative_battle = lambda: (
            "代表局正文",
            "/tmp/battle.png",
            {"AiCommentary": "AI 文案"},
        )

        result = ZFUNC.notify_msg_impl()

        self.assertEqual(
            result,
            [
                "今日王者战报(每日23:30推送)：\n排行正文",
                ("代表局正文", "/tmp/battle.png", "AI 文案"),
            ],
        )

    def test_rank_failure_returns_traceback_only(self):
        ZFUNC.rnk_process = lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("rank failed")
        )

        result = ZFUNC.notify_msg_impl()

        self.assertEqual(len(result), 1)
        self.assertIn("RuntimeError: rank failed", result[0])

    def test_representative_failure_keeps_main_report(self):
        ZFUNC.rnk_process = lambda **kwargs: ["排行正文", set(), ""]
        ZFUNC.get_daily_representative_battle = lambda: (_ for _ in ()).throw(
            RuntimeError("representative failed")
        )

        result = ZFUNC.notify_msg_impl()

        self.assertEqual(
            result,
            ["今日王者战报(每日23:30推送)：\n排行正文"],
        )
        self.assertTrue(
            any("GET_REPRESENTATIVE_BATTLE_ERROR" in item for item in self.logs)
        )


if __name__ == "__main__":
    unittest.main()
