"""Forecasts are empirical, private-data-free and independent of QQ delivery."""

import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from agent_console.reply_timing import ReplyTimingEstimator
from agent_console.tools.reply_timing import normalize_timing_sample, reply_timing_statistics
from qq_agent.output import QQOutput
from qq_agent.reply_timing import QQReplyTiming


def sample(total=80, model='model', images=False):
    return {'model': model, 'images': images, 'total_seconds': total,
            'checkpoints': {'start': 0, 'model:1': 2, 'model:2': 30, 'reply:1': 50}}


class ForecastTests(unittest.TestCase):
    def test_total_and_remaining_follow_real_stage_and_cohort(self):
        now = [0]
        predictor = ReplyTimingEstimator(samples=[sample(60), sample(80), sample(100), sample(300, model='other')],
                                         clock=lambda: now[0])
        predictor.begin('run', model='model')
        self.assertEqual(predictor.estimate('run')['estimated_total_seconds'], 80)
        now[0] = 40
        predictor.checkpoint({'run_id': 'run', 'kind': 'model.request', 'data': {'round': 2}})
        info = predictor.estimate('run')
        self.assertEqual(info['estimated_remaining_seconds'], 50)
        self.assertEqual(info['estimated_total_seconds'], 90)
        self.assertEqual(info['sample_count'], 3)
        now[0] = 100
        recorded = predictor.finish('run', success=True)
        self.assertEqual(recorded['total_seconds'], 100)
        self.assertEqual(recorded['checkpoints']['model:2'], 40)
        self.assertEqual(normalize_timing_sample(recorded), recorded)

    def test_unknown_overdue_and_failed_runs_do_not_claim_measured_accuracy(self):
        now = [0]
        predictor = ReplyTimingEstimator(samples=[sample()], cold_start_seconds=60, clock=lambda: now[0])
        predictor.begin('image', model='model', images=True)
        self.assertEqual(predictor.estimate('image')['source'], 'configured_baseline')
        now[0] = 120
        self.assertGreater(predictor.estimate('image')['estimated_total_seconds'], 120)
        self.assertIsNone(predictor.finish('image', success=False))
        self.assertEqual(len(predictor.samples), 1)
        self.assertFalse(predictor.runs)

    def test_storage_is_bounded_validated_and_excludes_content_and_identifiers(self):
        store = MagicMock()
        record = sample()
        self.assertEqual(reply_timing_statistics(store, {'action': 'record', 'sample': record}), {'recorded': True})
        pipe = store.pipeline.return_value.__enter__.return_value
        pipe.ltrim.assert_called_once_with('hok:agent_runtime:reply_timing:v1', 0, 127)
        pipe.execute.assert_called_once()
        store.lrange.return_value = [b'invalid', json.dumps(record), json.dumps({**record, 'user_id': 'private'})]
        self.assertEqual(reply_timing_statistics(store, {'action': 'read'})['samples'], [record])
        for bad in ({**record, 'prompt': 'private'}, {**record, 'total_seconds': float('nan')},
                    {**record, 'checkpoints': {'start': 0, 'tool:bad:1': 1000}}):
            with self.assertRaises(ValueError):
                normalize_timing_sample(bad)


class QQForecastTests(unittest.IsolatedAsyncioTestCase):
    def event(self, run='run', kind='run.start', data=None):
        return {'id': run + kind, 'run_id': run, 'session_id': run, 'sequence': 1,
                'time': '2026-01-01T00:00:00+08:00', 'kind': kind, 'data': data or {},
                'metadata': {'delivery': {'platform': 'qq', 'channel': 'group', 'recipient_id': '123',
                                         'mention_user_id': '456'}}}

    def output(self, timing, sender):
        bridge = SimpleNamespace(redact=lambda value: value, call=AsyncMock())
        return QQOutput(bridge=bridge, local_log=SimpleNamespace(record=AsyncMock()), sender=sender,
                        prepare_reply=AsyncMock(side_effect=lambda packet: packet), store_artifact=AsyncMock(),
                        reply_timing=timing), bridge

    async def test_notice_once_with_structured_data_and_final_delivery_survives_hint_failure(self):
        now = [0]
        timing = QQReplyTiming(SimpleNamespace(call=AsyncMock()), clock=lambda: now[0])
        self.addAsyncCleanup(timing.close)
        sender = AsyncMock(side_effect=[RuntimeError('notice unavailable'), None])
        output, bridge = self.output(timing, sender)
        await output.begin_timing(self.event(), model='model', started=0)
        packet, destination = sender.await_args.args
        self.assertIn('预计', packet['text'])
        self.assertEqual(packet['reply_estimate']['estimated_total_seconds'], 60)
        self.assertEqual(destination['recipient_id'], '123')
        self.assertEqual(output.events['run'][0]['data']['delivery_status'], 'failed')
        bridge.call.assert_not_awaited()
        await output.publish(self.event(kind='model.request', data={'round': 1}))
        await output.publish(self.event(kind='output.message', data={'kind': 'final', 'text': 'Final answer'}))
        now[0] = 70
        await output.publish(self.event(kind='run.end', data={'status': 'completed'}))
        self.assertEqual(sender.await_count, 2)
        self.assertEqual(sender.await_args.args[0]['text'], 'Final answer')
        self.assertEqual(bridge.call.await_count, 1)  # Only accepted final enters group context.
        self.assertEqual(timing.estimator.samples[-1]['total_seconds'], 70)
        self.assertFalse(timing.estimator.runs)

    async def test_threshold_concurrency_cancellation_and_no_late_notice(self):
        now = [0]
        timing = QQReplyTiming(SimpleNamespace(call=AsyncMock()), policy={'cold_start_seconds': 30}, clock=lambda: now[0])
        self.addAsyncCleanup(timing.close)
        timing.begin('a', model='model')
        timing.begin('b', model='model')
        self.assertIsNone(timing.notice(self.event('a')))
        now[0] = 31
        self.assertIsNotNone(timing.notice(self.event('a')))
        self.assertIsNone(timing.notice(self.event('a')))
        self.assertIsNotNone(timing.notice(self.event('b')))
        timing.finish('a', success=False)
        self.assertIsNone(timing.notice(self.event('a')))
        self.assertFalse(timing.estimator.samples)

    async def test_watchdog_notifies_when_an_initially_fast_request_overruns(self):
        now = [0]
        timing = QQReplyTiming(SimpleNamespace(call=AsyncMock()), policy={'cold_start_seconds': 20}, clock=lambda: now[0])
        self.addAsyncCleanup(timing.close)
        timing.begin('run', model='model')
        async def sleep(_):
            now[0] = 31
        announce = AsyncMock()
        with patch('qq_agent.reply_timing.asyncio.sleep', side_effect=sleep):
            timing.watch(self.event(), announce)
            await timing.watchers['run']
        announce.assert_awaited_once()
        self.assertIsNotNone(timing.notice(self.event()))

    async def test_background_runs_never_send_wait_notices(self):
        timing = QQReplyTiming(SimpleNamespace(call=AsyncMock()))
        timing.begin('run', model='model')
        event = self.event()
        event['metadata']['origin'] = 'background'
        self.assertIsNone(timing.notice(event))
        await timing.close()
