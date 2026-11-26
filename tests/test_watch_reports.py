import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from glorybond.features.game.watch_report import battle_reference, completed_battle
from glorybond.storage import watch_reports as store
from tools.debugger import import_project_module

try:
    import fakeredis
except ImportError:
    fakeredis = None

with patch('nonebot.get_driver', return_value=SimpleNamespace(on_startup=lambda fn: fn)):
    sender = import_project_module('glorybond.apps.qq.message_sender')
handler = import_project_module('glorybond.apps.qq.handlers.watch_reports')
rules = import_project_module('glorybond.apps.qq.rules')
facade = import_project_module('glorybond.features.facade')
reports = import_project_module('glorybond.apps.qq.handlers.player_reports')

ROUTE = ('smobagamehelper://hippy?modulename=battledetail&gameSvrId=3&relaySvrId=4'
         '&gameSeq=12345&pvpType=1&toAppRoleId=22')
PARAMS = dict(gameseq='12345', gameSvrId='3', relaySvrId='4', pvptype=1)
REFERENCE = {'battle_id': 'watch-id-is-not-game-seq', 'params': PARAMS}
TARGET = dict(name='player', userid=11, roleid=22, display_name='示例玩家')
ROW = dict(gameSeq='12345', gameSvrId='3', relaySvrId='4', pvpType=1)


class Event:
    def __init__(self, text='是', *, user=9, group=8):
        self.user_id, self.text = user, text
        if group is not None:
            self.group_id = group
    def get_user_id(self): return str(self.user_id)
    def get_plaintext(self): return self.text


class BattleReferenceTests(unittest.TestCase):
    def test_reference_uses_explicit_detail_parameters_and_exact_role(self):
        raw = {'battleID': REFERENCE['battle_id'], 'battleDetailUrl': ROUTE}
        self.assertEqual(battle_reference(raw, role_id=22), REFERENCE)
        self.assertIsNone(battle_reference(raw, role_id=33))
        for suffix in ('&gameSeq=999', '&toAppRoleId=33'):
            self.assertIsNone(battle_reference({**raw, 'battleDetailUrl': ROUTE + suffix}, role_id=22))
        for invalid in ({'battleID': '12345'}, {}, None):
            self.assertIsNone(battle_reference(invalid, role_id=22))

    def test_only_the_matching_completed_record_triggers_delivery(self):
        self.assertFalse(completed_battle({'list': [{**ROW, 'gameSeq': 'next-game'}]}, PARAMS))
        self.assertFalse(completed_battle({'list': [{**ROW, 'gameSvrId': 'wrong-server'}]}, PARAMS))
        self.assertFalse(completed_battle({'list': [{**ROW, 'isGaming': True}]}, PARAMS))
        self.assertTrue(completed_battle({'list': [ROW], 'isGaming': True}, PARAMS))
        with self.assertRaises(PermissionError):
            completed_battle({'list': [ROW], 'invisible': True}, PARAMS)


@unittest.skipUnless(fakeredis, 'Install fakeredis[lua] for durable queue tests')
class WatchReportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from glorybond import runtime
        self.db = fakeredis.FakeRedis()
        patches = [patch.object(runtime, 'redis_deamon', self.db),
                   patch.object(handler, 'confs', {'QQBot': {'bot_qid': 1}}),
                   patch.object(handler, 'userlist', {'player': 11}),
                   patch.object(handler, 'roleidlist', {'player': 22}),
                   patch.object(handler, 'current_timestamp', return_value=100),
                   patch.object(rules, 'is_battle_visible_qid_enabled', return_value=True),
                   patch.object(rules, 'check_sleep', new=AsyncMock(return_value=False)),
                   patch.object(rules.dmc, 'repair', False)]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        self.event = Event()
        self.scope = handler.reply_scope(self.event)
        self.question = {'type': 'group', 'toid': 8, 'content': '是否推送', 'delivery_id_internal': 'prompt'}

    def offer(self, *, scope=None, reference=None):
        return store.offer(scope or self.scope, TARGET, reference or REFERENCE, self.question, now=100)

    def accept(self, *, scope=None):
        scope = scope or self.scope
        return store.answer(scope, store.pending(scope), True, now=100)

    def queue(self):
        from glorybond.config.settings import REDIS_KEY_MESSAGE_OUTBOUND_QUEUE
        result = []
        while raw := self.db.rpop(REDIS_KEY_MESSAGE_OUTBOUND_QUEUE):
            result.append(json.loads(raw))
        return result

    async def test_no_network_before_yes_and_decline_creates_no_job(self):
        self.offer()
        with patch.object(facade, 'wzry_get_official') as api, patch.object(sender, 'add_msg') as send:
            await handler.check_pending_reports()
            await handler.answer_after_watch(Event('否'))
            await handler.check_pending_reports()
        api.assert_not_called()
        self.assertIn('不推送', send.call_args.args[0])
        self.assertIsNone(store.pending(self.scope))
        self.assertEqual(store.claim_due('1', now=100), [])

    def test_prompt_follows_successful_watch_without_querying_more_player_data(self):
        with patch.object(sender, 'offer_watch_report', return_value=True) as offer, \
             patch.object(facade, 'wzry_get_official') as api:
            self.assertTrue(handler.ask_after_watch(TARGET, {'battle_reference': REFERENCE}, event=self.event))
        offer.assert_called_once_with(self.scope, TARGET, REFERENCE, event=self.event)
        api.assert_not_called()
        with patch.object(sender, 'offer_watch_report') as offer, patch.object(sender, 'add_msg') as text:
            self.assertFalse(handler.ask_after_watch(TARGET, {}, event=self.event))
        offer.assert_not_called()
        self.assertIn('无法设置', text.call_args.args[0])

    async def test_private_report_stays_private_and_lost_detail_waits(self):
        scope = handler.reply_scope(Event(group=None))
        self.offer(scope=scope); self.accept(scope=scope); self.queue()
        with patch.object(facade, 'wzry_get_official', return_value={'list': [ROW]}), \
             patch.object(reports, 'single_last_battle_reply', new=AsyncMock(return_value=None)):
            await handler.check_pending_reports()
        self.assertEqual(self.queue(), [])
        with patch.object(handler, 'current_timestamp', return_value=161), \
             patch.object(facade, 'wzry_get_official', return_value={'list': [ROW]}), \
             patch.object(reports, 'single_last_battle_reply', new=AsyncMock(return_value={
                 'text': '该局详情', 'image_path': '/tmp/battle.png'})):
            await handler.check_pending_reports()
        payload = self.queue()[0]
        self.assertEqual((payload['type'], payload['toid']), ('private', 9))

    def test_enqueue_failure_does_not_mark_report_as_queued(self):
        from glorybond.config.settings import REDIS_KEY_MESSAGE_OUTBOUND_QUEUE
        self.offer(); self.accept(); self.queue()
        job = store.claim_due('1', now=100)[0]
        self.db.set(REDIS_KEY_MESSAGE_OUTBOUND_QUEUE, 'wrong-type')
        with self.assertRaises(Exception):
            sender.add_watch_report_msg(job, {'text': '该局详情', 'image_path': '/tmp/battle.png'})
        self.assertEqual(json.loads(self.db.get(job['key']))['state'], 'pending')

    async def test_only_pending_actor_in_original_conversation_can_answer(self):
        self.offer()
        self.assertTrue(await rules.judge_watch_report_answer(self.event))
        for event in (Event(user=10), Event(group=10), Event(group=None), Event('其他文本')):
            self.assertFalse(await rules.judge_watch_report_answer(event))
        with patch.object(sender, 'add_msg'):
            await handler.answer_after_watch(Event(user=10))
        self.assertIsNotNone(store.pending(self.scope))
        self.db.delete(store.prompt_key(self.scope))
        self.assertFalse(await rules.judge_watch_report_answer(self.event))

    def test_stale_confirmation_cannot_accept_a_newer_question(self):
        self.offer()
        old = store.pending(self.scope)
        new = {'battle_id': 'new-watch-id', 'params': {**PARAMS, 'gameseq': '23456'}}
        self.offer(reference=new)
        self.assertEqual(store.answer(self.scope, old, True, now=101), 0)
        self.assertEqual(store.pending(self.scope)['reference'], new)

    def test_new_watch_without_question_discards_previous_confirmation(self):
        self.offer(); self.accept()
        new = {'battle_id': 'new-watch-id', 'params': {**PARAMS, 'gameseq': '23456'}}
        self.offer(reference=new)
        self.assertIsNotNone(store.pending(self.scope))
        self.assertFalse(self.offer())  # This battle was already accepted.
        self.assertIsNone(store.pending(self.scope))
        self.offer(reference=new)
        with patch.object(sender, 'add_msg'):
            handler.ask_after_watch(TARGET, {}, event=self.event)
        self.assertIsNone(store.pending(self.scope))

    async def test_acceptance_persists_then_uses_exact_existing_battle_reply(self):
        self.offer(); self.queue()
        with patch.object(sender, 'add_msg') as send:
            await handler.answer_after_watch(self.event)
        self.assertIn('已开启', send.call_args.args[0])
        battle = {'text': '最后一局 [CQ:at,qq=999]\nhttps://example.test/detail',
                  'image_path': '/tmp/battle.png', 'map_name': '排位赛'}
        with patch.object(facade, 'wzry_get_official', return_value={'list': [ROW]}) as api, \
             patch.object(reports, 'single_last_battle_reply', new=AsyncMock(return_value=battle)) as render:
            await handler.check_pending_reports()
            await handler.check_pending_reports()
        api.assert_called_once_with('btlist', priority='low', userid=11, roleid=22)
        render.assert_awaited_once_with({'battle_params': PARAMS, 'battle_roleid': 22})
        payloads = self.queue()
        self.assertEqual(len(payloads), 1)
        payload = payloads[0]
        self.assertEqual(payload['content'], str(sender.battle_reply_message(battle)))
        self.assertEqual((payload['type'], payload['toid']), ('group', 8))
        job = json.loads(self.db.get(payload['watch_report_key']))
        self.assertEqual(job['state'], 'queued')
        sender._record_watch_report_outcome(payload, result={'message_id': 12})
        self.assertEqual(json.loads(self.db.get(payload['watch_report_key']))['state'], 'sent')

    async def test_other_latest_match_is_not_sent_and_job_waits_across_ticks(self):
        self.offer(); self.accept(); self.queue()
        with patch.object(facade, 'wzry_get_official', return_value={'list': [{**ROW, 'gameSeq': '555'}]}), \
             patch.object(reports, 'single_last_battle_reply', new=AsyncMock()) as render:
            await handler.check_pending_reports()
        render.assert_not_awaited()
        self.assertEqual(self.queue(), [])
        jobs = store.claim_due('1', now=161)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['reference'], REFERENCE)
        store.release(jobs[0])

    async def test_same_conversation_and_target_deduplicate_multiple_viewers(self):
        other = handler.reply_scope(Event(user=10))
        self.offer(); self.offer(scope=other)
        self.accept(); self.accept(scope=other)
        jobs = store.claim_due('1', now=100)
        self.assertEqual(len(jobs), 1)
        store.release(jobs[0])
        self.assertFalse(self.offer())

    async def test_unknown_send_is_recorded_and_never_requeued(self):
        self.offer(); self.accept(); self.queue()
        job = store.claim_due('1', now=100)[0]
        sender.add_watch_report_msg(job, {'text': '本局战绩', 'image_path': '/tmp/battle.png'})
        payload = self.queue()[0]
        sender._record_watch_report_outcome(payload, error=TimeoutError('PRIVATE'))
        self.assertEqual(json.loads(self.db.get(job['key']))['state'], 'unknown')
        self.assertEqual(store.claim_due('1', now=1000), [])
        self.assertFalse(sender.add_watch_report_msg(job, {'text': '本局战绩', 'image_path': '/tmp/battle.png'}))

    async def test_expiry_and_changed_binding_stop_without_query(self):
        for expired in (False, True):
            self.db.flushdb(); self.offer(); self.accept(); self.queue()
            with patch.object(handler, 'current_timestamp', return_value=7401 if expired else 100), \
                 patch.object(handler, 'roleidlist', {'player': 22 if expired else 33}), \
                 patch.object(facade, 'wzry_get_official') as api, \
                 patch.object(handler, '_report_failure') as error:
                await handler.check_pending_reports()
            api.assert_not_called(); error.assert_called_once()
            self.assertEqual(store.claim_due('1', now=8000), [])

    async def test_network_failure_stops_with_safe_error_and_original_destination(self):
        self.offer(); self.accept(); self.queue()
        with patch.object(facade, 'wzry_get_official', side_effect=RuntimeError('PRIVATE TOKEN')), \
             patch.object(handler, '_report_failure') as error:
            await handler.check_pending_reports()
        error.assert_called_once()
        self.assertEqual(error.call_args.args[0]['scope'], self.scope)
        self.assertNotIn('PRIVATE', str(error.call_args.args[1]))
        self.assertEqual(store.claim_due('1', now=200), [])

    def test_expired_worker_lease_cannot_enqueue(self):
        self.offer(); self.accept(); self.queue()
        job = store.claim_due('1', now=100)[0]
        self.db.delete(job['key'] + ':lock')
        self.assertFalse(sender.add_watch_report_msg(job, {'text': '本局战绩', 'image_path': '/tmp/battle.png'}))
        self.assertEqual(self.queue(), [])


if __name__ == '__main__':
    unittest.main()
