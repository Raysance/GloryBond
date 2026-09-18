import unittest

from local_debugger import import_hok_module


ZFUNC = import_hok_module("zfunc")


def player(position, hero_id):
    return {
        "battleRecords": {
            "position": position,
            "usedHero": {"heroId": hero_id},
        }
    }


class BattleMatchupTests(unittest.TestCase):
    def test_prefers_exact_lineup_when_it_has_samples(self):
        calls = []

        def matchup_api(camp1, camp2, days):
            calls.append((camp1, camp2, days))
            return {"camp1WinRate": 0.625, "totalMatchesFound": 8}

        result = ZFUNC.hero_matchup_process(
            [player(0, 105), player(1, 106)],
            [player(0, 107), player(1, 108)],
            matchup_api=matchup_api,
        )

        self.assertEqual(result["queryMode"], "exact")
        self.assertEqual(result["sampleMatches"], 8)
        self.assertEqual(result["winRate"], 0.625)
        self.assertEqual(len(calls), 1)

    def test_falls_back_to_sample_weighted_lane_pairs(self):
        responses = iter(
            [
                {"camp1WinRate": 0, "totalMatchesFound": 0},
                {"camp1WinRate": 0.6, "totalMatchesFound": 30},
                {"camp1WinRate": 0.3, "totalMatchesFound": 10},
            ]
        )

        result = ZFUNC.hero_matchup_process(
            [player("0", "105"), player(1, 106)],
            [player(0, 107), player(1, 108)],
            matchup_api=lambda *args, **kwargs: next(responses),
        )

        self.assertEqual(result["queryMode"], "lane_pairs")
        self.assertEqual(result["queryCount"], 2)
        self.assertEqual(result["sampleMatches"], 40)
        self.assertAlmostEqual(result["winRate"], 0.525)

    def test_api_failure_does_not_break_battle_power(self):
        def failed_api(*args, **kwargs):
            raise RuntimeError("service unavailable")

        result = ZFUNC.hero_matchup_process(
            [player(0, 105)],
            [player(0, 107)],
            matchup_api=failed_api,
        )

        self.assertEqual(result["queryMode"], "error")
        self.assertIsNone(result["winRate"])

    def test_lineup_ai_receives_only_hero_and_position_context(self):
        captured = {}

        def ai_func(user_query, msg_type):
            captured["query"] = user_query[0]
            captured["type"] = msg_type
            return "我方前排更稳，对方中野爆发更高，前期河道团将决定节奏。"

        result = ZFUNC.battle_lineup_ai_process(
            [{"position": 3, "heroName": "赵云"}, {"position": 0, "heroName": "廉颇"}],
            [{"position": None, "heroName": "小乔"}],
            ai_func=ai_func,
        )

        self.assertEqual(captured["type"], "battle_lineup")
        self.assertEqual(captured["query"], "我方：对抗路廉颇、打野赵云；对方：未知分路小乔。")
        self.assertIn("河道团", result)


if __name__ == "__main__":
    unittest.main()
