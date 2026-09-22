import unittest

from local_debugger import import_hok_module


ZAPI = import_hok_module("zapi")


class ArkApiTests(unittest.TestCase):
    def test_returns_empty_string_when_ark_request_fails(self):
        original_openai = ZAPI.OpenAI
        original_append_log = ZAPI.append_hok_exception_log
        original_qqbot = ZAPI.confs.get("QQBot")
        logged = []

        class FailingCompletions:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("endpoint closed")

        class FailingOpenAI:
            def __init__(self, **kwargs):
                self.chat = type("Chat", (), {"completions": FailingCompletions()})()

        ZAPI.OpenAI = FailingOpenAI
        ZAPI.confs["QQBot"] = {"ark_key": "test-key", "ark_bot_id": "test-bot"}
        ZAPI.append_hok_exception_log = lambda error, context=None: logged.append(
            (error, context)
        )
        try:
            result = ZAPI.ark_api("fetch news")
        finally:
            ZAPI.OpenAI = original_openai
            ZAPI.append_hok_exception_log = original_append_log
            if original_qqbot is None:
                ZAPI.confs.pop("QQBot", None)
            else:
                ZAPI.confs["QQBot"] = original_qqbot

        self.assertEqual(result, "")
        self.assertEqual(logged[0][1], {"function": "ark_api"})
        self.assertIn("endpoint closed", logged[0][0])


if __name__ == "__main__":
    unittest.main()
