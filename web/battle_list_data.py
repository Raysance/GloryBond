"""Compact list-page payloads without downloading native client match protocols."""
import json
from functools import lru_cache
from pathlib import Path

from web.runtime_config import RUNTIME


def compact_battle_list(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('btlist'), dict):
        return payload
    btlist = payload['btlist']
    rows = [{key: value for key, value in row.items() if key not in ('clientMatch', 'clientPlayer')}
            for row in btlist.get('list', [])]
    return {**payload, 'btlist': {**btlist, 'list': rows}}


@lru_cache(maxsize=8)
def _read_compact(path, modified_ns, size):
    with open(path, encoding='utf-8') as source:
        return compact_battle_list(json.load(source))


def load_battle_list(local_path):
    filename = Path(local_path).name
    if str(local_path) != f'file_transfer/temp_files/{filename}' or not filename.endswith('.json'):
        raise ValueError('invalid battle-list path')
    path = RUNTIME.file_transfer_dir / 'temp_files' / filename
    stat = path.stat()
    return _read_compact(str(path), stat.st_mtime_ns, stat.st_size)
