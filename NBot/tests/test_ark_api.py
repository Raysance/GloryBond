import unittest

from local_debugger import import_hok_module


ZAPI = import_hok_module("zapi")
AI_ADAPTER = import_hok_module("api_adapters.ai")


class ArkApiTests(unittest.TestCase):
    def test_returns_empty_string_when_ark_request_fails(self):
        original_openai = AI_ADAPTER.OpenAI
        original_append_log = AI_ADAPTER.append_hok_exception_log
        original_qqbot = AI_ADAPTER.confs.get("QQBot")
        logged = []

        class FailingResponses:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("endpoint closed")

        class FailingOpenAI:
            def __init__(self, **kwargs):
                self.responses = FailingResponses()

        AI_ADAPTER.OpenAI = FailingOpenAI
        AI_ADAPTER.confs["QQBot"] = {"ark_key": "test-key", "ark_responses_model": "test-model"}
        AI_ADAPTER.append_hok_exception_log = lambda error, context=None: logged.append(
            (error, context)
        )
        try:
            result = ZAPI.ark_api("fetch news")
        finally:
            AI_ADAPTER.OpenAI = original_openai
            AI_ADAPTER.append_hok_exception_log = original_append_log
            if original_qqbot is None:
                AI_ADAPTER.confs.pop("QQBot", None)
            else:
                AI_ADAPTER.confs["QQBot"] = original_qqbot

        self.assertEqual(result, "")
        self.assertEqual(logged[0][1], {"function": "ark_api"})
        self.assertIn("endpoint closed", logged[0][0])


if __name__ == "__main__":
    unittest.main()
