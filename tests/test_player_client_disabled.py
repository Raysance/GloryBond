"""Disabled client traffic leaves Camp queries and legacy hero replies usable."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from local_debugger import import_hok_module

ONLINE = import_hok_module('business.online_status')
DATA = import_hok_module('business.player_data')
HANDLER = import_hok_module('event_handlers.player_client')
HERO = import_hok_module('event_handlers.hero')
RULES = import_hok_module('event_rules')
STATIC = import_hok_module('zstatic')
ZFUNC = import_hok_module('zfunc')
ZAPI = import_hok_module('zapi')
ZTIME = import_hok_module('ztime')


class DisabledQueriesTests(unittest.TestCase):
    def test_online_uses_camp_and_keeps_steam_without_reading_client_cache(self):
        settings = {'enabled': False, 'players': {'alice': {'uid': 7, 'logic_world_id': 8}}}
        def camp(*, reqtype, **kwargs):
            return ({'roleList': [{'gameOnline': True, 'roleName': '营地玩家',
                                   'shortRoleJobName': '王者'}]} if reqtype == 'profile' else
                    {'isGaming': False, 'gaming': {}})
        with patch.object(ONLINE, 'player_client_config', settings), \
             patch.object(ONLINE, 'userlist', {'alice': 11}), \
             patch.object(ONLINE, 'roleidlist', {'alice': 22}), \
             patch.object(ONLINE, 'steam_userlist', {'steam': 'steam-1'}), \
             patch.dict(ONLINE.confs, {'Steam': {'api_key': 'test'}}), \
             patch.object(ZFUNC, 'wzry_get_official', side_effect=camp) as request, \
             patch.object(ZFUNC, 'player_client_online_snapshot') as snapshot, \
             patch.object(ZFUNC, 'player_client_query') as client, \
             patch.object(ZAPI, 'steam_api_user_status', return_value={
                 'personaname': 'Steam玩家', 'personastate': 1}):
            for options in ({}, {'use_client': True}):
                with self.subTest(options=options):
                    message, errors = ONLINE.online_process(**options)
                    self.assertIn('营地玩家', message)
                    self.assertIn('Steam玩家', message)
                    self.assertNotIn('只跟踪王者好友', message)
                    self.assertEqual(errors, '')
            self.assertEqual(request.call_count, 4)
            snapshot.assert_not_called()
            client.assert_not_called()

    def test_battles_skip_client_and_retain_saved_same_day_records_when_disabled(self):
        player = dict(uid=7, logic_world_id=8, fake_description_id=0)
        camp = {'list': [], 'invisible': False}
        saved_row = dict(gameSeq=-123, dtEventTime=str(int(ZTIME.str_to_time('2026-11-02 12:00:00').timestamp())),
                         clientOnly=True, clientPlayer=player)
        with patch.object(ZFUNC, 'player_client_config', {'enabled': False, 'players': {'alice': player},
                                                        'history_merge_tolerance_seconds': 90}), \
             patch.object(ZFUNC, 'userlist', {'alice': 11}), patch.object(ZFUNC, 'roleidlist', {'alice': 22}), \
             patch.object(DATA, '_battle_list_for_date', return_value=camp) as request, \
             patch.object(ZFUNC, 'player_client_query') as client, \
             patch.object(DATA.zfile, 'read_personal_history', return_value={'btlist': {'list': [saved_row]}}), \
             patch.object(DATA.zfile, 'read_latest_client_history') as saved:
            day = ZTIME.str_to_time('2026-11-02').date()
            result = DATA._combined_battle_list('alice', 11, 22, day)
            self.assertEqual(result['list'], [saved_row])
            self.assertEqual(result['sourceErrors'], [])
            request.assert_called_once_with(11, 22, day)
            client.assert_not_called()
            saved.assert_not_called()

    def test_direct_client_query_stops_before_credentials_or_adapter_creation(self):
        with patch.object(ZFUNC, 'player_client_config', {'enabled': False}), \
             patch.object(ZFUNC, '_player_client_account_fingerprint') as fingerprint, \
             patch.object(ZAPI, 'PlayerClientAdapter') as adapter:
            with self.assertRaisesRegex(ValueError, 'disabled'):
                ZFUNC.player_client_query('friend_states')
            fingerprint.assert_not_called()
            adapter.assert_not_called()


class DisabledCommandTests(unittest.IsolatedAsyncioTestCase):
    def event(self, text):
        return SimpleNamespace(get_plaintext=lambda: text, get_user_id=lambda: '100')

    async def test_hero_queries_reach_legacy_handler_without_client_information(self):
        with patch.object(STATIC, 'player_client_config', {'enabled': False}), \
             patch.object(ZFUNC, 'qid2nick', return_value='玩家'), \
             patch.object(ZFUNC, 'extract_name', return_value='alice'), \
             patch.object(ZFUNC, 'extract_heroname', return_value=(106, '小乔')), \
             patch.object(ZFUNC, 'single_player_mult_hero_process', return_value='原有英雄统计') as heroes, \
             patch.object(ZFUNC, 'single_player_single_hero_process', return_value='原有单英雄统计') as hero, \
             patch.object(ZFUNC, 'player_client_query') as client:
            for text, expected in (('#我的英雄', '原有英雄统计'), ('#我的小乔', '原有单英雄统计')):
                event = self.event(text)
                self.assertFalse(await RULES.judge_player_client(event))
                self.assertTrue(await RULES.judge_herostatistics_query(event))
                self.assertEqual(await HERO.hero_statistics_reply(event), expected)
            heroes.assert_called_once_with('alice', this_season=False)
            hero.assert_called_once_with('alice', 106, '小乔')
            client.assert_not_called()

    async def test_explicit_client_commands_report_disabled_without_request(self):
        with patch.object(STATIC, 'player_client_config', {'enabled': False}), \
             patch.object(ZFUNC, 'player_client_query') as client:
            for text in ('#客户端 好友状态', '#客户端 战绩 我', '#客户端 英雄 我'):
                event = self.event(text)
                self.assertTrue(await RULES.judge_player_client(event))
                self.assertEqual(await HANDLER.command_reply(event), ['王者客户端查询已停用。'])
            client.assert_not_called()
