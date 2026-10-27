import unittest

from local_debugger import import_hok_module


BILI_HANDLERS = import_hok_module("event_handlers.bili_video")
ZFUNC = import_hok_module("zfunc")


class EventStub:
    def __init__(self, text, user_id="10001"):
        self.text = text
        self.user_id = user_id

    def get_plaintext(self):
        return self.text

    def get_user_id(self):
        return self.user_id


class BiliVideoEventHandlerTests(unittest.IsolatedAsyncioTestCase):
    def test_strip_command_supports_full_width_hash_and_legacy_prefix(self):
        self.assertEqual(
            BILI_HANDLERS.strip_bili_video_command(
                "＃ 订阅B站 测试UP ",
                ["订阅B站", "订阅b站", "订阅"],
            ),
            "测试UP",
        )

    async def test_subscribe_dispatch_preserves_user_and_query(self):
        original = ZFUNC.bili_video_subscribe_user
        calls = []
        ZFUNC.bili_video_subscribe_user = (
            lambda user_id, query: calls.append((user_id, query)) or "ok"
        )
        try:
            result = await BILI_HANDLERS.subscribe_reply(
                EventStub("#订阅 测试UP")
            )
        finally:
            ZFUNC.bili_video_subscribe_user = original

        self.assertEqual(result, "ok")
        self.assertEqual(calls, [("10001", "测试UP")])

    async def test_unsubscribe_dispatch_allows_empty_query(self):
        original = ZFUNC.bili_video_unsubscribe_user
        calls = []
        ZFUNC.bili_video_unsubscribe_user = (
            lambda user_id, query: calls.append((user_id, query)) or "ok"
        )
        try:
            result = await BILI_HANDLERS.unsubscribe_reply(
                EventStub("#取消订阅")
            )
        finally:
            ZFUNC.bili_video_unsubscribe_user = original

        self.assertEqual(result, "ok")
        self.assertEqual(calls, [("10001", "")])

    async def test_latest_and_my_subscription_dispatch_by_user(self):
        original_latest = ZFUNC.bili_video_latest_for_user
        original_mine = ZFUNC.bili_video_my_subscription
        calls = []
        ZFUNC.bili_video_latest_for_user = (
            lambda user_id: calls.append(("latest", user_id)) or "latest"
        )
        ZFUNC.bili_video_my_subscription = (
            lambda user_id: calls.append(("mine", user_id)) or "mine"
        )
        try:
            latest = await BILI_HANDLERS.latest_reply(EventStub("#最新视频"))
            mine = await BILI_HANDLERS.my_subscription_reply(EventStub("#我的订阅"))
        finally:
            ZFUNC.bili_video_latest_for_user = original_latest
            ZFUNC.bili_video_my_subscription = original_mine

        self.assertEqual((latest, mine), ("latest", "mine"))
        self.assertEqual(calls, [("latest", "10001"), ("mine", "10001")])

    async def test_admin_dispatch_preserves_raw_command(self):
        original = ZFUNC.bili_video_admin_command
        calls = []
        ZFUNC.bili_video_admin_command = lambda raw: calls.append(raw) or "ok"
        try:
            result = await BILI_HANDLERS.admin_reply(
                EventStub("  ##bili status  ")
            )
        finally:
            ZFUNC.bili_video_admin_command = original

        self.assertEqual(result, "ok")
        self.assertEqual(calls, ["##bili status"])


if __name__ == "__main__":
    unittest.main()
