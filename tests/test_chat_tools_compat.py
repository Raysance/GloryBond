import unittest
import json
from unittest.mock import patch

from local_debugger import import_hok_module


LEGACY = import_hok_module("chat_tools")
ZMEMORY = import_hok_module("zmemory")
ZFUNC = import_hok_module("zfunc")


class HOKChatToolsTests(unittest.TestCase):
    def test_model_argument_normalization_preserves_trusted_history_scope(self):
        tools = LEGACY.HOKChatTools(group_id="200", original_query="谁发言最多")
        tools.require_automatic_history_search()
        result = tools.normalize_model_arguments("search_chat_history", {
            "queries": ["发言 排行", "消息 次数"], "players": ["A"],
            "time_start": "2026-09-01", "group_id": "other", "limit": 10,
        })
        self.assertEqual(result, {"queries": ["发言 排行", "消息 次数"], "limit": 10})
        with patch.object(ZFUNC, "search_group_chat_history", return_value=[]) as search:
            tools.execute("search_chat_history", result)
        self.assertEqual(search.call_args.args[0], "200")
        self.assertEqual(search.call_args.kwargs["user_ids"], [])

    def test_analysis_argument_normalization_only_fills_descriptive_intent(self):
        tools = LEGACY.HOKChatTools(original_query="谁的对局最多")
        result = tools.normalize_model_arguments("analyze_game_database", {
            "queries": ["SELECT 1 AS games", {"sql": "SELECT 2 AS games", "intent": "另一组"}],
        })
        self.assertEqual(result["queries"], [
            {"sql": "SELECT 1 AS games", "intent": "谁的对局最多"},
            {"sql": "SELECT 2 AS games", "intent": "另一组"},
        ])


    def test_group_scope_cannot_be_set_by_model_arguments(self):
        for group_id in (None, "200"):
            with self.subTest(group_id=group_id), patch.object(ZFUNC, "search_group_chat_history") as search:
                with self.assertRaises(ValueError):
                    LEGACY.HOKChatTools(group_id=group_id).execute(
                        "search_chat_history", {"queries": ["内卷 竞争", "压力 讨论"], "group_id": "other-group"})
                search.assert_not_called()


    def test_database_and_live_power_are_separate_tools(self):
        registry = LEGACY.HOKChatTools()
        self.assertEqual({item["name"] for item in registry.initial_schemas()}, {"discover_tools"})
        names = {item["name"] for item in registry.schemas()}
        self.assertTrue({"analyze_game_database", "check_game_database_query", "query_game_database",
                         "query_player_hero_power", "query_honor_power",
                         "render_python_plot", "web_search"}.issubset(names))
        self.assertNotIn("query_player_today_report", names)
        self.assertNotIn("remember_memory", names)

    def test_pre_disclosed_history_does_not_force_redundant_discovery(self):
        registry = LEGACY.HOKChatTools(group_id="200", original_query="查看群聊历史")
        self.assertTrue(registry.require_automatic_history_search())
        self.assertEqual(registry.required_discovery_categories(), [])
        self.assertNotIn("get_chat_history_database_schema",
                         {item["name"] for item in registry.model_schemas()})

    def test_group_message_ranking_requires_scoped_chat_sql_workflow(self):
        registry = LEGACY.HOKChatTools(group_id="200", original_query="谁发消息最多")
        self.assertTrue(registry.require_automatic_history_search())
        self.assertEqual(registry.required_discovery_categories(), ["chat_data"])
        disclosed = registry.execute("discover_tools", {"categories": ["chat_data"]})
        self.assertFalse(disclosed["unavailable_categories"])
        self.assertIn("chat_data", disclosed["authoritative_context"])
        self.assertEqual(registry.required_workflow_tool(["chat_data"]),
                         "analyze_chat_history_database")
        registry.record_tool_result("analyze_chat_history_database", {"completed": True})
        self.assertIsNone(registry.required_workflow_tool(["chat_data"]))

    def test_game_aggregations_without_sql_words_disclose_game_data(self):
        for question in (
            "统计最近半年所有玩家每个自然周的正式对局总场次趋势",
            "分析游走位出辅助装和不出辅助装时的平均评分差异",
            "谁和示例玩家41同队次数最多，列共同场次与胜率",
        ):
            with self.subTest(question=question):
                registry = LEGACY.HOKChatTools(user_id="100", original_query=question)
                self.assertIn("game_data", registry.required_discovery_categories())

    def test_group_chat_sql_ticket_executes_with_request_bound_scope(self):
        tools = LEGACY.HOKChatTools(group_id="200", original_query="发言统计")
        query = ("SELECT user_id, COUNT(*) AS message_count "
                 "FROM hok.chat_history_messages GROUP BY user_id")
        with patch.object(ZFUNC, "chat_check_history_database_query",
                          return_value={"ok": True, "normalized_sql": query}) as check, \
                patch.object(ZFUNC, "chat_query_history_database",
                             return_value={"ok": True, "rows": [{"user_id": "100", "message_count": 9}],
                                           "columns": ["user_id", "message_count"]}) as execute:
            checked = tools.execute("check_chat_history_database_query", {"queries": [
                {"sql": query, "intent": "统计当前群发言量"},
            ]})
            self.assertEqual(checked["check_id"], "chat_sql_check_1")
            result = tools.execute("query_chat_history_database", {"check_id": checked["check_id"]})
        check.assert_called_once_with(query, params=None)
        execute.assert_called_once_with(query, limit=None, group_id="200", all_groups=False)
        self.assertEqual(result["observations"][0]["dataset_id"], "dataset_1")
        self.assertEqual(tools.datasets["dataset_1"][0]["message_count"], 9)
        with self.assertRaisesRegex(ValueError, "unknown_or_consumed_check_id"):
            tools.execute("query_chat_history_database", {"check_id": checked["check_id"]})

    def test_group_chat_sql_is_unavailable_in_ordinary_private_chat(self):
        private = LEGACY.HOKChatTools(user_id="100", original_query="群聊发言统计")
        names = {item["name"] for item in private.schemas()}
        self.assertNotIn("get_chat_history_database_schema", names)
        self.assertNotIn("analyze_chat_history_database", names)
        with self.assertRaises(LEGACY.ChatToolUnavailableError):
            private.execute("analyze_chat_history_database", {"queries": [{
                "sql": "SELECT COUNT(*) FROM hok.chat_history_messages",
                "intent": "统计群聊消息",
            }]})

    def test_disabled_explicit_category_does_not_force_unknown_tool(self):
        registry = LEGACY.HOKChatTools(user_id="100", use_memory=False,
                                      original_query="调用memory记忆工具")
        categories = registry.required_discovery_categories()
        self.assertEqual(categories, ["memory"])
        result = registry.execute("discover_tools", {"categories": categories})
        self.assertEqual(result["unavailable_categories"], ["memory"])
        self.assertIsNone(registry.required_workflow_tool(categories))


    def test_batch_queries_keep_partial_errors_and_datasets_private_to_request(self):
        tools = LEGACY.HOKChatTools()
        with patch.object(ZFUNC, "chat_check_database_query", side_effect=[
            {"ok": True, "normalized_sql": "SELECT 1 AS score"},
            {"ok": True, "normalized_sql": "SELECT 2 AS score"},
        ]), patch.object(ZFUNC, "chat_query_database", side_effect=[
            {"ok": True, "rows": [{"player": "A", "score": 9}], "columns": ["player", "score"]},
            {"ok": False, "error": "forbidden_sql"},
        ]):
            checked = tools.execute("check_game_database_query", {"queries": [
                {"sql": "SELECT 1 AS score", "intent": "first metric"},
                {"sql": "SELECT 2 AS score", "intent": "second metric"},
            ]})
            self.assertTrue(checked["approved"])
            result = tools.execute("query_game_database", {"check_id": checked["check_id"]})
        self.assertEqual(len(result["observations"]), 2)
        self.assertEqual(result["observations"][0]["dataset_id"], "dataset_1")
        self.assertFalse(result["observations"][1]["ok"])
        self.assertEqual(list(tools.datasets), ["dataset_1"])
        self.assertEqual(LEGACY.HOKChatTools().datasets, {})
        with patch.object(ZFUNC, "chat_render_plot", return_value={"path": "/tmp/trusted.png", "width": 1456}) as plot:
            result = tools.execute("render_python_plot", {"dataset_id": "dataset_1", "options": {"columns": {"value": "score"}}})
        self.assertNotIn("path", result)
        self.assertEqual(tools.artifacts[0]["path"], "/tmp/trusted.png")
        self.assertEqual(plot.call_args.args[0], [{"player": "A", "score": 9}])
        with self.assertRaises(ValueError):
            LEGACY.HOKChatTools().execute("render_python_plot", {"dataset_id": "dataset_1"})
        with self.assertRaisesRegex(ValueError, "unknown_or_consumed_check_id"):
            tools.execute("query_game_database", {"check_id": checked["check_id"]})
        with patch.object(ZFUNC, "chat_check_database_query",
                          return_value={"ok": True, "normalized_sql": "SELECT 3 AS score"}):
            next_checked = tools.execute("check_game_database_query", {"queries": [
                {"sql": "SELECT 3 AS score", "intent": "third metric"},
            ]})
        self.assertEqual(next_checked["check_id"], "sql_check_2")

    def test_database_batch_cannot_execute_until_every_query_passes_checker(self):
        tools = LEGACY.HOKChatTools()
        with patch.object(ZFUNC, "chat_check_database_query", side_effect=[
            {"ok": True, "normalized_sql": "SELECT 1 AS value"},
            {"ok": False, "error": "unknown column"},
        ]), patch.object(ZFUNC, "chat_query_database") as execute:
            checked = tools.execute("analyze_game_database", {"queries": [
                {"sql": "SELECT 1 AS value", "intent": "valid part"},
                {"sql": "SELECT missing", "intent": "invalid part", "assumptions": ["schema checked"]},
            ]})
        self.assertFalse(checked["approved"])
        self.assertFalse(checked["completed"])
        self.assertEqual(checked["stage"], "validation")
        execute.assert_not_called()
        self.assertEqual(tools.sql_checks, {})

    def test_single_analysis_call_validates_executes_and_creates_dataset(self):
        tools = LEGACY.HOKChatTools()
        query = "SELECT 1 AS value"
        with patch.object(ZFUNC, "chat_check_database_query",
                          return_value={"ok": True, "normalized_sql": query}) as check, \
                patch.object(ZFUNC, "chat_query_database",
                             return_value={"ok": True, "rows": [{"value": 1}],
                                           "columns": ["value"]}) as execute:
            result = tools.execute("analyze_game_database", {"queries": [
                {"sql": query, "intent": "读取一个值", "assumptions": ["无业务时间范围"]},
            ]})
        check.assert_called_once_with(query, params=None)
        execute.assert_called_once_with(query, limit=None)
        self.assertTrue(result["approved"])
        self.assertTrue(result["completed"])
        self.assertEqual(result["observations"][0]["dataset_id"], "dataset_1")
        self.assertEqual(tools.datasets["dataset_1"], [{"value": 1}])

    def test_truncated_sql_result_requires_database_side_refinement(self):
        tools = LEGACY.HOKChatTools(original_query="统计每周总场次")
        tools.execute("discover_tools", {"categories": ["game_data"]})
        query = "SELECT 1 AS value"
        with patch.object(ZFUNC, "chat_check_database_query",
                          return_value={"ok": True, "normalized_sql": query}), \
                patch.object(ZFUNC, "chat_query_database", side_effect=[
                    {"ok": True, "rows": [{"value": 1}], "row_count": 1, "truncated": True},
                    {"ok": True, "rows": [{"value": 1}], "row_count": 1, "truncated": False},
                ]):
            first = tools.execute("analyze_game_database", {"queries": [
                {"sql": query, "intent": "统计每周总场次"},
            ]})
            self.assertEqual(first["stage"], "truncated")
            self.assertFalse(first["completed"])
            tools.record_tool_result("analyze_game_database", first)
            self.assertEqual(tools.required_workflow_tool(["game_data"]), "analyze_game_database")
            second = tools.execute("analyze_game_database", {"queries": [
                {"sql": query, "intent": "按要求聚合"},
            ]})
        self.assertTrue(second["completed"])

    def test_first_empty_sql_result_requires_one_identity_or_scope_check(self):
        tools = LEGACY.HOKChatTools(original_query="比较两人的英雄评分")
        tools.execute("discover_tools", {"categories": ["game_data"]})
        query = "SELECT 1 AS value"
        with patch.object(ZFUNC, "chat_check_database_query",
                          return_value={"ok": True, "normalized_sql": query}), \
                patch.object(ZFUNC, "chat_query_database",
                             return_value={"ok": True, "rows": [], "row_count": 0}):
            first = tools.execute("analyze_game_database", {"queries": [
                {"sql": query, "intent": "比较两人的英雄评分"},
            ]})
            second = tools.execute("analyze_game_database", {"queries": [
                {"sql": query, "intent": "核对身份和时间后复查"},
            ]})
        self.assertEqual(first["stage"], "empty_result")
        self.assertFalse(first["completed"])
        self.assertTrue(second["completed"])

    def test_memory_is_bound_to_user_and_nomem_disables_it(self):
        tools = LEGACY.HOKChatTools(user_id="100")
        with patch.object(ZFUNC, "chat_memory_save", return_value={"saved": True}) as save:
            tools.execute("remember_memory", {"content": "喜欢辅助"})
            save.assert_called_once_with("100", "喜欢辅助", memory_id="")
            with self.assertRaises(ValueError):
                tools.execute("remember_memory", {"content": "喜欢辅助", "user_id": "200"})
        with self.assertRaises(ValueError):
            LEGACY.HOKChatTools(user_id="100", use_memory=False).execute("remember_memory", {"content": "喜欢辅助"})

    def test_live_player_power_resolves_player_and_optional_hero(self):
        payload = {"heroList": [
            {"basicInfo": {"title": "赵云", "heroFightPower": 5000}, "honorTitle": {"rank": 8, "desc": {"full": "某地区第8"}}},
            {"basicInfo": {"title": "大乔", "heroFightPower": 4200}},
        ]}
        with patch.object(ZFUNC, "extract_name", return_value="alice"), \
                patch.object(ZFUNC, "extract_heroname", return_value=(123, "赵云")), \
                patch.dict(ZFUNC.userlist, {"alice": "game-user"}), \
                patch.dict(ZFUNC.roleidlist, {"alice": "game-role"}), \
                patch.object(ZFUNC, "wzry_get_official", return_value=payload) as official:
            result = LEGACY.HOKChatTools().execute("query_player_hero_power", {"player": "Alice", "hero": "云"})
        official.assert_called_once_with(reqtype="heropower", userid="game-user", roleid="game-role")
        self.assertEqual(result["heroes"][0]["power"], 5000)
        self.assertEqual(len(result["heroes"]), 1)

    def test_honor_power_keeps_region_specific_business_flow(self):
        with patch.object(ZFUNC, "extract_name", return_value="alice"), \
                patch.object(ZFUNC, "honor_power_query_process", return_value="地区榜单") as honor:
            result = LEGACY.HOKChatTools().execute("query_honor_power", {"player": "Alice", "hero": "大乔", "region": "上海市闵行区"})
        self.assertEqual(result, "地区榜单")
        honor.assert_called_once_with("alice", "大乔 上海市闵行区 战力查询")


if __name__ == "__main__":
    unittest.main()
