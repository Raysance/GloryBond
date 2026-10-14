import json
import unittest

from local_debugger import import_hok_module


TODAY_HERO = import_hok_module("business.today_hero")
ZFUNC = import_hok_module("zfunc")
ZTIME = import_hok_module("ztime")


class FakeHeroPool:
    def __init__(self):
        self.values = {}
        self.lists = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value
        return True

    def lrange(self, key, start, end):
        return list(self.lists.get(key, []))

    def lset(self, key, index, value):
        self.lists[key][index] = value
        return True

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])


class TodayHeroTests(unittest.TestCase):
    def setUp(self):
        self.original_pool = ZFUNC.dmc.TodayHeroPool
        self.pool = FakeHeroPool()
        ZFUNC.dmc.TodayHeroPool = self.pool

    def tearDown(self):
        ZFUNC.dmc.TodayHeroPool = self.original_pool

    def test_store_updates_same_day_history_in_place(self):
        first = {
            "date": "2026-09-23",
            "heroname": "赵云",
            "skinname": "皮肤一",
            "picpath": "/tmp/one.png",
            "selectinfo": {"way": "RANDOM", "details": []},
        }
        second = dict(first, heroname="韩信", skinname="皮肤二")

        ZFUNC._today_hero_store("alice", first)
        ZFUNC._today_hero_store("alice", second)

        cached = json.loads(self.pool.values["hok:hero:today:alice"])
        history = self.pool.lists["hok:hero:history:alice"]
        self.assertEqual(cached["heroname"], "韩信")
        self.assertEqual(len(history), 1)
        self.assertEqual(json.loads(history[0])["heroname"], "韩信")
        self.assertNotIn("picpath", json.loads(history[0]))

    def test_cached_recommendation_keeps_output_contract_without_ai(self):
        originals = {
            "hero_list": TODAY_HERO.HeroList,
            "namenick": TODAY_HERO.namenick,
            "skills": TODAY_HERO.read_hero_skill_descriptions,
            "statistics": ZFUNC.single_player_single_hero_process,
        }
        TODAY_HERO.HeroList = {"123": "赵云"}
        TODAY_HERO.namenick = {"alice": "Alice"}
        TODAY_HERO.read_hero_skill_descriptions = lambda hero_id: ["技能说明"]
        ZFUNC.single_player_single_hero_process = (
            lambda realname, hero_id, hero_name: "英雄统计"
        )
        current_date = ZTIME.time_r().strftime("%Y-%m-%d")
        self.pool.set(
            "hok:hero:today:alice",
            json.dumps(
                {
                    "date": current_date,
                    "heroname": "赵云",
                    "skinname": "经典",
                    "picpath": "/tmp/zhaoyun.png",
                    "selectinfo": {"way": "RANDOM", "details": []},
                }
            ),
        )
        try:
            result = ZFUNC.todayhero_process("alice", ai_comment=False)
        finally:
            TODAY_HERO.HeroList = originals["hero_list"]
            TODAY_HERO.namenick = originals["namenick"]
            TODAY_HERO.read_hero_skill_descriptions = originals["skills"]
            ZFUNC.single_player_single_hero_process = originals["statistics"]

        self.assertEqual(result[0], "Alice的今日英雄：赵云")
        self.assertEqual(result[1], "{'way': 'RANDOM', 'details': []}")
        self.assertEqual(result[2], "/tmp/zhaoyun.png")


if __name__ == "__main__":
    unittest.main()
