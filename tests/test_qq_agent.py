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
    {"player_key": "example_user_10", "name": "示例玩家65", "qq": ["100"]}
]}}}


def call(name, args, identifier):
    return {"id": identifier, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class IdentityTests(unittest.TestCase):
    def test_bot_identity_is_bound_without_replacing_sender_or_authority(self):
        principal = qq_principal('100', '200', '', admin_id='999', references=REFERENCES, bot_id='300')
        self.assertEqual(principal.attributes['bot'], {'user_id': '300'})
        self.assertEqual(principal.user_id, '100')
        self.assertEqual(principal.attributes['identity']['player_key'], 'example_user_10')
        self.assertNotIn('chat.cross_group', principal.scopes)
        self.assertEqual(principal.attributes['delivery']['recipient_id'], '200')
        self.assertEqual(principal.attributes['delivery']['mention_user_id'], '100')
        with self.assertRaises(ValueError):
            qq_principal('100', '200', '', admin_id='999', references=REFERENCES, bot_id='example_user_10')

    def test_admin_default_group_is_a_query_hint_not_a_group_event_or_destination(self):
        for user, group in [('999', None), ('999', '200'), ('101', None)]:
            principal = qq_principal(user, group, '', admin_id='999', references=REFERENCES,
                                     admin_private_default_group_id='2000000001')
            if user == '999' and group is None:
                self.assertEqual(principal.attributes['chat']['default_group_id'], '2000000001')
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
        self.assertEqual(known.attributes["identity"], {"name": "示例玩家65", "player_key": "example_user_10"})
        with self.assertRaises(ValueError):
            qq_principal("example_user_10", "200", "name", admin_id="999", references=REFERENCES)


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.events, self.dialogue, self.calls, self.sent = {}, {}, [], []
        self.script = []
        self.reply_text = "记住了。10秒一条，发3次。"
        self.reply_variant = None
        self.group_messages, self.group_replies = {}, {}
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
                if op == "recent_history":
                    group = args['principal']['group_id']
                    return {'messages': test.group_messages.get(group, [])}
                if op == "qq_group_replies":
                    return {'messages': test.group_replies.get(args['principal']['group_id'], [])}
                if op == "qq_group_reply_save":
                    test.group_replies.setdefault(args['delivery']['recipient_id'], []).append({
                        'text': args['text'], 'timestamp': 2, 'mention_user_id': args['delivery'].get('mention_user_id')})
                    return True
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

    async def test_lazy_business_image_uses_trusted_local_output_and_bound_destination(self):
        from agent_console.function_calls import FunctionArgs, FunctionCatalog, FunctionOutput
        await self.gateway.close()
        catalog = FunctionCatalog()
        catalog.register(name="query_chart", description="查询图表", category="visuals",
            args_model=FunctionArgs, handler=lambda args, ctx: FunctionOutput(text="真实图表", images=["/source/chart.png"]))
        self.gateway.business_functions = catalog
        self.gateway.business_image_loader = AsyncMock(side_effect=lambda path, identifier:
            {"artifact_id": identifier, "path": "/trusted/chat_plot_" + identifier + ".png"})
        await self.gateway.start()
        self.reply_text = "图表已生成。"
        self.script = [
            {"role": "assistant", "content": "", "tool_calls": [call("search_chat_history", {"queries": ["图表", "趋势"]}, "h")]},
            {"role": "assistant", "content": "", "tool_calls": [call("discover_tools", {"categories": ["hok_business"]}, "d")]},
            {"role": "assistant", "content": "", "tool_calls": [call("describe_hok_function", {"name": "query_chart"}, "s")]},
            {"role": "assistant", "content": "", "tool_calls": [call("call_hok_function", {"name": "query_chart"}, "c")]},
            {"role": "assistant", "content": "真实图表"},
        ]
        await self.gateway.chat(user_text="画图", user_id="100", nickname="用户", group_id="200")
        self.gateway.business_image_loader.assert_awaited_once()
        packet, delivery = self.sent[-1]
        self.assertEqual(len(packet["artifacts"]), 1)
        self.assertTrue(packet["artifacts"][0]["path"].startswith("/trusted/chat_plot_"))
        self.assertEqual(delivery["recipient_id"], "200")
        self.assertNotIn("/source/chart.png", json.dumps(packet["trace"]))
        self.assertFalse(self.gateway.output.local_artifacts)

    async def test_quoted_reminder_can_be_attributed_and_cancelled_by_another_group_member(self):
        from agent_console import remote_worker as worker
        from agent_console.task_timing import normalized_task_action, next_task_time
        from tests.test_agent_task_scope import TaskStore, principal
        from local_debugger import import_hok_module
        from types import SimpleNamespace
        funcs = import_hok_module("zfunc")
        store = TaskStore()
        original_call = self.gateway.state_bridge.call

        async def task_call(op, **args):
            if op in {"task_list", "task_cancel"}:
                self.calls.append((op, copy.deepcopy(args)))
                return worker.dispatch({"op": op, **args})
            return await original_call(op, **args)

        with patch.dict(worker.CONTEXT, store=store, task_timing={
                "normalized_task_action": normalized_task_action, "next_task_time": next_task_time}), \
                patch.object(funcs.dmc, "redis_deamon", store), \
                patch.object(self.gateway.state_bridge, "call", side_effect=task_call):
            task = worker.dispatch({"op": "task_create", "session_id": "qq_g_200_102", "principal": principal("102"),
                "kind": "message", "message": "休息一下", "interval_seconds": 60, "max_runs": 3})
            await self.gateway.output.send({"text": "休息一下"}, principal("102")["attributes"]["delivery"],
                {"id": "event", "run_id": "reminder", "session_id": "qq_g_200_102", "time": "now",
                 "metadata": {"origin": "background", "task_id": task["task_id"]}})
            sender_packet, destination = self.sent.pop()
            with patch("nonebot.get_driver", return_value=SimpleNamespace(on_startup=lambda fn: fn)):
                sender = import_hok_module("utils.message_sender")
            with patch.object(sender, "_enqueue_payload") as queue:
                sender.add_chat_result_msg(sender_packet, destination=destination, task_id=sender_packet["task_id"])
                payload = queue.call_args.args[0]
            await sender._send_queued_message(SimpleNamespace(send_group_msg=AsyncMock(return_value={"message_id": 42})), payload)
            self.reply_text = "这条提醒由创建者102设置，已取消。"
            self.script = [
                {"role": "assistant", "content": "", "tool_calls": [
                    call("search_chat_history", {"queries": ["定时提醒", "休息"]}, "s")]},
                {"role": "assistant", "content": "", "tool_calls": [
                    call("discover_tools", {"categories": ["tasks"]}, "d")]},
                {"role": "assistant", "content": "", "tool_calls": [call("list_tasks", {"message_id": "42"}, "l")]},
                {"role": "assistant", "content": "", "tool_calls": [call("cancel_task", {"task_id": task["task_id"]}, "c")]},
                {"role": "assistant", "content": self.reply_text},
            ]
            await self.gateway.chat(user_text="这条谁设置的？取消这个定时任务", user_id="101", nickname="甲", group_id="200",
                quoted_message={"available": True, "message_id": "42", "sender_id": "300", "text": "休息一下"})
        stored = json.loads(store.get(worker.STATE_PREFIX + "task:" + task["task_id"]))
        self.assertEqual((stored["status"], stored["principal"]["user_id"]), ("cancelled", "102"))
        listed = next(args for op, args in self.calls if op == "task_list")
        self.assertEqual((listed["message_id"], listed["principal"]["user_id"]), ("42", "101"))
        observation = next(m for m in self.gateway.model.requests[-1].messages if m.get("tool_call_id") == "l")
        self.assertIn('"user_id": "102"', observation["content"])
        self.assertEqual(self.sent[-1][1]["recipient_id"], "200")

    async def test_private_message_tool_is_registered_and_receipt_does_not_redirect_normal_reply(self):
        await self.gateway.close()
        self.gateway.member_profile_reader = AsyncMock(return_value={'profile': {'group_id': '200', 'user_id': '100'}})
        self.gateway.private_message_sender = AsyncMock(return_value={'message_id': 42})
        await self.gateway.start()
        self.reply_text = '已私发提醒给示例玩家65。'
        self.script = [
            {'role': 'assistant', 'content': '', 'tool_calls': [call('search_chat_history', {'queries': ['示例玩家65', '提醒']}, 's')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [call('discover_tools', {'categories': ['chat_delivery']}, 'd')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [call('send_group_member_private_message',
                {'user_id': '100', 'text': '别卷了，休息一下。'}, 'private')]},
            {'role': 'assistant', 'content': self.reply_text},
        ]
        result = await self.gateway.chat(user_text='私发给示例玩家65，让他别卷了。', user_id='101', nickname='甲', group_id='200')
        self.gateway.private_message_sender.assert_awaited_once_with(group_id='200', user_id='100', text='别卷了，休息一下。')
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][1], {'platform':'qq', 'channel':'group', 'recipient_id':'200', 'mention_user_id':'101'})
        observation = next(tool['observation'] for turn in result['trace']['rounds'] for tool in turn['tools']
                           if tool['name'] == 'send_group_member_private_message')
        self.assertTrue(observation['data']['sent'])
        self.assertEqual(observation['data']['message_id'], '42')
        self.assertEqual(set(self.dialogue), {'qq_g_200_101'})

    async def test_other_member_can_continue_public_topic_with_bot_replies_but_keeps_identity(self):
        self.group_messages['200'] = [{'user_id': '101', 'text': '每小时提醒示例玩家65别内卷', 'timestamp': 1}]
        self.reply_text = '已安排提醒示例玩家65。'
        self.script = [
            {'role': 'assistant', 'content': '', 'tool_calls': [call('search_chat_history', {'queries': ['提醒', '内卷']}, 's')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [call('discover_tools', {'categories': ['tasks']}, 'd')]},
            {'role': 'assistant', 'content': self.reply_text},
        ]
        await self.gateway.chat(user_text='每小时提醒示例玩家65别内卷', user_id='101', nickname='甲', group_id='200')
        self.reply_text = '示例玩家65别卷了，歇会儿。'
        self.script = [
            {'role': 'assistant', 'content': '', 'tool_calls': [call('search_chat_history', {'queries': ['提醒', '刚才']}, 's2')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [call('discover_tools', {'categories': ['tasks']}, 'd2')]},
            {'role': 'assistant', 'content': self.reply_text},
        ]
        await self.gateway.chat(user_text='现在立刻提醒一下', user_id='102', nickname='乙', group_id='200', message_id='42')
        messages = self.gateway.model.requests[-3].messages
        background = next(m for m in messages if m['role'] == 'user' and '当前群近期公共对话' in str(m.get('content')))
        self.assertEqual(background['role'], 'user')
        self.assertIn('每小时提醒示例玩家65别内卷', background['content'])
        self.assertIn('已安排提醒示例玩家65', background['content'])
        self.assertNotIn('每小时提醒示例玩家65别内卷', json.dumps(self.dialogue['qq_g_200_102'], ensure_ascii=False))
        self.assertEqual(self.sent[-1][1]['mention_user_id'], '102')
        recent = [args for op, args in self.calls if op == 'recent_history'][-1]
        self.assertEqual(recent['principal']['user_id'], '102')
        self.assertEqual(recent['exclude_message_id'], '42')

    async def test_selected_native_mention_is_inherited_by_task_without_changing_owner(self):
        from qq_agent.mentions import register_reply_mention_tool
        reader = AsyncMock(return_value={'profile': {'group_id': '200', 'user_id': '100'}})
        register_reply_mention_tool(self.gateway.runtime.registry, mentions=self.gateway.mentions, reader=reader)
        self.reply_text = '示例玩家65别卷了。'
        self.script = [
            {'role': 'assistant', 'content': '', 'tool_calls': [call('search_chat_history', {'queries': ['示例玩家65', '提醒']}, 's')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [call('discover_tools', {'categories': ['chat_delivery', 'tasks']}, 'd')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [call('set_reply_mention', {'user_id': '100'}, 'at')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [
                call('emit_message', {'text': '示例玩家65别卷了。'}, 'p'),
                call('create_task', {'kind': 'message', 'message': '别卷了。', 'interval_seconds': 3600, 'max_runs': 2}, 't')]},
            {'role': 'assistant', 'content': self.reply_text},
        ]
        await self.gateway.chat(user_text='现在和每小时at示例玩家65提醒别卷了', user_id='101', nickname='甲', group_id='200')
        reader.assert_awaited_once_with(group_id='200', user_id='100', include_avatar=False)
        self.assertTrue(all(destination['mention_user_id'] == '100' for _, destination in self.sent))
        task = next(args for op, args in self.calls if op == 'task_create')
        self.assertEqual(task['principal']['user_id'], '101')
        self.assertEqual(task['session_id'], 'qq_g_200_101')
        self.assertEqual(task['principal']['attributes']['delivery']['mention_user_id'], '100')
        self.assertEqual(task['principal']['attributes']['delivery']['recipient_id'], '200')
        self.assertEqual(task['principal']['attributes']['identity']['name'], '甲')
        self.assertFalse(self.gateway.mentions.targets)
        self.assertNotIn('[CQ:at', json.dumps(self.dialogue))

    async def test_no_mention_task_retains_explicit_null_after_restart(self):
        from agent_console.tasks import task_request
        from qq_agent.mentions import register_reply_mention_tool
        register_reply_mention_tool(self.gateway.runtime.registry, mentions=self.gateway.mentions, reader=AsyncMock())
        self.reply_text = '已设置。'
        self.script = [
            {'role': 'assistant', 'content': '', 'tool_calls': [call('search_chat_history', {'queries': ['提醒', '不at']}, 's')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [call('discover_tools', {'categories': ['chat_delivery', 'tasks']}, 'd')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [call('set_reply_mention', {'user_id': None}, 'at')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [call('create_task', {'kind': 'message', 'message': '别卷了。', 'delay_seconds': 60}, 't')]},
            {'role': 'assistant', 'content': self.reply_text},
        ]
        await self.gateway.chat(user_text='不at，每小时提醒一下', user_id='101', nickname='甲', group_id='200')
        created = next(args for op, args in self.calls if op == 'task_create')
        task = {**created, 'task_id': 't', 'runs': 0, 'max_runs': 1, 'lease_token': 'lease'}
        task = json.loads(json.dumps(task, default=list))
        self.assertIsNone(task_request(task).metadata['delivery']['mention_user_id'])
        await self.gateway.scheduler.perform(task)
        self.assertIsNone(self.sent[-1][1]['mention_user_id'])
        self.assertFalse(self.gateway.mentions.targets)

    async def test_daily_absolute_time_all_members_task_restores_native_mention_without_mentioning_creator(self):
        from types import SimpleNamespace
        from local_debugger import import_hok_module
        from qq_agent.mentions import register_reply_mention_tool
        from nonebot.adapters.onebot.v11 import Message
        reader = AsyncMock()
        register_reply_mention_tool(self.gateway.runtime.registry, mentions=self.gateway.mentions, reader=reader)
        self.reply_text = '已安排。'
        self.script = [
            {'role': 'assistant', 'content': '', 'tool_calls': [call('search_chat_history', {'queries': ['打王者', '提醒']}, 's')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [call('discover_tools', {'categories': ['chat_delivery', 'tasks']}, 'd')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [call('set_reply_mention', {'user_id': 'all'}, 'at')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [call('create_task', {
                'kind': 'message', 'message': '到点了，打王者。', 'run_at': '2026-10-16T21:30:00+08:00',
                'interval_seconds': 86400, 'max_runs': 365}, 't')]},
            {'role': 'assistant', 'content': self.reply_text},
        ]
        await self.gateway.chat(user_text='每天21:30提醒全群打王者', user_id='101', nickname='甲', group_id='200')
        created = next(args for op, args in self.calls if op == 'task_create')
        self.assertEqual(created['principal']['user_id'], '101')
        self.assertEqual(created['principal']['attributes']['delivery']['mention_user_id'], 'all')
        self.assertIsNone(created['delay_seconds'])
        reader.assert_not_called()
        self.assertFalse(self.gateway.mentions.targets)
        task = json.loads(json.dumps({**created, 'task_id': 'a' * 32, 'runs': 0, 'lease_token': 'lease'}, default=list))
        await self.gateway.scheduler.perform(task)
        packet, destination = self.sent[-1]
        self.assertEqual(destination['mention_user_id'], 'all')
        with patch('nonebot.get_driver', return_value=SimpleNamespace(on_startup=lambda function: function)):
            sender = import_hok_module('utils.message_sender')
        with patch.object(sender, '_enqueue_payload') as enqueue:
            sender.add_chat_result_msg(packet, destination=destination, task_id=task['task_id'])
        payload = enqueue.call_args.args[0]
        message = Message(payload.get('reply_direct', payload)['content'])
        self.assertEqual([part.data['qq'] for part in message if part.type == 'at'], ['all'])
        self.assertNotIn('[CQ:at', json.dumps(self.dialogue))

    async def test_final_reply_passes_existing_two_variants_to_both_qq_channels(self):
        from local_debugger import import_hok_module
        from types import SimpleNamespace
        from nonebot.adapters.onebot.v11 import Message
        with patch('nonebot.get_driver', return_value=SimpleNamespace(on_startup=lambda function: function)):
            sender = import_hok_module('utils.message_sender')
        composer = self.gateway.runtime.finalizer.composer
        composer.policy = composer.policy.model_copy(update={'select_delivery_variant': True})
        draft = '事实底稿：机器人支持查询近期群聊，但只读取授权范围。'
        self.reply_text = '可以查近期群聊，范围受当前会话权限限制。'
        cases = [('不用详细解释，简短说能否逐一统计所有玩家。', 'chat'),
                 ('Please show the full explanation and supporting evidence.', 'detailed')]
        for group in (None, '200'):
            for question, variant in cases:
                with self.subTest(group=group, question=question):
                    self.reply_variant = variant
                    self.script = [
                        {'role': 'assistant', 'content': '', 'tool_calls': [call('discover_tools', {'categories': ['bot_info']}, 'd')]},
                        {'role': 'assistant', 'content': draft},
                    ]
                    if group:
                        self.script.insert(0, {'role': 'assistant', 'content': '', 'tool_calls': [
                            call('search_chat_history', {'queries': ['近期群聊', '授权范围']}, 's')]})
                    original = ' ＃原话 ' + question + '\n'
                    result = await self.gateway.chat(user_text=question, user_id='101', nickname='用户', group_id=group,
                                                     original_user_text=original)
                    self.assertEqual(result['text'], self.reply_text)
                    session = 'qq_g_200_101' if group else 'qq_p_101'
                    self.assertEqual(self.dialogue[session][-1]['content'], self.reply_text)
                    self.assertEqual(result['variants'], {'detailed': draft, 'chat': self.reply_text})
                    self.assertNotIn('delivery_variant', result)
                    packet, destination = self.sent[-1]
                    with patch.object(sender, '_enqueue_payload') as enqueue:
                        sender.add_chat_result_msg(packet, destination=destination)
                    payload = enqueue.call_args.args[0]
                    self.assertEqual(payload['messages'][0]['data']['content'], [{'type': 'text', 'data': {'text': original}}])
                    self.assertEqual(payload['messages'][0]['data']['uin'], '101')
                    self.assertEqual(payload['messages'][0]['data']['name'], '用户')
                    self.assertEqual(payload['messages'][-1]['data']['content'],
                                     [{'type': 'text', 'data': {'text': '思考轨迹：' + packet['trace_url']}}])
                    detail = ''.join(part['data']['text'] for node in payload['messages'][1:-1]
                                     for part in node['data']['content'] if part['type'] == 'text')
                    brief = Message(payload['reply_direct']['content']).extract_plain_text().strip()
                    self.assertEqual(detail, draft)
                    self.assertEqual(brief, self.reply_text)
                    self.assertNotEqual(detail, brief)

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
        self.gateway.config['admin_private_default_group_id'] = '2000000001'
        self.reply_text = '默认群已确认。'
        self.script = [
            {'role': 'assistant', 'content': '', 'tool_calls': [call('search_chat_history', {'queries': ['默认群', '群信息']}, 'h')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [call('discover_tools', {'categories': ['chat_history']}, 'd')]},
            {'role': 'assistant', 'content': '默认群已确认。'},
        ]
        await self.gateway.chat(user_text='默认查询哪个群？', user_id='999', nickname='管理员', message_id=42)
        search = next(args for op, args in self.calls if op == 'search_history')
        self.assertEqual(search['principal']['default_group_id'], '2000000001')
        self.assertIsNone(search['principal']['group_id'])
        self.assertIn('qq_p_999', self.dialogue)
        self.assertTrue(all(delivery['channel'] == 'private' and delivery['recipient_id'] == '999' for _, delivery in self.sent))
        self.assertIn('2000000001', self.gateway.model.requests[0].messages[0]['content'])

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
        self.assertEqual(self.dialogue["qq_g_200_101"][-1]["content"],
                         "记忆已保存，正在设置提醒。\n\n" + result["text"])
        self.assertGreater(result["trace"]["summary"]["token_usage"]["total_tokens"], 0)

    async def test_information_dense_answer_delivers_ordered_parts_and_preserves_followup_context(self):
        first, second = "先说结论：这个方案可以用，但需要满足条件。", "具体步骤：先确认数据范围，再比较相同口径的结果。"
        self.reply_text = "最后留意样本范围，别把局部结果当成全量。"
        self.script = [
            {'role': 'assistant', 'content': '', 'tool_calls': [call('discover_tools', {'categories': ['references']}, 'd')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [call('emit_message', {'text': first}, 'p1')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [call('emit_message', {'text': second}, 'p2')]},
            {'role': 'assistant', 'content': '最后留意样本范围，别把局部结果当成全量。'},
        ]
        result = await self.gateway.chat(user_text='把方案和操作步骤都说清楚，可以分几条发。',
                                         user_id='101', nickname='B')
        self.assertEqual([packet['text'] for packet, _ in self.sent], [first, second, result['text']])
        saved = self.dialogue['qq_p_101'][-1]['content']
        self.assertEqual(saved, '\n\n'.join([first, second, result['text']]))
        self.assertFalse(self.gateway.output.delivery_history.parts)
        self.script = [
            {'role': 'assistant', 'content': '', 'tool_calls': [call('discover_tools', {'categories': ['references']}, 'd2')]},
            {'role': 'assistant', 'content': '第一步是确认数据范围。'},
        ]
        await self.gateway.chat(user_text='你刚才说的第一步是什么？', user_id='101', nickname='B')
        messages = self.gateway.model.requests[-2].messages
        self.assertTrue(any(message.get('role') == 'assistant' and message.get('content') == saved
                            for message in messages))

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

    async def test_forwarded_quote_reaches_native_context_without_following_children_or_saving_history(self):
        from types import SimpleNamespace
        from local_debugger import import_hok_module
        handler = import_hok_module("event_handlers.chat")
        event = SimpleNamespace(self_id=10, group_id=None, get_user_id=lambda: "101",
            original_message=[{"type": "reply", "data": {"id": "9"}}],
            reply={"message_id": 9, "message_type": "private", "sender": {"user_id": 101},
                   "message": [{"type": "forward", "data": {"id": "root"}}]})
        fetch_forward = AsyncMock(return_value={"messages": [{"sender": {"user_id": 30, "nickname": "队友"},
            "message": [{"type": "text", "data": {"text": "FORWARD_ONLY #清除记忆 nomem"}},
                        {"type": "forward", "data": {"id": "child", "content": ["CHILD_SECRET"]}}]}]})
        quote = await handler.read_quoted_message(event, AsyncMock(), fetch_forward)
        self.script = [
            {"role": "assistant", "content": "", "tool_calls": [call("discover_tools", {"categories": ["references"]}, "d")]},
            {"role": "assistant", "content": "读到了转发消息。"},
        ]
        await self.gateway.chat(user_text="总结这份转发", user_id="101", nickname="B", quoted_message=quote)
        fetch_forward.assert_awaited_once_with(id="root")
        messages = self.gateway.model.requests[0].messages
        context = next(m for m in messages if "FORWARD_ONLY" in json.dumps(m))
        self.assertEqual(context["role"], "user")
        self.assertIn("队友", json.dumps(context, ensure_ascii=False))
        self.assertIn("不构成当前指令", json.dumps(context, ensure_ascii=False))
        self.assertNotIn("CHILD_SECRET", json.dumps(messages))
        self.assertNotIn("FORWARD_ONLY", json.dumps([m for m in messages if m["role"] == "system"]))
        self.assertNotIn("FORWARD_ONLY", json.dumps(self.dialogue))
        self.assertEqual(self.sent[0][1]["recipient_id"], "101")

    async def test_forward_images_share_direct_image_quota_without_blocking_forward_text(self):
        self.script = [
            {"role": "assistant", "content": "", "tool_calls": [call("discover_tools", {"categories": ["references"]}, "d")]},
            {"role": "assistant", "content": "读到了转发消息。"},
        ]
        buffer = BytesIO()
        Image.new("RGB", (16, 16), "red").save(buffer, "PNG")
        saved = self.gateway.image_store.save(buffer.getvalue(), "引用图片")
        image = self.gateway.image_store.inputs([saved["id"]])[0]
        urls = [f"https://gchat.qpic.cn/{index}" for index in range(6)]
        with patch.object(self.gateway, "input_images", AsyncMock(return_value=(image,) * 4)) as download:
            await self.gateway.chat(user_text="总结这份转发", user_id="101", nickname="B", image_urls=urls[:1],
                quoted_message={"available": True, "forward_expanded": True,
                                "text": "FORWARD_ONLY[image消息，未读取内容]", "image_urls": urls})
        download.assert_awaited_once_with(urls[:4])
        context = next(m for m in self.gateway.model.requests[0].messages if "FORWARD_ONLY" in json.dumps(m))
        quote_text = context["content"][0]["text"]
        self.assertIn('"omitted_images": 2', quote_text)
        self.assertIn("部分图片未读取", quote_text)
        self.assertNotIn("像素已附上", quote_text)
        self.assertNotIn("FORWARD_ONLY", json.dumps(self.dialogue))

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
