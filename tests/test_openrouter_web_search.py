import json
import os
import unittest
from unittest.mock import patch

from local_debugger import import_hok_module


AI_ADAPTER = import_hok_module("api_adapters.ai")
ZAPI = import_hok_module("zapi")
ZSTATIC = import_hok_module("zstatic")


class FakeResponse:
    def __init__(self, payload, status_error=None):
        self.payload = payload
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def json(self):
        return self.payload


class OpenRouterWebSearchTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "base_url": "https://openrouter.ai/api/v1/chat/completions",
            "api_key": "private-openrouter-test-key",
            "model": "openrouter/auto",
            "engine": "auto",
        }
        config_patch = patch.object(AI_ADAPTER, "openrouter_search_config", self.config)
        config_patch.start()
        self.addCleanup(config_patch.stop)

    def test_static_variables_supply_default_api_key(self):
        self.assertTrue(ZSTATIC.openrouter_api_key)
        expected = os.environ.get("HOK_OPENROUTER_API_KEY") or ZSTATIC.openrouter_api_key
        self.assertEqual(ZSTATIC.openrouter_search_config["api_key"], expected)

    def test_search_uses_server_tool_and_clash_proxy_adapter(self):
        payload = {
            "id": "gen-1",
            "model": "openai/gpt-test",
            "choices": [{"message": {
                "role": "assistant",
                "content": "已核实的联网结果",
                "annotations": [
                    {"type": "url_citation", "url_citation": {
                        "title": "正式来源", "url": "https://example.com/cited"}},
                    {"type": "url_citation", "title": "第二来源", "url": "https://example.com/two"},
                    {"type": "url_citation", "url": "javascript:bad"},
                ],
            }}],
            "usage": {"server_tool_use": {"web_search_requests": 1}},
        }
        with patch.object(AI_ADAPTER, "clash_request", return_value=FakeResponse(payload)) as request:
            result = ZAPI.openrouter_web_search("  王者近期更新  ", max_results=2)

        self.assertEqual(result["provider"], "openrouter")
        self.assertEqual(result["query"], "王者近期更新")
        self.assertEqual(result["search_requests"], 1)
        self.assertEqual(result["sources"], [
            {"title": "正式来源", "url": "https://example.com/cited"},
            {"title": "第二来源", "url": "https://example.com/two"},
        ])
        args, kwargs = request.call_args
        self.assertEqual(args, ("POST", self.config["base_url"]))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer private-openrouter-test-key")
        self.assertEqual(kwargs["json"]["tools"], [{"type": "openrouter:web_search", "parameters": {
            "engine": "auto", "max_results": 2, "max_total_results": 2, "max_uses": 2,
        }}])
        self.assertEqual(kwargs["json"]["max_tool_calls"], 2)
        self.assertNotIn("private-openrouter-test-key", json.dumps(kwargs["json"]))

    def test_search_requires_evidence_that_server_tool_ran(self):
        payload = {"choices": [{"message": {"content": "未搜索的普通回答"}}], "usage": {}}
        with patch.object(AI_ADAPTER, "clash_request", return_value=FakeResponse(payload)):
            with self.assertRaisesRegex(RuntimeError, "did not execute"):
                ZAPI.openrouter_web_search("query")

    def test_failures_redact_key_and_missing_config_never_requests(self):
        with patch.object(AI_ADAPTER, "clash_request",
                          side_effect=RuntimeError("failed private-openrouter-test-key")):
            with self.assertRaises(RuntimeError) as caught:
                ZAPI.openrouter_web_search("query")
        self.assertNotIn("private-openrouter-test-key", str(caught.exception))

        with patch.object(AI_ADAPTER, "openrouter_search_config", {**self.config, "api_key": ""}), \
                patch.object(AI_ADAPTER, "clash_request") as request:
            with self.assertRaisesRegex(RuntimeError, "OpenRouterSearch.api_key"):
                ZAPI.openrouter_web_search("query")
            request.assert_not_called()

    def test_invalid_arguments_are_rejected_locally(self):
        for query, limit in (("", 5), ([], 5), ("query", True), ("query", 0), ("query", 11)):
            with self.subTest(query=query, limit=limit), self.assertRaises(ValueError):
                ZAPI.openrouter_web_search(query, max_results=limit)


if __name__ == "__main__":
    unittest.main()
