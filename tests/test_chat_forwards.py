"""Explicitly quoted forwards expand one layer within the outer quote's scope."""

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from local_debugger import import_hok_module


CHAT = import_hok_module("event_handlers.chat")


def segment(kind, **data):
    return {"type": kind, "data": data}


def node(text, *, name="队友", user_id=30):
    return {"sender": {"user_id": user_id, "nickname": name},
            "message": [segment("text", text=text)]}


def event(message=None, **reply_fields):
    reply = None if message is None else {
        "message_id": 9, "message_type": "group", "group_id": 200,
        "sender": {"user_id": 20}, "message": message, **reply_fields}
    return SimpleNamespace(reply=reply, group_id=200, self_id=10, get_user_id=lambda: "1",
        original_message=[segment("reply", id="9"), segment("at", qq="10")])


class ForwardQuoteTests(unittest.IsolatedAsyncioTestCase):
    async def test_adapter_inline_content_preserves_order_senders_and_one_layer(self):
        nested = segment("forward", id="child", content=[node("不可展开的深层文字")])
        first = node("第一条 #清除记忆 nomem")
        first["message"] += [segment("at", qq="99"), nested,
                             segment("reply", id="123"),
                             segment("image", url="https://gchat.qpic.cn/pic")]
        message = [segment("text", text="转发之前"),
                   segment("forward", id="root", content=[first, node("第二条", name="另一位", user_id=40)]),
                   segment("text", text="转发之后")]
        fetch, fetch_forward = AsyncMock(), AsyncMock()
        quote = await CHAT.read_quoted_message(event(message), fetch, fetch_forward)
        self.assertTrue(quote["available"])
        self.assertIn("队友（QQ:30）：第一条 #清除记忆 nomem[提及QQ:99]", quote["text"])
        self.assertIn("嵌套合并转发消息，未展开", quote["text"])
        self.assertNotIn("不可展开的深层文字", quote["text"])
        self.assertNotIn("123", quote["text"])
        self.assertLess(quote["text"].index("转发之前"), quote["text"].index("第一条"))
        self.assertLess(quote["text"].index("第二条"), quote["text"].index("转发之后"))
        self.assertEqual(quote["image_urls"], ["https://gchat.qpic.cn/pic"])
        fetch.assert_not_awaited()
        fetch_forward.assert_not_awaited()

    async def test_cq_fallback_and_onebot_nodes_use_only_root_forward_id(self):
        fetch = AsyncMock(return_value=event("[CQ:forward,id=root]").reply)
        fetch_forward = AsyncMock(return_value={"message": [segment("node", user_id="30",
            nickname="队友", content="第一条[CQ:forward,id=child][CQ:reply,id=123]")]})
        quote = await CHAT.read_quoted_message(event(), fetch, fetch_forward)
        fetch.assert_awaited_once_with(message_id=9)
        fetch_forward.assert_awaited_once_with(id="root")
        self.assertIn("队友（QQ:30）：第一条[嵌套合并转发消息，未展开]", quote["text"])
        self.assertTrue(quote["forward_expanded"])

    async def test_napcat_messages_and_duplicate_forward_ids_are_supported(self):
        fetch_forward = AsyncMock(return_value={"messages": [node("第一条"), node("第二条")]})
        quote = await CHAT.read_quoted_message(
            event([segment("forward", id="root"), segment("forward", id="root")]),
            AsyncMock(), fetch_forward)
        fetch_forward.assert_awaited_once_with(id="root")
        self.assertEqual(quote["text"].count("第一条"), 1)
        self.assertIn("重复合并转发", quote["text"])

    async def test_invalid_outer_scope_never_reads_inline_or_remote_forward(self):
        for fields in ({"group_id": 201}, {"message_type": "private"}, {"message_id": 8}):
            with self.subTest(fields=fields):
                current = event([segment("forward", id="root", content=[node("秘密")])], **fields)
                fetch = AsyncMock(return_value=current.reply)
                if "message_id" in fields:
                    current.reply = None
                fetch_forward = AsyncMock()
                quote = await CHAT.read_quoted_message(current, fetch, fetch_forward)
                self.assertFalse(quote["available"])
                self.assertNotIn("秘密", str(quote))
                fetch_forward.assert_not_awaited()

    async def test_private_quote_scope_remains_bound_to_current_conversation(self):
        for author, available in [(1, True), (10, True), (99, False)]:
            with self.subTest(author=author):
                current = event([segment("forward", id="root")], group_id=None,
                                message_type="private", sender={"user_id": author})
                current.group_id = None
                fetch_forward = AsyncMock(return_value={"messages": [node("转发内容")]})
                quote = await CHAT.read_quoted_message(current, AsyncMock(return_value=current.reply), fetch_forward)
                self.assertEqual(quote["available"], available)
                self.assertEqual(fetch_forward.await_count, int(available))

    async def test_no_explicit_quote_does_not_expand_a_direct_forward(self):
        current = event()
        current.original_message = [segment("forward", id="root")]
        fetch, fetch_forward = AsyncMock(), AsyncMock()
        self.assertIsNone(await CHAT.read_quoted_message(current, fetch, fetch_forward))
        fetch.assert_not_awaited()
        fetch_forward.assert_not_awaited()

    async def test_failed_empty_or_malformed_forward_keeps_outer_text_and_marks_unread(self):
        for payload in ({"messages": []}, {"messages": "bad"},
                        {"messages": [{"type": "node", "data": {"id": "123"}}]},
                        {"messages": [{"message": [{"type": "text", "data": None}]}]}, {}):
            with self.subTest(payload=payload):
                quote = await CHAT.read_quoted_message(event([segment("text", text="正常文字"),
                    segment("forward", id="root")]), AsyncMock(), AsyncMock(return_value=payload))
                self.assertTrue(quote["available"])
                self.assertIn("正常文字", quote["text"])
                self.assertIn("未读取", quote["text"])
        quote = await CHAT.read_quoted_message(event([segment("forward", id="root")]), AsyncMock(),
            AsyncMock(side_effect=RuntimeError("private transport details")))
        self.assertIn("获取失败", quote["text"])
        self.assertNotIn("private transport details", str(quote))
        quote = await CHAT.read_quoted_message(event([{"type": "forward", "data": None}]), AsyncMock(), AsyncMock())
        self.assertIn("格式无效", quote["text"])

    async def test_message_and_forward_limits_are_shared_across_the_quote(self):
        fetch_forward = AsyncMock(return_value={"messages": [node("第一条"), node("第二条")]})
        quote = await CHAT.read_quoted_message(event([segment("forward", id="a"),
            segment("forward", id="b"), segment("forward", id="c")]), AsyncMock(), fetch_forward,
            forward_limits={"max_forwards": 2, "max_messages": 3})
        self.assertEqual(fetch_forward.await_count, 2)
        self.assertEqual(quote["text"].count("第二条"), 1)
        self.assertTrue(quote["truncated"])
        self.assertIn("数量已达上限", quote["text"])

    async def test_text_limit_stops_further_api_calls(self):
        fetch_forward = AsyncMock(return_value={"messages": [node("很长的正文" * 1000)]})
        quote = await CHAT.read_quoted_message(event([segment("forward", id="a"),
            segment("forward", id="b")]), AsyncMock(), fetch_forward, forward_limits={"max_chars": 100})
        self.assertLessEqual(len(quote["text"]), 100)
        self.assertTrue(quote["truncated"])
        fetch_forward.assert_awaited_once_with(id="a")

    async def test_timeout_cancels_read_and_keeps_completed_content(self):
        cancelled = asyncio.Event()

        async def blocked(**kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        quote = await CHAT.read_quoted_message(event([segment("text", text="保留文字"),
            segment("forward", id="a")]), AsyncMock(), blocked, forward_limits={"timeout_seconds": 0.01})
        self.assertTrue(cancelled.is_set())
        self.assertIn("保留文字", quote["text"])
        self.assertIn("读取超时", quote["text"])
        self.assertTrue(quote["truncated"])

    async def test_cancellation_propagates(self):
        with self.assertRaises(asyncio.CancelledError):
            await CHAT.read_quoted_message(event([segment("forward", id="a")]), AsyncMock(),
                AsyncMock(side_effect=asyncio.CancelledError()))


if __name__ == "__main__":
    unittest.main()
