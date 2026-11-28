"""Run lookup binds real receipts and reports overlapping work without invented billing."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from agent_runtime import Principal, RunRequest, ToolRegistry
from agent_runtime.models import ToolContext
from glorybond.agent.local_logs import LocalEventLog
from glorybond.agent.run_costs import model_cost, total_cost
from glorybond.agent.run_history import RunHistory, project_run, load_events
from glorybond.agent.tools.run_history import RunHistoryArgs, register_run_history_tool
from glorybond.storage.agent_run_receipts import record_receipt, lookup_receipt, TTL_SECONDS


def principal(user="11", group="22", bot="33"):
    return Principal(user, attributes={"bot": {"user_id": bot}, "delivery": {
        "platform": "qq", "channel": "group" if group else "private", "recipient_id": group or user}})


def events(run="old", session="qq_g_22_11", user="11", group="22", bot="33"):
    rows = []
    def add(kind, second, **data):
        at = datetime(2026, 11, 29, tzinfo=timezone.utc) + timedelta(seconds=second)
        rows.append({"id": run + str(len(rows)), "kind": kind, "time": at.isoformat(),
                     "run_id": run, "session_id": session, "data": data})
    add("run.start", 0, message="private input")
    rows[0]["metadata"] = {"delivery": principal(user, group, bot).attributes["delivery"],
        "chat_context": {"record": {"user_id": user, "bot_id": bot}}, "reply_question": {"text": "测试问题"}}
    add("model.request", 0, round=1, messages=[{"content": "secret system prompt"}])
    add("model.delta", 1, text="secret reasoning")
    add("model.response", 2, model="deepseek-flash", provider_host="api.deepseek.com",
        usage={"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100,
               "prompt_cache_hit_tokens": 200, "completion_tokens_details": {"reasoning_tokens": 80}})
    add("tool.call", 2, round=1, id="a", function={"name": "read_image", "arguments": "secret URL"})
    add("tool.call", 2, round=1, id="b", function={"name": "read_media", "arguments": "secret path"})
    add("tool.result", 7, call_id="a", name="read_image", duration=3,
        result={"ok": True, "data": {"description": "private image text", "cached": False,
            "model": "doubao-seed-2-1-pro-260628", "usage": {"prompt_tokens": 100, "completion_tokens": 10}}})
    add("tool.result", 7.1, call_id="b", name="read_media", duration=5,
        result={"ok": True, "data": {"cache_hit": True, "model_usage": {"total_tokens": 9999},
                                    "new_model_usage": {}, "new_asr_seconds": 0}})
    add("reply.model.request", 8, attempt=1)
    add("reply.model.response", 9, model="deepseek-flash", usage={"prompt_tokens": 50, "completion_tokens": 20})
    add("run.end", 10, status="completed", duration=10)
    return rows


class ProjectionTests(unittest.TestCase):
    def test_parallel_latency_and_nested_model_usage_are_not_double_counted(self):
        report = project_run(events())
        summary = report["summary"]
        self.assertEqual(summary["tool_work_seconds"], 8)
        self.assertEqual(summary["tool_wall_seconds"], 5)
        self.assertEqual(summary["model_seconds"], 3)
        self.assertEqual(summary["usage"]["prompt_tokens"], 1150)
        self.assertEqual(summary["usage"]["completion_tokens"], 130)
        self.assertEqual(summary["usage"]["total_tokens"], 1100)
        self.assertEqual(summary["usage_counter_calls"]["total_tokens"], 1)
        self.assertEqual(summary["usage"]["reasoning_tokens"], 80)
        self.assertEqual(report["models"][0]["first_token_seconds"], 1)
        self.assertNotIn("private image text", json.dumps(report))
        self.assertNotIn("secret", json.dumps(report))
        self.assertEqual(report["tools"][1]["new_asr_seconds"], 0)

    def test_failed_missing_response_and_unpriced_tools_are_partial(self):
        rows = events()[:2]
        rows += [{**rows[0], "id": "fail", "kind": "run.end", "data": {"status": "cancelled"}}]
        result = project_run(rows)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(result["cost"]["coverage"], "partial")
        self.assertEqual(result["summary"]["usage_missing_calls"], 1)

    def test_prices_preserve_cache_subsets_and_unknown_providers(self):
        usage = {"prompt_tokens": 1000000, "completion_tokens": 1000000, "prompt_cache_hit_tokens": 1000000}
        cost = model_cost("deepseek-flash", usage, at="2026-11-29T10:00:00+08:00")
        self.assertEqual((cost["min"], cost["max"]), (4.02, 4.02))
        peak = model_cost("deepseek-flash", usage, at="2026-11-30T10:00:00+08:00")
        self.assertEqual(peak["max"], 8.04)
        unknown = model_cost("deepseek-flash", usage, provider_host="other.example")
        self.assertEqual(unknown["kind"], "unknown")
        reported = model_cost("unknown", {}, raw_usage={"cost": .3, "cost_currency": "USD"})
        self.assertEqual(reported["kind"], "reported")
        totals = total_cost([cost, unknown, reported])
        self.assertEqual(set(totals["currencies"]), {"CNY", "USD"})
        self.assertEqual(totals["coverage"], "partial")

    def test_media_only_new_usage_and_asr_are_billed(self):
        rows = events()
        rows[7]["data"]["result"]["data"].update(cache_hit=False, model="deepseek-flash",
            new_model_usage={"prompt_tokens": 20, "completion_tokens": 5}, new_asr_seconds=120)
        report = project_run(rows)
        self.assertEqual(report["summary"]["usage"]["prompt_tokens"], 1170)
        self.assertEqual(report["tools"][1]["asr_cost"]["min"], .013)


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = LocalEventLog(self.tmp.name)
        self.bridge = SimpleNamespace(call=AsyncMock())
        self.history = RunHistory(self.log, self.bridge)

    def context(self, *, owner=None, session="qq_g_22_11", quote=None):
        return ToolContext(RunRequest("查询运行", session, owner or principal(), run_id="current",
            metadata={"chat_context": {"record": quote or {}}}), AsyncMock())

    async def test_quote_resolves_other_requester_same_group_exactly(self):
        await self.log.record_many(events(session="qq_g_22_44", user="44"))
        self.bridge.call.return_value = {"run_id": "old", "session_id": "qq_g_22_44"}
        result = await self.history.read(RunHistoryArgs(), self.context(quote={"quote_sender_id": "33", "quote_message_id": "55"}))
        self.assertEqual(result["runs"][0]["requester_id"], "44")
        self.assertEqual(result["message_id"], "55")
        self.bridge.call.assert_awaited_once()

    async def test_missing_quote_mapping_never_substitutes_latest(self):
        await self.log.record_many(events())
        self.bridge.call.return_value = None
        result = await self.history.read(RunHistoryArgs(), self.context(quote={"quote_sender_id": "33", "quote_message_id": "55"}))
        self.assertFalse(result["matched"])
        self.assertEqual(result["runs"], [])

    async def test_non_bot_quote_is_not_used_and_current_run_is_excluded(self):
        await self.log.record_many(events())
        await self.log.record_many(events(run="current"))
        result = await self.history.read(RunHistoryArgs(), self.context(quote={"quote_sender_id": "44", "quote_message_id": "55"}))
        self.assertEqual(result["runs"][0]["run_id"], "old")
        self.bridge.call.assert_not_called()

    async def test_cross_group_private_and_other_bot_remain_inaccessible(self):
        for owner, session, data in [
            (principal(), "qq_g_99_11", events(session="qq_g_99_11", group="99")),
            (principal(group=None), "qq_p_44", events(session="qq_p_44", user="44", group=None)),
            (principal(), "qq_g_22_11", events(bot="66")),
        ]:
            with self.subTest(session=session):
                await self.log.record_many(data)
                self.bridge.call.return_value = {"run_id": "old", "session_id": session}
                result = await self.history.read(RunHistoryArgs(message_id="55"), self.context(owner=owner))
                self.assertFalse(result["matched"])

    async def test_console_requires_same_session_and_owner(self):
        data = events(session="console")
        data[0]["metadata"].pop("delivery")
        await self.log.record_many(data)
        ctx = self.context(owner=Principal("11"), session="console")
        self.assertTrue((await self.history.read(RunHistoryArgs(run_id="old"), ctx))["matched"])
        ctx = self.context(owner=Principal("44"), session="console")
        self.assertFalse((await self.history.read(RunHistoryArgs(run_id="old"), ctx))["matched"])

    async def test_group_run_identifier_and_symlink_boundary(self):
        await self.log.record_many(events(session="qq_g_22_44", user="44"))
        result = await self.history.read(RunHistoryArgs(run_id="old"), self.context())
        self.assertEqual(result["runs"][0]["requester_id"], "44")
        with self.assertRaises(ValueError):
            RunHistoryArgs(run_id="../../outside")
        with self.assertRaises(ValueError):
            RunHistoryArgs(run_id="old", message_id="1")
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "escape.jsonl"
            target.write_text("\n".join(json.dumps(row) for row in events(run="escape")))
            directory = Path(self.tmp.name) / "qq_g_22_11/runs"
            directory.mkdir(parents=True)
            (directory / "escape.jsonl").symlink_to(target)
            self.assertFalse((await self.history.read(RunHistoryArgs(run_id="escape"), self.context()))["matched"])

    async def test_torn_lines_and_duplicates_report_partial_without_content(self):
        await self.log.record_many(events())
        path = Path(self.tmp.name) / "qq_g_22_11/runs/old.jsonl"
        with path.open("a") as handle:
            handle.write(json.dumps(events()[3]) + "\n{torn\n")
        loaded, malformed = load_events(path)
        self.assertEqual(malformed, 1)
        self.assertNotIn("secret", json.dumps(loaded))
        result = await self.history.read(RunHistoryArgs(), self.context())
        self.assertEqual(result["runs"][0]["cost"]["coverage"], "partial")
        self.assertEqual(result["runs"][0]["summary"]["model_calls"], 2)

    async def test_oversized_journal_or_line_is_rejected(self):
        await self.log.record_many(events())
        path = Path(self.tmp.name) / "qq_g_22_11/runs/old.jsonl"
        with patch("glorybond.agent.run_history.MAX_FILE_BYTES", 32):
            with self.assertRaisesRegex(ValueError, "上限"):
                load_events(path)
        with patch("glorybond.agent.run_history.MAX_LINE_BYTES", 32):
            with self.assertRaisesRegex(ValueError, "上限"):
                load_events(path)

    async def test_tool_is_discovered_normally(self):
        registry = ToolRegistry()
        register_run_history_tool(registry, log=self.log, bridge=self.bridge)
        spec = registry.tools["read_run_history"]
        self.assertFalse(spec.initially_visible)
        self.assertEqual(spec.effect, "read")
        await self.log.record_many(events())
        result = await spec.handler(RunHistoryArgs(), self.context())
        self.assertTrue(result["matched"])

    async def test_runtime_discovers_and_reads_quote_without_prompt_special_case(self):
        from agent_runtime import AgentRuntime
        from glorybond.agent.tools.application import register_application_tools
        from tests.test_agent_runtime import ScriptedModel, State, Sink, Clock, call
        await self.log.record_many(events())
        self.bridge.call.return_value = {"run_id": "old", "session_id": "qq_g_22_11"}
        registry = ToolRegistry()
        register_application_tools(registry, service=SimpleNamespace(), catalogs={})
        register_run_history_tool(registry, log=self.log, bridge=self.bridge)
        model = ScriptedModel([
            {"role": "assistant", "content": "", "tool_calls": [call("discover_tools", {"categories": ["run_history"]}, "discover")]},
            {"role": "assistant", "content": "", "tool_calls": [call("read_run_history", {}, "inspect")]},
            {"role": "assistant", "content": "这次运行10秒，并发工具共经过5秒。"},
        ])
        request = self.context(quote={"quote_sender_id": "33", "quote_message_id": "55"}).request
        runtime = AgentRuntime(model=model, registry=registry, state=State(), output=Sink(), clock=Clock())
        result = await runtime.run(request)
        self.assertIn("10秒", result["text"])
        self.assertNotIn("read_run_history", [item["function"]["name"] for item in model.schemas[0]])
        self.assertIn("read_run_history", [item["function"]["name"] for item in model.schemas[1]])
        observed = json.loads(next(item["content"] for item in model.requests[-1] if item.get("tool_call_id") == "inspect"))
        self.assertEqual(observed["data"]["runs"][0]["run_id"], "old")


class ReceiptTests(unittest.TestCase):
    def test_receipt_key_includes_bot_channel_and_target_and_fixed_expiry(self):
        store = Mock()
        record_receipt(bot_id="33", channel="group", recipient_id="22", message_id="-55",
                       run_id="old", session_id="qq_g_22_11", store=store)
        self.assertEqual(store.set.call_args.kwargs, {"ex": TTL_SECONDS, "nx": True})
        key, value = store.set.call_args.args
        store.get.return_value = value
        owner = principal()
        result = lookup_receipt(store, principal={"user_id": owner.user_id, "attributes": owner.attributes}, message_id="-55")
        self.assertEqual(store.get.call_args.args[0], key)
        self.assertEqual(result["run_id"], "old")

    def test_private_recipient_cannot_be_rebound(self):
        owner = principal(group=None)
        owner.attributes["delivery"]["recipient_id"] = "44"
        with self.assertRaises(PermissionError):
            lookup_receipt(Mock(), principal={"user_id": owner.user_id, "attributes": owner.attributes}, message_id="55")
