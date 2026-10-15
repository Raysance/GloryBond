"""Canonical facts, bounded presentation context and graceful degradation."""

import asyncio
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch
import httpx
from agent_console.provider import DeepSeekModel

from agent_runtime import FinalizationContext, Principal, RunRequest
from agent_console.replies import (
    ReplyComposer,
    ReplyPolicy,
    DeliveryHistory,
    expression_role,
    source_packet,
    validate_chat,
)
from tests.test_agent_runtime import ScriptedModel


ROLE = json.loads(Path("shared/agent/roles/makise_kurisu.json").read_text())
DETAIL = "数据为8场5胜，胜率62.5%，样本还小，不能据此断言实力。"
CHAT = "8场5胜，62.5%。先别急着下结论，样本还小，证据总得够吧。"


def context():
    request = RunRequest(
        "这8场5胜说明我强吗？",
        "session",
        Principal(
            "owner", frozenset({"roleplay.use"}), {"identity": {"name": "示例玩家65"}}
        ),
    )
    messages = [
        {"role": "system", "content": "policy"},
        {"role": "user", "content": request.user_message},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c", "function": {"name": "custom_query"}}],
        },
        {
            "role": "tool",
            "tool_call_id": "c",
            "content": json.dumps(
                {"ok": True, "games": 8, "wins": 5, "win_rate": 0.625}
            ),
        },
        {"role": "assistant", "content": DETAIL},
    ]
    return FinalizationContext(request, DETAIL, messages)


class Roles:
    def __init__(self, selected=None, length="concise"):
        self.selected = selected or ROLE
        self.length = length
        self.users = []

    async def manage(self, principal):
        self.users.append(principal.user_id)
        return {
            "selected": copy.deepcopy(self.selected),
            "preferences": {"length": self.length, "address": "", "style": "少用表情"},
            "memories": ["喜欢玩安琪拉"],
        }


def response(chat=CHAT):
    return {
        "role": "assistant",
        "content": json.dumps({"chat": chat}, ensure_ascii=False),
    }


class ValidationTests(unittest.TestCase):
    def test_unknown_delivery_variant_cannot_select_an_arbitrary_output(self):
        with self.assertRaises(ValueError):
            validate_chat(json.dumps({'chat': CHAT, 'default_variant': 'private'}), DETAIL, ReplyPolicy())

    def test_numbers_percentage_conversion_and_links_are_preserved(self):
        policy = ReplyPolicy()
        chat = validate_chat(response()["content"], DETAIL, policy)
        self.assertEqual(chat, CHAT)
        for bad in [
            response(chat="8场6胜，75%。"),
            response(chat="**62.5%**"),
            response(chat="x" * 281),
            response(chat="数据见 https://unknown.example/data"),
        ]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_chat(bad["content"], DETAIL, policy)
        chat = validate_chat(
            response(chat="win rate 62.5%")["content"],
            "win_rate=0.625",
            policy,
        )
        self.assertIn("62.5%", chat)
        validate_chat(
            response(chat=CHAT + "\nhttps://example.com/data")["content"],
            DETAIL + " https://example.com/data",
            policy,
        )

    def test_empty_chat_and_unsupported_extra_fields_are_rejected(self):
        for value in [
            {},
            {"detailed": "x", "chat": " "},
            {"detailed": "x", "chat": "y", "user_id": "other"},
        ]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_chat(json.dumps(value), DETAIL, ReplyPolicy())

    def test_presentation_uses_one_answer_even_with_conflicting_raw_sources(self):
        ctx = context()
        ctx.messages.insert(1, {"role": "assistant", "content": "旧结论：8负5胜"})
        ctx.messages[-2]["content"] = json.dumps(
            {"unrelated_chat": "他在17场里输9场", "example": "5胜8负"}
        )
        original = copy.deepcopy(ctx.messages)
        packet = source_packet(ctx)
        self.assertEqual(packet, {"question": ctx.request.user_message, "answer": DETAIL})
        self.assertNotIn("5胜8负", json.dumps(packet, ensure_ascii=False))
        self.assertNotIn("17场", json.dumps(packet, ensure_ascii=False))
        self.assertEqual(ctx.messages, original)

    def test_role_voice_excludes_biography_and_old_profiles_keep_expression(self):
        packet = expression_role(ROLE)
        self.assertEqual(packet["voice"], ROLE["voice"])
        self.assertNotIn("profile", packet)
        legacy = expression_role(
            {"name": "角色", "profile": json.dumps({
                "background": "很长的剧情", "personality": "温和", "speech_style": "短句"
            })}
        )
        self.assertEqual(legacy["expression"], {"personality": "温和", "speech_style": "短句"})


class ComposerTests(unittest.IsolatedAsyncioTestCase):
    async def test_qq_variant_selection_requires_a_valid_explicit_choice(self):
        invalid = response()
        valid = response()
        value = json.loads(valid['content'])
        value['default_variant'] = 'detailed'
        valid['content'] = json.dumps(value, ensure_ascii=False)
        model = ScriptedModel([invalid, valid])
        events = []
        async def emit(kind, data, **kwargs):
            events.append(kind)
        answer = await ReplyComposer(model=model, roles=Roles(),
                                     policy=ReplyPolicy(select_delivery_variant=True)).finalize(context(), emit)
        self.assertEqual(answer.text, DETAIL)
        self.assertEqual(answer.variants['chat'], CHAT)
        self.assertEqual(answer.metadata['default_variant'], 'detailed')
        self.assertIn('reply.validation', events)
        self.assertEqual(len(model.requests), 2)

    async def test_json_mode_wire_request_is_tool_free_and_preserves_usage(self):
        observed = []

        def transport(request):
            observed.append(json.loads(request.content))
            frame = {
                "choices": [
                    {
                        "delta": {"content": response()["content"]},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 200,
                    "completion_tokens": 40,
                    "total_tokens": 240,
                },
            }
            return httpx.Response(
                200, text="data: " + json.dumps(frame) + "\n\ndata: [DONE]\n\n"
            )

        client_type = httpx.AsyncClient
        model = DeepSeekModel(
            api_key="test-key",
            base_url="https://api.deepseek.com",
            model="text-model",
            thinking=False,
            response_format={"type": "json_object"},
        )
        with patch(
            "agent_console.provider.httpx.AsyncClient",
            side_effect=lambda **kw: client_type(
                transport=httpx.MockTransport(transport), **kw
            ),
        ):
            result = await model.complete(
                [{"role": "user", "content": "JSON response"}], [], AsyncMock()
            )
        self.assertEqual(observed[0]["response_format"], {"type": "json_object"})
        self.assertEqual(observed[0]["thinking"], {"type": "disabled"})
        self.assertNotIn("tools", observed[0])
        self.assertEqual(result["usage"]["total_tokens"], 240)

    async def test_group_text_is_default_detail_is_immutable_and_history_not_doubled(self):
        roles = Roles()
        model = ScriptedModel([response()])
        events = []

        async def emit(kind, data, **kw):
            events.append((kind, data, kw))

        answer = await ReplyComposer(model=model, roles=roles).finalize(context(), emit)
        self.assertEqual(answer.text, CHAT)
        self.assertEqual(answer.variants, {"detailed": DETAIL, "chat": CHAT})
        self.assertEqual(DETAIL, answer.history_text)
        self.assertEqual(roles.users, ["owner"])
        self.assertEqual(answer.metadata["role_id"], "makise_kurisu")
        packet = json.loads(model.requests[0][1]["content"])
        self.assertEqual(packet["role"]["voice"]["examples"], ROLE["voice"]["examples"])
        self.assertNotIn("profile", packet["role"])
        self.assertEqual(packet["answer"], DETAIL)
        self.assertEqual(set(packet), {"question", "answer", "role", "preferences"})
        self.assertNotIn("喜欢玩安琪拉", json.dumps(packet, ensure_ascii=False))
        self.assertEqual(packet["preferences"]["style"], "少用表情")
        self.assertEqual(model.schemas, [[]])
        self.assertEqual(
            [e[0] for e in events], ["reply.model.request", "reply.model.response"]
        )

    async def test_latest_role_is_used_even_when_original_task_prompt_has_old_role(
        self,
    ):
        neutral = json.loads(Path("shared/agent/roles/assistant.json").read_text())
        model = ScriptedModel(
            [response(chat="8场5胜，胜率62.5%。样本较少，暂时不足以判断实力。")]
        )

        async def emit(*args, **kw):
            pass

        answer = await ReplyComposer(
            model=model,
            roles=Roles(neutral),
            policy=ReplyPolicy(history_variant="chat"),
        ).finalize(context(), emit)
        self.assertEqual(answer.metadata["role_id"], "assistant")
        self.assertEqual(answer.history_text, answer.text)
        self.assertEqual(
            json.loads(model.requests[0][1]["content"])["role"]["voice"]["tone"],
            neutral["voice"]["tone"],
        )

    async def test_literal_guard_repair_does_not_repeat_tools_or_mutate_detail(self):
        model = ScriptedModel([response(chat="8场6胜，75%。"), response()])
        events = []

        async def emit(kind, data, **kw):
            events.append(kind)

        answer = await ReplyComposer(model=model, roles=Roles()).finalize(
            context(), emit
        )
        self.assertEqual(answer.text, CHAT)
        self.assertEqual(answer.variants["detailed"], DETAIL)
        self.assertEqual(len(model.requests), 2)
        self.assertEqual(model.schemas, [[], []])
        self.assertIn("reply.validation", events)
        self.assertNotIn("tool.call", events)

    async def test_repair_exhaustion_keeps_original_detail_and_reports_degradation(
        self,
    ):
        model = ScriptedModel(
            [
                {"role": "assistant", "content": "invalid json"},
                response(chat="new number 999"),
            ]
        )
        events = []

        async def emit(kind, data, **kw):
            events.append(kind)

        answer = await ReplyComposer(model=model, roles=Roles()).finalize(
            context(), emit
        )
        self.assertTrue(answer.metadata["degraded"])
        self.assertEqual(answer.variants["detailed"], DETAIL)
        self.assertEqual(answer.history_text, DETAIL)
        self.assertEqual(len(model.requests), 2)
        self.assertIn("reply.failure", events)
        self.assertIn("run.warning", events)

    async def test_large_source_keeps_original_without_truncation_or_model_call(self):
        ctx = context()
        draft = DETAIL * 100
        ctx = FinalizationContext(ctx.request, draft, ctx.messages)
        model = ScriptedModel([])

        async def emit(*args, **kw):
            pass

        answer = await ReplyComposer(
            model=model, roles=Roles(), policy=ReplyPolicy(source_max_chars=1000)
        ).finalize(ctx, emit)
        self.assertTrue(answer.metadata["degraded"])
        self.assertEqual(answer.history_text, draft)
        self.assertEqual(model.requests, [])

    async def test_concise_preference_changes_generation_budget_before_request(self):
        long_chat = "自然中文" * 40

        async def emit(*args, **kw):
            pass

        concise_model = ScriptedModel([response(chat=long_chat), response()])
        answer = await ReplyComposer(model=concise_model, roles=Roles()).finalize(context(), emit)
        self.assertIn("最多100字", concise_model.requests[0][0]["content"])
        self.assertEqual(len(concise_model.requests), 2)
        self.assertEqual(answer.text, CHAT)
        standard_model = ScriptedModel([response(chat=long_chat)])
        answer = await ReplyComposer(model=standard_model, roles=Roles(length="standard")).finalize(context(), emit)
        self.assertIn("最多280字", standard_model.requests[0][0]["content"])
        self.assertEqual(len(standard_model.requests), 1)
        self.assertEqual(answer.text, long_chat)

    async def test_no_role_permission_never_reads_user_role_or_memory(self):
        ctx = context()
        principal = Principal("old-task", frozenset())
        ctx = FinalizationContext(RunRequest("问题", "session", principal), DETAIL, ctx.messages)
        roles = Roles()
        model = ScriptedModel([response()])

        async def emit(*args, **kw):
            pass

        await ReplyComposer(model=model, roles=roles).finalize(ctx, emit)
        self.assertEqual(roles.users, [])
        packet = json.loads(model.requests[0][1]["content"])
        self.assertEqual(packet["role"]["name"], "通用助手")

    async def test_phase_timeout_degrades_and_user_cancellation_propagates(self):
        started = asyncio.Event()

        class Pending:
            async def complete(self, *args):
                started.set()
                await asyncio.Event().wait()

        async def emit(*args, **kw):
            pass

        answer = await ReplyComposer(
            model=Pending(), roles=Roles(), policy=ReplyPolicy(timeout_seconds=0.01)
        ).finalize(context(), emit)
        self.assertTrue(answer.metadata["degraded"])
        started.clear()
        task = asyncio.create_task(
            ReplyComposer(model=Pending(), roles=Roles()).finalize(context(), emit)
        )
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


class StagedDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_web_delivery_history_keeps_parts_out_of_expression_input_and_variants(self):
        from types import SimpleNamespace
        from agent_console.server import EventBroker
        ctx = context()
        broker = EventBroker(SimpleNamespace(redact=lambda value: value))
        part = '第一部分：统计的适用范围有限。'
        await broker.publish({'run_id': ctx.request.run_id, 'session_id': 'session',
                              'kind': 'output.message', 'data': {'kind': 'partial', 'text': part}})
        model = ScriptedModel([response()])
        composer = ReplyComposer(model=model, roles=Roles(), delivery_history=broker.delivery_history)
        answer = await composer.finalize(ctx, AsyncMock())
        self.assertEqual(answer.history_text, part + '\n\n' + DETAIL)
        self.assertEqual(answer.variants['detailed'], DETAIL)
        self.assertEqual(answer.text, CHAT)
        self.assertNotIn(part, json.dumps(model.requests, ensure_ascii=False))
        await broker.publish({'run_id': ctx.request.run_id, 'session_id': 'session',
                              'kind': 'run.end', 'data': {'status': 'completed'}})
        self.assertEqual(broker.delivery_history.parts, {})

    async def test_concurrent_run_isolation_and_failure_fallback_preserve_only_answer_parts(self):
        ctx = context()
        history = DeliveryHistory()
        for run, kind, text in ((ctx.request.run_id, 'partial', '已发送的依据。'),
                                 ('other', 'partial', '别人的回答'),
                                 (ctx.request.run_id, 'progress', '正在生成'),
                                 (ctx.request.run_id, 'notification', '定时提醒')):
            history.record({'run_id': run, 'kind': 'output.message', 'data': {'kind': kind, 'text': text}})
        composer = ReplyComposer(model=ScriptedModel([{'role': 'assistant', 'content': 'invalid'}]),
                                 roles=Roles(), policy=ReplyPolicy(max_attempts=1), delivery_history=history)
        answer = await composer.finalize(ctx, AsyncMock())
        self.assertTrue(answer.metadata['degraded'])
        self.assertEqual(answer.history_text, '已发送的依据。\n\n' + DETAIL)


if __name__ == "__main__":
    unittest.main()
