import sys
import types
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


def video(bvid, title, pubdate, up_name="罗翔说刑法", aid="100001", pic="https://i0.hdslb.com/bfs/archive/thumb.jpg"):
    return {
        "up_name": up_name,
        "up_mid": "517327498",
        "aid": aid,
        "bvid": bvid,
        "title": title,
        "pubdate": pubdate,
        "url": f"https://www.bilibili.com/video/{bvid}",
        "pic": pic,
    }


def save_subscriptions(subscriptions):
    ZFUNC._bili_video_save_subscriptions(subscriptions)


class BiliVideoSubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.original_redis = ZFUNC.dmc.redis_deamon
        self.original_search_users = ZAPI.bilibili_search_users
        self.original_search_by_mid = ZAPI.bilibili_search_videos_by_mid
        self.original_user_card = ZAPI.bilibili_get_user_card
        self.original_message_sender = sys.modules.get("hok.utils.message_sender")
        self.original_confs = dict(ZFUNC.confs)
        self.fake_redis = FakeRedis()
        self.sent_messages = []

        ZFUNC.confs.setdefault("QQBot", {})["super_qid"] = 999001
        ZFUNC.confs.setdefault("WebService", {})["server_domain"] = "example.test"
        ZFUNC.dmc.redis_deamon = self.fake_redis
        ZFUNC.dmc.BiliVideoApiPageSize = 20
        ZFUNC.dmc.BiliVideoPushEnabled = True

        sender_module = types.ModuleType("hok.utils.message_sender")

        def fake_add_msg(content, *, event=None, msg_type=None, to_id=None):
            self.sent_messages.append({
                "content": content,
                "msg_type": msg_type,
                "to_id": to_id,
            })

        sender_module.add_msg = fake_add_msg
        sys.modules["hok.utils.message_sender"] = sender_module

    def tearDown(self):
        ZFUNC.dmc.redis_deamon = self.original_redis
        ZAPI.bilibili_search_users = self.original_search_users
        ZAPI.bilibili_search_videos_by_mid = self.original_search_by_mid
        ZAPI.bilibili_get_user_card = self.original_user_card
        ZFUNC.confs.clear()
        ZFUNC.confs.update(self.original_confs)
        if self.original_message_sender is None:
            sys.modules.pop("hok.utils.message_sender", None)
        else:
            sys.modules["hok.utils.message_sender"] = self.original_message_sender

    def test_subscribe_resolves_fuzzy_name_and_marks_current_videos_seen_without_push(self):
        ZAPI.bilibili_search_users = lambda query, page_size=10: [
            {"mid": "111", "name": "张三讲法学", "fans": 100, "videos": 1},
            {"mid": "517327498", "name": "罗翔说刑法", "fans": 30000000, "videos": 500},
        ]
        ZAPI.bilibili_search_videos_by_mid = lambda mid, up_name=None, page_size=20: [
            video("BV-new", "最新视频", 200),
            video("BV-old", "旧视频", 100),
        ]

        result = ZFUNC.bili_video_subscribe_user("10001", "罗翔刑法")

        self.assertIn("订阅成功：罗翔说刑法(517327498)", result)
        self.assertEqual(
            ZFUNC._bili_video_get_subscriptions()["10001"]["up_name"],
            "罗翔说刑法",
        )
        self.assertEqual(
            ZFUNC._bili_video_get_subscriptions()["10001"]["up_mid"],
            "517327498",
        )
        self.assertEqual(
            ZFUNC._bili_video_get_subscriptions()["10001"]["query"],
            "罗翔刑法",
        )
        saved_subscriptions = json.loads(self.fake_redis.get("bili:video_subscriptions"))
        self.assertEqual(saved_subscriptions["10001"]["up_mid"], "517327498")
        self.assertTrue(self.fake_redis.sismember("bili:video_seen:mid:517327498", "BV-new"))
        self.assertTrue(self.fake_redis.sismember("bili:video_seen:mid:517327498", "BV-old"))
        self.assertEqual(self.sent_messages, [])

    def test_subscriptions_do_not_fallback_to_dynamic_variable(self):
        ZFUNC.dmc.BiliVideoUserSubscriptions = {
            "10001": {"up_mid": "517327498", "up_name": "旧文件订阅", "subscribed_at": ""}
        }

        self.assertEqual(ZFUNC._bili_video_get_subscriptions(), {})

    def test_one_subscription_per_user_limit(self):
        save_subscriptions({
            "10001": {"up_mid": "517327498", "up_name": "罗翔说刑法", "subscribed_at": "2026-07-25 12:00:00"}
        })
        ZAPI.bilibili_search_users = lambda query, page_size=10: []
        ZAPI.bilibili_search_videos_by_mid = lambda mid, up_name=None, page_size=20: []

        result = ZFUNC.bili_video_subscribe_user("10001", "影视飓风")

        self.assertIn("每人最多订阅 1 个 UP", result)
        self.assertEqual(
            ZFUNC._bili_video_get_subscriptions()["10001"]["up_name"],
            "罗翔说刑法",
        )

    def test_check_pushes_new_video_to_admin_only_and_deduplicates(self):
        save_subscriptions({
            "10001": {"up_mid": "517327498", "up_name": "罗翔旧昵称", "subscribed_at": ""},
            "10002": {"up_mid": "517327498", "up_name": "罗翔旧昵称", "subscribed_at": ""},
        })
        self.fake_redis.sadd("bili:video_seen:mid:517327498", "BV-old")
        ZAPI.bilibili_get_user_card = lambda mid: {"mid": str(mid), "name": "罗翔说刑法"}
        ZAPI.bilibili_search_videos_by_mid = lambda mid, up_name=None, page_size=20: [
            video("BV-new", "最新视频", 200),
            video("BV-old", "旧视频", 100),
        ]

        result = ZFUNC.bili_video_check_and_push(debug=True)
        second_result = ZFUNC.bili_video_check_and_push(debug=True)

        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["pushed"], 1)
        self.assertEqual(second_result["pushed"], 0)
        self.assertEqual(len(self.sent_messages), 1)
        self.assertEqual(self.sent_messages[0]["msg_type"], "private")
        self.assertEqual(self.sent_messages[0]["to_id"], ZFUNC.confs["QQBot"]["super_qid"])
        self.assertTrue(self.sent_messages[0]["content"].startswith("B站订阅视频推送\n"))
        self.assertIn("【最新视频】", self.sent_messages[0]["content"])
        self.assertIn("罗翔说刑法 · ", self.sent_messages[0]["content"])
        self.assertIn("\n\n[CQ:image,file=https://i0.hdslb.com/bfs/archive/thumb.jpg]\n\n", self.sent_messages[0]["content"])
        self.assertIn("https://hok.example.test/bili-video?key=", self.sent_messages[0]["content"])
        self.assertNotIn("视频标题：", self.sent_messages[0]["content"])
        self.assertNotIn("UP名字：", self.sent_messages[0]["content"])
        self.assertNotIn("发布时间：", self.sent_messages[0]["content"])
        self.assertNotIn("跳转链接：", self.sent_messages[0]["content"])
        self.assertNotIn("B站直链", self.sent_messages[0]["content"])
        self.assertNotIn("https://www.bilibili.com/video/BV-new", self.sent_messages[0]["content"])
        pushed_payloads = [json.loads(value) for value in self.fake_redis.values.values()]
        self.assertEqual(pushed_payloads[-1]["app_url"], "bilibili://video/100001?page=0")
        self.assertEqual(
            ZFUNC._bili_video_get_subscriptions()["10001"]["up_name"],
            "罗翔说刑法",
        )

    def test_latest_query_for_user_returns_current_video_detail_link(self):
        save_subscriptions({
            "10001": {"up_mid": "517327498", "up_name": "罗翔旧昵称", "subscribed_at": ""}
        })
        ZAPI.bilibili_get_user_card = lambda mid: {"mid": str(mid), "name": "罗翔说刑法"}
        ZAPI.bilibili_search_videos_by_mid = lambda mid, up_name=None, page_size=20: [
            video("BV-new", "最新视频", 200, aid="116975984513331"),
            video("BV-old", "旧视频", 100, aid="116000000000000"),
        ]

        result = ZFUNC.bili_video_latest_for_user("10001")

        self.assertTrue(result.startswith("B站订阅视频推送\n"))
        self.assertIn("【最新视频】", result)
        self.assertIn("罗翔说刑法 · ", result)
        self.assertIn("\n\n[CQ:image,file=https://i0.hdslb.com/bfs/archive/thumb.jpg]\n\n", result)
        self.assertIn("https://hok.example.test/bili-video?key=", result)
        self.assertNotIn("视频标题：", result)
        self.assertNotIn("UP名字：", result)
        self.assertNotIn("发布时间：", result)
        self.assertNotIn("跳转链接：", result)
        self.assertNotIn("B站直链", result)
        self.assertNotIn("https://www.bilibili.com/video/BV-new", result)
        query_payloads = [json.loads(value) for value in self.fake_redis.values.values()]
        self.assertEqual(query_payloads[-1]["app_url"], "bilibili://video/116975984513331?page=0")
        self.assertEqual(
            ZFUNC._bili_video_get_subscriptions()["10001"]["up_name"],
            "罗翔说刑法",
        )


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
            json.loads(self.fake_redis.get("battle:invisible_disabled_qids")),
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
