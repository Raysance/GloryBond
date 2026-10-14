import unittest

from local_debugger import import_hok_module


COLLECTOR = import_hok_module("tools.kpl_match_collector")
ZAPI = import_hok_module("zapi")
ZFUNC = import_hok_module("zfunc")


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.sets = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.values.pop(key, None)
        return True

    def sismember(self, key, value):
        return str(value) in self.sets.get(key, set())

    def sadd(self, key, *values):
        target = self.sets.setdefault(key, set())
        before = len(target)
        target.update(str(value) for value in values)
        return len(target) - before


def sample_match_content():
    return {
        "home_team": {"name": "主队"},
        "away_team": {"name": "客队"},
        "score": {"home": 4, "away": 2},
        "start_time_iso": "2026-09-23T18:00:00+08:00",
        "end_time_iso": "2026-09-23T21:00:00+08:00",
        "overall_ratings": [
            {
                "name": "主队",
                "players": [
                    {"name": "选手A", "position": "打野", "rating": 9.8}
                ],
            }
        ],
    }


class KplBusinessTests(unittest.TestCase):
    def test_prompt_builder_normalizes_series_payload(self):
        original_mode = getattr(ZFUNC.dmc, "KplImageStyleMode", None)
        original_index = getattr(ZFUNC.dmc, "KplImageStyleFixedIndex", None)
        ZFUNC.dmc.KplImageStyleMode = "fixed"
        ZFUNC.dmc.KplImageStyleFixedIndex = 1
        try:
            result = ZFUNC.kpl_build_match_image_prompt(
                match_content=sample_match_content()
            )
        finally:
            if original_mode is None:
                delattr(ZFUNC.dmc, "KplImageStyleMode")
            else:
                ZFUNC.dmc.KplImageStyleMode = original_mode
            if original_index is None:
                delattr(ZFUNC.dmc, "KplImageStyleFixedIndex")
            else:
                ZFUNC.dmc.KplImageStyleFixedIndex = original_index

        payload = result["payload"]
        self.assertEqual(payload["match_name"], "主队 vs 客队")
        self.assertEqual(payload["total_score"], "4-2")
        self.assertEqual(payload["start_time"], "2026-09-23 18:00:00")
        self.assertIn("浅色极简信息图", result["style_template"])

    def test_image_generation_preserves_debug_payload(self):
        original_generate = ZAPI.apimart_images_generate
        captured = []
        ZAPI.apimart_images_generate = lambda **kwargs: captured.append(kwargs) or {
            "url": "https://example/image.png"
        }
        try:
            result = ZFUNC.kpl_match_image_generate(
                match_content=sample_match_content(),
                size="1792x1024",
                resolution="2k",
            )
        finally:
            ZAPI.apimart_images_generate = original_generate

        self.assertEqual(result["url"], "https://example/image.png")
        self.assertEqual(result["payload"]["total_score"], "4-2")
        self.assertEqual(captured[0]["size"], "1792x1024")
        self.assertEqual(captured[0]["resolution"], "2k")

    def test_force_preview_selects_latest_finished_match_without_side_effects(self):
        originals = {
            "redis": ZFUNC.dmc.redis_deamon,
            "list": COLLECTOR.get_full_match_list,
            "content": COLLECTOR.get_match_content,
        }
        ZFUNC.dmc.redis_deamon = FakeRedis()
        COLLECTOR.get_full_match_list = lambda **kwargs: {
            "now_epoch": 300,
            "groups": {
                "finished": [
                    {
                        "cid": 1,
                        "etime": 100,
                        "home": {"name": "旧主队"},
                        "away": {"name": "旧客队"},
                        "score": {"home": 1, "away": 0},
                    },
                    {
                        "cid": 2,
                        "etime": 200,
                        "home": {"name": "主队"},
                        "away": {"name": "客队"},
                        "score": {"home": 4, "away": 2},
                    },
                ]
            },
        }
        COLLECTOR.get_match_content = lambda item: sample_match_content()
        try:
            result = ZFUNC.kpl_check_and_push(
                debug=True,
                force=True,
                preview_only=True,
            )
        finally:
            ZFUNC.dmc.redis_deamon = originals["redis"]
            COLLECTOR.get_full_match_list = originals["list"]
            COLLECTOR.get_match_content = originals["content"]

        self.assertFalse(result["pushed"])
        self.assertEqual(result["cid"], 2)
        self.assertIn("KPL_PUSH_PROMPT", result["debug"])
        self.assertIn('"total_score": "4-2"', result["debug"])


if __name__ == "__main__":
    unittest.main()
