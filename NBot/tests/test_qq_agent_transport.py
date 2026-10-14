"""Provider protocol and independent scheduled delivery queues."""
import json
import unittest
from unittest.mock import patch

import httpx

from agent_runtime import ModelRequest
from agent_console.provider import DeepSeekModel
from agent_console import remote_worker as worker
from agent_console.task_timing import normalized_task_action, next_task_time


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_required_choice_and_tool_chain_never_switch_thinking_modes(self):
        requests, options = [], []
        original = httpx.AsyncClient

        def respond(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}],"usage":{"total_tokens":1}}\n\ndata: [DONE]\n\n')

        def client(**kwargs):
            options.append(kwargs)
            return original(transport=httpx.MockTransport(respond), **kwargs)

        async def delta(*args):
            pass

        model = DeepSeekModel(api_key="secret", base_url="https://example.invalid", model="test", thinking=True)
        tools = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]
        forced = {"type": "function", "function": {"name": "lookup"}}
        with patch("agent_console.provider.httpx.AsyncClient", side_effect=client):
            await model.complete_request(ModelRequest([{"role": "user", "content": "hi"}], tools, forced), delta)
            chain = [{"role": "assistant", "tool_calls": [{"id": "call"}]}]
            await model.complete_request(ModelRequest(chain, tools, "auto"), delta)
            result = await model.complete_request(ModelRequest(chain, [], "none"), delta)
            await model.complete_request(ModelRequest([{"role": "user", "content": "hi"}], [], "none"), delta)
        self.assertEqual(requests[0]["tool_choice"], forced)
        self.assertEqual([r["thinking"]["type"] for r in requests], ["disabled", "disabled", "disabled", "enabled"])
        self.assertNotIn("tools", requests[2])
        self.assertTrue(all(o["trust_env"] is False for o in options))
        self.assertNotIn("secret", json.dumps(result))


class Store:
    def __init__(self):
        self.values, self.indexes = {}, {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def zadd(self, key, values):
        self.indexes.setdefault(key, {}).update(values)

    def zrem(self, key, member):
        self.indexes.setdefault(key, {}).pop(member, None)

    def zrangebyscore(self, key, low, high, *, start, num):
        return [k for k, v in sorted(self.indexes.get(key, {}).items(), key=lambda p: p[1]) if low <= v <= high][start:start + num]

    def pipeline(self, **kwargs):
        return Pipeline(self)


class Pipeline:
    def __init__(self, store):
        self.store, self.pending = store, []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def watch(self, *args):
        pass

    def multi(self):
        pass

    def get(self, key):
        return self.store.get(key)

    def set(self, *args):
        self.pending.append(("set", args))

    def zadd(self, *args):
        self.pending.append(("zadd", args))

    def zrem(self, *args):
        self.pending.append(("zrem", args))

    def execute(self):
        for name, args in self.pending:
            getattr(self.store, name)(*args)
        self.pending.clear()


class TaskQueueTests(unittest.TestCase):
    def test_console_backlog_does_not_steal_or_starve_qq_and_finish_reschedules_same_channel(self):
        store = Store()
        with patch.dict(worker.CONTEXT, store=store, task_timing={"normalized_task_action": normalized_task_action, "next_task_time": next_task_time}), patch.object(worker.time, "time", return_value=100):
            for number in range(6):
                worker.dispatch({"op": "task_create", "session_id": f"web_{number}", "principal": {"user_id": "u"},
                                 "kind": "message", "message": "web", "delay_seconds": 0})
            qq = worker.dispatch({"op": "task_create", "session_id": "qq_g_200_101",
                                  "principal": {"user_id": "101", "attributes": {"delivery": {"platform": "qq"}}},
                                  "kind": "message", "message": "qq", "interval_seconds": 10, "delay_seconds": 0, "max_runs": 3})
            due = worker.dispatch({"op": "task_due", "channel": "qq"})
            self.assertEqual([t["task_id"] for t in due], [qq["task_id"]])
            self.assertEqual(worker.dispatch({"op": "task_due", "channel": "qq"}), [])
            web = worker.dispatch({"op": "task_due"})
            self.assertEqual(len(web), 4)
            self.assertNotIn(qq["task_id"], [t["task_id"] for t in web])
            worker.dispatch({"op": "task_finish", "task_id": qq["task_id"], "lease_token": due[0]["lease_token"], "failed": False})
            self.assertIn(qq["task_id"], store.indexes[worker.STATE_PREFIX + "tasks:qq"])
            self.assertNotIn(qq["task_id"], store.indexes[worker.STATE_PREFIX + "tasks"])
            with self.assertRaises(PermissionError):
                worker.dispatch({"op": "task_cancel", "task_id": qq["task_id"], "session_id": "wrong"})
            worker.dispatch({"op": "task_cancel", "task_id": qq["task_id"], "session_id": qq["session_id"]})
            self.assertNotIn(qq["task_id"], store.indexes[worker.STATE_PREFIX + "tasks:qq"])
