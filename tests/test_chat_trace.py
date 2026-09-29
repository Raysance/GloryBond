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
        self.key = "a" * 48
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
        for key in ["", "../secret", "a" * 16, "a" * 49]:
            self.assertEqual(self.client.get("/chat-trace", params={"key": key}).status_code, 400)
        self.loader.assert_not_called()

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


if __name__ == "__main__":
    unittest.main()
