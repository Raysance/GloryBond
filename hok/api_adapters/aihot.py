"""Anonymous, bounded read-only access to AIHOT's stable daily-report API."""

import json
import re

import requests

from ..zstatic import ai_daily_config
from ..ztime import parse_chat_time_bound


def _validate_report(payload):
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise ValueError("AIHOT_DAILY_SCHEMA: unsupported response version")
    report = payload.get("report")
    if not isinstance(report, dict) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(report.get("date", ""))):
        raise ValueError("AIHOT_DAILY_SCHEMA: missing report date")
    for key in ("generatedAt", "windowStart", "windowEnd"):
        if not report.get(key) or parse_chat_time_bound(report[key]) is None:
            raise ValueError(f"AIHOT_DAILY_SCHEMA: invalid {key}")
    if parse_chat_time_bound(report["windowStart"]) >= parse_chat_time_bound(report["windowEnd"]):
        raise ValueError("AIHOT_DAILY_SCHEMA: invalid reporting window")
    if not isinstance(report.get("links"), dict) or not report["links"].get("aihot"):
        raise ValueError("AIHOT_DAILY_SCHEMA: missing report link")
    lead = report.get("lead")
    if lead is not None and (not isinstance(lead, dict) or not all(
            isinstance(lead.get(key), str) for key in ("title", "leadParagraph"))):
        raise ValueError("AIHOT_DAILY_SCHEMA: invalid lead")
    if not all(isinstance(report.get(key), list) for key in ("sections", "flashes")):
        raise ValueError("AIHOT_DAILY_SCHEMA: missing sections/flashes")
    items = list(report["flashes"])
    for section in report["sections"]:
        if not isinstance(section, dict) or not isinstance(section.get("label"), str) or not isinstance(section.get("items"), list):
            raise ValueError("AIHOT_DAILY_SCHEMA: invalid section")
        for item in section["items"]:
            if not isinstance(item, dict) or not isinstance(item.get("summary"), str):
                raise ValueError("AIHOT_DAILY_SCHEMA: missing item summary")
        items.extend(section["items"])
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("title"), str) or not item["title"].strip():
            raise ValueError("AIHOT_DAILY_SCHEMA: invalid item title")
        if not isinstance(item.get("source"), dict) or not isinstance(item["source"].get("name"), str):
            raise ValueError("AIHOT_DAILY_SCHEMA: invalid item source")
        if not isinstance(item.get("links"), dict) or not item["links"].get("original"):
            raise ValueError("AIHOT_DAILY_SCHEMA: missing item original link")
    return report


def aihot_latest_daily():
    """Fetch once per scheduled run; never retry 429/503 ahead of Retry-After."""
    url = str(ai_daily_config["api_base_url"]).rstrip("/") + "/dailies/latest"
    budget = int(ai_daily_config["max_response_bytes"])
    with requests.Session() as session:
        session.trust_env = False
        with session.get(url, headers={"Accept": "application/json", "User-Agent": "HOK-QQBot/AI-Daily"},
                         timeout=float(ai_daily_config["timeout_seconds"]), stream=True,
                         allow_redirects=False) as response:
            if response.status_code != 200:
                retry_after = str(response.headers.get("Retry-After", ""))[:80]
                raise RuntimeError(f"AIHOT_DAILY_HTTP: status={response.status_code} retry_after={retry_after!r}")
            content = bytearray()
            for chunk in response.iter_content(chunk_size=16384):
                content.extend(chunk)
                if len(content) > budget:
                    raise ValueError("AIHOT_DAILY_SIZE: response exceeds byte budget")
    return _validate_report(json.loads(content))
