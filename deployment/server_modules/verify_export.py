#!/usr/bin/env python3
"""Read an exported module without extracting secrets; validate every file hash."""

import argparse
import base64
import hashlib
import json
from pathlib import PurePosixPath
import tarfile


def verify(path):
    observed = {}
    manifest = None
    redis_keys = 0
    postgres_header = False
    with tarfile.open(path, 'r|gz') as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts:
                raise ValueError('Unsafe archive member path')
            if not member.isfile():
                continue
            stream = archive.extractfile(member)
            if member.name.endswith('/export-manifest.json'):
                manifest = json.load(stream)
                continue
            digest = hashlib.sha256()
            if member.name.endswith('/snapshots/redis-db0-hok.jsonl'):
                for line in stream:
                    digest.update(line)
                    record = json.loads(line)
                    if record['type'] == 'metadata':
                        assert record['db'] == 0 and record['pattern'] == 'hok:*'
                    elif record['type'] == 'key':
                        assert base64.b64decode(record['key_b64'], validate=True).startswith(b'hok:')
                        assert base64.b64decode(record['dump_b64'], validate=True)
                        assert record['ttl_ms'] == -1 or record['ttl_ms'] >= 0
                        redis_keys += 1
                    elif record['type'] == 'summary':
                        assert redis_keys == record['key_count']
            else:
                first = True
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    if first and member.name.endswith('/snapshots/postgresql.dump'):
                        postgres_header = block.startswith(b'PGDMP')
                    first = False
                    digest.update(block)
            if member.name in observed:
                raise ValueError('Duplicate regular file member')
            observed[member.name] = digest.hexdigest()
    if not manifest:
        raise ValueError('Missing export manifest')
    expected = {item['path']: item['sha256'] for item in manifest['entries'] if item['type'] == 'file'}
    if observed != expected:
        raise ValueError('Archive file inventory/hash mismatch')
    if manifest['module'] == 'hok' and not postgres_header:
        raise ValueError('Missing or invalid PostgreSQL custom dump')
    return {'module': manifest['module'], 'verified_files': len(observed),
            'redis_hok_keys': redis_keys, 'postgres_custom_dump': postgres_header,
            'capture_mode': manifest.get('capture_mode', 'online')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive')
    args = parser.parse_args()
    print(json.dumps(verify(args.archive)))
