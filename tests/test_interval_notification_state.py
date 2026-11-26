"""Exercise atomic failure streaks against an explicitly supplied test Redis."""
from concurrent.futures import ThreadPoolExecutor
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from glorybond import runtime
from glorybond.storage.notification_state import record_interval_outcome


@unittest.skipUnless(os.environ.get("HOK_TEST_REDIS_URL"), "requires a dedicated test Redis")
class IntervalNotificationStateTests(unittest.TestCase):
    def setUp(self):
        import redis
        self.client = redis.Redis.from_url(os.environ["HOK_TEST_REDIS_URL"])
        self.addCleanup(self.client.close)
        self.scope = "test:" + uuid4().hex
        self.keys = []
        self.addCleanup(lambda: self.client.delete(*self.keys) if self.keys else None)
        patched = patch.object(runtime, "redis_deamon", self.client)
        patched.start()
        self.addCleanup(patched.stop)

    def record(self, failed=True, suffix=""):
        scope = self.scope + suffix
        self.keys.append("hok:interval_failures:" + scope)
        return record_interval_outcome(scope, failed=failed, threshold=30)

    def test_thirtieth_failure_notifies_once_until_success(self):
        for n in range(1, 30):
            self.assertEqual(self.record(), (n, False))
        self.assertEqual(self.record(), (30, True))
        for n in range(31, 61):
            self.assertEqual(self.record(), (n, False))
        self.assertEqual(self.record(False), (0, False))
        self.assertEqual(self.record(), (1, False))
        for _ in range(28):
            self.record()
        self.assertEqual(self.record(), (30, True))

    def test_platform_phase_and_destination_are_independent(self):
        for _ in range(29):
            self.record(suffix=":bili:poll:group1")
        for scope in (":x:poll:group1", ":bili:delivery:group1", ":bili:poll:group2"):
            self.assertEqual(self.record(suffix=scope), (1, False))
            self.record(False, suffix=scope)
        self.assertEqual(self.record(suffix=":bili:poll:group1"), (30, True))

    def test_reconnect_keeps_streak_and_parallel_failures_claim_one_notice(self):
        for _ in range(20):
            self.record()
        self.client.connection_pool.disconnect()
        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(lambda _: self.record(), range(20)))
        self.assertEqual(sorted(count for count, _ in outcomes), list(range(21, 41)))
        self.assertEqual(sum(notify for _, notify in outcomes), 1)


if __name__ == "__main__":
    unittest.main()
