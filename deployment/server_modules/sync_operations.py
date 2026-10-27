#!/usr/bin/env python3
"""Synchronize current HOK maintenance tools with a private rollback snapshot."""

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile

CURRENT = ('modulectl.py', 'snapshot_hok.py', 'verify_export.py', 'refresh_export.py')
RETIRED = ('migrate_aliyun.py', 'unify_project.py', 'ALIYUN_HANDOFF.md', 'UNIFIED_PROJECT.md', 'sync_operations.py', 'README.md')


def atomic_write(path, content, mode):
    descriptor, temporary = tempfile.mkstemp(prefix='.ops-sync-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def synchronize(module, *, apply=False, source=None):
    module = Path(module).resolve()
    source = Path(source) if source is not None else Path(__file__).resolve().parent
    if json.loads((module / 'module.json').read_text()).get('name') != 'hok':
        raise ValueError('Select the HOK module')
    operations = module / 'ops'
    if operations.is_symlink():
        raise ValueError('The HOK operations directory must be local to its module')
    for name in CURRENT:
        if not (source / name).is_file():
            raise ValueError('Missing current maintenance tool: ' + name)
    for name in [*CURRENT, *RETIRED]:
        if (operations / name).is_dir() and not (operations / name).is_symlink():
            raise ValueError('Unexpected directory in maintenance tools: ' + name)
    changed = [name for name in CURRENT if (operations / name).is_symlink()
               or not (operations / name).exists()
               or (operations / name).read_bytes() != (source / name).read_bytes()
               or ((operations / name).stat().st_mode & 0o777) != (0o755 if name.endswith('.py') else 0o644)]
    retired = [name for name in RETIRED if (operations / name).exists() or (operations / name).is_symlink()]
    result = {'updated': changed, 'retired': retired, 'applied': False}
    if not apply or not changed + retired:
        return result
    operations.mkdir(parents=True, exist_ok=True)
    backups = module / 'backups'
    backups.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='maintenance-', dir=backups))
    directory.chmod(0o700)
    saved = {}
    for name in [*changed, *retired]:
        path = operations / name
        if path.is_symlink():
            saved[name] = {'link': str(path.readlink())}
        elif path.exists():
            shutil.copy2(path, directory / name)
            saved[name] = {'mode': path.stat().st_mode & 0o777}
        else:
            saved[name] = None
    (directory / 'files.json').write_text(json.dumps(saved, indent=2))
    try:
        for name in changed:
            atomic_write(operations / name, (source / name).read_bytes(), 0o755 if name.endswith('.py') else 0o644)
        for name in retired:
            (operations / name).unlink()
    except BaseException:
        for name, previous in saved.items():
            path = operations / name
            if previous is None:
                path.unlink(missing_ok=True)
            elif 'link' in previous:
                path.unlink(missing_ok=True)
                path.symlink_to(previous['link'])
            else:
                atomic_write(path, (directory / name).read_bytes(), previous['mode'])
        raise
    return {**result, 'applied': True, 'backup': str(directory)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(synchronize(args.module, apply=args.apply)))


if __name__ == '__main__':
    main()
