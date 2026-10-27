import json
import unittest
from unittest.mock import patch

from local_debugger import import_hok_module


HISTORY_QUERY = import_hok_module("business.history_query")
ZAPI = import_hok_module("zapi")


class HistoryQueryModeTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            self.battle("-900000000000000001", "共鸣之战", ""),
            self.battle("-900000000000000002", "共鸣之战", "MVP"),
            self.battle("3", "排位赛", "MVP"),
            self.battle("4", "无限乱斗", None),
            self.battle("5", "梦境大乱斗", ""),
        ]

    @staticmethod
    def battle(sequence, mode, others):
        return {
            "GameSeq": sequence, "MapName": mode, "Others": others,
            "Result": "胜利", "GameGrade": 0, "GradeMissing": True,
            "KillCnt": 1, "DeadCnt": 2, "AssistCnt": 3,
        }

    def query(self, **conditions):
        conditions = {"PlayerName": "示例玩家65", **conditions}
        with patch.object(ZAPI, "ai_api", return_value=json.dumps(conditions)) as ai, \
             patch.object(HISTORY_QUERY, "extract_name", return_value="alice"), \
             patch.object(HISTORY_QUERY, "namenick", {"alice": "示例玩家65"}), \
             patch.object(HISTORY_QUERY, "fetch_history", return_value=(
                 {"alice": self.rows + self.rows[:1], "bob": self.rows}, 2,
             )) as fetch:
            result = HISTORY_QUERY.history_query_handler("#查询示例玩家65的共鸣之战")
        self.assertFalse(fetch.call_args.kwargs["filter_official"])
        self.assertIn("共鸣之战", ai.call_args.args[0])
        return result

    def test_misclassified_mode_is_promoted_from_other_keywords(self):
        target, matches, description, stats = self.query(Others=["共鸣之战"])

        self.assertEqual(target["MapName"], "共鸣之战")
        self.assertFalse(target["Others"])
        self.assertEqual([row["GameSeq"] for row, _ in matches], [
            "-900000000000000001", "-900000000000000002",
        ])
        self.assertTrue(all(player == "alice" for _, player in matches))
        self.assertEqual(description, "玩家: 示例玩家65 | 地图: 共鸣之战")
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["score_count"], 0)

    def test_mode_and_achievement_remain_independent_conditions(self):
        target, matches, _, _ = self.query(Others=["共鸣之战", "MVP"])

        self.assertEqual(target["Others"], ["MVP"])
        self.assertEqual([row["GameSeq"] for row, _ in matches], ["-900000000000000002"])

    def test_explicit_mode_removes_duplicated_other_keyword(self):
        _, matches, _, _ = self.query(MapName="共鸣之战", Others=["共鸣之战"])

        self.assertEqual(len(matches), 2)

    def test_entertainment_group_includes_resonance(self):
        _, matches, _, _ = self.query(MapName="娱乐模式")

        self.assertEqual({row["MapName"] for row, _ in matches}, {
            "共鸣之战", "无限乱斗", "梦境大乱斗",
        })
        self.assertEqual(len(matches), 4)

    def test_achievement_filter_tolerates_null_others(self):
        _, matches, _, _ = self.query(Others=["MVP"])

        self.assertEqual({row["GameSeq"] for row, _ in matches}, {
            "-900000000000000002", "3",
        })

    def test_conflicting_mode_and_other_condition_does_not_broaden_query(self):
        _, matches, _, _ = self.query(MapName="排位赛", Others=["共鸣之战"])

        self.assertEqual(matches, [])


if __name__ == "__main__":
    unittest.main()
