"""On-demand source tools, native document inputs and the generic tool barrier."""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from agent_runtime import AgentRuntime, Principal, RunRequest, ToolRegistry
from agent_runtime.models import ToolContext
from agent_runtime.tools.executor import execute
from glorybond.agent.document_inputs import DeepSeekDocuments, MAX_DOCUMENT_BYTES
from glorybond.agent.provider import DeepSeekModel
from glorybond.agent.tools.application import register_application_tools
from glorybond.agent.tools.documents import ReadDocumentArgs, download_name, read_local_document
from glorybond.agent.webpages import PageError, extract_webpage
from tests.test_agent_runtime import Clock, Sink, State, call
from tests.test_agent_webpages import fetcher, response
from tests.test_chat_media_inputs import REMOTE


class LinkTests(unittest.TestCase):
    def test_visible_links_keep_formats_and_navigation_without_unsafe_targets(self):
        page = extract_webpage(b'''<aside class="social"><a href="/profile">Author</a></aside>
            <main><h1>Report</h1><a href="../paper.pdf">Full paper</a>
            <a href="https://other.example/details#one">Details</a><a href="https://other.example/details#two">Duplicate</a>
            <a href="#local">Heading</a><nav><a href="/index">Navigation</a></nav>
            <div hidden><a href="/hidden">Hidden</a></div><a href="javascript:alert(1)">Unsafe</a>
            <a href="https://user:secret@example.com/">Login</a><a href="/image.png">Image</a>
            <a href="/archive.zip">Sources</a></main>''', "text/html", "https://example.com/docs/index")
        self.assertEqual(page["links"], [
            {"url": "https://example.com/profile", "text": "Author"},
            {"url": "https://example.com/paper.pdf", "text": "Full paper"},
            {"url": "https://other.example/details", "text": "Details"},
            {"url": "https://example.com/index", "text": "Navigation"},
            {"url": "https://example.com/image.png", "text": "Image"},
            {"url": "https://example.com/archive.zip", "text": "Sources"}])

    def test_markdown_labels_relative_links_balanced_urls_and_bounded_list(self):
        page = extract_webpage(b'[Report](paper.pdf) https://example.com/test_(x)\n[Third](/third)',
                               "text/plain", "https://example.com/docs/README.md", 2)
        self.assertEqual(page["links"], [{"url": "https://example.com/docs/paper.pdf", "text": "Report"},
                                          {"url": "https://example.com/third", "text": "Third"}])
        self.assertEqual(page["omitted_links"], 1)
        page = extract_webpage(b'https://example.com/test_(x)', "text/plain", "https://example.com/")
        self.assertEqual(page["links"][0]["url"], "https://example.com/test_(x)")

    def test_markdown_table_does_not_reparse_destinations_with_cell_separators(self):
        page = extract_webpage(b'''|File|Commit|
|---|---|
|[Sources](https://example.com/src)|[Revision](https://example.com/rev)|
|https://example.com/bare|https://example.com/next|
`https://example.com/code`''', "text/markdown", "https://example.com/", None)
        self.assertEqual(page["links"], [
            {"url": "https://example.com/src", "text": "Sources"},
            {"url": "https://example.com/rev", "text": "Revision"},
            {"url": "https://example.com/bare", "text": ""},
            {"url": "https://example.com/next", "text": ""}])


class ReadingTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_first_batch_exposes_links_after_navigation_and_continues_after_100(self):
        raw = ("<nav>" + "".join(f'<a href="/nav/{i}">Menu {i}</a>' for i in range(30)) +
               "</nav><main>Body" + "".join(f'<a href="/source/{i}">Source {i}</a>' for i in range(79)) +
               "</main>").encode()
        reader, _, _ = fetcher(lambda _: response(raw))
        first = await reader.read("https://example.com/")
        self.assertEqual(len(first["links"]), 100)
        self.assertEqual(first["total_links"], 109)
        self.assertEqual(first["next_link_offset"], 100)
        self.assertIn({"url": "https://example.com/source/0", "text": "Source 0"}, first["links"])
        rest = await reader.read("https://example.com/", link_offset=first["next_link_offset"])
        self.assertEqual(len(rest["links"]), 9)
        self.assertIsNone(rest["next_link_offset"])

    async def test_continuations_recover_all_text_and_links_without_following_them(self):
        raw = ("<main><p>" + "x" * 310 + "</p>" +
               "".join(f'<a href="/{i}.dat">Source {i}</a>' for i in range(26)) + "</main>").encode()
        paths = []
        def handler(request):
            paths.append(request.url.path)
            return response(raw)
        reader, _, _ = fetcher(handler, max_page_chars=100, max_links=10)
        full = extract_webpage(raw, "text/html", "https://example.com/", None)
        result = await reader.read("https://example.com/")
        text, links = result["text"], result["links"]
        while result["next_offset"] is not None or result["next_link_offset"] is not None:
            result = await reader.read("https://example.com/", offset=result["next_offset"] or result["total_chars"],
                                       link_offset=result["next_link_offset"] or result["total_links"])
            text += result["text"]
            links += result["links"]
        self.assertEqual(text, full["text"])
        self.assertEqual(links, full["links"])
        self.assertTrue(all(path == "/" for path in paths))

    async def test_web_reader_reports_content_type_without_auto_parsing_documents(self):
        for mime in ("application/pdf", "application/zip", "image/png"):
            reader, _, _ = fetcher(lambda _: response(b"binary", headers={"Content-Type": mime}))
            result = await reader.read("https://example.com/resource")
            self.assertEqual(result["status"], "unavailable")
            self.assertIn(mime, result["error"])
            self.assertNotIn("text", result)

    async def test_binary_download_uses_same_public_address_and_size_boundaries(self):
        reader, _, _ = fetcher(lambda _: response(b"x" * 1025, headers={"Content-Type": "application/pdf"}))
        with self.assertRaisesRegex(PageError, "体积上限"):
            await reader.download("https://example.com/a", max_bytes=1024)
        reader.resolver = reader._resolve
        with self.assertRaisesRegex(PageError, "内网"):
            await reader.download("http://127.0.0.1/a", max_bytes=1024)


class DocumentToolTests(unittest.IsolatedAsyncioTestCase):
    def registry(self, reader, documents, roots=()):
        registry = ToolRegistry()
        register_application_tools(registry, service=Mock(), catalogs={}, webpages=reader,
                                   documents=documents, document_roots=roots)
        return registry

    def context(self):
        return ToolContext(RunRequest("read", "s", Principal("u", frozenset({"web.read"}))), None)

    async def test_local_source_scope_and_upload(self):
        docs = DeepSeekDocuments(REMOTE)
        docs.upload = AsyncMock(return_value={"file_id": "file-test"})
        reader, resolver, _ = fetcher(lambda _: self.fail("unexpected network"))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            allowed = root / "documents"
            allowed.mkdir()
            source = allowed / "notes.txt"
            source.write_bytes(b"notes")
            outside = root / "private.txt"
            outside.write_bytes(b"private")
            (allowed / "escape.txt").symlink_to(outside)
            registry = self.registry(reader, docs, [allowed])
            handler = registry.tools["read_document"].handler
            result = await handler(ReadDocumentArgs(local_path=str(source)), self.context())
            self.assertEqual(result["document"]["file_id"], "file-test")
            docs.upload.assert_awaited_once_with("notes.txt", b"notes")
            for path in (outside, allowed / "escape.txt"):
                with self.assertRaises(PermissionError):
                    await handler(ReadDocumentArgs(local_path=str(path)), self.context())
            with self.assertRaises(ValueError):
                read_local_document("notes.txt", (allowed,))
            source.write_bytes(b"")
            with self.assertRaises(ValueError):
                read_local_document(str(source), (allowed,))
            with source.open("wb") as stream:
                stream.truncate(MAX_DOCUMENT_BYTES + 1)
            with self.assertRaises(ValueError):
                read_local_document(str(source), (allowed,))
        resolver.assert_not_awaited()

    def test_source_validation_and_download_filename(self):
        for args in ({}, {"url": "https://example.com", "local_path": "/a.txt"}):
            with self.assertRaises(ValueError):
                ReadDocumentArgs(**args)
        data = {"final_url": "https://example.com/download", "content_type": "application/pdf",
                "content_disposition": "attachment; filename*=UTF-8''report%20one.docx"}
        self.assertEqual(download_name(data, None), "report one.docx")
        self.assertEqual(download_name({**data, "content_disposition": ""}, None), "document.pdf")
        self.assertEqual(download_name(data, "report.csv"), "report.csv")
        with self.assertRaises(ValueError):
            download_name({**data, "content_disposition": "", "content_type": "application/octet-stream"}, None)

    async def test_common_authorization_disclosure_and_configuration(self):
        reader, _, _ = fetcher(lambda _: self.fail("unexpected network"))
        docs = DeepSeekDocuments(REMOTE)
        docs.upload = AsyncMock(side_effect=AssertionError("unexpected upload"))
        registry = self.registry(reader, docs)
        for name in ("read_webpage", "read_document"):
            ctx = ToolContext(RunRequest("read", "s", Principal("u")), None)
            result = await execute(registry, call(name, {"url": "https://example.com/"}), ctx)
            self.assertFalse(result.ok)
            result = await execute(registry, call(name, {"url": "https://example.com/"}), self.context())
            self.assertFalse(result.ok)  # Not disclosed yet.
        reader.limits.enabled = False
        docs.settings = None
        registry = self.registry(reader, docs)
        self.assertNotIn("read_webpage", registry.tools)
        self.assertNotIn("read_document", registry.tools)

    def test_native_projection_requires_successful_host_issued_tool_reference(self):
        docs = DeepSeekDocuments(REMOTE)
        part = {"type": "chat_document", "name": "real.txt", "file_id": "file-known", "expires_at": time.time() + 60}
        docs.issued[part["file_id"]] = part
        def messages(name="read_document", ok=True, file_id="file-known"):
            return [{"role": "assistant", "reasoning_content": "kept", "tool_calls": [call(name, {}, "a")]},
                    {"role": "tool", "tool_call_id": "a", "content": json.dumps({"ok": ok, "data": {
                        "document": {**part, "name": "untrusted-name", "file_id": file_id}}})}]
        for source in (messages(name="read_webpage"), messages(ok=False), messages(file_id="file-forged")):
            self.assertEqual(docs.project_tool_documents(source), source)
        source = messages()
        original = copy.deepcopy(source)
        projected = docs.project_tool_documents(source)
        self.assertEqual(source, original)
        self.assertEqual(projected[:-1], original)
        self.assertEqual(projected[-1]["content"][-1], part)
        part["expires_at"] = 0
        self.assertEqual(docs.project_tool_documents(source), source)

    async def test_generic_chain_parallel_sources_and_native_file_in_next_model_request(self):
        fetched, provider_requests, parallel_started = [], [], set()
        both = asyncio.Event()
        async def handler(request):
            host, path = request.headers["host"], request.url.path
            fetched.append((host, path))
            if path in {"/report.csv", "/details"}:
                parallel_started.add(path)
                if len(parallel_started) == 2:
                    both.set()
                await asyncio.wait_for(both.wait(), 1)
            if path == "/report.csv":
                return response(b"item,total\na,42", headers={"Content-Type": "text/csv"})
            if host == "github.com":
                return response(b"<main>Repository</main><aside><a href='https://profile.example/'>Author</a></aside>")
            if path == "/":
                return response(b"<main>Homepage <a href='/report.csv'>Report</a><a href='/details'>Details</a></main>")
            return response(b"<main>Supporting facts</main>")
        reader, _, _ = fetcher(handler)
        docs = DeepSeekDocuments(REMOTE)
        registry = self.registry(reader, docs)
        batches = [
            [call("discover_tools", {"categories": ["internet", "documents"]}, "d")],
            [call("read_webpage", {"url": "https://github.com/example/repo"}, "r")],
            [call("read_webpage", {"url": "https://profile.example/"}, "h")],
            [call("read_document", {"url": "https://profile.example/report.csv"}, "p"),
             call("read_webpage", {"url": "https://profile.example/details"}, "f")],
        ]
        def provider(request):
            provider_requests.append(request)
            if request.url.path == "/files":
                return httpx.Response(200, json={"id": "file-api-report"})
            body = json.loads(request.content)
            index = sum(r.url.path != "/files" for r in provider_requests) - 1
            if index < len(batches):
                delta = {"tool_calls": [{"index": i, **c} for i, c in enumerate(batches[index])]}
                finish = "tool_calls"
            else:
                self.assertEqual(body["model"], "deepseek-flash")
                content = next(m["content"] for m in reversed(body["messages"]) if m["role"] == "user")
                self.assertIn({"type": "file", "file_id": "file-api-report"}, content)
                self.assertEqual([m["tool_call_id"] for m in body["messages"] if m["role"] == "tool"][-2:], ["p", "f"])
                self.assertIn("Supporting facts", json.dumps(body))
                delta, finish = {"content": "Read the report and supporting facts."}, "stop"
            frame = {"choices": [{"delta": delta, "finish_reason": finish}]}
            return httpx.Response(200, text="data: " + json.dumps(frame) + "\n\ndata: [DONE]\n\n")
        model = DeepSeekModel(api_key="local", base_url="https://local.invalid", model="text", documents=docs)
        runtime = AgentRuntime(model=model, registry=registry, state=State(), output=Sink(), clock=Clock())
        factory = httpx.AsyncClient
        with patch("httpx.AsyncClient", side_effect=lambda **opts: factory(transport=httpx.MockTransport(provider), **opts)):
            result = await runtime.run(RunRequest("Summarize the author's report: https://github.com/example/repo", "session",
                                                 Principal("u", frozenset({"web.read"}))))
        self.assertIn("supporting facts", result.get("text", ""), result)
        self.assertEqual(fetched, [("github.com", "/example/repo"), ("profile.example", "/"),
                                  ("profile.example", "/report.csv"), ("profile.example", "/details")])
        self.assertTrue(both.is_set())
        self.assertEqual(len(provider_requests), 6)  # Five ReAct steps and one Files upload, no summarizer.
        for request in provider_requests[-2:]:
            self.assertEqual(request.url.host, "api.deepseek.com")
            self.assertEqual(request.headers["Authorization"], "Bearer official-test-key")
        self.assertIn(b"user_data", provider_requests[-2].content)
        self.assertIn(b"item,total", provider_requests[-2].content)


if __name__ == "__main__":
    unittest.main()
