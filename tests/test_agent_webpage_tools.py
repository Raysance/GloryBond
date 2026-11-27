"""On-demand follow-up reads: real PDF extraction, batching and agent tool flow."""
import asyncio
import io
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from agent_runtime import AgentRuntime, Principal, RunRequest, ToolRegistry
from agent_runtime.models import ToolContext
from agent_runtime.tools.executor import execute
from pypdf import PdfWriter
from pypdf.annotations import Link
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from glorybond.agent.tools.application import register_application_tools
from glorybond.agent.webpages import WebPageLimits, extract_pdf, extract_webpage
from tests.test_agent_runtime import Clock, ScriptedModel, Sink, State, call
from tests.test_agent_webpages import fetcher, response


def pdf_bytes(*, encrypted=False, blank=False):
    writer = PdfWriter()
    for number in (1, 2, 3):
        page = writer.add_blank_page(width=600, height=800)
        if not blank:
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({
                NameObject("/F1"): DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})})})
            content = DecodedStreamObject()
            content.set_data(f"BT /F1 12 Tf 20 750 Td (Report page {number}) Tj ET".encode())
            page.replace_contents(content)
    writer.add_annotation(page_number=0, annotation=Link(rect=(0, 0, 10, 10), url="https://example.com/details"))
    writer.add_metadata({"/Title": "Public report"})
    if encrypted:
        writer.encrypt("secret")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class LinkTests(unittest.TestCase):
    def test_visible_relative_pdf_and_external_links_without_hidden_or_unsafe_targets(self):
        page = extract_webpage(b'''<main><h1>Report</h1><a href="../paper.pdf">Full paper</a>
            <a href="https://other.example/details#one">Details</a><a href="https://other.example/details#two">Duplicate</a>
            <a href="#local">Heading</a><nav><a href="/noise">Navigation</a></nav>
            <div hidden><a href="/hidden">Hidden</a></div><a href="javascript:alert(1)">Unsafe</a>
            <a href="https://user:secret@example.com/">Login</a><a href="/image.png">Image</a></main>''',
            "text/html", "https://example.com/docs/index")
        self.assertEqual(page["links"], [{"url": "https://example.com/paper.pdf", "text": "Full paper"},
                                          {"url": "https://other.example/details", "text": "Details"}])

    def test_markdown_relative_links_balanced_urls_and_bounded_list(self):
        page = extract_webpage(b'[PDF](paper.pdf) https://example.com/test_(x)\n[Third](/third)',
                               "text/plain", "https://example.com/docs/README.md", 2)
        self.assertEqual([row["url"] for row in page["links"]],
                         ["https://example.com/docs/paper.pdf", "https://example.com/third"])
        self.assertEqual(page["omitted_links"], 1)
        page = extract_webpage(b'https://example.com/test_(x)', "text/plain", "https://example.com/")
        self.assertEqual(page["links"][0]["url"], "https://example.com/test_(x)")


class ReadingTests(unittest.IsolatedAsyncioTestCase):
    async def test_batch_downloads_overlap_and_one_failure_keeps_other_body(self):
        started = set()
        both_started = asyncio.Event()
        async def handler(request):
            started.add(request.url.path)
            if len(started) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), 1)
            return response(b"<main>Success <a href='/never'>Next</a></main>") if request.url.path == "/good" else response(status=403)
        reader, resolver, _ = fetcher(handler)
        result = await reader.read_many(["https://example.com/good", "https://example.com/bad"])
        self.assertEqual([page["status"] for page in result["results"]], ["ok", "unavailable"])
        self.assertIn("Success", result["results"][0]["text"])
        self.assertEqual(started, {"/good", "/bad"})
        self.assertEqual(resolver.await_count, 2)

    async def test_normalized_duplicates_and_invalid_links_are_isolated(self):
        reader, resolver, _ = fetcher(lambda _: response())
        result = await reader.read_many(["https://example.com/a#1", "https://EXAMPLE.com/a#2",
                                         "https://user:secret@example.com/private"])
        self.assertEqual(resolver.await_count, 1)
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(result["results"][1]["input_index"], 3)
        self.assertNotIn("secret", json.dumps(result))

    async def test_batch_total_budget_and_private_targets(self):
        reader, _, _ = fetcher(lambda _: response(b"x" * 110, headers={"Content-Type": "text/plain"}),
                               max_page_chars=100, max_total_chars=150)
        result = await reader.read_many(["https://example.com/a", "https://example.com/b"])
        self.assertEqual([len(page["text"]) for page in result["results"]], [100, 50])
        self.assertTrue(all(page["truncated"] for page in result["results"]))
        reader.resolver = reader._resolve
        result = await reader.read_many(["http://127.0.0.1/private.pdf"])
        self.assertIn("内网", result["results"][0]["error"])

    async def test_pdf_pages_and_links_use_real_parser_without_following_links(self):
        paths = []
        raw = pdf_bytes()
        def handler(request):
            paths.append(request.url.path)
            return response(raw, headers={"Content-Type": "application/pdf"})
        reader, _, _ = fetcher(handler)
        result = await reader.read("https://example.com/report.pdf", page_count=1)
        self.assertEqual(result["status"], "ok", result)
        self.assertEqual(result["title"], "Public report")
        self.assertEqual(result["page_count"], 3)
        self.assertEqual(result["next_page"], 2)
        self.assertEqual(result["pages"][0]["text"], "Report page 1")
        self.assertEqual(result["links"][0]["url"], "https://example.com/details")
        second = await reader.read("https://example.com/report.pdf", start_page=2, page_count=2)
        self.assertEqual([page["text"] for page in second["pages"]], ["Report page 2", "Report page 3"])
        self.assertIsNone(second["next_page"])
        self.assertEqual(paths, ["/report.pdf", "/report.pdf"])

    async def test_pdf_blank_encrypted_malformed_limits_and_octet_stream(self):
        for raw, expected in [(pdf_bytes(encrypted=True), "加密"), (b"%PDF-1.7 invalid", "解析失败"),
                               (pdf_bytes(), "体积上限"), (b"not a PDF", "有效 PDF")]:
            reader, _, _ = fetcher(lambda _: response(raw, headers={"Content-Type": "application/pdf"}),
                                   **({"max_pdf_bytes": 1024} if expected == "体积上限" else {}))
            with self.subTest(expected=expected):
                result = await reader.read("https://example.com/report")
                self.assertEqual(result["status"], "unavailable")
                self.assertIn(expected, result["error"])
        reader, _, _ = fetcher(lambda _: response(pdf_bytes(blank=True), headers={"Content-Type": "application/octet-stream"}))
        result = await reader.read("https://example.com/report")
        self.assertEqual(result["status"], "ok", result)
        self.assertFalse(result["text_available"])
        self.assertEqual(result["extraction"], "text_only_no_ocr")
        result = await reader.read("https://example.com/report", start_page=4)
        self.assertIn("超出范围", result["error"])

    async def test_cancellation_reaps_pdf_process(self):
        entered = asyncio.Event()
        async def running(raw):
            entered.set()
            await asyncio.Event().wait()
        process = Mock(returncode=None, communicate=running, wait=AsyncMock())
        with patch("glorybond.agent.webpages.asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
            task = asyncio.create_task(extract_pdf(b"%PDF-", WebPageLimits(), 1, 1))
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        process.kill.assert_called_once()
        process.wait.assert_awaited_once()


class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_followup_batch_and_pdf_in_one_agent_interaction(self):
        fetched = []
        def handler(request):
            path = request.url.path
            fetched.append(path)
            if path == "/report.pdf":
                return response(pdf_bytes(), headers={"Content-Type": "application/pdf"})
            if path == "/article":
                return response(b"<main>Study <a href='/report.pdf'>Report</a><a href='/details'>Details</a></main>")
            return response(b"<main>Supporting facts</main>")
        reader, _, _ = fetcher(handler)
        registry = ToolRegistry()
        register_application_tools(registry, service=Mock(), catalogs={}, webpages=reader)
        model = ScriptedModel([
            {"role": "assistant", "content": "", "tool_calls": [call("discover_tools", {"categories": ["internet"]}, "d")]},
            {"role": "assistant", "content": "", "tool_calls": [call("read_webpage", {"urls": ["https://example.com/article"]}, "p")]},
            {"role": "assistant", "content": "", "tool_calls": [call("read_webpage", {"urls": ["https://example.com/report.pdf", "https://example.com/details"]}, "f")]},
            {"role": "assistant", "content": "Read the report and supporting facts."},
        ])
        state = State()
        runtime = AgentRuntime(model=model, registry=registry, state=state, output=Sink(), clock=Clock())
        result = await runtime.run(RunRequest("Read the linked report", "session", Principal("u", frozenset({"web.read"}))))
        self.assertIn("supporting facts", result["text"])
        self.assertEqual(fetched, ["/article", "/report.pdf", "/details"])
        self.assertIn("read_webpage", [s["function"]["name"] for s in model.schemas[1]])
        tool_messages = [m for m in model.requests[-1] if m["role"] == "tool"]
        self.assertIn("Report page 1", json.dumps(tool_messages))
        self.assertIn("Supporting facts", json.dumps(tool_messages))

    async def test_authorization_disclosure_and_disabled_config(self):
        reader, _, _ = fetcher(lambda _: self.fail("unexpected network"))
        registry = ToolRegistry()
        register_application_tools(registry, service=Mock(), catalogs={}, webpages=reader)
        ctx = ToolContext(RunRequest("read", "s", Principal("u")), None)
        result = await execute(registry, call("read_webpage", {"urls": ["https://example.com/"]}), ctx)
        self.assertFalse(result.ok)
        ctx = ToolContext(RunRequest("read", "s", Principal("u", frozenset({"web.read"}))), None)
        result = await execute(registry, call("read_webpage", {"urls": ["https://example.com/"]}), ctx)
        self.assertFalse(result.ok)
        reader.limits.enabled = False
        registry = ToolRegistry()
        register_application_tools(registry, service=Mock(), catalogs={}, webpages=reader)
        self.assertNotIn("read_webpage", registry.tools)


if __name__ == "__main__":
    unittest.main()
