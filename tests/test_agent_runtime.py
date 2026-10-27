"""Contract tests for the independent engine; no SSH/model calls."""

import asyncio
import json
import unittest

from pydantic import BaseModel

from agent_runtime import AgentRuntime, Budget, Principal, RunRequest, ToolRegistry
from agent_runtime.models import ToolContext
from agent_runtime.tools.executor import execute


class State:
    def __init__(self):
        self.events = []
        self.dialogue = []

    async def append_event(self, sid, event):
        self.events.append(event)

    async def load_events(self, sid):
        return self.events

    async def load_dialogue(self, sid):
        return self.dialogue

    async def save_dialogue(self, sid, q, a):
        self.dialogue.extend(
            [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
        )


class Sink:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


class Clock:
    def now(self):
        return "2026-10-13T12:00:00+08:00"

    def monotonic(self):
        return asyncio.get_running_loop().time()


class Args(BaseModel):
    value: int


class ScriptedModel:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []
        self.schemas = []

    async def complete(self, messages, tools, on_delta):
        self.requests.append(json.loads(json.dumps(messages)))
        self.schemas.append(json.loads(json.dumps(tools)))
        return {"message": next(self.replies), "usage": {}}


def call(name, args, call_id="c1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_arbitrary_tool_runs_without_application_tools_or_required_stage(
        self,
    ):
        model = ScriptedModel(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [call("double", {"value": 4})],
                },
                {"role": "assistant", "content": "8"},
            ]
        )
        runtime = AgentRuntime(
            model=model,
            registry=self.registry(),
            state=State(),
            output=Sink(),
            clock=Clock(),
        )
        result = await runtime.run(
            RunRequest("Calculate", "session", Principal("generic-user"))
        )
        self.assertEqual(result["text"], "8")
        self.assertEqual(
            [item["function"]["name"] for item in model.schemas[0]], ["double"]
        )
        instruction = model.requests[0][0]["content"]
        for business_name in [
            "discover_tools",
            "emit_message",
            "search_chat_history",
            "QQ",
            "SQL",
            "memory",
        ]:
            self.assertNotIn(business_name, instruction)

    async def test_tool_owns_result_projection_and_raw_observation_is_retained(self):
        registry = ToolRegistry()
        raw = {"receipt": "r1", "documents": "x" * 10000}

        async def handle(args, ctx):
            return raw

        def project(value, budget):
            value["data"]["documents"] = "preview"
            return value

        registry.register(
            name="documents",
            description="documents",
            args_model=Args,
            handler=handle,
            result_projector=project,
        )
        model = ScriptedModel(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [call("documents", {"value": 0})],
                },
                {"role": "assistant", "content": "done"},
            ]
        )
        state = State()
        runtime = AgentRuntime(
            model=model, registry=registry, state=state, output=Sink(), clock=Clock()
        )
        await runtime.run(
            RunRequest(
                "test",
                "session",
                Principal("user"),
                budget=Budget(observation_chars=500),
            )
        )
        sent = json.loads(
            next(m["content"] for m in model.requests[1] if m["role"] == "tool")
        )
        self.assertEqual(sent["data"], {"receipt": "r1", "documents": "preview"})
        persisted = next(
            e["data"]["result"] for e in state.events if e["kind"] == "tool.result"
        )
        self.assertEqual(len(persisted["data"]["documents"]), 10000)
        self.assertEqual(len(raw["documents"]), 10000)

    def registry(self):
        r = ToolRegistry()

        async def handle(args, ctx):
            return {"value": args.value * 2}

        r.register(
            name="double",
            description="double",
            args_model=Args,
            handler=handle,
            category="external",
        )
        return r

    async def test_all_calls_have_results_and_snapshots_do_not_mutate(self):
        model = ScriptedModel(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        call("double", {"value": 3}),
                        call("missing", {}, "c2"),
                    ],
                },
                {"role": "assistant", "content": "完成"},
            ]
        )
        state = State()
        sink = Sink()
        runtime = AgentRuntime(
            model=model,
            registry=self.registry(),
            state=state,
            output=sink,
            clock=Clock(),
        )
        req = RunRequest(
            "计算", "session", Principal("user"), required_tools=("double",)
        )
        await runtime.run(req)
        observations = [e for e in state.events if e["kind"] == "tool.result"]
        self.assertEqual([e["data"]["call_id"] for e in observations], ["c1", "c2"])
        self.assertTrue(observations[0]["data"]["result"]["ok"])
        self.assertFalse(observations[1]["data"]["result"]["ok"])
        first = next(e for e in state.events if e["kind"] == "model.request")
        self.assertEqual(len(first["data"]["messages"]), 2)
        tool_messages = [m for m in model.requests[1] if m["role"] == "tool"]
        self.assertEqual(len(tool_messages), 2)

    async def test_undisclosed_and_unauthorized_tools_do_not_execute(self):
        executed = []

        async def handle(args, ctx):
            executed.append(True)

        r = ToolRegistry()
        r.register(
            name="private",
            description="private",
            args_model=Args,
            handler=handle,
            scopes={"private"},
        )
        ctx = ToolContext(RunRequest("x", "s", Principal("u")), None)
        result = await execute(r, call("private", {"value": 1}), ctx)
        self.assertEqual(result.code, "UNDISCLOSED_TOOL")
        ctx.disclosed.add("private")
        result = await execute(r, call("private", {"value": 1}), ctx)
        self.assertEqual(result.code, "PERMISSION_DENIED")
        self.assertFalse(executed)

    async def test_multiple_messages_and_final_use_same_output_port(self):
        async def emit(args, ctx):
            await ctx.emit("output.message", {"kind": "partial", "text": "第一条"})
            await ctx.emit("output.message", {"kind": "partial", "text": "第二条"})
            return True

        r = ToolRegistry()
        r.register(name="emit", description="emit", args_model=Args, handler=emit)
        model = ScriptedModel(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [call("emit", {"value": 0})],
                },
                {"role": "assistant", "content": "最终结果"},
            ]
        )
        state = State()
        sink = Sink()
        runtime = AgentRuntime(
            model=model, registry=r, state=state, output=sink, clock=Clock()
        )
        await runtime.run(
            RunRequest("x", "s", Principal("u"), required_tools=("emit",))
        )
        self.assertEqual(
            [e["data"]["text"] for e in sink.events if e["kind"] == "output.message"],
            ["第一条", "第二条", "最终结果"],
        )

    async def test_failure_preserves_trace_and_cancellation_finishes(self):
        class Failing:
            async def complete(self, *args):
                raise RuntimeError("provider down")

        state = State()
        sink = Sink()
        runtime = AgentRuntime(
            model=Failing(),
            registry=self.registry(),
            state=state,
            output=sink,
            clock=Clock(),
        )
        result = await runtime.run(RunRequest("x", "s", Principal("u")))
        self.assertIn("error", result)
        self.assertEqual(state.events[-1]["data"]["status"], "failed")
        self.assertTrue(any(e["kind"] == "model.request" for e in state.events))

    async def test_cancelled_call_and_remaining_calls_have_observations(self):
        started = asyncio.Event()

        async def wait(args, ctx):
            started.set()
            await asyncio.Event().wait()

        registry = ToolRegistry()
        registry.register(
            name="wait", description="wait", args_model=Args, handler=wait
        )
        model = ScriptedModel(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        call("wait", {"value": 1}),
                        call("wait", {"value": 2}, "c2"),
                    ],
                }
            ]
        )
        state = State()
        runtime = AgentRuntime(
            model=model, registry=registry, state=state, output=Sink(), clock=Clock()
        )
        run_id = runtime.submit(
            RunRequest("x", "s", Principal("u"), required_tools=("wait",))
        )
        await started.wait()
        await runtime.cancel(run_id)
        results = [
            event["data"] for event in state.events if event["kind"] == "tool.result"
        ]
        self.assertEqual([item["call_id"] for item in results], ["c1", "c2"])
        self.assertEqual(state.events[-1]["data"]["status"], "cancelled")

    async def test_storage_failure_preserves_answer(self):
        class BrokenState(State):
            async def append_event(self, *args):
                raise RuntimeError("store unavailable")

            async def load_dialogue(self, *args):
                raise RuntimeError("store unavailable")

            async def save_dialogue(self, *args):
                raise RuntimeError("store unavailable")

        sink = Sink()
        model = ScriptedModel([{"role": "assistant", "content": "正常答案"}])
        runtime = AgentRuntime(
            model=model,
            registry=self.registry(),
            state=BrokenState(),
            output=sink,
            clock=Clock(),
        )
        result = await runtime.run(RunRequest("x", "s", Principal("u")))
        self.assertEqual(result["text"], "正常答案")
        self.assertTrue(any(event.get("persistence_error") for event in sink.events))

    async def test_resource_ids_are_isolated_between_runs(self):
        first = ToolContext(RunRequest("x", "s", Principal("u")), None)
        second = ToolContext(RunRequest("x", "s", Principal("u")), None)
        resource_id = first.add_resource({"value": 1})
        with self.assertRaises(ValueError):
            second.resource(resource_id)

    async def test_timed_out_side_effect_is_not_submitted_twice(self):
        submissions = []

        async def slow(args, ctx):
            submissions.append(args.value)
            await asyncio.sleep(1)

        registry = ToolRegistry()
        registry.register(
            name="create",
            description="create",
            args_model=Args,
            handler=slow,
            timeout=0.001,
            effect="external_write",
        )
        context = ToolContext(RunRequest("x", "s", Principal("u")), None)
        context.disclosed.add("create")
        first = await execute(registry, call("create", {"value": 1}), context)
        second = await execute(registry, call("create", {"value": 1}), context)
        self.assertEqual(first.code, "OUTCOME_UNKNOWN")
        self.assertEqual(second.code, "OUTCOME_UNKNOWN")
        self.assertEqual(submissions, [1])


if __name__ == "__main__":
    unittest.main()
