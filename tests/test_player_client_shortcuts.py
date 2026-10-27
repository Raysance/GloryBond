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


class PrimaryAccountTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.main = {"uid": 7, "logic_world_id": 8, "fake_description_id": 9}
        self.alt = {"uid": 70, "logic_world_id": 80, "fake_description_id": 90}
        self.settings = {**STATIC.player_client_config, "players": {"example_user_5": self.main, "example_user_6": self.alt}}
        values = {"player_client_config": self.settings, "userlist": {"example_user_5": 11},
                  "namenick": {"example_user_5": "示例玩家41"}, "extra_namenick": {"example_user_6": "示例玩家41"},
                  # Put the alternate first and give the main an alias matching the explicit alternate key.
                  "nameref": {"example_user_6": ["示例玩家41", "卷王"], "example_user_5": ["示例玩家41", "卷王", "example_user_6"]},
                  "qid": {"example_user_5": "100", "example_user_6": "100"}, "HeroList": {"106": "小乔"}}
        for name, value in values.items():
            patcher = patch.object(STATIC, name, value)
            patcher.start(); self.addCleanup(patcher.stop)

    def event(self, text):
        return SimpleNamespace(get_plaintext=lambda: text, get_user_id=lambda: "100")

    async def test_shared_nickname_alias_and_self_use_main_across_all_client_commands(self):
        for text, operation in (("#示例玩家41的英雄", "heroes"), ("#卷王的小乔", "hero_honors"),
                                ("#示例玩家41的数据", "game_statistics"), ("#我的英雄", "heroes"),
                                ("#客户端 资料 示例玩家41", "profile_summary"),
                                ("#客户端 好友状态 示例玩家41", "friend_state")):
            with self.subTest(text=text), patch.object(ZFUNC, "player_client_query", return_value={}) as query, \
                 patch.object(ZFUNC, "player_client_hero_report", return_value={}), \
                 patch.object(ZFUNC, "player_client_screen_report", return_value={}), \
                 patch.object(ZFUNC, "player_client_text_report", return_value=[]):
                await HANDLER.command_reply(self.event(text))
            self.assertEqual(query.call_args.args, (operation,))
            self.assertEqual(query.call_args.kwargs["player"], self.main)

    async def test_explicit_alternate_key_beats_nickname_aliases_and_both_sources_use_that_key(self):
        for text, key, reference in (("#示例玩家41的英雄", "example_user_5", self.main),
                                     ("#我的英雄", "example_user_5", self.main),
                                     ("#HYQ_的英雄", "example_user_6", self.alt)):
            with self.subTest(text=text), patch.object(ZFUNC, "player_client_query", return_value={}) as query, \
                 patch.object(ZFUNC, "player_client_hero_report", return_value={}), \
                 patch.object(ZFUNC, "qid2nick", return_value="示例玩家41"), \
                 patch.object(ZFUNC, "extract_name") as legacy_resolve, \
                 patch.object(ZFUNC, "single_player_mult_hero_process", return_value={"kind": "hero_history"}) as aggregate:
                await HANDLER.command_reply(self.event(text))
                await HANDLER.original_hero_reply(self.event(text))
            self.assertEqual(query.call_args.kwargs["player"], reference)
            aggregate.assert_called_once_with(key, this_season=False, as_report=True)
            legacy_resolve.assert_not_called()

    async def test_two_main_matches_or_two_alternates_remain_ambiguous(self):
        for mains in ({"example_user_5": 11, "example_user_6": 22}, {}):
            with self.subTest(mains=mains), patch.object(STATIC, "userlist", mains), \
                 patch.object(ZFUNC, "player_client_query") as query:
                reply = await HANDLER.command_reply(self.event("#示例玩家41的英雄"))
                self.assertIn("不唯一", reply[0])
                self.assertIsNone(await HANDLER.original_hero_reply(self.event("#示例玩家41的英雄")))
            query.assert_not_called()

    async def test_unbound_main_never_silently_switches_to_the_bound_alternate(self):
        with patch.object(STATIC, "player_client_config", {**self.settings, "players": {"example_user_6": self.alt}}), \
             patch.object(ZFUNC, "player_client_query") as query:
            reply = await HANDLER.command_reply(self.event("#示例玩家41的英雄"))
        self.assertIn("尚未绑定", reply[0])
        query.assert_not_called()

    async def test_single_alternate_is_usable_when_there_is_no_matching_main(self):
        with patch.object(STATIC, "namenick", {"example_user_5": "另一人"}), \
             patch.object(STATIC, "nameref", {"example_user_6": ["示例玩家41"]}), \
             patch.object(ZFUNC, "player_client_query", return_value={}) as query, \
             patch.object(ZFUNC, "player_client_hero_report", return_value={}):
            await HANDLER.command_reply(self.event("#示例玩家41的英雄"))
        self.assertEqual(query.call_args.kwargs["player"], self.alt)
