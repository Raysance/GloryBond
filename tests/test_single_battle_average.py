import unittest

from local_debugger import import_hok_module


ZFUNC = import_hok_module("zfunc")


class SingleBattleAverageTests(unittest.TestCase):
    def test_average_only_includes_official_battles(self):
        details = [
            {"MapName": "排位赛", "GameGrade": 10},
            {"MapName": "巅峰赛", "GameGrade": 12},
            {"MapName": "战队赛", "GameGrade": 8},
            {"MapName": "匹配赛", "GameGrade": 16},
            {"MapName": "王者峡谷", "GameGrade": 18},
        ]

        self.assertEqual(ZFUNC.calculate_official_battle_average(details), 10)

    def test_average_returns_zero_without_official_battles(self):
        details = [
            {"MapName": "匹配赛", "GameGrade": 16},
            {"MapName": "1v1排位", "GameGrade": 12},
        ]

        self.assertEqual(ZFUNC.calculate_official_battle_average(details), 0)


if __name__ == "__main__":
    unittest.main()
