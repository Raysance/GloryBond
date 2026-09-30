#!/usr/bin/env python3
"""Adopt the existing Aliyun services into three modules, with a rollback journal.

This host-specific migration deliberately preserves working Python/QQ runtimes,
Git checkouts, deployment output, and old absolute paths. Run --plan first.
"""

import argparse
import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


ROOT = Path('/srv/modules')
BACKUPS = Path('/srv/module-backups')
NGINX = Path('/usr/local/nginx/conf/nginx.conf')
UNIT_DIR = Path('/etc/systemd/system')
RUNNER = 'actions.runner.Raysance-Studio.izhdxlz.service'
MEMBERS = {
    'hok': ['hok-napcat.service', 'hok-nbot.service', 'hok-web.service',
            'hok-temp-files-cleanup.timer'],
    'personal-site': ['raysance-decap-oauth.service'],
    'clash': ['clash.service'],
}


def run(*args, check=True, **kwargs):
    return subprocess.run(args, check=check, text=True, capture_output=True, **kwargs)


def active(unit):
    return run('systemctl', 'is-active', '--quiet', unit, check=False).returncode == 0


def atomic_text(path, value, mode=0o644):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.module-new')
    with temporary.open('w', encoding='utf-8') as stream:
        stream.write(value)
    temporary.chmod(mode)
    temporary.replace(path)


def moves():
    """Children that belong elsewhere are extracted before relocating parents."""
    return [
        ('/QQBot/Web/raysance-site', 'personal-site/apps/site'),
        ('/QQBot/Web/html/raysance', 'personal-site/public'),
        ('/etc/raysance-decap-oauth.env', 'personal-site/config/oauth.env'),
        ('/var/lib/raysance-agent-api', 'personal-site/state'),
        ('/usr/local/bin/node-raysance-cms', 'personal-site/runtime/node'),
        ('/clash-for-linux', 'clash/apps/engine'),
        ('/QQBot/NBot', 'hok/apps/NBot'),
        ('/QQBot/Web', 'hok/apps/Web'),
        ('/root/Napcat', 'hok/apps/napcat'),
        ('/root/.config/QQ', 'hok/data/qq-profile'),
        ('/QQBot/Lagrange', 'hok/legacy/Lagrange'),
        ('/QQBot/BotDemo', 'hok/legacy/BotDemo'),
        ('/QQBot/Napcat', 'hok/legacy/napcat-installer'),
        ('/QQBot/backups', 'hok/backups/postgres-history'),
        ('/QQBot/redis-migration-backups', 'hok/backups/redis-history'),
    ]


class Transaction:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=False)
        self.journal = {'root': str(ROOT), 'actions': [], 'enabled': {}, 'active': {}, 'complete': False}
        self.flush()

    def flush(self):
        atomic_text(self.directory / 'journal.json', json.dumps(self.journal, indent=2), 0o600)

    def write(self, path, text, mode=0o644):
        path = Path(path)
        if path.is_symlink():
            raise RuntimeError(f'Refusing to overwrite a symlink: {path}')
        index = len(self.journal['actions'])
        backup = None
        if path.exists():
            backup = self.directory / f'file-{index}'
            shutil.copy2(path, backup)
        self.journal['actions'].append({'kind': 'write', 'path': str(path), 'backup': str(backup) if backup else None})
        self.flush()
        atomic_text(path, text, mode)

    def relocate(self, old, new):
        old, new = Path(old), Path(new)
        if old.is_symlink() or not old.exists() or new.exists():
            raise RuntimeError(f'Unexpected relocation source/target: {old} -> {new}')
        # Resolve parents so nested moves remain reversible after parent moves.
        old = old.parent.resolve() / old.name
        new.parent.mkdir(parents=True, exist_ok=True)
        self.journal['actions'].append({'kind': 'move', 'old': str(old), 'new': str(new)})
        self.flush()
        old.rename(new)
        old.symlink_to(new, target_is_directory=new.is_dir())

    def link(self, path, destination):
        path = Path(path)
        if path.exists() or path.is_symlink():
            raise RuntimeError(f'Link already exists: {path}')
        path.parent.mkdir(parents=True, exist_ok=True)
        self.journal['actions'].append({'kind': 'link', 'path': str(path)})
        self.flush()
        path.symlink_to(destination)

    def chmod(self, path, mode):
        path = Path(path)
        self.journal['actions'].append({'kind': 'chmod', 'path': str(path),
                                       'mode': path.stat().st_mode & 0o7777})
        self.flush()
        path.chmod(mode)


def split_nginx(text):
    """Split this host's simple server blocks without changing location content."""
    lines = text.splitlines(keepends=True)
    shared, blocks = [], {'hok': [], 'personal-site': []}
    i = 0
    while i < len(lines):
        if not re.match(r'^    server\s*\{', lines[i]):
            shared.append(lines[i])
            i += 1
            continue
        block, depth = [], 0
        while i < len(lines):
            line = lines[i]
            block.append(line)
            lexical = re.sub(r'"[^"\n]*"|\x27[^\x27\n]*\x27|#.*', '', line)
            depth += lexical.count('{') - lexical.count('}')
            i += 1
            if depth == 0:
                break
        body = ''.join(block)
        if 'server_name  hok.example_user_29.top;' in body:
            owner = 'hok'
            body = body.replace('root html;', 'root /srv/modules/hok/public;')
            body = body.replace('/QQBot/NBot/file_transfer/', '/srv/modules/hok/data/file_transfer/')
        elif re.search(r'server_name\s+example_user_29\.top;', body):
            owner = 'personal-site'
            body = body.replace('root html/raysance;', 'root /srv/modules/personal-site/public;')
            body = body.replace('/QQBot/NBot/file_transfer/', '/srv/modules/hok/data/file_transfer/')
        else:
            raise RuntimeError('Unexpected Nginx server block; manual review required')
        blocks[owner].append(body)
    if len(blocks['hok']) != 1 or len(blocks['personal-site']) != 2:
        raise RuntimeError('Expected one HOK and two personal-site server blocks')
    shared_text = ''.join(shared)
    offset = shared_text.rfind('}')
    includes = ('    include /srv/modules/hok/nginx/site.conf;\n'
                '    include /srv/modules/personal-site/nginx/site.conf;\n')
    return shared_text[:offset] + includes + shared_text[offset:], blocks


def insert_partof(unit_text, target):
    return unit_text.replace('[Unit]\n', f'[Unit]\nPartOf={target}\n', 1)


def target_text(name):
    dependencies = {'hok': 'redis.service postgresql-16.service clash.service',
                    'personal-site': '', 'clash': ''}[name]
    units = ' '.join(MEMBERS[name])
    return (f'[Unit]\nDescription={name} complete application module\n'
            f'Wants=network-online.target {dependencies} {units}\n'
            f'After=network-online.target {dependencies}\n'
            '\n[Install]\nWantedBy=multi-user.target\n')


def health():
    results = {unit: active(unit) for items in MEMBERS.values() for unit in items}
    for name in MEMBERS:
        results[f'{name}.target'] = active(f'{name}.target')
    probes = [
        ('website', ['curl', '--silent', '--show-error', '--output', '/dev/null', '--write-out', '%{http_code}', '--max-time', '8', '--resolve', 'example_user_29.top:443:127.0.0.1', 'https://example_user_29.top/'], '200'),
        ('hok-web', ['curl', '--silent', '--show-error', '--output', '/dev/null', '--write-out', '%{http_code}', '--max-time', '8', '--resolve', 'hok.example_user_29.top:443:127.0.0.1', 'https://hok.example_user_29.top/health'], '200'),
        ('oauth', ['curl', '--silent', '--output', '/dev/null', '--write-out', '%{http_code}', '--max-time', '4', 'http://127.0.0.1:9105/healthz'], '204'),
    ]
    for name, command, expected in probes:
        result = run(*command, check=False)
        results[name] = result.returncode == 0 and result.stdout == expected
    import socket
    for name, port in [('nonebot-port', 8080), ('clash-port', 7890), ('napcat-http', 4001)]:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=3):
                results[name] = True
        except OSError:
            results[name] = False
    return results


def rollback(directory):
    directory = Path(directory)
    journal = json.loads((directory / 'journal.json').read_text())
    if RUNNER in journal['active']:
        if run('pgrep', '-f', '^.*Runner.Worker.*$', check=False).returncode == 0:
            raise RuntimeError('A CI job is running; retry rollback after it finishes')
        run('systemctl', 'stop', RUNNER)
    for name in MEMBERS:
        run('systemctl', 'stop', f'{name}.target', check=False)
    for items in MEMBERS.values():
        for unit in items:
            run('systemctl', 'stop', unit, check=False)
    for action in reversed(journal['actions']):
        if action['kind'] == 'write':
            path = Path(action['path'])
            if action['backup']:
                shutil.copy2(action['backup'], path)
            elif path.exists():
                path.unlink()
        elif action['kind'] == 'link':
            path = Path(action['path'])
            if path.is_symlink():
                path.unlink()
        elif action['kind'] == 'chmod':
            Path(action['path']).chmod(action['mode'])
        elif action['kind'] == 'move':
            old, new = Path(action['old']), Path(action['new'])
            if old.is_symlink():
                old.unlink()
            if new.exists() and not old.exists():
                new.rename(old)
    run('systemctl', 'daemon-reload')
    for unit, was_enabled in journal['enabled'].items():
        run('systemctl', 'enable' if was_enabled else 'disable', unit, check=False)
    for unit, was_active in journal['active'].items():
        if was_active:
            run('systemctl', 'start', unit, check=False)
    run('nginx', '-t')
    run('systemctl', 'reload', 'nginx')
    print(f'Rolled back filesystem/configuration changes using {directory}', flush=True)


def apply(source_dir):
    if os.geteuid() != 0:
        raise RuntimeError('Run as root')
    for old, new in moves():
        if Path(old).is_symlink() or not Path(old).exists() or (ROOT / new).exists():
            raise RuntimeError(f'Preflight path mismatch: {old} -> {ROOT / new}')
    if run('pgrep', '-f', '^.*Runner.Worker.*$', check=False).returncode == 0:
        raise RuntimeError('A GitHub Actions job is running; retry after it finishes')
    shared, blocks = split_nginx(NGINX.read_text())
    run('nginx', '-t')
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    transaction = Transaction(BACKUPS / timestamp)
    all_units = [unit for items in MEMBERS.values() for unit in items] + [RUNNER]
    for unit in all_units:
        transaction.journal['enabled'][unit] = run('systemctl', 'is-enabled', unit, check=False).stdout.strip() == 'enabled'
        transaction.journal['active'][unit] = active(unit)
    for name in MEMBERS:
        transaction.journal['enabled'][f'{name}.target'] = False
    transaction.flush()
    print(f'Rollback journal: {transaction.directory}', flush=True)
    try:
        # Pause the shared deployment agent during path adoption to exclude races.
        run('systemctl', 'stop', RUNNER)
        for name in ['hok', 'personal-site', 'clash']:
            run('systemctl', 'stop', *MEMBERS[name])
        for old, new in moves():
            transaction.relocate(old, ROOT / new)
        # This installation was protected by /root before relocation. Preserve
        # that privacy boundary for OneBot tokens and QQ runtime settings.
        transaction.chmod(ROOT / 'hok/apps/napcat', 0o700)
        internal_moves = [
            ('hok/apps/NBot/file_transfer', 'hok/data/file_transfer'),
            ('hok/apps/NBot/log', 'hok/logs/nbot'),
            ('hok/apps/Web/html', 'hok/public'),
            ('clash/apps/engine/conf', 'clash/config'),
            ('clash/apps/engine/logs', 'clash/logs'),
        ]
        for old, new in internal_moves:
            transaction.relocate(ROOT / old, ROOT / new)
        # data/ contains Git-tracked files; git restore would replace an outward
        # directory symlink. Keep it real until CI uses external data paths.
        transaction.link(ROOT / 'hok/data/nbot', '../apps/NBot/data')
        for name in MEMBERS:
            for child in ['systemd', 'nginx', 'ops']:
                (ROOT / name / child).mkdir(parents=True, exist_ok=True)
        for filename in ['config.yaml', '.env']:
            transaction.link(ROOT / 'hok/config' / filename, '../apps/NBot/' + filename)
        # Git-tracked application settings keep their ownership and live paths;
        # config/ presents a stable two-file catalog without duplicate settings.
        paths = {
            'hok-nbot.service': [('/QQBot/NBot', '/srv/modules/hok/apps/NBot')],
            'hok-web.service': [('/QQBot/Web', '/srv/modules/hok/apps/Web')],
            'hok-napcat.service': [('/QQBot/NBot', '/srv/modules/hok/apps/NBot'), ('/root/Napcat', '/srv/modules/hok/apps/napcat')],
            'hok-temp-files-cleanup.service': [('/QQBot/NBot/file_transfer', '/srv/modules/hok/data/file_transfer')],
            'hok-temp-files-cleanup.timer': [],
            'raysance-decap-oauth.service': [('/QQBot/Web/raysance-site', '/srv/modules/personal-site/apps/site'), ('/etc/raysance-decap-oauth.env', '/srv/modules/personal-site/config/oauth.env'), ('/usr/local/bin/node-raysance-cms', '/srv/modules/personal-site/runtime/node')],
            'clash.service': [('/clash-for-linux/conf', '/srv/modules/clash/config'), ('/clash-for-linux', '/srv/modules/clash/apps/engine')],
        }
        for unit, replacements in paths.items():
            owner = 'personal-site' if unit.startswith('raysance-') else 'clash' if unit == 'clash.service' else 'hok'
            content = insert_partof((UNIT_DIR / unit).read_text(), f'{owner}.target')
            for old, new in replacements:
                content = content.replace(old, new)
            if owner == 'hok':
                environment = (
                    'EnvironmentFile=/srv/modules/hok/apps/NBot/.env\n'
                    'Environment=BOT_PATH=/srv/modules/hok/apps/NBot\n'
                    'Environment=HOK_CONFIG_FILE=/srv/modules/hok/apps/NBot/config.yaml\n'
                    'Environment=HOK_DATA_DIR=/srv/modules/hok/data/nbot\n'
                    'Environment=HOK_FILE_TRANSFER_DIR=/srv/modules/hok/data/file_transfer\n'
                    'Environment=HOK_LOG_DIR=/srv/modules/hok/logs/nbot\n'
                )
                if unit == 'hok-web.service':
                    environment += 'Environment=WEB_PATH=/srv/modules/hok/apps/Web\n'
                if unit == 'hok-nbot.service':
                    environment += 'Environment=HOK_NB_BIN=/root/miniconda3/bin/nb\n'
                content = content.replace('[Service]\n', '[Service]\n' + environment, 1)
            if owner == 'personal-site':
                content = content.replace('[Service]\n', '[Service]\nEnvironment=CONTENT_ROOT=/srv/modules/personal-site/apps/site/src/content\nEnvironment=DEPLOYMENT_STATUS_FILE=/srv/modules/personal-site/state/deployment.json\n', 1)
            transaction.write(ROOT / owner / 'systemd' / unit, content)
            transaction.write(UNIT_DIR / unit, content)
        for name in MEMBERS:
            content = target_text(name)
            transaction.write(ROOT / name / 'systemd' / f'{name}.target', content)
            transaction.write(UNIT_DIR / f'{name}.target', content)
        for name in blocks:
            transaction.write(ROOT / name / 'nginx/site.conf', '\n'.join(blocks[name]))
        transaction.write(NGINX, shared)
        # Replace aliases that bypass systemd, preserving the rest of shell setup.
        bashrc = Path('/root/.bashrc')
        text = bashrc.read_text()
        text = text.replace("alias clash='/clash-for-linux/start.sh'", "alias clash='modulectl status clash'")
        text = text.replace("alias nap='xvfb-run -a /root/Napcat/opt/QQ/qq --no-sandbox'", "alias nap='systemctl status hok-napcat.service'")
        transaction.write(bashrc, text, bashrc.stat().st_mode & 0o777)
        for name in MEMBERS:
            legacy = {old: str(Path(new).relative_to(name)) for old, new in moves() if new.startswith(name + '/')}
            manifest = {
                'schema_version': 1, 'name': name, 'target': name + '.target',
                'members': MEMBERS[name],
                'shared_dependencies': {'hok': ['nginx.service', 'redis.service', 'postgresql-16.service', 'clash.service'], 'personal-site': ['nginx.service'], 'clash': []}[name],
                'legacy_links': legacy,
                'portable_notes': ['Restore at /srv/modules or re-render absolute paths before installation.', 'Configuration/QQ sessions contain credentials; keep exports private.', 'Virtualenvs, database engines, certificates and host build toolchains must be installed on the target.'],
                'adopted_at': timestamp,
            }
            transaction.write(ROOT / name / 'module.json', json.dumps(manifest, indent=2) + '\n')
        for filename in ['modulectl.py', 'snapshot_hok.py', 'verify_export.py', 'migrate_aliyun.py', 'README.md']:
            source = source_dir / filename
            if source.is_file():
                transaction.write(ROOT / 'bin' / filename, source.read_text(), 0o755 if filename.endswith('.py') else 0o644)
        launcher = '#!/bin/sh\nexec /root/miniconda3/bin/python /srv/modules/bin/modulectl.py "$@"\n'
        transaction.write('/usr/local/bin/modulectl', launcher, 0o755)
        for name in MEMBERS:
            # Exports carry real tools, not links to the unbundled shared bin/.
            for filename in ['modulectl.py', 'snapshot_hok.py', 'verify_export.py']:
                transaction.write(ROOT / name / 'ops' / filename,
                                  (source_dir / filename).read_text(), 0o755)
            transaction.write(ROOT / name / 'README.md',
                              (source_dir / 'README.md').read_text())
        # Record installed distributions without embedding index credentials.
        distribution_probe = (
            'import importlib.metadata as m; '
            'print("\\n".join(sorted({d.metadata["Name"] + "==" + d.version '
            'for d in m.distributions() if d.metadata["Name"]})))'
        )
        for name, interpreter in [
            ('nbot', ROOT / 'hok/apps/NBot/.venv/bin/python'),
            ('web', Path('/root/miniconda3/bin/python')),
        ]:
            pins = run(str(interpreter), '-c', distribution_probe).stdout
            transaction.write(ROOT / 'hok/runtime' / f'{name}-requirements.txt', pins)
        # Check all configs before scheduling any new process.
        run('nginx', '-t')
        units = [str(UNIT_DIR / unit) for unit in paths] + [str(UNIT_DIR / (name + '.target')) for name in MEMBERS]
        run('systemd-analyze', 'verify', *units)
        run('systemctl', 'daemon-reload')
        for name in MEMBERS:
            run('systemctl', 'disable', *MEMBERS[name])
            run('systemctl', 'enable', name + '.target')
        for name in ['clash', 'personal-site', 'hok']:
            run('systemctl', 'start', name + '.target')
        run('systemctl', 'reload', 'nginx')
        result = {}
        for _ in range(24):
            result = health()
            if all(result.values()):
                break
            time.sleep(3)
        print(json.dumps(result, indent=2), flush=True)
        if not all(result.values()):
            raise RuntimeError('Module health checks failed')
        if transaction.journal['active'][RUNNER]:
            run('systemctl', 'start', RUNNER)
        transaction.journal['complete'] = True
        transaction.flush()
        print(f'Module migration complete; rollback retained in {transaction.directory}', flush=True)
    except BaseException:
        print('Migration failed; restoring original layout and services', flush=True)
        rollback(transaction.directory)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--plan', action='store_true')
    group.add_argument('--apply', action='store_true')
    group.add_argument('--rollback', type=Path)
    args = parser.parse_args()
    if args.plan:
        print(json.dumps({'moves': moves(), 'targets': MEMBERS, 'nginx': str(NGINX), 'rollback_root': str(BACKUPS)}, indent=2))
    elif args.rollback:
        rollback(args.rollback)
    else:
        apply(Path(__file__).resolve().parent)


if __name__ == '__main__':
    main()
