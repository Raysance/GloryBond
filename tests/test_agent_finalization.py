"""The runtime accepts presentation hooks without knowing their channel or style."""

import asyncio
import unittest

from agent_runtime import AgentRuntime, FinalAnswer, Principal, RunRequest, ToolRegistry
from tests.test_agent_runtime import Clock, ScriptedModel, Sink, State


class FinalizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_delivery_variants_and_context_remain_caller_owned(self):
        captured = []

        class Finalizer:
            async def finalize(self, context, emit):
                captured.append(context)
                context.messages[0]["content"] = "changed copy"
                await emit("custom.presentation", {"ready": True})
                return FinalAnswer(
                    "compact",
                    variants={"long": "expanded", "short": "compact"},
                    metadata={"format": "custom"},
                    history_text="expanded context",
                )

        model = ScriptedModel([{"role": "assistant", "content": "draft"}])
        state, sink = State(), Sink()
        runtime = AgentRuntime(
            model=model,
            registry=ToolRegistry(),
            state=state,
            output=sink,
            clock=Clock(),
            finalizer=Finalizer(),
        )
        request = RunRequest("question", "s", Principal("u"))
        result = await runtime.run(request)
        self.assertEqual(result["text"], "compact")
        self.assertEqual(result["variants"], {"long": "expanded", "short": "compact"})
        self.assertEqual(captured[0].draft, "draft")
        self.assertEqual(captured[0].request.principal.user_id, "u")
        self.assertEqual(state.dialogue[-1]["content"], "expanded context")
        message = next(e["data"] for e in sink.events if e["kind"] == "output.message")
        self.assertEqual(message["variants"]["short"], message["text"])
        self.assertEqual(message["presentation"], {"format": "custom"})
        original = next(e for e in state.events if e["kind"] == "model.request")
        self.assertNotEqual(original["data"]["messages"][0]["content"], "changed copy")

    async def test_failed_finalizer_preserves_successful_task_answer(self):
        class Broken:
            async def finalize(self, context, emit):
                raise RuntimeError("presentation unavailable")

        state, sink = State(), Sink()
        runtime = AgentRuntime(
            model=ScriptedModel([{"role": "assistant", "content": "verified answer"}]),
            registry=ToolRegistry(),
            state=state,
            output=sink,
            clock=Clock(),
            finalizer=Broken(),
        )
        result = await runtime.run(RunRequest("question", "s", Principal("u")))
        self.assertEqual(result["text"], "verified answer")
        self.assertEqual(state.dialogue[-1]["content"], result["text"])
        self.assertTrue(any(e["kind"] == "run.warning" for e in sink.events))
        self.assertEqual(sum(e["kind"] == "output.message" for e in sink.events), 1)
        self.assertEqual(sink.events[-1]["data"]["status"], "completed")

    async def test_cancellation_during_finalization_does_not_publish_or_save(self):
        started = asyncio.Event()

        class Pending:
            async def finalize(self, context, emit):
                started.set()
                await asyncio.Event().wait()

        state, sink = State(), Sink()
        runtime = AgentRuntime(
            model=ScriptedModel([{"role": "assistant", "content": "draft"}]),
            registry=ToolRegistry(),
            state=state,
            output=sink,
            clock=Clock(),
            finalizer=Pending(),
        )
        run_id = runtime.submit(RunRequest("question", "s", Principal("u")))
        await started.wait()
        self.assertTrue(await runtime.cancel(run_id))
        self.assertFalse(state.dialogue)
        self.assertFalse(any(e["kind"] == "output.message" for e in sink.events))
        self.assertEqual(sink.events[-1]["data"]["status"], "cancelled")
        self.assertTrue(any(e["kind"] == "model.response" for e in sink.events))


if __name__ == "__main__":
    unittest.main()
