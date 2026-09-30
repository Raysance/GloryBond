import unittest
from types import SimpleNamespace
from unittest.mock import patch

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

    def test_configuration_detects_running_process_credential_mismatch(self):
        config = {
            "base_url": "https://api.deepseek.com",
            "api_key": "current-secret",
            "model": "deepseek-flash",
            "proxy_url": "",
        }
        with patch.dict("os.environ", {"HOK_DIAGNOSTIC_EXPECTED_KEY_SHA256": "wrong"}):
            result = DIAGNOSTIC.configuration_check(config)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["credential_comparison_available"])
        self.assertFalse(result["credential_matches_running_process"])
        self.assertNotIn("current-secret", str(result))

    def test_storage_database_history_and_search_checks_return_only_summaries(self):
        class FakeRedis:
            connection_pool = SimpleNamespace(connection_kwargs={"db": 0})

            @staticmethod
            def ping():
                return True

        fake_zfunc = SimpleNamespace(
            chat_active_dialogue_load=lambda *args, **kwargs: [],
            chat_memory_list=lambda *args, **kwargs: {"memories": [], "total": 0},
            chat_roleplay_get=lambda *args, **kwargs: None,
        )
        redis_result = DIAGNOSTIC.redis_storage_check(FakeRedis(), fake_zfunc)
        self.assertEqual(redis_result["status"], "ok")

        database_result = DIAGNOSTIC.game_database_check(
            lambda: {"ok": True, "tables": {str(index): {} for index in range(10)}},
            lambda sql: {"ok": True, "normalized_sql": sql},
            lambda sql, limit: {
                "ok": True, "row_count": 1, "rows": [{"private": "not returned"}],
                "truncated": False,
            },
        )
        self.assertEqual(database_result["status"], "ok")
        self.assertNotIn("private", str(database_result))

        history_result = DIAGNOSTIC.group_history_check(
            lambda: [{"group_id": "123", "message_count": 20}],
            lambda: [{"group_id": "123", "message_count": 20}],
            lambda *args, **kwargs: [{"text": "private chat message"}],
        )
        self.assertEqual(history_result["status"], "ok")
        self.assertEqual(history_result["archived_message_count"], 20)
        self.assertNotIn("private chat message", str(history_result))

        history_sql_result = DIAGNOSTIC.group_history_database_check(
            lambda: {"ok": True, "scope_mode": "current_group",
                     "tables": {"chat_history_messages": {}}},
            lambda sql: {"ok": True, "normalized_sql": sql},
            lambda sql, limit, group_id: {
                "ok": True, "row_count": 1,
                "rows": [{"message_count": 20, "private": "not returned"}],
            },
        )
        self.assertEqual(history_sql_result["status"], "ok")
        self.assertTrue(history_sql_result["scoped_view_ready"])
        self.assertNotIn("private", str(history_sql_result))

        search_result = DIAGNOSTIC.web_search_check(lambda *args, **kwargs: {
            "answer": "private web answer",
            "sources": [{"url": "https://example.test"}],
            "provider": "aliyun_opensearch",
            "service_id": "ops-web-search-001",
            "search_requests": 1,
        })
        self.assertEqual(search_result["status"], "ok")
        self.assertNotIn("private web answer", str(search_result))

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
