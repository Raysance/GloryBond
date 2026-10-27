#!/usr/bin/env python3
"""Keep published artifacts readable by Nginx under the service's private umask."""

import argparse
import grp
import json
import os
from pathlib import Path
import stat


def nginx_group(directory, proc=Path('/proc')):
    workers = []
    for process in proc.iterdir():
        if not process.name.isdigit():
            continue
        try:
            if (process / 'comm').read_text().strip() != 'nginx':
                continue
            values = dict(line.split(':', 1) for line in (process / 'status').read_text().splitlines() if ':' in line)
            if int(values['Uid'].split()[1]) == 0:
                continue
            primary = int(values['Gid'].split()[1])
            workers.append((primary, {primary, *map(int, values.get('Groups', '').split())}))
        except (OSError, KeyError, ValueError):
            continue
    if not workers:
        raise RuntimeError('No running Nginx worker; specify --group explicitly')
    current = directory.stat()
    if current.st_mode & stat.S_ISGID and all(current.st_gid in groups for _, groups in workers):
        return current.st_gid
    primary = {group for group, _ in workers}
    if len(primary) != 1:
        raise RuntimeError('Multiple Nginx worker groups; specify --group explicitly')
    return primary.pop()


def prepare(directory, group_id, *, apply=False):
    directory = Path(directory).resolve(strict=True)
    if not directory.is_dir() or directory == Path(directory.anchor) or any(
        (directory / name).exists() for name in ('.env', 'config.yaml', '.git')
    ):
        raise ValueError('Select the public artifact directory, outside private application files')
    result = {'directories_changed': 0, 'files_changed': 0, 'symlinks_skipped': 0,
              'group_id': group_id, 'applied': apply}
    for _, dirs, files, descriptor in os.fwalk(directory, follow_symlinks=False):
        current = os.fstat(descriptor)
        mode = stat.S_IMODE(current.st_mode) | stat.S_IRGRP | stat.S_IXGRP | stat.S_ISGID
        if current.st_gid != group_id or stat.S_IMODE(current.st_mode) != mode:
            result['directories_changed'] += 1
            if apply:
                if current.st_gid != group_id:
                    os.fchown(descriptor, -1, group_id)
                os.fchmod(descriptor, mode)
        for name in dirs:
            if stat.S_ISLNK(os.stat(name, dir_fd=descriptor, follow_symlinks=False).st_mode):
                result['symlinks_skipped'] += 1
        for name in files:
            try:
                current = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if stat.S_ISLNK(current.st_mode):
                    result['symlinks_skipped'] += 1
                    continue
                if not stat.S_ISREG(current.st_mode):
                    continue
                mode = stat.S_IMODE(current.st_mode) | stat.S_IRGRP
                if current.st_gid != group_id or stat.S_IMODE(current.st_mode) != mode:
                    result['files_changed'] += 1
                    if apply:
                        handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
                        try:
                            # Use one descriptor so a concurrent rename cannot redirect chmod.
                            current = os.fstat(handle)
                            if current.st_gid != group_id:
                                os.fchown(handle, -1, group_id)
                            os.fchmod(handle, stat.S_IMODE(current.st_mode) | stat.S_IRGRP)
                        finally:
                            os.close(handle)
            except FileNotFoundError:
                # The normal artifact expiry task may remove a file during deployment.
                continue
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--group', help='Public read group; defaults to the running Nginx worker group')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    group_id = (int(args.group) if args.group.isdigit() else grp.getgrnam(args.group).gr_gid) if args.group else nginx_group(args.directory)
    print(json.dumps(prepare(args.directory, group_id, apply=args.apply)))


if __name__ == '__main__':
    main()
