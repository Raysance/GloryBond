"""Business discovery, authorization, reentry and real scheduler integration."""

import asyncio
import dataclasses
import json
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from pydantic import Field

from agent_runtime import AgentRuntime, Principal, RunRequest
from agent_runtime.models import ToolContext
from agent_runtime.tools.executor import execute
from agent_console.capabilities import Capabilities
from agent_console.function_calls import (FunctionArgs, FunctionCatalog, FunctionOutput,
    SearchFunctionsArgs, assert_outside_function, register_function_tools)
from agent_console.tasks import TaskScheduler
from agent_console.tools.application import register_application_tools
from agent_console.tools.diagnostics import DiagnosticToolRegistry
from qq_agent.business_functions import build_hok_function_catalog
from tests.test_agent_runtime import Clock, ScriptedModel, Sink, State, call


class ValueArgs(FunctionArgs):
    value: int = Field(default=1, ge=1, le=10, strict=True)


def context(*, scopes=("game.read",), origin=None):
    return ToolContext(RunRequest("test", "s", Principal("101", frozenset(scopes),
        {"identity": {"player_key": "player"}}), metadata={"origin": origin} if origin else {}), AsyncMock())


class FunctionTests(unittest.IsolatedAsyncioTestCase):
    def make_catalog(self, handler=None, **options):
        catalog = FunctionCatalog(**options)
        handler = handler or Mock(return_value=FunctionOutput(text="真实结果"))
        catalog.register(name="query_player", description="查询玩家状态", category="players",
            args_model=ValueArgs, handler=handler)
        return catalog, handler

    async def test_discovery_is_small_paged_and_never_contains_all_schemas(self):
        catalog, _ = self.make_catalog()
        for i in range(30):
            catalog.register(name=f"query_more_{i}", description=f"其它功能{i}", category="more",
                args_model=ValueArgs, handler=Mock())
        registry = DiagnosticToolRegistry()
        register_application_tools(registry, service=Capabilities(Mock()), catalogs={})
        register_function_tools(registry, catalog=catalog)
        ctx = context()
        ctx.disclosed = registry.initial_names(ctx)
        initial = json.dumps(registry.schemas(ctx), ensure_ascii=False)
        self.assertNotIn("query_player", initial)
        self.assertIn("hok_business", initial)
        result = await execute(registry, call("discover_tools", {"categories": ["hok_business"]}), ctx)
        self.assertTrue(result.ok)
        schemas = registry.schemas(ctx)
        self.assertEqual(len([s for s in schemas if "hok_function" in s["function"]["name"]]), 3)
        self.assertNotIn("query_more_29", json.dumps(schemas))
        page = catalog.search(SearchFunctionsArgs(limit=3), ctx)
        self.assertEqual(len(page["functions"]), 3)
        self.assertEqual(page["next_offset"], 3)
        self.assertNotIn("parameters", str(page))
        ctx2 = context(scopes=())
        self.assertEqual(catalog.search(SearchFunctionsArgs(), ctx2)["total"], 0)
        self.assertEqual(catalog.describe("query_player", ctx2).code, "FUNCTION_UNAVAILABLE")

    async def test_describe_required_authorization_checked_on_every_call_and_no_argument_injection(self):
        catalog, handler = self.make_catalog()
        ctx = context()
        self.assertEqual((await catalog.call("query_player", {}, ctx)).code, "FUNCTION_NOT_DESCRIBED")
        catalog.describe("query_player", ctx)
        for args in ({"value": "2"}, {"group_id": "999"}, {"principal": {}}, {"value": 99}):
            self.assertEqual((await catalog.call("query_player", args, ctx)).code, "INVALID_ARGUMENTS")
        self.assertEqual((await catalog.call("agent_chat", {}, ctx)).code, "FUNCTION_UNAVAILABLE")
        denied = context(scopes=())
        self.assertEqual((await catalog.call("query_player", {}, denied)).code, "FUNCTION_UNAVAILABLE")
        handler.assert_not_called()

    async def test_identical_calls_execute_once_but_different_runs_are_isolated(self):
        catalog, handler = self.make_catalog()
        ctx = context()
        catalog.describe("query_player", ctx)
        first = await catalog.call("query_player", {}, ctx)
        again = await catalog.call("query_player", {"value": 1}, ctx)
        self.assertIs(first, again)
        handler.assert_called_once()
        ctx2 = context()
        catalog.describe("query_player", ctx2)
        await catalog.call("query_player", {}, ctx2)
        self.assertEqual(handler.call_count, 2)

    async def test_call_budget_and_output_budget_are_enforced(self):
        catalog, handler = self.make_catalog(max_calls=1, max_result_chars=1000,
            handler=Mock(return_value=FunctionOutput(text="x" * 1100)))
        ctx = context()
        catalog.describe("query_player", ctx)
        first = await catalog.call("query_player", {}, ctx)
        self.assertTrue(first.data["truncated"])
        self.assertEqual(len(first.data["text"]), 1000)
        self.assertEqual((await catalog.call("query_player", {"value": 2}, ctx)).code, "FUNCTION_CALL_LIMIT")
        handler.assert_called_once()

    async def test_reentry_and_background_child_tasks_never_reach_state_store(self):
        bridge = SimpleNamespace(call=AsyncMock())
        capabilities = Capabilities(bridge)
        with self.assertRaises(PermissionError):
            await capabilities.create_task({}, context(origin="background"))
        bridge.call.assert_not_called()
        async def recursive(args, ctx):
            await capabilities.create_task({}, ctx)
        catalog, _ = self.make_catalog(handler=recursive)
        ctx = context()
        catalog.describe("query_player", ctx)
        with self.assertRaisesRegex(RuntimeError, "禁止重新进入"):
            await catalog.call("query_player", {}, ctx)
        self.assertEqual((await catalog.call("query_player", {}, ctx)).code, "FUNCTION_ALREADY_CALLED")
        bridge.call.assert_not_called()
        await capabilities.create_task({"kind": "message", "message": "ok"}, context())
        bridge.call.assert_awaited_once()

    async def test_qq_task_creation_override_cannot_bypass_background_or_reentry_guard(self):
        from qq_agent.mentions import QQCapabilities, ReplyMentions
        bridge = SimpleNamespace(call=AsyncMock())
        capabilities = QQCapabilities(bridge, bridge, ReplyMentions())
        with self.assertRaises(PermissionError):
            await capabilities.create_task({}, context(origin="background"))
        async def recursive(args, ctx):
            return await capabilities.create_task({}, ctx)
        catalog, _ = self.make_catalog(handler=recursive)
        ctx = context()
        catalog.describe("query_player", ctx)
        with self.assertRaisesRegex(RuntimeError, "禁止重新进入"):
            await catalog.call("query_player", {}, ctx)
        bridge.call.assert_not_called()

    async def test_sync_thread_context_blocks_ai_reentry_and_unwinds(self):
        def recursive(args, ctx):
            assert_outside_function()
        catalog, _ = self.make_catalog(handler=recursive)
        ctx = context()
        catalog.describe("query_player", ctx)
        with self.assertRaisesRegex(RuntimeError, "禁止重新进入"):
            await catalog.call("query_player", {}, ctx)
        assert_outside_function()

    async def test_timeout_holds_slot_until_sync_worker_really_finishes(self):
        entered, release = threading.Event(), threading.Event()
        def slow(args, ctx):
            entered.set()
            release.wait(3)
            return FunctionOutput(text="late")
        catalog, handler = self.make_catalog(handler=Mock(side_effect=slow))
        catalog.timeout = 0.03
        ctx = context()
        catalog.describe("query_player", ctx)
        try:
            timed = await catalog.call("query_player", {}, ctx)
            self.assertTrue(entered.is_set())
            self.assertEqual(timed.code, "TOOL_TIMEOUT")
            self.assertEqual((await catalog.call("query_player", {}, ctx)).code, "TOOL_TIMEOUT")
            other = context()
            catalog.describe("query_player", other)
            self.assertEqual((await catalog.call("query_player", {}, other)).code, "FUNCTION_BUSY")
            handler.assert_called_once()
        finally:
            release.set()
            await catalog._running
            await asyncio.sleep(0)
        self.assertFalse(catalog._busy)

    async def test_cancellation_does_not_release_running_sync_slot_or_repeat(self):
        entered, release = threading.Event(), threading.Event()
        def slow(args, ctx):
            entered.set()
            release.wait(3)
            return FunctionOutput()
        catalog, _ = self.make_catalog(handler=slow)
        ctx = context()
        catalog.describe("query_player", ctx)
        task = asyncio.create_task(catalog.call("query_player", {}, ctx))
        try:
            await asyncio.to_thread(entered.wait, 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(catalog._busy)
            self.assertEqual((await catalog.call("query_player", {}, ctx)).code, "FUNCTION_ALREADY_CALLED")
        finally:
            release.set()
            await catalog._running
            await asyncio.sleep(0)

    async def test_write_timeout_is_uncertain_and_not_replayed(self):
        async def slow(args, ctx):
            await asyncio.sleep(0.05)
            return FunctionOutput()
        catalog = FunctionCatalog()
        catalog.timeout = 0.01
        catalog.register(name="update_subscription", description="test", category="test",
            args_model=ValueArgs, handler=slow, effect="write")
        ctx = context()
        catalog.describe("update_subscription", ctx)
        self.assertEqual((await catalog.call("update_subscription", {}, ctx)).code, "OUTCOME_UNKNOWN")
        await catalog._running

    async def test_images_emitted_once_and_paths_never_enter_observation(self):
        catalog, _ = self.make_catalog(handler=Mock(return_value=FunctionOutput(text="图表", images=["/trusted/image.png"])))
        ctx = context()
        catalog.describe("query_player", ctx)
        publish = AsyncMock(return_value={"artifact_id": "opaque", "mime": "image/png"})
        first = await catalog.call("query_player", {}, ctx, publish_image=publish)
        await catalog.call("query_player", {}, ctx, publish_image=publish)
        publish.assert_awaited_once_with("/trusted/image.png", ctx)
        self.assertNotIn("/trusted", json.dumps(first.data))

    async def test_new_function_requires_no_new_tool_definition_and_fails_closed(self):
        catalog, _ = self.make_catalog()
        for name in ("agent_chat", "task_tick", "chat_prepare_reply", "_private", "module.function", "ai_parser"):
            with self.assertRaises(ValueError):
                catalog.register(name=name, description="x", category="x", args_model=ValueArgs, handler=Mock())
        catalog.register(name="future_function", description="扩展", category="future",
            args_model=ValueArgs, handler=Mock(return_value=FunctionOutput(text="new")), scopes=("new.scope",))
        self.assertEqual(catalog.describe("future_function", context()).code, "FUNCTION_UNAVAILABLE")
        ctx = context(scopes=("new.scope",))
        self.assertIn("parameters", catalog.describe("future_function", ctx))
        self.assertEqual((await catalog.call("future_function", {}, ctx)).data["text"], "new")

    async def test_scheduled_agent_uses_same_catalog_and_bound_identity(self):
        catalog, handler = self.make_catalog()
        registry = DiagnosticToolRegistry()
        register_application_tools(registry, service=Capabilities(Mock()), catalogs={})
        register_function_tools(registry, catalog=catalog)
        model = ScriptedModel([
            {"role": "assistant", "content": "", "tool_calls": [call("discover_tools", {"categories": ["hok_business"]}, "d")]},
            {"role": "assistant", "content": "", "tool_calls": [call("describe_hok_function", {"name": "query_player"}, "s")]},
            {"role": "assistant", "content": "", "tool_calls": [call("call_hok_function", {"name": "query_player", "arguments": {"value": 3}}, "c")]},
            {"role": "assistant", "content": "真实结果"},
        ])
        state, output, clock = State(), Sink(), Clock()
        runtime = AgentRuntime(model=model, registry=registry, state=state, output=output, clock=clock)
        bridge = SimpleNamespace(call=AsyncMock(return_value=True))
        scheduler = TaskScheduler(runtime=runtime, bridge=bridge, state=state, output=output,
            clock=clock, prompt_factory=AsyncMock(return_value=""))
        principal = Principal("101", frozenset({"game.read"}), {"delivery": {"platform": "qq", "recipient_id": "200"}})
        await scheduler.perform({"task_id": "t", "lease_token": "l", "session_id": "qq_g_200_101",
            "kind": "agent", "instruction": "查询玩家", "principal": dataclasses.asdict(principal)})
        handler.assert_called_once()
        self.assertEqual(handler.call_args.args[1].principal.user_id, "101")
        self.assertEqual(handler.call_args.args[1].request.metadata["origin"], "background")
        self.assertEqual(output.events[-1]["metadata"]["delivery"]["recipient_id"], "200")
        bridge.call.assert_any_await("task_finish", task_id="t", lease_token="l", failed=False)


class BindingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_catalog_uses_safe_shapes_and_self_identity(self):
        class Functions(dict):
            def __missing__(self, name):
                self[name] = Mock(return_value="text")
                return self[name]
        functions = Functions()
        functions["extract_name"] = lambda name: "player" if name == "有效别名" else None
        catalog = build_hok_function_catalog(functions, player_keys=("player",), player_aliases={"player": ["有效别名"]})
        self.assertEqual(len(catalog.functions), 17)
        ctx = context()
        catalog.describe("heropower_process", ctx)
        self.assertEqual((await catalog.call("heropower_process", {"realname": "invented"}, ctx)).code, "INVALID_ARGUMENTS")
        functions["todayhero_process"].return_value = ("推荐", "依据", "image.png")
        catalog.describe("todayhero_process", ctx)
        result = await catalog.call("todayhero_process", {}, ctx, publish_image=AsyncMock(return_value={"artifact_id": "id"}))
        self.assertTrue(result.ok)
        functions["todayhero_process"].assert_called_once_with(realname="player", ignore_limit=False, ai_comment=False)
        functions["single_process"].return_value = ["战报", ["private"], True, {"params": "private"}, 123]
        catalog.describe("single_process", ctx)
        report = await catalog.call("single_process", {"player": "player"}, ctx)
        self.assertEqual(report.data["text"], "战报")
        self.assertNotIn("private", json.dumps(report.data))
        functions["single_process"].assert_called_once_with(rcv_msg="有效别名战报$")
        await catalog.call("single_process", {"player": "player", "days_ago": 1}, ctx)
        functions["single_process"].assert_called_with(rcv_msg="有效别名战报$1")
