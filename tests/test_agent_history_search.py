import unittest


from agent_console.tools import memory as MEMORY


class ChatHistoryRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"message_id": "1", "user_id": "100", "text": "鸡处这个赛季不适合打野", "time": "2026-09-18 10:00:00", "reply_to_message_id": None},
            {"message_id": "2", "user_id": "200", "text": "今晚五排缺一个辅助", "time": "2026-09-18 10:01:00", "reply_to_message_id": None},
            {"message_id": "3", "user_id": "100", "text": "基础走野区总是掉节奏", "time": "2026-09-18 10:02:00", "reply_to_message_id": "1"},
            {"message_id": "4", "user_id": "300", "text": "新皮肤挺好看", "time": "2026-09-18 10:03:00", "reply_to_message_id": "3"},
        ]

    def test_multi_query_aliases_fuse_relevant_results(self):
        results = MEMORY.search_history_records(
            self.records,
            ["鸡处不适合打野", "基础野区节奏"],
            limit=3,
        )

        self.assertEqual({item["message_id"] for item in results[:2]}, {"1", "3"})
        self.assertTrue(all(item["matches"] for item in results))

    def test_user_filter_and_current_message_exclusion(self):
        results = MEMORY.search_history_records(
            self.records,
            ["打野 野区"],
            user_ids=["100"],
            exclude_message_id="1",
        )

        self.assertEqual([item["message_id"] for item in results], ["3"])


if __name__ == "__main__":
    unittest.main()
