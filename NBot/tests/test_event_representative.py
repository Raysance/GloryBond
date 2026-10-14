import unittest

from local_debugger import import_hok_module


REP_HANDLER = import_hok_module("event_handlers.representative")
ZFUNC = import_hok_module("zfunc")


class RepresentativeEventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.originals = {
            "query": ZFUNC.representative_battle_query_impl,
            "daily": ZFUNC.get_daily_representative_battle,
            "range": ZFUNC.representative_battle_range_debug_impl,
        }

    def tearDown(self):
        ZFUNC.representative_battle_query_impl = self.originals["query"]
        ZFUNC.get_daily_representative_battle = self.originals["daily"]
        ZFUNC.representative_battle_range_debug_impl = self.originals["range"]

    async def test_public_query_normalizes_missing_and_found_results(self):
        ZFUNC.representative_battle_query_impl = lambda query: {
            "found": False,
            "target_date": "2026-09-23",
        }
        missing = await REP_HANDLER.representative_query_reply("#昨天代表局")
        self.assertEqual(
            missing,
            {"kind": "text", "text": "2026-09-23 暂无可用的代表局"},
        )

        ZFUNC.representative_battle_query_impl = lambda query: {
            "found": True,
            "text": "代表局",
            "image_path": "/tmp/battle.png",
            "commentary": "短评",
        }
        found = await REP_HANDLER.representative_query_reply("#昨天代表局")
        self.assertEqual(found["kind"], "battle")
        self.assertEqual(found["commentary"], "短评")

    async def test_daily_debug_formats_scoring_payload(self):
        ZFUNC.get_daily_representative_battle = lambda target_date=None: (
            "正文",
            "/tmp/battle.png",
            {
                "RepresentativeCategory": "优秀",
                "RepScore": 88,
                "CategoryScores": {"优秀": 88, "糟糕": 2},
                "RawTags": ["高评分"],
                "ScoreBreakdown": [
                    {
                        "factor": "评分",
                        "contribution": 20,
                        "max_weight": 25,
                        "condition": "12.0分",
                    }
                ],
                "FilterSummary": {"scanned": 10, "eligible_unique_battles": 2},
                "HasDetail": True,
                "AiCommentary": "短评",
            },
        )

        result = await REP_HANDLER.daily_representative_debug_reply(
            "##srep 2026-09-23"
        )

        self.assertEqual(result["kind"], "battle")
        self.assertIn("● 代表类型: 优秀", result["text"])
        self.assertIn("扫描10局", result["text"])
        self.assertEqual(result["commentary"], "短评")
        self.assertEqual(result["acknowledgement"], "代表局调试结果已私聊发送")

    async def test_range_debug_returns_day_reports(self):
        ZFUNC.representative_battle_range_debug_impl = lambda query: {
            "day_reports": ["第一天", "第二天"]
        }

        self.assertEqual(
            await REP_HANDLER.representative_range_debug_replies("##rep3"),
            ["第一天", "第二天"],
        )


if __name__ == "__main__":
    unittest.main()
