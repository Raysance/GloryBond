#!/usr/bin/env python3
"""Migrate legacy DB0 group-chat lists into PostgreSQL without deleting Redis.

The command is a dry run unless ``--apply`` is supplied.  Apply mode first
writes a mode-0600 Redis DUMP backup, creates the idempotent database schema,
upserts every valid message, and verifies source fields against PostgreSQL.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime
import json
import os
from pathlib import Path

from local_debugger import bootstrap, import_hok_module, project_root


PREFIX = "hok:chat:group:"


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Back up Redis, upsert and verify PostgreSQL.")
    parser.add_argument("--backup-dir", help="Private Redis DUMP backup directory.")
    return parser


def decode(value):
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def source_timestamp(item):
    """Validate and normalize the two timestamp formats used by legacy rows."""
    from zoneinfo import ZoneInfo

    raw_timestamp = item.get("timestamp")
    if raw_timestamp not in (None, "", 0, "0"):
        timestamp = int(raw_timestamp)
        if timestamp <= 0:
            raise ValueError("timestamp must be positive")
        datetime.fromtimestamp(timestamp, ZoneInfo("Asia/Shanghai"))
        return timestamp
    sent_at = datetime.fromisoformat(str(item.get("time") or ""))
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return int(sent_at.timestamp())


def discover(redis_client):
    records = []
    invalid = []
    keys = []
    for raw_key in redis_client.scan_iter(match=f"{PREFIX}*"):
        key = decode(raw_key)
        group_id = key[len(PREFIX):]
        if not group_id.isascii() or not group_id.isdecimal() or int(group_id) <= 0:
            continue
        keys.append(key)
        for index, raw in enumerate(redis_client.lrange(key, 0, -1)):
            try:
                item = json.loads(decode(raw))
            except (TypeError, json.JSONDecodeError):
                invalid.append({"key": key, "index": index, "reason": "invalid_json"})
                continue
            if not isinstance(item, dict):
                invalid.append({"key": key, "index": index, "reason": "not_object"})
                continue
            item = {**item, "group_id": group_id}
            if not str(item.get("message_id") or "").strip() or not str(item.get("text") or "").strip():
                invalid.append({"key": key, "index": index, "reason": "missing_required_field"})
                continue
            try:
                source_timestamp(item)
            except (OverflowError, OSError, TypeError, ValueError):
                invalid.append({"key": key, "index": index, "reason": "invalid_timestamp"})
                continue
            records.append(item)
    return sorted(keys), records, invalid


def backup_redis(redis_client, keys, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    payload = []
    for key in keys:
        dumped = redis_client.dump(key)
        if dumped is None:
            continue
        payload.append({
            "key": key,
            "ttl_ms": int(redis_client.pttl(key)),
            "dump_base64": base64.b64encode(dumped).decode("ascii"),
        })
    path = directory / f"group-chat-redis-before-postgres-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
    serialized = json.dumps(payload, ensure_ascii=False)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(serialized)
    return path


def expected_records(records):
    expected = {}
    for item in records:
        timestamp = source_timestamp(item)
        key = (str(item["group_id"]), str(item["message_id"]))
        expected[key] = {
            "user_id": str(item.get("user_id") or ""),
            "reply_to_message_id": (str(item["reply_to_message_id"])
                                    if item.get("reply_to_message_id") not in (None, "") else None),
            "timestamp": int(timestamp),
            "text": str(item.get("text") or "").strip(),
        }
    return expected


def verify(zdb, records):
    expected = expected_records(records)
    actual = {}
    for group_id in sorted({group_id for group_id, _ in expected}):
        for item in zdb.load_group_chat_messages(group_id):
            actual[(group_id, str(item["message_id"]))] = {
                "user_id": str(item.get("user_id") or ""),
                "reply_to_message_id": item.get("reply_to_message_id"),
                "timestamp": int(item.get("timestamp") or 0),
                "text": str(item.get("text") or ""),
            }
    mismatches = [key for key, value in expected.items() if actual.get(key) != value]
    return {"expected_unique": len(expected), "verified": len(expected) - len(mismatches),
            "mismatches": len(mismatches), "mismatch_preview": mismatches[:20]}


def main():
    args = build_parser().parse_args()
    bootstrap()
    zdb = import_hok_module("zdb")
    zfile = import_hok_module("zfile")
    zfunc = import_hok_module("zfunc")
    redis_client = zfunc.dmc.redis_deamon
    keys, records, invalid = discover(redis_client)
    summary = {"apply": args.apply, "keys": len(keys), "records": len(records),
               "invalid_records": len(invalid), "invalid_preview": invalid[:20]}
    print(json.dumps(summary, ensure_ascii=False))
    if not args.apply:
        return 1 if invalid else 0

    backup_dir = args.backup_dir or os.environ.get("HOK_REDIS_BACKUP_DIR")
    if not backup_dir:
        backup_dir = project_root() / "redis-migration-backups"
    backup_path = backup_redis(redis_client, keys, backup_dir)
    schema_sql = zfile.readera(str(project_root() / "database" / "schema.sql"))
    zdb.execute_schema(schema_sql)
    imported = zdb.upsert_group_chat_messages(records)
    verification = verify(zdb, records)
    result = {"status": "complete" if not invalid and not verification["mismatches"] else "incomplete",
              "backup": str(backup_path), "import": imported, "verification": verification,
              "redis_retained": True}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
