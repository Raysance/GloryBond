import unittest
from unittest.mock import patch

from local_debugger import import_hok_module


AI_PROMPTS = import_hok_module("business.ai_prompts")
ZFUNC = import_hok_module("zfunc")


class AiPromptTests(unittest.TestCase):
    def setUp(self):
        self.originals = {
            "random": AI_PROMPTS.ztime.get_timebased_rand,
            "ai": AI_PROMPTS.zapi.ai_api,
            "ark": AI_PROMPTS.zapi.ark_api,
        }
        AI_PROMPTS.ztime.get_timebased_rand = lambda count, gap: 0

    def tearDown(self):
        AI_PROMPTS.ztime.get_timebased_rand = self.originals["random"]
        AI_PROMPTS.zapi.ai_api = self.originals["ai"]
        AI_PROMPTS.zapi.ark_api = self.originals["ark"]

    def test_pure_chat_uses_standard_ai_adapter(self):
        calls = []
        AI_PROMPTS.zapi.ai_api = lambda **kwargs: calls.append(kwargs) or "reply"

        result = ZFUNC.ai_parser(["hello"], "pure_chat")

        self.assertEqual(result, "reply")
        self.assertEqual(
            calls,
            [{"user_query": "hello", "temperature": 1.5}],
        )

    def test_network_chat_uses_ark_adapter_with_network_prompt(self):
        calls = []
        AI_PROMPTS.zapi.ark_api = lambda prompt: calls.append(prompt) or "network"

        result = ZFUNC.ai_parser(["latest"], "pure_chat", network=True)

        self.assertEqual(result, "network")
        self.assertEqual(calls, [AI_PROMPTS.ark_chat_pmpt + "latest"])

    def test_ranking_prompt_reads_current_dynamic_news(self):
        calls = []
        AI_PROMPTS.zapi.ai_api = lambda **kwargs: calls.append(kwargs) or "点评"

        with patch.object(AI_PROMPTS.dmc, "today_news", "新闻一"):
            self.assertEqual(ZFUNC.ai_parser(["排行榜"], "rnk"), "点评")
            AI_PROMPTS.dmc.today_news = "新闻二"
            self.assertEqual(ZFUNC.ai_parser(["排行榜"], "rnk"), "点评")

        self.assertEqual(
            calls,
            [
                {
                    "user_query": AI_PROMPTS.remind_news_pmpt
                    + news
                    + AI_PROMPTS.rnk_pmpt
                    + "排行榜",
                    "temperature": 1.5,
                }
                for news in ("新闻一", "新闻二")
            ],
        )

    def test_network_ranking_prompt_uses_dynamic_news(self):
        calls = []
        AI_PROMPTS.zapi.ark_api = lambda prompt: calls.append(prompt) or "点评"

        with patch.object(AI_PROMPTS.dmc, "today_news", "今日新闻"):
            result = ZFUNC.ai_parser(["排行榜"], "rnk", network=True)

        self.assertEqual(result, "点评")
        self.assertEqual(
            calls,
            [AI_PROMPTS.ark_chat_pmpt + AI_PROMPTS.remind_news_pmpt
             + "今日新闻" + AI_PROMPTS.rnk_pmpt + "排行榜"],
        )

    def test_adapter_error_keeps_existing_text_response(self):
        AI_PROMPTS.zapi.ai_api = lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("ai unavailable")
        )

        result = ZFUNC.ai_parser(["hello"], "pure_chat")

        self.assertEqual(result, "ai unavailable")


if __name__ == "__main__":
    unittest.main()
