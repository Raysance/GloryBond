"""Owned fact writes and QQ context clearing use the current worker store."""
import json
import unittest
from unittest.mock import patch
from agent_console import remote_worker as worker
from agent_console.tools import memory


class Store:
    def __init__(self):
        self.hashes, self.values = {}, {}
    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)
    def hvals(self, key):
        return list(self.hashes.get(key, {}).values())
    def hlen(self, key):
        return len(self.hashes.get(key, {}))
    def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value
    def hdel(self, key, field):
        return bool(self.hashes.get(key, {}).pop(field, None))
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
    def multi(self):
        pass
    def hset(self, *args):
        self.pending.append(args)
    def execute(self):
        for args in self.pending:
            self.store.hset(*args)


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
