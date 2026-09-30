import fnmatch
import json
import unittest
from unittest.mock import patch

from local_debugger import import_hok_module


ZFUNC = import_hok_module("zfunc")
ZDB = import_hok_module("zdb")
CHAT = import_hok_module("zchat")
TOOLS = import_hok_module("chat_tools")
IDENTITY = import_hok_module("business.user_helpers")
MEMORY = import_hok_module("zmemory")


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

    def test_search_tool_reads_all_users_in_current_group_and_excludes_current_message(self):
        ZFUNC.record_group_chat_message("200", "100", "辅助英雄应该保护射手", message_id="1")
        ZFUNC.record_group_chat_message("200", "101", "辅助游走也很重要", message_id="2")
        ZFUNC.record_group_chat_message("200", "102", "辅助推荐", message_id="3")
        ZFUNC.record_group_chat_message("300", "103", "其他群辅助资料", message_id="4")

        tools = TOOLS.HOKChatTools(group_id="200", current_message_id="3", original_query="辅助推荐")
        result = tools.execute("search_chat_history", {"queries": ["辅助英雄 射手", "辅助 游走"]})

        self.assertEqual({item["user_id"] for item in result}, {"100", "101"})
        self.assertTrue(all(item["group_id"] == "200" for item in result))
        self.assertNotIn("3", {item["message_id"] for item in result})

    def test_admin_search_tool_can_read_all_groups_without_private_message_id_exclusion(self):
        ZFUNC.record_group_chat_message("200", "100", "内卷记录 A", message_id="42")
        ZFUNC.record_group_chat_message("300", "101", "内卷记录 B", message_id="42")

        with patch.dict(ZFUNC.confs["QQBot"], {"super_qid": 999}):
            tools = TOOLS.HOKChatTools(user_id="999", current_message_id="42", original_query="查看内卷记录")
            result = tools.execute("search_chat_history", {
                "all_groups": True,
                "queries": ["内卷 记录", "竞争 压力"],
            })

        self.assertEqual({item["group_id"] for item in result}, {"200", "300"})

    def test_every_group_chat_forces_model_generated_queries_through_search_tool(self):
        ZFUNC.record_group_chat_message("200", "100", "AUTO_HISTORY 辅助英雄保护射手", message_id="1")
        ZFUNC.record_group_chat_message("200", "101", "完全无关的话题", message_id="2")
        ZFUNC.record_group_chat_message("200", "102", "辅助英雄推荐", message_id="3")
        requests = []

        def model(messages, tools=None, **kwargs):
            requests.append({"messages": list(messages), "tools": tools, **kwargs})
            if len(requests) == 1:
                self.assertEqual(kwargs["tool_choice"]["function"]["name"], "search_chat_history")
                self.assertIn("search_chat_history", {schema["name"] for schema in tools})
                return {"tool_calls": [{"call_id": "history", "name": "search_chat_history",
                                        "arguments": '{"queries":["辅助英雄 射手","保护 后排"]}'}]}
            output = json.loads(next(item["output"] for item in reversed(messages)
                                     if item.get("type") == "function_call_output"))
            self.assertIn("AUTO_HISTORY", json.dumps(output, ensure_ascii=False))
            return {"content": "已结合历史回答"}

        with patch.object(MEMORY.instance, "load_active_chat_records", return_value=[]), \
                patch.object(MEMORY.instance, "save_active_chat"), \
                patch.object(ZFUNC, "chat_roleplay_get", return_value=None):
            result = CHAT.chat_process(
                user_text="辅助英雄推荐", user_id="102", nickname="C", group_id="200", message_id="3",
                use_memory=False, model_caller=model, return_artifacts=True)

        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[1]["tool_choice"], "auto")
        self.assertEqual(result["trace"]["context"]["automatic_history_scope"], "current_group_all_users")
        self.assertTrue(result["trace"]["context"]["automatic_history_completed"])
        self.assertEqual(result["trace"]["context"]["automatic_history_queries"], ["辅助英雄 射手", "保护 后排"])
        self.assertEqual(result["trace"]["context"]["automatic_history_matches"], 1)

    def test_mandatory_history_search_cannot_narrow_users_or_saved_time(self):
        ZFUNC.record_group_chat_message("200", "100", "辅助英雄保护射手", message_id="1")
        tools = TOOLS.HOKChatTools(group_id="200", original_query="辅助怎么选")
        self.assertTrue(tools.require_automatic_history_search())

        with self.assertRaisesRegex(ValueError, "all users and all saved times"):
            tools.execute("search_chat_history", {
                "players": ["示例玩家41"],
                "queries": ["辅助英雄", "保护射手"],
            })

        result = tools.execute("search_chat_history", {"queries": ["辅助英雄", "保护射手"]})
        self.assertEqual(result[0]["message_id"], "1")

    def test_cross_group_access_requires_super_id_in_private_event(self):
        history = {"search_chat_history", "fetch_recent_chat_messages", "fetch_chat_context", "fetch_chat_reply_thread"}
        calls = {"list_chat_groups": {}, "search_chat_history": {"queries": ["内卷"]},
                 "fetch_recent_chat_messages": {},
                 "fetch_chat_context": {"message_id": "1"}, "fetch_chat_reply_thread": {"message_id": "1"}}
        with patch.dict(ZFUNC.confs["QQBot"], {"super_qid": 999}):
            for user_id, group_id in [(999, None), ("999", 0), (999, "200"), (100, None), (100, "200"), (None, None)]:
                with self.subTest(user_id=user_id, group_id=group_id):
                    tools = TOOLS.HOKChatTools(user_id=user_id, group_id=group_id, use_memory=False)
                    names = {schema["name"] for schema in tools.schemas()}
                    is_super_private = str(user_id) == "999" and not group_id
                    self.assertEqual("list_chat_groups" in names, is_super_private)
                    self.assertEqual(history.issubset(names), bool(group_id or is_super_private))
                    if not is_super_private:
                        for name, arguments in calls.items():
                            with patch.object(ZFUNC, "load_group_chat_history") as load, \
                                    patch.object(ZFUNC, "list_chat_history_groups") as groups:
                                with self.assertRaises(ValueError):
                                    tools.execute(name, {**arguments, "group_id": "300"})
                                load.assert_not_called()
                                groups.assert_not_called()

    def test_admin_history_tools_keep_overlapping_message_ids_in_correct_group(self):
        ZFUNC.record_group_chat_message("200", "100", "内卷 A", message_id="42")
        ZFUNC.record_group_chat_message("200", "101", "A 回复", message_id="43", reply_to_message_id="42")
        ZFUNC.record_group_chat_message("300", "102", "内卷 B", message_id="42")
        ZFUNC.record_group_chat_message("300", "103", "B 回复", message_id="43", reply_to_message_id="42")
        with patch.dict(ZFUNC.confs["QQBot"], {"super_qid": 999}):
            tools = TOOLS.HOKChatTools(user_id="999", current_message_id="42", original_query="内卷", use_memory=False)
            for group_id, marker in [("200", "A"), ("300", "B")]:
                with self.subTest(group_id=group_id):
                    hits = tools.execute("search_chat_history", {"group_id": group_id,
                                                                 "queries": ["内卷 记录", "竞争 压力"]})
                    self.assertEqual(hits[0]["message_id"], "42")
                    recent = tools.execute("fetch_recent_chat_messages", {"group_id": group_id})
                    self.assertEqual({message["message_id"] for message in recent["messages"]}, {"42", "43"})
                    context = tools.execute("fetch_chat_context", {"group_id": int(group_id), "message_id": "42"})
                    thread = tools.execute("fetch_chat_reply_thread", {"group_id": group_id, "message_id": "43"})
                    for records in (context, thread):
                        self.assertEqual([record["message_id"] for record in records], ["42", "43"])
                        self.assertTrue(all(record["group_id"] == group_id and marker in record["text"] for record in records))

    def test_recent_player_messages_resolve_alias_and_order_without_keywords(self):
        with patch.object(IDENTITY, "qid", {"player": "100"}), \
                patch.object(IDENTITY, "nameref", {"player": ["示例玩家41"]}), \
                patch.object(IDENTITY, "namenick", {"player": "昵称"}):
            ZFUNC.record_group_chat_message("200", "100", "今晚吃面", message_id="1")
            ZFUNC.record_group_chat_message("200", "101", "另一个用户", message_id="2")
            ZFUNC.record_group_chat_message("200", "100", "散步回来了", message_id="3")
            ZFUNC.record_group_chat_message("200", "100", "正在提问", message_id="4")
            tools = TOOLS.HOKChatTools(user_id="100", group_id="200", current_message_id="4")
            result = tools.execute("fetch_recent_chat_messages", {"players": ["示例玩家41"], "limit": 1})
        self.assertEqual(result["qq_ids"], ["100"])
        self.assertEqual(result["messages"][0]["message_id"], "3")
        self.assertEqual(result["total_matches"], 2)
        self.assertTrue(result["truncated"])

    def test_game_id_filter_rejected_with_correct_qq_hint(self):
        with patch.object(IDENTITY, "qid", {"player": "100"}), \
                patch.object(IDENTITY, "userlist", {"player": "900"}), \
                patch.object(IDENTITY, "roleidlist", {"player": "901"}):
            tools = TOOLS.HOKChatTools(group_id="200")
            for name, args in [("fetch_recent_chat_messages", {"qq_ids": ["900"]}),
                               ("search_chat_history", {"user_ids": ["901"],
                                                        "queries": ["表现 好", "发挥 不错"]})]:
                with self.subTest(name=name), patch.object(ZFUNC, "load_group_chat_history") as load:
                    with self.assertRaisesRegex(ValueError, "chat_game_id_not_qq.*100"):
                        tools.execute(name, args)
                    load.assert_not_called()

    def test_recent_time_window_and_exact_alias_validation(self):
        records = [{"user_id": "100", "timestamp": stamp, "text": str(stamp), "message_id": str(stamp)}
                   for stamp in [30, 10, 20]]
        with patch.object(ZFUNC, "load_group_chat_history", return_value=records), \
                patch("hok.ztime.parse_chat_time_bound", side_effect=[15, 25]):
            result = ZFUNC.recent_group_chat_messages("200", time_start="start", time_end="end")
        self.assertEqual([message["timestamp"] for message in result["messages"]], [20])
        with patch.object(IDENTITY, "qid", {"a": "100", "b": "101"}), \
                patch.object(IDENTITY, "nameref", {"a": ["重名"], "b": ["重名"]}), \
                patch.object(IDENTITY, "namenick", {}):
            for label in ["重名", "不存在"]:
                with self.assertRaisesRegex(ValueError, "chat_player_identity"):
                    ZFUNC.resolve_chat_history_users([label])

    def test_admin_must_supply_an_archived_group_and_cannot_override_identity(self):
        with patch.dict(ZFUNC.confs["QQBot"], {"super_qid": 999}):
            tools = TOOLS.HOKChatTools(user_id="999", use_memory=False)
            with patch.object(ZFUNC, "load_group_chat_history") as load:
                with self.assertRaisesRegex(ValueError, "group_id: required"):
                    tools.execute("search_chat_history", {"queries": ["内卷 讨论", "竞争 压力"]})
                with self.assertRaises(TOOLS.ChatToolUnavailableError) as error:
                    tools.execute("fetch_chat_context", {"group_id": "123", "message_id": "42"})
                self.assertEqual(error.exception.code, "chat_group_not_found")
                with self.assertRaisesRegex(ValueError, "unknown parameters"):
                    tools.execute("search_chat_history", {"queries": ["内卷 讨论", "竞争 压力"],
                                                          "group_id": "200", "user_id": "999"})
                load.assert_not_called()

    def test_admin_private_loop_automatically_searches_all_groups_and_shares_results(self):
        ZFUNC.record_group_chat_message("200", "100", "PRIVATE_HISTORY 内卷", message_id="42")
        stages = []

        def model(messages, tools=None, **kwargs):
            stage = len(stages)
            stages.append(stage)
            if stage == 0:
                self.assertIn("search_chat_history", {schema["name"] for schema in tools})
                self.assertEqual(kwargs["tool_choice"]["function"]["name"], "search_chat_history")
                name, arguments = "search_chat_history", {
                    "all_groups": True, "queries": ["内卷 讨论", "竞争 压力"]}
            elif stage == 1:
                hit = json.loads(next(item["output"] for item in reversed(messages)
                                      if item.get("type") == "function_call_output"))["data"][0]
                name, arguments = "fetch_chat_context", {"group_id": hit["group_id"], "message_id": hit["message_id"]}
            else:
                output = next(item["output"] for item in reversed(messages)
                              if item.get("type") == "function_call_output")
                self.assertIn("PRIVATE_HISTORY", output)
                return {"content": "已找到并展开群内对话。"}
            return {"tool_calls": [{"call_id": str(stage), "name": name, "arguments": json.dumps(arguments)}]}

        with patch.dict(ZFUNC.confs["QQBot"], {"super_qid": 999}):
            result = CHAT.chat_process(user_text="查看内卷的对话上下文", user_id="999", nickname="管理员",
                                       use_memory=False, model_caller=model, return_artifacts=True)
        self.assertEqual(result["trace"]["summary"]["tool_errors"], 0)
        self.assertEqual(len(stages), 3)
        self.assertTrue(result["trace"]["context"]["cross_group_history_enabled"])
        self.assertTrue(result["trace"]["context"]["automatic_history_completed"])
        self.assertIn("PRIVATE_HISTORY", json.dumps(result["trace"]))


if __name__ == "__main__":
    unittest.main()
