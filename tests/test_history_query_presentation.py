import unittest

from local_debugger import import_hok_module


HISTORY_QUERY = import_hok_module("business.history_query")


class HistoryQueryPresentationTests(unittest.TestCase):
    def test_statistics_prefix_matches_existing_output(self):
        prefix = HISTORY_QUERY.format_history_query_prefix(
            "本赛季赵云",
            {
                "total": 2,
                "wins": 1,
                "win_rate": 50,
                "avg_grade": 9.25,
                "total_k": 10,
                "total_d": 4,
                "total_a": 12,
                "avg_kda": 5.5,
            },
        )

        self.assertEqual(
            prefix,
            "🔍查询条件：本赛季赵云\n\n"
            "📊 统计概览 (2场)：\n"
            "胜率: 50.0% (1胜1负)\n"
            "平均评分: 9.2\n"
            "场均KDA: 5.0/2.0/6.0 (5.50)\n\n",
        )

    def test_match_packing_resolves_nickname_from_battle(self):
        detail = {
            "GameSeq": "123",
            "GameTime_Timestamp": 100,
            "Duration_Second": 900,
            "HeroName": "赵云",
            "MapName": "排位赛",
            "KillCnt": 5,
            "DeadCnt": 2,
            "AssistCnt": 8,
            "Result": "胜利",
            "GameGrade": 10.5,
            "Others": "MVP",
        }
        battle = {
            "redRoles": [
                {"basicInfo": {"roleId": 88, "roleName": "游戏昵称"}}
            ],
            "blueRoles": [],
        }

        packed = HISTORY_QUERY.pack_history_query_matches(
            [[detail, "alice"]],
            {"alice": 88},
            lambda gameseq: battle,
        )

        self.assertEqual(len(packed), 1)
        self.assertEqual(packed[0]["Nickname"], "游戏昵称")
        self.assertEqual(packed[0]["GameSeq"], "123")
        self.assertEqual(packed[0]["roleId"], 88)


if __name__ == "__main__":
    unittest.main()
