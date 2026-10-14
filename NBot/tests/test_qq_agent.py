"""The QQ adapter runs the shared engine with bounded, trusted destinations."""

import asyncio
import copy
import json
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import httpx
from PIL import Image

from agent_runtime import AgentRuntime
from qq_agent.service import QQAgentService, qq_principal
from qq_agent.member_profiles import register_member_profile_tool
from agent_console.remote import RemoteBridge


ROOT = Path(__file__).parents[1]
ROLE = json.loads((ROOT / "shared/agent/roles/makise_kurisu.json").read_text())
REFERENCES = {"directory": {}, "context": {"catalogs": {"players": [
    {"player_key": "lry", "name": "阳大师", "qq": ["100"]}
]}}}


def call(name, args, identifier):
    return {"id": identifier, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class IdentityTests(unittest.TestCase):
    def test_bot_identity_is_bound_without_replacing_sender_or_authority(self):
        principal = qq_principal('100', '200', '', admin_id='999', references=REFERENCES, bot_id='300')
        self.assertEqual(principal.attributes['bot'], {'user_id': '300'})
        self.assertEqual(principal.user_id, '100')
        self.assertEqual(principal.attributes['identity']['player_key'], 'lry')
        self.assertNotIn('chat.cross_group', principal.scopes)
        self.assertEqual(principal.attributes['delivery']['recipient_id'], '200')
        self.assertEqual(principal.attributes['delivery']['mention_user_id'], '100')
        with self.assertRaises(ValueError):
            qq_principal('100', '200', '', admin_id='999', references=REFERENCES, bot_id='lry')

    def test_admin_default_group_is_a_query_hint_not_a_group_event_or_destination(self):
        for user, group in [('999', None), ('999', '200'), ('101', None)]:
            principal = qq_principal(user, group, '', admin_id='999', references=REFERENCES,
                                     admin_private_default_group_id='2000000000')
            if user == '999' and group is None:
                self.assertEqual(principal.attributes['chat']['default_group_id'], '2000000000')
                self.assertIsNone(principal.attributes['chat']['group_id'])
                self.assertEqual(principal.attributes['delivery'], {'platform': 'qq', 'channel': 'private', 'recipient_id': '999'})
            else:
                self.assertNotIn('default_group_id', principal.attributes['chat'])

    def test_group_never_gets_cross_group_authority_even_for_admin(self):
        group = qq_principal("999", "200", "admin", admin_id="999", references=REFERENCES)
        self.assertIn("chat.read", group.scopes)
        self.assertNotIn("chat.cross_group", group.scopes)
        self.assertFalse(group.attributes["chat"]["all_groups"])
        private = qq_principal("999", None, "admin", admin_id="999", references=REFERENCES)
        self.assertIn("chat.cross_group", private.scopes)
        ordinary = qq_principal("101", None, "user", admin_id="999", references=REFERENCES, use_memory=False)
        self.assertNotIn("chat.read", ordinary.scopes)
        self.assertNotIn("memory.use", ordinary.scopes)
        self.assertIn("roleplay.use", ordinary.scopes)

    def test_real_sender_resolves_independently_of_local_lry_default(self):
        user = qq_principal("101", "200", "第二个用户", admin_id="999", references=REFERENCES)
        self.assertEqual(user.user_id, "101")
        self.assertEqual(user.attributes["identity"], {"name": "第二个用户"})
        known = qq_principal("100", "200", "old nickname", admin_id="999", references=REFERENCES)
        self.assertEqual(known.attributes["identity"], {"name": "阳大师", "player_key": "lry"})
        with self.assertRaises(ValueError):
            qq_principal("lry", "200", "name", admin_id="999", references=REFERENCES)


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.events, self.dialogue, self.calls, self.sent = {}, {}, [], []
        self.script = []
        self.reply_text = "记住了。10秒一条，发3次。"
        self.reply_variant = None
        test = self

        class Bridge:
            secrets = ["test-key"]
            redact = RemoteBridge.redact

            def __init__(self, *args):
                pass

            async def start(self):
                return {"private": {"api_key": "test-key"}, "public": {
                    "model": "test-model", "base_url": "https://example.invalid",
                    "proxy_url": "http://configured-proxy.invalid:7890",
                    "references": REFERENCES, "season_start": "2026-01-01",
                }}

            async def call(self, op, **args):
                test.calls.append((op, copy.deepcopy(args)))
                session = args.get("session_id")
                if op == "state_append":
                    test.events.setdefault(session, []).append(args["event"])
                    return True
                if op == "dialogue_load":
                    return test.dialogue.get(session, [])
                if op == "dialogue_save":
                    test.dialogue.setdefault(session, []).extend([
                        {"role": "user", "content": args["question"]},
                        {"role": "assistant", "content": args["answer"]},
                    ])
                    return True
                if op == "reference_snapshot":
                    return REFERENCES
                if op == "roleplay":
                    return {"selected": ROLE, "preferences": {"length": "concise", "address": "", "style": ""}, "roles": [ROLE]}
                if op == "memory":
                    return {"memories": []} if args["action"] == "recall" else {"saved": True}
                if op == "search_history":
                    return {"messages": []}
                if op == "task_create":
                    return {"task_id": "t", "created": True, "max_runs": args["max_runs"]}
                if op == "task_due":
                    return []
                if op in {"task_active", "task_finish"}:
                    return True
                raise AssertionError(op)

            async def close(self):
                pass

        class Model:
            def __init__(self, **options):
                self.reply = bool(options.get("response_format"))
                self.options = options
                self.requests = []

            async def complete(self, messages, tools, delta):
                value = {"chat": test.reply_text}
                if test.reply_variant is not None:
                    value['default_variant'] = test.reply_variant
                return {"message": {"role": "assistant", "content": json.dumps(value, ensure_ascii=False)}}

            async def complete_request(self, request, delta):
                self.requests.append(request)
                message = test.script.pop(0)
                return {"message": message, "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                        "request_payload": {"messages": copy.deepcopy(request.messages), "tool_choice": request.tool_choice},
                        "response_payload": message}

        async def send(packet, delivery):
            test.sent.append((packet, delivery))

        async def prepare(packet):
            return {**packet, "trace_url": "https://example.invalid/chat-trace"}

        async def artifact(identifier, raw):
            return {"artifact_id": identifier, "path": "/tmp/test.png"}

        self.gateway = QQAgentService(root=ROOT, config={"log_directory": self.tmp.name, "image_directory": self.tmp.name},
                                      admin_id="999", bot_id="300", sender=send, prepare_reply=prepare, store_artifact=artifact,
                                      formatter=lambda text: text, bridge_factory=Bridge, model_factory=Model)
        await self.gateway.start()
        self.addAsyncCleanup(self.gateway.close)

    async def test_model_uses_configured_remote_proxy_and_model_as_vision_fallback(self):
        self.assertEqual(self.gateway.model.options['proxy_url'], 'http://configured-proxy.invalid:7890')
        self.assertEqual(self.gateway.model.options['vision_model'], 'test-model')

    async def test_reply_delivery_uses_model_intent_instead_of_question_keywords(self):
        composer = self.gateway.runtime.finalizer.composer
        composer.policy = composer.policy.model_copy(update={'select_delivery_variant': True})
        draft = '事实底稿：机器人支持查询近期群聊，但只读取授权范围。'
        self.reply_text = '可以查近期群聊，范围受当前会话权限限制。'
        cases = [('不用详细解释，简短说能否逐一统计所有玩家。', 'chat', self.reply_text),
                 ('Please show the full explanation and supporting evidence.', 'detailed', draft)]
        for question, variant, expected in cases:
            with self.subTest(question=question):
                self.reply_variant = variant
                self.script = [
                    {'role': 'assistant', 'content': '', 'tool_calls': [call('discover_tools', {'categories': ['bot_info']}, 'd')]},
                    {'role': 'assistant', 'content': draft},
                ]
                result = await self.gateway.chat(user_text=question, user_id='101', nickname='用户')
                self.assertEqual(result['text'], expected)
                self.assertEqual(self.dialogue['qq_p_101'][-1]['content'], expected)
                self.assertEqual(result['variants']['detailed'], draft)

    async def test_bot_avatar_request_uses_bound_bot_and_keeps_sender_history(self):
        reader = AsyncMock(return_value={'profile': {'group_id': '200', 'user_id': '300', 'nickname': '机器人'},
                                         'avatar_bytes': None, 'avatar_error': '头像暂不可用'})
        register_member_profile_tool(self.gateway.runtime.registry, reader=reader,
                                     store_image=self.gateway.store_tool_image, now=self.gateway.clock.now)
        self.reply_text = '我的头像暂时读取失败。'
        self.script = [
            {'role': 'assistant', 'content': '', 'tool_calls': [call('search_chat_history', {'queries': ['机器人头像', 'QQ头像']}, 'h')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [call('discover_tools', {'categories': ['references']}, 'd')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [call('read_group_member_profile', {'target': 'bot'}, 'p')]},
            {'role': 'assistant', 'content': self.reply_text},
        ]
        await self.gateway.chat(user_text='你的QQ头像是什么？', user_id='100', nickname='提问者', group_id='200')
        reader.assert_awaited_once_with(group_id='200', user_id='300', include_avatar=True)
        prompt = self.gateway.model.requests[0].messages[0]['content']
        self.assertIn('机器人QQ为 300', prompt)
        self.assertIn('本次提问者QQ为 100', prompt)
        self.assertIn("target='bot'", prompt)
        self.assertEqual(self.dialogue['qq_g_200_100'][-1]['content'], self.reply_text)
        self.assertTrue(all(delivery['recipient_id'] == '200' for _, delivery in self.sent))

    async def test_admin_private_query_uses_configured_default_without_changing_private_history(self):
        self.gateway.config['admin_private_default_group_id'] = '2000000000'
        self.reply_text = '默认群已确认。'
        self.script = [
            {'role': 'assistant', 'content': '', 'tool_calls': [call('search_chat_history', {'queries': ['默认群', '群信息']}, 'h')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [call('discover_tools', {'categories': ['chat_history']}, 'd')]},
            {'role': 'assistant', 'content': '默认群已确认。'},
        ]
        await self.gateway.chat(user_text='默认查询哪个群？', user_id='999', nickname='管理员', message_id=42)
        search = next(args for op, args in self.calls if op == 'search_history')
        self.assertEqual(search['principal']['default_group_id'], '2000000000')
        self.assertIsNone(search['principal']['group_id'])
        self.assertIn('qq_p_999', self.dialogue)
        self.assertTrue(all(delivery['channel'] == 'private' and delivery['recipient_id'] == '999' for _, delivery in self.sent))
        self.assertIn('2000000000', self.gateway.model.requests[0].messages[0]['content'])

    async def test_real_engine_binds_memory_tasks_and_multiple_messages_to_sender(self):
        self.assertIsInstance(self.gateway.runtime, AgentRuntime)
        self.script = [
            {"role": "assistant", "content": "", "tool_calls": [call("search_chat_history", {"queries": ["偏好", "提醒"]}, "h")]},
            {"role": "assistant", "content": "", "tool_calls": [call("discover_tools", {"categories": ["memory", "tasks"]}, "d")]},
            {"role": "assistant", "content": "", "tool_calls": [
                call("remember_memory", {"content": "喜欢玩安琪拉"}, "m"),
                call("emit_message", {"text": "记忆已保存，正在设置提醒。"}, "e"),
                call("create_task", {"kind": "message", "message": "提醒 {run}", "interval_seconds": 10, "max_runs": 3}, "t"),
            ]},
            {"role": "assistant", "content": "记忆已保存。之后每10秒发一条提醒，共3次。"},
        ]
        result = await self.gateway.chat(user_text="记住我喜欢安琪拉，每10秒发一条消息，共3次。", user_id="101", nickname="B", group_id="200", message_id=300)
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(result["text"], "记住了。10秒一条，发3次。")
        self.assertTrue(all(delivery == {"platform": "qq", "channel": "group", "recipient_id": "200",
                                       "mention_user_id": "101"} for _, delivery in self.sent))
        self.assertTrue(all(args["user_id"] == "101" for op, args in self.calls if op == "memory"))
        task = next(args for op, args in self.calls if op == "task_create")
        self.assertEqual(task["principal"]["user_id"], "101")
        self.assertEqual(task["principal"]["attributes"]["delivery"]["recipient_id"], "200")
        self.assertEqual(task["principal"]["attributes"]["delivery"]["mention_user_id"], "101")
        self.assertEqual(task["session_id"], "qq_g_200_101")
        self.assertEqual(next(args for op, args in self.calls if op == "search_history")["exclude_message_id"], 300)
        self.assertEqual(self.gateway.model.requests[0].tool_choice["function"]["name"], "search_chat_history")
        self.assertEqual(self.gateway.model.requests[1].tool_choice["function"]["name"], "discover_tools")
        self.assertEqual(self.dialogue["qq_g_200_101"][-1]["content"], result["text"])
        self.assertGreater(result["trace"]["summary"]["token_usage"]["total_tokens"], 0)

    async def test_private_has_no_group_tool_and_qq_runner_is_separate(self):
        self.script = [
            {"role": "assistant", "content": "", "tool_calls": [call("discover_tools", {"categories": ["memory"]}, "d")]},
            {"role": "assistant", "content": "说明已有事实，共3次，间隔10秒。"},
        ]
        await self.gateway.chat(user_text="查询本人偏好", user_id="101", nickname="B", use_memory=False)
        self.assertFalse(any(op == "search_history" for op, args in self.calls))
        self.assertEqual(self.gateway.model.requests[0].tool_choice["function"]["name"], "discover_tools")
        self.assertEqual(self.sent[-1][1]["recipient_id"], "101")
        self.assertEqual(self.sent[-1][1]["channel"], "private")
        await self.gateway.tick()
        self.assertEqual([args["channel"] for op, args in self.calls if op == "task_due"], ["qq"])

    async def test_untrusted_image_source_is_rejected_without_a_request(self):
        for url in ("http://127.0.0.1/secret", "file:///etc/passwd", "https://qq.com.evil.test/a.png"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                await self.gateway.input_images([url])

    async def test_quote_is_current_only_and_dialogue_restores_native_roles(self):
        self.script = [
            {"role": "assistant", "content": "", "tool_calls": [call("discover_tools", {"categories": ["references"]}, "d")]},
            {"role": "assistant", "content": "记忆已保存。10秒一条，共3次。"},
        ] * 2
        await self.gateway.chat(user_text="看引用", user_id="101", nickname="B", use_memory=False,
                                quoted_message={"text": "QUOTE_ONLY", "available": True})
        self.assertIn("QUOTE_ONLY", json.dumps(self.gateway.model.requests[0].messages))
        self.assertNotIn("QUOTE_ONLY", json.dumps([m for m in self.gateway.model.requests[0].messages if m["role"] == "system"]))
        self.assertNotIn("QUOTE_ONLY", json.dumps(self.dialogue))
        await self.gateway.chat(user_text="接着说", user_id="101", nickname="B", use_memory=False)
        followup = self.gateway.model.requests[2].messages
        self.assertNotIn("QUOTE_ONLY", json.dumps(followup))
        self.assertTrue(any(m["role"] == "user" and m["content"] == "看引用" for m in followup))
        self.assertTrue(any(m["role"] == "assistant" and m["content"] == self.sent[0][0]["text"] for m in followup))

    async def test_webpages_from_message_and_authorized_quote_are_current_only(self):
        from tests.test_agent_webpages import fetcher, response
        requests = []
        def handler(request):
            requests.append(request)
            return response()
        self.gateway.webpages, _, _ = fetcher(handler)
        self.script = [
            {"role": "assistant", "content": "", "tool_calls": [call("discover_tools", {"categories": ["references"]}, "d")]},
            {"role": "assistant", "content": "已读取网页正文。"},
        ] * 2
        question = "帮我总结 https://example.com/article#current"
        await self.gateway.chat(user_text=question, user_id="101", nickname="B", use_memory=False,
                                quoted_message={"text": "https://example.com/article#quoted", "available": True})
        self.assertEqual(len(requests), 1)
        messages = self.gateway.model.requests[0].messages
        page = next(message for message in messages if "安琪拉技能伤害提升" in json.dumps(message, ensure_ascii=False))
        self.assertEqual(page["role"], "user")
        self.assertIn('"origins": ["message", "quote"]', page["content"])
        self.assertNotIn("安琪拉技能伤害提升", json.dumps([m for m in messages if m["role"] == "system"], ensure_ascii=False))
        self.assertNotIn("安琪拉技能伤害提升", json.dumps(self.dialogue, ensure_ascii=False))
        self.assertEqual(self.dialogue["qq_p_101"][0]["content"], question)
        await self.gateway.chat(user_text="接着说", user_id="101", nickname="B", use_memory=False,
                                quoted_message={"text": "https://unavailable.invalid/", "available": False})
        self.assertEqual(len(requests), 1)
        self.assertNotIn("安琪拉技能伤害提升", json.dumps(self.gateway.model.requests[2].messages, ensure_ascii=False))
        start = next(row for row in self.events['qq_p_101'] if row['kind'] == 'run.start')
        self.assertIn("安琪拉技能伤害提升", json.dumps(start, ensure_ascii=False))

    async def test_qq_image_download_becomes_native_input_and_is_saved(self):
        buffer = BytesIO()
        Image.new("RGB", (16, 16), "red").save(buffer, "PNG")
        raw = buffer.getvalue()
        real_client = httpx.AsyncClient
        with patch("qq_agent.service.httpx.AsyncClient", side_effect=lambda **kw: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=raw)), **kw)):
            images = await self.gateway.input_images(["https://gchat.qpic.cn/test"])
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].content_part()["type"], "image_url")
        wire, _ = self.gateway.image_store.model_messages([{"role": "user", "content": [images[0].content_part()]}])
        self.assertTrue(wire[0]["content"][0]["image_url"]["url"].startswith("data:image/png;base64,"))

    async def test_quoted_pixels_are_transient_native_context_without_history_or_system_injection(self):
        self.script = [
            {"role":"assistant", "content":"", "tool_calls":[call("discover_tools", {"categories":["references"]}, "d")]},
            {"role":"assistant", "content":"读到了引用图片。"},
        ]
        buffer = BytesIO()
        Image.new("RGB", (16,16), "red").save(buffer, "PNG")
        saved = self.gateway.image_store.save(buffer.getvalue(), "引用图片")
        from unittest.mock import AsyncMock
        image = self.gateway.image_store.inputs([saved["id"]])[0]
        with patch.object(self.gateway, "input_images", AsyncMock(return_value=(image,))) as download:
            await self.gateway.chat(user_text="这张图是什么意思", user_id="101", nickname="B",
                quoted_message={"available":True, "text":"QUOTE_ONLY[image消息，未读取内容]",
                                "image_urls":["https://gchat.qpic.cn/reference"]})
        download.assert_awaited_once_with(["https://gchat.qpic.cn/reference"])
        messages = self.gateway.model.requests[0].messages
        context = next(m for m in messages if "QUOTE_ONLY" in json.dumps(m))
        self.assertEqual(context["role"], "user")
        self.assertEqual(context["content"][1], image.content_part())
        self.assertNotIn("QUOTE_ONLY", json.dumps([m for m in messages if m["role"] == "system"]))
        self.assertNotIn("QUOTE_ONLY", json.dumps(self.dialogue))
        self.assertNotIn("attachment://", json.dumps(self.dialogue))

    async def test_napcat_dynamic_sticker_download_reaches_vision_as_sampled_png(self):
        from tests.test_agent_animations import animation
        raw = animation()
        real_client = httpx.AsyncClient
        with patch("qq_agent.service.httpx.AsyncClient", side_effect=lambda **kw: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=raw)), **kw)):
            images = await self.gateway.input_images(["https://gxh.vip.qq.com/club/item/parcel/item/ab/test/raw300.gif"])
        source_id = images[0].url.removeprefix("attachment://")
        self.assertEqual(self.gateway.image_store.load(source_id)[0]["frames"], 8)
        wire, _ = self.gateway.image_store.model_messages([{"role":"user", "content":[images[0].content_part()]}])
        self.assertTrue(wire[0]["content"][1]["image_url"]["url"].startswith("data:image/png;"))

    async def test_fixed_background_messages_emit_once_and_keep_bound_destination(self):
        from agent_console.tasks import task_request
        principal = qq_principal("101", "200", "B", admin_id="999", references=REFERENCES)
        from dataclasses import asdict
        for count in range(3):
            task = {"task_id": "t", "session_id": "qq_g_200_101", "principal": asdict(principal),
                    "kind": "message", "message": "第{run}/{max_runs}次", "runs": count, "max_runs": 3, "lease_token": "lease"}
            self.assertEqual(task_request(task).metadata["delivery"]["recipient_id"], "200")
            await self.gateway.scheduler.perform(task)
        self.assertEqual([p["text"] for p, _ in self.sent], ["第1/3次", "第2/3次", "第3/3次"])
        self.assertFalse(self.gateway.model.requests)
        self.assertFalse(self.gateway.output.events)
        self.assertFalse(self.gateway.output.results)

    async def test_model_failure_keeps_observations_and_sends_trace(self):
        self.script = [{"role": "assistant", "content": "", "tool_calls": [call("discover_tools", {"categories": ["references"]}, "d")]}]
        result = await self.gateway.chat(user_text="失败测试", user_id="101", nickname="B", use_memory=False)
        self.assertEqual(result["trace"]["status"], "error")
        self.assertEqual(result["trace"]["rounds"][0]["tools"][0]["name"], "discover_tools")
        self.assertIn("未完成", self.sent[-1][0]["text"])
        self.assertEqual(len(self.sent), 1)
        self.assertFalse(self.dialogue)
