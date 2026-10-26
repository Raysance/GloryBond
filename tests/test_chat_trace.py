import json
import unittest
from pathlib import Path
from unittest.mock import Mock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from fastapi.templating import Jinja2Templates

from chat_trace import chat_trace_response, parse_chat_trace


class TracePageTests(unittest.TestCase):
    def setUp(self):
        self.key = "a" * 16
        self.payload = {"kind": "chat_trace", "version": 1, "rounds": [],
                        "question": '</script><img src=x onerror="alert(1)">', "status": "ok"}
        self.loader = Mock(side_effect=lambda key: json.dumps(self.payload))
        templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))
        app = FastAPI()
        @app.get("/chat-trace")
        async def page(request: Request, key: str = ""):
            return await chat_trace_response(request, key, load_artifact=self.loader, templates=templates)
        self.client = TestClient(app)

    def test_success_is_self_contained_escaped_and_not_cached(self):
        response = self.client.get("/chat-trace", params={"key": self.key})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertIn("noindex", response.headers["x-robots-tag"])
        self.assertNotIn(self.payload["question"], response.text)
        self.assertIn(r"\u003c/script\u003e", response.text)
        self.assertNotIn('src="https://', response.text)
        self.assertNotIn("innerHTML", response.text)

    def test_invalid_token_does_not_access_redis(self):
        for key in ["", "../secret", "a" * 15, "a" * 17, "a" * 47, "a" * 49, "z" * 16]:
            self.assertEqual(self.client.get("/chat-trace", params={"key": key}).status_code, 400)
        self.loader.assert_not_called()

    def test_existing_48_character_links_remain_readable_until_expiry(self):
        self.assertEqual(self.client.get("/chat-trace", params={"key": "b" * 48}).status_code, 200)
        self.loader.assert_called_once_with("b" * 48)

    def test_shared_records_ignore_old_visibility_and_do_not_require_admin_cookies(self):
        for visibility in ("public", "admin"):
            for key in (self.key, "b" * 48):
                with self.subTest(visibility=visibility, key=key):
                    self.payload["visibility"] = visibility
                    response = self.client.get("/chat-trace", params={"key": key}, follow_redirects=False)
                    self.assertEqual(response.status_code, 200)
                    self.assertNotIn("location", response.headers)
                    self.assertNotIn('← AI 运行记录', response.text)

    def test_missing_or_wrong_kind_is_expired(self):
        for raw in [None, b"bad", b'{"kind":"bili_video"}', b'[]']:
            self.loader.side_effect = lambda key: raw
            self.assertEqual(self.client.get("/chat-trace", params={"key": self.key}).status_code, 410)

    def test_redis_unavailable_is_retryable(self):
        self.loader.side_effect = ConnectionError("private details")
        response = self.client.get("/chat-trace", params={"key": self.key})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private details", response.text)

    def test_only_local_harness_images_can_be_rendered(self):
        self.payload["artifacts"] = [{"url": "https://tracker/private"}, {"url": "//evil/x"},
                                     {"url": "/file_transfer/../x"},
                                     {"url": "/file_transfer/chat_plot_" + "a" * 32 + ".png"}]
        self.assertEqual(len(parse_chat_trace(json.dumps(self.payload))["artifacts"]), 1)

    def test_large_model_payload_is_complete_and_html_safe(self):
        body = "正文" * 1100000 + "TAIL</script>"
        self.payload["rounds"] = [{"tools": [], "request_payload": {"messages": [{"content": body}]},
                                  "response_payload": {"choices": [{"message": {"content": "RESPONSE_END"}}]}}]
        response = self.client.get("/chat-trace", params={"key": self.key})
        self.assertEqual(response.status_code, 200)
        start = response.text.index('id="trace-data"')
        embedded = response.text[start:].split('>', 1)[1].split('</script>', 1)[0]
        self.assertEqual(json.loads(embedded)["rounds"], self.payload["rounds"])

    def test_harness_context_system_prompts_and_tool_definitions_are_preserved(self):
        injection = {
            "messages": [{"role": "system", "content": "SYSTEM_FULL"},
                         {"role": "user", "content": "USER_FULL"}],
            "system_messages": [{"role": "system", "content": "SYSTEM_FULL"}],
            "context_messages": [{"role": "user", "content": "USER_FULL"}],
            "tool_definitions": [{"type": "function", "name": "lookup",
                                  "parameters": {"type": "object"}}],
            "tool_choice": "auto",
        }
        self.payload["rounds"] = [{"index": 1, "tools": [], "context_injection": injection}]
        parsed = parse_chat_trace(json.dumps(self.payload))
        self.assertEqual(parsed["rounds"][0]["context_injection"], injection)
        response = self.client.get("/chat-trace", params={"key": self.key})
        for marker in ("System Prompt", "Context Injection", "Tool Definitions"):
            self.assertIn(marker, response.text)

    def test_trace_script_uses_request_payload_then_context_snapshot(self):
        script = (Path(__file__).resolve().parents[1]
                  / "templates/CommonPages/ChatTrace/app.js").read_text(encoding="utf-8")
        self.assertIn("request.messages", script)
        self.assertIn("injected.system_messages", script)
        self.assertIn("Tool Definition ·", script)


if __name__ == "__main__":
    unittest.main()
