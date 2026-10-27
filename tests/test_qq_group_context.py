"""Public group continuity and mentions do not confer personal authority."""

import asyncio
import datetime
import json
import unittest
from unittest.mock import AsyncMock, patch

from agent_runtime import RunRequest, ToolRegistry
from agent_runtime.models import ToolContext
from agent_console import remote_worker as worker
from agent_console.tools.memory import recent_history_limits
from qq_agent.context import group_context
from qq_agent.mentions import ReplyMentions, register_reply_mention_tool
from qq_agent.output import QQOutput
from qq_agent.service import qq_principal
from tests.test_qq_agent import REFERENCES


def principal(user='101', group='200'):
    return qq_principal(user, group, user, admin_id='999', references=REFERENCES)


class ContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_combines_bounded_chronological_public_sources_and_reports_missing_source(self):
        bridge = AsyncMock()
        bridge.call.side_effect = [
            {'messages': [{'text': '较早', 'timestamp': 1}, {'text': '接话', 'timestamp': 3}]},
            {'messages': [{'text': '机器人已发回复', 'timestamp': 2}]},
        ]
        context = await group_context(bridge, principal(), '42', {'limit': 2})
        payload = json.loads(context[0]['content'].split('\n', 1)[1])
        self.assertEqual([r['text'] for r in payload['messages']], ['机器人已发回复', '接话'])
        self.assertTrue(payload['combined_truncated'])
        self.assertEqual(context[0]['role'], 'user')
        recent = bridge.call.await_args_list[0]
        self.assertEqual(recent.kwargs['limit'], 2)
        self.assertNotIn('window_minutes', recent.kwargs)
        bridge.call.side_effect = [OSError('database unavailable'), {'messages': []}]
        with self.assertLogs('qq_agent.context', 'WARNING'):
            context = await group_context(bridge, principal(), '42')
        self.assertIn('"available": false', context[0]['content'])

    async def test_private_context_is_not_injected_even_for_admin_with_default_query_group(self):
        bridge = AsyncMock()
        for user in ('101', '999'):
            self.assertEqual(await group_context(bridge, principal(user, None), '42'), ())
        bridge.call.assert_not_called()

    async def test_context_timeout_and_cancellation_do_not_wait_for_remote_timeout(self):
        bridge = AsyncMock()
        async def stalled(*args, **kwargs):
            await asyncio.Event().wait()
        bridge.call.side_effect = stalled
        with self.assertLogs('qq_agent.context', 'WARNING'):
            context = await group_context(bridge, principal(), '42', timeout_seconds=.01)
        self.assertIn('"available": false', context[0]['content'])
        task = asyncio.create_task(group_context(bridge, principal(), '42'))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


class MentionTests(unittest.IsolatedAsyncioTestCase):
    async def test_mismatched_nonmember_and_private_targets_cannot_override_delivery(self):
        mentions, registry, reader = ReplyMentions(), ToolRegistry(), AsyncMock()
        register_reply_mention_tool(registry, mentions=mentions, reader=reader)
        spec = registry.tools['set_reply_mention']
        for profile in ({'group_id': '300', 'user_id': '100'}, {'group_id': '200', 'user_id': '102'}):
            ctx = ToolContext(RunRequest('提醒他', 'qq_g_200_101', principal()), None)
            reader.return_value = {'profile': profile}
            with self.assertRaises(ValueError):
                await spec.handler(spec.args_model(user_id='100'), ctx)
        reader.side_effect = ValueError('not a group member')
        with self.assertRaises(ValueError):
            await spec.handler(spec.args_model(user_id='100'), ctx)
        with self.assertRaises(PermissionError):
            await spec.handler(spec.args_model(user_id=None), ToolContext(RunRequest('提醒', 'qq_p_999', principal('999', None)), None))
        self.assertFalse(mentions.targets)
        for target in ('-1', 'example_user_10', '[CQ:at,qq=100]', True, 100):
            with self.subTest(target=target), self.assertRaises(ValueError):
                spec.args_model(user_id=target)

    async def test_all_members_requires_current_group_and_does_not_lookup_a_fake_member(self):
        mentions, registry, reader = ReplyMentions(), ToolRegistry(), AsyncMock()
        register_reply_mention_tool(registry, mentions=mentions, reader=reader)
        spec = registry.tools['set_reply_mention']
        request = RunRequest('提醒全群', 'qq_g_200_101', principal())
        await spec.handler(spec.args_model(user_id='all'), ToolContext(request, None))
        self.assertEqual(mentions.delivery(request.run_id, principal().attributes['delivery'])['mention_user_id'], 'all')
        reader.assert_not_called()
        for user in ('101', '999'):
            with self.assertRaises(PermissionError):
                await spec.handler(spec.args_model(user_id='all'),
                    ToolContext(RunRequest('提醒全群', 'qq_p_' + user, principal(user, None)), None))

    async def test_concurrent_runs_deliver_selected_default_and_no_mention_independently(self):
        mentions = ReplyMentions()
        mentions.targets.update({'a': '100', 'b': None})
        bridge = AsyncMock()
        bridge.redact = lambda value: value
        sender = AsyncMock()
        output = QQOutput(bridge=bridge, local_log=AsyncMock(), sender=sender,
            prepare_reply=AsyncMock(side_effect=lambda packet: packet), store_artifact=AsyncMock(), mentions=mentions)
        for run, user in [('a', '101'), ('b', '102'), ('c', '103')]:
            event = {'id': run, 'run_id': run, 'session_id': 'qq_g_200_' + user,
                     'time': '2026-10-15T15:30:00+08:00', 'kind': 'output.message',
                     'data': {'kind': 'partial', 'text': '提醒正文'}, 'metadata': {'delivery': principal(user).attributes['delivery']}}
            await output.publish(event)
        self.assertEqual([call.args[1]['mention_user_id'] for call in sender.await_args_list], ['100', None, '103'])
        self.assertEqual([call.kwargs['delivery']['mention_user_id'] for call in bridge.call.await_args_list], ['100', None, '103'])
        self.assertEqual([call.args[0]['metadata']['delivery']['mention_user_id']
                          for call in output.local_log.record.await_args_list], ['100', None, '103'])
        for run in ('a', 'b'):
            await output.publish({**event, 'run_id': run, 'kind': 'run.end', 'data': {'status': 'cancelled'}})
        self.assertFalse(mentions.targets)

    async def test_failed_sender_is_not_added_to_public_context_and_run_state_is_released(self):
        mentions = ReplyMentions()
        mentions.targets['a'] = '100'
        bridge = AsyncMock()
        bridge.redact = lambda value: value
        output = QQOutput(bridge=bridge, local_log=AsyncMock(), sender=AsyncMock(side_effect=OSError('queue failed')),
            prepare_reply=AsyncMock(side_effect=lambda packet: packet), store_artifact=AsyncMock(), mentions=mentions)
        event = {'id': 'a', 'run_id': 'a', 'session_id': 'qq_g_200_101', 'time': '2026-10-15T15:30:00+08:00',
                 'kind': 'run.end', 'data': {'status': 'failed'}, 'metadata': {'delivery': principal().attributes['delivery']}}
        with self.assertRaises(OSError):
            await output.publish(event)
        bridge.call.assert_not_called()
        self.assertFalse(mentions.targets)
        self.assertFalse(output.delivery_history.parts)

    async def test_context_write_failure_does_not_repeat_or_fail_an_accepted_reply(self):
        business, state = AsyncMock(), AsyncMock()
        business.redact = lambda value: value
        state.call.side_effect = OSError('Redis unavailable')
        output = QQOutput(bridge=business, context_bridge=state, local_log=AsyncMock(), sender=AsyncMock(),
            prepare_reply=AsyncMock(), store_artifact=AsyncMock())
        event = {'id': 'a', 'run_id': 'a', 'session_id': 'qq_g_200_101', 'time': '2026-10-15T15:30:00+08:00',
                 'kind': 'output.message', 'data': {'kind': 'partial', 'text': '已经入队的正文'},
                 'metadata': {'delivery': principal().attributes['delivery']}}
        with self.assertLogs('qq_agent.output', 'WARNING'):
            await output.publish(event)
        output.sender.assert_awaited_once()
        business.call.assert_not_called()
        self.assertEqual(output.delivery_history.parts['a'], ['已经入队的正文'])

    async def test_cancelled_run_keeps_trace_and_identity_without_sending_extra_message(self):
        bridge = AsyncMock()
        bridge.redact = lambda value: value
        prepare = AsyncMock(side_effect=lambda packet: packet)
        output = QQOutput(bridge=bridge, local_log=AsyncMock(), sender=AsyncMock(),
            prepare_reply=prepare, store_artifact=AsyncMock())
        event = {'id': 'start', 'run_id': 'a', 'session_id': 'qq_g_200_101', 'time': '2026-10-15T15:30:00+08:00',
                 'kind': 'run.start', 'data': {'message': '帮我查一下'},
                 'metadata': {'delivery': principal().attributes['delivery']}}
        await output.publish(event)
        await output.publish({**event, 'id': 'part', 'kind': 'output.message',
                              'data': {'kind': 'partial', 'text': '已有部分结果'}})
        await output.publish({**event, 'id': 'end', 'kind': 'run.end', 'data': {'status': 'cancelled'}})
        output.sender.assert_awaited_once()
        trace = prepare.call_args.args[0]['trace']
        self.assertEqual((trace['run_id'], trace['session_id'], trace['status']), ('a', 'qq_g_200_101', 'cancelled'))
        self.assertEqual(trace['question'], '帮我查一下')
        self.assertEqual(trace['answer'], '已有部分结果')


class Store:
    def __init__(self):
        self.rows, self.expirations = {}, {}
    def pipeline(self, **kwargs):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def rpush(self, key, raw):
        self.rows.setdefault(key, []).append(raw)
    def ltrim(self, key, start, end):
        self.rows[key] = self.rows[key][start:]
    def persist(self, key):
        self.expirations.pop(key, None)
    def execute(self):
        pass
    def lrange(self, key, start, end):
        return self.rows.get(key, [])[start:]


class GroupReplyStoreTests(unittest.TestCase):
    def test_persistence_binds_group_keeps_old_replies_and_bounds_count_and_text(self):
        store = Store()
        key = worker.STATE_PREFIX + 'qq_group_replies:200'
        store.expirations[key] = 604800
        context = {'cfg': {'AgentHistory': {'limit': 2, 'max_limit': 3, 'max_message_chars': 5}},
                   'store': store, 'memory': {'recent_history_limits': recent_history_limits}}
        with patch.dict(worker.CONTEXT, context, clear=True), patch.object(worker.time, 'time', return_value=10000):
            def save(group, number, timestamp=9999):
                return worker.dispatch({'op': 'qq_group_reply_save', 'session_id': f'qq_g_{group}_101',
                    'delivery': principal(group=group).attributes['delivery'], 'text': '一个很长的机器人回复',
                    'event_id': str(number), 'timestamp': datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc).isoformat()})
            save('200', 0, 1)
            save('300', 0)
            result = worker.dispatch({'op': 'qq_group_replies', 'principal': {'user_id': '102', 'group_id': '200', 'scopes': ['chat.read']}})
            self.assertEqual([row['message_id'] for row in result['messages']], ['0'])
            self.assertNotIn(key, store.expirations)
            for number in range(1, 5):
                save('200', number)
            result = worker.dispatch({'op': 'qq_group_replies', 'principal': {'user_id': '102', 'group_id': '200', 'scopes': ['chat.read']}})
            self.assertEqual([row['message_id'] for row in result['messages']], ['3', '4'])
            self.assertTrue(result['has_older_messages'])
            self.assertTrue(all(row['text_truncated'] and len(row['text']) == 5 for row in result['messages']))
            self.assertEqual(len(store.rows[worker.STATE_PREFIX + 'qq_group_replies:200']), 3)
            self.assertNotIn(key, store.expirations)
            for caller in ({'group_id': None, 'scopes': ['chat.read', 'chat.cross_group']}, {'group_id': '200', 'scopes': []}):
                with self.assertRaises(PermissionError):
                    worker.dispatch({'op': 'qq_group_replies', 'principal': caller})
            with self.assertRaises(PermissionError):
                worker.dispatch({'op': 'qq_group_reply_save', 'session_id': 'qq_g_300_101', 'delivery': principal().attributes['delivery']})
