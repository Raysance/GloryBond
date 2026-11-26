"""Variety history stays bounded, scoped and distinct from delivery records."""
import json
import unittest
from unittest.mock import patch

from tools.debugger import import_project_module
from tests.test_zfunc_chat_history import FakeRedisList

HISTORY = import_project_module("glorybond.storage.poke_history")
RUNTIME = import_project_module("glorybond.runtime")


class HistoryStore(FakeRedisList):
    def __init__(self):
        super().__init__()
        self.expirations = {}

    def pipeline(self, *, transaction):
        assert transaction
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def expire(self, key, seconds):
        self.expirations[key] = seconds

    def execute(self):
        return []


class PokeHistoryTests(unittest.TestCase):
    def setUp(self):
        self.store = HistoryStore()
        patcher = patch.object(RUNTIME, "redis_deamon", self.store)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_generated_history_is_bounded_per_group_with_one_day_expiry(self):
        for index in range(30):
            HISTORY.record_generated("200", f"话题{index}", as_of=1000+index)
        HISTORY.record_generated("201", "另一个群", as_of=1000, source_message_ids=["source1"])
        result = HISTORY.recent_generated("200", as_of=2000)
        self.assertEqual([r["topic"] for r in result], [f"话题{i}" for i in range(18, 30)])
        self.assertTrue(all(seconds == 86400 for seconds in self.store.expirations.values()))
        self.assertEqual(HISTORY.recent_generated("201", as_of=2000)[0],
                         {"timestamp": 1000, "topic": "另一个群", "source_message_ids": ["source1"]})

    def test_expired_future_and_corrupt_records_are_not_reference_material(self):
        key = HISTORY._key("200")
        self.store.values[key] = [json.dumps(row) for row in (
            {"timestamp": 1, "topic": "过期"}, {"timestamp": 99999, "topic": "可用"},
            {"timestamp": 100001, "topic": "未来"}, [], {"timestamp": "bad", "topic": "坏记录"})] + ["bad-json"]
        self.assertEqual(HISTORY.recent_generated("200", as_of=100000), [{"timestamp": 99999, "topic": "可用", "source_message_ids": []}])

    def test_missing_group_has_no_state_and_invalid_groups_are_rejected(self):
        HISTORY.record_generated(None, "文字", as_of=1000)
        self.assertEqual(HISTORY.recent_generated(None, as_of=1000), [])
        self.assertEqual(self.store.values, {})
        for group in ("0", "-1", "unknown", "200:private"):
            with self.subTest(group=group), self.assertRaises(ValueError):
                HISTORY.recent_generated(group, as_of=1000)


if __name__ == "__main__":
    unittest.main()
