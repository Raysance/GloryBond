import unittest

from local_debugger import import_hok_module


SPOILER = import_hok_module("event_handlers.spoiler")
ZFUNC = import_hok_module("zfunc")


class FakeEvent:
    def __init__(self, text):
        self.text = text

    def get_plaintext(self):
        return self.text

    def get_user_id(self):
        return "1001"


class SpoilerEventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.originals = {
            "nick": ZFUNC.qid2nick,
            "extract": ZFUNC.extract_name,
            "official": ZFUNC.wzry_get_official,
            "spoiler": ZFUNC.spoiler_process,
            "users": SPOILER.userlist,
            "roles": SPOILER.roleidlist,
            "names": SPOILER.namenick,
            "time": SPOILER.ztime.current_timestamp,
            "cache": getattr(SPOILER.dmc, "spoiler_cache", None),
        }
        ZFUNC.qid2nick = lambda user_id: "alice"
        SPOILER.userlist = {"alice": 11}
        SPOILER.roleidlist = {"alice": 22}
        SPOILER.namenick = {"alice": "Alice"}
        SPOILER.ztime.current_timestamp = lambda: 1000
        SPOILER.dmc.spoiler_cache = None

    def tearDown(self):
        ZFUNC.qid2nick = self.originals["nick"]
        ZFUNC.extract_name = self.originals["extract"]
        ZFUNC.wzry_get_official = self.originals["official"]
        ZFUNC.spoiler_process = self.originals["spoiler"]
        SPOILER.userlist = self.originals["users"]
        SPOILER.roleidlist = self.originals["roles"]
        SPOILER.namenick = self.originals["names"]
        SPOILER.ztime.current_timestamp = self.originals["time"]
        SPOILER.dmc.spoiler_cache = self.originals["cache"]

    async def test_named_query_requires_recognized_player(self):
        ZFUNC.extract_name = lambda text: None

        result = await SPOILER.prepare_spoiler_request(FakeEvent("#未知的预言"))

        self.assertEqual(result, {"kind": "text", "text": "没有提到玩家名字哦"})

    async def test_named_query_caches_active_battle(self):
        ZFUNC.extract_name = lambda text: "alice"
        ZFUNC.wzry_get_official = lambda **kwargs: {
            "isGaming": True,
            "gaming": {"battleId": "battle-1"},
        }

        result = await SPOILER.prepare_spoiler_request(FakeEvent("#alice的预言"))

        self.assertEqual(result["kind"], "ready")
        self.assertEqual(result["battle_id"], "battle-1")
        self.assertEqual(result["roleid"], 22)
        self.assertEqual(SPOILER.dmc.spoiler_cache["time"], 1000)

    async def test_expired_cache_is_rejected(self):
        SPOILER.dmc.spoiler_cache = {
            "time": 699,
            "realname": "alice",
            "battleID": "old",
        }

        result = await SPOILER.prepare_spoiler_request(FakeEvent("#预言"))

        self.assertEqual(result, {"kind": "text", "text": "不存在待预言对局"})

    async def test_run_dispatches_cached_identifiers(self):
        calls = []
        ZFUNC.spoiler_process = lambda *args: calls.append(args) or (
            "预言正文",
            "/tmp/prediction.png",
        )

        result = await SPOILER.run_spoiler_request(
            {"battle_id": "battle-1", "roleid": 22, "userid": 11}
        )

        self.assertEqual(calls, [("battle-1", 22, 11)])
        self.assertEqual(result["image_path"], "/tmp/prediction.png")


if __name__ == "__main__":
    unittest.main()
