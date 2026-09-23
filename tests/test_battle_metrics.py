import unittest

from local_debugger import import_hok_module


ZFUNC = import_hok_module("zfunc")


def role(role_id, camp, grade, money, equips=None):
    return {
        "basicInfo": {"roleId": role_id, "acntCamp": camp},
        "battleStats": {"gradeGame": grade, "money": money},
        "battleRecords": {"finalEquips": equips or []},
    }


class BattleMetricTests(unittest.TestCase):
    def test_contribution_factor_uses_team_share(self):
        detail = {
            "redRoles": [
                role("1", 1, 10, 10000),
                role("2", 1, 5, 5000),
            ],
            "blueRoles": [],
        }
        factor = ZFUNC.calculate_battle_contribution_factor(detail, roleid="1")
        expected = (5 * 10 / 15) * ((5 * 10000 / 15000) ** -0.5)
        self.assertAlmostEqual(factor, expected)

    def test_support_equipment_applies_existing_adjustment(self):
        detail = {
            "redRoles": [
                role("1", 1, 10, 10000, [{"equipName": "极影"}]),
                role("2", 1, 5, 5000),
            ],
            "blueRoles": [],
        }
        adjusted = ZFUNC.calculate_battle_contribution_factor(detail, roleid="1")
        detail["redRoles"][0]["battleRecords"]["finalEquips"] = []
        plain = ZFUNC.calculate_battle_contribution_factor(detail, roleid="1")
        self.assertAlmostEqual(adjusted, plain * 0.9)

    def test_official_average_fetches_details_through_zfunc_facade(self):
        original_fetch = ZFUNC.fetch_battle
        ZFUNC.fetch_battle = lambda gameseq, roleid=0: {
            "redRoles": [role(str(roleid), 1, 10, 10000)],
            "blueRoles": [],
        }
        try:
            result = ZFUNC.calculate_official_battle_contribution_average(
                [{"MapName": "排位赛", "GameSeq": "g1"}],
                roleid="1",
            )
        finally:
            ZFUNC.fetch_battle = original_fetch

        self.assertEqual(result, round(5 * (5 ** -0.5), 3))


if __name__ == "__main__":
    unittest.main()
