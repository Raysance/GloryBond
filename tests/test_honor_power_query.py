import unittest

from local_debugger import import_hok_module


ZAPI = import_hok_module("zapi")
ZFILE = import_hok_module("zfile")
ZFUNC = import_hok_module("zfunc")


class HonorPowerQueryTests(unittest.TestCase):
    def setUp(self):
        self.original_api = ZAPI.wzry_get_official
        self.original_district_reader = ZFILE.read_honor_districts
        self.calls = []
        self.original_roleid = ZFUNC.roleidlist.get("tester")
        ZFUNC.roleidlist["tester"] = 123456
        ZFILE.read_honor_districts = lambda: {
            "data": {
                "list": [
                    {
                        "adcode": 510000,
                        "shortName": "四川",
                        "fullName": "四川省",
                        "list": [
                            {
                                "adcode": 510100,
                                "shortName": "成都市",
                                "fullName": "成都市",
                                "list": [
                                    {
                                        "adcode": 510107,
                                        "shortName": "武侯区",
                                        "fullName": "武侯区",
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        }

        def fake_api(**kwargs):
            self.calls.append(kwargs)
            return {
                "list": [
                    {"rankNo": 99, "rankValue": "13900"},
                    {"rankNo": 100, "rankValue": "13890"},
                ]
            }

        ZAPI.wzry_get_official = fake_api

    def tearDown(self):
        ZAPI.wzry_get_official = self.original_api
        ZFILE.read_honor_districts = self.original_district_reader
        if self.original_roleid is None:
            ZFUNC.roleidlist.pop("tester", None)
        else:
            ZFUNC.roleidlist["tester"] = self.original_roleid

    def test_queries_selected_district_threshold_only(self):
        result = ZFUNC.honor_power_query_process("tester", "帮我查询一下武侯区的火舞战力")

        self.assertIn("【不知火舞战力查询】", result)
        self.assertIn("四川省成都市武侯区", result)
        self.assertIn("上榜战力 13890", result)
        self.assertEqual(
            self.calls,
            [
                {
                    "reqtype": "honorranklist",
                    "roleid": 123456,
                    "heroid": "157",
                    "honor_adcode": 510107,
                },
            ],
        )

    def test_reports_unrecognized_hero_without_api_call(self):
        original_to_pinyin = ZFUNC._to_pinyin
        ZFUNC._to_pinyin = lambda value: str(value)
        try:
            result = ZFUNC.honor_power_query_process("tester", "#战力查询 不存在英雄 武侯区")
        finally:
            ZFUNC._to_pinyin = original_to_pinyin

        self.assertEqual(result, "未识别到英雄，请使用：#战力查询 英雄名 地区名")
        self.assertEqual(self.calls, [])

    def test_supports_pinyin_hero_name_in_any_position(self):
        original_to_pinyin = ZFUNC._to_pinyin
        pinyin_map = {
            "帮我查询武侯区huowu战力": "bangwochaxunwuhouquhuowuzhanli",
            "火舞": "huowu",
            "不知火舞": "buzhihuowu",
        }
        ZFUNC._to_pinyin = lambda value: pinyin_map.get(value, f"nomatch{value}")
        try:
            result = ZFUNC.honor_power_query_process("tester", "帮我查询武侯区huowu战力")
        finally:
            ZFUNC._to_pinyin = original_to_pinyin

        self.assertIn("【不知火舞战力查询】", result)
        self.assertEqual(self.calls[0]["honor_adcode"], 510107)

    def test_prefers_smallest_region_found_anywhere_in_prompt(self):
        district, error = ZFUNC.resolve_honor_district("查询浙江省杭州市萧山区火舞战力", {
            "data": {
                "list": [{
                    "adcode": 330000,
                    "shortName": "浙江",
                    "fullName": "浙江省",
                    "list": [{
                        "adcode": 330100,
                        "shortName": "杭州市",
                        "fullName": "杭州市",
                        "list": [{"adcode": 330109, "shortName": "萧山区", "fullName": "萧山区"}],
                    }],
                }]
            }
        })

        self.assertIsNone(error)
        self.assertEqual(district["adcode"], 330109)

    def test_requires_full_path_for_duplicate_district_name(self):
        payload = {
            "data": {
                "list": [
                    {
                        "adcode": 320000,
                        "shortName": "江苏",
                        "fullName": "江苏省",
                        "list": [{
                            "adcode": 320100,
                            "shortName": "南京市",
                            "fullName": "南京市",
                            "list": [{"adcode": 320106, "shortName": "鼓楼区", "fullName": "鼓楼区"}],
                        }],
                    },
                    {
                        "adcode": 350000,
                        "shortName": "福建",
                        "fullName": "福建省",
                        "list": [{
                            "adcode": 350100,
                            "shortName": "福州市",
                            "fullName": "福州市",
                            "list": [{"adcode": 350102, "shortName": "鼓楼区", "fullName": "鼓楼区"}],
                        }],
                    },
                ]
            }
        }

        district, error = ZFUNC.resolve_honor_district("鼓楼区", payload)

        self.assertIsNone(district)
        self.assertIn("江苏省南京市鼓楼区", error)
        self.assertIn("福建省福州市鼓楼区", error)


if __name__ == "__main__":
    unittest.main()
