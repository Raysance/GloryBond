import unittest

from local_debugger import import_hok_module


ACTIVITY = import_hok_module("event_handlers.activity")
EVENT_RULES = import_hok_module("event_rules")
ZFUNC = import_hok_module("zfunc")


class FakeEvent:
    def __init__(self, text, user_id="100"):
        self.text = text
        self.user_id = user_id

    def get_plaintext(self):
        return self.text

    def get_user_id(self):
        return self.user_id


class ActivityEventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.originals = {
            "validated": EVENT_RULES.get_validated_name,
            "nick": ZFUNC.qid2nick,
            "power_rank": ZFUNC.power_rank_process,
            "recent_power": ZFUNC.recent_power_process,
            "extract": ZFUNC.extract_name,
            "time_rank": ZFUNC.gametime_rank_process,
            "recent_games": ZFUNC.recentgames_process,
        }
        ZFUNC.qid2nick = lambda user_id: "alice"

    def tearDown(self):
        EVENT_RULES.get_validated_name = self.originals["validated"]
        ZFUNC.qid2nick = self.originals["nick"]
        ZFUNC.power_rank_process = self.originals["power_rank"]
        ZFUNC.recent_power_process = self.originals["recent_power"]
        ZFUNC.extract_name = self.originals["extract"]
        ZFUNC.gametime_rank_process = self.originals["time_rank"]
        ZFUNC.recentgames_process = self.originals["recent_games"]

    async def test_power_rank_dispatches_image_result(self):
        ZFUNC.power_rank_process = lambda days: ("", "/tmp/power.png")

        result = await ACTIVITY.battle_power_reply(FakeEvent("#底蕴排行"))

        self.assertEqual(
            result,
            {"kind": "image", "text": "", "image_path": "/tmp/power.png"},
        )

    async def test_individual_power_uses_validated_player(self):
        EVENT_RULES.get_validated_name = lambda event: "alice"
        calls = []
        ZFUNC.recent_power_process = lambda realname, days: calls.append(
            (realname, days)
        ) or "底蕴统计"

        result = await ACTIVITY.battle_power_reply(FakeEvent("#我的底蕴"))

        self.assertEqual(calls, [("alice", 7)])
        self.assertEqual(result, {"kind": "text", "text": "底蕴统计"})

    async def test_game_time_rank_dispatches_image_result(self):
        ZFUNC.gametime_rank_process = lambda: ("", "/tmp/time.png")

        result = await ACTIVITY.game_time_reply(FakeEvent("#时长排名"))

        self.assertEqual(result["kind"], "image")
        self.assertEqual(result["image_path"], "/tmp/time.png")

    async def test_game_time_reports_unrecognized_player(self):
        ZFUNC.extract_name = lambda **kwargs: None

        result = await ACTIVITY.game_time_reply(FakeEvent("#未知玩家时长"))

        self.assertEqual(result, {"kind": "text", "text": "未识别到玩家名字"})


if __name__ == "__main__":
    unittest.main()
