"""Reply latency forecasts from anonymous completed-run landmarks; no model calls."""

from dataclasses import dataclass, field
import math
import statistics
import time

from .tools.reply_timing import normalize_timing_sample


@dataclass
class TimingRun:
    model: str
    started: float
    images: bool
    checkpoints: dict = field(default_factory=lambda: {"start": 0.0})
    stage: str = "start"
    announced: bool = False


class ReplyTimingEstimator:
    def __init__(self, *, samples=(), cold_start_seconds=60, clock=time.monotonic):
        self.samples = [normalize_timing_sample(sample) for sample in list(samples)[-128:]]
        self.cold_start_seconds = max(1, float(cold_start_seconds))
        self.clock = clock
        self.runs = {}

    def begin(self, run_id, *, model, started=None, images=False):
        self.runs[run_id] = TimingRun(model, self.clock() if started is None else started, images)

    def checkpoint(self, event):
        run = self.runs.get(event['run_id'])
        if run is None:
            return
        kind, data = event['kind'], event['data']
        if kind == 'model.request':
            stage = 'model:' + str(data.get('round', 1))
        elif kind == 'reply.model.request':
            stage = 'reply:' + str(data.get('attempt', 1))
        elif kind == 'tool.call':
            name = data.get('function', {}).get('name', '')
            stage = 'tool:' + name + ':' + str(data.get('round', 1))
        else:
            return
        run.stage = stage
        run.checkpoints.setdefault(stage, max(0, self.clock() - run.started))

    def estimate(self, run_id):
        run = self.runs[run_id]
        elapsed = max(0, self.clock() - run.started)
        samples = [s for s in self.samples if s.get('model') == run.model
                   and s.get('images') == run.images and run.stage in s.get('checkpoints', {})]
        # A stage-specific residual accounts for actual rounds/tools already
        # selected. Unfinished/failed runs never become successful latency data.
        since_stage = elapsed - run.checkpoints[run.stage]
        remaining = [s['total_seconds'] - s['checkpoints'][run.stage] - since_stage for s in samples]
        remaining = sorted(value for value in remaining if value > 0)
        if remaining:
            expected = statistics.median(remaining)
            lower = remaining[int((len(remaining) - 1) * .25)]
            upper = remaining[math.ceil((len(remaining) - 1) * .75)]
            source = 'completed_runs'
        else:
            # Cold start and overruns remain explicitly uncalibrated estimates.
            expected = max(10, self.cold_start_seconds - since_stage)
            lower, upper, source = expected * .5, expected * 1.5, 'configured_baseline'
        return {'estimated_total_seconds': math.ceil(elapsed + expected),
                'estimated_remaining_seconds': math.ceil(expected),
                'remaining_range_seconds': [math.ceil(lower), math.ceil(upper)],
                'elapsed_seconds': round(elapsed, 2), 'source': source,
                'sample_count': len(remaining), 'stage': run.stage, 'is_estimate': True}

    def finish(self, run_id, *, success):
        run = self.runs.pop(run_id, None)
        if run is None or not success:
            return None
        sample = {'model': run.model, 'images': run.images,
                  'total_seconds': round(max(0, self.clock() - run.started), 3),
                  'checkpoints': {key: round(value, 3) for key, value in run.checkpoints.items()}}
        self.samples = [*self.samples, sample][-128:]
        return sample
