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
        self.original_load = ZMEMORY.instance.load_active_chat
        self.original_load_forced = ZMEMORY.instance.load_user_forced_memory
        self.original_save = ZMEMORY.instance.save_active_chat
        ZMEMORY.instance.load_active_chat = lambda qid, num=5: ""
        ZMEMORY.instance.load_user_forced_memory = lambda qid, num=5: ""
        self.saved = []
        ZMEMORY.instance.save_active_chat = lambda qid, question, answer: self.saved.append((qid, question, answer))

    def tearDown(self):
        ZMEMORY.instance.load_active_chat = self.original_load
        ZMEMORY.instance.load_user_forced_memory = self.original_load_forced
        ZMEMORY.instance.save_active_chat = self.original_save

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
        self.assertEqual(self.saved, [])

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

        self.assertEqual(result, "结论\n• 使用 赵云\n详情")

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

    def test_database_and_live_power_are_separate_tools(self):
        names = {item["name"] for item in ZCHAT.HOKChatTools().schemas()}
        self.assertTrue({"query_game_database", "query_player_hero_power", "query_honor_power",
                         "render_python_plot", "web_search"}.issubset(names))
        self.assertNotIn("query_player_today_report", names)
        self.assertNotIn("remember_memory", names)

    def test_batch_queries_keep_partial_errors_and_datasets_private_to_request(self):
        tools = ZCHAT.HOKChatTools()
        with patch.object(ZFUNC, "chat_query_database", side_effect=[
            {"ok": True, "rows": [{"player": "A", "score": 9}], "columns": ["player", "score"]},
            {"ok": False, "error": "forbidden_sql"},
        ]):
            result = tools.execute("query_game_database", {"queries": [{"sql": "SELECT ..."}, {"sql": "DELETE ..."}]})
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
        def model(messages, **kwargs):
            snapshots.append([dict(item) for item in messages])
            if len(snapshots) == 1:
                calls = [{"call_id": "query", "name": "query_game_database", "arguments": json.dumps({"queries": [{"sql": "SELECT ..."}]})},
                         {"call_id": "web", "name": "web_search", "arguments": '{"query":"赛事新闻"}'}]
            elif len(snapshots) == 2:
                outputs = [item for item in messages if item.get("type") == "function_call_output"]
                self.assertEqual([item["call_id"] for item in outputs], ["query", "web"])
                self.assertTrue(json.loads(outputs[0]["output"])["ok"])
                self.assertFalse(json.loads(outputs[1]["output"])["ok"])
                calls = [{"call_id": "plot", "name": "render_python_plot", "arguments": '{"dataset_id":"dataset_1"}'}]
            else:
                return {"content": "已生成图表，联网暂不可用", "tool_calls": []}
            return {"tool_calls": calls, "output_items": [{"type": "function_call", **call} for call in calls]}
        with patch.object(ZFUNC, "chat_query_database", return_value={"ok": True, "rows": [{"label": "A", "value": 9}]}), \
                patch.object(ZFUNC, "chat_web_search", side_effect=RuntimeError("Ark unavailable")), \
                patch.object(ZFUNC, "chat_render_plot", return_value={"path": "/tmp/trusted.png", "width": 1456}), \
                patch.object(ZMEMORY.instance, "save_active_chat") as save:
            result = ZCHAT.chat_process(user_text="比较并画图", user_id="100", nickname="A", use_memory=False,
                                        model_caller=model, tool_registry=registry, return_artifacts=True)
        self.assertEqual(result["artifacts"][0]["path"], "/tmp/trusted.png")
        self.assertEqual(len(snapshots), 3)
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
