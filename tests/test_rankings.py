import unittest

from local_debugger import import_hok_module


RANKINGS = import_hok_module("business.rankings")
ZFUNC = import_hok_module("zfunc")


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.originals = {
            "userlist": RANKINGS.userlist,
            "roleidlist": RANKINGS.roleidlist,
            "wzry_data": ZFUNC.wzry_data,
            "history_artifact": ZFUNC.WebArtifacts.__dict__["make_hash"],
            "history_link": ZFUNC.WebArtifacts.__dict__["history_route_link"],
            "daily_writer": RANKINGS.write_daily_history_export,
            "web_writer": RANKINGS.write_web_history_payload,
        }
        RANKINGS.userlist = {"alice": 11, "bob": 22}
        RANKINGS.roleidlist = {"alice": 111, "bob": 222}
        ZFUNC.WebArtifacts.make_hash = staticmethod(lambda seed=None: "fixed")
        ZFUNC.WebArtifacts.history_route_link = staticmethod(
            lambda *args, **kwargs: "https://example/rank"
        )
        self.daily_writes = []
        self.web_writes = []
        RANKINGS.write_daily_history_export = (
            lambda date_text, payload: self.daily_writes.append((date_text, payload))
        )
        RANKINGS.write_web_history_payload = (
            lambda key, payload: self.web_writes.append((key, payload))
        )

    def tearDown(self):
        RANKINGS.userlist = self.originals["userlist"]
        RANKINGS.roleidlist = self.originals["roleidlist"]
        ZFUNC.wzry_data = self.originals["wzry_data"]
        ZFUNC.WebArtifacts.make_hash = self.originals["history_artifact"]
        ZFUNC.WebArtifacts.history_route_link = self.originals["history_link"]
        RANKINGS.write_daily_history_export = self.originals["daily_writer"]
        RANKINGS.write_web_history_payload = self.originals["web_writer"]

    def test_partial_player_failure_keeps_available_ranking(self):
        def wzry_data(*, realname):
            if realname == "bob":
                raise RuntimeError("unavailable")
            return {
                "key": "alice",
                "nickname": "Alice",
                "star_up": 3,
                "today_num": 2,
            }

        ZFUNC.wzry_data = wzry_data
        message, highlights, error_report = ZFUNC.rnk_process(
            "$",
            caller="tester",
            show_zero=False,
        )

        self.assertIn("今日上分最佳👆：Alice", message)
        self.assertIn("https://example/rank", message)
        self.assertEqual(highlights, {"Alice", ""})
        self.assertIn("排行遍历异常汇总 count=1", error_report)
        self.assertIn("rank.wzry_data", error_report)
        self.assertEqual(len(self.daily_writes), 1)
        self.assertEqual(self.web_writes[0][0], "fixed")
        self.assertNotIn("key", self.web_writes[0][1][0])

    def test_all_player_failures_keep_existing_error_response(self):
        ZFUNC.wzry_data = lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("offline")
        )

        message, highlights, error_report = ZFUNC.rnk_process("$")

        self.assertIn("王者荣耀数据源错误，暂无可用排行数据", message)
        self.assertEqual(highlights, [])
        self.assertIn("排行遍历异常汇总 count=2", error_report)
        self.assertEqual(self.daily_writes, [])
        self.assertEqual(self.web_writes, [])


if __name__ == "__main__":
    unittest.main()
