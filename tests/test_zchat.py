import unittest
import json
from unittest.mock import patch

from local_debugger import import_hok_module


ZCHAT = import_hok_module("zchat")
ZMEMORY = import_hok_module("zmemory")
ZFUNC = import_hok_module("zfunc")


class FakeTools:
    def __init__(self):
        self.calls = []

    def schemas(self):
        return [{"type": "function", "name": "lookup", "parameters": {"type": "object"}}]

    def execute(self, name, arguments):
        self.calls.append((name, arguments))
        return {"value": 42}


class ChatLoopTests(unittest.TestCase):
    def setUp(self):
        self.original_load = ZMEMORY.instance.load_active_chat_records
        self.original_load_forced = ZMEMORY.instance.load_user_forced_memory
        self.original_save = ZMEMORY.instance.save_active_chat
        ZMEMORY.instance.load_active_chat_records = lambda qid, num=5: []
        ZMEMORY.instance.load_user_forced_memory = lambda qid, num=5: ""
        self.saved = []
        ZMEMORY.instance.save_active_chat = lambda qid, question, answer: self.saved.append((qid, question, answer))

    def tearDown(self):
        ZMEMORY.instance.load_active_chat_records = self.original_load
        ZMEMORY.instance.load_user_forced_memory = self.original_load_forced
        ZMEMORY.instance.save_active_chat = self.original_save

    def test_private_chat_explains_scope_and_rejects_invented_history_tool(self):
        requests = []

        def model(messages, tools=None, **kwargs):
            requests.append(list(messages))
            self.assertEqual({tool["name"] for tool in tools}, {"discover_tools"})
            if len(requests) == 1:
                system_text = "\n".join(item["content"] for item in messages if item.get("role") == "system")
                self.assertIn("选择chat_history", system_text)
                return {"tool_calls": [{"call_id": "discover", "name": "discover_tools",
                                        "arguments": '{"categories":["chat_history"]}'}]}
            output = json.loads(next(item["output"] for item in reversed(messages)
                                     if item.get("type") == "function_call_output"))
            self.assertTrue(output["ok"])
            self.assertEqual(output["data"]["unavailable_categories"], ["chat_history"])
            return {"content": "请在目标群内发送同一查询。"}

        with patch.object(ZFUNC, "search_group_chat_history") as search:
            result = ZCHAT.chat_process(user_text="查最近的对话", user_id="100", nickname="A",
                                        use_memory=False, model_caller=model, return_artifacts=True)
        search.assert_not_called()
        self.assertFalse(result["trace"]["context"]["group_history_enabled"])
        observation = result["trace"]["rounds"][0]["tools"][0]["observation"]
        self.assertEqual(observation["data"]["unavailable_categories"], ["chat_history"])
        self.assertEqual(result["trace"]["rounds"][0]["tools"][0]["arguments"],
                         {"categories": ["chat_history"]})

    def test_group_request_keeps_history_search_bound_to_event_group(self):
        handler = import_hok_module("event_handlers.chat")
        from types import SimpleNamespace
        event = SimpleNamespace(group_id=200, message_id=300, get_user_id=lambda: "100",
                                get_plaintext=lambda: "#查看最近含有内卷的对话")
        request = handler.prepare_chat_request(event, {}, default_use_memory=False)
        calls = []

        def model(messages, tools=None, **kwargs):
            calls.append(messages)
            if len(calls) == 1:
                self.assertIn("search_chat_history", {tool["name"] for tool in tools})
                self.assertEqual(kwargs["tool_choice"]["function"]["name"], "search_chat_history")
                return {"tool_calls": [{"call_id": "search", "name": "search_chat_history",
                                        "arguments": '{"queries":["内卷","竞争 压力"],"limit":5}'}]}
            output = next(item for item in reversed(messages) if item.get("type") == "function_call_output")
            self.assertEqual(json.loads(output["output"])["data"][0]["message_id"], "42")
            return {"content": "已找到相关对话。"}

        with patch.object(ZFUNC, "search_group_chat_history", return_value=[{"message_id": "42", "text": "PRIVATE_HISTORY"}]) as search:
            result = ZCHAT.chat_process(**request, model_caller=model, return_artifacts=True)
        search.assert_called_once_with("200", [request["user_text"], "内卷", "竞争 压力"],
                                       user_ids=[], time_start=None, time_end=None, limit=5,
                                       exclude_message_id=300)
        self.assertTrue(result["trace"]["context"]["group_history_enabled"])
        self.assertEqual(result["trace"]["summary"]["tool_errors"], 0)
        self.assertIn("PRIVATE_HISTORY", json.dumps(result["trace"]))

    def test_explicit_database_request_forces_discovery_after_history(self):
        calls = []
        registry = ZCHAT.HOKChatTools(group_id="200", current_message_id="300",
                                      original_query="调用game_data工具并画可视化图",
                                      user_id="100", use_memory=False)

        def model(messages, tools=None, tool_choice="auto", **kwargs):
            names = {tool["name"] for tool in tools or []}
            calls.append({"names": names, "tool_choice": tool_choice,
                          "messages": [dict(item) for item in messages]})
            if len(calls) == 1:
                self.assertEqual(tool_choice["function"]["name"], "search_chat_history")
                call = {"call_id": "history", "name": "search_chat_history",
                        "arguments": '{"queries":["赛季 战局","组排 数据"]}'}
            elif len(calls) == 2:
                self.assertEqual(tool_choice["function"]["name"], "discover_tools")
                call = {"call_id": "discover", "name": "discover_tools",
                        "arguments": '{"categories":["game_data"]}'}
            elif len(calls) == 3:
                self.assertEqual(tool_choice["function"]["name"], "analyze_game_database")
                self.assertEqual(names, {"analyze_game_database"})
                call = {"call_id": "analysis", "name": "analyze_game_database",
                        "arguments": json.dumps({"queries": [{"sql": "SELECT 1 AS value",
                                                                 "intent": "读取战局统计"}]})}
            elif len(calls) == 4:
                self.assertEqual(tool_choice["function"]["name"], "list_plot_templates")
                call = {"call_id": "templates", "name": "list_plot_templates", "arguments": "{}"}
            elif len(calls) == 5:
                self.assertEqual(tool_choice["function"]["name"], "render_python_plot")
                call = {"call_id": "plot", "name": "render_python_plot",
                        "arguments": '{"dataset_id":"dataset_1"}'}
            else:
                return {"content": "已按数据库结构继续查询。", "tool_calls": [], "output_items": []}
            return {"tool_calls": [call], "output_items": [{"type": "function_call", **call}]}

        with patch.object(ZFUNC, "search_group_chat_history", return_value=[]), \
                patch.object(ZFUNC, "chat_database_schema", return_value={"ok": True, "tables": {}}), \
                patch.object(ZFUNC, "chat_check_database_query",
                             return_value={"ok": True, "normalized_sql": "SELECT 1 AS value"}), \
                patch.object(ZFUNC, "chat_query_database",
                             return_value={"ok": True, "rows": [{"value": 1}], "columns": ["value"]}), \
                patch.object(ZFUNC, "chat_plot_templates", return_value={"templates": ["bar"]}), \
                patch.object(ZFUNC, "chat_render_plot", return_value={"path": "/tmp/forced.png", "width": 800}):
            result = ZCHAT.chat_process(user_text=registry.original_query, user_id="100", nickname="A",
                                        group_id="200", message_id="300", use_memory=False,
                                        model_caller=model, tool_registry=registry, return_artifacts=True)
        self.assertEqual(result["text"], "已按数据库结构继续查询。")
        self.assertEqual(result["trace"]["context"]["explicit_discovery_categories"],
                         ["game_data", "plots"])
        self.assertTrue(result["trace"]["context"]["forced_discovery_completed"])
        self.assertTrue(result["trace"]["context"]["forced_tool_workflow_completed"])
        discover = result["trace"]["rounds"][1]["tools"][0]
        self.assertEqual(discover["arguments"]["categories"], ["game_data", "plots"])
        self.assertIn("game_data", discover["observation"]["data"]["authoritative_context"])
        self.assertEqual(len(calls), 6)

    def test_message_count_request_forces_scoped_chat_sql_after_history_search(self):
        calls = []
        registry = ZCHAT.HOKChatTools(group_id="200", current_message_id="300",
                                      original_query="谁发消息最多", user_id="100", use_memory=False)
        query = ("SELECT user_id, COUNT(*) AS message_count "
                 "FROM hok.chat_history_messages GROUP BY user_id ORDER BY message_count DESC")

        def model(messages, tools=None, tool_choice="auto", **kwargs):
            calls.append(tool_choice)
            stage = len(calls)
            if stage == 1:
                self.assertEqual(tool_choice["function"]["name"], "search_chat_history")
                call = {"call_id": "history", "name": "search_chat_history",
                        "arguments": '{"queries":["群成员 发言","聊天 活跃"]}'}
            elif stage == 2:
                self.assertEqual(tool_choice["function"]["name"], "discover_tools")
                call = {"call_id": "discover", "name": "discover_tools",
                        "arguments": '{"categories":["chat_data"]}'}
            elif stage == 3:
                self.assertEqual(tool_choice["function"]["name"], "analyze_chat_history_database")
                call = {"call_id": "analysis", "name": "analyze_chat_history_database",
                        "arguments": json.dumps({"queries": [{"sql": query, "intent": "统计发言排行"}]})}
            else:
                return {"content": "昵称A发言最多，共9条。", "tool_calls": [], "output_items": []}
            return {"tool_calls": [call], "output_items": [{"type": "function_call", **call}]}

        with patch.object(ZFUNC, "search_group_chat_history", return_value=[]), \
                patch.object(ZFUNC, "chat_history_database_schema",
                             return_value={"ok": True, "tables": {"chat_history_messages": {}}}), \
                patch.object(ZFUNC, "chat_check_history_database_query",
                             return_value={"ok": True, "normalized_sql": query}), \
                patch.object(ZFUNC, "chat_query_history_database",
                             return_value={"ok": True, "rows": [{"user_id": "100", "message_count": 9}],
                                           "columns": ["user_id", "message_count"]}):
            result = ZCHAT.chat_process(user_text=registry.original_query, user_id="100", nickname="A",
                                        group_id="200", message_id="300", use_memory=False,
                                        model_caller=model, tool_registry=registry, return_artifacts=True)
        self.assertEqual(result["text"], "昵称A发言最多，共9条。")
        self.assertEqual(result["trace"]["context"]["explicit_discovery_categories"], ["chat_data"])
        self.assertTrue(result["trace"]["context"]["forced_tool_workflow_completed"])
        self.assertEqual(len(calls), 4)

    def test_implicit_analysis_and_data_followup_discover_then_query(self):
        query = "SELECT 7 AS games"
        for question, history in (
            ("群里谁玩猪八戒最多", []),
            ("查下具体数据呢", [{"time": "2026-09-30 22:11:54",
                             "Q": "群里谁玩猪八戒最多", "A": "只看聊天记录查不了。"}]),
        ):
            with self.subTest(question=question):
                choices = []
                registry = ZCHAT.HOKChatTools(group_id="200", original_query=question,
                                               user_id="100", use_memory=False)

                def model(messages, tools=None, tool_choice="auto", **kwargs):
                    choices.append(tool_choice)
                    if len(choices) == 1:
                        call = {"call_id": "history", "name": "search_chat_history",
                                "arguments": '{"queries":["英雄场次","游戏玩家"]}'}
                    elif len(choices) == 2:
                        self.assertEqual(tool_choice["function"]["name"], "discover_tools")
                        call = {"call_id": "discovery", "name": "discover_tools",
                                "arguments": '{"categories":["game_data"]}'}
                    elif len(choices) == 3:
                        self.assertEqual(tool_choice["function"]["name"], "analyze_game_database")
                        call = {"call_id": "analysis", "name": "analyze_game_database",
                                "arguments": json.dumps({"queries": [{"sql": query,
                                                                     "intent": "统计英雄使用场次"}]})}
                    else:
                        return {"content": "查到 7 场。", "tool_calls": [], "output_items": []}
                    return {"tool_calls": [call],
                            "output_items": [{"type": "function_call", **call}]}

                with patch.object(ZMEMORY.instance, "load_active_chat_records", return_value=history), \
                        patch.object(ZFUNC, "search_group_chat_history", return_value=[]), \
                        patch.object(ZFUNC, "chat_database_schema", return_value={"ok": True, "tables": {}}), \
                        patch.object(ZFUNC, "chat_check_database_query",
                                     return_value={"ok": True, "normalized_sql": query}), \
                        patch.object(ZFUNC, "chat_query_database",
                                     return_value={"ok": True, "rows": [{"games": 7}],
                                                   "columns": ["games"]}):
                    result = ZCHAT.chat_process(user_text=question, user_id="100", nickname="A",
                                                group_id="200", use_memory=False, model_caller=model,
                                                tool_registry=registry, return_artifacts=True)
                self.assertEqual(result["text"], "查到 7 场。")
                self.assertEqual(len(choices), 4)
                self.assertEqual(result["trace"]["context"]["explicit_discovery_categories"], [])
                self.assertEqual(result["trace"]["context"]["forced_discovery_categories"], ["game_data"])
                self.assertTrue(result["trace"]["context"]["forced_tool_workflow_completed"])

    def test_generic_smalltalk_does_not_force_analytical_discovery(self):
        self.assertFalse(ZCHAT.needs_analysis_discovery("你是谁"))
        self.assertFalse(ZCHAT.needs_analysis_discovery("谢谢，先不用了", previous_query="谁玩英雄最多"))
        self.assertFalse(ZCHAT.needs_analysis_discovery("查下具体数据呢"))
        self.assertTrue(ZCHAT.needs_analysis_discovery("查下具体数据呢", previous_query="谁玩英雄最多"))

    def test_model_identity_context_uses_player_key_not_copied_game_ids(self):
        context = ZCHAT._known_users_context_message()["content"]
        self.assertIn('"player":', context)
        self.assertIn('"namenick":', context)
        self.assertNotIn('"game_user_id":', context)
        self.assertNotIn('"game_role_id":', context)

    def test_capability_denial_gets_one_forced_discovery_retry(self):
        calls = []
        registry = ZCHAT.HOKChatTools(group_id="200", original_query="群友哪一对组排最多",
                                      user_id="100", use_memory=False)

        def model(messages, tools=None, tool_choice="auto", **kwargs):
            calls.append(tool_choice)
            if len(calls) == 1:
                call = {"call_id": "history", "name": "search_chat_history",
                        "arguments": '{"queries":["组排 搭档","双排 次数"]}'}
                return {"tool_calls": [call], "output_items": [{"type": "function_call", **call}]}
            if len(calls) == 2:
                return {"content": "这个不属于群聊工具，需要你提供查询入口。", "tool_calls": [],
                        "output_items": [{"role": "assistant", "content": "这个不属于群聊工具，需要你提供查询入口。"}]}
            if len(calls) == 3:
                self.assertEqual(tool_choice["function"]["name"], "discover_tools")
                call = {"call_id": "discover", "name": "discover_tools",
                        "arguments": '{"categories":["game_data"]}'}
                return {"tool_calls": [call], "output_items": [{"type": "function_call", **call}]}
            if len(calls) == 4:
                self.assertEqual(tool_choice["function"]["name"], "analyze_game_database")
                call = {"call_id": "analysis", "name": "analyze_game_database",
                        "arguments": json.dumps({"queries": [{"sql": "SELECT 1 AS value",
                                                               "intent": "统计组排次数"}]})}
                return {"tool_calls": [call], "output_items": [{"type": "function_call", **call}]}
            return {"content": "已改用游戏数据库查询。", "tool_calls": [], "output_items": []}

        with patch.object(ZFUNC, "search_group_chat_history", return_value=[]), \
                patch.object(ZFUNC, "chat_database_schema", return_value={"ok": True, "tables": {}}), \
                patch.object(ZFUNC, "chat_check_database_query",
                             return_value={"ok": True, "normalized_sql": "SELECT 1 AS value"}), \
                patch.object(ZFUNC, "chat_query_database",
                             return_value={"ok": True, "rows": [{"value": 1}], "columns": ["value"]}):
            result = ZCHAT.chat_process(user_text=registry.original_query, user_id="100", nickname="A",
                                        group_id="200", use_memory=False, model_caller=model,
                                        tool_registry=registry, return_artifacts=True)
        self.assertEqual(result["text"], "已改用游戏数据库查询。")
        self.assertEqual(result["trace"]["rounds"][1]["required_tool_missing"], "discover_tools")
        self.assertTrue(result["trace"]["context"]["forced_discovery_completed"])
        self.assertTrue(result["trace"]["context"]["forced_tool_workflow_completed"])
        self.assertEqual(len(calls), 5)

    def test_repeated_sql_failures_stop_at_configured_attempt_limit(self):
        calls = []
        registry = ZCHAT.HOKChatTools(
            user_id="100", use_memory=False,
            original_query="调用game_data查询历史战绩",
        )

        def model(messages, tools=None, tool_choice="auto", **kwargs):
            calls.append(tool_choice)
            if len(calls) == 1:
                call = {"call_id": "discover", "name": "discover_tools",
                        "arguments": '{"categories":["game_data"]}'}
            elif len(calls) <= 4:
                call = {"call_id": f"analysis-{len(calls)}", "name": "analyze_game_database",
                        "arguments": json.dumps({"queries": [{
                            "sql": "SELECT missing FROM hok.battle_records",
                            "intent": "故意触发列校验失败",
                        }]})}
            else:
                self.assertEqual(tool_choice, "none")
                return {"content": "三次查询均未通过字段校验，暂时无法给出结果。",
                        "tool_calls": [], "output_items": []}
            return {"tool_calls": [call], "output_items": [{"type": "function_call", **call}]}

        with patch.object(ZMEMORY.instance, "load_active_chat_records", return_value=[]), \
                patch.object(ZMEMORY.instance, "save_active_chat"), \
                patch.object(ZFUNC, "chat_roleplay_get", return_value=None), \
                patch.object(ZFUNC, "chat_database_schema", return_value={"ok": True, "tables": {}}), \
                patch.object(ZFUNC, "chat_check_database_query",
                             return_value={"ok": False, "error": "unknown column"}), \
                patch.object(ZFUNC, "chat_query_database") as execute, \
                patch.object(ZCHAT.dmc, "ChatSQLMaxAttempts", 3):
            result = ZCHAT.chat_process(
                user_text=registry.original_query, user_id="100", nickname="A",
                use_memory=False, model_caller=model, tool_registry=registry,
                return_artifacts=True,
            )
        self.assertEqual(result["trace"]["stop_reason"], "sql_attempt_limit")
        self.assertEqual(result["trace"]["limits"]["sql_max_attempts"], 3)
        self.assertEqual(len(calls), 5)
        execute.assert_not_called()

    def test_tool_result_is_appended_before_second_model_turn(self):
        calls = []

        def fake_model(messages, tools=None, tool_choice="auto", network=False):
            calls.append([dict(message) for message in messages])
            if len(calls) == 1:
                tool_calls = [{
                    "id": "fc-1",
                    "call_id": "call-1",
                    "name": "lookup",
                    "arguments": '{"name":"alpha"}',
                }]
                return {
                    "content": "",
                    "tool_calls": tool_calls,
                    "output_items": [{"type": "function_call", **tool_calls[0]}],
                }
            return {"content": "最终回答", "tool_calls": [], "output_items": []}

        tools = FakeTools()
        result = ZCHAT.chat_process(
            user_text="查一下alpha",
            user_id="100",
            nickname="Alpha",
            group_id="200",
            use_memory=False,
            tool_registry=tools,
            model_caller=fake_model,
        )

        self.assertEqual(result, "最终回答")
        self.assertEqual(tools.calls, [("lookup", {"name": "alpha"})])
        self.assertEqual(calls[1][-1]["type"], "function_call_output")
        self.assertEqual(calls[1][-1]["call_id"], "call-1")
        self.assertEqual(self.saved, [("100", "查一下alpha", "最终回答")])

    def test_invalid_arguments_still_receive_tool_result(self):
        calls = []

        def fake_model(messages, tools=None, tool_choice="auto", network=False):
            calls.append([dict(message) for message in messages])
            if len(calls) == 1:
                tool_calls = [{
                    "id": "fc-bad",
                    "call_id": "bad-call",
                    "name": "lookup",
                    "arguments": "not-json",
                }]
                return {"content": "", "tool_calls": tool_calls, "output_items": [{"type": "function_call", **tool_calls[0]}]}
            return {"content": "参数有误，已停止查询", "tool_calls": [], "output_items": []}

        result = ZCHAT.chat_process(
            user_text="测试",
            user_id="100",
            nickname="Alpha",
            use_memory=False,
            tool_registry=FakeTools(),
            model_caller=fake_model,
        )

        self.assertEqual(result, "参数有误，已停止查询")
        self.assertEqual(calls[1][-1]["type"], "function_call_output")
        self.assertIn("JSONDecodeError", calls[1][-1]["output"])

    def test_final_markdown_is_normalized_for_qq(self):
        def fake_model(messages, tools=None, tool_choice="auto", network=False):
            return {
                "content": "## 结论\n- 使用 `赵云`\n[详情](https://example.com)",
                "tool_calls": [],
                "output_items": [],
            }

        result = ZCHAT.chat_process(
            user_text="怎么打",
            user_id="100",
            nickname="Alpha",
            use_memory=False,
            tool_registry=FakeTools(),
            model_caller=fake_model,
        )

        self.assertEqual(result, "结论\n\n• 使用 赵云\n详情")

    def test_display_policy_and_final_identity_filter_preserve_raw_payloads(self):
        raw_answer = "**alpha（错误名字）**（qid: 123456789，roleid: 99887766）8场5胜，胜率62.5%。"
        raw_payload = {"choices": [{"message": {"content": raw_answer}}]}
        requests = []

        def model(messages, **kwargs):
            requests.extend(messages)
            return {"content": raw_answer, "request_payload": {"messages": messages}, "response_payload": raw_payload}

        with patch.object(ZCHAT, "namenick", {"alpha": "甲"}), patch.object(ZCHAT, "qid", {"alpha": "123456789"}), \
                patch.object(ZCHAT, "userlist", {}), patch.object(ZCHAT, "roleidlist", {"alpha": "99887766"}), \
                patch.object(ZCHAT, "nameref", {"alpha": ["错误名字"]}):
            result = ZCHAT.chat_process(user_text="谁表现好", user_id="123456789", nickname="甲", use_memory=True,
                                        tool_registry=FakeTools(), model_caller=model, return_artifacts=True)
        self.assertEqual(result["text"], "甲8场5胜，胜率62.5%。")
        self.assertEqual(result["trace"]["answer"], result["text"])
        self.assertEqual(self.saved[-1][-1], result["text"])
        self.assertEqual(result["trace"]["rounds"][0]["response_payload"], raw_payload)
        systems = "\n".join(item["content"] for item in requests if item["role"] == "system")
        self.assertIn('"namenick": "甲"', systems)
        self.assertIn("不输出任何身份或记录ID", systems)
        self.assertIn("回答默认简短", systems)
        self.assertIn("123456789", json.dumps(result["trace"]["rounds"][0]["request_payload"]))

    def test_empty_model_fallback_uses_nickname_without_speaker_id(self):
        class HistoryTools(FakeTools):
            def schemas(self):
                return [{"type": "function", "name": "fetch_recent_chat_messages", "parameters": {"type": "object"}}]

            def execute(self, name, arguments):
                return {"messages": [{"user_id": "123456789", "text": "lry今天5胜3负"},
                                     {"user_id": "99887766", "text": "我也在"}]}

        calls = []
        def model(messages, **kwargs):
            calls.append(messages)
            if len(calls) == 1:
                return {"tool_calls": [{"call_id": "recent", "name": "fetch_recent_chat_messages", "arguments": "{}"}]}
            return {"content": ""}

        with patch.object(ZCHAT, "qid", {"example_user_10": "123456789"}), patch.object(ZCHAT, "namenick", {"example_user_10": "示例玩家65"}):
            result = ZCHAT.chat_process(user_text="最近在聊什么", user_id="100", nickname="A", use_memory=False,
                                        tool_registry=HistoryTools(), model_caller=model, return_artifacts=True)
        self.assertIn("示例玩家65：示例玩家65今天5胜3负", result["text"])
        self.assertIn("群成员：我也在", result["text"])
        self.assertNotIn("123456789", result["text"])
        self.assertNotIn("99887766", result["text"])
        self.assertNotIn("example_user_10", result["text"])

    def test_long_term_memory_requires_explicit_tool_recall(self):
        seen = []
        ZMEMORY.instance.load_user_forced_memory = lambda qid, num=5: "偏好辅助英雄"

        def fake_model(messages, tools=None, tool_choice="auto", network=False):
            seen.extend(messages)
            return {"content": "收到", "tool_calls": [], "output_items": []}

        result = ZCHAT.chat_process(
            user_text="推荐英雄",
            user_id="100",
            nickname="Alpha",
            use_memory=True,
            tool_registry=FakeTools(),
            model_caller=fake_model,
        )

        self.assertEqual(result, "收到")
        self.assertFalse(any("偏好辅助英雄" in item.get("content", "") for item in seen))
        self.assertEqual(self.saved, [("100", "推荐英雄", "收到")])


class HOKChatToolsTests(unittest.TestCase):
    def test_model_argument_normalization_preserves_trusted_history_scope(self):
        tools = ZCHAT.HOKChatTools(group_id="200", original_query="谁发言最多")
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
        tools = ZCHAT.HOKChatTools(original_query="谁的对局最多")
        result = tools.normalize_model_arguments("analyze_game_database", {
            "queries": ["SELECT 1 AS games", {"sql": "SELECT 2 AS games", "intent": "另一组"}],
        })
        self.assertEqual(result["queries"], [
            {"sql": "SELECT 1 AS games", "intent": "谁的对局最多"},
            {"sql": "SELECT 2 AS games", "intent": "另一组"},
        ])

    def test_unspecified_hero_period_must_follow_documented_season_default(self):
        tools = ZCHAT.HOKChatTools(original_query="谁玩某个英雄最多")
        sql = "SELECT hero_name, COUNT(*) FROM hok.battle_records GROUP BY hero_name"
        with patch.object(ZFUNC, "chat_check_database_query",
                          return_value={"ok": True, "normalized_sql": sql}), \
                patch.object(ZFUNC, "chat_query_database") as execute:
            result = tools.execute("analyze_game_database", {"queries": [
                {"sql": sql, "intent": "英雄使用次数"},
            ]})
        self.assertEqual(result["stage"], "validation")
        self.assertIn("默认本赛季", result["observations"][0]["error"])
        execute.assert_not_called()
        self.assertEqual(
            ZCHAT.resolved_analysis_question("查下具体数据呢", previous_query="谁玩某个英雄最多"),
            "谁玩某个英雄最多",
        )

    def test_group_scope_cannot_be_set_by_model_arguments(self):
        for group_id in (None, "200"):
            with self.subTest(group_id=group_id), patch.object(ZFUNC, "search_group_chat_history") as search:
                with self.assertRaises(ValueError):
                    ZCHAT.HOKChatTools(group_id=group_id).execute(
                        "search_chat_history", {"queries": ["内卷 竞争", "压力 讨论"], "group_id": "other-group"})
                search.assert_not_called()

    def test_large_batch_preserves_each_outcome_and_dataset(self):
        observations = [{"ok": True, "dataset_id": f"dataset_{n}", "rows": [{"value": "x" * 1000}] * 50,
                         "row_count": 50, "columns": ["value"]} for n in range(4)]
        value = {"ok": True, "data": {"observations": observations}}
        result = json.loads(ZCHAT._serialize_tool_result(value))
        self.assertEqual(len(result["data"]["observations"]), 4)
        for n, item in enumerate(result["data"]["observations"]):
            self.assertEqual(item["dataset_id"], f"dataset_{n}")
            self.assertTrue(item["context_truncated"])
        self.assertEqual(len(observations[0]["rows"]), 50)

    def test_successful_sql_context_does_not_echo_the_submitted_plan(self):
        observation = {
            "ok": True,
            "stage": "execution",
            "intent": "统计胜率",
            "assumptions": ["本赛季"],
            "normalized_sql": "SELECT player_key FROM hok.battle_records",
            "dataset_id": "dataset_1",
            "rows": [{"player_key": "a"}],
        }
        value = {"ok": True, "data": {"observations": [observation]}}
        serialized = json.loads(ZCHAT._serialize_tool_result(value))
        sent = serialized["data"]["observations"][0]
        self.assertNotIn("normalized_sql", sent)
        self.assertNotIn("intent", sent)
        self.assertNotIn("assumptions", sent)
        self.assertEqual(sent["dataset_id"], "dataset_1")
        self.assertIn("normalized_sql", observation)

    def test_sql_row_projection_omits_machine_values_without_mutating_dataset(self):
        row = {
            "hero": "瑶",
            "description": "推荐出装见 https://example.test/build?token=private，胜率为 52%",
            "metadata": {"icon_url": "https://example.test/very/long/icon.png",
                         "image": "data:image/png;base64," + "a" * 600,
                         "blob": "A" * 300},
            "scores": [51.2, 52.8],
        }
        value = {"ok": True, "data": {"observations": [{
            "ok": True, "stage": "execution", "rows": [row], "row_count": 1,
            "columns": list(row), "dataset_id": "dataset_1",
        }]}}
        projected = json.loads(ZCHAT._serialize_tool_result(value, omit_sql_machine_values=True))
        sent = projected["data"]["observations"][0]
        self.assertEqual(sent["dataset_id"], "dataset_1")
        self.assertEqual(sent["row_count"], 1)
        self.assertEqual(sent["columns"], list(row))
        self.assertEqual(sent["rows"][0]["hero"], "瑶")
        self.assertIn("，胜率为 52%", sent["rows"][0]["description"])
        self.assertNotIn("example.test", json.dumps(sent, ensure_ascii=False))
        self.assertEqual(sent["rows"][0]["metadata"]["image"], "[URL omitted]")
        self.assertIn("opaque content omitted", sent["rows"][0]["metadata"]["blob"])
        self.assertEqual(value["data"]["observations"][0]["rows"][0], row)
        raw = json.loads(ZCHAT._serialize_tool_result(value))
        self.assertEqual(raw["data"]["observations"][0]["rows"][0], row)

    def test_database_and_live_power_are_separate_tools(self):
        registry = ZCHAT.HOKChatTools()
        self.assertEqual({item["name"] for item in registry.initial_schemas()}, {"discover_tools"})
        names = {item["name"] for item in registry.schemas()}
        self.assertTrue({"analyze_game_database", "check_game_database_query", "query_game_database",
                         "query_player_hero_power", "query_honor_power",
                         "render_python_plot", "web_search"}.issubset(names))
        self.assertNotIn("query_player_today_report", names)
        self.assertNotIn("remember_memory", names)

    def test_pre_disclosed_history_does_not_force_redundant_discovery(self):
        registry = ZCHAT.HOKChatTools(group_id="200", original_query="查看群聊历史")
        self.assertTrue(registry.require_automatic_history_search())
        self.assertEqual(registry.required_discovery_categories(), [])
        self.assertNotIn("get_chat_history_database_schema",
                         {item["name"] for item in registry.model_schemas()})

    def test_group_message_ranking_requires_scoped_chat_sql_workflow(self):
        registry = ZCHAT.HOKChatTools(group_id="200", original_query="谁发消息最多")
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
                registry = ZCHAT.HOKChatTools(user_id="100", original_query=question)
                self.assertIn("game_data", registry.required_discovery_categories())

    def test_group_chat_sql_ticket_executes_with_request_bound_scope(self):
        tools = ZCHAT.HOKChatTools(group_id="200", original_query="发言统计")
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
        private = ZCHAT.HOKChatTools(user_id="100", original_query="群聊发言统计")
        names = {item["name"] for item in private.schemas()}
        self.assertNotIn("get_chat_history_database_schema", names)
        self.assertNotIn("analyze_chat_history_database", names)
        with self.assertRaises(ZCHAT.ChatToolUnavailableError):
            private.execute("analyze_chat_history_database", {"queries": [{
                "sql": "SELECT COUNT(*) FROM hok.chat_history_messages",
                "intent": "统计群聊消息",
            }]})

    def test_disabled_explicit_category_does_not_force_unknown_tool(self):
        registry = ZCHAT.HOKChatTools(user_id="100", use_memory=False,
                                      original_query="调用memory记忆工具")
        categories = registry.required_discovery_categories()
        self.assertEqual(categories, ["memory"])
        result = registry.execute("discover_tools", {"categories": categories})
        self.assertEqual(result["unavailable_categories"], ["memory"])
        self.assertIsNone(registry.required_workflow_tool(categories))

    def test_empty_response_after_disclosure_retries_with_tools_preserved(self):
        requests = []
        registry = ZCHAT.HOKChatTools(user_id="100", use_memory=False)

        def model(messages, tools=None, tool_choice="auto", **kwargs):
            names = {tool["name"] for tool in tools or []}
            requests.append({"messages": [dict(item) for item in messages],
                             "names": names, "tool_choice": tool_choice})
            if len(requests) == 1:
                call = {"call_id": "discover", "name": "discover_tools",
                        "arguments": '{"categories":["game_data"],"reason":"需要历史统计"}'}
                return {"tool_calls": [call], "output_items": [{"type": "function_call", **call}]}
            if len(requests) == 2:
                self.assertIn("analyze_game_database", names)
                systems = [item.get("content", "") for item in messages if item.get("role") == "system"]
                self.assertEqual(sum("已知玩家与身份" in text for text in systems), 1)
                return {"content": None, "tool_calls": [], "output_items": []}
            if len(requests) == 3:
                self.assertEqual(tool_choice, "auto")
                self.assertIn("analyze_game_database", names)
                self.assertIn("不得在没有失败observation", messages[-1]["content"])
                call = {"call_id": "analysis", "name": "analyze_game_database",
                        "arguments": json.dumps({"queries": [{"sql": "SELECT 1 AS value",
                                                                 "intent": "继续历史统计"}]})}
                return {"tool_calls": [call], "output_items": [{"type": "function_call", **call}]}
            return {"content": "查询已继续完成", "tool_calls": [], "output_items": []}

        with patch.object(ZMEMORY.instance, "load_active_chat_records", return_value=[]), \
                patch.object(ZMEMORY.instance, "save_active_chat"), \
                patch.object(ZFUNC, "chat_roleplay_get", return_value=None), \
                patch.object(ZFUNC, "chat_database_schema", return_value={"ok": True, "tables": {}}) as schema:
            result = ZCHAT.chat_process(user_text="比较历史数据", user_id="100", nickname="A",
                                        use_memory=False, model_caller=model,
                                        tool_registry=registry, return_artifacts=True)
        self.assertEqual(result["text"], "查询已继续完成")
        self.assertEqual(result["trace"]["recovery"], {
            "reason": "chat_empty_response", "attempts": 1,
            "mode": "tools_preserved", "outcome": "recovered",
        })
        self.assertEqual(result["trace"]["summary"]["tool_calls"], 2)
        schema.assert_called_once_with()

    def test_batch_queries_keep_partial_errors_and_datasets_private_to_request(self):
        tools = ZCHAT.HOKChatTools()
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
        self.assertEqual(ZCHAT.HOKChatTools().datasets, {})
        with patch.object(ZFUNC, "chat_render_plot", return_value={"path": "/tmp/trusted.png", "width": 1456}) as plot:
            result = tools.execute("render_python_plot", {"dataset_id": "dataset_1", "options": {"columns": {"value": "score"}}})
        self.assertNotIn("path", result)
        self.assertEqual(tools.artifacts[0]["path"], "/tmp/trusted.png")
        self.assertEqual(plot.call_args.args[0], [{"player": "A", "score": 9}])
        with self.assertRaises(ValueError):
            ZCHAT.HOKChatTools().execute("render_python_plot", {"dataset_id": "dataset_1"})
        with self.assertRaisesRegex(ValueError, "unknown_or_consumed_check_id"):
            tools.execute("query_game_database", {"check_id": checked["check_id"]})
        with patch.object(ZFUNC, "chat_check_database_query",
                          return_value={"ok": True, "normalized_sql": "SELECT 3 AS score"}):
            next_checked = tools.execute("check_game_database_query", {"queries": [
                {"sql": "SELECT 3 AS score", "intent": "third metric"},
            ]})
        self.assertEqual(next_checked["check_id"], "sql_check_2")

    def test_database_batch_cannot_execute_until_every_query_passes_checker(self):
        tools = ZCHAT.HOKChatTools()
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
        tools = ZCHAT.HOKChatTools()
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
        tools = ZCHAT.HOKChatTools(original_query="统计每周总场次")
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
        tools = ZCHAT.HOKChatTools(original_query="比较两人的英雄评分")
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
        tools = ZCHAT.HOKChatTools(user_id="100")
        with patch.object(ZFUNC, "chat_memory_save", return_value={"saved": True}) as save:
            tools.execute("remember_memory", {"content": "喜欢辅助"})
            save.assert_called_once_with("100", "喜欢辅助", memory_id="")
            with self.assertRaises(ValueError):
                tools.execute("remember_memory", {"content": "喜欢辅助", "user_id": "200"})
        with self.assertRaises(ValueError):
            ZCHAT.HOKChatTools(user_id="100", use_memory=False).execute("remember_memory", {"content": "喜欢辅助"})

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
            result = ZCHAT.HOKChatTools().execute("query_player_hero_power", {"player": "Alice", "hero": "云"})
        official.assert_called_once_with(reqtype="heropower", userid="game-user", roleid="game-role")
        self.assertEqual(result["heroes"][0]["power"], 5000)
        self.assertEqual(len(result["heroes"]), 1)

    def test_honor_power_keeps_region_specific_business_flow(self):
        with patch.object(ZFUNC, "extract_name", return_value="alice"), \
                patch.object(ZFUNC, "honor_power_query_process", return_value="地区榜单") as honor:
            result = ZCHAT.HOKChatTools().execute("query_honor_power", {"player": "Alice", "hero": "大乔", "region": "上海市闵行区"})
        self.assertEqual(result, "地区榜单")
        honor.assert_called_once_with("alice", "大乔 上海市闵行区 战力查询")

    def test_multiple_calls_receive_independent_observations_and_artifact_delivery(self):
        snapshots = []
        registry = ZCHAT.HOKChatTools(user_id="100", use_memory=False)
        registry.execute("discover_tools", {"categories": ["game_data", "internet", "plots"]})
        def model(messages, **kwargs):
            snapshots.append([dict(item) for item in messages])
            if len(snapshots) == 1:
                calls = [{"call_id": "analysis", "name": "analyze_game_database", "arguments": json.dumps({"queries": [{"sql": "SELECT 1 AS value", "intent": "compare values"}]})},
                         {"call_id": "web", "name": "web_search", "arguments": '{"query":"赛事新闻"}'}]
            elif len(snapshots) == 2:
                outputs = [item for item in messages if item.get("type") == "function_call_output"]
                self.assertEqual([item["call_id"] for item in outputs], ["analysis", "web"])
                self.assertTrue(json.loads(outputs[0]["output"])["ok"])
                self.assertFalse(json.loads(outputs[1]["output"])["ok"])
                calls = [{"call_id": "plot", "name": "render_python_plot", "arguments": '{"dataset_id":"dataset_1"}'}]
            else:
                return {"content": "已生成图表，联网暂不可用", "tool_calls": []}
            return {"tool_calls": calls, "output_items": [{"type": "function_call", **call} for call in calls]}
        with patch.object(ZFUNC, "chat_check_database_query", return_value={"ok": True, "normalized_sql": "SELECT 1 AS value"}), \
                patch.object(ZFUNC, "chat_query_database", return_value={"ok": True, "rows": [{"label": "A", "value": 9}]}), \
                patch.object(ZFUNC, "chat_web_search", side_effect=RuntimeError("Aliyun OpenSearch unavailable")), \
                patch.object(ZFUNC, "chat_render_plot", return_value={"path": "/tmp/trusted.png", "width": 1456}), \
                patch.object(ZMEMORY.instance, "load_active_chat_records", return_value=[]), \
                patch.object(ZMEMORY.instance, "save_active_chat") as save:
            result = ZCHAT.chat_process(user_text="比较并画图", user_id="100", nickname="A", use_memory=False,
                                        model_caller=model, tool_registry=registry, return_artifacts=True)
        self.assertEqual(result["artifacts"][0]["path"], "/tmp/trusted.png")
        self.assertEqual(len(snapshots), 3)
        save.assert_called_once_with("100", "比较并画图", "已生成图表，联网暂不可用")


if __name__ == "__main__":
    unittest.main()
