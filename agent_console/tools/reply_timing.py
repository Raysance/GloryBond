"""Bounded anonymous reply statistics, portable to the trusted storage worker."""

import json
import math
import re


def normalize_timing_sample(sample):
    if not isinstance(sample, dict) or set(sample) != {'model', 'images', 'total_seconds', 'checkpoints'}:
        raise ValueError('Invalid reply timing sample')
    if not isinstance(sample['model'], str) or not 1 <= len(sample['model']) <= 120 or type(sample['images']) is not bool:
        raise ValueError('Invalid timing cohort')
    total = sample['total_seconds']
    points = sample['checkpoints']
    valid = lambda value: type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 7200
    if not valid(total) or not isinstance(points, dict) or not 1 <= len(points) <= 64 or points.get('start') != 0:
        raise ValueError('Invalid timing duration')
    for key, value in points.items():
        if (not isinstance(key, str) or not re.fullmatch(r'start|(?:model|reply):[1-9][0-9]*|tool:[a-zA-Z0-9_]{1,80}:[1-9][0-9]*', key)
                or not valid(value) or value > total):
            raise ValueError('Invalid timing checkpoint')
    return {'model': sample['model'], 'images': sample['images'], 'total_seconds': round(total, 3),
            'checkpoints': {key: round(value, 3) for key, value in points.items()}}


def reply_timing_statistics(store, args):
    key = 'hok:agent_runtime:reply_timing:v1'
    if args.get('action') == 'record':
        sample = normalize_timing_sample(args.get('sample'))
        with store.pipeline(transaction=True) as pipe:
            pipe.lpush(key, json.dumps(sample, ensure_ascii=False, separators=(',', ':')))
            pipe.ltrim(key, 0, 127)
            pipe.execute()
        return {'recorded': True}
    if args.get('action') != 'read':
        raise ValueError('Unknown reply timing action')
    samples = []
    for raw in reversed(store.lrange(key, 0, 127)):
        try:
            samples.append(normalize_timing_sample(json.loads(raw)))
        except (ValueError, TypeError):
            continue
    return {'samples': samples}
