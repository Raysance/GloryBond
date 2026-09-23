import unittest
from types import SimpleNamespace

from local_debugger import import_hok_module


EVENT_RULES = import_hok_module("event_rules")
EVENT_INGRESS = import_hok_module("event_ingress")
ZFUNC = import_hok_module("zfunc")
ZMEMORY = import_hok_module("zmemory")


class EventStub:
    def __init__(self, text):
        self.text = text

    def get_plaintext(self):
        return self.text

    def get_user_id(self):
        return "10001"


class EventRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_hash_prefix_routes_to_bot(self):
        self.assertTrue(await EVENT_RULES.judge_to_me(EventStub("#查询")))
        self.assertTrue(await EVENT_RULES.judge_to_me(EventStub("＃查询")))
        self.assertFalse(await EVENT_RULES.judge_to_me(EventStub("普通聊天")))

    async def test_bili_latest_does_not_fall_into_subscribe(self):
        event = EventStub("#订阅最新视频")
        self.assertTrue(await EVENT_RULES.judge_bili_video_latest(event))
        self.assertFalse(await EVENT_RULES.judge_bili_video_subscribe(event))

    async def test_bili_free_form_subscription_is_supported(self):
        event = EventStub("#订阅某个UP主")
        self.assertTrue(await EVENT_RULES.judge_bili_video_subscribe(event))
        self.assertFalse(await EVENT_RULES.judge_bili_video_latest(event))

    async def test_bili_unsubscribe_prefix_is_supported(self):
        self.assertTrue(
            await EVENT_RULES.judge_bili_video_unsubscribe(
                EventStub("#取消订阅某个UP主")
            )
        )

    async def test_ingress_records_reply_metadata_before_passive_chat(self):
        event = EventStub("普通聊天")
        event.group_id = 20001
        event.message_id = 30001
        event.original_message = [SimpleNamespace(type="reply", data={"id": "29999"})]
        captured = []
        original_record = ZFUNC.record_group_chat_message
        original_passive = ZMEMORY.instance.log_passive_chat
        original_registered = EVENT_INGRESS.is_registered_qid
        original_visible = EVENT_INGRESS.is_battle_visible_qid_enabled
        ZFUNC.record_group_chat_message = lambda *args, **kwargs: captured.append(
            ("history", args, kwargs)
        )
        ZMEMORY.instance.log_passive_chat = lambda *args: captured.append(
            ("passive", args)
        )
        EVENT_INGRESS.is_registered_qid = lambda user_id: True
        EVENT_INGRESS.is_battle_visible_qid_enabled = lambda user_id: True
        try:
            await EVENT_INGRESS.capture_group_message(event)
        finally:
            ZFUNC.record_group_chat_message = original_record
            ZMEMORY.instance.log_passive_chat = original_passive
            EVENT_INGRESS.is_registered_qid = original_registered
            EVENT_INGRESS.is_battle_visible_qid_enabled = original_visible

        self.assertEqual(captured[0][0], "history")
        self.assertEqual(captured[0][1], (20001, "10001", "普通聊天"))
        self.assertEqual(captured[0][2]["message_id"], 30001)
        self.assertEqual(captured[0][2]["reply_to_message_id"], "29999")
        self.assertEqual(captured[1], ("passive", ("10001", "普通聊天")))


if __name__ == "__main__":
    unittest.main()
