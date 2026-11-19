"""Native mention archives retain receipt-time names through existing storage paths."""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.adapters.onebot.v11.bot import _check_at_me

from local_debugger import import_hok_module


INGRESS = import_hok_module("event_ingress")
PROFILES = import_hok_module("utils.qq_profiles")
FUNCS = import_hok_module("zfunc")
DB = import_hok_module("zdb")


def event(segments):
    return GroupMessageEvent.model_validate({
        "time": 100, "self_id": 10, "post_type": "message", "message_type": "group",
        "sub_type": "normal", "message_id": 42, "group_id": 200, "user_id": 100,
        "anonymous": None, "font": 0, "sender": {"user_id": 100, "nickname": "作者"},
        "raw_message": "", "message": segments,
    })


def at(user):
    return {"type": "at", "data": {"qq": str(user)}}


def text(value):
    return {"type": "text", "data": {"text": value}}


class MentionArchiveTests(unittest.IsolatedAsyncioTestCase):
    async def capture(self, message, reader):
        bot = Mock(get_group_member_info=reader)
        with patch.object(PROFILES.nonebot, "get_bot", return_value=bot), \
                patch.object(DB, "upsert_group_chat_message") as save, \
                patch.object(FUNCS, "automation_publish_event", return_value=[]):
            await INGRESS.capture_group_message(message)
        return save

    async def test_multiple_mentions_preserve_order_names_and_plain_text_in_database_payload(self):
        reader = AsyncMock(side_effect=[
            {"group_id": 200, "user_id": 101, "nickname": "昵称一", "card": "群名片一", "uid": "private"},
            {"group_id": 200, "user_id": 102, "nickname": "昵称二", "card": ""},
        ])
        save = await self.capture(event([text("请 "), at(101), text("和 "), at(102), text(" 看看 "), at(101)]), reader)
        record = save.call_args.args[0]
        self.assertEqual(record["text"], "请 @群名片一(QQ:101) 和 @昵称二(QQ:102)  看看 @群名片一(QQ:101)")
        self.assertEqual(record["plain_text"], "请 和  看看")
        self.assertEqual(record["mentions"], [
            {"user_id": "101", "nickname": "昵称一", "group_card": "群名片一", "display_name": "群名片一"},
            {"user_id": "102", "nickname": "昵称二", "group_card": None, "display_name": "昵称二"},
        ])
        self.assertEqual(reader.await_count, 2)
        reader.assert_any_await(group_id=200, user_id=101, no_cache=True)
        row = DB._normalize_group_chat_row(record)
        restored = DB._group_chat_record({
            "group_id": row[0], "message_id": row[1], "user_id": row[2],
            "reply_to_message_id": row[3], "sent_at": row[4], "source_timestamp": row[5],
            "message_text": row[6], "payload": row[7],
        })
        self.assertEqual(restored, record)

    async def test_adapter_stripped_bot_mention_with_no_body_is_still_archived(self):
        message = event([at(10)])
        _check_at_me(None, message)
        save = await self.capture(message, AsyncMock(return_value={
            "group_id": 200, "user_id": 10, "nickname": "机器人", "card": ""}))
        self.assertEqual(save.call_args.args[0]["text"], "@机器人(QQ:10)")
        self.assertEqual(save.call_args.args[0]["plain_text"], "")

    async def test_all_members_never_requests_a_person_profile(self):
        reader = AsyncMock()
        save = await self.capture(event([at("all")]), reader)
        self.assertEqual(save.call_args.args[0]["text"], "@全体成员")
        self.assertEqual(save.call_args.args[0]["mentions"][0]["user_id"], "all")
        reader.assert_not_awaited()

    async def test_profile_failure_or_wrong_identity_keeps_qq_without_inventing_a_name(self):
        reader = AsyncMock(side_effect=[RuntimeError("unavailable"),
            {"group_id": 201, "user_id": 102, "nickname": "错误身份"}])
        save = await self.capture(event([at(101), at(102)]), reader)
        record = save.call_args.args[0]
        self.assertEqual(record["text"], "@101(QQ:101) @102(QQ:102)")
        self.assertTrue(all(item["display_name"] is None for item in record["mentions"]))

    async def test_timeout_retains_finished_name_and_cancels_slow_lookup(self):
        cancelled = asyncio.Event()

        async def read(**args):
            if args["user_id"] == 101:
                return {"group_id": 200, "user_id": 101, "nickname": "已读取"}
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        with patch.object(PROFILES, "MENTION_SNAPSHOT_TIMEOUT_SECONDS", 0.02):
            save = await self.capture(event([at(101), at(102)]), AsyncMock(side_effect=read))
        self.assertTrue(cancelled.is_set())
        self.assertEqual(save.call_args.args[0]["text"], "@已读取(QQ:101) @102(QQ:102)")

    async def test_quoted_mentions_are_not_attributed_to_current_message(self):
        message = event([{"type": "reply", "data": {"id": "41"}}, text("普通回复")])
        reader = AsyncMock()
        save = await self.capture(message, reader)
        record = save.call_args.args[0]
        self.assertEqual(record["reply_to_message_id"], "41")
        self.assertEqual(record["text"], "普通回复")
        self.assertNotIn("mentions", record)
        reader.assert_not_awaited()

    async def test_literal_at_is_plain_text_and_empty_nonmention_is_skipped(self):
        reader = AsyncMock()
        save = await self.capture(event([text("@某人")]), reader)
        self.assertEqual(save.call_args.args[0]["text"], "@某人")
        self.assertNotIn("mentions", save.call_args.args[0])
        empty_save = await self.capture(event([{"type": "face", "data": {"id": "1"}}]), reader)
        empty_save.assert_not_called()
        reader.assert_not_awaited()
