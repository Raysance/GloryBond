import asyncio
import json
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from fastapi.testclient import TestClient

from agent_console.document_inputs import DeepSeekDocuments, project_documents
from agent_console.provider import DeepSeekModel
from agent_console.server import create_app
from agent_runtime import Principal
from local_debugger import import_hok_module
from qq_agent.documents import QQDocuments


REMOTE = {"public": {"base_url": "https://api.deepseek.com", "model": "deepseek-flash"},
          "private": {"api_key": "official-test-key"}}


def document():
    return {"type": "chat_document", "name": "报告.pdf", "file_id": "file-api-test", "expires_at": time.time() + 60}


class DocumentTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_upload_then_mixed_image_and_document_route(self):
        requests = []
        def handle(request):
            requests.append(request)
            if request.url.path == "/files":
                return httpx.Response(200, json={"id": "file-api-test"})
            frame = {"choices": [{"delta": {"content": "已读取"}, "finish_reason": "stop"}]}
            return httpx.Response(200, text="data: " + json.dumps(frame) + "\n\ndata: [DONE]\n\n")
        docs = DeepSeekDocuments(REMOTE)
        model = DeepSeekModel(api_key="local", base_url="https://local.invalid", model="text",
                              documents=docs, vision={"model": "vision"}, fallback={"model": "backup"})
        factory = httpx.AsyncClient
        with patch("httpx.AsyncClient", side_effect=lambda **opts: factory(transport=httpx.MockTransport(handle), **opts)):
            part = await docs.upload("报告.pdf", b"%PDF-test")
            stored = [{"role": "user", "content": [part, {"type": "image_url", "image_url": {"url": "data:image/png;base64,test"}}]}]
            await model.complete(stored, [], AsyncMock())
            await docs.upload("表.csv", b"a,b")
        self.assertIn(b"rich_layout_recognition", requests[0].content)
        self.assertLess(requests[0].content.index(b'name="purpose"'), requests[0].content.index(b'name="file"'))
        self.assertIn(b"user_data", requests[2].content)
        body = json.loads(requests[1].content)
        self.assertEqual(body["model"], "deepseek-flash")
        self.assertIn({"type": "file", "file_id": "file-api-test"}, next(m["content"] for m in body["messages"] if m["role"] == "user"))
        self.assertTrue(all(req.url.host == "api.deepseek.com" and
                            req.headers["Authorization"] == "Bearer official-test-key" for req in requests))
        self.assertEqual(stored[0]["content"][0]["type"], "chat_document")
        combined, _ = project_documents(stored + stored)
        self.assertEqual(sum(p["type"] == "file" for m in combined for p in m["content"]), 1)
        part["expires_at"] = 0
        projected, has_files = project_documents(stored)
        self.assertFalse(has_files)
        self.assertIn("已过期", projected[0]["content"][0]["text"])

    async def test_qq_quote_concurrent_reads_reuse_upload_only_in_bound_scope(self):
        docs = QQDocuments(REMOTE)
        docs.provider.upload = AsyncMock(return_value=document())
        read = AsyncMock(return_value=b"pdf")
        sources = [{"name": "报告.pdf"}]
        await asyncio.gather(*(docs.prepare(sources, ("group", "1"), "10", read) for _ in range(2)))
        self.assertEqual(read.await_count, 1)
        await docs.prepare(sources, ("group", "2"), "10", read)
        self.assertEqual(read.await_count, 2)
        bad = await docs.prepare(sources, ("group", "2"), "11", AsyncMock(side_effect=Exception("signed-url")))
        self.assertIn("未读取", bad[0]["text"])
        self.assertNotIn("signed-url", str(bad))

    def test_group_file_quote_requires_verified_group(self):
        chat = import_hok_module("event_handlers.chat")
        event = Mock(group_id=1, self_id=2)
        reply = {"message_id": 4, "message_type": "group", "sender": {"user_id": 3},
                 "message": [{"type": "file", "data": {"file": "文档.pdf", "file_id": "qq-id"}}]}
        event.reply = reply
        self.assertFalse(chat.normalize_quoted_message(event)["available"])
        self.assertFalse(chat.normalize_quoted_message(event, {**reply, "group_id": 2})["available"])
        allowed = chat.normalize_quoted_message(event, {**reply, "group_id": 1})
        self.assertEqual(allowed["document_sources"][0]["id"], "qq-id")

    def test_web_document_only_submission_and_session_binding(self):
        app = create_app()
        app.state.documents = Mock(upload=AsyncMock(return_value=document()))
        app.state.local_log = Mock(record=AsyncMock())
        app.state.current_prompt = AsyncMock(return_value="prompt")
        app.state.roles = Mock(manage=AsyncMock(return_value={"selected": {"name": "role"}}))
        app.state.principal = Principal("u")
        app.state.runtime = Mock(active={"run": Mock()}, submit=Mock(return_value="run"))
        client = TestClient(app)
        self.addCleanup(client.close)
        client.get("/")
        headers = {"X-Local-UI": "1"}
        uploaded = client.post("/api/documents?name=a.pdf&session_id=a", content=b"pdf", headers=headers)
        self.assertEqual(uploaded.status_code, 200)
        self.assertNotIn("file-api", uploaded.text)
        def submit(session):
            return client.post("/api/chat", json={"session_id": session, "document_ids": [uploaded.json()["id"]]}, headers=headers)
        self.assertEqual(submit("b").status_code, 422)
        self.assertEqual(submit("a").status_code, 200)
        current = app.state.runtime.submit.call_args.args[0].metadata["chat_context"]["current"]
        self.assertEqual(current[-1]["file_id"], "file-api-test")
