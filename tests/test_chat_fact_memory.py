import json
import unittest

from local_debugger import import_hok_module


ZMEMORY = import_hok_module("zmemory")


class ChatFactMemoryTests(unittest.TestCase):
    def test_create_and_update_keep_identity_and_created_time(self):
        original = ZMEMORY.prepare_fact_memory(
            "  我习惯打辅助  ", memory_id="fact-1", timestamp="2026-09-29 10:00:00",
        )
        updated = ZMEMORY.prepare_fact_memory(
            "我现在主玩打野", memory_id="fact-1", timestamp="2026-09-30 10:00:00", existing=original,
        )

        self.assertEqual(original["content"], "我习惯打辅助")
        self.assertEqual(updated["memory_id"], original["memory_id"])
        self.assertEqual(updated["created_at"], original["created_at"])
        self.assertEqual(updated["updated_at"], "2026-09-30 10:00:00")
        self.assertEqual(updated["source"], "direct_user")
        self.assertFalse(updated["read_only"])
        self.assertEqual(original["content"], "我习惯打辅助")

    def test_mismatched_ids_legacy_writes_and_invalid_content_are_rejected(self):
        for kwargs in (
            {"content": " ", "memory_id": "fact-1"},
            {"content": "过长的记忆", "memory_id": "fact-1", "max_chars": 3},
            {"content": "有效内容", "memory_id": "bad:id"},
            {"content": "有效内容", "memory_id": "legacy-read-only"},
            {"content": "有效内容", "memory_id": "new-id", "existing": {"memory_id": "old-id"}},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ZMEMORY.prepare_fact_memory(timestamp="now", **kwargs)

    def test_credential_rejection_does_not_echo_secret(self):
        secret = "sk-test-private-credential-12345"
        with self.assertRaises(ValueError) as caught:
            ZMEMORY.prepare_fact_memory(
                "我的密钥是 " + secret, memory_id="fact-1", timestamp="now",
            )
        self.assertNotIn(secret, str(caught.exception))

    def test_parsing_supports_json_hash_and_stable_readonly_legacy_records(self):
        item = ZMEMORY.prepare_fact_memory(
            "我习惯打辅助", memory_id="fact-1", timestamp="2026-09-29 10:00:00",
        )
        legacy = json.dumps({"time": "2026-09-20 12:00:00", "mem": "我不玩射手"})
        records = ZMEMORY.parse_fact_memories(
            {"fact-1": json.dumps(item).encode(), "bad": "broken-json"},
            legacy_records=[legacy, legacy, "[]", "{}"],
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0], item)
        self.assertEqual(records[1]["source"], "legacy_forced")
        self.assertTrue(records[1]["read_only"])
        self.assertTrue(records[1]["memory_id"].startswith("legacy-"))
        repeated = ZMEMORY.parse_fact_memories([], legacy_records=[legacy])
        self.assertEqual(repeated[0]["memory_id"], records[1]["memory_id"])

    def test_malformed_and_secret_legacy_records_are_not_observations(self):
        records = ZMEMORY.parse_fact_memories(
            ["null", "[]", "{", {"memory_id": "bad:id", "content": "hello"}],
            legacy_records=[{"mem": "sk-test-private-credential-12345"}],
        )
        self.assertEqual(records, [])

    def test_list_and_search_are_bounded_and_do_not_mutate_stored_records(self):
        records = [
            ZMEMORY.prepare_fact_memory("I prefer support", memory_id="old", timestamp="2026-09-20 10:00:00"),
            ZMEMORY.prepare_fact_memory("My main role is jungle", memory_id="new", timestamp="2026-09-29 10:00:00"),
        ]
        recent = ZMEMORY.search_fact_memories(records, limit=1)
        match = ZMEMORY.search_fact_memories(records, query="support", limit=1)

        self.assertEqual([item["memory_id"] for item in recent], ["new"])
        self.assertEqual([item["memory_id"] for item in match], ["old"])
        self.assertEqual(ZMEMORY.search_fact_memories(records, query="unmentioned"), [])
        recent[0]["content"] = "changed"
        self.assertEqual(records[1]["content"], "My main role is jungle")


if __name__ == "__main__":
    unittest.main()
