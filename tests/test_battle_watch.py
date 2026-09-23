import unittest

from local_debugger import import_hok_module


ZFUNC = import_hok_module("zfunc")


def player(role_id, user_id, role_name, hero_name="赵云"):
    return {
        "roleId": role_id,
        "userId": user_id,
        "roleInfo": {"roleName": role_name},
        "win": 6,
        "lost": 4,
        "winRate": "60%",
        "heroName": hero_name,
        "heroIcon": "https://example/hero.png",
        "heroFightValue": 9000,
    }


class BattleWatchConversionTests(unittest.TestCase):
    def test_converts_players_and_detects_target_camp(self):
        payload = {
            "battleInfo": {
                "camp1": [player(1, 11, "玩家一")],
                "camp2": [player(2, 22, "玩家二")],
                "roleInfo": {"roleId": 2},
                "battleDetailUrl": "https://example/detail?acntCamp=1",
            }
        }

        result = ZFUNC.watchbattleinfo_to_coplayer_res(payload)

        self.assertEqual(result["head"]["acntCamp"], 2)
        self.assertTrue(result["redRoles"][0]["basicInfo"]["isGameAuth"])
        self.assertEqual(
            result["blueRoles"][0]["battleStats"]["fightPower"],
            9000,
        )

    def test_marks_unapproved_player_and_falls_back_to_url_camp(self):
        payload = {
            "data": {
                "battleInfo": {
                    "camp1": [player(0, 0, "未授权游戏信息")],
                    "camp2": [],
                    "roleInfo": {"roleId": 99},
                    "battleDetailUrl": "https://example/detail?foo=1&acntCamp=2",
                }
            }
        }

        result = ZFUNC.watchbattleinfo_to_coplayer_res(payload)

        self.assertEqual(result["head"]["acntCamp"], 2)
        self.assertFalse(result["redRoles"][0]["basicInfo"]["isGameAuth"])

    def test_missing_required_numeric_field_raises(self):
        broken = player(1, 11, "玩家一")
        broken["heroFightValue"] = None
        payload = {
            "battleInfo": {
                "camp1": [broken],
                "camp2": [],
                "roleInfo": {"roleId": 1},
                "battleDetailUrl": "https://example/detail?acntCamp=1",
            }
        }

        with self.assertRaisesRegex(
            ValueError,
            "missing required field: heroFightValue",
        ):
            ZFUNC.watchbattleinfo_to_coplayer_res(payload)


if __name__ == "__main__":
    unittest.main()
