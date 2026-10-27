"""Standalone Search API contract and the shared QQ/Web worker route."""
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlparse

from local_debugger import import_hok_module
from agent_console import remote_worker
from agent_console.tools.application import WebArgs

AI = import_hok_module("api_adapters.ai")
ZAPI = import_hok_module("zapi")
ROOT = Path(__file__).resolve().parents[1]


class DeepSeekSearchTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "endpoint": "https://api.deepseek.com/v1/tools/search",
            "api_key_env": "HOK_DEEPSEEK_API_KEY", "api_key": "private-search-key",
            "timeout_seconds": 30, "need_content": False, "max_result_chars": 6000,
        }
        self.patch = patch.object(AI, "deepseek_search_config", self.config)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def search(self, payload, *, status=200, **args):
        self.request = Mock(return_value=Mock(status_code=status, json=Mock(return_value=payload)))
        with patch.object(AI, "direct_request", self.request):
            return ZAPI.deepseek_web_search("  王者更新 site:pvp.qq.com  ", **args)

    def test_official_request_and_summary_date_source_normalization(self):
        result = self.search({"results": [
            {"title": "官方更新", "url": "https://pvp.qq.com/a", "snippet": "短摘要",
             "summary": "供模型阅读的长摘要", "content": "", "date": "2026-10-17T00:00:00Z"},
            {"title": "重复", "url": "https://pvp.qq.com/a"},
            {"url": "javascript:bad"}, {"url": "https://user:secret@example.com/"},
            {"title": "第二来源", "url": "https://example.com/b", "snippet": "后备摘要"},
        ]}, max_results=2)
        self.assertEqual(result["provider"], "deepseek_search")
        self.assertEqual(result["sources"], [{"title": "官方更新", "url": "https://pvp.qq.com/a"},
                                             {"title": "第二来源", "url": "https://example.com/b"}])
        self.assertIn("供模型阅读的长摘要", result["answer"])
        self.assertIn("2026-10-17T00:00:00Z", result["answer"])
        self.assertIn("后备摘要", result["answer"])
        args, kwargs = self.request.call_args
        self.assertEqual(args, ("POST", self.config["endpoint"]))
        self.assertEqual(kwargs["json"], {"query": "王者更新 site:pvp.qq.com", "count": 2, "need_content": False})
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer private-search-key")
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["timeout"], 30)

    def test_empty_search_content_and_bounded_observation(self):
        result = self.search({"results": []})
        self.assertEqual(result["sources"], [])
        self.assertIn("未返回", result["answer"])
        self.config.update(need_content=True, max_result_chars=10)
        result = self.search({"results": [{"url": "https://example.com/", "content": "正文" * 100, "summary": "不选摘要"}]})
        self.assertIn("正文" * 5, result["answer"])
        self.assertNotIn("正文" * 6, result["answer"])
        self.assertTrue(self.request.call_args.kwargs["json"]["need_content"])

    def test_invalid_args_config_and_long_query_never_request(self):
        with patch.object(AI, "direct_request") as request:
            for query, count in [("", 5), (" ", 5), ([], 5), ("字" * 129, 5), ("q", True), ("q", 0), ("q", 11)]:
                with self.subTest(query=query, count=count), self.assertRaises(ValueError):
                    ZAPI.deepseek_web_search(query, count)
            for endpoint in ["http://example.com/", "https://user:password@example.com/", ""]:
                self.config["endpoint"] = endpoint
                with self.assertRaisesRegex(RuntimeError, "HTTPS"):
                    ZAPI.deepseek_web_search("q")
            self.config["api_key"] = ""
            with self.assertRaisesRegex(RuntimeError, "HOK_DEEPSEEK_API_KEY"):
                ZAPI.deepseek_web_search("q")
            request.assert_not_called()
        with self.assertRaises(ValueError):
            WebArgs(query="字" * 129)
        self.assertEqual(WebArgs(query="字" * 128).query, "字" * 128)

    def test_http_and_malformed_responses_do_not_leak_body_or_fallback(self):
        for status in (301, 400, 401, 402, 429, 500, 504):
            with self.subTest(status=status), patch.object(AI, "aliyun_web_search") as old:
                with self.assertRaisesRegex(RuntimeError, f"HTTP {status}") as error:
                    self.search({"error": {"message": "private-search-key sensitive-body"}}, status=status)
                self.assertNotIn("private-search-key", str(error.exception))
                self.assertNotIn("sensitive-body", str(error.exception))
                old.assert_not_called()
        for payload in ([], {}, {"results": None}):
            with self.subTest(payload=payload), self.assertRaises(RuntimeError):
                self.search(payload)
        with patch.object(AI, "direct_request", side_effect=RuntimeError("private-search-key")):
            with self.assertRaises(RuntimeError) as error:
                ZAPI.deepseek_web_search("q")
            self.assertNotIn("private-search-key", str(error.exception))

    def test_worker_extracts_same_config_and_function_and_routes_only_to_deepseek(self):
        namespace = {"urlparse": urlparse}
        remote_worker.extracted_functions(ROOT / "hok/zstatic.py", ["_build_deepseek_search_config"], namespace)
        config = namespace["_build_deepseek_search_config"]({"DeepSeekSearch": self.config,
                   "ChatAPI": {"api_key_env": "OTHER_KEY"}},
                   {"HOK_DEEPSEEK_API_KEY": "search-key", "OTHER_KEY": "wrong-provider-key"})
        self.assertEqual(config["api_key"], "search-key")
        namespace.update(deepseek_search_config=config,
                         direct_request=Mock(return_value=Mock(status_code=200, json=lambda: {"results": []})))
        remote_worker.extracted_functions(ROOT / "hok/api_adapters/ai.py", ["deepseek_web_search"], namespace)
        old = Mock(side_effect=AssertionError("legacy search must not run"))
        with patch.dict(remote_worker.CONTEXT, {"store": Mock(), "api": {**namespace, "aliyun_web_search": old}}):
            result = remote_worker.dispatch({"op": "web_search", "query": "q", "max_results": 1})
        self.assertEqual(result["provider"], "deepseek_search")
        old.assert_not_called()
        self.assertEqual(namespace["direct_request"].call_args.kwargs["headers"]["Authorization"], "Bearer search-key")


if __name__ == "__main__":
    unittest.main()
