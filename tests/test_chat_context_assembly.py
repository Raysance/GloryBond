"""Current-turn grounding, bounded history and lossless tool continuations."""

import asyncio
from copy import deepcopy
import json
import unittest
from unittest.mock import AsyncMock

from agent_runtime import AgentRuntime, ImageInput, ModelRequest, Principal, RunRequest, ToolRegistry
from agent_runtime.core.context import build_messages
from agent_console.chat_context import (ChatContextPolicy, ChatModel, active_turn, chat_metadata,
    current_message, estimated_tokens, observe_chat_event, prepare_request, reference_projection)
from agent_console.remote import RemoteState
from agent_console.capabilities import Capabilities
from tests.test_agent_runtime import Clock, Sink


def bind(*, history=(), rows=(), question="你怎么看", quote=None, policy=None):
    group = ()
    if rows:
        group = ({"role": "user", "content": "群聊背景\n" + json.dumps({
            "current_turn": {"reply_to_message_id": (quote or {}).get("message_id")},
            "messages": rows, "sources": [], "combined_truncated": False}, ensure_ascii=False)},)
    current = current_message(question, actor={"user_id": "100", "name": "提问者"}, quote=quote)
    request = RunRequest(question, "s", Principal("100"), system_prompt="stable policy", context_messages=group,
        metadata={"chat_context": chat_metadata(current=current, context_count=len(group),
            group_rows=rows, user_id="100", bot_id="900", quote_message_id=(quote or {}).get("message_id"),
            quote_sender_id=(quote or {}).get("sender_id"), policy=policy)})
    observe_chat_event({"run_id": request.run_id, "kind": "run.start", "metadata": request.metadata,
                        "data": {"context_messages": list(group)}})
    return request, build_messages(request, list(history))


class AssemblyTests(unittest.TestCase):
    def tearDown(self):
        observe_chat_event({"kind": "run.end", "run_id": "done"})

    def test_quote_author_media_and_question_form_one_current_message(self):
        image = ImageInput("attachment://" + "a" * 32)
        parts = current_message("你怎么看", actor={"user_id": "100", "name": "甲"},
            quote={"message_id": "42", "sender_id": "200", "sender_name": "乙", "text": "提议"},
            quoted_images=(image,))
        self.assertEqual(parts[1], image.content_part())
        self.assertEqual(json.loads(parts[0]["text"].split("\n", 1)[1])["sender_id"], "200")
        self.assertEqual(json.loads(parts[-1]["text"].split("\n", 1)[1])["sender"]["user_id"], "100")
        self.assertNotIn("评价乙", str(parts))

    def test_history_keeps_latest_complete_turn_instead_of_substituting_old_topic(self):
        history = [{"role": "user", "content": "旧问题"}, {"role": "assistant", "content": "旧回答"},
                   {"role": "user", "content": "写一首诗"}, {"role": "assistant", "content": "完整作品" * 100}]
        _, messages = bind(history=history, question="再改一下", policy={"history_tokens": 30})
        before = deepcopy(messages)
        prepared = prepare_request(ModelRequest(messages, [])).messages
        self.assertIn(history[-1], prepared)
        self.assertNotIn(history[0], prepared)
        self.assertTrue(active_turn().diagnostics["history_over_budget"])
        self.assertEqual(messages, before)

    def test_dedup_identified_public_copy_keeps_detailed_answer(self):
        history = [{"role": "user", "content": "原问题", "turn": {"message_id": "10"}},
                   {"role": "assistant", "content": "完整答案和条件"}]
        rows = [{"message_id": "10", "user_id": "100", "text": "原问题"},
                {"message_id": "reply", "requester_id": "100", "reply_to_message_id": "10", "text": "简答"},
                {"message_id": "11", "user_id": "200", "text": "其他人的话"}]
        _, messages = bind(history=history, rows=rows)
        result = prepare_request(ModelRequest(messages, [])).messages
        payload = json.loads(result[-2]["content"].split("\n", 1)[1])
        self.assertEqual([r["message_id"] for r in payload["messages"]], ["11"])
        self.assertTrue(any(m.get("content") == "完整答案和条件" for m in result))

    def test_dropped_history_does_not_remove_the_only_public_copy(self):
        history = [{"role": "user", "content": "原问题", "turn": {"message_id": "10"}},
                   {"role": "assistant", "content": "完整答案"}]
        rows = [{"message_id": "10", "user_id": "100", "text": "原问题"}]
        _, messages = bind(history=history, rows=rows, policy={"history_tokens": 0})
        result = prepare_request(ModelRequest(messages, [])).messages
        self.assertTrue(any('"message_id":"10"' in str(m.get("content")) for m in result))

    def test_new_third_party_quote_starts_its_branch_and_exposes_older_history_for_optional_read(self):
        history = [{"role": "user", "content": "其他主题"}, {"role": "assistant", "content": "旧结论"}]
        rows = [{"message_id": "1", "user_id": "300", "text": "无关发言"},
                {"message_id": "2", "user_id": "200", "text": "引用作者的发言"}]
        _, messages = bind(history=history, rows=rows, quote={"message_id": "42", "sender_id": "200", "text": "新资料"})
        result = prepare_request(ModelRequest(messages, [])).messages
        self.assertNotIn("旧结论", str(result))
        self.assertNotIn("无关发言", str(result))
        self.assertNotIn("引用作者的发言", str(result))
        self.assertIn("新资料", str(result))
        self.assertIn("read_direct_history", str(result))

    def test_short_followup_keeps_the_previous_quote_branch_and_its_complete_answer(self):
        history = [{"role": "user", "content": "旧主题"}, {"role": "assistant", "content": "旧回答"},
            {"role": "user", "content": "你怎么看", "turn": {"quote_sender_id": "200", "quote_message_id": "42",
                "input": current_message("你怎么看", actor={"user_id": "100"}, quote={"sender_id": "200", "text": "原提议"})}},
            {"role": "assistant", "content": "完整的点评与条件"}]
        _, messages = bind(history=history, question="按刚才的意思展开")
        result = prepare_request(ModelRequest(messages, [])).messages
        self.assertIn("原提议", str(result))
        self.assertIn("完整的点评与条件", str(result))
        self.assertNotIn("旧回答", str(result))

    def test_replies_to_a_media_quote_survive_even_when_its_text_was_not_archived(self):
        rows = [{"message_id": "1", "user_id": "300", "reply_to_message_id": "42", "text": "对这张图的评论"},
                {"message_id": "2", "user_id": "200", "text": "同作者的其他话题"}]
        _, messages = bind(rows=rows, quote={"message_id": "42", "sender_id": "200", "text": "图片"})
        result = prepare_request(ModelRequest(messages, [])).messages
        self.assertIn("对这张图的评论", str(result))
        self.assertNotIn("同作者的其他话题", str(result))

    def test_same_sentence_by_another_author_is_not_a_duplicate(self):
        history = [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "收到"}]
        rows = [{"message_id": "10", "user_id": "200", "text": "你好"},
                {"message_id": "11", "requester_id": "200", "reply_to_message_id": "10", "text": "收到"}]
        _, messages = bind(history=history, rows=rows)
        result = prepare_request(ModelRequest(messages, [])).messages
        self.assertIn('"message_id":"10"', result[-2]["content"])

    def test_quote_ancestors_survive_background_budget(self):
        rows = [{"message_id": "1", "user_id": "200", "text": "原提议"},
                {"message_id": "2", "user_id": "300", "reply_to_message_id": "1", "text": "对此的回复"},
                {"message_id": "3", "user_id": "400", "text": "其他主题" * 100}]
        _, messages = bind(rows=rows, quote={"message_id": "2", "sender_id": "300"},
                           policy={"group_tokens": 0})
        result = prepare_request(ModelRequest(messages, [])).messages
        payload = json.loads(result[-2]["content"].split("\n", 1)[1])
        self.assertEqual([r["message_id"] for r in payload["messages"]], ["1", "2"])

    def test_tool_messages_and_reasoning_are_not_rebuilt_or_truncated(self):
        _, messages = bind()
        prepare_request(ModelRequest(messages, []))
        continuation = [{"role": "assistant", "content": "", "reasoning_content": "完整推理", "encrypted_content": "cipher",
                         "tool_calls": [{"id": "c", "function": {"name": "read"}}]},
                        {"role": "tool", "tool_call_id": "c", "content": "完整结果" * 2000}]
        result = prepare_request(ModelRequest(messages + continuation, [])).messages
        self.assertEqual(result[-2:], continuation)

    def test_reference_projection_keeps_collisions_and_does_not_guess_unknown_names(self):
        snapshot = {"context": {"catalogs": {"players": [
            {"player_key": "a", "name": "同名", "qq": ["100"]},
            {"player_key": "b", "name": "同名", "qq": ["200"]},
            {"player_key": "c", "name": "另一个人", "qq": ["300"]}]}}, "directory": {"catalogs": []}}
        before = deepcopy(snapshot)
        result = reference_projection(snapshot, user_ids=["100"], query="同名最近怎样")
        self.assertEqual([p["player_key"] for p in result["players"]], ["a", "b"])
        unknown = reference_projection(snapshot, query="新称呼")
        self.assertEqual(unknown["players"], [])
        self.assertEqual(snapshot, before)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_automatic_history_excludes_later_concurrent_turns(self):
        bridge = AsyncMock()
        bridge.redact = lambda value: value
        bridge.call.return_value = [{"role": "user", "content": "较早", "turn": {"timestamp": 10}},
                                    {"role": "user", "content": "较晚", "turn": {"timestamp": 30}}]
        current = current_message("当前问题", actor={"user_id": "100"})
        observe_chat_event({"run_id": "run", "kind": "run.start", "data": {}, "metadata": {
            "chat_context": chat_metadata(current=current, context_count=0, user_id="100", timestamp=20)}})
        try:
            messages = await RemoteState(bridge).load_dialogue("own-session")
            self.assertEqual([message["content"] for message in messages], ["较早"])
        finally:
            observe_chat_event({"kind": "run.end", "run_id": "run"})

    async def test_optional_direct_history_uses_only_the_bound_session_and_reports_legacy_time_limits(self):
        from agent_runtime.models import ToolContext
        bridge = AsyncMock()
        bridge.call.return_value = [
            {"role": "user", "content": "原任务", "turn": {"timestamp": 10}},
            {"role": "assistant", "content": "完整作品", "turn": {"timestamp": 10}},
            {"role": "user", "content": "后来的消息", "turn": {"timestamp": 30}},
            {"role": "assistant", "content": "旧无时间记录"}]
        request = RunRequest("按之前的格式", "qq_g_200_100", Principal("100"), metadata={"message_timestamp": 20})
        result = await Capabilities(bridge).direct_history(ToolContext(request, None))
        bridge.call.assert_awaited_once_with("dialogue_load", session_id="qq_g_200_100")
        self.assertNotIn("后来的消息", str(result))
        self.assertIn("完整作品", str(result))
        self.assertTrue(result["legacy_timestamps_unknown"])

    async def test_saved_input_preserves_quote_for_the_next_short_followup_and_raw_question_for_memory(self):
        store = []
        async def call(op, **args):
            if op == "dialogue_load":
                return deepcopy(store)
            if op == "dialogue_save":
                store.extend([{"role": "user", "content": args["question"], "turn": args["turn"]},
                              {"role": "assistant", "content": args["answer"]}])
        bridge = type("Bridge", (), {"call": staticmethod(call), "redact": staticmethod(lambda e: e)})()
        state = RemoteState(bridge)
        captured = []
        class Model:
            async def complete_request(self, request, delta):
                captured.append(request)
                return {"message": {"role": "assistant", "content": "完整回答"}}
        runtime = AgentRuntime(model=ChatModel(Model()), registry=ToolRegistry(), state=state, output=Sink(), clock=Clock())
        for question, quote in [("你怎么看", {"sender_id": "200", "sender_name": "乙", "text": "原提议"}), ("那展开说说", None)]:
            current = current_message(question, actor={"user_id": "100"}, quote=quote)
            request = RunRequest(question, "session", Principal("100"), metadata={"chat_context":
                chat_metadata(current=current, context_count=0, user_id="100")})
            await runtime.run(request)
        self.assertEqual(store[0]["content"], "你怎么看")
        self.assertIn("原提议", str(captured[1].messages))
        self.assertIn('"sender_id":"200"', str(captured[1].messages))
        self.assertIn("完整回答", str(captured[1].messages))
        self.assertNotIn("turn", captured[1].messages[1])

    async def test_concurrent_chats_cannot_share_current_turn_or_history_selection(self):
        async def run(user):
            request, messages = bind(question=user)
            await asyncio.sleep(0)
            result = prepare_request(ModelRequest(messages, [])).messages
            observe_chat_event({"kind": "run.end", "run_id": request.run_id})
            return result[-1]["content"]
        first, second = await asyncio.gather(run("甲的问题"), run("乙的问题"))
        self.assertIn("甲的问题", str(first))
        self.assertNotIn("乙的问题", str(first))
        self.assertIn("乙的问题", str(second))
