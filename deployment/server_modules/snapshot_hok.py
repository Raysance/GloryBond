#!/usr/bin/env python3
"""Read-only HOK database snapshot helper; run with the application's Python."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone


PG_ENV = {
    "host": "PGHOST", "hostaddr": "PGHOSTADDR", "port": "PGPORT",
    "dbname": "PGDATABASE", "user": "PGUSER", "password": "PGPASSWORD",
    "passfile": "PGPASSFILE", "service": "PGSERVICE", "connect_timeout": "PGCONNECT_TIMEOUT",
    "client_encoding": "PGCLIENTENCODING", "options": "PGOPTIONS", "application_name": "PGAPPNAME",
    "sslmode": "PGSSLMODE", "sslcert": "PGSSLCERT", "sslkey": "PGSSLKEY",
    "sslrootcert": "PGSSLROOTCERT", "sslcrl": "PGSSLCRL", "sslcrldir": "PGSSLCRLDIR",
    "sslcompression": "PGSSLCOMPRESSION", "sslsni": "PGSSLSNI",
    "requirepeer": "PGREQUIREPEER", "channel_binding": "PGCHANNELBINDING",
    "target_session_attrs": "PGTARGETSESSIONATTRS", "gssencmode": "PGGSSENCMODE",
    "krbsrvname": "PGKRBSRVNAME", "gsslib": "PGGSSLIB",
}


def private_file(path: Path):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    return os.fdopen(descriptor, "w", encoding="utf-8")


def dump_postgres(module: Path, output: Path, executable: str | None) -> dict:
    import yaml
    from psycopg.conninfo import conninfo_to_dict

    config_path = Path(os.environ.get("HOK_CONFIG_FILE", str(module / "apps/NBot/config.yaml")))
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    dsn = os.environ.get("HOK_DATABASE_DSN") or config["PostgreSQL"]["dsn"]
    connection = conninfo_to_dict(dsn)
    if set(connection) - PG_ENV.keys():
        raise ValueError("Unsupported PostgreSQL connection option for environment-based pg_dump")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    environment.update({PG_ENV[key]: value for key, value in connection.items()})
    environment.setdefault("PGCONNECT_TIMEOUT", "15")
    pg_dump = executable or next((
        str(path) for path in (Path("/usr/pgsql-16/bin/pg_dump"), Path("/usr/bin/pg_dump")) if path.is_file()
    ), None) or shutil.which("pg_dump")
    if not pg_dump:
        raise FileNotFoundError("pg_dump executable missing")
    path = output / "postgresql.dump"
    # Create privately before pg_dump opens the destination. Credentials only enter libpq's environment.
    with private_file(path):
        pass
    result = subprocess.run(
        [pg_dump, "--format=custom", "--no-owner", "--no-acl", "--file", str(path)],
        env=environment, capture_output=True, check=False,
    )
    if result.returncode:
        raise RuntimeError("pg_dump failed")
    return {"file": path.name, "format": "pg_dump custom", "bytes": path.stat().st_size}


def dump_redis(module: Path, output: Path) -> dict:
    import redis
    import yaml

    config = yaml.safe_load((module / "apps/NBot/config.yaml").read_text(encoding="utf-8"))["Redis"]
    if int(config.get("REDIS_DB", 0)) != 0:
        raise ValueError("Only HOK Redis DB0 is allowed")
    kwargs = {
        "host": config["REDIS_HOST"], "port": int(config["REDIS_PORT"]), "db": 0,
        "decode_responses": False, "socket_connect_timeout": 15, "socket_timeout": 30,
    }
    for config_key, argument in (("REDIS_PASSWORD", "password"), ("REDIS_USERNAME", "username"), ("REDIS_SSL", "ssl")):
        if config_key in config:
            kwargs[argument] = config[config_key]
    client = redis.Redis(**kwargs)
    path = output / "redis-db0-hok.jsonl"
    count = 0
    seen = set()
    try:
        with private_file(path) as stream:
            stream.write(json.dumps({"type": "metadata", "format_version": 1, "db": 0, "pattern": "hok:*", "created_at": datetime.now(timezone.utc).isoformat()}) + "\n")
            for key in client.scan_iter(match=b"hok:*", count=500):
                if key in seen:
                    continue
                seen.add(key)
                with client.pipeline(transaction=True) as pipeline:
                    pipeline.dump(key)
                    pipeline.pttl(key)
                    pipeline.time()
                    dumped, ttl_ms, server_time = pipeline.execute()
                if dumped is None or ttl_ms == -2:
                    continue
                captured_at_ms = server_time[0] * 1000 + server_time[1] // 1000
                record = {
                    "type": "key", "key_b64": base64.b64encode(key).decode("ascii"),
                    "dump_b64": base64.b64encode(dumped).decode("ascii"),
                    "ttl_ms": ttl_ms, "captured_at_ms": captured_at_ms,
                    "expires_at_ms": captured_at_ms + ttl_ms if ttl_ms >= 0 else None,
                }
                stream.write(json.dumps(record, separators=(",", ":")) + "\n")
                count += 1
            stream.write(json.dumps({"type": "summary", "key_count": count}) + "\n")
    finally:
        client.close()
    return {"file": path.name, "db": 0, "pattern": "hok:*", "key_count": count}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--pg-dump")
    args = parser.parse_args()
    stage = "initialize private snapshot directory"
    try:
        args.output_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
        stage = "PostgreSQL snapshot"
        postgres = dump_postgres(args.module_dir, args.output_dir, args.pg_dump)
        stage = "Redis DB0 hok:* snapshot"
        redis = dump_redis(args.module_dir, args.output_dir)
        metadata = {"created_at": datetime.now(timezone.utc).isoformat(), "postgresql": postgres, "redis": redis, "sha256": {}}
        for path in sorted(args.output_dir.iterdir()):
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            metadata["sha256"][path.name] = digest.hexdigest()
        with private_file(args.output_dir / "snapshot.json") as stream:
            json.dump(metadata, stream, indent=2)
            stream.write("\n")
        print(json.dumps(metadata))
        return 0
    except Exception as exc:
        # Third-party exceptions may contain credentials. Log only a stable stage and exception type.
        print(f"{stage}: {type(exc).__name__}; connection details suppressed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
