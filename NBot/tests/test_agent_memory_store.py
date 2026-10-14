"""Owned fact writes and QQ context clearing use the current worker store."""
import json
import unittest
from unittest.mock import patch
from agent_console import remote_worker as worker
from agent_console.tools import memory


class Store:
    def __init__(self):
        self.hashes, self.values, self.transactions = {}, {}, []
    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)
    def hvals(self, key):
        return list(self.hashes.get(key, {}).values())
    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))
    def hlen(self, key):
        return len(self.hashes.get(key, {}))
    def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value
    def hdel(self, key, *fields):
        return sum(bool(self.hashes.get(key, {}).pop(field, None)) for field in fields)
    def delete(self, *keys):
        count=0
        for key in keys:
            count += bool(self.hashes.pop(key, None) or self.values.pop(key, None))
        return count
    def pipeline(self, **kwargs):
        return Pipeline(self)


class Pipeline:
    def __init__(self, store):
        self.store, self.pending = store, []
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def watch(self, key):
        pass
    def hget(self, *args):
        return self.store.hget(*args)
    def hlen(self, *args):
        return self.store.hlen(*args)
    def hgetall(self, *args):
        return self.store.hgetall(*args)
    def multi(self):
        pass
    def hset(self, *args):
        self.pending.append(('hset', args))
    def hdel(self, *args):
        self.pending.append(('hdel', args))
    def execute(self):
        self.store.transactions.append(list(self.pending))
        for operation, args in self.pending:
            getattr(self.store, operation)(*args)


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.store=Store()
        patcher=patch.dict(worker.CONTEXT,store=self.store,memory=memory.__dict__)
        patcher.start()
        self.addCleanup(patcher.stop)
    def call(self, user, action, **args):
        return worker.memory({'user_id':user,'action':action,**args})
    def test_writes_updates_retrieval_and_deletions_are_owned(self):
        first=self.call('101','remember',content='I prefer support')['memory']
        other=self.call('102','remember',content='I prefer jungle')['memory']
        updated=self.call('101','remember',content='I prefer concise replies',memory_id=first['memory_id'])['memory']
        self.assertEqual(updated['created_at'],first['created_at'])
        self.assertEqual(self.call('101','recall')['memories'],[updated])
        self.assertFalse(self.call('101','forget',memory_id=other['memory_id'])['deleted'])
        self.assertEqual(self.call('102','recall')['memories'],[other])
        with self.assertRaises(ValueError):
            self.call('101','remember',content='cannot create missing update',memory_id='missing')
    def test_clear_removes_current_context_and_facts_without_clearing_other_channels(self):
        self.call('101','remember',content='favorite hero')
        self.call('102','remember',content='another user')
        target=worker.STATE_PREFIX+'dialogue:qq_g_200_101'
        private=worker.STATE_PREFIX+'dialogue:qq_p_101'
        self.store.values.update({target:['group'],private:['private']})
        with self.assertRaises(ValueError):
            self.call('101','clear',session_id='qq_g_200_102')
        self.assertIn(target,self.store.values)
        self.assertTrue(self.call('101','clear',session_id='qq_g_200_101')['cleared'])
        self.assertEqual(self.call('101','recall')['total'],0)
        self.assertNotIn(target,self.store.values)
        self.assertIn(private,self.store.values)
        self.assertEqual(self.call('102','recall')['total'],1)

    def test_correction_replaces_conflicting_facts_atomically_and_preserves_other_preferences(self):
        first = self.call('101', 'remember', content='主玩辅助')['memory']
        conflict = self.call('101', 'remember', content='喜欢打辅助位置')['memory']
        unrelated = self.call('101', 'remember', content='喜欢简短回复')['memory']
        result = self.call('101', 'remember', content='一直主玩中路，不是辅助', memory_id=first['memory_id'],
                           supersedes=[conflict['memory_id'], conflict['memory_id'], first['memory_id']])
        self.assertTrue(result['changed'])
        self.assertEqual(result['memory']['memory_id'], first['memory_id'])
        self.assertEqual(result['memory']['created_at'], first['created_at'])
        self.assertEqual(result['superseded'], [conflict['memory_id']])
        self.assertEqual([operation for operation, args in self.store.transactions[-1]], ['hset', 'hdel'])
        self.assertEqual({row['content'] for row in self.call('101', 'recall')['memories']},
                         {'一直主玩中路，不是辅助', unrelated['content']})

    def test_invalid_cross_user_or_secret_replacement_never_partially_modifies_facts(self):
        mine = self.call('101', 'remember', content='主玩辅助')['memory']
        other = self.call('102', 'remember', content='喜欢安琪拉')['memory']
        before = dict(self.store.hashes['hok:memory:facts:101'])
        for removed in ['missing', other['memory_id'], 'legacy-old', 'invalid:id']:
            with self.subTest(removed=removed), self.assertRaises(ValueError):
                self.call('101', 'remember', content='主玩中路', memory_id=mine['memory_id'], supersedes=[removed])
            self.assertEqual(self.store.hashes['hok:memory:facts:101'], before)
        with self.assertRaises(ValueError):
            self.call('101', 'remember', content='sk-test-private-credential-12345', memory_id=mine['memory_id'])
        self.assertEqual(self.store.hashes['hok:memory:facts:101'], before)
        self.assertEqual(self.call('102', 'recall')['memories'], [other])

    def test_duplicate_writes_are_idempotent_and_correction_works_at_capacity(self):
        for number in range(100):
            self.call('101', 'remember', content=f'事实{number}')
        record = self.call('101', 'recall')['memories'][0]
        duplicate = self.call('101', 'remember', content=' ' + record['content'] + ' ')
        self.assertFalse(duplicate['changed'])
        self.assertEqual(duplicate['memory'], record)
        self.assertEqual(self.call('101', 'recall')['total'], 100)
        with self.assertRaises(ValueError):
            self.call('101', 'remember', content='超限新事实')
        updated = self.call('101', 'remember', content='纠正后的事实', supersedes=[record['memory_id']])
        self.assertEqual(updated['memory']['memory_id'], record['memory_id'])
        self.assertEqual(self.call('101', 'recall')['total'], 100)
        same = self.call('101', 'remember', content='纠正后的事实', memory_id=record['memory_id'])
        self.assertFalse(same['changed'])


class MemoryToolIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_implicit_correction_tools_update_owned_facts_and_log_replacements(self):
        from agent_runtime import AgentRuntime, Principal, RunRequest, ToolRegistry
        from agent_console.capabilities import Capabilities, application_prompt
        from agent_console.tools.application import register_application_tools
        from tests.test_agent_runtime import Clock, ScriptedModel, Sink, State, call
        store = Store()
        with patch.dict(worker.CONTEXT, store=store, memory=memory.__dict__):
            first = worker.memory({'user_id': '101', 'action': 'remember', 'content': '主玩辅助'})['memory']
            second = worker.memory({'user_id': '101', 'action': 'remember', 'content': '常用辅助位'})['memory']
            class Bridge:
                async def call(self, operation, **args):
                    self_case.assertEqual(operation, 'memory')
                    return worker.memory(args)
            self_case = self
            registry = ToolRegistry()
            register_application_tools(registry, service=Capabilities(Bridge()), catalogs={})
            model = ScriptedModel([
                {'role': 'assistant', 'content': '', 'tool_calls': [call('discover_tools', {'categories': ['memory']}, 'd')]},
                {'role': 'assistant', 'content': '', 'tool_calls': [call('recall_memory', {'query': '辅助位置'}, 'r')]},
                {'role': 'assistant', 'content': '', 'tool_calls': [call('remember_memory',
                    {'content': '一直主玩中路，不是辅助', 'memory_id': first['memory_id'], 'supersedes': [second['memory_id']]}, 'm')]},
                {'role': 'assistant', 'content': '明白了，你一直主玩中路，已更新。'},
            ])
            state = State()
            runtime = AgentRuntime(model=model, registry=registry, state=state, output=Sink(), clock=Clock())
            question = '你理解错了，我一直主玩中路，不是辅助。'
            await runtime.run(RunRequest(question, 'correction', Principal('101', frozenset({'memory.use'})),
                                         system_prompt=application_prompt(), required_tools=('discover_tools',)))
            facts = worker.memory({'user_id': '101', 'action': 'recall'})['memories']
        self.assertEqual([row['content'] for row in facts], ['一直主玩中路，不是辅助'])
        self.assertIn(second['memory_id'], json.dumps(state.events))
        self.assertIn('superseded', json.dumps(state.events))
        self.assertEqual(state.dialogue[0]['content'], question)
