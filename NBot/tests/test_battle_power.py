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

    def test_process_reuses_saved_history_without_recomputing(self):
        history = ZFUNC.BattlePowerHistory
        originals = {
            "load": history.load,
            "saved_response": history.saved_response,
            "coplayer": ZFUNC.coplayer_process,
        }
        saved = {"GameSeq": "123", "players": []}
        history.load = staticmethod(lambda gameseq: saved)
        history.saved_response = staticmethod(
            lambda payload, gen_image, with_ai_analysis=False: (
                payload["GameSeq"],
                gen_image,
                with_ai_analysis,
            )
        )
        ZFUNC.coplayer_process = lambda *args, **kwargs: self.fail(
            "saved history should bypass recomputation"
        )
        try:
            result = ZFUNC.battle_power_process(
                1,
                2,
                "123",
                3,
                4,
                gen_image=False,
                with_ai_analysis=True,
            )
        finally:
            history.load = originals["load"]
            history.saved_response = originals["saved_response"]
            ZFUNC.coplayer_process = originals["coplayer"]

        self.assertEqual(result, ("123", False, True))

    def test_history_save_accepts_postgres_only_write_without_json_archive(self):
        history = ZFUNC.BattlePowerHistory
        originals = {
            "official": ZFUNC.check_btl_official,
            "writer": ZFILE.writerl,
            "db_exists": BATTLE_POWER.zdb.battle_power_exists,
            "file_exists": ZFILE.file_exist,
        }
        writes = []
        ZFUNC.check_btl_official = lambda _map_name: True
        ZFILE.writerl = lambda path, payload: writes.append((path, payload))
        BATTLE_POWER.zdb.battle_power_exists = lambda _gameseq: True
        ZFILE.file_exist = lambda _path: False
        try:
            saved_path = history.save(
                {
                    "GameSeq": "1790140310",
                    "mapName": "排位赛",
                    "mySide": {"level": 1.23456},
                }
            )
        finally:
            ZFUNC.check_btl_official = originals["official"]
            ZFILE.writerl = originals["writer"]
            BATTLE_POWER.zdb.battle_power_exists = originals["db_exists"]
            ZFILE.file_exist = originals["file_exists"]

        self.assertEqual(saved_path, ZFILE.battle_power_history_path("1790140310"))
        self.assertEqual(writes[0][1]["mySide"]["level"], 1.235)

    def test_pending_candidate_selects_latest_valid_unprocessed_battle(self):
        original_fetch = ZFUNC.fetch_history
        original_skip = ZFUNC.BattlePowerHistory.should_skip_candidate
        now = BATTLE_POWER.ztime.time_r()
        older = int(BATTLE_POWER.ztime.time_delta(now, -2).timestamp())
        newer = int(BATTLE_POWER.ztime.time_delta(now, -1).timestamp())
        ZFUNC.fetch_history = lambda **kwargs: (
            {
                "alice": [
                    {
                        "GameSeq": "old",
                        "GameTime_Timestamp": older,
                        "Params": {"gameSvrId": 1},
                    },
                    {
                        "GameSeq": "new",
                        "GameTime_Timestamp": newer,
                        "Params": {"gameSvrId": 2},
                    },
                ]
            },
            2,
        )
        ZFUNC.BattlePowerHistory.should_skip_candidate = staticmethod(
            lambda gameseq, excluded: gameseq in excluded
        )
        original_roleids = BATTLE_POWER.roleidlist
        BATTLE_POWER.roleidlist = {"alice": 1001}
        try:
            candidate = ZFUNC.find_pending_battle_power_candidate(
                days=7,
                excluded_gameseqs={"old"},
            )
        finally:
            ZFUNC.fetch_history = original_fetch
            ZFUNC.BattlePowerHistory.should_skip_candidate = original_skip
            BATTLE_POWER.roleidlist = original_roleids

        self.assertEqual(candidate["GameSeq"], "new")
        self.assertEqual(candidate["roleid"], 1001)


if __name__ == "__main__":
    unittest.main()
