import unittest
from unittest.mock import patch

from local_debugger import import_hok_module


ZFUNC = import_hok_module("zfunc")


class BattleSummonerSkillTests(unittest.TestCase):
    def test_enriches_matching_player_skill_from_cached_detail(self):
        payload = {
            "btlist": {"list": [{"gameSeq": "123"}]},
        }
        detail = {
            "redRoles": [
                {
                    "basicInfo": {"roleId": "42"},
                    "battleRecords": {
                        "skill": {
                            "skillId": 80115,
                            "skillIcon": "https://example.com/flash.png",
                            "skillName": "闪现",
                        }
                    },
                }
            ],
            "blueRoles": [],
        }

        with patch("hok.zfile.read_battle_detail", return_value=detail):
            ZFUNC._enrich_battle_list_skills_from_cache(payload, "42")

        self.assertEqual(payload["btlist"]["list"][0]["skill"]["skillName"], "闪现")

    def test_preserves_skill_already_returned_by_list_api(self):
        original_skill = {
            "skillId": 80102,
            "skillIcon": "https://example.com/heal.png",
            "skillName": "治疗术",
        }
        payload = {
            "btlist": {"list": [{"gameSeq": "123", "skill": original_skill.copy()}]},
        }

        with patch("hok.zfile.read_battle_detail") as read_detail:
            ZFUNC._enrich_battle_list_skills_from_cache(payload, "42")

        read_detail.assert_not_called()
        self.assertEqual(payload["btlist"]["list"][0]["skill"], original_skill)


if __name__ == "__main__":
    unittest.main()
