import unittest

from local_debugger import import_hok_module


BATTLE_HISTORY = import_hok_module("business.battle_history")
ZFUNC = import_hok_module("zfunc")


def _role(role_id, user_id, name, camp, hero, result_stats):
    return {
        "basicInfo": {
            "roleId": role_id,
            "userId": user_id,
            "roleName": name,
            "acntCamp": camp,
        },
        "battleRecords": {"usedHero": {"heroName": hero}},
        "battleStats": result_stats,
    }


class BattleHistoryTests(unittest.TestCase):
    def test_fetch_battle_retargets_head_for_requested_role(self):
        original_reader = BATTLE_HISTORY.zfile.read_battle_detail
        detail = {
            "battle": {"mapName": "排位赛", "dtEventTime": "2026-09-23"},
            "redTeam": {"acntCamp": 1, "gameResult": 1},
            "blueTeam": {"acntCamp": 2, "gameResult": 2},
            "redRoles": [
                _role(
                    11,
                    101,
                    "Alice",
                    1,
                    "赵云",
                    {
                        "killCnt": 8,
                        "deadCnt": 2,
                        "assistCnt": 6,
                        "gradeGame": "12.3",
                    },
                )
            ],
            "blueRoles": [],
        }
        BATTLE_HISTORY.zfile.read_battle_detail = lambda gameseq: detail
        try:
            result = ZFUNC.fetch_battle("game-1", roleid=11)
        finally:
            BATTLE_HISTORY.zfile.read_battle_detail = original_reader

        self.assertEqual(result["head"]["roleName"], "Alice")
        self.assertEqual(result["head"]["heroName"], "赵云")
        self.assertTrue(result["head"]["gameResult"])
        self.assertEqual(result["head"]["gradeGame"], "12.3")

    def test_analyze_history_aggregates_player_and_hero_metrics(self):
        original_fetch = ZFUNC.fetch_history
        ZFUNC.fetch_history = lambda **kwargs: (
            {
                "alice": [
                    {"Result": "胜利", "HeroName": "赵云", "GameGrade": "10"},
                    {"Result": "失败", "HeroName": "赵云", "GameGrade": "8"},
                    {"Result": "胜利", "HeroName": "韩信", "GameGrade": "12"},
                ]
            },
            7,
        )
        try:
            result = ZFUNC.Analyses.analyze_history(userid=1001)
        finally:
            ZFUNC.fetch_history = original_fetch

        alice = result["alice"]
        self.assertEqual(alice["win_tourna_cnt"], 2)
        self.assertEqual(alice["total_tourna_cnt"], 3)
        self.assertEqual(alice["duration"], 7)
        self.assertEqual(alice["hero_info"]["赵云"][0:2], [1, 2])
        self.assertEqual(alice["hero_info"]["赵云"][4], 9.0)

    def test_intersection_counts_each_shared_game_once(self):
        original_fetch = ZFUNC.fetch_history
        ZFUNC.fetch_history = lambda **kwargs: (
            {
                "alice": [{"GameSeq": "shared"}, {"GameSeq": "solo-a"}],
                "bob": [{"GameSeq": "shared"}, {"GameSeq": "solo-b"}],
            },
            1,
        )
        try:
            result = ZFUNC.Analyses.get_intersection_data(time_gap=7)
        finally:
            ZFUNC.fetch_history = original_fetch

        self.assertEqual(result[frozenset({"alice", "bob"})], 1)


if __name__ == "__main__":
    unittest.main()
