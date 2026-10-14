import unittest

from local_debugger import import_hok_module


HERO_PROFILES = import_hok_module("business.hero_profiles")
ZFUNC = import_hok_module("zfunc")


class HeroProfileTests(unittest.TestCase):
    def setUp(self):
        self.originals = {
            "userlist": HERO_PROFILES.userlist,
            "roleidlist": HERO_PROFILES.roleidlist,
            "namenick": HERO_PROFILES.namenick,
            "official": ZFUNC.wzry_get_official,
        }
        HERO_PROFILES.userlist = {"alice": 11}
        HERO_PROFILES.roleidlist = {"alice": 111}
        HERO_PROFILES.namenick = {"alice": "Alice"}

    def tearDown(self):
        HERO_PROFILES.userlist = self.originals["userlist"]
        HERO_PROFILES.roleidlist = self.originals["roleidlist"]
        HERO_PROFILES.namenick = self.originals["namenick"]
        ZFUNC.wzry_get_official = self.originals["official"]

    def test_hero_power_skips_malformed_rows(self):
        captured = []
        ZFUNC.wzry_get_official = lambda **kwargs: captured.append(kwargs) or {
            "heroList": [
                {
                    "basicInfo": {"title": "赵云", "heroFightPower": 9000},
                    "honorTitle": {
                        "desc": {"full": "成都市第10", "abbr": "市第10"},
                        "rank": 10,
                    },
                },
                {"basicInfo": {"title": "损坏数据"}},
            ]
        }

        result = ZFUNC.heropower_process("alice")

        self.assertIn("Alice的战力英雄", result)
        self.assertIn("【赵云】 9000", result)
        self.assertIn("成都市  第 10 名", result)
        self.assertNotIn("损坏数据", result)
        self.assertEqual(
            captured,
            [{"reqtype": "heropower", "userid": 11, "roleid": 111}],
        )

    def test_all_hero_output_keeps_six_item_limit(self):
        ZFUNC.wzry_get_official = lambda **kwargs: {
            "heroList": [
                {
                    "name": f"英雄{index}",
                    "heroFightPower": index,
                    "playNum": index + 1,
                    "winRate": "50%",
                }
                for index in range(8)
            ]
        }

        result = ZFUNC.allhero_process("alice")

        self.assertIn("英雄0", result)
        self.assertIn("英雄5", result)
        self.assertNotIn("英雄6", result)


if __name__ == "__main__":
    unittest.main()
