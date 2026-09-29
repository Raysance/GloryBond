import unittest
import traceback
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from local_debugger import import_hok_module


AI_ADAPTER = import_hok_module("api_adapters.ai")
ZAPI = import_hok_module("zapi")


def response_with_search(*, sources=None, annotations=None, text="已联网核实的结果", status="completed"):
    return SimpleNamespace(
        id="response-test", model="ark-test-model", status=status, output_text=text,
        output=[
            {"type": "web_search_call", "status": "completed", "action": {"sources": sources or []}},
            SimpleNamespace(type="message", content=[
                {"type": "output_text", "text": text, "annotations": annotations or []},
            ]),
        ],
    )


class ArkWebSearchTests(unittest.TestCase):
    def setUp(self):
        config_patch = patch.dict(AI_ADAPTER.confs, {
            "QQBot": {"ark_key": "private-ark-test-key", "ark_responses_model": "ark-test-model"},
        })
        config_patch.start()
        self.addCleanup(config_patch.stop)
        self.openai_patch = patch.object(AI_ADAPTER, "OpenAI")
        self.openai = self.openai_patch.start()
        self.addCleanup(self.openai_patch.stop)
        self.client = MagicMock()
        self.openai.return_value.__enter__.return_value = self.client

    def test_search_has_its_own_ark_request_and_extracts_only_metadata_sources(self):
        self.client.responses.create.return_value = response_with_search(
            annotations=[
                {"type": "url_citation", "title": "正式引用", "url": "https://example.com/cited"},
                SimpleNamespace(type="url_citation", title="第二来源", url="https://example.com/second"),
                {"type": "url_citation", "title": "重复", "url": "https://example.com/cited"},
                {"type": "url_citation", "title": "无效网址", "url": "javascript:invalid"},
            ],
            sources=[
                {"title": "重复搜索来源", "url": "https://example.com/cited"},
                {"title": "已搜索来源", "url": "https://example.com/searched"},
            ],
            text="答案包含一个未经证实的链接 https://fabricated.example，不能作为元数据来源",
        )

        result = ZAPI.ark_web_search("  王者近期更新  ", max_results=3)

        self.assertEqual(result["query"], "王者近期更新")
        self.assertEqual(result["provider"], "ark")
        self.assertEqual(result["response_id"], "response-test")
        self.assertEqual(result["sources"], [
            {"title": "正式引用", "url": "https://example.com/cited"},
            {"title": "第二来源", "url": "https://example.com/second"},
            {"title": "已搜索来源", "url": "https://example.com/searched"},
        ])
        request = self.client.responses.create.call_args.kwargs
        self.assertEqual(request["model"], "ark-test-model")
        self.assertEqual(request["tools"], [{"type": "web_search", "limit": 3}])
        self.assertEqual(request["tool_choice"], {"type": "web_search"})
        self.assertEqual(request["input"][-1], {"role": "user", "content": "王者近期更新"})
        self.assertFalse(request["store"])
        self.assertFalse(request["stream"])
        self.client.chat.completions.create.assert_not_called()
        self.openai.return_value.__exit__.assert_called_once()

    def test_source_count_is_limited_and_empty_search_results_are_valid(self):
        self.client.responses.create.return_value = response_with_search(sources=[
            {"url": "https://example.com/one"}, {"url": "https://example.com/two"},
        ])
        self.assertEqual(len(ZAPI.ark_web_search("query", max_results=1)["sources"]), 1)
        self.client.responses.create.return_value = response_with_search(text="未找到可核验的相关结果")
        self.assertEqual(ZAPI.ark_web_search("query")["sources"], [])

    def test_endpoint_failure_is_a_tool_error_and_redacts_configured_credentials(self):
        self.client.responses.create.side_effect = RuntimeError("closed endpoint private-ark-test-key")

        with self.assertRaisesRegex(RuntimeError, "ark_web_search unavailable") as caught:
            ZAPI.ark_web_search("query")

        self.assertNotIn("private-ark-test-key", str(caught.exception))
        self.assertIn("closed endpoint", str(caught.exception))
        self.assertNotIn("private-ark-test-key", "".join(traceback.format_exception(caught.exception)))

    def test_no_search_call_incomplete_or_empty_response_is_not_claimed_success(self):
        no_search = response_with_search()
        no_search.output = no_search.output[1:]
        for response in (no_search, response_with_search(status="incomplete"), response_with_search(text="")):
            with self.subTest(response=response):
                self.client.responses.create.return_value = response
                with self.assertRaisesRegex(RuntimeError, "ark_web_search unavailable"):
                    ZAPI.ark_web_search("query")

    def test_invalid_arguments_or_missing_configuration_do_not_request_network(self):
        for query, limit in (("", 5), ("query", True), ("query", 0), ("query", 11), ([], 5)):
            with self.subTest(query=query, limit=limit), self.assertRaises(ValueError):
                ZAPI.ark_web_search(query, max_results=limit)
        with patch.dict(AI_ADAPTER.confs, {"QQBot": {}}):
            with self.assertRaisesRegex(RuntimeError, "configure QQBot"):
                ZAPI.ark_web_search("query")
        self.openai.assert_not_called()


if __name__ == "__main__":
    unittest.main()
