import json
import unittest
from unittest.mock import patch

from local_debugger import import_hok_module


AI_ADAPTER = import_hok_module("api_adapters.ai")
ZAPI = import_hok_module("zapi")


class FakeResponse:
    def __init__(self, payload, status_error=None):
        self.payload = payload
        self.status_error = status_error

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def json(self):
        return self.payload


class AliyunWebSearchTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "endpoint": "https://default-test.platform-cn-shanghai.opensearch.aliyuncs.com",
            "api_key": "private-aliyun-test-key",
            "workspace": "default",
            "service_id": "ops-web-search-001",
            "content_type": "snippet",
            "way": "pro",
            "query_rewrite": True,
        }
        config_patch = patch.object(AI_ADAPTER, "aliyun_search_config", self.config)
        config_patch.start()
        self.addCleanup(config_patch.stop)

    def test_search_calls_direct_api_and_normalizes_results(self):
        payload = {
            "request_id": "request-1",
            "usage": {"ops-web-search-001/pro": 1},
            "result": {"search_result": [
                {
                    "title": "正式来源",
                    "link": "https://example.com/cited",
                    "snippet": "网页摘要",
                    "content": "网页内容",
                    "meta_info": {"publishedTime": "2026-09-30T10:00:00+08:00"},
                },
                {"title": "第二来源", "link": "https://example.com/two", "snippet": "第二条摘要"},
                {"title": "无效链接", "link": "javascript:bad", "snippet": "不可采用"},
            ]},
        }
        with patch.object(AI_ADAPTER, "direct_request", return_value=FakeResponse(payload)) as request:
            result = ZAPI.aliyun_web_search("  王者近期更新  ", max_results=2)

        self.assertEqual(result["provider"], "aliyun_opensearch")
        self.assertEqual(result["query"], "王者近期更新")
        self.assertEqual(result["response_id"], "request-1")
        self.assertEqual(result["search_requests"], 1)
        self.assertEqual(result["sources"], [
            {"title": "正式来源", "url": "https://example.com/cited"},
            {"title": "第二来源", "url": "https://example.com/two"},
        ])
        self.assertIn("网页内容", result["answer"])
        self.assertIn("2026-09-30T10:00:00+08:00", result["answer"])
        args, kwargs = request.call_args
        self.assertEqual(args, (
            "POST",
            "https://default-test.platform-cn-shanghai.opensearch.aliyuncs.com/"
            "v3/openapi/workspaces/default/web-search/ops-web-search-001",
        ))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer private-aliyun-test-key")
        self.assertEqual(kwargs["json"], {
            "query": "王者近期更新",
            "query_rewrite": True,
            "top_k": 2,
            "content_type": "snippet",
            "way": "pro",
        })
        self.assertNotIn("private-aliyun-test-key", json.dumps(kwargs["json"]))

    def test_empty_search_results_are_valid(self):
        payload = {"request_id": "request-empty", "result": {"search_result": []}}
        with patch.object(AI_ADAPTER, "direct_request", return_value=FakeResponse(payload)):
            result = ZAPI.aliyun_web_search("query")
        self.assertEqual(result["sources"], [])
        self.assertIn("未返回", result["answer"])

    def test_failures_redact_key_and_missing_config_never_requests(self):
        with patch.object(
            AI_ADAPTER,
            "direct_request",
            side_effect=RuntimeError("failed private-aliyun-test-key"),
        ):
            with self.assertRaises(RuntimeError) as caught:
                ZAPI.aliyun_web_search("query")
        self.assertNotIn("private-aliyun-test-key", str(caught.exception))

        with patch.object(AI_ADAPTER, "aliyun_search_config", {**self.config, "api_key": ""}), \
                patch.object(AI_ADAPTER, "direct_request") as request:
            with self.assertRaisesRegex(RuntimeError, "HOK_ALIYUN_SEARCH_API_KEY"):
                ZAPI.aliyun_web_search("query")
            request.assert_not_called()

    def test_provider_error_and_insecure_endpoint_are_rejected(self):
        payload = {"code": "InvalidParameter", "http_code": 400, "message": "bad query"}
        with patch.object(AI_ADAPTER, "direct_request", return_value=FakeResponse(payload)):
            with self.assertRaisesRegex(RuntimeError, "InvalidParameter"):
                ZAPI.aliyun_web_search("query")

        with patch.object(AI_ADAPTER, "aliyun_search_config", {
            **self.config, "endpoint": "http://insecure.example.test",
        }), patch.object(AI_ADAPTER, "direct_request") as request:
            with self.assertRaisesRegex(RuntimeError, "valid HTTPS URL"):
                ZAPI.aliyun_web_search("query")
            request.assert_not_called()

    def test_invalid_arguments_are_rejected_locally(self):
        for query, limit in (("", 5), ([], 5), ("query", True), ("query", 0), ("query", 11)):
            with self.subTest(query=query, limit=limit), self.assertRaises(ValueError):
                ZAPI.aliyun_web_search(query, max_results=limit)


if __name__ == "__main__":
    unittest.main()
