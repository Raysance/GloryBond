"""Compact list-page payloads without downloading native client match protocols."""
import json
from functools import lru_cache
from pathlib import Path

from web.runtime_config import RUNTIME


def profile_only_battle_list(profile, reason=None, *, unavailable=False):
    """Publish only the selected role's display fields for a hidden battle list."""
    profile = profile if isinstance(profile, dict) else {}
    roles = [role for role in (profile.get('roleList') or []) if isinstance(role, dict)]
    target_id = profile.get('targetRoleId')
    if target_id not in (None, ''):
        roles = [role for role in roles if str(role.get('roleId')) == str(target_id)]
    fields = ('roleName', 'roleIcon', 'roleJobName', 'areaName', 'serverName', 'gameLevel')
    display = {key: roles[0][key] for key in fields if key in roles[0]} if len(roles) == 1 else {}
    return {'profile': {'roleList': [display] if display else []},
            'btlist': {'invisible': not unavailable, 'unavailable': unavailable, 'invisDes': reason, 'list': []}}


def visible_period_data(payload):
    """Old period artifacts contain per-day visibility instead of a battle list."""
    days = payload.get('periods') if isinstance(payload, dict) else payload
    if not isinstance(days, list) or not any(isinstance(day, dict) and day.get('visible') is False for day in days):
        return payload
    available = [day for day in days if isinstance(day, dict) and day.get('visible') is not False]
    if available:
        return {**payload, 'periods': available} if isinstance(payload, dict) else available
    first = next(day for day in days if isinstance(day, dict))
    role = {'roleName': first.get('nickname'), 'roleJobName': first.get('rank_name') or first.get('rank')}
    return profile_only_battle_list({'roleList': [role]})


def compact_battle_list(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('btlist'), dict):
        return payload
    btlist = payload['btlist']
    if btlist.get('invisible'):
        return profile_only_battle_list(payload.get('profile'), btlist.get('invisDes'))
    rows = [{key: value for key, value in row.items() if key not in ('clientMatch', 'clientPlayer')}
            for row in btlist.get('list', [])]
    return {**payload, 'btlist': {**btlist, 'list': rows}}


@lru_cache(maxsize=8)
def _read_compact(path, modified_ns, size):
    with open(path, encoding='utf-8') as source:
        payload = json.load(source)
        if isinstance(payload, str):
            payload = json.loads(payload)
        return compact_battle_list(payload)


def load_battle_list(local_path):
    filename = Path(local_path).name
    if str(local_path) != f'file_transfer/temp_files/{filename}' or not filename.endswith('.json'):
        raise ValueError('invalid battle-list path')
    path = RUNTIME.file_transfer_dir / 'temp_files' / filename
    stat = path.stat()
    return _read_compact(str(path), stat.st_mtime_ns, stat.st_size)
