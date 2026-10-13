import unittest
from types import SimpleNamespace
from unittest.mock import patch

from local_debugger import import_hok_module


EVENT_RULES = import_hok_module("event_rules")
EVENT_INGRESS = import_hok_module("event_ingress")
ZFUNC = import_hok_module("zfunc")


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

    def mentioned(self, text, segments, *, to_me=False):
        event = EventStub(text)
        event.self_id = 10
        event.original_message = segments
        event.to_me = to_me
        return event

    async def test_direct_bot_mention_routes_to_ai_without_enabling_keyword_commands(self):
        event = self.mentioned("在线和战力查询怎么做", [{"type":"at", "data":{"qq":"10"}}])
        self.assertTrue(await EVENT_RULES.judge_direct_ai_request(event))
        self.assertTrue(await EVENT_RULES.judge_bot_addressed(event))
        self.assertFalse(await EVENT_RULES.judge_to_me(event))
        self.assertFalse(await EVENT_RULES.judge_honor_power_query(event))
        self.assertFalse(await EVENT_RULES.judge_super_command(event))

    async def test_hash_commands_keep_their_existing_route(self):
        event = self.mentioned("#在线", [SimpleNamespace(type="at", data={"qq":10})])
        self.assertTrue(await EVENT_RULES.judge_to_me(event))
        self.assertFalse(await EVENT_RULES.judge_direct_ai_request(event))

    async def test_direct_mentions_keep_existing_registration_and_disable_checks(self):
        event = self.mentioned("hello", [{"type":"at", "data":{"qq":"10"}}])
        for registered, enabled, blocked in [(False,True,True), (True,False,True), (True,True,False)]:
            with self.subTest(registered=registered, enabled=enabled), \
                 patch.object(EVENT_RULES, "is_registered_qid", return_value=registered), \
                 patch.object(EVENT_RULES, "is_battle_visible_qid_enabled", return_value=enabled):
                self.assertEqual(await EVENT_RULES.judge_qid_blocked(event), blocked)

    async def test_other_mentions_quoted_mentions_and_inferred_to_me_do_not_trigger_ai(self):
        for segments in ([{"type":"at", "data":{"qq":"all"}}],
                         [{"type":"at", "data":{"qq":"20"}}],
                         [{"type":"reply", "data":{"id":"42"}}], []):
            event = self.mentioned("普通消息", segments, to_me=True)
            event.reply = SimpleNamespace(message=[SimpleNamespace(type="at", data={"qq":"10"})])
            self.assertFalse(await EVENT_RULES.judge_direct_ai_request(event))

    async def test_adapter_stripped_mention_remains_in_original_message(self):
        from nonebot.adapters.onebot.v11 import GroupMessageEvent
        from nonebot.adapters.onebot.v11.bot import _check_at_me
        event = GroupMessageEvent.model_validate({"time":0,"self_id":10,"post_type":"message",
            "message_type":"group","sub_type":"normal","message_id":42,"group_id":200,
            "user_id":1,"anonymous":None,"font":0,"sender":{"user_id":1,"nickname":"user"},
            "raw_message":"[CQ:at,qq=10] 在线", "message":[{"type":"at","data":{"qq":"10"}},
            {"type":"text","data":{"text":" 在线"}}]})
        _check_at_me(None, event)
        self.assertFalse(any(segment.type == "at" for segment in event.message))
        self.assertTrue(await EVENT_RULES.judge_direct_ai_request(event))

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

    async def test_ingress_records_reply_metadata_once(self):
        event = EventStub("普通聊天")
        event.group_id = 20001
        event.message_id = 30001
        event.original_message = [SimpleNamespace(type="reply", data={"id": "29999"})]
        captured = []
        original_record = ZFUNC.record_group_chat_message
        ZFUNC.record_group_chat_message = lambda *args, **kwargs: captured.append(
            ("history", args, kwargs)
        )
        try:
            await EVENT_INGRESS.capture_group_message(event)
        finally:
            ZFUNC.record_group_chat_message = original_record

        self.assertEqual(captured[0][0], "history")
        self.assertEqual(captured[0][1], (20001, "10001", "普通聊天"))
        self.assertEqual(captured[0][2]["message_id"], 30001)
        self.assertEqual(captured[0][2]["reply_to_message_id"], "29999")


if __name__ == "__main__":
    unittest.main()
