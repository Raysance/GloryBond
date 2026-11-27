"""Search HTTP overlaps independently of the serialized state/business RPC."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock

import httpx

from glorybond.agent.remote import RemoteBridge
from glorybond.integrations.deepseek_web import DeepSeekSearchClient


SETTINGS = {"endpoint": "https://api.deepseek.com/v1/tools/search", "api_key": "independent-search-key"}


class SearchTransportTests(unittest.IsolatedAsyncioTestCase):
    def client(self, handler):
        client = DeepSeekSearchClient(SETTINGS, client_factory=lambda **kwargs:
            httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs))
        self.addAsyncCleanup(client.close)
        return client

    async def test_two_http_requests_overlap_while_rpc_is_locked_and_one_failure_is_isolated(self):
        arrived, both = [], asyncio.Event()
        async def handler(request):
            self.assertEqual(request.headers["Authorization"], "Bearer independent-search-key")
            payload = json.loads(request.content)
            arrived.append(payload)
            if len(arrived) == 2:
                both.set()
            await asyncio.wait_for(both.wait(), 1)
            if payload["query"] == "fail":
                return httpx.Response(429, text="independent-search-key provider-private-message")
            return httpx.Response(200, json={"results": [{"url": "https://example.com/", "snippet": "short"}]})
        bridge = RemoteBridge("unused", ".", "python", ".")
        bridge._search_client = self.client(handler)
        bridge._exchange = AsyncMock(side_effect=AssertionError("search must not use RPC"))
        self.addAsyncCleanup(bridge.close)
        async with bridge.lock:
            results = await asyncio.gather(bridge.call("web_search", query="ok", result_type="snippet"),
                                          bridge.call("web_search", query="fail"), return_exceptions=True)
        self.assertTrue(both.is_set())
        self.assertIn("short", results[0]["answer"])
        self.assertEqual(str(results[1]), "deepseek_web_search unavailable: HTTP 429")
        self.assertEqual([p["need_content"] for p in arrived], [False, False])
        bridge._exchange.assert_not_awaited()

    async def test_gate_limits_http_to_two_and_cancel_releases_slot_without_retry(self):
        started, stopped = [], []
        both, third = asyncio.Event(), asyncio.Event()
        async def handler(request):
            query = json.loads(request.content)["query"]
            started.append(query)
            if len(started) == 2:
                both.set()
            if query == "third":
                third.set()
                return httpx.Response(200, json={"results": []})
            try:
                await asyncio.Event().wait()
            finally:
                stopped.append(query)
        client = self.client(handler)
        first = asyncio.create_task(client.search("first"))
        second = asyncio.create_task(client.search("second"))
        await asyncio.wait_for(both.wait(), 1)
        queued = asyncio.create_task(client.search("third"))
        await asyncio.sleep(0)
        self.assertEqual(started, ["first", "second"])
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        await asyncio.wait_for(third.wait(), 1)
        self.assertEqual((await queued)["query"], "third")
        await client.close()
        self.assertTrue(second.cancelled())
        self.assertEqual(started, ["first", "second", "third"])
        self.assertEqual(stopped, ["first", "second"])
        self.assertFalse(client._active)
        with self.assertRaisesRegex(RuntimeError, "已关闭"):
            await client.search("later")

    async def test_reconnect_preserves_search_client_when_credentials_are_unchanged(self):
        bridge = RemoteBridge("unused", ".", "python", ".")
        client = self.client(lambda _: httpx.Response(200, json={"results": []}))
        bridge._search_client = client
        bridge._bootstrap_args = {}
        bridge._stop_worker_locked = AsyncMock()
        bridge._spawn_worker = AsyncMock()
        bridge._request_locked = AsyncMock(return_value={"private": {"search_api_key": SETTINGS["api_key"]},
            "public": {"search_config": {"endpoint": SETTINGS["endpoint"]}}})
        await bridge._connect_locked()
        self.assertIs(bridge._search_client, client)
        self.assertEqual(bridge.redact(SETTINGS["api_key"]), "[redacted]")
        await bridge.close()
        self.assertTrue(client._closed)


if __name__ == "__main__":
    unittest.main()
