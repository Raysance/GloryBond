import unittest

from local_debugger import import_hok_module


REPORTS = import_hok_module("event_handlers.player_reports")
ZFUNC = import_hok_module("zfunc")


class FakeEvent:
    def __init__(self, text, *, group_id=None):
        self.text = text
        if group_id is not None:
            self.group_id = group_id

    def get_plaintext(self):
        return self.text

    def get_user_id(self):
        return "1001"


class PlayerReportEventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.originals = {
            "online": ZFUNC.online_process,
            "nick": ZFUNC.qid2nick,
            "greeting": ZFUNC.generate_greeting,
            "rank": ZFUNC.rnk_process,
            "single": ZFUNC.single_process,
            "detail": ZFUNC.btldetail_process,
            "view": ZFUNC.view_process,
        }

    def tearDown(self):
        ZFUNC.online_process = self.originals["online"]
        ZFUNC.qid2nick = self.originals["nick"]
        ZFUNC.generate_greeting = self.originals["greeting"]
        ZFUNC.rnk_process = self.originals["rank"]
        ZFUNC.single_process = self.originals["single"]
        ZFUNC.btldetail_process = self.originals["detail"]
        ZFUNC.view_process = self.originals["view"]

    async def test_online_normalizes_legacy_text_and_tuple_results(self):
        ZFUNC.online_process = lambda: "在线正文"
        self.assertEqual(
            await REPORTS.online_reply(),
            {"text": "在线正文", "error_report": ""},
        )
        ZFUNC.online_process = lambda: ("在线正文", "错误汇总")
        self.assertEqual(
            await REPORTS.online_reply(),
            {"text": "在线正文", "error_report": "错误汇总"},
        )

    async def test_ranking_keeps_caller_debug_and_greeting_contract(self):
        calls = []
        ZFUNC.qid2nick = lambda user_id: "Alice"
        ZFUNC.generate_greeting = lambda: "晚上好"
        ZFUNC.rnk_process = lambda **kwargs: calls.append(kwargs) or [
            "排行正文",
            set(),
            "错误汇总",
        ]

        result = await REPORTS.ranking_reply(FakeEvent("#排行", group_id=123))

        self.assertEqual(result["text"], "Alice 晚上好\n排行正文")
        self.assertEqual(result["error_report"], "错误汇总")
        self.assertEqual(result["group_id"], 123)
        self.assertTrue(calls[0]["debug"])
        self.assertEqual(calls[0]["caller"], "Alice")

    async def test_single_summary_and_last_battle_keep_two_stage_contract(self):
        ZFUNC.qid2nick = lambda user_id: "Alice"
        ZFUNC.single_process = lambda message: [
            "单人正文",
            set(),
            False,
            {"gameseq": "1"},
            42,
        ]
        ZFUNC.btldetail_process = lambda **kwargs: (
            "单局正文",
            "/tmp/battle.png",
            "排位赛",
        )

        summary = await REPORTS.single_summary_reply(
            FakeEvent("#我的战报", group_id=123)
        )
        battle = await REPORTS.single_last_battle_reply(summary)

        self.assertEqual(summary["text"], "单人正文")
        self.assertEqual(summary["battle_roleid"], 42)
        self.assertEqual(battle["text"], "单局正文")
        self.assertEqual(battle["image_path"], "/tmp/battle.png")

    async def test_view_suffix_selects_explicit_or_default_days(self):
        calls = []
        ZFUNC.view_process = lambda **kwargs: calls.append(kwargs) or "视图"

        await REPORTS.battle_view_reply(FakeEvent("#查看-30天"))
        await REPORTS.battle_view_reply(FakeEvent("#查看"))

        self.assertEqual(calls[0]["time_gap"], 30)
        self.assertEqual(calls[1]["time_gap"], REPORTS.analyze_time_gap)


if __name__ == "__main__":
    unittest.main()
