#!/usr/bin/env python3
"""Backfill recent human-facing request analytics from the Nginx access log."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from request_analytics import (  # noqa: E402
    RECENT_REQUESTS_KEY,
    ROUTE_LABELS,
    cache_ip_geography,
    describe_request,
    enrich_request_event,
    sanitized_query,
    should_track_request,
)


IMPORTED_EVENT_IDS_KEY = "web:request_analytics:imported_event_ids"
NGINX_COMBINED_PATTERN = re.compile(
    r'^(?P<ip>\S+) - \S+ \[(?P<time>[^]]+)\] '
    r'"(?P<method>\S+) (?P<target>\S+) [^"]+" '
    r'(?P<status>\d{3}) \S+ "[^"]*" "(?P<user_agent>[^"]*)"'
)
CHINA_TZ = timezone(timedelta(hours=8))


def parse_nginx_line(
    line: str,
    cutoff: datetime,
    source_reference: str = "",
) -> tuple[dict, str | None] | None:
    match = NGINX_COMBINED_PATTERN.match(line)
    if not match:
        return None
    timestamp = datetime.strptime(match["time"], "%d/%b/%Y:%H:%M:%S %z")
    if timestamp < cutoff:
        return None

    method = match["method"].upper()
    target = urlsplit(match["target"])
    status = int(match["status"])
    user_agent = match["user_agent"]
    if status == 301 or not should_track_request(target.path, method, user_agent):
        return None

    params = sanitized_query(target.query)
    event = {
        "id": hashlib.sha256(
            f"{source_reference}\0{line.rstrip()}".encode("utf-8")
        ).hexdigest(),
        "timestamp": int(timestamp.timestamp()),
        "method": method,
        "path": target.path,
        "route_label": ROUTE_LABELS.get(target.path, target.path),
        "content": describe_request(target.path, params),
        "query": params,
        "status": status,
        "duration_ms": 0,
        "ip": match["ip"],
        "source": "nginx_backfill",
    }
    route_key = (parse_qs(target.query).get("key") or [None])[0]
    return event, route_key


def collect_events(log_paths: list[Path], cutoff: datetime) -> list[tuple[dict, str | None]]:
    events = []
    for log_path in log_paths:
        with log_path.open("r", encoding="utf-8", errors="replace") as log_file:
            for line_number, line in enumerate(log_file, start=1):
                parsed = parse_nginx_line(
                    line,
                    cutoff,
                    source_reference=f"{log_path.resolve()}:{line_number}",
                )
                if parsed:
                    events.append(parsed)
    events.sort(key=lambda item: (item[0]["timestamp"], item[0]["id"]))
    return events


def connect_redis():
    from dotenv import load_dotenv
    import redis

    load_dotenv("/QQBot/.env")
    redis_path = os.environ.get("REDIS_CONF")
    if not redis_path:
        raise RuntimeError("REDIS_CONF is unavailable")
    with open(redis_path, "r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    return redis.Redis(
        host=config["REDIS_HOST"],
        port=config["REDIS_PORT"],
        db=config["REDIS_DB"],
    )


def import_events(redis_client, events: list[tuple[dict, str | None]], resolve_geo: bool) -> dict:
    max_events = max(100, int(os.environ.get("REQUEST_ANALYTICS_MAX_EVENTS", "1000")))
    imported = 0
    duplicate = 0
    imported_ips = set()
    pipeline = redis_client.pipeline()

    for event, route_key in events:
        if not redis_client.sadd(IMPORTED_EVENT_IDS_KEY, event["id"]):
            duplicate += 1
            continue
        enrich_request_event(redis_client, event, route_key)
        pipeline.lpush(RECENT_REQUESTS_KEY, json.dumps(event, ensure_ascii=False))
        imported += 1
        if event.get("ip"):
            imported_ips.add(event["ip"])

    if imported:
        pipeline.ltrim(RECENT_REQUESTS_KEY, 0, max_events - 1)
        pipeline.execute()
    redis_client.expire(IMPORTED_EVENT_IDS_KEY, 60 * 60 * 24 * 30)

    if resolve_geo and imported_ips:
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda ip: cache_ip_geography(redis_client, ip), sorted(imported_ips)))

    return {
        "matched": len(events),
        "imported": imported,
        "duplicates": duplicate,
        "unique_imported_ips": len(imported_ips),
        "geo_resolution_requested": bool(resolve_geo),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", action="append", required=True, help="Nginx access log path")
    parser.add_argument("--days", type=float, default=2, help="Rolling lookback window in days")
    parser.add_argument("--dry-run", action="store_true", help="Parse only; do not write Redis")
    parser.add_argument("--skip-geo", action="store_true", help="Do not populate IP geography cache")
    args = parser.parse_args()

    cutoff = datetime.now(CHINA_TZ) - timedelta(days=max(args.days, 0))
    log_paths = [Path(path) for path in args.log]
    events = collect_events(log_paths, cutoff)
    summary = {
        "cutoff": cutoff.isoformat(),
        "matched": len(events),
        "unique_ips": len({event["ip"] for event, _ in events if event.get("ip")}),
        "first": datetime.fromtimestamp(events[0][0]["timestamp"], CHINA_TZ).isoformat() if events else None,
        "last": datetime.fromtimestamp(events[-1][0]["timestamp"], CHINA_TZ).isoformat() if events else None,
    }
    if args.dry_run:
        print(json.dumps(summary, ensure_ascii=False))
        return 0

    redis_client = connect_redis()
    result = import_events(redis_client, events, resolve_geo=not args.skip_geo)
    print(json.dumps({**summary, **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
