"""Official Fetch supplies Markdown; pagination never crawls its child URLs."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock

import httpx

from glorybond.agent.webpages import WebPageFetcher, WebPageLimits
from glorybond.integrations.deepseek_web import DeepSeekFetchClient


class FetchTests(unittest.IsolatedAsyncioTestCase):
    def reader(self, handler, **limits):
        self.client = DeepSeekFetchClient({"api_key": "fetch-only-secret"}, client_factory=lambda **kw:
            httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw))
        self.addAsyncCleanup(self.client.close)
        reader = WebPageFetcher(WebPageLimits(**limits), page_reader=self.client.fetch)
        reader._download = AsyncMock(side_effect=AssertionError("official Fetch must not fall back"))
        return reader

    async def test_markdown_links_and_all_text_are_preserved_with_independent_continuation(self):
        markdown = "# Page\n\n" + "Body " * 30 + "\n[Author](https://profile.example/)\n" + "\n".join(
            f"[Source {i}](/source/{i})" for i in range(105))
        requests = []
        def handler(request):
            requests.append(json.loads(request.content))
            self.assertEqual(str(request.url), "https://api.deepseek.com/v1/tools/fetch")
            self.assertEqual(request.headers["Authorization"], "Bearer fetch-only-secret")
            self.assertEqual(json.loads(request.content), {"url": "https://example.com/page"})
            return httpx.Response(200, json={"content": markdown, "title": "Page"})
        reader = self.reader(handler, max_page_chars=100)
        first = result = await reader.read("https://example.com/page#fragment")
        text, links = result["text"], result["links"]
        self.assertEqual(first["provider"], "deepseek_fetch")
        self.assertEqual(first["content_format"], "markdown")
        self.assertEqual(first["title"], "Page")
        self.assertEqual(len(links), 100)
        while result["next_offset"] is not None or result["next_link_offset"] is not None:
            result = await reader.read("https://example.com/page", offset=result["next_offset"] or result["total_chars"],
                                       link_offset=result["next_link_offset"] or result["total_links"])
            text += result["text"]
            links += result["links"]
        self.assertEqual(text, markdown)
        self.assertEqual(len(links), 106)
        self.assertEqual(links[0], {"url": "https://profile.example/", "text": "Author"})
        self.assertEqual(links[-1]["url"], "https://example.com/source/104")
        self.assertTrue(all(request == requests[0] for request in requests))
        reader._download.assert_not_awaited()

    async def test_http_errors_bad_payload_and_oversize_do_not_expose_provider_body_or_fallback(self):
        responses = [httpx.Response(404, text="fetch-only-secret provider-private-message"),
                     httpx.Response(200, json={"content": ""}), httpx.Response(200, json=[]),
                     httpx.Response(200, json={"content": "x" * 2048})]
        reader = self.reader(lambda _: responses.pop(0), max_response_bytes=1024)
        for index in range(4):
            result = await reader.read("https://example.com/page")
            self.assertEqual(result["status"], "unavailable")
            self.assertNotIn("fetch-only-secret", str(result))
            self.assertNotIn("provider-private-message", str(result))
            self.assertNotIn("text", result)
            if index == 0:
                self.assertIn("HTTP 404", result["error"])
        reader._download.assert_not_awaited()

    async def test_private_urls_and_credentials_are_rejected_before_provider_request(self):
        reader = self.reader(lambda _: self.fail("unexpected Fetch request"))
        for url in ("http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/",
                    "http://localhost/", "https://private.local/", "https://user:password@example.com/"):
            with self.subTest(url=url):
                try:
                    result = await reader.read(url)
                except ValueError:
                    continue
                self.assertEqual(result["status"], "unavailable")

    async def test_official_fetch_calls_overlap_and_cancellation_closes_both(self):
        started, cancelled = [], []
        both = asyncio.Event()
        async def handler(request):
            url = json.loads(request.content)["url"]
            started.append(url)
            if len(started) == 2:
                both.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(url)
        reader = self.reader(handler)
        tasks = [asyncio.create_task(reader.read(f"https://example.com/{i}")) for i in range(2)]
        await asyncio.wait_for(both.wait(), 1)
        await self.client.close()
        self.assertTrue(all(task.cancelled() for task in tasks))
        self.assertEqual(set(cancelled), set(started))


if __name__ == "__main__":
    unittest.main()
