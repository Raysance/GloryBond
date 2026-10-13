import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from local_debugger import import_hok_module


ZAPI = import_hok_module("zapi")
AI_ADAPTER = import_hok_module("api_adapters.ai")
ZMEMORY = import_hok_module("zmemory")


TOOL_SCHEMA = {
    "type": "function",
    "name": "lookup",
    "description": "Look up one player",
    "parameters": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
    "strict": False,
}


def tool_call(call_id, name):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "lookup", "arguments": json.dumps({"name": name})},
    }


class ChatCompletionsApiTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "base_url": "https://api.deepseek.com",
            "api_key": "test-deepseek-key",
            "model": "deepseek-flash",
            "proxy_url": "",
            "tool_max_tokens": 4096,
            "final_max_tokens": 800,
        }
        self.requests = []
        self.responses = []
        self.client_options = []
        self.http_clients = []
        config_patch = patch.object(AI_ADAPTER, "chat_api_config", self.config)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        client_patch = patch.object(AI_ADAPTER, "DefaultHttpxClient", self.make_http_client)
        client_patch.start()
        self.addCleanup(client_patch.stop)
        history_patch = patch.object(ZMEMORY.instance, "load_active_chat_records", return_value=[])
        history_patch.start()
        self.addCleanup(history_patch.stop)

    def make_http_client(self, **kwargs):
        self.client_options.append(kwargs)
        client = httpx.Client(transport=httpx.MockTransport(self.handle_request), trust_env=False)
        self.http_clients.append(client)
        return client

    def handle_request(self, request):
        self.requests.append({
            "url": str(request.url),
            "authorization": request.headers.get("Authorization"),
            "body": json.loads(request.content),
        })
        self.assertTrue(self.responses, "Unexpected additional model request")
        return httpx.Response(200, json={
            "id": f"chatcmpl-{len(self.requests)}",
            "object": "chat.completion",
            "created": 0,
            "model": self.config["model"],
            "choices": [{
                "index": 0,
                "finish_reason": "stop",
                "message": self.responses.pop(0),
            }],
        })


    def test_chat_payload_direct_connection_and_normalized_tool_calls(self):
        call = tool_call("call-1", "alpha")
        assistant = {
            "role": "assistant",
            "content": "",
            "reasoning_content": "Need player data",
            "tool_calls": [call],
        }
        self.responses.append(assistant)

        result = ZAPI.ai_response_create(
            [{"role": "user", "content": "查 alpha"}],
            tools=[TOOL_SCHEMA],
        )

        request = self.requests[0]
        self.assertEqual(request["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(request["authorization"], "Bearer test-deepseek-key")
        self.assertEqual(request["body"], {
            "model": "deepseek-flash",
            "messages": [{"role": "user", "content": "查 alpha"}],
            "stream": False,
            "max_tokens": 4096,
            "tools": [{"type": "function", "function": {
                key: value for key, value in TOOL_SCHEMA.items() if key != "type"
            }}],
            "tool_choice": "auto",
            "thinking": {"type": "disabled"},
        })
        self.assertEqual(self.client_options, [{"trust_env": False}])
        self.assertTrue(self.http_clients[0].is_closed)
        self.assertEqual(result["response_id"], "chatcmpl-1")
        self.assertEqual(result["model"], "deepseek-flash")
        self.assertEqual(result["request_payload"], request["body"])
        self.assertEqual(result["response_payload"]["choices"][0]["message"], assistant)
        self.assertEqual(result["response_meta"]["finish_reason"], "stop")
        self.assertNotIn("headers", result)
        self.assertEqual(result["content"], "")
        self.assertEqual(result["output_items"], [assistant])
        self.assertEqual(result["tool_calls"], [{
            "id": "call-1",
            "call_id": "call-1",
            "name": "lookup",
            "arguments": call["function"]["arguments"],
        }])

    def test_adapter_uses_separate_tool_and_no_tool_output_caps(self):
        self.responses.extend([
            {"role": "assistant", "content": "", "tool_calls": [tool_call("call-1", "alpha")]},
            {"role": "assistant", "content": "alpha 为 42 分"},
        ])
        ZAPI.ai_response_create(
            [{"role": "user", "content": "查 alpha"}],
            tools=[TOOL_SCHEMA],
        )
        ZAPI.ai_response_create(
            [{"role": "user", "content": "总结"}],
            tools=None,
            tool_choice="none",
        )
        self.assertEqual(self.requests[0]["body"]["max_tokens"], 4096)
        self.assertEqual(self.requests[1]["body"]["max_tokens"], 800)

    def test_http_error_keeps_both_payloads_through_wrapper(self):
        body = {"error": {"message": "context length exceeded", "code": "context_length"}}
        with patch.object(self, "handle_request", return_value=httpx.Response(400, json=body)):
            with self.assertRaises(Exception) as raised:
                ZAPI.ai_response_create([{"role": "user", "content": "FULL_INPUT"}])
        trace_helpers = import_hok_module("business.chat_trace")
        payloads = trace_helpers.failed_request_payloads(raised.exception)
        self.assertEqual(payloads["request_payload"]["messages"][0]["content"], "FULL_INPUT")
        self.assertEqual(payloads["response_payload"], body)
        diagnostics = trace_helpers.error_record(raised.exception, "model_request")
        self.assertTrue(any(item.get("status_code") == 400 for item in diagnostics["causes"]))
        self.assertNotIn("Authorization", json.dumps(payloads))


    def test_missing_choices_and_invalid_json_still_keep_response_body(self):
        body = {"id": "empty", "model": "deepseek-chat", "choices": [],
                "usage": {"total_tokens": 100, "completion_tokens": 1}}
        with patch.object(self, "handle_request", return_value=httpx.Response(200, json=body)):
            result = ZAPI.ai_response_create([{"role": "user", "content": "输入"}])
        self.assertEqual(result["response_payload"], body)
        self.assertEqual(result["response_meta"]["finish_reason"], "missing_choice")
        self.assertEqual(result["response_meta"]["usage"], body["usage"])
        self.assertEqual(result["content"], "")
        with patch.object(self, "handle_request", return_value=httpx.Response(200, text="INVALID_BODY")):
            with self.assertRaises(Exception) as raised:
                ZAPI.ai_response_create([{"role": "user", "content": "输入"}])
        trace_helpers = import_hok_module("business.chat_trace")
        self.assertEqual(trace_helpers.failed_request_payloads(raised.exception)["response_payload"], "INVALID_BODY")


    def test_legacy_text_helpers_use_same_configured_client(self):
        self.responses.extend([
            {"role": "assistant", "content": "简单回答"},
            {"role": "assistant", "content": "函数回答"},
        ])

        self.assertEqual(ZAPI.ai_api("你好", 0.5), "简单回答")
        self.assertEqual(ZAPI.ai_function([{"role": "user", "content": "选一个"}]), "函数回答")

        self.assertEqual(self.requests[0]["body"]["messages"], [{"role": "user", "content": "你好"}])
        self.assertEqual(self.requests[0]["body"]["temperature"], 0.5)
        self.assertEqual(self.requests[1]["body"]["messages"], [{"role": "user", "content": "选一个"}])
        self.assertEqual(self.requests[1]["body"]["temperature"], 1)
        for request in self.requests:
            self.assertEqual(request["body"]["model"], "deepseek-flash")
            self.assertNotIn("tools", request["body"])
            self.assertNotIn("input", request["body"])
        self.assertTrue(all(client.is_closed for client in self.http_clients))

    def test_optional_proxy_is_used_only_when_explicitly_configured(self):
        self.config["proxy_url"] = "socks5h://127.0.0.1:18080"
        self.responses.append({"role": "assistant", "content": "代理回答"})

        self.assertEqual(ZAPI.ai_response_create(
            [{"role": "user", "content": "你好"}])["content"], "代理回答")

        self.assertEqual(self.client_options, [{
            "trust_env": False, "proxy": "socks5h://127.0.0.1:18080",
        }])

    def test_deepseek_tool_requests_disable_thinking_consistently(self):
        self.responses.append({"role": "assistant", "content": "", "tool_calls": [
            tool_call("call-1", "alpha"),
        ]})

        ZAPI.ai_response_create(
            [{"role": "user", "content": "查 alpha"}],
            tools=[TOOL_SCHEMA],
            tool_choice={"type": "function", "function": {"name": "lookup"}},
        )

        self.assertEqual(self.requests[0]["body"]["thinking"], {"type": "disabled"})
        self.assertNotIn("extra_body", self.requests[0]["body"])

    def test_deepseek_no_tools_continuation_keeps_tool_chain_non_thinking(self):
        assistant = {
            "role": "assistant",
            "content": "",
            "tool_calls": [tool_call("call-1", "alpha")],
        }
        self.responses.append({"role": "assistant", "content": "alpha 为 42 分"})

        result = ZAPI.ai_response_create([
            {"role": "user", "content": "查 alpha"},
            assistant,
            {"type": "function_call_output", "call_id": "call-1", "output": '{"score":42}'},
        ], tools=None, tool_choice="none")

        self.assertEqual(result["content"], "alpha 为 42 分")
        self.assertNotIn("tools", self.requests[0]["body"])
        self.assertEqual(self.requests[0]["body"]["tool_choice"], "none")
        self.assertEqual(self.requests[0]["body"]["thinking"], {"type": "disabled"})

    def test_deepseek_standalone_no_tools_request_retains_default_mode(self):
        self.responses.append({"role": "assistant", "content": "普通回答"})

        result = ZAPI.ai_response_create(
            [{"role": "user", "content": "你好"}], tools=None, tool_choice="none",
        )

        self.assertEqual(result["content"], "普通回答")
        self.assertNotIn("thinking", self.requests[0]["body"])


class ResponsesApiTests(unittest.TestCase):
    def test_network_mode_uses_ark_responses_endpoint_and_web_search(self):
        captured = {}
        function_call = SimpleNamespace(
            id="fc-1", type="function_call", call_id="call-1",
            name="lookup", arguments='{"name":"alpha"}',
        )
        output = [SimpleNamespace(type="reasoning", encrypted_content="encrypted"), function_call]

        class FakeResponses:
            @staticmethod
            def create(**kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    id="resp-ark", model="ark-responses-model", output_text="联网结果", output=output,
                )

        class FakeOpenAI:
            def __init__(self, **kwargs):
                captured["client"] = kwargs
                self.responses = FakeResponses()

        with patch.object(AI_ADAPTER, "OpenAI", FakeOpenAI), \
                patch.object(AI_ADAPTER, "DefaultHttpxClient") as proxy_client, \
                patch.dict(AI_ADAPTER.confs, {"QQBot": {
                    "ark_key": "test-key", "ark_responses_model": "ark-responses-model",
                }}):
            result = ZAPI.ai_response_create(
                [{"role": "user", "content": "查新闻"}], tools=[TOOL_SCHEMA], network=True,
            )
            proxy_client.assert_not_called()

        self.assertEqual(captured["client"], {"base_url": AI_ADAPTER.ark_model_url, "api_key": "test-key"})
        self.assertEqual(captured["input"], [{"role": "user", "content": "查新闻"}])
        self.assertEqual(captured["model"], "ark-responses-model")
        self.assertEqual(captured["tools"], [TOOL_SCHEMA, {"type": "web_search"}])
        self.assertEqual(captured["tool_choice"], "auto")
        self.assertFalse(captured["store"])
        self.assertEqual(captured["include"], ["reasoning.encrypted_content"])
        self.assertEqual(result["content"], "联网结果")
        self.assertEqual(result["output_items"], output)
        self.assertEqual(result["tool_calls"], [{
            "id": "fc-1", "call_id": "call-1", "name": "lookup", "arguments": '{"name":"alpha"}',
        }])

    def test_reads_output_text_from_typed_message_items(self):
        response = SimpleNamespace(
            output_text="",
            output=[{
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "第一段"},
                    {"type": "output_text", "text": "第二段"},
                ],
            }],
        )

        self.assertEqual(ZAPI._response_output_text(response), "第一段第二段")


if __name__ == "__main__":
    unittest.main()
