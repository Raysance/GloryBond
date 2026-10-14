import unittest

from local_debugger import import_hok_module


HERO_HANDLERS = import_hok_module("event_handlers.hero")
ZFUNC = import_hok_module("zfunc")


class EventStub:
    def __init__(self, text):
        self.text = text

    def get_plaintext(self):
        return self.text

    def get_user_id(self):
        return "10001"


class HeroEventHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_single_player_single_hero_dispatch(self):
        originals = {
            name: getattr(ZFUNC, name)
            for name in (
                "qid2nick",
                "extract_name",
                "extract_heroname",
                "single_player_single_hero_process",
            )
        }
        calls = []
        ZFUNC.qid2nick = lambda qid: "alice"
        ZFUNC.extract_name = lambda value, precise=False: "alice"
        ZFUNC.extract_heroname = lambda value, precise=False: (123, "赵云")
        ZFUNC.single_player_single_hero_process = lambda *args: calls.append(args) or "ok"
        try:
            result = await HERO_HANDLERS.hero_statistics_reply(
                EventStub("#我的赵云")
            )
        finally:
            for name, value in originals.items():
                setattr(ZFUNC, name, value)

        self.assertEqual(result, "ok")
        self.assertEqual(calls, [("alice", 123, "赵云")])

    async def test_group_all_heroes_keeps_season_flag(self):
        original_qid2nick = ZFUNC.qid2nick
        original_process = ZFUNC.mult_player_mult_hero_process
        calls = []
        ZFUNC.qid2nick = lambda qid: "alice"
        ZFUNC.mult_player_mult_hero_process = lambda **kwargs: calls.append(kwargs) or "ok"
        try:
            result = await HERO_HANDLERS.hero_statistics_reply(
                EventStub("#群u的英雄 本赛季")
            )
        finally:
            ZFUNC.qid2nick = original_qid2nick
            ZFUNC.mult_player_mult_hero_process = original_process

        self.assertEqual(result, "ok")
        self.assertEqual(calls, [{"this_season": True}])

    async def test_honor_power_dispatch_returns_identity_for_error_context(self):
        original_realname = ZFUNC.qid2realname
        original_process = ZFUNC.honor_power_query_process
        ZFUNC.qid2realname = lambda qid: "alice"
        ZFUNC.honor_power_query_process = lambda name, query: f"{name}:{query}"
        try:
            realname, reply = await HERO_HANDLERS.honor_power_reply(
                EventStub("#战力查询 赵云 成都")
            )
        finally:
            ZFUNC.qid2realname = original_realname
            ZFUNC.honor_power_query_process = original_process

        self.assertEqual(realname, "alice")
        self.assertEqual(reply, "alice:#战力查询 赵云 成都")


if __name__ == "__main__":
    unittest.main()
