import unittest

from local_debugger import import_hok_module


DIAGNOSTIC = import_hok_module("tools.chat_runtime_diagnostic")


class ChatRuntimeDiagnosticTests(unittest.TestCase):
    def test_configuration_check_requires_deepseek_flash_without_proxy(self):
        good = DIAGNOSTIC.configuration_check({
            "base_url": "https://api.deepseek.com",
            "api_key": "secret",
            "model": "deepseek-flash",
            "proxy_url": "",
        })
        self.assertEqual(good["status"], "ok")
        self.assertTrue(good["direct_connection"])
        self.assertNotIn("secret", str(good))

        bad = DIAGNOSTIC.configuration_check({
            "base_url": "https://example.test",
            "api_key": "",
            "model": "other",
            "proxy_url": "http://proxy.test",
        })
        self.assertEqual(bad["status"], "failed")

    def test_run_diagnostics_exercises_text_and_tool_continuation(self):
        requests = []

        def fake_ai_create(input_items, tools=None, tool_choice="auto", network=False):
            requests.append({
                "input_items": input_items,
                "tools": tools,
                "tool_choice": tool_choice,
                "network": network,
            })
            if not tools:
                return {"content": "HOK_HEALTH_OK", "model": "deepseek-flash"}
            if len(requests) == 2:
                return {
                    "content": "",
                    "model": "deepseek-flash",
                    "tool_calls": [{
                        "id": "call-health",
                        "call_id": "call-health",
                        "name": "health_probe",
                        "arguments": '{"token":"HOK_TOOL_PROBE"}',
                    }],
                    "output_items": [{
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": "call-health",
                            "type": "function",
                            "function": {
                                "name": "health_probe",
                                "arguments": '{"token":"HOK_TOOL_PROBE"}',
                            },
                        }],
                    }],
                }
            return {"content": "probe complete", "model": "deepseek-flash", "tool_calls": []}

        report = DIAGNOSTIC.run_diagnostics({
            "base_url": "https://api.deepseek.com",
            "api_key": "secret",
            "model": "deepseek-flash",
            "proxy_url": "",
        }, fake_ai_create)

        self.assertEqual(report["status"], "ok")
        self.assertEqual([item["name"] for item in report["checks"]], [
            "configuration", "text_completion", "tool_continuation",
        ])
        self.assertEqual(len(requests), 3)
        self.assertEqual(requests[0]["tool_choice"], "none")
        self.assertEqual(requests[1]["tool_choice"]["function"]["name"], "health_probe")
        self.assertEqual(requests[2]["tool_choice"], "auto")
        self.assertEqual(requests[2]["input_items"][-1]["call_id"], "call-health")

    def test_errors_are_redacted(self):
        def fail(*args, **kwargs):
            raise RuntimeError("bad key sk-secretvalue123456")

        result = DIAGNOSTIC.text_completion_check(fail, "sk-secretvalue123456")
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("sk-secretvalue123456", result["error"])
        self.assertIn("[redacted]", result["error"])


if __name__ == "__main__":
    unittest.main()
