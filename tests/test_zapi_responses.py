import unittest
from types import SimpleNamespace

from local_debugger import import_hok_module


ZAPI = import_hok_module("zapi")


class ResponsesApiTests(unittest.TestCase):
    def test_uses_responses_api_and_normalizes_function_calls(self):
        original_openai = ZAPI.OpenAI
        original_qqbot = ZAPI.confs.get("QQBot")
        captured = {}

        response = SimpleNamespace(
            id="resp-1",
            model="test-model",
            output_text="",
            output=[
                SimpleNamespace(type="reasoning", encrypted_content="encrypted"),
                SimpleNamespace(
                    id="fc-1",
                    type="function_call",
                    call_id="call-1",
                    name="lookup",
                    arguments='{"name":"alpha"}',
                ),
            ],
        )

        class FakeResponses:
            @staticmethod
            def create(**kwargs):
                captured.update(kwargs)
                return response

        class FakeOpenAI:
            def __init__(self, **kwargs):
                captured["client"] = kwargs
                self.responses = FakeResponses()

        ZAPI.OpenAI = FakeOpenAI
        ZAPI.confs["QQBot"] = {
            "deepseek_key": "test-key",
            "deepseek_chat_model": "test-model",
        }
        try:
            result = ZAPI.ai_response_create(
                [{"role": "user", "content": "查alpha"}],
                tools=[{
                    "type": "function",
                    "name": "lookup",
                    "parameters": {"type": "object", "properties": {}},
                }],
            )
        finally:
            ZAPI.OpenAI = original_openai
            if original_qqbot is None:
                ZAPI.confs.pop("QQBot", None)
            else:
                ZAPI.confs["QQBot"] = original_qqbot

        self.assertEqual(captured["input"], [{"role": "user", "content": "查alpha"}])
        self.assertEqual(captured["tool_choice"], "auto")
        self.assertFalse(captured["store"])
        self.assertEqual(captured["include"], ["reasoning.encrypted_content"])
        self.assertEqual(result["response_id"], "resp-1")
        self.assertEqual(result["output_items"], response.output)
        self.assertEqual(result["tool_calls"], [{
            "id": "fc-1",
            "call_id": "call-1",
            "name": "lookup",
            "arguments": '{"name":"alpha"}',
        }])

    def test_network_mode_uses_ark_responses_endpoint_and_web_search(self):
        original_openai = ZAPI.OpenAI
        original_qqbot = ZAPI.confs.get("QQBot")
        captured = {}

        class FakeResponses:
            @staticmethod
            def create(**kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    id="resp-ark",
                    model="ark-responses-model",
                    output_text="联网结果",
                    output=[],
                )

        class FakeOpenAI:
            def __init__(self, **kwargs):
                captured["client"] = kwargs
                self.responses = FakeResponses()

        ZAPI.OpenAI = FakeOpenAI
        ZAPI.confs["QQBot"] = {
            "ark_key": "test-key",
            "ark_responses_model": "ark-responses-model",
        }
        try:
            result = ZAPI.ai_response_create(
                [{"role": "user", "content": "查新闻"}],
                tools=[{
                    "type": "function",
                    "name": "lookup",
                    "parameters": {"type": "object", "properties": {}},
                }],
                network=True,
            )
        finally:
            ZAPI.OpenAI = original_openai
            if original_qqbot is None:
                ZAPI.confs.pop("QQBot", None)
            else:
                ZAPI.confs["QQBot"] = original_qqbot

        self.assertEqual(captured["client"]["base_url"], ZAPI.ark_model_url)
        self.assertEqual(captured["model"], "ark-responses-model")
        self.assertIn({"type": "web_search"}, captured["tools"])
        self.assertEqual(result["content"], "联网结果")

    def test_reads_output_text_from_typed_message_items(self):
        response = SimpleNamespace(
            output_text="",
            output=[
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "第一段"},
                        {"type": "output_text", "text": "第二段"},
                    ],
                }
            ],
        )

        self.assertEqual(ZAPI._response_output_text(response), "第一段第二段")


if __name__ == "__main__":
    unittest.main()
