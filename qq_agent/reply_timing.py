"""QQ forecast lifecycle and persistence, separate from runtime/model protocols."""

import asyncio
import logging
import math

from agent_console.reply_timing import ReplyTimingEstimator
from agent_console.tools.reply_timing import normalize_timing_sample


class QQReplyTiming:
    def __init__(self, bridge, *, policy=None, clock=None):
        policy = policy or {}
        self.bridge = bridge
        self.enabled = policy.get('enabled', True)
        self.estimator = ReplyTimingEstimator(cold_start_seconds=policy.get('cold_start_seconds', 60),
                                             **({'clock': clock} if clock else {}))
        self.pending = set()
        self.watchers = {}

    async def load(self):
        if not self.enabled:
            return
        try:
            async with asyncio.timeout(3):
                result = await self.bridge.call('reply_timing', action='read')
                self.estimator.samples = [normalize_timing_sample(sample) for sample in result['samples'][-128:]]
        except Exception:
            logging.getLogger(__name__).warning('Reply timing history unavailable; using configured baseline')

    def begin(self, run_id, **kwargs):
        if self.enabled:
            self.estimator.begin(run_id, **kwargs)

    def notice(self, event):
        run_id = event['run_id']
        run = self.estimator.runs.get(run_id)
        if run is None or event.get('metadata', {}).get('origin') in {'background', 'event'}:
            return None
        self.estimator.checkpoint(event)
        if run.announced:
            return None
        estimate = self.estimator.estimate(run_id)
        if estimate['estimated_total_seconds'] <= 30:
            return None
        run.announced = True
        seconds = estimate['estimated_remaining_seconds']
        duration = f'{math.ceil(seconds / 10) * 10} 秒' if seconds < 60 else f'{math.ceil(seconds / 60)} 分钟'
        return {'text': f'这次回复预计还需要约 {duration}，完成后会发给你。',
                'artifacts': [], 'reply_estimate': estimate}

    def finish(self, run_id, *, success):
        watcher = self.watchers.pop(run_id, None)
        if watcher:
            watcher.cancel()
        sample = self.estimator.finish(run_id, success=success)
        if sample is None:
            return
        task = asyncio.create_task(self._save(sample))
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)

    def watch(self, event, announce):
        run = self.estimator.runs.get(event['run_id'])
        if run is None or run.announced:
            return
        async def overdue():
            await asyncio.sleep(max(0, 30 - (self.estimator.clock() - run.started)))
            await announce(event)
        self.watchers[event['run_id']] = asyncio.create_task(overdue())

    async def _save(self, sample):
        try:
            async with asyncio.timeout(3):
                await self.bridge.call('reply_timing', action='record', sample=sample)
        except Exception:
            logging.getLogger(__name__).warning('Reply timing sample could not be saved')

    async def close(self):
        tasks = [*self.pending, *self.watchers.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.watchers.clear()
        self.estimator.runs.clear()
