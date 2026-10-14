"""Retrieve only useful handbook evidence and approved, bounded code fragments."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from agent_runtime import AgentRuntime, Principal, RunRequest, ToolRegistry
from agent_runtime.models import ToolContext
from agent_runtime.tools.executor import execute
from agent_console.bot_manual import BotManual
from agent_console.capabilities import Capabilities, application_prompt, load_catalogs
from agent_console.remote import RemoteBridge
from agent_console import remote_worker
from agent_console.tools.application import register_application_tools
from tests.test_agent_runtime import Clock, ScriptedModel, Sink, State, call


ROOT = Path(__file__).parents[1]
SHARED = ROOT / 'shared/agent'
CATALOG = json.loads((SHARED / 'manual/catalog.json').read_text())
HANDBOOK = (SHARED / 'manual/handbook.md').read_text()


class ManualTests(unittest.TestCase):
    def setUp(self):
        self.manual = BotManual(ROOT, copy.deepcopy(CATALOG), HANDBOOK)

    def test_relevant_chapters_are_ranked_and_empty_query_is_an_overview(self):
        for question, expected in [('你能记住我喜欢玩的英雄吗？', 'memory'),
                                   ('引用一张图片再@你，可以读取动态表情吗？', 'vision'),
                                   ('每隔10秒提醒一次支持吗？', 'tasks'),
                                   ('你的头像是什么，怎样读取机器人资料？', 'profiles'),
                                   ('管理员私聊默认查询哪个群？', 'permissions')]:
            with self.subTest(question=question):
                result = self.manual.read(query=question, limit=1)
                self.assertEqual(result['topics'][0]['section_id'], expected)
                self.assertFalse(result['code'])
        self.assertEqual(self.manual.read()['topics'][0]['section_id'], 'overview')
        self.assertEqual(self.manual.read(query='zzzz_unlisted_feature')['topics'], [])

    def test_every_declared_source_resolves_without_importing_or_executing_code(self):
        for topic in CATALOG['topics']:
            with self.subTest(section=topic['id']):
                result = self.manual.read(section_id=topic['id'], include_code=True)
                self.assertTrue(result['code'])
                for source in result['code']:
                    self.assertNotIn('unavailable', source, source)
                    self.assertEqual(source['evidence'], 'deployed_source')
                    self.assertGreaterEqual(source['end_line'], source['start_line'])
                    self.assertLessEqual(len(source['content']), CATALOG['limits']['max_code_excerpt_chars'])

    def test_budgets_and_invalid_queries_fail_explicitly(self):
        for options in ({'limit': True}, {'limit': 6}, {'query': 'x' * 401},
                        {'include_code': 'yes'}, {'section_id': '../../.env'}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.manual.read(**options)
        self.manual.limits.update(max_handbook_chars=30, max_code_chars=200, max_code_references=1)
        result = self.manual.read(section_id='tasks', include_code=True)
        self.assertLessEqual(sum(len(item['content']) for item in result['topics']), 30)
        self.assertTrue(result['topics'][0]['truncated'])
        self.assertEqual(len(result['code']), 1)
        self.assertEqual(result['code_omitted'], 1)
        self.assertTrue(result['code_truncated'])
        self.assertLessEqual(sum(len(item.get('content', '')) for item in result['code']), 200)

    def test_secret_files_traversal_and_symlinks_are_never_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.env').write_text('secret-unreadable')
            (root / 'redirect.py').symlink_to(root / '.env')
            for path in ('.env', 'config.yaml', '../private.py', '/tmp/private.py', 'redirect.py'):
                with self.subTest(path=path):
                    catalog = copy.deepcopy(CATALOG)
                    catalog['topics'][0]['code'] = [{'path': path, 'symbol': 'f'}]
                    reader = BotManual(root, catalog, HANDBOOK)
                    with patch.object(Path, 'open', side_effect=AssertionError('private file read')):
                        result = reader.read(section_id='overview', include_code=True)
                    self.assertTrue(result['code'][0]['unavailable'])
                    self.assertNotIn('secret-unreadable', json.dumps(result))

    def test_source_cache_refreshes_and_redacts_without_executing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'example.py'
            path.write_text('raise RuntimeError("must not execute")\ndef sample():\n    return "private-secret-value", "sk-abcdefghijklmnop"\n')
            catalog = copy.deepcopy(CATALOG)
            catalog['topics'][0]['code'] = [{'path': 'example.py', 'symbol': 'sample'}]
            reader = BotManual(directory, catalog, HANDBOOK, secrets=['private-secret-value'])
            first = reader.read(section_id='overview', include_code=True)
            self.assertNotIn('private-secret-value', json.dumps(first))
            self.assertNotIn('sk-abcdefghijklmnop', json.dumps(first))
            with patch.object(Path, 'open', side_effect=AssertionError('cached file reread')):
                self.assertEqual(reader.read(section_id='overview', include_code=True)['code'], first['code'])
            path.write_text('def sample():\n    return "new implementation"\n')
            second = reader.read(section_id='overview', include_code=True)
            self.assertIn('new implementation', second['code'][0]['content'])
            self.assertNotEqual(second['code'][0]['version'], first['code'][0]['version'])

    def test_missing_source_is_marked_and_handbook_still_returns(self):
        catalog = copy.deepcopy(CATALOG)
        catalog['topics'][0]['code'] = [{'path': 'not_present.py', 'symbol': 'missing'}]
        result = BotManual(ROOT, catalog, HANDBOOK).read(section_id='overview', include_code=True)
        self.assertTrue(result['topics'][0]['content'])
        self.assertTrue(result['code'][0]['unavailable'])
        self.assertNotIn(str(ROOT), json.dumps(result))

    def test_portable_worker_uses_the_supplied_handbook_and_current_target_source(self):
        bridge = RemoteBridge('test', str(ROOT), 'python', SHARED)
        bootstrap = bridge._bootstrap_arguments()
        namespace = {}
        exec(compile(bootstrap['bot_manual_reader'], 'portable_bot_manual', 'exec'), namespace)
        reader = namespace['BotManual'](ROOT, bootstrap['bot_manual_catalog'], bootstrap['bot_manual_handbook'])
        with patch.dict(remote_worker.CONTEXT, {'store': object(), 'bot_manual': reader}, clear=True):
            result = remote_worker.dispatch({'op': 'bot_manual', 'section_id': 'profiles', 'include_code': True})
        self.assertIn('target=bot', result['topics'][0]['content'])
        self.assertTrue(any("args.target == \"bot\"" in item.get('content', '') for item in result['code']))
        self.assertNotIn('code', load_catalogs(SHARED)['bot_info']['topics'][0])


class ManualToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.reader = BotManual(ROOT, CATALOG, HANDBOOK)
        self.bridge = AsyncMock()
        self.bridge.call.side_effect = lambda op, **args: self.reader.read(**args) if op == 'bot_manual' else None
        self.registry = ToolRegistry()
        register_application_tools(self.registry, service=Capabilities(self.bridge), catalogs=load_catalogs(SHARED))

    async def test_metadata_tool_is_discovered_then_used_without_group_permission(self):
        model = ScriptedModel([
            {'role': 'assistant', 'content': '', 'tool_calls': [call('discover_tools', {'categories': ['bot_info']}, 'd')]},
            {'role': 'assistant', 'content': '', 'tool_calls': [call('read_bot_manual', {'query': '机器人怎样读取自己的头像？', 'limit': 1, 'include_code': True}, 'm')]},
            {'role': 'assistant', 'content': 'QQ使用绑定机器人身份读取头像，本地Web尚未注入实时资料读取器。'},
        ])
        state, sink = State(), Sink()
        runtime = AgentRuntime(model=model, registry=self.registry, state=state, output=sink, clock=Clock())
        result = await runtime.run(RunRequest('你能看自己的QQ头像吗？', 's', Principal('user'),
            system_prompt=application_prompt(), required_tools=('discover_tools',)))
        self.assertIn('本地Web', result['text'])
        self.assertNotIn('read_bot_manual', [item['function']['name'] for item in model.schemas[0]])
        self.assertIn('read_bot_manual', [item['function']['name'] for item in model.schemas[1]])
        observation = next(event['data']['result'] for event in sink.events
                           if event['kind'] == 'tool.result' and event['data']['name'] == 'read_bot_manual')
        self.assertTrue(observation['ok'])
        profile = next(item for item in observation['data']['tool_availability'] if item['name'] == 'read_group_member_profile')
        self.assertFalse(profile['registered'])
        self.assertFalse(profile['authorized'])
        self.assertEqual([event['kind'] for event in sink.events].count('tool.result'), 2)

    async def test_tool_rejects_arbitrary_files_and_marks_current_channel_permissions(self):
        ctx = ToolContext(RunRequest('手册', 's', Principal('user', attributes={'delivery': {'platform': 'qq'}})), AsyncMock())
        ctx.disclosed.add('read_bot_manual')
        rejected = await execute(self.registry, call('read_bot_manual', {'path': '.env'}, 'bad'), ctx)
        self.assertEqual(rejected.code, 'INVALID_ARGUMENTS')
        self.bridge.call.assert_not_awaited()
        result = await execute(self.registry, call('read_bot_manual', {'section_id': 'permissions'}, 'ok'), ctx)
        self.assertTrue(result.ok)
        self.assertEqual(result.data['current_channel'], 'qq')
        self.assertTrue(all(item['registered'] and not item['authorized'] for item in result.data['tool_availability']
                            if item['name'] != 'read_group_member_profile'))


if __name__ == '__main__':
    unittest.main()
