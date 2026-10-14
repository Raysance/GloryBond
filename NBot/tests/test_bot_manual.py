"""Scoped tree retrieval, independent docs and gated source fallback."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from agent_runtime import AgentRuntime, Principal, RunRequest, ToolRegistry
from agent_runtime.models import ToolContext
from agent_runtime.tools.executor import execute
from agent_console.bot_manual import BotManual, handbook_text, load_manual_documents
from agent_console.capabilities import Capabilities, application_prompt, load_catalogs
from agent_console.remote import RemoteBridge
from agent_console import remote_worker
from agent_console.tools.application import register_application_tools
from tests.test_agent_runtime import Clock, ScriptedModel, Sink, State, call

ROOT = Path(__file__).parents[1]
SHARED = ROOT / 'shared/agent'
CATALOG = json.loads((SHARED / 'manual/catalog.json').read_text())
DOCUMENTS = load_manual_documents(ROOT, CATALOG)


class ManualTests(unittest.TestCase):
    def setUp(self):
        self.catalog = copy.deepcopy(CATALOG)
        self.documents = dict(DOCUMENTS)
        self.manual = BotManual(ROOT, self.catalog, self.documents)

    def test_root_only_returns_paginated_child_cards_and_discovery_is_brief(self):
        result = self.manual.read()
        self.assertEqual([n['node_id'] for n in result['topics']], ['conversation', 'game', 'creation'])
        self.assertEqual(result['next_offset'], 3)
        self.assertTrue(all('content' not in n for n in result['topics']))
        more = self.manual.read(offset=3)
        self.assertEqual(len(more['topics']), 3)
        self.assertIsNone(more['next_offset'])
        discovery = load_catalogs(SHARED)['bot_info']
        self.assertEqual(len(discovery['topics']), 6)
        self.assertNotIn('code_positions', json.dumps(discovery))
        self.assertNotIn('metrics_power_formula', json.dumps(discovery))

    def test_questions_follow_scoped_paths_to_precise_leaves(self):
        for question, path in [('底蕴怎么算', ['manual','game','metrics','metrics_power_formula']),
                               ('图片生成API', ['manual','creation','plots','plots_image_service'])]:
            for parent, child in zip(path, path[1:]):
                with self.subTest(question=question, parent=parent):
                    self.assertEqual(self.manual.read(action='search', node_id=parent, query=question, limit=1)['topics'][0]['node_id'], child)
            result = self.manual.read(action='read', node_id=path[-1])
            self.assertTrue(result['topics'][0]['content'])
            self.assertEqual(result['code'], [])
            self.assertEqual([i['node_id'] for i in result['breadcrumb']], path)

    def test_other_subtree_growth_does_not_change_feature_search(self):
        path = 'shared/agent/manual/chapters/emoji.md'
        self.documents[path] += '\n底蕴怎么算，MVP战斗力评分。' * 500
        expanded = BotManual(ROOT, self.catalog, self.documents)
        original = self.manual.read(action='search', node_id='metrics', query='底蕴怎么算')
        self.assertEqual(expanded.read(action='search', node_id='metrics', query='底蕴怎么算')['topics'], original['topics'])
        absent = self.manual.read(action='search', node_id='metrics', query='APIMart API')
        self.assertTrue(absent['not_found'])
        self.assertEqual(absent['topics'], [])
        self.assertTrue(absent['node']['code_positions'])

    def test_functional_details_and_source_citations_are_specific(self):
        for node, phrase in [('metrics_power_formula', '固定基准8'), ('metrics_power_scope', '不是按个人单人底蕴排序'),
                             ('metrics_contribution', '团队贡献系数'), ('metrics_game_time', '大厅'),
                             ('heroes_sample_rules', '至少2场'), ('representative_rules', '300至7200'),
                             ('plots_image_service', 'gpt-image-2'), ('history_query_rules', '匹配0局'),
                             ('history_window_limits', '15分钟'), ('memory_update_rules', '最多100条')]:
            with self.subTest(node=node):
                result = self.manual.read(action='read', node_id=node)
                self.assertIn(phrase, result['topics'][0]['content'])
                source = result['topics'][0]['source']
                self.assertIn('/chapters/', source['path'])
                self.assertGreaterEqual(source['end_line'], source['start_line'])
                self.assertNotIn('ReAct', result['topics'][0]['content'])

    def test_every_declared_source_resolves_and_focus_extracts_the_formula(self):
        for node in self.catalog['topics']:
            for reference in node.get('code', []):
                with self.subTest(node=node['id'], reference=reference):
                    result = self.manual._source(reference, 6000)
                    self.assertEqual(result['evidence'], 'deployed_source')
                    self.assertLessEqual(len(result['content']), self.catalog['limits']['max_code_excerpt_chars'])
        result = self.manual.read(action='code', node_id='metrics_power_formula', fallback_reason='检查公式权重')
        self.assertIn('pow(equiv_star, 0.3)', result['code'][0]['content'])
        self.assertEqual(result['code'][0]['focus'], 'single_level')

    def test_cycles_missing_parents_and_branch_documents_are_rejected(self):
        for change in ['cycle','parent','branch_doc','duplicate','missing_heading']:
            catalog = copy.deepcopy(CATALOG)
            nodes = {n['id']:n for n in catalog['topics']}
            if change == 'cycle': nodes['game']['parent'] = 'metrics'
            elif change == 'parent': nodes['game']['parent'] = 'missing'
            elif change == 'branch_doc': nodes['game']['document'] = nodes['metrics_power_formula']['document']
            elif change == 'duplicate': catalog['topics'].append(copy.deepcopy(nodes['game']))
            else: nodes['metrics_power_formula']['document']['heading'] = '不存在的标题'
            with self.subTest(change=change), self.assertRaises(ValueError):
                BotManual(ROOT, catalog, DOCUMENTS)

    def test_documents_reject_private_paths_and_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root/'shared/agent/manual/chapters'
            directory.mkdir(parents=True)
            (root/'.env').write_text('must-not-read')
            (directory/'redirect.md').symlink_to(root/'.env')
            for path in ['.env','config.yaml','../private.md','/tmp/private.md','shared/agent/manual/chapters/redirect.md']:
                catalog = copy.deepcopy(CATALOG)
                catalog['topics'] = [{'document': {'path': path}}]
                with self.subTest(path=path), patch.object(Path, 'open', side_effect=AssertionError('private file read')), self.assertRaises(ValueError):
                    load_manual_documents(root, catalog)

    def test_code_rejects_private_paths_and_missing_source_is_explicit(self):
        node = next(n for n in self.catalog['topics'] if n['id']=='metrics_power_formula')
        for path in ['.env','config.yaml','../private.py','/tmp/private.py']:
            node['code'] = [{'path':path,'symbol':'f'}]
            with self.subTest(path=path), patch.object(Path,'open',side_effect=AssertionError('private file read')):
                result = self.manual.read(action='code',node_id=node['id'],fallback_reason='未找到规则说明')
            self.assertTrue(result['code'][0]['unavailable'])
        node['code']=[{'path':'not_present.py','symbol':'f'}]
        result=self.manual.read(action='code',node_id=node['id'],fallback_reason='未找到规则说明')
        self.assertTrue(result['code'][0]['unavailable'])
        self.assertNotIn(str(ROOT),json.dumps(result))

    def test_source_refreshes_without_execution_and_secrets_are_redacted(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'example.py'
            path.write_text('raise RuntimeError("do not execute")\ndef sample():\n    return "private-secret-value", "sk-abcdefghijklmnop"\n')
            node=next(n for n in self.catalog['topics'] if n['id']=='metrics_power_formula')
            node['code']=[{'path':'example.py','symbol':'sample'}]
            reader=BotManual(directory,self.catalog,DOCUMENTS,secrets=['private-secret-value'])
            first=reader.read(action='code',node_id=node['id'],fallback_reason='核对计算细节')
            self.assertNotIn('private-secret-value',json.dumps(first))
            self.assertNotIn('sk-abcdefghijklmnop',json.dumps(first))
            path.write_text('def sample():\n    return "updated"\n')
            second=reader.read(action='code',node_id=node['id'],fallback_reason='核对计算细节')
            self.assertIn('updated',second['code'][0]['content'])
            self.assertNotEqual(first['code'][0]['version'],second['code'][0]['version'])

    def test_content_budgets_paginate_and_stale_version_cannot_read_code(self):
        self.manual.limits['max_handbook_chars']=30
        first=self.manual.read(action='read',node_id='metrics_power_formula')
        second=self.manual.read(action='read',node_id='metrics_power_formula',offset=first['next_offset'])
        self.assertEqual(len(first['topics'][0]['content']),30)
        self.assertTrue(second['topics'][0]['truncated'])
        with patch.object(Path,'open',side_effect=AssertionError('code read before version check')), self.assertRaises(ValueError):
            self.manual.read(action='code',node_id='metrics_power_formula',fallback_reason='公式缺少说明',expected_version='stale')
        for options in [{'limit':True},{'limit':6},{'offset':True},{'query':'x'*401},{'node_id':'../../.env'},
                        {'action':'code','node_id':'metrics'},{'action':'code','node_id':'metrics_power_formula'}]:
            with self.subTest(options=options),self.assertRaises(ValueError): self.manual.read(**options)

    def test_images_and_fenced_headings_are_not_search_evidence(self):
        example='![秘密图片关键词](https://media.invalid/one.png)\n<img src="https://media.invalid/two.png" alt="私密图"/>\n```text\n### 虚假的新章节\n```\n可见说明'
        self.assertNotIn('media.invalid',handbook_text(example))
        path='shared/agent/manual/chapters/metrics_power_formula.md'
        self.documents[path]+='\n'+example
        reader=BotManual(ROOT,self.catalog,self.documents)
        result=reader.read(action='read',node_id='metrics_power_formula')
        self.assertIn('可见说明',result['topics'][0]['content'])
        self.assertNotIn('秘密图片关键词',json.dumps(result))
        self.assertNotIn('media.invalid',json.dumps(result))

    def test_bootstrap_ships_declared_documents_and_worker_reads_supplied_tree(self):
        bridge=RemoteBridge('test',str(ROOT),'python',SHARED)
        args=bridge._bootstrap_arguments()
        namespace={}
        exec(compile(args['bot_manual_reader'],'portable_manual','exec'),namespace)
        reader=namespace['BotManual'](ROOT,args['bot_manual_catalog'],args['bot_manual_documents'])
        with patch.dict(remote_worker.CONTEXT,store=object(),bot_manual=reader,clear=True):
            result=remote_worker.dispatch({'op':'bot_manual','action':'read','node_id':'plots_image_service'})
        self.assertIn('APIMart',result['topics'][0]['content'])
        self.assertNotIn('bot_manual_handbook',args)


class ManualToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.reader=BotManual(ROOT,CATALOG,DOCUMENTS)
        self.bridge=AsyncMock()
        self.bridge.call.side_effect=lambda op,**args:self.reader.read(**args) if op=='bot_manual' else None
        self.registry=ToolRegistry()
        register_application_tools(self.registry,service=Capabilities(self.bridge),catalogs=load_catalogs(SHARED))

    def context(self):
        ctx=ToolContext(RunRequest('手册','s',Principal('user',attributes={'delivery':{'platform':'qq'}})),AsyncMock())
        ctx.disclosed.add('read_bot_manual')
        return ctx

    async def test_code_requires_complete_read_of_same_leaf_and_explicit_missing_fact(self):
        ctx=self.context()
        args={'action':'code','node_id':'metrics_power_formula','fallback_reason':'核对新增权重'}
        result=await execute(self.registry,call('read_bot_manual',args),ctx)
        self.assertFalse(result.ok)
        self.bridge.call.assert_not_awaited()
        read=await execute(self.registry,call('read_bot_manual',{'action':'read','node_id':'metrics_power_formula'}),ctx)
        self.assertTrue(read.ok)
        for invalid in [{'action':'code','node_id':'plots_image_service','fallback_reason':'未知API'},
                        {'action':'code','node_id':'metrics_power_formula'}]:
            self.assertFalse((await execute(self.registry,call('read_bot_manual',invalid),ctx)).ok)
        result=await execute(self.registry,call('read_bot_manual',args),ctx)
        self.assertTrue(result.ok)
        self.assertIn('single_level',result.data['code'][0]['content'])
        self.assertEqual(result.data['current_channel'],'qq')
        self.assertFalse((await execute(self.registry,call('read_bot_manual',args),self.context())).ok)

    async def test_skipping_a_body_page_cannot_enable_fallback(self):
        self.reader.limits['max_handbook_chars']=100
        ctx=self.context()
        async def read(offset):
            return await execute(self.registry,call('read_bot_manual',{'action':'read','node_id':'metrics_power_formula','offset':offset}),ctx)
        first=await read(0)
        await read(100000)
        code={'action':'code','node_id':'metrics_power_formula','fallback_reason':'公式缺失'}
        self.assertFalse((await execute(self.registry,call('read_bot_manual',code),ctx)).ok)
        offset=first.data['next_offset']
        while offset is not None:
            page=await read(offset);offset=page.data['next_offset']
        self.assertTrue((await execute(self.registry,call('read_bot_manual',code),ctx)).ok)

    async def test_react_discovery_navigation_read_then_code_produces_bounded_observations(self):
        steps=[{'categories':['bot_info']}, {'action':'search','query':'底蕴怎么算'},
               {'action':'search','query':'底蕴怎么算','node_id':'game'},
               {'action':'search','query':'底蕴怎么算','node_id':'metrics'},
               {'action':'read','node_id':'metrics_power_formula'},
               {'action':'code','node_id':'metrics_power_formula','fallback_reason':'核对当前公式权重是否一致'}]
        replies=[{'role':'assistant','content':'','tool_calls':[call('discover_tools' if i==0 else 'read_bot_manual',args,str(i))]}
                 for i,args in enumerate(steps)]
        replies.append({'role':'assistant','content':'底蕴按公式与有效样本计算。'})
        model=ScriptedModel(replies);state=State();sink=Sink()
        runtime=AgentRuntime(model=model,registry=self.registry,state=state,output=sink,clock=Clock())
        await runtime.run(RunRequest('底蕴怎么算','s',Principal('u'),system_prompt=application_prompt()))
        observations=[e['data']['result'] for e in state.events if e['kind']=='tool.result']
        self.assertTrue(all(o['ok'] for o in observations))
        for observation in observations[1:4]:
            self.assertTrue(all('content' not in topic for topic in observation['data']['topics']))
        self.assertEqual(observations[4]['data']['code'],[])
        self.assertTrue(observations[5]['data']['code'])
        self.assertNotIn('APIMart',json.dumps(observations[4]['data']))

    async def test_arbitrary_path_parameters_are_rejected_before_rpc(self):
        result=await execute(self.registry,call('read_bot_manual',{'path':'.env'}),self.context())
        self.assertEqual(result.code,'INVALID_ARGUMENTS')
        self.bridge.call.assert_not_awaited()


if __name__=='__main__': unittest.main()
