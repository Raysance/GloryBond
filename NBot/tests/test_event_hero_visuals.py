import unittest

from local_debugger import import_hok_module


EVENT_RULES = import_hok_module("event_rules")
HERO_VISUALS = import_hok_module("event_handlers.hero_visuals")
ZFILE = import_hok_module("zfile")
ZFUNC = import_hok_module("zfunc")


class FakeEvent:
    def __init__(self, text):
        self.text = text

    def get_plaintext(self):
        return self.text

    def get_user_id(self):
        return "1001"


class HeroVisualEventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.originals = {
            "validated": EVENT_RULES.get_validated_name,
            "hero_power": ZFUNC.heropower_process,
            "realname": ZFUNC.qid2realname,
            "today": ZFUNC.todayhero_process,
            "grade": ZFUNC.gradeanalyze_process,
            "watch": ZFUNC.watchbattle_process,
            "exists": ZFILE.file_exist,
        }
        EVENT_RULES.get_validated_name = lambda event: "alice"

    def tearDown(self):
        EVENT_RULES.get_validated_name = self.originals["validated"]
        ZFUNC.heropower_process = self.originals["hero_power"]
        ZFUNC.qid2realname = self.originals["realname"]
        ZFUNC.todayhero_process = self.originals["today"]
        ZFUNC.gradeanalyze_process = self.originals["grade"]
        ZFUNC.watchbattle_process = self.originals["watch"]
        ZFILE.file_exist = self.originals["exists"]

    async def test_hero_power_uses_validated_player(self):
        ZFUNC.heropower_process = lambda realname: f"{realname}英雄战力"

        result = await HERO_VISUALS.hero_power_reply(FakeEvent("#英雄战力"))

        self.assertEqual(result, {"kind": "text", "text": "alice英雄战力"})

    async def test_today_hero_parses_cache_and_ai_flags(self):
        ZFUNC.qid2realname = lambda user_id: "alice"
        calls = []
        ZFUNC.todayhero_process = lambda *args: calls.append(args) or (
            "今日英雄",
            "推荐理由",
            "/tmp/hero.png",
        )

        result = await HERO_VISUALS.today_hero_reply(FakeEvent("#今日英雄%$"))

        self.assertEqual(calls, [("alice", True, False)])
        self.assertEqual(result["kind"], "image")
        self.assertEqual(result["suffix"], "推荐理由")

    async def test_today_hero_rejects_other_player_plain_syntax(self):
        result = await HERO_VISUALS.today_hero_reply(
            FakeEvent("#alice的今日英雄")
        )

        self.assertEqual(result, {"kind": "text", "text": "只能查询自己的今日英雄"})

    async def test_grade_and_watch_results_keep_image_contract(self):
        ZFUNC.gradeanalyze_process = lambda realname: (
            "/tmp/grade.png",
            "分析",
        )
        ZFUNC.watchbattle_process = lambda realname: (
            "/tmp/watch.png",
            "观战",
        )
        ZFILE.file_exist = lambda path: path == "/tmp/watch.png"

        grade = await HERO_VISUALS.grade_analysis_reply(FakeEvent("#分析"))
        watch = await HERO_VISUALS.watch_battle_reply(FakeEvent("#ob"))

        self.assertEqual(grade["image_path"], "/tmp/grade.png")
        self.assertEqual(watch["kind"], "image")
        self.assertEqual(watch["image_path"], "/tmp/watch.png")


if __name__ == "__main__":
    unittest.main()
