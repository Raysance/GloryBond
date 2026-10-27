import unittest
from types import SimpleNamespace

from local_debugger import import_hok_module


EMOJI = import_hok_module("event_handlers.emoji")


class EmojiEventHandlerTests(unittest.TestCase):
    def test_parses_named_template_prompt_and_image(self):
        result = EMOJI.parse_emoji_request(
            "##emoji 模板名：开心猫 提示词：今天赢了",
            [SimpleNamespace(type="image", data={"url": "https://img.test/a.png"})],
        )
        self.assertEqual(result["template_name"], "开心猫")
        self.assertIsNone(result["template_prefix"])
        self.assertEqual(result["prompt_tail"], "今天赢了")
        self.assertEqual(result["custom_image_url"], "https://img.test/a.png")

    def test_parses_positional_ascii_template_prefix(self):
        result = EMOJI.parse_emoji_request("#emoji cat 今天输了", [])
        self.assertEqual(result["template_prefix"], "cat")
        self.assertIsNone(result["template_name"])
        self.assertEqual(result["prompt_tail"], "今天输了")

    def test_plain_prompt_does_not_become_template(self):
        result = EMOJI.parse_emoji_request("emoji 开心", None)
        self.assertIsNone(result["template_prefix"])
        self.assertIsNone(result["template_name"])
        self.assertEqual(result["prompt_tail"], "开心")


if __name__ == "__main__":
    unittest.main()
