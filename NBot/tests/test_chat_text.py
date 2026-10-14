import unittest

from local_debugger import import_hok_module

normalize = import_hok_module("tools.chat_text").normalize_qq_text
format_reply = import_hok_module("tools.chat_text").format_chat_reply


class PlainChatTextTests(unittest.TestCase):
    def test_emphasis_strikethrough_and_nested_formatting_are_removed(self):
        text = '**王芳** × __小卷王__，*辅助*和 _打野_，~~旧结论~~，***强强***'
        self.assertEqual(normalize(text), '王芳 × 小卷王，辅助和 打野，旧结论，强强')

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


class PlayerDisplayTests(unittest.TestCase):
    def render(self, text):
        return format_reply(text, player_names={"lry": "阳大师", "wzy": "王芳", "jiao": "交出", "sh": "sh"},
                            identity_names={"123456789": "阳大师", "987654321": "王芳"}, aliases=["脚"])

    def test_configured_nicknames_replace_raw_keys_and_incorrect_aliases(self):
        self.assertEqual(self.render("推荐lry与wzy；LRY（阳大师）和jiao（脚）。"), "推荐阳大师与王芳；阳大师和交出。")
        self.assertEqual(self.render("王芳（lry）× wzy（阳大师）"), "阳大师× 王芳")
        self.assertEqual(self.render("sh与jiao（本赛季0场）"), "sh与交出（本赛季0场）")

    def test_labeled_ids_disappear_and_unlabeled_known_ids_become_names(self):
        self.assertEqual(self.render("lry（qid: 123456789，role_id=556677）胜率62.5%。"), "阳大师胜率62.5%。")
        self.assertEqual(self.render("123456789与987654321，共玩8场，5胜3负。"), "阳大师与王芳，共玩8场，5胜3负。")
        for field in ["qid", "roleid", "user_id", "player_id", "game_role_id", "QQ号", "营地ID", "群号", "message_id", "dataset_id"]:
            with self.subTest(field=field):
                self.assertEqual(self.render(f"{field}: 112233"), "身份信息不在最终回复中展示。")

    def test_stats_math_long_words_and_public_urls_are_preserved(self):
        text = "show / fish / wzy_2 / lry2 / score_value = 1；2026年9月30日，62.5%，评分10.5，a * b，a_b。https://example.com/sh"
        self.assertEqual(self.render(text), text)
        self.assertEqual(self.render("详情 https://example.com/?role_id=998877"), "详情")
        self.assertEqual(self.render("详情 https://example.com/123456789"), "详情")

    def test_name_substitution_does_not_cascade_or_invent_nicknames(self):
        self.assertEqual(format_reply("a和b", player_names={"a": "b", "b": "丙"}, identity_names={}), "b和丙")
        self.assertEqual(format_reply("abc", player_names={"abc": ""}, identity_names={}), "该玩家")
        self.assertEqual(format_reply("普通回复", player_names={}, identity_names={}), "普通回复")


if __name__ == '__main__':
    unittest.main()
