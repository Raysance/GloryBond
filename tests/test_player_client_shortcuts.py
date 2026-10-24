"""Exact client shortcuts, trusted self binding, and legacy group-query isolation."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from local_debugger import import_hok_module

HANDLER = import_hok_module("event_handlers.player_client")
RULES = import_hok_module("event_rules")
STATIC = import_hok_module("zstatic")
ZFUNC = import_hok_module("zfunc")


class ShortcutTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = {**STATIC.player_client_config, "players": {"alice": {"uid": 7}}}
        values = {"player_client_config": self.settings, "namenick": {"alice": "甲"},
                  "extra_namenick": {}, "nameref": {"alice": ["甲", "ali", "alice"]},
                  "qid": {"alice": "1"}, "HeroList": {"106": "小乔", "112": "鲁班七号"},
                  "HeroName_replacements": {"112": "卤蛋"}}
        for name, value in values.items():
            patcher = patch.object(STATIC, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def event(self, text, user="1"):
        return SimpleNamespace(get_plaintext=lambda: text, get_user_id=lambda: user)

    async def test_shortcuts_dispatch_the_same_client_operations_as_explicit_commands(self):
        cases = (("#甲的小乔", "hero_honors", {"hero_id": 106, "scope": "all"}),
                 ("＃我的卤蛋", "hero_honors", {"hero_id": 112, "scope": "all"}),
                 ("#ALI的英雄", "heroes", {"scope": "season"}),
                 ("#甲的本赛季英雄", "heroes", {"scope": "season"}),
                 ("#甲的英雄 本赛季", "heroes", {"scope": "season"}),
                 ("#我本赛季的英雄", "heroes", {"scope": "season"}),
                 ("#我的数据", "game_statistics", {"scope": "season", "mode": "all", "branch": None}))
        for text, operation, parameters in cases:
            with self.subTest(text=text), patch.object(ZFUNC, "player_client_query", return_value={"result": 1}) as query, \
                 patch.object(ZFUNC, "player_client_hero_report", return_value={"text": "英雄图", "image_path": "card.png"}) as report, \
                 patch.object(ZFUNC, "player_client_screen_report", return_value={"text": "图", "image_path": "card.png"}):
                self.assertTrue(await RULES.judge_player_client(self.event(text)))
                await HANDLER.command_reply(self.event(text))
                query.assert_called_once_with(operation, player={"uid": 7}, **parameters)
                self.assertEqual(report.call_count, 1 if operation == "heroes" else 0)

    async def test_unprefixed_unknown_extra_text_and_admin_prefix_do_not_become_shortcuts(self):
        for text in ("甲的小乔", "#甲的小乔怎么样", "#陌生人的小乔", "#甲的不存在", "##甲的数据",
                     "#关于甲的数据"):
            with self.subTest(text=text):
                self.assertFalse(await RULES.judge_player_client(self.event(text)))

    async def test_group_u_queries_keep_the_existing_group_hero_handler(self):
        with patch.object(ZFUNC, "extract_heroname", return_value=(106, "小乔")):
            for text in ("#群u的小乔", "＃群u的英雄", "#群u的英雄 本赛季"):
                with self.subTest(text=text):
                    self.assertFalse(await RULES.judge_player_client(self.event(text)))
                    self.assertTrue(await RULES.judge_herostatistics_query(self.event(text)))

    async def test_self_and_unbound_players_cannot_fall_back_to_the_login_account(self):
        with patch.object(ZFUNC, "player_client_query") as query:
            reply = await HANDLER.command_reply(self.event("#我的小乔", user="2"))
            self.assertIn("尚未绑定", reply[0])
            with patch.object(STATIC, "nameref", {"unbound": ["乙"]}):
                reply = await HANDLER.command_reply(self.event("#乙的数据"))
                self.assertIn("尚未绑定", reply[0])
            query.assert_not_called()

    async def test_ambiguous_player_alias_is_rejected_before_network_access(self):
        with patch.object(STATIC, "nameref", {"alice": ["同名"], "other": ["同名"]}), \
             patch.object(ZFUNC, "player_client_query") as query:
            reply = await HANDLER.command_reply(self.event("#同名的数据"))
        self.assertIn("不唯一", reply[0])
        query.assert_not_called()
