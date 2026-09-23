import unittest
import json

from local_debugger import import_hok_module


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

    def exists(self, key):
        return key in self.sets or key in self.values

    def sadd(self, key, *values):
        target = self.sets.setdefault(key, set())
        before = len(target)
        for value in values:
            target.add(str(value))
        return len(target) - before

    def sismember(self, key, value):
        return str(value) in self.sets.get(key, set())


class BiliVideoSubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.original_redis = ZFUNC.dmc.redis_deamon
        self.fake_redis = FakeRedis()
        ZFUNC.dmc.redis_deamon = self.fake_redis

    def tearDown(self):
        ZFUNC.dmc.redis_deamon = self.original_redis

    def test_subscriptions_do_not_fallback_to_dynamic_variable(self):
        ZFUNC.dmc.BiliVideoUserSubscriptions = {
            "10001": {"up_mid": "517327498", "up_name": "旧文件订阅", "subscribed_at": ""}
        }

        self.assertEqual(ZFUNC._bili_video_get_subscriptions(), {})

class RuntimeStateRedisTests(unittest.TestCase):
    def setUp(self):
        self.original_redis = ZFUNC.dmc.redis_deamon
        self.fake_redis = FakeRedis()
        ZFUNC.dmc.redis_deamon = self.fake_redis

    def tearDown(self):
        ZFUNC.dmc.redis_deamon = self.original_redis

    def test_battle_visibility_disabled_qids_are_stored_in_redis(self):
        ZFUNC.save_battle_invisible_disabled_qids(["10002", "10001", "10001"])

        self.assertEqual(
            json.loads(self.fake_redis.get("hok:battle:invisible_disabled_qids")),
            ["10001", "10002"],
        )
        self.assertEqual(
            ZFUNC.get_battle_invisible_disabled_qids(),
            ["10001", "10002"],
        )

    def test_battle_visibility_does_not_fallback_to_dynamic_variable(self):
        ZFUNC.dmc.BattleInvisibleDisabledQids = ["10001"]

        self.assertEqual(ZFUNC.get_battle_invisible_disabled_qids(), [])


if __name__ == "__main__":
    unittest.main()
