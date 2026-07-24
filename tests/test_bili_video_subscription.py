import sys
import types
import unittest

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


def video(bvid, title, pubdate, up_name="罗翔说刑法"):
    return {
        "up_name": up_name,
        "bvid": bvid,
        "title": title,
        "pubdate": pubdate,
        "url": f"https://www.bilibili.com/video/{bvid}",
        "pic": "",
    }


class BiliVideoSubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.original_subscriptions = getattr(ZFUNC.dmc, "BiliVideoUserSubscriptions", {})
        self.original_redis = ZFUNC.dmc.redis_deamon
        self.original_search = ZAPI.bilibili_search_videos_by_exact_author
        self.original_save = ZFUNC._bili_video_save_subscriptions
        self.original_message_sender = sys.modules.get("hok.utils.message_sender")
        self.original_confs = dict(ZFUNC.confs)
        self.fake_redis = FakeRedis()
        self.sent_messages = []

        ZFUNC.confs.setdefault("QQBot", {})["super_qid"] = 999001
        ZFUNC.dmc.BiliVideoUserSubscriptions = {}
        ZFUNC.dmc.redis_deamon = self.fake_redis
        ZFUNC.dmc.BiliVideoApiPageSize = 20
        ZFUNC.dmc.BiliVideoPushEnabled = True

        def fake_save(subscriptions):
            ZFUNC.dmc.BiliVideoUserSubscriptions = subscriptions

        ZFUNC._bili_video_save_subscriptions = fake_save

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
        ZFUNC.dmc.BiliVideoUserSubscriptions = self.original_subscriptions
        ZFUNC.dmc.redis_deamon = self.original_redis
        ZAPI.bilibili_search_videos_by_exact_author = self.original_search
        ZFUNC._bili_video_save_subscriptions = self.original_save
        ZFUNC.confs.clear()
        ZFUNC.confs.update(self.original_confs)
        if self.original_message_sender is None:
            sys.modules.pop("hok.utils.message_sender", None)
        else:
            sys.modules["hok.utils.message_sender"] = self.original_message_sender

    def test_subscribe_marks_current_videos_seen_without_push(self):
        ZAPI.bilibili_search_videos_by_exact_author = lambda up_name, page_size=20: [
            video("BV-new", "最新视频", 200),
            video("BV-old", "旧视频", 100),
        ]

        result = ZFUNC.bili_video_subscribe_user("10001", "罗翔说刑法")

        self.assertIn("订阅成功：罗翔说刑法", result)
        self.assertEqual(
            ZFUNC.dmc.BiliVideoUserSubscriptions["10001"]["up_name"],
            "罗翔说刑法",
        )
        self.assertTrue(self.fake_redis.sismember("bili:video_seen:罗翔说刑法", "BV-new"))
        self.assertTrue(self.fake_redis.sismember("bili:video_seen:罗翔说刑法", "BV-old"))
        self.assertEqual(self.sent_messages, [])

    def test_one_subscription_per_user_limit(self):
        ZFUNC.dmc.BiliVideoUserSubscriptions = {
            "10001": {"up_name": "罗翔说刑法", "subscribed_at": "2026-07-25 12:00:00"}
        }
        ZAPI.bilibili_search_videos_by_exact_author = lambda up_name, page_size=20: [
            video("BV-any", "任意视频", 100, up_name=up_name),
        ]

        result = ZFUNC.bili_video_subscribe_user("10001", "影视飓风")

        self.assertIn("每人最多订阅 1 个 UP", result)
        self.assertEqual(
            ZFUNC.dmc.BiliVideoUserSubscriptions["10001"]["up_name"],
            "罗翔说刑法",
        )

    def test_check_pushes_new_video_to_admin_only_and_deduplicates(self):
        ZFUNC.dmc.BiliVideoUserSubscriptions = {
            "10001": {"up_name": "罗翔说刑法", "subscribed_at": ""},
            "10002": {"up_name": "罗翔说刑法", "subscribed_at": ""},
        }
        self.fake_redis.sadd("bili:video_seen:罗翔说刑法", "BV-old")
        ZAPI.bilibili_search_videos_by_exact_author = lambda up_name, page_size=20: [
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
        self.assertIn("B站订阅新视频：罗翔说刑法", self.sent_messages[0]["content"])
        self.assertIn("BV-new", self.sent_messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
