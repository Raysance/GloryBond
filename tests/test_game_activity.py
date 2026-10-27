import unittest

from local_debugger import import_hok_module


GAME_ACTIVITY = import_hok_module("business.game_activity")
GEN_GAMETIME = import_hok_module("tools.gen_gametime_table")
ZAPI = import_hok_module("zapi")
ZFUNC = import_hok_module("zfunc")


class GameActivityTests(unittest.TestCase):
    def setUp(self):
        self.originals = {
            "userlist": ZFUNC.userlist,
            "steam_userlist": ZFUNC.steam_userlist,
            "namenick": ZFUNC.namenick,
            "sameuser": getattr(ZFUNC, "sameuser", {}),
            "confs": ZFUNC.confs,
            "fetch": ZFUNC.fetch_history,
            "steam": ZAPI.steam_api_recent_games,
            "gen": GEN_GAMETIME.gen,
        }
        ZFUNC.userlist = {"alice": 1001}
        ZFUNC.steam_userlist = {"alice": "steam-1"}
        ZFUNC.namenick = {"alice": "Alice"}
        ZFUNC.sameuser = {}
        ZFUNC.confs = {"Steam": {"api_key": "test-key"}}

    def tearDown(self):
        ZFUNC.userlist = self.originals["userlist"]
        ZFUNC.steam_userlist = self.originals["steam_userlist"]
        ZFUNC.namenick = self.originals["namenick"]
        ZFUNC.sameuser = self.originals["sameuser"]
        ZFUNC.confs = self.originals["confs"]
        ZFUNC.fetch_history = self.originals["fetch"]
        ZAPI.steam_api_recent_games = self.originals["steam"]
        GEN_GAMETIME.gen = self.originals["gen"]

    def test_recent_summary_combines_hok_and_steam_hours(self):
        ZFUNC.fetch_history = lambda **kwargs: (
            {
                "alice": [
                    {"Duration_Second": 3600},
                    {"Duration_Second": 1800},
                ]
            },
            1,
        )
        ZAPI.steam_api_recent_games = lambda api_key, steam_id: [
            {"name": "Game A", "playtime_2weeks": 90}
        ]

        result = ZFUNC.recentgames_process("alice")

        self.assertIn("🎮 Alice 最近2周的游戏时长", result)
        self.assertIn("👑 王者荣耀: 1.5h", result)
        self.assertIn("♨️ Game A: 1.5h", result)
        self.assertIn("📊 总计时长：3.0h", result)
        self.assertIn("📈 占所有玩家总时长：100.0%", result)

    def test_recent_share_includes_hok_and_steam_only_players(self):
        ZFUNC.userlist = {"alice": 1001, "bob": 1002}
        ZFUNC.steam_userlist = {"alice": "steam-1", "carol": "steam-3"}
        calls = []

        def fetch(**kwargs):
            calls.append(kwargs)
            return {
                "alice": [{"Duration_Second": 3600}],
                "bob": [{"Duration_Second": 7200}],
                "unconfigured": [{"Duration_Second": 360000}],
            }, 1

        ZFUNC.fetch_history = fetch
        ZAPI.steam_api_recent_games = lambda api_key, steam_id: [
            {"name": "Game A", "playtime_2weeks": 60}
        ]

        result = ZFUNC.recentgames_process("alice")

        self.assertIn("📊 总计时长：2.0h", result)
        self.assertIn("📈 占所有玩家总时长：40.0%", result)
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0]["filter_official"])
        self.assertNotIn("userid", calls[0])

    def test_recent_share_uses_unrounded_hours(self):
        ZFUNC.userlist = {"alice": 1001, "bob": 1002}
        ZFUNC.steam_userlist = {}
        ZFUNC.fetch_history = lambda **kwargs: (
            {"alice": [{"Duration_Second": 61}], "bob": [{"Duration_Second": 122}]},
            1,
        )

        result = ZFUNC.recentgames_process("alice")

        self.assertIn("👑 王者荣耀: 0.0h", result)
        self.assertIn("📈 占所有玩家总时长：33.3%", result)

    def test_recent_share_handles_no_playtime(self):
        ZFUNC.fetch_history = lambda **kwargs: ({}, 0)
        ZAPI.steam_api_recent_games = lambda *args: []

        result = ZFUNC.recentgames_process("alice")

        self.assertIn("最近2周没有游戏记录", result)
        self.assertIn("📈 占所有玩家总时长：0.0%", result)

    def test_rank_keeps_game_order_and_image_contract(self):
        generated = []
        ZFUNC.fetch_history = lambda **kwargs: (
            {"alice": [{"Duration_Second": 7200}]},
            1,
        )
        ZAPI.steam_api_recent_games = lambda api_key, steam_id: [
            {"name": "Game A", "playtime_2weeks": 60}
        ]
        GEN_GAMETIME.gen = lambda rows, games, path, title: generated.append(
            (rows, games, path, title)
        )

        text, picture_path = ZFUNC.gametime_rank_process(days=14)

        self.assertEqual(text, "")
        self.assertEqual(generated[0][1], ["王者荣耀", "Game A"])
        self.assertEqual(generated[0][2], picture_path)
        self.assertTrue(picture_path.endswith(".png"))
        self.assertEqual(generated[0][3], "最近14天游戏时长排行")

    def test_rank_preserves_steam_failure_context(self):
        ZFUNC.userlist = {}
        ZAPI.steam_api_recent_games = lambda api_key, steam_id: (_ for _ in ()).throw(
            RuntimeError("steam unavailable")
        )

        with self.assertRaisesRegex(
            Exception,
            "steam_recent_games_error: alice",
        ):
            ZFUNC.gametime_rank_process()


if __name__ == "__main__":
    unittest.main()
