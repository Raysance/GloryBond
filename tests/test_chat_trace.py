import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qq_agent.trace import build_trace
from PIL import Image
from local_debugger import import_hok_module

TRACE = import_hok_module("business.chat_trace")
HANDLER = import_hok_module("event_handlers.chat")
FILES = import_hok_module("zfile")
FUNC = import_hok_module("zfunc")


class TraceTests(unittest.TestCase):

    def test_admin_summary_keeps_sender_identity_and_missing_usage_distinct_from_zero(self):
        payload = {'session_id': 'qq_g_200_101', 'expires_in_seconds': 604800,
                   'rounds': [{'response_meta': {'usage': None}}],
                   'summary': {'token_usage': {'total_tokens': 0}}}
        entry = TRACE.trace_index_entry(payload, 'a' * 16, 1000)
        self.assertEqual((entry['group_id'], entry['user_id']), ('200', '101'))
        self.assertIsNone(entry['total_tokens'])
        self.assertTrue(entry['usage_incomplete'])
        payload['rounds'].append({'response_meta': {'usage': {'total_tokens': 12}}})
        entry = TRACE.trace_index_entry(payload, 'a' * 16, 1000)
        self.assertEqual(entry['total_tokens'], 12)
        self.assertTrue(entry['usage_incomplete'])


    def test_summary_aggregates_deepseek_cache_and_token_usage(self):
        rounds = [
            {"tools": [], "response_meta": {"usage": {
                "prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
                "prompt_cache_hit_tokens": 80, "prompt_cache_miss_tokens": 20,
            }}},
            {"tools": [], "response_meta": {"usage": {
                "prompt_tokens": 150, "completion_tokens": 30, "total_tokens": 180,
                "prompt_cache_hit_tokens": 120, "prompt_cache_miss_tokens": 30,
            }}},
        ]
        events = []
        for turn in rounds:
            events.extend([{ "kind": "model.request", "data": {"messages": [], "tools": []}},
                           { "kind": "model.response", "data": turn["response_meta"]}])
        usage = build_trace(events)["summary"]["token_usage"]
        self.assertEqual(usage, {
            "prompt_tokens": 250,
            "completion_tokens": 50,
            "total_tokens": 300,
            "prompt_cache_hit_tokens": 200,
            "prompt_cache_miss_tokens": 50,
        })


    def test_payload_survives_publication_without_preview_limits(self):
        payload = {"messages": [{"role": "system", "content": "x" * 25000 + "TAIL"}] * 201,
                   "extra": {str(index): index for index in range(90)}}
        response = {"choices": [{"message": {"content": "OUTPUT", "reasoning_content": "PROVIDER_FIELD"}}]}
        trace = {"kind": "chat_trace", "version": 1, "rounds": [{"tools": [],
                 "request_payload": payload, "response_payload": response}]}
        sanitized = TRACE.public_value(trace)
        self.assertEqual(sanitized, trace)
        with patch.object(FUNC.dmc.redis_deamon, "pipeline") as transaction:
            pipe = transaction.return_value.__enter__.return_value
            pipe.execute.return_value = [True, 1, True, True]
            FUNC.chat_publish_trace(sanitized)
        stored = json.loads(pipe.set.call_args.args[1])
        self.assertEqual(stored["rounds"], trace["rounds"])


    def test_public_trace_keeps_system_prompt_but_still_removes_credentials(self):
        data = TRACE.public_value({
            "system_prompt": "SYSTEM_VISIBLE",
            "api_key": "PRIVATE",
            "context_injection": {"tool_definitions": [{"parameters": {"properties": {
                "path": {"type": "string"}, "token": {"type": "string"},
            }}}]},
        })
        self.assertEqual(data["system_prompt"], "SYSTEM_VISIBLE")
        self.assertNotIn("api_key", data)
        properties = data["context_injection"]["tool_definitions"][0]["parameters"]["properties"]
        self.assertEqual(set(properties), {"path", "token"})


    def test_memory_and_history_arguments_and_results_are_visible_but_credentials_are_hidden(self):
        for name in ("recall_memory", "remember_memory", "forget_memory", "search_chat_history",
                     "analyze_game_database", "roleplay_select", "render_plot"):
            arguments = {"content": "偏好辅助英雄", "queries": ["内卷", "压力"], "group_id": "200",
                         "message_id": "42", "memory_id": "fact-1"}
            def record(result):
                events = [
                    {"kind": "model.request", "data": {"messages": [], "tools": []}},
                    {"kind": "tool.call", "data": {"id": "c", "function": {"name": name, "arguments": json.dumps(arguments)}}},
                    {"kind": "tool.result", "data": {"call_id": "c", "result": result}},
                ]
                return build_trace(events)["rounds"][0]["tools"][0]
            value = record({"ok": True, "data": [{"text": "群聊工具返回原文"}]})
            self.assertEqual(value["arguments"], arguments)
            self.assertEqual(value["observation"], {"ok": True, "data": [{"text": "群聊工具返回原文"}]})
            failure = record({"ok": False, "error": "ConnectionError", "detail": "检索服务连接失败"})
            self.assertEqual(failure["observation"]["error"], "ConnectionError")
            self.assertEqual(failure["arguments"], arguments)
            self.assertEqual(failure["observation"]["detail"], "检索服务连接失败")
        data = TRACE.public_value({"reasoning_content": "THOUGHT", "arguments": {
            "content": "sk-testsecret111 /srv/config/file PRIVATEKEY", "api_key": "PRIVATEKEY"},
            "observation": {"data": [{"text": "sk-testsecret111 PRIVATEKEY", "password": "PRIVATEKEY"}]}}, secrets=("PRIVATEKEY",))
        self.assertNotIn("THOUGHT", json.dumps(data))
        self.assertNotIn("sk-testsecret", json.dumps(data))
        self.assertNotIn("/srv", json.dumps(data))
        self.assertNotIn("PRIVATEKEY", json.dumps(data))
        self.assertNotIn("api_key", data["arguments"])

    def test_expiring_publish_and_failed_storage(self):
        trace = {"kind": "chat_trace", "version": 1, "rounds": [], "question": "你好"}
        with patch.object(FUNC.dmc.redis_deamon, "pipeline") as transaction:
            pipe = transaction.return_value.__enter__.return_value
            pipe.execute.return_value = [True, 1, True, True]
            url = FUNC.chat_publish_trace(trace)
        token = url.rsplit("=", 1)[1]
        self.assertRegex(token, r"^[a-f0-9]{16}$")
        self.assertEqual(pipe.set.call_args.args[0], FUNC.REDIS_KEY_WEB_ARTIFACT_PREFIX + token)
        self.assertIn("/chat-trace?key=", url)
        self.assertEqual(pipe.set.call_args.kwargs["ex"], 604800)
        self.assertEqual(json.loads(pipe.set.call_args.args[1])['visibility'], 'public')
        entry = json.loads(pipe.lpush.call_args.args[1])
        self.assertEqual(pipe.lpush.call_args.args[0], FUNC.REDIS_KEY_CHAT_TRACE_INDEX)
        self.assertEqual(entry['key'], token)
        self.assertEqual(entry['expires_at'] - entry['created_at'], 604800)
        self.assertNotIn('rounds', entry)
        pipe.ltrim.assert_called_once_with(FUNC.REDIS_KEY_CHAT_TRACE_INDEX, 0, 999)
        transaction.assert_called_once_with(transaction=True)
        with patch.object(FUNC.dmc.redis_deamon, "pipeline") as transaction:
            transaction.return_value.__enter__.return_value.execute.return_value = [False]
            result = FUNC.chat_prepare_reply({"text": "已回答", "trace": trace, "artifacts": []})
        self.assertEqual(result["text"], "已回答")
        self.assertEqual(result["trace_error"], "RuntimeError")


class QuoteTests(unittest.TestCase):
    def event(self, reply=None, group_id=2):
        return SimpleNamespace(reply=reply, group_id=group_id, self_id=10, get_user_id=lambda: "1",
                               original_message=[{"type": "reply", "data": {"id": "9"}}])

    def reply(self, **kwargs):
        return {"message_id": 9, "message_type": "group", "sender": {"user_id": 3, "card": "队友"},
                "message": [{"type": "text", "data": {"text": "这局表现如何"}},
                            {"type": "image", "data": {"url": "https://private-image/"}}], **kwargs}

    def test_adapter_reply_and_fallback_have_same_text_without_media_urls(self):
        adapter = HANDLER.normalize_quoted_message(self.event(self.reply()))
        fallback = HANDLER.normalize_quoted_message(self.event(), self.reply())
        self.assertEqual(adapter, fallback)
        self.assertTrue(adapter["available"])
        self.assertIn("这局表现如何", adapter["text"])
        self.assertIn("image消息", adapter["text"])
        self.assertNotIn("https://", adapter["text"])

    def test_missing_mismatched_or_cross_group_reply_is_unavailable(self):
        for reply in [None, self.reply(group_id=88), self.reply(message_type="private")]:
            self.assertFalse(HANDLER.normalize_quoted_message(self.event(), reply)["available"])
        self.assertFalse(HANDLER.normalize_quoted_message(self.event(), self.reply(message_id=8))["available"])

    def test_quote_drops_only_trigger_markers_and_keeps_commands_as_data(self):
        reply = self.reply(message=[{"type":"at", "data":{"qq":"10"}},
            {"type":"text", "data":{"text":"＃清除记忆 nomem"}},
            {"type":"at", "data":{"qq":"3"}}, {"type":"reply", "data":{"id":"8"}}])
        result = HANDLER.normalize_quoted_message(self.event(reply))
        self.assertEqual(result["text"], "清除记忆 nomem[提及QQ:3]")
        self.assertNotIn("8", result["text"])

    def test_cq_string_and_native_quote_preserve_the_same_content(self):
        native = self.reply(message=[{"type":"at", "data":{"qq":"10"}},
            {"type":"text", "data":{"text":"#解释 [CQ:at,qq=20]"}},
            {"type":"image", "data":{"url":"https://gchat.qpic.cn/a?x=1&y=2"}}])
        cq = self.reply(message="[CQ:at,qq=10]#解释 &#91;CQ:at&#44;qq=20&#93;[CQ:image,url=https://gchat.qpic.cn/a?x=1&amp;y=2]")
        self.assertEqual(HANDLER.normalize_quoted_message(self.event(native)), HANDLER.normalize_quoted_message(self.event(cq)))


class QuoteReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_the_explicit_quote_once_and_never_follow_nested_replies(self):
        from unittest.mock import AsyncMock
        event = QuoteTests().event()
        reply = QuoteTests().reply(message=[{"type":"reply", "data":{"id":"8"}},
            {"type":"text", "data":{"text":"#当前引用"}}])
        fetch = AsyncMock(return_value=reply)
        quote = await HANDLER.read_quoted_message(event, fetch)
        self.assertEqual(quote["text"], "当前引用")
        fetch.assert_awaited_once_with(message_id=9)

    async def test_adapter_reply_needs_no_fetch_and_unavailable_quote_keeps_failure(self):
        from unittest.mock import AsyncMock
        event = QuoteTests().event(QuoteTests().reply())
        fetch = AsyncMock()
        self.assertTrue((await HANDLER.read_quoted_message(event, fetch))["available"])
        fetch.assert_not_awaited()
        fetch.side_effect = RuntimeError("message was deleted")
        quote = await HANDLER.read_quoted_message(QuoteTests().event(), fetch)
        self.assertFalse(quote["available"])


class CollageTests(unittest.TestCase):
    def test_multiple_charts_become_one_bounded_png_and_originals_survive(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(FILES, "temp_path", directory):
            artifacts = []
            for number, size in enumerate([(1600, 900), (800, 1200), (1456, 900)]):
                path = Path(directory) / f"chat_plot_{number:032x}.png"
                Image.new("RGB", size, (number * 80, 100, 100)).save(path)
                artifacts.append({"path": str(path)})
            result = FILES.combine_chat_plot_images(artifacts)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["source_count"], 3)
            with Image.open(result[0]["path"]) as image:
                self.assertEqual(image.width, 2400)
                self.assertLess(image.height, 3700)
            self.assertTrue(all(Path(item["path"]).exists() for item in artifacts))
            self.assertTrue(FILES.chat_plot_public_path(result[0]["path"]).startswith("/file_transfer/"))
            self.assertEqual(FILES.chat_plot_public_path("/etc/passwd"), "")


class ChatMessageTests(unittest.TestCase):
    def sender(self):
        with patch("nonebot.get_driver", return_value=SimpleNamespace(on_startup=lambda function: function)):
            return import_hok_module("utils.message_sender")

    def test_detailed_forward_reuses_the_url_from_existing_trace_publication(self):
        sender = self.sender()
        trace = {"kind": "chat_trace", "version": 1, "question": "模型输入", "rounds": []}
        url = "https://hok.example.com/chat-trace?key=0123456789abcdef"
        packet = {"text": "简略回复", "variants": {"chat": "简略回复", "detailed": "详细回复"}, "trace": trace,
                  "_reply_question": {"text": "用户原话", "user_id": "101", "name": "用户"}}
        with patch.object(FUNC, "chat_publish_trace", return_value=url) as publish, \
             patch.object(sender, "_enqueue_payload") as enqueue:
            prepared = FUNC.chat_prepare_reply(packet)
            sender.add_chat_result_msg(prepared,
                destination={"platform": "qq", "channel": "private", "recipient_id": "101"})
        publish.assert_called_once()
        payload = enqueue.call_args.args[0]
        self.assertEqual(payload["messages"][0]["data"]["content"][0]["data"]["text"], "用户原话")
        self.assertEqual(payload["messages"][-1]["data"]["content"][0]["data"]["text"], "思考轨迹：" + url)
        self.assertEqual(payload["reply_direct"]["content"], "简略回复")

    def test_group_mentions_trusted_requester_before_text_images_and_trace(self):
        from nonebot.adapters.onebot.v11 import Message
        sender = self.sender()
        packet = {"text": "回复 [CQ:at,qq=all]", "mention_user_id": "999",
                  "artifacts": [{"path": "/tmp/trusted.png"}], "trace_url": "https://hok.example.com/chat-trace"}
        with patch.object(sender, "_enqueue_payload") as enqueue:
            # Replies may finish out of order; each destination keeps its caller.
            for user in ('102', '101'):
                sender.add_chat_result_msg(packet, destination={"platform": "qq", "channel": "group",
                    "recipient_id": "200", "mention_user_id": user})
        for call, user in zip(enqueue.call_args_list, ('102', '101')):
            payload = call.args[0]
            message = Message(payload['content'])
            self.assertEqual([part.type for part in message], ['at', 'text', 'image'])
            self.assertEqual(message[0].data['qq'], user)
            self.assertTrue(message[1].data['text'].startswith(' 回复'))
            self.assertIn('[CQ:at,qq=all]', message[1].data['text'])
            self.assertEqual(payload['toid'], 200)
        self.assertEqual(packet['text'], '回复 [CQ:at,qq=all]')

    def test_private_reply_and_unbound_legacy_destination_do_not_guess_mentions(self):
        from nonebot.adapters.onebot.v11 import Message
        sender = self.sender()
        for destination in [
            {'platform': 'qq', 'channel': 'private', 'recipient_id': '101', 'mention_user_id': '102'},
            {'platform': 'qq', 'channel': 'group', 'recipient_id': '200'},
        ]:
            with self.subTest(destination=destination), patch.object(sender, '_enqueue_payload') as enqueue:
                sender.add_chat_result_msg({'text': '回复'}, destination=destination,
                                           event=SimpleNamespace(group_id=300, user_id=999))
            self.assertEqual([part.type for part in Message(enqueue.call_args.args[0]['content'])], ['text'])

    def test_event_group_mention_and_invalid_target_validation(self):
        from nonebot.adapters.onebot.v11 import Message
        sender = self.sender()
        with patch.object(sender, '_enqueue_payload') as enqueue:
            sender.add_chat_result_msg({'text': '回复'}, event=SimpleNamespace(group_id=200, get_user_id=lambda: '101'))
        self.assertEqual(Message(enqueue.call_args.args[0]['content'])[0].data, {'qq': '101'})
        for target in ('[CQ:at,qq=all]', -1, 0, True, 101.5):
            with self.subTest(target=target), patch.object(sender, '_enqueue_payload') as enqueue:
                with self.assertRaises(ValueError):
                    sender.add_chat_result_msg({'text': '回复'}, destination={'platform': 'qq', 'channel': 'group',
                        'recipient_id': '200', 'mention_user_id': target})
                enqueue.assert_not_called()

    def test_native_all_members_mention_only_comes_from_trusted_group_destination(self):
        from nonebot.adapters.onebot.v11 import Message
        sender = self.sender()
        for channel, expected in [('group', ['at', 'text']), ('private', ['text'])]:
            with self.subTest(channel=channel), patch.object(sender, '_enqueue_payload') as enqueue:
                sender.add_chat_result_msg({'text': '打王者 [CQ:at,qq=999]'},
                    destination={'platform': 'qq', 'channel': channel, 'recipient_id': '200', 'mention_user_id': 'all'})
            message = Message(enqueue.call_args.args[0]['content'])
            self.assertEqual([part.type for part in message], expected)
            if channel == 'group':
                self.assertEqual(message[0].data, {'qq': 'all'})
            self.assertIn('[CQ:at,qq=999]', message[-1].data['text'])

    def test_text_and_chart_enqueue_once_without_record_footer_or_url(self):
        from nonebot.adapters.onebot.v11 import Message

        with patch("nonebot.get_driver", return_value=SimpleNamespace(on_startup=lambda function: function)):
            sender = import_hok_module("utils.message_sender")
        event = SimpleNamespace(group_id=2)
        with patch.object(sender, "_enqueue_payload") as enqueue:
            sender.add_chat_result_msg({"text": "分析 [CQ:image,file=untrusted]",
                                        "artifacts": [{"path": "/tmp/trusted.png"}],
                                        "trace_url": "https://hok.example.com/chat-trace?key=abc"}, event=event)
        enqueue.assert_called_once()
        payload = enqueue.call_args.args[0]
        message = Message(payload["content"])
        self.assertEqual([part.type for part in message], ["text", "image"])
        self.assertIn("untrusted", message[0].data["text"])
        self.assertNotIn("运行记录", payload['content'])
        self.assertNotIn("chat-trace", payload['content'])
        self.assertEqual(payload["toid"], 2)

    def test_trace_failure_is_hidden_and_sources_remain_in_message_text(self):
        sender = self.sender()
        with patch.object(sender, '_enqueue_payload') as enqueue:
            sender.add_chat_result_msg({'text': '原文 https://example.com/article', 'trace_error': 'RuntimeError'},
                destination={'platform': 'qq', 'channel': 'private', 'recipient_id': '101'})
        self.assertEqual(enqueue.call_args.args[0]['content'], '原文 https://example.com/article')


if __name__ == "__main__":
    unittest.main()
