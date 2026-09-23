import json
import unittest

from local_debugger import import_hok_module


BATTLE_POWER = import_hok_module("business.battle_power")
GEN_COPLAYER = import_hok_module("tools.gen_coplayer_analyses")
ZFILE = import_hok_module("zfile")
ZFUNC = import_hok_module("zfunc")


class FakeEvaluatorPool:
    def __init__(self):
        self.records = []
        self.trim_calls = []

    def rpush(self, key, value):
        self.records.append((key, value))

    def ltrim(self, key, start, end):
        self.trim_calls.append((key, start, end))


class FakeCoPlayerProcess:
    instances = []

    def __init__(self):
        self.players = []
        self.generated = None
        self.__class__.instances.append(self)

    def add_player(self, **kwargs):
        self.players.append(kwargs)

    def gen(self, path, title, subtitle):
        self.generated = (path, title, subtitle)
        return path, True


def _unauthorized_player(index, hero_name):
    return {
        "basicInfo": {
            "roleId": index,
            "userId": index + 100,
            "roleName": f"玩家{index}",
            "isGameAuth": False,
        },
        "heroBehavior": {
            "winNum": 0,
            "loseNum": 0,
            "avgScore": "0",
            "winRate": "0%",
        },
        "battleRecords": {
            "usedHero": {
                "heroName": hero_name,
                "heroIcon": f"https://example/{index}.png",
            },
            "position": index % 5,
        },
        "battleStats": {"fightPower": 0},
    }


class BattlePowerTests(unittest.TestCase):
    def test_history_helpers_keep_message_stats_and_rounding_contract(self):
        payload = {
            "mySide": {"level": 12.3456, "tier": 6.789},
            "opSide": {"level": 10.111, "tier": 5.432},
            "matchup": {"winRate": 0.625, "sampleMatches": 16},
        }

        message = ZFUNC.BattlePowerHistory.message(payload)
        stats = ZFUNC.BattlePowerHistory.stats(payload)

        self.assertIn("实力天平倾斜度：2.23", message)
        self.assertIn("英雄对位胜率：62.5%（近30天，16局）", message)
        self.assertEqual(stats["my_side_level"], 12.3456)
        self.assertEqual(
            ZFUNC.BattlePowerHistory.rounded({"items": [1.23456]}),
            {"items": [1.235]},
        )
        self.assertEqual(
            ZFUNC.BattlePowerHistory.path("123"),
            ZFILE.battle_power_history_path("123"),
        )

    def test_redis_evaluator_write_stays_in_zfunc_facade(self):
        original_pool = ZFUNC.dmc.BtlAnalyzeEvaluatorPool
        original_limit = getattr(ZFUNC.dmc, "BtlAnalyzeEvaluatorMaxRecords", None)
        pool = FakeEvaluatorPool()
        ZFUNC.dmc.BtlAnalyzeEvaluatorPool = pool
        ZFUNC.dmc.BtlAnalyzeEvaluatorMaxRecords = 3
        try:
            ZFUNC.record_battle_evaluator({"gameseq": "123"})
        finally:
            ZFUNC.dmc.BtlAnalyzeEvaluatorPool = original_pool
            if original_limit is None:
                delattr(ZFUNC.dmc, "BtlAnalyzeEvaluatorMaxRecords")
            else:
                ZFUNC.dmc.BtlAnalyzeEvaluatorMaxRecords = original_limit

        self.assertEqual(json.loads(pool.records[0][1]), {"gameseq": "123"})
        self.assertEqual(pool.trim_calls[0][1:], (-3, -1))

    def test_spoiler_analysis_keeps_ten_player_output_without_api_fetches(self):
        originals = {
            "generator": GEN_COPLAYER.CoPlayerProcess,
            "matchup": ZFUNC.hero_matchup_process,
            "official": ZFUNC.wzry_get_official,
        }
        FakeCoPlayerProcess.instances = []
        GEN_COPLAYER.CoPlayerProcess = FakeCoPlayerProcess
        ZFUNC.hero_matchup_process = lambda my_side, op_side: {
            "winRate": None,
            "sampleMatches": 0,
        }
        ZFUNC.wzry_get_official = lambda **kwargs: self.fail(
            f"unexpected official API call: {kwargs}"
        )
        red_roles = [_unauthorized_player(index, "赵云") for index in range(1, 6)]
        blue_roles = [_unauthorized_player(index, "韩信") for index in range(6, 11)]
        spoiler = {
            "head": {"gameResult": True, "acntCamp": 1},
            "redTeam": {"acntCamp": 1},
            "blueTeam": {"acntCamp": 2},
            "redRoles": red_roles,
            "blueRoles": blue_roles,
        }
        try:
            text, image_path, stats, power_data = ZFUNC.coplayer_process(
                -1,
                -1,
                "battle-1",
                -1,
                1,
                spoiler,
                return_power_data=True,
            )
        finally:
            GEN_COPLAYER.CoPlayerProcess = originals["generator"]
            ZFUNC.hero_matchup_process = originals["matchup"]
            ZFUNC.wzry_get_official = originals["official"]

        self.assertIn("我方底蕴：unknown", text)
        self.assertEqual(image_path, ZFILE.battle_power_image_path())
        self.assertEqual(stats["my_side_level"], 0)
        self.assertEqual(len(power_data["players"]), 10)
        self.assertEqual(len(FakeCoPlayerProcess.instances[0].players), 10)
        self.assertEqual(FakeCoPlayerProcess.instances[0].generated[1], "对局预言")


if __name__ == "__main__":
    unittest.main()
