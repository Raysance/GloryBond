import json
import stat
import tempfile
import unittest

from scripts import migrate_group_chat_history_to_postgres as migration


class FakeRedis:
    def __init__(self, values):
        self.values = values

    def scan_iter(self, match):
        return iter(self.values)

    def lrange(self, key, start, end):
        return self.values.get(key, self.values.get(key.encode()))

    def dump(self, key):
        return b"private-dump"

    def pttl(self, key):
        return -1


class FakeDatabase:
    def __init__(self, records):
        self.records = records

    def load_group_chat_messages(self, group_id):
        return [item for item in self.records if item["group_id"] == group_id]


class GroupChatMigrationTests(unittest.TestCase):
    def test_backup_is_created_privately_and_contains_restorable_dump(self):
        redis = FakeRedis({"hok:chat:group:200": []})
        with tempfile.TemporaryDirectory() as directory:
            path = migration.backup_redis(redis, ["hok:chat:group:200"], directory)
            payload = json.loads(path.read_text())
            mode = stat.S_IMODE(path.stat().st_mode)
        self.assertEqual(mode, 0o600)
        self.assertEqual(payload[0]["key"], "hok:chat:group:200")
        self.assertEqual(payload[0]["ttl_ms"], -1)

    def test_discovery_binds_group_to_redis_key_and_reports_invalid_records(self):
        redis = FakeRedis({
            b"hok:chat:group:200": [
                json.dumps({"group_id": "999", "message_id": "1", "user_id": "100",
                            "timestamp": 10, "text": "有效"}).encode(),
                b"not-json",
                json.dumps({"message_id": "", "text": "缺少ID"}).encode(),
                json.dumps({"message_id": "3", "timestamp": "not-a-time", "text": "坏时间"}).encode(),
            ],
            b"hok:chat:group:bad": [json.dumps({"message_id": "2", "text": "忽略"}).encode()],
        })
        keys, records, invalid = migration.discover(redis)
        self.assertEqual(keys, ["hok:chat:group:200"])
        self.assertEqual(records[0]["group_id"], "200")
        self.assertEqual(len(invalid), 3)
        self.assertEqual(invalid[-1]["reason"], "invalid_timestamp")

    def test_verification_compares_every_unique_source_message(self):
        source = [
            {"group_id": "200", "message_id": "1", "user_id": "100", "timestamp": 10,
             "text": "一致"},
            {"group_id": "200", "message_id": "2", "user_id": "101", "timestamp": 20,
             "text": "来源"},
        ]
        database = FakeDatabase([
            {"group_id": "200", "message_id": "1", "user_id": "100", "timestamp": 10,
             "reply_to_message_id": None, "text": "一致"},
            {"group_id": "200", "message_id": "2", "user_id": "101", "timestamp": 20,
             "reply_to_message_id": None, "text": "数据库不同"},
        ])
        result = migration.verify(database, source)
        self.assertEqual(result["expected_unique"], 2)
        self.assertEqual(result["verified"], 1)
        self.assertEqual(result["mismatches"], 1)


if __name__ == "__main__":
    unittest.main()
