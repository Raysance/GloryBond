import unittest
import json

from local_debugger import import_hok_module


ZFUNC = import_hok_module("zfunc")
ZAPI = import_hok_module("zapi")


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

    def test_unsubscribe_one_of_multiple_subscriptions_persists_the_rest(self):
        ZFUNC._bili_video_save_subscriptions(
            {
                "10001": [
                    {"up_mid": "1", "up_name": "一号", "query": "一号"},
                    {"up_mid": "2", "up_name": "二号", "query": "二号"},
                ]
            }
        )

        result = ZFUNC.bili_video_unsubscribe_user("10001", "1")

        self.assertEqual(result, "已取消订阅：一号(1)")
        remaining = ZFUNC._bili_video_get_subscriptions()["10001"]
        self.assertEqual([item["up_mid"] for item in remaining], ["2"])

    def test_push_workflow_uses_zfunc_state_and_marks_video_seen(self):
        originals = {
            "card": ZAPI.bilibili_get_user_card,
            "videos": ZAPI.bilibili_search_videos_by_mid,
            "send": ZFUNC._bili_video_send_group_message,
            "enabled": getattr(ZFUNC.dmc, "BiliVideoPushEnabled", None),
            "web_service": ZFUNC.confs.get("WebService"),
        }
        sent = []
        ZFUNC.dmc.BiliVideoPushEnabled = True
        ZFUNC.confs["WebService"] = {"server_domain": "example.com"}
        ZFUNC._bili_video_save_subscriptions(
            {
                "10001": [
                    {
                        "up_mid": "123",
                        "up_name": "测试UP",
                        "query": "测试UP",
                        "subscribed_at": "",
                    }
                ]
            }
        )
        self.fake_redis.sadd("hok:bili:seen:123", "BVold")
        ZAPI.bilibili_get_user_card = lambda mid: {"name": "测试UP"}
        ZAPI.bilibili_search_videos_by_mid = lambda *args, **kwargs: [
            {
                "aid": "99",
                "bvid": "BVnew",
                "title": "新视频",
                "pubdate": 2,
                "pic": "",
                "up_mid": "123",
            }
        ]
        ZFUNC._bili_video_send_group_message = lambda message, **kwargs: sent.append(message)
        try:
            result = ZFUNC.bili_video_check_and_push(debug=True)
        finally:
            ZAPI.bilibili_get_user_card = originals["card"]
            ZAPI.bilibili_search_videos_by_mid = originals["videos"]
            ZFUNC._bili_video_send_group_message = originals["send"]
            if originals["enabled"] is None:
                delattr(ZFUNC.dmc, "BiliVideoPushEnabled")
            else:
                ZFUNC.dmc.BiliVideoPushEnabled = originals["enabled"]
            if originals["web_service"] is None:
                ZFUNC.confs.pop("WebService", None)
            else:
                ZFUNC.confs["WebService"] = originals["web_service"]

        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["pushed"], 1)
        self.assertEqual(len(sent), 1)
        self.assertIn("新视频", sent[0])
        self.assertTrue(self.fake_redis.sismember("hok:bili:seen:123", "BVnew"))
        self.assertNotIn("hok:lock:bili:video_push", self.fake_redis.values)

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
