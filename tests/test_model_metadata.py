"""Model-visible facts follow real calls, delivery stages and run boundaries."""

import asyncio
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from agent_runtime import AgentRuntime, Principal, RunRequest, ToolRegistry
from agent_console.model_metadata import model_metadata, observe_model_event
from agent_console.provider import DeepSeekModel
from agent_console.replies import ReplyComposer
from agent_console.server import EventBroker
from qq_agent.output import QQOutput
from tests.test_agent_replies import Roles
from tests.test_agent_roleplay import BUILTINS
from tests.test_agent_runtime import Args, Clock, State


def metadata(payload):
    return json.loads(payload["messages"][0]["content"].splitlines()[-1])["runtime_metadata"]


def stream(*, text="完成", usage=None, tool=False, model="actual-backend"):
    delta = {"content": text}
    if tool:
        delta = {"tool_calls": [{"index": 0, "id": "call-1", "type": "function",
                  "function": {"name": "double", "arguments": '{"value":4}'}}]}
    frame = {"model": model, "choices": [{"delta": delta, "finish_reason": "tool_calls" if tool else "stop"}]}
    if usage is not None:
        frame["usage"] = usage
    return httpx.Response(200, text="data: " + json.dumps(frame) + "\n\ndata: [DONE]\n\n")


class ModelMetadataTests(unittest.IsolatedAsyncioTestCase):
    def provider(self, **overrides):
        return DeepSeekModel(api_key="PRIVATE_MODEL_KEY", base_url="https://primary.invalid",
                             model="configured-model", **overrides)

    def transport(self, handler):
        original = httpx.AsyncClient
        return patch("agent_console.provider.httpx.AsyncClient", side_effect=lambda **kw: original(
            transport=httpx.MockTransport(handler), **kw))

    def runtime(self, *, finalizer=None):
        async def double(args, ctx):
            return {"value": args.value * 2}
        registry = ToolRegistry()
        registry.register(name="double", description="Double a number", args_model=Args, handler=double)
        state = State()
        broker = EventBroker(type("Bridge", (), {"redact": staticmethod(lambda value: value)})())
        return AgentRuntime(model=self.provider(), registry=registry, state=state, output=broker,
                            clock=Clock(), finalizer=finalizer), state

    async def test_usage_reaches_following_round_and_reply_without_entering_dialogue(self):
        requests = []
        usages = [
            {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110,
             "prompt_cache_hit_tokens": 60, "prompt_cache_miss_tokens": 40,
             "completion_tokens_details": {"reasoning_tokens": 4}},
            {"prompt_tokens": 120, "completion_tokens": 20, "total_tokens": 140},
            {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
        ]
        def respond(request):
            body = json.loads(request.content)
            requests.append(body)
            index = len(requests) - 1
            return stream(text=json.dumps({"chat": "结果为8。"}) if index == 2 else "结果为8。",
                          usage=usages[index], tool=index == 0)
        assistant = next(role for role in BUILTINS if role["role_id"] == "assistant")
        runtime, state = self.runtime(finalizer=ReplyComposer(model=self.provider(), roles=Roles(assistant)))
        request = RunRequest("算出结果", "session", Principal("owner", frozenset({"roleplay.use"})),
                             required_tools=("double",), system_prompt="保持事实准确")
        with self.transport(respond):
            result = await runtime.run(request)
        first, second, reply = [metadata(body) for body in requests]
        self.assertIsNone(first["run"]["cumulative_usage"])
        self.assertEqual(second["run"]["cumulative_usage"]["total_tokens"], 110)
        self.assertEqual(second["run"]["cumulative_usage"]["reasoning_tokens"], 4)
        self.assertEqual(second["run"]["tool_calls"], 1)
        self.assertEqual(second["run"]["last_response"]["model"], "actual-backend")
        self.assertEqual(reply["run"]["phase"], "reply")
        self.assertEqual(reply["run"]["cumulative_usage"]["total_tokens"], 250)
        self.assertEqual(reply["run"]["usage_counter_calls"]["total_tokens"], 2)
        self.assertEqual(result["text"], "结果为8。")
        self.assertNotIn("runtime_metadata", json.dumps(state.dialogue))
        self.assertEqual(request.system_prompt, "保持事实准确")
        self.assertTrue(all(body["messages"][0]["content"].count('"runtime_metadata"') == 1 for body in requests))
        self.assertIsNone(model_metadata(model="next", protocol="deepseek", max_tokens=10, messages=[], tools=[])["run"])

    async def test_concurrent_runs_keep_separate_usage_and_origins(self):
        requests, counts = {}, {}
        both_started = asyncio.Event()
        async def respond(request):
            body = json.loads(request.content)
            label = next(message["content"] for message in body["messages"] if message["role"] == "user")
            counts[label] = counts.get(label, 0) + 1
            requests.setdefault(label, []).append(metadata(body))
            if sum(len(values) > 0 for values in requests.values()) == 2:
                both_started.set()
            await both_started.wait()
            return stream(tool=counts[label] == 1, usage={"total_tokens": 33 if label == "alpha" else 77})
        runtime, _ = self.runtime()
        with self.transport(respond):
            await asyncio.gather(*(runtime.run(RunRequest(label, label, Principal(label),
                required_tools=("double",), metadata={"origin": "background" if label == "beta" else "foreground"}))
                for label in ("alpha", "beta")))
        self.assertNotEqual(requests["alpha"][0]["run"]["run_id"], requests["beta"][0]["run"]["run_id"])
        for label, total in (("alpha", 33), ("beta", 77)):
            self.assertIsNone(requests[label][0]["run"]["cumulative_usage"])
            self.assertEqual(requests[label][1]["run"]["cumulative_usage"], {"total_tokens": total})
        self.assertEqual(requests["beta"][1]["run"]["origin"], "background")

    async def test_failover_vision_uses_selected_model_and_keeps_original_input(self):
        bodies = []
        def respond(request):
            bodies.append(json.loads(request.content))
            if request.url.host == "primary.invalid":
                return httpx.Response(503)
            return stream(model="reported-vision-backend")
        messages = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,test"}}]}]
        before = copy.deepcopy(messages)
        provider = self.provider(vision_model="primary-vision", fallback={
            "api_key": "PRIVATE_BACKUP_KEY", "base_url": "https://backup.invalid", "model": "fallback-text",
            "vision_model": "fallback-vision", "protocol": "bailian_kimi"})
        with self.transport(respond):
            result = await provider.complete(messages, [], AsyncMock())
        self.assertEqual(messages, before)
        self.assertEqual(metadata(bodies[0])["model"], "primary-vision")
        self.assertEqual(metadata(bodies[1])["model"], "fallback-vision")
        self.assertEqual(metadata(bodies[1])["message_count"], len(bodies[1]["messages"]))
        self.assertEqual(result["model"], "reported-vision-backend")
        self.assertEqual(bodies[1]["messages"][1:], messages)
        self.assertNotIn("PRIVATE_", json.dumps(result))

    async def test_missing_usage_is_unknown_and_private_event_fields_are_excluded(self):
        def event(kind, data=None):
            observe_model_event({"kind": kind, "run_id": "run-test", "time": Clock().now(),
                "data": data or {}, "metadata": {"api_key": "PRIVATE_KEY", "principal": "PRIVATE_PRINCIPAL",
                    "delivery": {"platform": "qq", "channel": "group", "recipient_id": "PRIVATE_GROUP"}}})
        event("run.start")
        event("model.response", {"model": "actual", "usage": {"total_tokens": None, "prompt_tokens": -1,
              "completion_tokens": True, "provider_secret": "PRIVATE_SECRET"}})
        info = model_metadata(model="current", protocol="deepseek", max_tokens=64, messages=[], tools=[])
        self.assertIsNone(info["run"]["cumulative_usage"])
        self.assertIsNone(info["run"]["last_response"]["usage"])
        self.assertEqual(info["run"]["usage_missing_calls"], 1)
        self.assertEqual(info["run"]["channel"], "qq_group")
        self.assertNotIn("PRIVATE_", json.dumps(info))
        event("roleplay.model.response", {"usage": {"total_tokens": 0}})
        info = model_metadata(model="current", protocol="deepseek", max_tokens=64, messages=[], tools=[])
        self.assertEqual(info["run"]["cumulative_usage"], {"total_tokens": 0})
        self.assertEqual(info["run"]["usage_reported_calls"], 1)
        event("run.end")

    async def test_failed_and_cancelled_runs_release_metadata(self):
        for error in (httpx.ConnectError("unavailable"), asyncio.CancelledError()):
            with self.subTest(error=type(error).__name__):
                runtime, _ = self.runtime()
                def respond(request):
                    raise error
                with self.transport(respond):
                    try:
                        await runtime.run(RunRequest("test", "session", Principal("owner")))
                    except asyncio.CancelledError:
                        pass
                self.assertIsNone(model_metadata(model="next", protocol="deepseek", max_tokens=10, messages=[], tools=[])["run"])

    async def test_qq_publisher_tracks_group_context_and_clears_after_cancel(self):
        sender = AsyncMock()
        output = QQOutput(bridge=SimpleNamespace(redact=lambda value: value),
            local_log=SimpleNamespace(record=AsyncMock()), sender=sender,
            prepare_reply=AsyncMock(side_effect=lambda packet: packet), store_artifact=AsyncMock())
        def event(kind, data):
            return {"id": kind, "kind": kind, "data": data, "run_id": "qq-run", "session_id": "qq-session",
                    "time": Clock().now(), "metadata": {"delivery": {
                        "platform": "qq", "channel": "group", "recipient_id": "123"}}}
        await output.publish(event("run.start", {"message": "test"}))
        await output.publish(event("model.response", {"model": "actual", "usage": {"total_tokens": 7}}))
        info = model_metadata(model="current", protocol="deepseek", max_tokens=10, messages=[], tools=[])
        self.assertEqual(info["run"]["channel"], "qq_group")
        self.assertEqual(info["run"]["cumulative_usage"], {"total_tokens": 7})
        await output.publish(event("run.end", {"status": "cancelled"}))
        self.assertIsNone(model_metadata(model="next", protocol="deepseek", max_tokens=10, messages=[], tools=[])["run"])
        sender.assert_not_awaited()
