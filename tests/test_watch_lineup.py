"""Lineup projection, ordering, atomic deduplication and real receipt states."""
import asyncio
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from glorybond.features.game.watch_lineup import prepare_watch_lineup
from glorybond.storage import watch_lineups as store
from tools.debugger import import_project_module

try:
    import fakeredis
except ImportError:
    fakeredis = None

with patch('nonebot.get_driver', return_value=SimpleNamespace(on_startup=lambda fn: fn)):
    sender = import_project_module('glorybond.apps.qq.message_sender')
handler = import_project_module('glorybond.apps.qq.handlers.live_watch')
business = import_project_module('glorybond.features.game.watch_lineup')


class LineupProjectionTests(unittest.TestCase):
    def test_preserves_visible_fields_and_omits_credentials_and_identifiers(self):
        raw = {'battleID': 'example-battle', 'mapName': '排位赛', 'stream_url': 'SECRET', 'camp1': [
            {'roleId': 22, 'userId': 123, 'heroId': 107, 'heroName': '赵云',
             'heroUrl': 'https://game.gtimg.cn/hero.jpg', 'heroIcon': 'https://game.gtimg.cn/icon.jpg',
             'roleInfo': {'roleName': '未授权游戏信息', 'roleIcon': 'https://q.qlogo.cn/avatar',
                          'roleJobIcon': 'https://game.gtimg.cn/jungle.png'}}], 'camp2': [{}]}
        before = copy.deepcopy(raw)
        data = prepare_watch_lineup(raw, role_id=22)
        first = data['teams'][0]['players'][0]
        self.assertEqual(first['name'], '未授权游戏信息')
        self.assertEqual(first['hero_name'], '赵云')
        self.assertTrue(first['is_target'])
        self.assertIsNone(data['teams'][1]['players'][0]['name'])
        self.assertEqual(raw, before)
        self.assertNotIn('SECRET', str(data))
        self.assertNotIn('userId', str(data))
        self.assertNotIn('roleId', str(data))

    def test_missing_lineup_or_identity_is_not_fabricated(self):
        for raw in (None, {}, {'battleID': 'b'}, {'camp1': [{}]}):
            self.assertIsNone(prepare_watch_lineup(raw, role_id=22))
        data = prepare_watch_lineup({'battleID': 'b', 'camp1': [
            {'roleId': 12, 'userId': 22, 'heroIcon': 'http://127.0.0.1/private'}]}, role_id=22)
        self.assertFalse(data['teams'][0]['players'][0]['is_target'])
        self.assertIsNone(data['teams'][0]['players'][0]['hero_icon'])
        with self.assertRaises(ValueError):
            prepare_watch_lineup({'battleID': 'b', 'camp1': [{}] * 11}, role_id=22)

    def test_single_response_fields_preserve_zero_and_unknown_without_supplement_queries(self):
        raw = {'battleID': 'b', 'camp1': [{}], 'camp2': [
            {'roleId': 22, 'heroName': '英雄', 'heroFightValue': 0, 'win': '12', 'lost': 0,
             'winRate': '100%', 'roleInfo': {'roleName': '目标'}}]}
        data = prepare_watch_lineup(raw, role_id=22)
        first, target = (team['players'][0] for team in data['teams'])
        self.assertIsNone(first['hero_power'])
        self.assertEqual(target['hero_power'], 0)
        self.assertEqual((target['wins'], target['losses'], target['win_rate']), (12, 0, 1))
        from glorybond.rendering import gen_coplayer_analyses as renderer
        from glorybond.storage import files
        from glorybond.integrations import camp
        with patch.object(files, 'load_watch_lineup_images', return_value={}), \
             patch.object(files, 'save_watch_lineup_image', return_value='/tmp/lineup.png'), \
             patch.object(renderer, 'render_player_strength_image') as render, \
             patch.object(camp, 'query', side_effect=AssertionError('No supplemental request')):
            self.assertEqual(business.render_watch_lineup_file(data), '/tmp/lineup.png')
        players = render.call_args.args[0]
        self.assertEqual((players[0].name, players[0].side), ('目标', 'my'))
        self.assertEqual(players[0].derived_matches(), 12)
        self.assertTrue(render.call_args.kwargs['partial_data'])
        self.assertEqual(render.call_args.kwargs['team_labels'], ('我方', '对方'))
        for player in players:
            for field in ('single_level', 'score', 'avg_score', 'total_cnt', 'mvp_cnt', 'power', 'auth'):
                self.assertIsNone(getattr(player, field), field)

    def test_invalid_metrics_remain_blank(self):
        for value in (True, 'NaN', 'inf', -1, {}, ''):
            raw = {'battleID': 'b', 'camp1': [{'win': value, 'lost': value,
                    'heroFightValue': value, 'winRate': value}]}
            row = prepare_watch_lineup(raw, role_id=22)['teams'][0]['players'][0]
            for key in ('wins', 'losses', 'hero_power', 'win_rate'):
                self.assertIsNone(row[key], (key, value))

    def test_previous_lineup_skips_render_and_new_card_uses_atomic_queue(self):
        event = SimpleNamespace(group_id=123, user_id=456)
        data = {'battle_id': 'b'}
        with patch.object(sender, 'watch_lineup_queued', return_value=True), \
             patch.object(business, 'render_watch_lineup_file') as render:
            self.assertFalse(handler.send_watch_lineup(data, event=event))
            render.assert_not_called()
        with patch.object(sender, 'watch_lineup_queued', return_value=False), \
             patch.object(business, 'render_watch_lineup_file', return_value='/tmp/lineup.png'), \
             patch.object(sender, 'add_watch_lineup_msg', return_value=True) as enqueue:
            self.assertTrue(handler.send_watch_lineup(data, event=event))
            enqueue.assert_called_once_with('b', '/tmp/lineup.png', event=event)


@unittest.skipUnless(fakeredis, 'Install the optional fakeredis[lua] test dependency')
class LineupDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from glorybond import runtime
        self.db = fakeredis.FakeRedis()
        patcher = patch.object(runtime, 'redis_deamon', self.db)
        patcher.start(); self.addCleanup(patcher.stop)
        self.event = SimpleNamespace(group_id=123, user_id=456)

    def payload(self):
        from glorybond.config.settings import REDIS_KEY_MESSAGE_OUTBOUND_QUEUE
        return json.loads(self.db.rpop(REDIS_KEY_MESSAGE_OUTBOUND_QUEUE))

    def test_dedup_is_per_bot_conversation_and_battle_with_expiry(self):
        self.assertTrue(sender.add_watch_lineup_msg('battle-a', '/tmp/card.png', event=self.event))
        self.assertFalse(sender.add_watch_lineup_msg('battle-a', '/tmp/card.png', event=self.event))
        payload = self.payload()
        key = payload['watch_lineup_key']
        self.assertGreater(self.db.ttl(key), 86300)
        self.assertTrue(self.db.get(key).startswith(b'queued:'))
        self.assertTrue(sender.add_watch_lineup_msg('battle-b', '/tmp/card.png', event=self.event))
        self.assertTrue(sender.add_watch_lineup_msg('battle-a', '/tmp/card.png', event=SimpleNamespace(user_id=123)))
        other = SimpleNamespace(group_id=789, user_id=456)
        self.assertTrue(sender.add_watch_lineup_msg('battle-a', '/tmp/card.png', event=other))
        self.assertNotEqual(store.lineup_key(bot_id=1, channel='group', recipient=123, battle_id='battle-a'),
                            store.lineup_key(bot_id=2, channel='group', recipient=123, battle_id='battle-a'))

    def test_queue_failure_does_not_reserve_battle(self):
        from glorybond.config.settings import REDIS_KEY_MESSAGE_OUTBOUND_QUEUE
        self.db.set(REDIS_KEY_MESSAGE_OUTBOUND_QUEUE, 'wrong-type')
        with self.assertRaises(Exception):
            sender.add_watch_lineup_msg('battle-a', '/tmp/card.png', event=self.event)
        self.assertFalse(sender.watch_lineup_queued('battle-a', event=self.event))

    async def test_receipts_are_separate_and_unknown_send_is_not_replayed(self):
        sender.add_watch_lineup_msg('battle-a', '/tmp/card.png', event=self.event)
        payload = self.payload()
        bot = SimpleNamespace(send_group_msg=AsyncMock(side_effect=TimeoutError('SECRET')))
        with patch.object(sender, '_automation_before_send', new=AsyncMock(side_effect=lambda p: p)), \
             patch.object(sender, '_automation_sent', new=AsyncMock()), \
             patch.object(sender, '_record_task_receipt', new=AsyncMock()):
            with self.assertRaises(TimeoutError):
                await sender._send_queued_message(bot, payload)
        self.assertTrue(self.db.get(payload['watch_lineup_key']).startswith(b'unknown:'))
        self.assertFalse(sender.add_watch_lineup_msg('battle-a', '/tmp/card.png', event=self.event))
        bot.send_group_msg.assert_awaited_once()

    def test_definite_failure_allows_explicit_retry_but_old_receipt_cannot_overwrite_it(self):
        sender.add_watch_lineup_msg('battle-a', '/tmp/card.png', event=self.event)
        first = self.payload()
        store.record_outcome(first, 'failed')
        self.assertTrue(sender.add_watch_lineup_msg('battle-a', '/tmp/card.png', event=self.event))
        second = self.payload()
        store.record_outcome(first, 'sent')
        self.assertEqual(self.db.get(second['watch_lineup_key']), ('queued:' + second['delivery_id_internal']).encode())
        sender._record_watch_lineup_outcome(second, result={'message_id': 77})
        self.assertTrue(self.db.get(second['watch_lineup_key']).startswith(b'sent:'))
