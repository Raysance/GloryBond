import unittest

from local_debugger import import_hok_module


ZFUNC = import_hok_module("zfunc")


class FakeRedisList:
    def __init__(self):
        self.values = {}
        self.trim_calls = []

    def rpush(self, key, value):
        self.values.setdefault(key, []).append(value)

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

    def tearDown(self):
        ZFUNC.dmc.redis_deamon = self.original_redis
        if self.original_max_messages is None:
            delattr(ZFUNC.dmc, "ChatHistoryMaxMessages")
        else:
            ZFUNC.dmc.ChatHistoryMaxMessages = self.original_max_messages

    def test_record_search_and_reply_expansion(self):
        ZFUNC.record_group_chat_message("200", "100", "老王不适合打野", message_id="1")
        ZFUNC.record_group_chat_message(
            "200",
            "101",
            "我也觉得他野区节奏不好",
            message_id="2",
            reply_to_message_id="1",
        )

        results = ZFUNC.search_group_chat_history("200", ["老王 打野 野区"], limit=2)
        thread = ZFUNC.fetch_group_chat_reply_thread("200", "1")

        self.assertEqual(results[0]["message_id"], "1")
        self.assertEqual([item["message_id"] for item in thread], ["1", "2"])

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


if __name__ == "__main__":
    unittest.main()
