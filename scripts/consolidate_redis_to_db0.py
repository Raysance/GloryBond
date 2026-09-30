#!/usr/bin/env python3
"""Consolidate all HOK Redis data into DB0 under the ``hok:`` namespace.

The command defaults to a dry run. ``--apply`` creates a mode-0600 Redis DUMP
backup of every source key before moving or merging data. DB9 (Planit) is never
inspected or modified.
"""

import argparse
import base64
import datetime
import json
import os
from pathlib import Path

import redis
import yaml
from dotenv import load_dotenv


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-dir")
    return parser.parse_args()


def decode(value):
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def client(config, db):
    return redis.Redis(host=config["REDIS_HOST"], port=config["REDIS_PORT"], db=int(db))


def discover(config):
    moves = []

    def add(db_name, source, destination, mode="value"):
        moves.append({
            "db_name": db_name,
            "source_db": int(config[db_name]),
            "source": source,
            "destination": destination,
            "mode": mode,
        })

    common = client(config, config["REDIS_DB"])
    exact_common = {
        "battle:invisible_disabled_qids": "hok:battle:invisible_disabled_qids",
        "bili:video_subscriptions": "hok:bili:subscriptions",
        "bili:video_push_lock": "hok:lock:bili:video_push",
        "kpl:push_lock": "hok:lock:kpl:push",
        "kpl:push_pending": "hok:kpl:push_pending",
        "kpl:pushed_cids": "hok:kpl:pushed_cids",
        "web:request_analytics:recent": "hok:web:analytics:recent",
        "web:request_analytics:imported_event_ids": "hok:web:analytics:imported_event_ids",
    }
    for source, destination in exact_common.items():
        if common.exists(source):
            add("REDIS_DB", source, destination)
    for raw_key in common.scan_iter("web:artifact:*"):
        source = decode(raw_key)
        add("REDIS_DB", source, f"hok:web:artifact:{source[len('web:artifact:'):]}")
    for raw_key in common.scan_iter("web:request_analytics:geo:*"):
        source = decode(raw_key)
        add("REDIS_DB", source, f"hok:web:analytics:geo:{source[len('web:request_analytics:geo:'):]}")
    for raw_key in common.scan_iter("bili:video_seen:*"):
        source = decode(raw_key)
        identity = source[len("bili:video_seen:"):]
        if identity.startswith("mid:"):
            identity = identity[len("mid:"):]
        add("REDIS_DB", source, f"hok:bili:seen:{identity}")

    mappings = [
        ("REDIS_DB_LIKED_SET", "battle:liked_ids", "hok:battle:liked_ids", "value"),
        ("REDIS_DB_SHARE_QUEUE", "queue:battle:share", "hok:queue:battle:share", "queue"),
        ("REDIS_DB_ANALYZE_QUEUE", "queue:battle:analyze", "hok:queue:battle:analyze", "queue"),
        ("REDIS_DB_MESSAGE_QUEUE", "queue:message:outbound", "hok:queue:message:outbound", "queue"),
        ("REDIS_DB_BTL_ANALYZE_EVALUATOR_POOL", "battle:evaluator:records", "hok:evaluator:battle:records", "timeline"),
        ("REDIS_DB_DIY_CODE", "diy:codes", "hok:diy:codes", "value"),
        ("REDIS_DB_DIY_CODE", "diy:summaries", "hok:diy:summaries", "value"),
    ]
    for db_name, source, destination, mode in mappings:
        if client(config, config[db_name]).exists(source):
            add(db_name, source, destination, mode)

    heroes = client(config, config["REDIS_DB_TODAY_HERO_POOL"])
    for raw_key in heroes.scan_iter("hero:today:*"):
        source = decode(raw_key)
        add("REDIS_DB_TODAY_HERO_POOL", source, f"hok:{source}")
    for raw_key in heroes.scan_iter("hero:history:*"):
        source = decode(raw_key)
        add("REDIS_DB_TODAY_HERO_POOL", source, f"hok:{source}", "timeline")

    chat = client(config, config["REDIS_DB_CHAT_MEMORY"])
    for raw_key in chat.scan_iter("chat:group_history:*"):
        source = decode(raw_key)
        suffix = source[len("chat:group_history:"):]
        add("REDIS_DB_CHAT_MEMORY", source, f"hok:chat:group:{suffix}", "timeline")
    memory_categories = {
        "active_chat": "active_chat",
        "passive_chat": "passive_chat",
        "forced_mem": "forced_mem",
        "summary_mem": "summary_mem",
        "emoji_action": "emoji:action",
        "emoji_used": "emoji:used",
    }
    for old_category, new_category in memory_categories.items():
        prefix = f"zmem:{old_category}:"
        for raw_key in chat.scan_iter(f"{prefix}*"):
            source = decode(raw_key)
            add(
                "REDIS_DB_CHAT_MEMORY",
                source,
                f"hok:memory:{new_category}:{source[len(prefix):]}",
                "timeline" if old_category in {"active_chat", "passive_chat", "forced_mem", "summary_mem"} else "value",
            )
    return moves


def backup(config, moves, backup_dir):
    records = []
    for move in moves:
        source_client = client(config, move["source_db"])
        dumped = source_client.dump(move["source"])
        if dumped is None:
            continue
        records.append({
            **move,
            "ttl_ms": source_client.pttl(move["source"]),
            "dump_base64": base64.b64encode(dumped).decode("ascii"),
        })
    directory = Path(backup_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = directory / f"hok-redis-before-db0-consolidation-{stamp}.json"
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    path.chmod(0o600)
    return path


def unify_redis_config(config_path, full_config, config, backup_dir):
    legacy_fields = [
        "REDIS_DB_LIKED_SET",
        "REDIS_DB_SHARE_QUEUE",
        "REDIS_DB_ANALYZE_QUEUE",
        "REDIS_DB_MESSAGE_QUEUE",
        "REDIS_DB_TODAY_HERO_POOL",
        "REDIS_DB_BTL_ANALYZE_EVALUATOR_POOL",
        "REDIS_DB_DIY_CODE",
        "REDIS_DB_CHAT_MEMORY",
    ]
    directory = Path(backup_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = directory / f"redis-config-before-db0-consolidation-{stamp}.json"
    backup_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    backup_path.chmod(0o600)

    updated = dict(config)
    target_db = int(config["REDIS_DB"])
    for field in legacy_fields:
        if field in updated:
            updated[field] = target_db
    config_file = Path(config_path)
    temp_file = config_file.with_name(f".{config_file.name}.tmp")
    full_config["Redis"] = updated
    temp_file.write_text(yaml.safe_dump(full_config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    temp_file.chmod(config_file.stat().st_mode & 0o777)
    os.replace(temp_file, config_file)
    return backup_path


def restore_new(destination_client, destination, dumped, ttl_ms):
    ttl_ms = 0 if ttl_ms < 0 else max(1, ttl_ms)
    destination_client.restore(destination, ttl_ms, dumped, replace=False)


def merge_existing(source_client, destination_client, move):
    source = move["source"]
    destination = move["destination"]
    source_type = decode(source_client.type(source))
    destination_type = decode(destination_client.type(destination))
    if source_type != destination_type:
        raise RuntimeError(f"type conflict for {destination}: {source_type} != {destination_type}")
    if source_type == "set":
        values = source_client.smembers(source)
        if values:
            destination_client.sadd(destination, *values)
    elif source_type == "hash":
        values = source_client.hgetall(source)
        if values:
            destination_client.hset(destination, mapping=values)
    elif source_type == "list":
        source_values = source_client.lrange(source, 0, -1)
        destination_values = destination_client.lrange(destination, 0, -1)
        values = (
            destination_values + source_values
            if move["mode"] == "queue"
            else source_values + destination_values
        )
        destination_client.delete(destination)
        if values:
            destination_client.rpush(destination, *values)
    elif source_type == "string":
        pass  # The destination was written by the new code and is newer.
    else:
        raise RuntimeError(f"unsupported merge type {source_type} for {destination}")
    source_client.delete(source)


def apply(config, moves):
    destination_client = client(config, config["REDIS_DB"])
    for move in moves:
        source_client = client(config, move["source_db"])
        source = move["source"]
        destination = move["destination"]
        if not source_client.exists(source):
            continue
        if destination_client.exists(destination):
            merge_existing(source_client, destination_client, move)
            continue
        if move["source_db"] == int(config["REDIS_DB"]):
            source_client.rename(source, destination)
            continue
        dumped = source_client.dump(source)
        ttl_ms = source_client.pttl(source)
        restore_new(destination_client, destination, dumped, ttl_ms)
        source_client.delete(source)


def main():
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    env_path = os.environ.get("HOK_ENV_FILE") or project_root / ".env"
    load_dotenv(env_path)
    config_path = os.environ.get("HOK_CONFIG_FILE") or project_root / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as config_file:
        full_config = yaml.safe_load(config_file) or {}
    config = full_config["Redis"]
    moves = discover(config)
    by_db = {}
    for move in moves:
        key = f"db{move['source_db']}->db{config['REDIS_DB']}"
        by_db[key] = by_db.get(key, 0) + 1
    print(json.dumps({"apply": args.apply, "keys": len(moves), "by_db": by_db}, ensure_ascii=False))
    if not args.apply:
        return
    backup_dir = args.backup_dir or os.environ.get("HOK_REDIS_BACKUP_DIR")
    if not backup_dir:
        backup_dir = project_root / "redis-migration-backups"
    backup_path = backup(config, moves, backup_dir)
    apply(config, moves)
    config_backup_path = unify_redis_config(config_path, full_config, config, backup_dir)
    print(json.dumps({
        "status": "complete",
        "backup": str(backup_path),
        "config_backup": str(config_backup_path),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
