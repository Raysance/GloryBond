import unittest

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

        self.assertEqual(result, "结论\n• 使用 赵云\n详情")

    def test_current_user_forced_memory_is_injected_as_system_context(self):
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
        self.assertTrue(any("偏好辅助英雄" in item.get("content", "") for item in seen))


class HOKChatToolsTests(unittest.TestCase):
    def test_player_capabilities_are_split_into_structured_tools(self):
        tool_names = {
            item["name"]
            for item in ZCHAT.HOKChatTools().schemas()
        }

        self.assertNotIn("query_player", tool_names)
        self.assertTrue({
            "query_player_today_report",
            "query_player_past_day_report",
            "query_player_period_report",
            "query_player_hero_stats",
            "query_player_hero_rankings",
            "query_group_hero_stats",
            "query_group_hero_rankings",
        }.issubset(tool_names))

    def test_past_day_report_builds_canonical_business_call(self):
        original_extract_name = ZFUNC.extract_name
        original_single_process = ZFUNC.single_process
        calls = []
        ZFUNC.extract_name = lambda value, precise=False: "alice"
        ZFUNC.single_process = lambda query: calls.append(query) or ["战报", [], True, None, "1"]
        try:
            result = ZCHAT.HOKChatTools().execute(
                "query_player_past_day_report",
                {"player": "Alice", "days_ago": 2},
            )
        finally:
            ZFUNC.extract_name = original_extract_name
            ZFUNC.single_process = original_single_process

        self.assertEqual(result, "战报")
        self.assertEqual(calls, ["alice $ 2"])

    def test_single_hero_tool_resolves_entities_before_business_call(self):
        original_extract_name = ZFUNC.extract_name
        original_extract_hero = ZFUNC.extract_heroname
        original_process = ZFUNC.single_player_single_hero_process
        calls = []
        ZFUNC.extract_name = lambda value, precise=False: "alice"
        ZFUNC.extract_heroname = lambda value, precise=False: (123, "赵云")
        ZFUNC.single_player_single_hero_process = lambda *args, **kwargs: calls.append((args, kwargs)) or "英雄统计"
        try:
            result = ZCHAT.HOKChatTools().execute(
                "query_player_hero_stats",
                {"player": "Alice", "hero": "赵云", "this_season": False},
            )
        finally:
            ZFUNC.extract_name = original_extract_name
            ZFUNC.extract_heroname = original_extract_hero
            ZFUNC.single_player_single_hero_process = original_process

        self.assertEqual(result, "英雄统计")
        self.assertEqual(calls, [(('alice', 123, '赵云'), {'this_season': False})])


if __name__ == "__main__":
    unittest.main()
