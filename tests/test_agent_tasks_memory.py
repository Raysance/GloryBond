"""Regression coverage for undiscovered personal tools and scheduled delivery."""

import dataclasses
from datetime import datetime
import json
import unittest

from agent_runtime import AgentRuntime, Principal, RunRequest, ToolRegistry
from agent_console.capabilities import Capabilities, chat_required_tools
from agent_console.task_timing import normalized_task_action, next_task_time
from agent_console.tasks import TaskScheduler
from agent_console.tools.application import TaskArgs, register_application_tools
from tests.test_agent_runtime import Clock, ScriptedModel, Sink, State, call


class TimingTests(unittest.TestCase):
    def test_absolute_time_avoids_model_delay_arithmetic_and_anchors_daily_cadence(self):
        now = datetime.fromisoformat("2026-10-15T21:27:16+08:00").timestamp()
        for run_at in ("2026-10-15T21:30:00+08:00", "2026-10-15T13:30:00Z"):
            with self.subTest(run_at=run_at):
                args = TaskArgs(kind="message", message="打王者", run_at=run_at,
                                interval_seconds=86400, max_runs=365)
                task = normalized_task_action(args.model_dump(), now)
                self.assertEqual(task["next_run_at"] - now, 164)
                self.assertEqual(next_task_time(task, task["next_run_at"] + 2),
                                 datetime.fromisoformat("2026-10-16T21:30:00+08:00").timestamp())

    def test_absolute_and_relative_start_times_are_mutually_exclusive(self):
        args = {"kind": "message", "message": "x", "run_at": "2026-10-15T21:30:00+08:00", "delay_seconds": 0}
        with self.assertRaisesRegex(ValueError, "只能选择一种"):
            TaskArgs(**args)
        with self.assertRaisesRegex(ValueError, "只能选择一种"):
            normalized_task_action(args, 100)

    def test_invalid_naive_past_and_too_distant_dates_are_rejected(self):
        now = datetime.fromisoformat("2026-10-15T21:30:00+08:00").timestamp()
        for run_at in ("21:30", "2026-10-15", "2026-10-15T21:30:00", "2026-02-30T21:30:00+08:00",
                       "2026-10-15T21:29:59+08:00", "2026-10-15T21:30:00+08:00", "2028-10-15T21:30:00+08:00"):
            with self.subTest(run_at=run_at), self.assertRaises(ValueError):
                normalized_task_action({"kind": "message", "message": "x", "run_at": run_at}, now)

    def test_ten_second_three_delivery_request_is_supported(self):
        args = TaskArgs(
            kind="message", message="第{run}条消息", interval_seconds=10, max_runs=3
        )
        record = normalized_task_action(args.model_dump(), 100)
        self.assertEqual(record["next_run_at"], 110)
        self.assertEqual(next_task_time(record, 111.5), 120)
        self.assertEqual(record["max_runs"], 3)

    def test_slow_execution_skips_missed_ticks_without_changing_cadence(self):
        record = {"interval_seconds": 10, "next_run_at": 110}
        self.assertEqual(next_task_time(record, 135), 140)

    def test_invalid_actions_do_not_reach_storage(self):
        for args in [
            {"kind": "message"},
            {"kind": "agent"},
            {"kind": "message", "message": "x", "interval_seconds": 0},
            {"kind": "message", "message": "x", "max_runs": 3},
        ]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                normalized_task_action(args, 100)


class PersonalCapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_early_refusal_cannot_skip_discovery_and_bound_memory_write(self):
        class Bridge:
            def __init__(self):
                self.memories = {}

            async def call(self, op, **args):
                if op == "search_history":
                    return {"messages": []}
                if op == "memory":
                    self.memories[args["user_id"]] = args["content"]
                    return {"saved": True, "memory": {"content": args["content"]}}
                raise AssertionError(op)

        data_bridge, state_bridge = Bridge(), Bridge()
        registry = ToolRegistry()
        register_application_tools(
            registry, service=Capabilities(data_bridge, state_bridge), catalogs={}
        )
        model = ScriptedModel(
            [
                {"role": "assistant", "content": "没有记忆能力"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        call("search_chat_history", {"queries": ["偏好", "英雄"]}, "h")
                    ],
                },
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        call("discover_tools", {"categories": ["memory"]}, "d")
                    ],
                },
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        call("remember_memory", {"content": "喜欢玩安琪拉"}, "m")
                    ],
                },
                {"role": "assistant", "content": "已记住"},
            ]
        )
        state = State()
        runtime = AgentRuntime(
            model=model, registry=registry, state=state, output=Sink(), clock=Clock()
        )
        principal = Principal("local-ui:caller", frozenset({"chat.read", "memory.use"}))
        await runtime.run(
            RunRequest(
                "你需要记住我喜欢玩安琪拉",
                "s",
                principal,
                required_tools=chat_required_tools(),
            )
        )
        self.assertEqual(state_bridge.memories, {"local-ui:caller": "喜欢玩安琪拉"})
        self.assertEqual(data_bridge.memories, {})
        replies = [
            e["data"]["text"] for e in state.events if e["kind"] == "output.message"
        ]
        self.assertEqual(replies, ["已记住"])
        self.assertIn(
            "remember_memory", [item["function"]["name"] for item in model.schemas[-1]]
        )

    async def test_fixed_delivery_runs_while_foreground_model_is_busy(self):
        class BusyRuntime:
            active = {"foreground": object()}

            def submit(self, request):
                raise AssertionError("Fixed deliveries must not request a model")

        class Bridge:
            def __init__(self):
                self.finished = []

            async def call(self, op, **args):
                if op == "task_active":
                    return True
                if op == "task_finish":
                    self.finished.append(args)
                    return True
                raise AssertionError(op)

        async def prompt():
            raise AssertionError("Fixed deliveries need no model context")

        bridge, state, output = Bridge(), State(), Sink()
        scheduler = TaskScheduler(
            runtime=BusyRuntime(),
            bridge=bridge,
            state=state,
            output=output,
            clock=Clock(),
            prompt_factory=prompt,
        )
        principal = dataclasses.asdict(Principal("caller"))
        for index in range(3):
            await scheduler.perform(
                {
                    "task_id": "task",
                    "lease_token": str(index),
                    "kind": "message",
                    "message": "第{run}/{max_runs}条",
                    "runs": index,
                    "max_runs": 3,
                    "principal": principal,
                    "session_id": "s",
                }
            )
        messages = [e for e in output.events if e["kind"] == "output.message"]
        self.assertEqual(
            [e["data"]["text"] for e in messages], ["第1/3条", "第2/3条", "第3/3条"]
        )
        self.assertTrue(all(e["metadata"]["origin"] == "background" for e in messages))
        self.assertEqual(len(bridge.finished), 3)
        self.assertFalse(scheduler.active_run_ids)
        self.assertFalse(any(e["kind"] == "model.request" for e in output.events))

    async def test_cancelled_task_publishes_no_message(self):
        class Bridge:
            async def call(self, op, **args):
                self_case.assertEqual(op, "task_active")
                return False

        self_case = self
        output = Sink()
        scheduler = TaskScheduler(
            runtime=None,
            bridge=Bridge(),
            state=State(),
            output=output,
            clock=Clock(),
            prompt_factory=None,
        )
        await scheduler.perform({"task_id": "cancelled", "lease_token": "lease"})
        self.assertEqual(output.events, [])


if __name__ == "__main__":
    unittest.main()
