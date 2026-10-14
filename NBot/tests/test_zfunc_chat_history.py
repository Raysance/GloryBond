import fnmatch
import json
import unittest
from unittest.mock import patch

from local_debugger import import_hok_module


ZFUNC = import_hok_module("zfunc")
ZDB = import_hok_module("zdb")
IDENTITY = import_hok_module("business.user_helpers")


class FakeRedisList:
    def __init__(self):
        self.values = {}
        self.trim_calls = []

    def rpush(self, key, value):
        self.values.setdefault(key, []).append(value)

    def scan_iter(self, match):
        return (key.encode() for key in self.values if fnmatch.fnmatchcase(key, match))

    def llen(self, key):
        return len(self.values.get(key, []))

    def ltrim(self, key, start, end):
        self.trim_calls.append((key, start, end))
        values = self.values.get(key, [])
        if start < 0:
            start = max(0, len(values) + start)
        self.values[key] = values[start:] if end == -1 else values[start:end + 1]

    def lrange(self, key, start, end):
        values = self.values.get(key, [])
        if start < 0:
            start = max(0, len(values) + start)
        return values[start:] if end == -1 else values[start:end + 1]


class GroupChatHistoryBusinessTests(unittest.TestCase):
    def setUp(self):
        self.original_redis = ZFUNC.dmc.redis_deamon
        self.original_max_messages = getattr(ZFUNC.dmc, "ChatHistoryMaxMessages", None)
        ZFUNC.dmc.redis_deamon = FakeRedisList()
        ZFUNC.dmc.ChatHistoryMaxMessages = 0
        self.postgres_patches = [
            patch.object(ZDB, "upsert_group_chat_message", side_effect=RuntimeError("database unavailable")),
            patch.object(ZDB, "load_group_chat_messages", side_effect=RuntimeError("database unavailable")),
            patch.object(ZDB, "list_group_chat_history_groups", side_effect=RuntimeError("database unavailable")),
            patch.object(ZFUNC, "log_message"),
        ]
        for item in self.postgres_patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.postgres_patches):
            item.stop()
        ZFUNC.dmc.redis_deamon = self.original_redis
        if self.original_max_messages is None:
            delattr(ZFUNC.dmc, "ChatHistoryMaxMessages")
        else:
            ZFUNC.dmc.ChatHistoryMaxMessages = self.original_max_messages

    def test_record_and_load_reply_metadata(self):
        ZFUNC.record_group_chat_message("200", "100", "老王不适合打野", message_id="1")
        ZFUNC.record_group_chat_message(
            "200",
            "101",
            "我也觉得他野区节奏不好",
            message_id="2",
            reply_to_message_id="1",
        )

        records = ZFUNC.load_group_chat_history("200")

        self.assertEqual([item["message_id"] for item in records], ["1", "2"])

    def test_postgres_is_primary_and_success_does_not_duplicate_to_redis(self):
        with patch.object(ZDB, "upsert_group_chat_message", return_value={"group_id": "200", "message_id": "1"}) as save:
            record = ZFUNC.record_group_chat_message("200", "100", "数据库消息", message_id="1")
        save.assert_called_once_with(record, trusted_group_id="200")
        self.assertEqual(ZFUNC.dmc.redis_deamon.values, {})

    def test_sql_and_legacy_redis_are_merged_with_sql_authoritative(self):
        key = ZFUNC._group_chat_history_key("200")
        ZFUNC.dmc.redis_deamon.values[key] = [
            json.dumps({"group_id": "999", "user_id": "100", "message_id": "1",
                        "timestamp": 10, "time": "1970-01-01 08:00:10", "text": "旧文本"}),
            json.dumps({"user_id": "101", "message_id": "2", "timestamp": 20,
                        "time": "1970-01-01 08:00:20", "text": "仅Redis"}),
        ]
        sql_records = [
            {"group_id": "200", "user_id": "100", "message_id": "1", "timestamp": 10,
             "time": "1970-01-01 08:00:10", "text": "SQL文本"},
            {"group_id": "200", "user_id": "102", "message_id": "3", "timestamp": 30,
             "time": "1970-01-01 08:00:30", "text": "仅SQL"},
        ]
        with patch.object(ZDB, "load_group_chat_messages", return_value=sql_records):
            records = ZFUNC.load_group_chat_history("200")
        self.assertEqual([item["message_id"] for item in records], ["1", "2", "3"])
        self.assertEqual(records[0]["text"], "SQL文本")
        self.assertTrue(all(item["group_id"] == "200" for item in records))

    def test_sql_read_remains_available_when_legacy_redis_is_down(self):
        sql_records = [{"group_id": "200", "user_id": "100", "message_id": "1",
                        "timestamp": 10, "time": "1970-01-01 08:00:10", "text": "SQL可用"}]
        with patch.object(ZFUNC.dmc.redis_deamon, "lrange", side_effect=RuntimeError("redis down")), \
                patch.object(ZDB, "load_group_chat_messages", return_value=sql_records), \
                patch.object(ZFUNC, "log_message"):
            self.assertEqual(ZFUNC.load_group_chat_history("200"), sql_records)

    def test_unlimited_history_does_not_trim_and_loads_every_record(self):
        for index in range(150):
            ZFUNC.record_group_chat_message("200", "100", f"消息{index}", message_id=str(index))

        records = ZFUNC.load_group_chat_history("200")

        self.assertEqual(len(records), 150)
        self.assertEqual(records[0]["message_id"], "0")
        self.assertEqual(records[-1]["message_id"], "149")
        self.assertEqual(ZFUNC.dmc.redis_deamon.trim_calls, [])

    def test_positive_history_cap_remains_available(self):
        ZFUNC.dmc.ChatHistoryMaxMessages = 2
        for index in range(3):
            ZFUNC.record_group_chat_message("200", "100", f"消息{index}", message_id=str(index))

        records = ZFUNC.load_group_chat_history("200")

        self.assertEqual([item["message_id"] for item in records], ["1", "2"])

    def test_group_discovery_returns_only_archived_group_metadata(self):
        ZFUNC.record_group_chat_message("300", "100", "PRIVATE_HISTORY", message_id="1")
        ZFUNC.record_group_chat_message("200", "100", "PRIVATE_HISTORY", message_id="1")
        redis = ZFUNC.dmc.redis_deamon
        redis.values.update({"hok:memory:facts:100": ["secret"], "hok:chat:group:bad": ["secret"],
                             "hok:chat:group:200:extra": ["secret"], "hok:chat:group:0": ["secret"],
                             "hok:chat:group:400": []})
        with patch.object(ZFUNC, "load_group_chat_history") as load:
            result = ZFUNC.list_chat_history_groups()
        load.assert_not_called()
        self.assertEqual(result, [{"group_id": "200", "message_count": 1},
                                  {"group_id": "300", "message_count": 1}])

    def test_loaded_message_group_is_bound_to_storage_key(self):
        key = ZFUNC._group_chat_history_key("200")
        ZFUNC.dmc.redis_deamon.values[key] = [json.dumps({"message_id": "1", "text": "old record"}),
                                            json.dumps({"group_id": "300", "message_id": "2", "text": "wrong metadata"})]
        records = ZFUNC.load_group_chat_history("200")
        self.assertEqual([record["group_id"] for record in records], ["200", "200"])
