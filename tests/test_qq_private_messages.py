"""Private sends retain caller authority and only claim confirmed QQ receipts."""

import asyncio
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from agent_runtime import Principal, RunRequest, ToolRegistry
from agent_runtime.models import ToolContext
from agent_runtime.tools.executor import execute
from agent_console.tools.diagnostics import DiagnosticToolRegistry
from local_debugger import import_hok_module
from qq_agent.private_messages import register_private_message_tool
from qq_agent.service import qq_principal


def tool_call(**arguments):
    return {"id": "private", "type": "function", "function": {
        "name": "send_group_member_private_message", "arguments": json.dumps(arguments)}}


class PrivateToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.reader = AsyncMock(return_value={"profile": {"group_id": "200", "user_id": "102"}})
        self.sender = AsyncMock(return_value={"message_id": 42})
        self.registry = DiagnosticToolRegistry()
        register_private_message_tool(self.registry, reader=self.reader, sender=self.sender)
        self.principal = qq_principal('101', '200', '甲', admin_id='999', bot_id='300',
            references={'context': {'catalogs': {}}})
        self.ctx = self.context(self.principal)

    def context(self, principal, **metadata):
        return ToolContext(RunRequest('私发给乙提醒休息', 'qq_g_200_101', principal, metadata=metadata),
            None, disclosed={'send_group_member_private_message'})

    async def test_verified_private_send_keeps_sender_group_and_normal_reply_unchanged(self):
        original = copy.deepcopy(self.principal)
        result = await execute(self.registry, tool_call(user_id='102', text='休息一下 [CQ:at,qq=all]'), self.ctx)
        self.assertTrue(result.ok)
        self.assertEqual(result.data['message_id'], '42')
        self.reader.assert_awaited_once_with(group_id='200', user_id='102', include_avatar=False)
        self.sender.assert_awaited_once_with(group_id='200', user_id='102', text='休息一下 [CQ:at,qq=all]')
        self.assertEqual(self.principal, original)
        self.assertEqual(self.principal.attributes['delivery']['mention_user_id'], '101')
        again = await execute(self.registry, tool_call(user_id='102', text='休息一下 [CQ:at,qq=all]'), self.ctx)
        self.assertTrue(again.data['duplicate'])
        self.assertEqual(self.sender.await_count, 1)

    async def test_nonmembers_cross_group_and_mismatched_profiles_never_send(self):
        result = await execute(self.registry, tool_call(user_id='102', group_id='201', text='你好'), self.ctx)
        self.assertFalse(result.ok)
        self.reader.assert_not_awaited()
        for profile in ({'group_id': '201', 'user_id': '102'}, {'group_id': '200', 'user_id': '103'}):
            self.reader.return_value = {'profile': profile}
            result = await execute(self.registry, tool_call(user_id='102', text='你好'), self.ctx)
            self.assertFalse(result.ok)
        self.reader.side_effect = ValueError('目标不在群中')
        self.assertFalse((await execute(self.registry, tool_call(user_id='102', text='你好'), self.ctx)).ok)
        self.sender.assert_not_awaited()

    async def test_plain_private_and_web_lack_capability_even_with_arbitrary_group_argument(self):
        private = qq_principal('101', None, '', admin_id='999', references={'context': {'catalogs': {}}})
        for principal in (private, Principal('101', frozenset({'chat.cross_group', 'qq.profile.read'}))):
            ctx = self.context(principal)
            self.assertNotIn('send_group_member_private_message', self.registry.available(ctx))
            result = await execute(self.registry, tool_call(group_id='200', user_id='102', text='你好'), ctx)
            self.assertEqual(result.code, 'PERMISSION_DENIED')
        self.reader.assert_not_awaited()
        self.sender.assert_not_awaited()

    async def test_admin_private_uses_default_or_explicit_group_without_changing_private_destination(self):
        admin = qq_principal('999', None, '', admin_id='999', admin_private_default_group_id='200',
            references={'context': {'catalogs': {}}})
        result = await execute(self.registry, tool_call(user_id='102', text='你好'), self.context(admin))
        self.assertTrue(result.ok)
        self.assertEqual(admin.attributes['delivery'], {'platform':'qq', 'channel':'private', 'recipient_id':'999'})
        self.reader.return_value['profile']['group_id'] = '201'
        result = await execute(self.registry, tool_call(group_id='201', user_id='102', text='你好'), self.context(admin))
        self.assertTrue(result.ok)
        self.reader.assert_awaited_with(group_id='201', user_id='102', include_avatar=False)

    async def test_old_background_grants_are_not_upgraded_and_new_authorized_agent_tasks_can_send(self):
        old = Principal('101', self.principal.scopes - {'qq.private.send'}, self.principal.attributes)
        result = await execute(self.registry, tool_call(user_id='102', text='休息'), self.context(old, origin='background'))
        self.assertEqual(result.code, 'PERMISSION_DENIED')
        result = await execute(self.registry, tool_call(user_id='102', text='休息'), self.context(self.principal, origin='background'))
        self.assertTrue(result.ok)

    async def test_empty_oversized_bot_and_untrusted_identity_arguments_are_rejected(self):
        for args in ({'user_id': '300', 'text': '你好'}, {'user_id': '102', 'text': ' '},
                     {'user_id': '102', 'text': 'x' * 4001}, {'user_id': 'all', 'text': '你好'},
                     {'user_id': '102', 'text': '你好', 'principal': {}}, {'user_id': True, 'text': '你好'}):
            with self.subTest(args=str(args)[:80]):
                self.assertFalse((await execute(self.registry, tool_call(**args), self.ctx)).ok)
        self.reader.assert_not_awaited()
        self.sender.assert_not_awaited()

    async def test_missing_receipt_and_timeout_block_replay_without_success_claim(self):
        for response in ({}, {'message_id': True}, {'message_id': '--1'}, None):
            self.sender.return_value = response
            ctx = self.context(self.principal)
            result = await execute(self.registry, tool_call(user_id='102', text='你好'), ctx)
            self.assertEqual(result.code, 'OUTCOME_UNKNOWN')
            attempts = self.sender.await_count
            again = await execute(self.registry, tool_call(user_id='102', text='你好'), ctx)
            self.assertEqual(again.code, 'OUTCOME_UNKNOWN')
            self.assertEqual(attempts, self.sender.await_count)
        registry = DiagnosticToolRegistry()
        async def pending(**kwargs):
            await asyncio.Event().wait()
        register_private_message_tool(registry, reader=self.reader, sender=pending, policy={'timeout_seconds': .01})
        result = await execute(registry, tool_call(user_id='102', text='你好'), self.ctx)
        self.assertEqual(result.code, 'OUTCOME_UNKNOWN')

    def test_config_disables_registration_or_exposes_matching_schema_limits(self):
        registry = ToolRegistry()
        register_private_message_tool(registry, reader=self.reader, sender=self.sender, policy={'enabled':False})
        self.assertNotIn('send_group_member_private_message', registry.tools)
        register_private_message_tool(registry, reader=self.reader, sender=self.sender, policy={'max_chars':12})
        schema = registry.tools['send_group_member_private_message'].schema()['function']['parameters']
        self.assertEqual(schema['properties']['text']['maxLength'], 12)
        with self.assertRaises(ValueError):
            register_private_message_tool(registry, reader=self.reader, sender=self.sender, policy=False)


class PrivateOutletTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        with patch('nonebot.get_driver', return_value=SimpleNamespace(on_startup=lambda fn: fn)):
            self.outlet = import_hok_module('utils.message_sender')
        self.profiles = import_hok_module('utils.qq_profiles')
        self.funcs = import_hok_module('zfunc')
        self.bot = Mock(self_id=str(self.outlet.confs['QQBot']['bot_qid']),
            send_private_msg=AsyncMock(return_value={'message_id': -42}))
        self.member = AsyncMock(return_value={'group_id': '200', 'user_id': '102'})

    async def test_facade_uses_real_unified_outlet_and_native_literal_text(self):
        from nonebot.adapters.onebot.v11 import Message
        text = '休息一下 [CQ:image,file=/private/file]'
        with patch.object(self.outlet.nonebot, 'get_bot', return_value=self.bot), \
             patch.object(self.profiles, 'load_group_member_profile', self.member), \
             patch.object(self.outlet, '_enqueue_payload') as enqueue:
            result = await self.funcs.agent_send_group_member_private_message(group_id='200', user_id='102', text=text)
        self.assertEqual(result, {'message_id': '-42'})
        kwargs = self.bot.send_private_msg.call_args.kwargs
        self.assertEqual((kwargs['group_id'], kwargs['user_id']), (200,102))
        message = Message(kwargs['message'])
        self.assertEqual([part.type for part in message], ['text'])
        self.assertEqual(message[0].data['text'], text)
        self.assertTrue(kwargs['auto_escape'])
        enqueue.assert_not_called()

    async def test_unknown_or_lost_receipts_are_not_replayed(self):
        for value in (None, {}, {'message_id': True}, {'message_id': '--1'}):
            self.bot.send_private_msg.return_value = value
            with self.subTest(value=value), patch.object(self.outlet.nonebot,'get_bot',return_value=self.bot), \
                 patch.object(self.profiles,'load_group_member_profile',self.member), \
                 self.assertRaises(self.outlet.PrivateMessageOutcomeUnknown):
                await self.outlet.send_group_member_private_message(group_id='200', user_id='102', text='你好')
        self.bot.send_private_msg.side_effect = ConnectionError('connection lost')
        with patch.object(self.outlet.nonebot,'get_bot',return_value=self.bot), \
             patch.object(self.profiles,'load_group_member_profile',self.member), \
             self.assertRaises(self.outlet.PrivateMessageOutcomeUnknown) as failure:
            await self.outlet.send_group_member_private_message(group_id='200', user_id='102', text='你好')
        self.assertTrue(failure.exception.error_details['outcome_unknown'])

    async def test_qq_rejection_is_reported_without_group_or_queue_fallback(self):
        from nonebot.adapters.onebot.v11.exception import ActionFailed
        self.bot.send_private_msg.side_effect = ActionFailed(status='failed', retcode=1200, message='临时会话不可用')
        with patch.object(self.outlet.nonebot, 'get_bot', return_value=self.bot), \
             patch.object(self.profiles, 'load_group_member_profile', self.member), \
             patch.object(self.outlet, '_enqueue_payload') as enqueue, self.assertRaises(ActionFailed):
            await self.outlet.send_group_member_private_message(group_id='200', user_id='102', text='你好')
        enqueue.assert_not_called()
        self.bot.send_group_msg.assert_not_called()
        self.assertEqual(self.bot.send_private_msg.await_count, 1)

    async def test_invalid_membership_and_ids_fail_before_sending(self):
        for group, user in ((True,'102'), ('200','all'), ('0','102')):
            with self.assertRaises(ValueError):
                await self.outlet.send_group_member_private_message(group_id=group, user_id=user, text='你好')
        self.member.return_value['group_id'] = '201'
        with patch.object(self.outlet.nonebot, 'get_bot', return_value=self.bot), \
             patch.object(self.profiles, 'load_group_member_profile', self.member), self.assertRaises(ValueError):
            await self.outlet.send_group_member_private_message(group_id='200', user_id='102', text='你好')
        self.bot.send_private_msg.assert_not_awaited()
