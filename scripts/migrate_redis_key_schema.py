#!/usr/bin/env python3
"""Migrate HOK Redis keys to the namespaced schema.

The command is a dry run unless ``--apply`` is supplied. Before any mutation,
all source keys are serialized with Redis DUMP into a mode-0600 JSON backup.
Run this after the compatible NBot and Web code has been deployed.
"""

import argparse
import base64
import datetime
import json
import os
import re
from pathlib import Path

import redis
from dotenv import load_dotenv


WEB_ARTIFACT_PREFIX = "web:artifact:"
BATTLE_LIKED_IDS_KEY = "battle:liked_ids"
BATTLE_SHARE_QUEUE_KEY = "queue:battle:share"
BATTLE_ANALYZE_QUEUE_KEY = "queue:battle:analyze"
MESSAGE_OUTBOUND_QUEUE_KEY = "queue:message:outbound"
HERO_TODAY_PREFIX = "hero:today:"
HERO_HISTORY_PREFIX = "hero:history:"
BATTLE_EVALUATOR_RECORDS_KEY = "battle:evaluator:records"
DIY_CODES_KEY = "diy:codes"
DIY_SUMMARIES_KEY = "diy:summaries"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform the migration")
    parser.add_argument(
        "--cleanup-only",
        action="store_true",
        help="only back up and delete obsolete/malformed keys; safe before code deployment",
    )
    parser.add_argument(
        "--backup-dir",
        default="/QQBot/redis-migration-backups",
        help="directory for the pre-migration DUMP backup",
    )
    return parser.parse_args()


def decode(value):
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def redis_client(config, db):
    return redis.Redis(host=config["REDIS_HOST"], port=config["REDIS_PORT"], db=db)


def discover(config):
    sources = []

    def add(db_name, key, operation, destination=None):
        sources.append({
            "db_name": db_name,
            "db": int(config[db_name]),
            "key": key,
            "operation": operation,
            "destination": destination,
        })

    common = redis_client(config, config["REDIS_DB"])
    for raw_key in common.scan_iter("*"):
        key = decode(raw_key)
        if re.fullmatch(r"[0-9a-f]{16}", key) and common.ttl(raw_key) >= 0:
            add("REDIS_DB", key, "rename", f"{WEB_ARTIFACT_PREFIX}{key}")
        elif key.startswith("bili:video_seen:"):
            identity = key[len("bili:video_seen:"):]
            if not identity.startswith(("mid:", "name:")):
                add("REDIS_DB", key, "delete_obsolete")

    liked = redis_client(config, config["REDIS_DB_LIKED_SET"])
    for raw_key in liked.scan_iter("*"):
        key = decode(raw_key)
        if key.isdigit():
            add("REDIS_DB_LIKED_SET", key, "liked_to_set", BATTLE_LIKED_IDS_KEY)

    share = redis_client(config, config["REDIS_DB_SHARE_QUEUE"])
    if share.exists("Shared_queue"):
        add("REDIS_DB_SHARE_QUEUE", "Shared_queue", "move_queue", BATTLE_SHARE_QUEUE_KEY)
    if share.exists("Analyze_queue"):
        add("REDIS_DB_SHARE_QUEUE", "Analyze_queue", "delete_misplaced")

    analyze = redis_client(config, config["REDIS_DB_ANALYZE_QUEUE"])
    if analyze.exists("Analyze_queue"):
        add("REDIS_DB_ANALYZE_QUEUE", "Analyze_queue", "move_queue", BATTLE_ANALYZE_QUEUE_KEY)

    messages = redis_client(config, config["REDIS_DB_MESSAGE_QUEUE"])
    if messages.exists("MessageQueue"):
        add("REDIS_DB_MESSAGE_QUEUE", "MessageQueue", "move_queue", MESSAGE_OUTBOUND_QUEUE_KEY)

    heroes = redis_client(config, config["REDIS_DB_TODAY_HERO_POOL"])
    for raw_key in heroes.scan_iter("*"):
        key = decode(raw_key)
        if key.startswith("hero_history:"):
            add(
                "REDIS_DB_TODAY_HERO_POOL",
                key,
                "rename",
                f"{HERO_HISTORY_PREFIX}{key[len('hero_history:'):]}",
            )
        elif ":" not in key and heroes.type(raw_key) == b"string":
            add("REDIS_DB_TODAY_HERO_POOL", key, "rename", f"{HERO_TODAY_PREFIX}{key}")

    evaluator = redis_client(config, config["REDIS_DB_BTL_ANALYZE_EVALUATOR_POOL"])
    if evaluator.exists("records"):
        add(
            "REDIS_DB_BTL_ANALYZE_EVALUATOR_POOL",
            "records",
            "rename",
            BATTLE_EVALUATOR_RECORDS_KEY,
        )

    diy = redis_client(config, config["REDIS_DB_DIY_CODE"])
    for old_key, new_key in (("diy_codes", DIY_CODES_KEY), ("diy_summaries", DIY_SUMMARIES_KEY)):
        if diy.exists(old_key):
            add("REDIS_DB_DIY_CODE", old_key, "rename", new_key)

    chat = redis_client(config, config["REDIS_DB_CHAT_MEMORY"])
    prefix = "zmem:active_chat:"
    for raw_key in chat.scan_iter(f"{prefix}*"):
        key = decode(raw_key)
        if not key[len(prefix):].isdigit():
            add("REDIS_DB_CHAT_MEMORY", key, "delete_malformed")

    return sources


def write_backup(config, sources, backup_dir):
    records = []
    for source in sources:
        client = redis_client(config, source["db"])
        raw_key = source["key"]
        dumped = client.dump(raw_key)
        if dumped is None:
            continue
        records.append({
            **source,
            "ttl_ms": client.pttl(raw_key),
            "dump_base64": base64.b64encode(dumped).decode("ascii"),
        })
    directory = Path(backup_dir)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = directory / f"hok-redis-before-key-migration-{timestamp}.json"
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    path.chmod(0o600)
    return path


def merge_queue(client, source, destination):
    if not client.exists(destination):
        client.rename(source, destination)
        return
    values = client.lrange(source, 0, -1)
    if values:
        client.rpush(destination, *values)
    client.delete(source)


def apply_migration(config, sources):
    for source in sources:
        client = redis_client(config, source["db"])
        key = source["key"]
        if not client.exists(key):
            continue
        operation = source["operation"]
        destination = source.get("destination")
        if operation == "rename":
            if client.exists(destination):
                raise RuntimeError(f"destination already exists: db={source['db']} key={destination}")
            client.rename(key, destination)
        elif operation == "move_queue":
            merge_queue(client, key, destination)
        elif operation == "liked_to_set":
            client.sadd(destination, key)
            client.delete(key)
        elif operation.startswith("delete_"):
            client.delete(key)
        else:
            raise RuntimeError(f"unknown operation: {operation}")


def main():
    args = parse_args()
    load_dotenv("/QQBot/.env")
    config_path = os.environ.get("REDIS_CONF")
    if not config_path:
        raise RuntimeError("REDIS_CONF is not configured")
    with open(config_path, "r", encoding="utf-8") as config_file:
        config = json.load(config_file)

    sources = discover(config)
    if args.cleanup_only:
        sources = [source for source in sources if source["operation"].startswith("delete_")]
    summary = {}
    for source in sources:
        label = f"db{source['db']}:{source['operation']}"
        summary[label] = summary.get(label, 0) + 1
    print(json.dumps({
        "apply": args.apply,
        "cleanup_only": args.cleanup_only,
        "keys": len(sources),
        "summary": summary,
    }, ensure_ascii=False))
    if not args.apply:
        return
    backup_path = write_backup(config, sources, args.backup_dir)
    apply_migration(config, sources)
    print(json.dumps({"status": "complete", "backup": str(backup_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
