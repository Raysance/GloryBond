import json
import unittest
from unittest.mock import patch

from redis.exceptions import WatchError

from local_debugger import import_hok_module


ZFUNC = import_hok_module("zfunc")
ZTIME = import_hok_module("ztime")


class MemoryRedis:
    """In-memory Redis hash/list operations with optimistic-write conflicts."""

    def __init__(self):
        self.hashes = {}
        self.lists = {}
        self.pipeline_count = 0
        self.conflicts = 0
        self.on_conflict = None
        self.watched_keys = []

    def hvals(self, key):
        return list(self.hashes.get(key, {}).values())

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hlen(self, key):
        return len(self.hashes.get(key, {}))

    def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    def hdel(self, key, field):
        if field not in self.hashes.get(key, {}):
            return 0
        del self.hashes[key][field]
        return 1

    def lrange(self, key, start, end):
        values = self.lists.get(key, [])
        return values[start:] if end == -1 else values[start:end + 1]

    def delete(self, key):
        existed = key in self.hashes or key in self.lists
        self.hashes.pop(key, None)
        self.lists.pop(key, None)
        return int(existed)

    def pipeline(self):
        self.pipeline_count += 1
        return MemoryPipeline(self)


class MemoryPipeline:
    def __init__(self, redis):
        self.redis = redis
        self.pending = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.pending = []

    def watch(self, key):
        self.redis.watched_keys.append(key)

    def hget(self, key, field):
        return self.redis.hget(key, field)

    def hlen(self, key):
        return self.redis.hlen(key)

    def multi(self):
        pass

    def hset(self, key, field, value):
        self.pending.append((key, field, value))

    def execute(self):
        if self.redis.conflicts:
            self.redis.conflicts -= 1
            if self.redis.on_conflict:
                self.redis.on_conflict()
            raise WatchError("another writer changed the watched user namespace")
        for args in self.pending:
            self.redis.hset(*args)
        return [1] * len(self.pending)


class ChatMemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.redis = MemoryRedis()
        self.now = "2026-09-29 10:00:00"
        for patcher in (
            patch.object(ZFUNC.dmc, "redis_deamon", self.redis),
            patch.object(ZFUNC.dmc, "ChatMemoryMaxItems", 2, create=True),
            patch.object(ZFUNC.dmc, "ChatMemoryMaxChars", 2000, create=True),
            patch.object(ZTIME, "current_datetime_text", lambda: self.now),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_list_update_delete_and_clear_are_scoped_to_the_current_user(self):
        alpha = ZFUNC.chat_memory_save("100", "I play support")["memory"]
        beta = ZFUNC.chat_memory_save("200", "I play jungle")["memory"]

        self.assertEqual(ZFUNC.chat_memory_list("100")["memories"], [alpha])
        self.assertEqual(ZFUNC.chat_memory_list("200")["memories"], [beta])
        self.assertEqual(set(self.redis.hashes), {"hok:memory:facts:100", "hok:memory:facts:200"})
        with self.assertRaisesRegex(ValueError, "not found for current user"):
            ZFUNC.chat_memory_save("100", "overwrite someone else", beta["memory_id"])
        deleted = ZFUNC.chat_memory_delete("100", beta["memory_id"])
        self.assertFalse(deleted["deleted"])
        self.assertEqual(ZFUNC.chat_memory_list("200")["memories"], [beta])

        self.assertEqual(ZFUNC.chat_memory_clear("100"), 1)
        self.assertEqual(ZFUNC.chat_memory_list("100"), {"memories": [], "total": 0})
        self.assertEqual(ZFUNC.chat_memory_list("200")["memories"], [beta])
        self.assertEqual(ZFUNC.chat_memory_clear("100"), 0)

    def test_capacity_blocks_new_facts_but_allows_owned_updates_and_deletes(self):
        first = ZFUNC.chat_memory_save("100", "I play support")["memory"]
        second = ZFUNC.chat_memory_save("100", "I prefer short answers")["memory"]
        with self.assertRaisesRegex(ValueError, "memory limit reached"):
            ZFUNC.chat_memory_save("100", "third fact")

        self.now = "2026-09-30 11:00:00"
        result = ZFUNC.chat_memory_save("100", "I now play jungle", first["memory_id"])
        self.assertTrue(result["saved"])
        self.assertEqual(result["memory"]["created_at"], first["created_at"])
        self.assertEqual(result["memory"]["updated_at"], self.now)
        self.assertEqual(ZFUNC.chat_memory_list("100")["total"], 2)
        self.assertEqual(ZFUNC.chat_memory_delete("100", second["memory_id"]), {
            "deleted": True, "memory_id": second["memory_id"],
        })
        self.assertFalse(ZFUNC.chat_memory_delete("100", second["memory_id"])["deleted"])
        self.assertTrue(ZFUNC.chat_memory_save("100", "replacement fact")["saved"])
        self.assertEqual(ZFUNC.chat_memory_list("100")["total"], 2)

    def test_unknown_update_does_not_create_a_new_fact(self):
        with self.assertRaisesRegex(ValueError, "not found for current user"):
            ZFUNC.chat_memory_save("100", "some fact", "missing-id")
        self.assertEqual(self.redis.hashes, {})

    def test_legacy_records_can_be_retrieved_but_not_overwritten_or_deleted(self):
        self.redis.lists["hok:memory:forced_mem:100"] = [
            json.dumps({"time": "2026-09-20 10:00:00", "mem": "I play support"}),
        ]
        self.redis.lists["hok:memory:forced_mem:200"] = [
            json.dumps({"time": "2026-09-20 10:00:00", "mem": "another user's private fact"}),
        ]
        legacy = ZFUNC.chat_memory_list("100")["memories"][0]
        self.assertEqual(legacy["content"], "I play support")
        self.assertEqual(legacy["source"], "legacy_forced")
        self.assertTrue(legacy["read_only"])
        with self.assertRaisesRegex(ValueError, "legacy memory is read-only"):
            ZFUNC.chat_memory_save("100", "overwrite legacy", legacy["memory_id"])
        with self.assertRaisesRegex(ValueError, "legacy memory is read-only"):
            ZFUNC.chat_memory_delete("100", legacy["memory_id"])
        # The existing clear command separately clears ZMemory's legacy lists.
        ZFUNC.chat_memory_clear("100")
        self.assertEqual(ZFUNC.chat_memory_list("100")["memories"], [legacy])

    def test_retrieval_can_filter_and_bound_results_without_changing_the_total(self):
        ZFUNC.chat_memory_save("100", "I play support")
        self.now = "2026-09-30 11:00:00"
        new = ZFUNC.chat_memory_save("100", "I prefer short answers")["memory"]

        recent = ZFUNC.chat_memory_list("100", limit=1)
        self.assertEqual(recent, {"memories": [new], "total": 2})
        match = ZFUNC.chat_memory_list("100", query="support", limit=1)
        self.assertEqual([item["content"] for item in match["memories"]], ["I play support"])
        self.assertEqual(match["total"], 2)
        self.assertEqual(ZFUNC.chat_memory_list("100", query="unrelated"), {"memories": [], "total": 2})

    def test_content_validation_rejects_secrets_without_echo_or_storage(self):
        secret = "sk-test-private-credential-12345"
        for content in (" ", "x" * 2001, secret):
            with self.subTest(length=len(content)), self.assertRaises(ValueError) as caught:
                ZFUNC.chat_memory_save("100", content)
            self.assertNotIn(secret, str(caught.exception))
        self.assertEqual(self.redis.hashes, {})
        with patch.object(ZFUNC.dmc, "ChatMemoryMaxChars", 5):
            with self.assertRaisesRegex(ValueError, "exceeds 5"):
                ZFUNC.chat_memory_save("100", "longer than configured")

    def test_configured_larger_content_limit_is_consistent_when_listing(self):
        content = "x" * 2200
        with patch.object(ZFUNC.dmc, "ChatMemoryMaxChars", 2500):
            saved = ZFUNC.chat_memory_save("100", content)["memory"]
            self.assertEqual(ZFUNC.chat_memory_list("100"), {"memories": [saved], "total": 1})

    def test_empty_user_or_deletion_id_cannot_select_an_implicit_namespace(self):
        for user in ("", "   ", None):
            for operation in (
                lambda: ZFUNC.chat_memory_list(user),
                lambda: ZFUNC.chat_memory_save(user, "some fact"),
                lambda: ZFUNC.chat_memory_delete(user, "fact-id"),
                lambda: ZFUNC.chat_memory_clear(user),
            ):
                with self.subTest(user=user, operation=operation), self.assertRaises(ValueError):
                    operation()
        with self.assertRaises(ValueError):
            ZFUNC.chat_memory_delete("100", "")
        self.assertEqual(self.redis.hashes, {})

    def test_optimistic_conflict_retries_without_duplicate_records(self):
        self.redis.conflicts = 1
        result = ZFUNC.chat_memory_save("100", "I play support")

        self.assertTrue(result["saved"])
        self.assertEqual(self.redis.pipeline_count, 2)
        self.assertEqual(self.redis.watched_keys, ["hok:memory:facts:100"] * 2)
        self.assertEqual(ZFUNC.chat_memory_list("100"), {"memories": [result["memory"]], "total": 1})

    def test_contended_writer_rechecks_capacity_before_retrying(self):
        self.redis.conflicts = 1
        self.redis.on_conflict = lambda: self.redis.hset(
            "hok:memory:facts:100", "other-writer", json.dumps({
                "memory_id": "other-writer", "content": "committed by another writer",
                "created_at": self.now, "updated_at": self.now,
            }),
        )
        with patch.object(ZFUNC.dmc, "ChatMemoryMaxItems", 1):
            with self.assertRaisesRegex(ValueError, "memory limit reached"):
                ZFUNC.chat_memory_save("100", "must not overfill")

        self.assertEqual(self.redis.pipeline_count, 2)
        self.assertEqual(list(self.redis.hashes["hok:memory:facts:100"]), ["other-writer"])

    def test_persistent_contention_returns_failure_instead_of_false_confirmation(self):
        self.redis.conflicts = 3
        with self.assertRaisesRegex(RuntimeError, "memory changed concurrently"):
            ZFUNC.chat_memory_save("100", "I play support")
        self.assertEqual(self.redis.pipeline_count, 3)
        self.assertEqual(self.redis.hashes, {})


if __name__ == "__main__":
    unittest.main()
