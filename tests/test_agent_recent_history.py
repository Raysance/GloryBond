"""Window retrieval stays bounded, scoped and optional in the same ReAct loop."""
import datetime
import json
import unittest
from unittest.mock import AsyncMock, patch

from agent_runtime import AgentRuntime, Principal, RunRequest, ToolRegistry
from agent_console import remote_worker as worker
from agent_console.capabilities import Capabilities, application_prompt
from agent_console.tools.application import register_application_tools
from agent_console.tools.memory import recent_history_limits
from tests.test_agent_runtime import Clock, ScriptedModel, Sink, State, call


class Database:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchall(self):
        return self.rows


class RecentHistoryWorkerTests(unittest.TestCase):
    def setUp(self):
        self.principal = {"user_id":"100", "group_id":"200", "all_groups":False, "scopes":["chat.read"]}
        self.context = {"cfg":{}, "memory":{"recent_history_limits":recent_history_limits}, "store":object()}

    def read(self, db, **extra):
        with patch.dict(worker.CONTEXT, self.context, clear=True), patch.object(worker, "db_connection", return_value=db) as connection:
            result = worker.dispatch({"op":"recent_history", "principal":self.principal, **extra})
        return result, connection

    def test_window_filters_at_database_and_keeps_multiple_senders_in_chronological_order(self):
        rows = [{"message_id":"3", "user_id":"100", "timestamp":300, "text":"最近的话题", "text_truncated":False},
                {"message_id":"2", "user_id":"101", "timestamp":200, "text":"其他人的发言", "text_truncated":True},
                {"message_id":"1", "user_id":"102", "timestamp":100, "text":"更早的话题", "text_truncated":False}]
        db = Database(rows)
        result, connection = self.read(db, limit=2, window_minutes=10, exclude_message_id="42")
        connection.assert_called_once_with("200")
        sql, params = db.calls[0]
        self.assertIn("hok.chat_history_messages", sql)
        self.assertNotIn("hok.group_chat_messages", sql)
        self.assertIn("source_timestamp>=%s AND source_timestamp<=%s", sql)
        self.assertIn("message_id<>%s", sql)
        self.assertNotIn("user_id=", sql)
        self.assertEqual(params[2], "200")
        self.assertEqual(params[4] - params[3], 600)
        self.assertIs(type(params[3]), int)  # The authoritative view stores Unix seconds.
        self.assertEqual(params[-2:], ["42",3])
        self.assertEqual([r["message_id"] for r in result["messages"]], ["2","3"])
        self.assertTrue(result["has_older_messages"])
        self.assertTrue(result["text_truncated"])

    def test_empty_window_reports_no_messages_and_config_defaults_match_schema_policy(self):
        self.context["cfg"] = {"AgentHistory":{"window_minutes":8,"limit":4,"max_message_chars":80}}
        result, _ = self.read(Database())
        self.assertEqual((result["window_minutes"], result["limit"]), (8,4))
        self.assertEqual(result["messages"], [])
        self.assertFalse(result["has_older_messages"])
        self.assertFalse(result["text_truncated"])

    def test_malformed_configuration_is_rejected_instead_of_silently_using_defaults(self):
        for config in [False, [], "", {"limit":0}, {"limit":True}, {"limit":51}, {"unknown":1}]:
            with self.subTest(config=config), self.assertRaises(ValueError):
                recent_history_limits(config)

    def test_permissions_scope_and_limits_fail_before_database_access(self):
        cases = [({**self.principal, "scopes":[]}, {}, PermissionError),
                 ({**self.principal, "group_id":None}, {}, PermissionError),
                 (self.principal, {"group_id":"300"}, PermissionError),
                 ({**self.principal, "all_groups":True, "scopes":["chat.read","chat.cross_group"]}, {"group_id":"300"}, PermissionError),
                 (self.principal, {"limit":51}, ValueError),
                 (self.principal, {"window_minutes":61}, ValueError),
                 (self.principal, {"window_minutes":True}, ValueError),
                 (self.principal, {"limit":0}, ValueError)]
        for principal, extra, error in cases:
            with self.subTest(principal=principal, extra=extra), patch.dict(worker.CONTEXT, self.context, clear=True), \
                 patch.object(worker, "db_connection") as connection, self.assertRaises(error):
                worker.recent_history({"principal":principal, **extra})
            connection.assert_not_called()

    def test_admin_private_selects_one_group_and_does_not_exclude_private_message_id(self):
        self.principal = {"user_id":"100", "all_groups":True, "scopes":["chat.read","chat.cross_group"]}
        with self.assertRaisesRegex(ValueError, "目标群"):
            self.read(Database())
        db = Database()
        result, connection = self.read(db, group_id="300", exclude_message_id="42")
        connection.assert_called_once_with("300")
        self.assertNotIn("message_id<>%s", db.calls[0][0])
        self.assertEqual(result["scope"], "selected_group")

    def test_admin_default_group_applies_to_window_without_private_id_exclusion(self):
        self.principal = {'user_id': '100', 'all_groups': True, 'default_group_id': '2000000001',
                          'scopes': ['chat.read', 'chat.cross_group']}
        db = Database()
        result, connection = self.read(db, exclude_message_id='42')
        connection.assert_called_once_with('2000000001')
        self.assertEqual(result['group_id'], '2000000001')
        self.assertNotIn('message_id<>%s', db.calls[0][0])
        _, connection = self.read(Database(), group_id='300')
        connection.assert_called_once_with('300')


class RecentHistoryToolTests(unittest.IsolatedAsyncioTestCase):
    def registry(self, bridge, policy=None):
        registry = ToolRegistry()
        register_application_tools(registry, service=Capabilities(bridge),
            catalogs={"chat_history":{"recent_limits":policy or {}}})
        return registry

    async def test_agent_discovers_and_uses_recent_context_after_empty_search(self):
        bridge = AsyncMock()
        async def respond(op, **args):
            if op == "search_history":
                return {"messages":[]}
            if op == "recent_history":
                return {"messages":[{"user_id":"101", "text":"刚才正在聊今晚五排缺辅助"}]}
            raise AssertionError(op)
        bridge.call.side_effect = respond
        registry = self.registry(bridge)
        model = ScriptedModel([
            {"role":"assistant", "content":"", "tool_calls":[call("search_chat_history", {"queries":["刚才话题","当前讨论"]}, "s")]},
            {"role":"assistant", "content":"", "tool_calls":[call("discover_tools", {"categories":["chat_history"]}, "d")]},
            {"role":"assistant", "content":"", "tool_calls":[call("read_recent_chat_history", {}, "r")]},
            {"role":"assistant", "content":"刚才在聊今晚五排缺辅助。"},
        ])
        state = State()
        runtime = AgentRuntime(model=model, registry=registry, state=state, output=Sink(), clock=Clock())
        principal = Principal("100", frozenset({"chat.read"}), {"chat":{"group_id":"200"}})
        result = await runtime.run(RunRequest("刚才聊啥？", "s", principal, system_prompt=application_prompt(),
            required_tools=("search_chat_history","discover_tools"), metadata={"message_id":"42"}))
        self.assertIn("缺辅助", result["text"])
        self.assertNotIn("read_recent_chat_history", [t["function"]["name"] for t in model.schemas[0]])
        recent = next(c for c in bridge.call.await_args_list if c.args[0] == "recent_history")
        self.assertEqual(recent.kwargs["principal"]["group_id"], "200")
        self.assertEqual(recent.kwargs["exclude_message_id"], "42")
        self.assertEqual((recent.kwargs["window_minutes"],recent.kwargs["limit"]), (15,20))
        self.assertEqual([e["data"]["name"] for e in state.events if e["kind"] == "tool.result"],
                         ["search_chat_history","discover_tools","read_recent_chat_history"])
        self.assertNotIn("刚才正在聊", json.dumps(state.dialogue, ensure_ascii=False))

    async def test_private_user_cannot_discover_recent_tool_and_schema_uses_configured_limits(self):
        from agent_runtime.models import ToolContext
        registry = self.registry(AsyncMock(), {"window_minutes":7,"max_window_minutes":30,"limit":6,"max_limit":12})
        ctx = ToolContext(RunRequest("test", "s", Principal("100")), None)
        self.assertNotIn("read_recent_chat_history", registry.available(ctx))
        schema = registry.tools["read_recent_chat_history"].schema()["function"]["parameters"]["properties"]
        self.assertEqual((schema["window_minutes"]["default"],schema["window_minutes"]["maximum"]), (7,30))
        self.assertEqual((schema["limit"]["default"],schema["limit"]["maximum"]), (6,12))
        for args in ({"limit":13}, {"window_minutes":31}, {"window_minutes":True}):
            with self.assertRaises(ValueError):
                registry.tools["read_recent_chat_history"].args_model.model_validate(args)
