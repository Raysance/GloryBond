"""Helpers for collecting and presenting human-facing web request analytics."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl

import requests


RECENT_REQUESTS_KEY = "web:request_analytics:recent"
WEB_ARTIFACT_PREFIX = "web:artifact:"
TRACKED_PATHS = {
    "/all",
    "/person",
    "/period",
    "/battle",
    "/query",
    "/benefit",
    "/bili-video",
    "/jump-person",
    "/jump-battle",
    "/like-battle",
    "/share-battle",
    "/analyze-battle",
}
SENSITIVE_QUERY_FIELDS = {"key", "adminkey", "password", "token", "secret"}
BOT_USER_AGENT_TOKENS = {
    "bot",
    "crawler",
    "spider",
    "slurp",
    "headless",
    "preview",
    "facebookexternalhit",
    "telegrambot",
    "whatsapp",
}
ROUTE_LABELS = {
    "/all": "全部战绩",
    "/person": "个人战绩",
    "/period": "周期战绩",
    "/battle": "对局详情",
    "/query": "战绩查询",
    "/benefit": "底蕴分析",
    "/bili-video": "B站视频",
    "/jump-person": "跳转玩家",
    "/jump-battle": "跳转对局",
    "/like-battle": "收藏对局",
    "/share-battle": "分享对局",
    "/analyze-battle": "分析对局",
}


def should_track_request(path: str, method: str, user_agent: str) -> bool:
    """Return whether a request represents a public, human-facing interaction."""
    if path not in TRACKED_PATHS or method.upper() not in {"GET", "POST"}:
        return False
    normalized_agent = (user_agent or "").strip().lower()
    if not normalized_agent:
        return False
    return not any(token in normalized_agent for token in BOT_USER_AGENT_TOKENS)


def extract_client_ip(headers, fallback_ip: str | None = None) -> str:
    """Read the original client IP supplied by the trusted reverse proxy."""
    candidates = [
        headers.get("cf-connecting-ip"),
        headers.get("x-real-ip"),
    ]
    forwarded_for = headers.get("x-forwarded-for")
    if forwarded_for:
        candidates.extend(part.strip() for part in forwarded_for.split(","))
    candidates.append(fallback_ip)
    for candidate in candidates:
        try:
            return str(ipaddress.ip_address(str(candidate).strip()))
        except ValueError:
            continue
    return ""


def sanitized_query(query_string: str) -> dict[str, list[str]]:
    """Parse query parameters while removing credentials from stored analytics."""
    params: dict[str, list[str]] = {}
    for key, value in parse_qsl(query_string, keep_blank_values=True):
        if key.lower() in SENSITIVE_QUERY_FIELDS:
            continue
        cleaned_value = value[:160]
        params.setdefault(key[:64], []).append(cleaned_value)
    return params


def describe_request(path: str, params: dict[str, list[str]]) -> str:
    label = ROUTE_LABELS.get(path, path)
    visible_parts = []
    for key, values in params.items():
        value = ", ".join(values)
        if value:
            visible_parts.append(f"{key}={value}")
    return f"{label} · {' · '.join(visible_parts)}" if visible_parts else label


def build_request_event(request, response_status: int, duration_ms: float) -> dict:
    path = request.url.path
    params = sanitized_query(request.url.query)
    fallback_ip = request.client.host if request.client else None
    return {
        "id": uuid.uuid4().hex,
        "timestamp": int(time.time()),
        "method": request.method.upper(),
        "path": path,
        "route_label": ROUTE_LABELS.get(path, path),
        "content": describe_request(path, params),
        "query": params,
        "status": int(response_status),
        "duration_ms": round(duration_ms, 1),
        "ip": extract_client_ip(request.headers, fallback_ip),
    }


def enrich_request_event(redis_client, event: dict, route_key: str | None) -> dict:
    """Add safe, human-readable context from a short-lived route payload."""
    if not route_key:
        return event
    try:
        raw_payload = (
            redis_client.get(f"{WEB_ARTIFACT_PREFIX}{route_key}")
            or redis_client.get(route_key)
        )
        if isinstance(raw_payload, bytes):
            raw_payload = raw_payload.decode("utf-8")
        payload = json.loads(raw_payload)
    except (TypeError, ValueError, UnicodeDecodeError):
        return event
    if not isinstance(payload, dict):
        return event

    details = []
    caller = payload.get("caller")
    if isinstance(caller, dict):
        caller = next(
            (caller.get(field) for field in ("PlayerName", "nickname", "name", "realname") if caller.get(field)),
            "",
        )
    if isinstance(caller, (str, int)) and str(caller).strip():
        details.append(f"发起者={str(caller).strip()[:80]}")

    for field, label in (
        ("title", "标题"),
        ("up_name", "UP主"),
        ("DateFrom", "开始"),
        ("DateTo", "结束"),
        ("time", "生成时间"),
    ):
        value = payload.get(field)
        if isinstance(value, (str, int, float)) and str(value).strip():
            details.append(f"{label}={str(value).strip()[:100]}")
    if details:
        event["content"] = f"{event.get('route_label') or event.get('path')} · {' · '.join(details)}"
    return event


def store_request_event(redis_client, event: dict) -> None:
    max_events = max(100, int(os.environ.get("REQUEST_ANALYTICS_MAX_EVENTS", "1000")))
    pipeline = redis_client.pipeline()
    pipeline.lpush(RECENT_REQUESTS_KEY, json.dumps(event, ensure_ascii=False))
    pipeline.ltrim(RECENT_REQUESTS_KEY, 0, max_events - 1)
    pipeline.execute()


def geo_cache_key(ip: str) -> str:
    return f"web:request_analytics:geo:{ip}"


def _local_geo(ip: str) -> dict | None:
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return {"status": "unknown", "label": "未知地区"}
    if parsed.is_private or parsed.is_loopback or parsed.is_link_local:
        return {
            "status": "local",
            "country": "本地网络",
            "region": "",
            "city": "",
            "latitude": None,
            "longitude": None,
            "label": "本地网络",
        }
    return None


def cache_ip_geography(redis_client, ip: str) -> None:
    """Resolve and cache one IP. Intended to run outside the response path."""
    if not ip or redis_client.get(geo_cache_key(ip)):
        return
    lock_key = f"{geo_cache_key(ip)}:lock"
    if not redis_client.set(lock_key, "1", nx=True, ex=30):
        return
    try:
        geo = _local_geo(ip)
        if geo is None:
            response = requests.get(
                f"https://ipwho.is/{ip}",
                params={"lang": "zh-CN"},
                timeout=4,
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("success", False):
                raise ValueError(payload.get("message") or "geolocation lookup failed")
            connection = payload.get("connection") or {}
            geo = {
                "status": "ok",
                "country": str(payload.get("country") or ""),
                "country_code": str(payload.get("country_code") or ""),
                "region": str(payload.get("region") or ""),
                "city": str(payload.get("city") or ""),
                "latitude": payload.get("latitude"),
                "longitude": payload.get("longitude"),
                "isp": str(connection.get("isp") or ""),
            }
            geo["label"] = " · ".join(
                part for part in (geo["country"], geo["region"], geo["city"]) if part
            ) or "未知地区"
        cache_seconds = max(3600, int(os.environ.get("REQUEST_GEO_CACHE_SECONDS", "2592000")))
        redis_client.set(geo_cache_key(ip), json.dumps(geo, ensure_ascii=False), ex=cache_seconds)
    except Exception:
        retry_seconds = max(60, int(os.environ.get("REQUEST_GEO_RETRY_SECONDS", "1800")))
        redis_client.set(
            geo_cache_key(ip),
            json.dumps({"status": "unavailable", "label": "定位暂不可用"}, ensure_ascii=False),
            ex=retry_seconds,
        )
    finally:
        redis_client.delete(lock_key)


def _decode_json(raw, default):
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError):
        return default


def _masked_ip(ip: str) -> str:
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return "未知"
    if parsed.version == 4:
        parts = ip.split(".")
        return ".".join(parts[:2] + ["*", "*"])
    return f"{':'.join(parsed.exploded.split(':')[:3])}:*"


def _visitor_id(ip: str, secret: str) -> str:
    return hashlib.sha256(f"{secret}:{ip}".encode("utf-8")).hexdigest()[:12]


def _event_time(timestamp: int) -> str:
    china_tz = timezone(timedelta(hours=8))
    return datetime.fromtimestamp(timestamp, tz=china_tz).strftime("%m-%d %H:%M:%S")


def analytics_payload(redis_client, secret: str, limit: int = 200) -> dict:
    limit = min(max(int(limit), 1), 500)
    raw_events = redis_client.lrange(RECENT_REQUESTS_KEY, 0, limit - 1)
    events = []
    locations = Counter()
    routes = Counter()
    visitors = set()
    located_count = 0

    for raw_event in raw_events:
        event = _decode_json(raw_event, {})
        if not isinstance(event, dict) or not event.get("timestamp"):
            continue
        ip = str(event.pop("ip", "") or "")
        event.pop("user_agent", None)
        event.pop("referer", None)
        geo = _decode_json(redis_client.get(geo_cache_key(ip)), {})
        location = str(geo.get("label") or "定位中")
        if geo.get("status") in {"ok", "local"}:
            located_count += 1
            locations[location] += 1
        routes[str(event.get("route_label") or event.get("path") or "未知入口")] += 1
        if ip:
            visitors.add(_visitor_id(ip, secret))
        event.update({
            "time": _event_time(int(event["timestamp"])),
            "location": location,
            "country": geo.get("country") or "",
            "region": geo.get("region") or "",
            "city": geo.get("city") or "",
            "latitude": geo.get("latitude"),
            "longitude": geo.get("longitude"),
            "masked_ip": _masked_ip(ip),
            "visitor_id": _visitor_id(ip, secret) if ip else "unknown",
        })
        events.append(event)

    total = len(events)
    distribution = [
        {"location": location, "count": count, "percent": round(count * 100 / located_count, 1)}
        for location, count in locations.most_common(12)
    ]
    route_distribution = [
        {"route": route, "count": count, "percent": round(count * 100 / total, 1) if total else 0}
        for route, count in routes.most_common(8)
    ]
    return {
        "generated_at": _event_time(int(time.time())),
        "sample_limit": limit,
        "summary": {
            "requests": total,
            "unique_visitors": len(visitors),
            "located": located_count,
            "pending": total - located_count,
        },
        "distribution": distribution,
        "route_distribution": route_distribution,
        "events": events,
    }
