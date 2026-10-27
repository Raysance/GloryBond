#!/usr/bin/env python3
"""Resolve configured players from latest DB names using the normal paced adapter."""
import argparse
import inspect
import json
from pathlib import Path
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from local_debugger import import_hok_module


def select_candidate(result, nickname, existing=None):
    """Only exact names or a previously verified identical reference may bind."""
    candidates = [candidate for candidate in result["candidates"] if candidate["nickname"] == nickname]
    if existing:
        same_identity = [candidate for candidate in candidates if all(
            str(candidate.get(field)) == str(existing.get(field))
            for field in ("uid", "logic_world_id", "platform"))]
        if len(same_identity) == 1:
            return same_identity[0], candidates
        # A different unique nickname match must never silently replace a bound account.
        return None, candidates
    return (candidates[0] if len(candidates) == 1 else None), candidates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh', help='Read the existing server DB through this SSH host')
    parser.add_argument('--remote-root', default='/srv/modules/hok/apps/HOK_QQBot')
    parser.add_argument('--remote-python', default='.venv/bin/python')
    parser.add_argument('--redis-port', type=int, help='Local SSH tunnel port to the same server DB0 (required with --ssh)')
    parser.add_argument('--refresh', action='store_true', help='Requery all selected players, preserving verified identities')
    parser.add_argument('--apply', action='store_true', help='Save unique exact nickname matches to config.yaml')
    parser.add_argument('--players', nargs='*', help='Only resolve these configured player keys')
    args = parser.parse_args()
    if args.ssh and not args.redis_port:
        parser.error('--ssh requires --redis-port pointing to the same server DB0')
    zdb = import_hok_module('zdb')
    zfunc = import_hok_module('zfunc')
    zfile = import_hok_module('zfile')
    static = import_hok_module('zstatic')
    dynamic = import_hok_module('zdynamic')
    from hok.api_adapters.player_client import PlayerClientRateLimited
    if args.redis_port:
        import redis
        dynamic.redis_deamon = redis.Redis(host='127.0.0.1', port=args.redis_port, db=0,
                                          socket_timeout=5, socket_connect_timeout=5)
    roles = {**static.confs['StaticVariables']['roleidlist'], **static.confs['StaticVariables']['extra_roleidlist']}
    if args.players:
        unknown = set(args.players) - roles.keys()
        if unknown:
            parser.error('Unknown player keys: ' + ', '.join(sorted(unknown)))
        roles = {key: role for key, role in roles.items() if key in args.players}
    # Transmit the current read-only accessor to older servers without deploying code.
    if args.ssh:
        source = ('import json\nfrom local_debugger import import_hok_module\n'
                  'zdb=import_hok_module("zdb")\n_connect=zdb._connect\n'
                  + inspect.getsource(zdb.load_latest_player_client_names)
                  + '\nprint(json.dumps(load_latest_player_client_names(' + repr(list(roles.values())) + '),ensure_ascii=False))\n')
        command = 'cd ' + shlex.quote(args.remote_root) + ' && ' + shlex.quote(args.remote_python) + ' -'
        result = subprocess.run(['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', args.ssh, command],
                                input=source, text=True, capture_output=True, timeout=120)
        if result.returncode:
            print('DB read failed; remote error text withheld', flush=True)
            return 1
        rows = json.loads(result.stdout)
    else:
        rows = zdb.load_latest_player_client_names(list(roles.values()))
    names = {str(row['role_id']): row for row in rows}
    existing = static.player_client_config.get('players', {})
    failed = []
    search_cache = {}
    try:
        for key, role in roles.items():
            if key in static.player_client_config.get("binding_skip_players", []):
                print(key, "skipped_by_configuration", flush=True)
                continue
            if key in existing and not args.refresh:
                print(key, 'already_bound', flush=True)
                continue
            row = names.get(str(role))
            override = static.player_client_config.get('nickname_overrides', {}).get(key)
            if override:
                row = {'nickname': override, 'epoch': None, 'source': 'configured_nickname_override'}
            if not row:
                failed.append(key)
                print(key, 'missing_database_nickname', flush=True)
                if args.apply:
                    zfile.save_player_client_bindings({}, pending={key: {'source_role_id': role, 'nickname': None, 'status': 'missing_database_nickname'}})
                continue
            try:
                if row['nickname'] not in search_cache:
                    search_cache[row['nickname']] = zfunc.player_client_query('search', name=row['nickname'], platform=None)
                result = search_cache[row['nickname']]
                chosen, candidates = select_candidate(result, row['nickname'], existing.get(key))
                if chosen is None:
                    failed.append(key)
                    print(key, 'unresolved_exact_matches', len(candidates), flush=True)
                    if args.apply:
                        status = ('existing_reference_not_found' if key in existing else
                                  'ambiguous_exact_nickname' if candidates else 'no_exact_match_both_platforms')
                        zfile.save_player_client_bindings({}, pending={key: {
                            'source_role_id': role, 'nickname': row['nickname'], 'status': status,
                            'candidates': candidates, 'platform_results': [
                                {'platform': r['platform'], 'result_code': r['result_code'], 'count': r['count']}
                                for r in result.get('platform_results', [])]}})
                    continue
                candidate = {**existing.get(key, {}), **chosen, 'source_role_id': role,
                             'source_epoch': row['epoch'], 'source': row['source']}
                if args.apply:
                    zfile.save_player_client_bindings({key: candidate})
                print(key, 'bound' if args.apply else 'unique_match_preview', 'platform', candidate['platform'], flush=True)
            except Exception as error:
                failed.append(key)
                print(key, 'failed', type(error).__name__, 'code', getattr(error, 'code', None), flush=True)
                if args.apply:
                    zfile.save_player_client_bindings({}, pending={key: {
                        'source_role_id': role, 'nickname': row['nickname'], 'status': 'batch_error',
                        'error_type': type(error).__name__, 'error_code': getattr(error, 'code', None)}})
                # Stop on any rejection/transport issue. No retries or cooldown bypass.
                if isinstance(error, PlayerClientRateLimited):
                    print('retry_after', error.retry_after, flush=True)
                print('Batch stopped; previous bindings retained', flush=True)
                return 1
    finally:
        zfunc.player_client_close()
    print('Unresolved:', ', '.join(failed) if failed else 'none', flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print('Player resolution failed:', type(error).__name__, '(details withheld)', file=sys.stderr)
        raise SystemExit(1)
