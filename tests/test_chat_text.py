import unittest

from local_debugger import import_hok_module

normalize = import_hok_module("tools.chat_text").normalize_qq_text


class PlainChatTextTests(unittest.TestCase):
    def test_emphasis_strikethrough_and_nested_formatting_are_removed(self):
        text = '**示例玩家51** × __示例玩家41__，*辅助*和 _打野_，~~旧结论~~，***强强***'
        self.assertEqual(normalize(text), '示例玩家51 × 示例玩家41，辅助和 打野，旧结论，强强')

    def test_tables_become_readable_labeled_rows(self):
        text = '| 玩家 | 胜率 |\n| :--- | ---: |\n| **甲** | 60% |\n| 乙 | 70% |'
        self.assertEqual(normalize(text), '玩家：甲；胜率：60%\n玩家：乙；胜率：70%')
        self.assertEqual(normalize('| 玩家 | 胜率 |\n|---|---|'), '玩家；胜率')

    def test_task_list_has_plain_check_symbols(self):
        self.assertEqual(normalize('- [x] 已完成\n- [ ] 待完成'), '• ✓ 已完成\n• ☐ 待完成')

    def test_fences_and_inline_code_preserve_literal_symbols(self):
        text = '```python\nx = a * b\nplayer_id = 1\n```\n\n`a_b * c`'
        self.assertEqual(normalize(text), 'x = a * b\nplayer_id = 1\na_b * c')
        self.assertEqual(normalize('a * b = 6，player_id = 1'), 'a * b = 6，player_id = 1')

    def test_headings_quotes_lists_links_and_images_render_plainly(self):
        text = '# 推荐\n\n> **第一组**\n\n3. [查看](https://example.com)\n4. ![示意图](https://example.com/a.png)\n\n---'
        self.assertEqual(normalize(text), '推荐\n\n第一组\n\n3、查看\n4、示意图')

    def test_plain_output_is_stable(self):
        for text in ['第一组：甲 × 乙\n\n胜率 60%。', '• 玩家一\n• 玩家二', '1、第一组\n2、第二组']:
            self.assertEqual(normalize(text), text)
            self.assertEqual(normalize(normalize(text)), text)


if __name__ == '__main__':
    unittest.main()
