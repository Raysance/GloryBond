import unittest
from types import SimpleNamespace
from unittest.mock import patch

from local_debugger import import_hok_module


PROXY = import_hok_module("api_adapters.proxy")
STEAM = import_hok_module("api_adapters.steam")
AI = import_hok_module("api_adapters.ai")


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, responses, calls):
        self.responses = responses
        self.calls = calls
        self.trust_env = True
        self.proxies = {}
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.closed = True

    def request(self, method, url, **kwargs):
        self.calls.append({
            "method": method,
            "url": url,
            "kwargs": kwargs,
            "trust_env": self.trust_env,
            "proxies": dict(self.proxies),
        })
        return self.responses.pop(0)


class ClashProxyRoutingTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.sessions = []
        self.responses = []

        def session_factory():
            session = FakeSession(self.responses, self.calls)
            self.sessions.append(session)
            return session

        self.session_patch = patch.object(PROXY.requests, "Session", side_effect=session_factory)
        self.proxy_patch = patch.object(PROXY, "clash_proxy_url", "http://127.0.0.1:7890")
        self.session_patch.start()
        self.proxy_patch.start()
        self.addCleanup(self.session_patch.stop)
        self.addCleanup(self.proxy_patch.stop)

    def assert_clash_call(self, call):
        self.assertFalse(call["trust_env"])
        self.assertEqual(call["proxies"], {
            "http": "http://127.0.0.1:7890",
            "https": "http://127.0.0.1:7890",
        })

    def test_steam_status_and_recent_games_use_clash(self):
        self.responses.extend([
            FakeResponse({"response": {"players": [{"personaname": "Tester"}]}}),
            FakeResponse({"response": {"games": [{"appid": 1}]}}),
        ])

        self.assertEqual(STEAM.steam_api_user_status("key", "steam-1")["personaname"], "Tester")
        self.assertEqual(STEAM.steam_api_recent_games("key", "steam-1"), [{"appid": 1}])

        self.assertEqual([call["method"] for call in self.calls], ["GET", "GET"])
        self.assertTrue(all(session.closed for session in self.sessions))
        for call in self.calls:
            self.assert_clash_call(call)

    def test_apimart_submit_and_poll_use_clash(self):
        self.responses.extend([
            FakeResponse({"code": 200, "data": [{"task_id": "task-1"}]}),
            FakeResponse({"code": 200, "data": {
                "status": "completed",
                "result": {"images": [{"url": ["https://example.test/result.png"]}]},
            }}),
        ])

        with patch.dict(AI.confs, {"QQBot": {"apimart_key": "test-key"}}), \
                patch.object(AI.dmc, "EmojiImageModel", "test-model"):
            result = AI.apimart_images_generate(
                prompt="test", reference_image_url="", size="1:1", resolution="1k",
                task_timeout_seconds=2, task_poll_interval_seconds=1,
            )

        self.assertEqual(result["url"], "https://example.test/result.png")
        self.assertEqual([call["method"] for call in self.calls], ["POST", "GET"])
        self.assertTrue(all(session.closed for session in self.sessions))
        for call in self.calls:
            self.assert_clash_call(call)

    def test_missing_clash_proxy_refuses_request(self):
        with patch.object(PROXY, "clash_proxy_url", ""):
            with self.assertRaisesRegex(ValueError, "Clash proxy configuration missing"):
                PROXY.clash_request("GET", "https://example.test")

        self.assertEqual(self.calls, [])
        self.assertEqual(self.sessions, [])

    def test_direct_request_disables_environment_and_has_no_proxy(self):
        self.responses.append(FakeResponse({"ok": True}))

        result = PROXY.direct_request("POST", "https://example.test", json={"query": "test"})

        self.assertEqual(result.json(), {"ok": True})
        self.assertFalse(self.calls[0]["trust_env"])
        self.assertEqual(self.calls[0]["proxies"], {})
        self.assertTrue(self.sessions[0].closed)


if __name__ == "__main__":
    unittest.main()
