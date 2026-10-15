"""AI daily editorial layout and scheduled workflow, without transport or state IO."""

from ..zstatic import ai_daily_config, confs
from ..ztime import current_epoch_seconds, epoch_to_text
from ..tools.chat_text import normalize_qq_text
from ..zutil import json


def _text(value):
    return normalize_qq_text(str(value or "")).strip()


def _original_link(item):
    url = str((item.get("links") or {}).get("original") or "").strip()
    if url.startswith(("https://", "http://")) and not any(char.isspace() for char in url):
        return f"原文：{url}"
    return ""


def _split_node(text, limit):
    """Keep paragraphs together where possible, preserving all text on overflow."""
    while len(text) > limit:
        split_at = text.rfind("\n", 0, limit + 1)
        if split_at < limit // 2:
            split_at = limit
        yield text[:split_at]
        text = text[split_at:].lstrip("\n")
    if text:
        yield text


def _overview_node(date, takeaways, limit, *, has_news):
    """Summarize the application section in one node; never fill it with specialist news."""
    heading = (f"{_text(ai_daily_config['title'])} · {date}\n\n今日看点\n"
               + _text(ai_daily_config["overview_description"]))
    if not takeaways:
        return heading + ("\n\n今天暂无新的应用动态。" if has_news else "\n\n本期无新增资讯。")
    prefixes = [f"\n\n{index:02d}｜" for index in range(1, len(takeaways) + 1)]
    title_budget = (limit - len(heading) - sum(map(len, prefixes))) // len(takeaways)
    if title_budget < 8:
        raise ValueError("AI_DAILY_LAYOUT: complete overview cannot fit in the first node")
    lines = [heading]
    for prefix, takeaway in zip(prefixes, takeaways):
        title = (" ".join(_text(takeaway["headline"]).split()) + "\n"
                 + " ".join(_text(takeaway["takeaway"]).split()))
        if len(title) > title_budget:
            title = title[:title_budget - 1] + "…"
        lines.append(prefix + title)
    return "".join(lines)


def _daily_items(report):
    """Give every unique source article one stable editorial ID."""
    items, seen = [], set()
    for section in report["sections"]:
        for item in section["items"]:
            identity = item["links"].get("original") or item["title"]
            if identity not in seen:
                seen.add(identity)
                items.append({**item, "_section": section["label"]})
    for item in report["flashes"]:
        identity = item["links"].get("original") or item["title"]
        if identity not in seen:
            seen.add(identity)
            items.append({**item, "_section": "快讯"})
    return items


def _request_editorial(items):
    from .. import zapi
    from .ai_prompts import ai_daily_editorial_prompt

    if not items:
        return {"items": []}
    messages = ai_daily_editorial_prompt(items)
    budget = int(ai_daily_config["editorial_max_input_chars"])
    if len(messages[1]["content"]) > budget:
        raise ValueError("AI_DAILY_EDITORIAL: input exceeds configured budget")
    response = zapi.ai_api(messages, temperature=0.1, timeout=ai_daily_config["editorial_timeout_seconds"],
                           thinking=ai_daily_config["editorial_thinking"], response_format={"type": "json_object"})
    if not isinstance(response, str) or len(response) > budget:
        raise ValueError("AI_DAILY_EDITORIAL: invalid response size")
    try:
        return json.loads(response)
    except ValueError as error:
        raise ValueError("AI_DAILY_EDITORIAL: invalid JSON response") from error


def _split_audiences(items, editorial):
    """Bind decisions to source IDs; preserve all originals and gate overview topics."""
    rows = editorial.get("items") if isinstance(editorial, dict) else None
    if not isinstance(rows, list):
        raise ValueError("AI_DAILY_EDITORIAL: missing item decisions")
    daily, professional, seen = [], [], set()
    topics = {"application", "models", "engineering", "research", "legal", "finance", "industry"}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("AI_DAILY_EDITORIAL: invalid item decision")
        identity = row.get("id")
        if type(identity) is not int or not 1 <= identity <= len(items) or identity in seen:
            raise ValueError("AI_DAILY_EDITORIAL: unknown or repeated source ID")
        if not isinstance(row.get("section"), str) or not isinstance(row.get("topic"), str) or \
                row["section"] not in {"daily", "professional"} or row["topic"] not in topics:
            raise ValueError("AI_DAILY_EDITORIAL: invalid section or topic")
        seen.add(identity)
        item = items[identity - 1]
        if row["section"] == "daily" and row["topic"] == "application":
            headline = row.get("headline")
            takeaway = row.get("takeaway")
            if not isinstance(headline, str) or not _text(headline) or \
                    not isinstance(takeaway, str) or not _text(takeaway):
                raise ValueError("AI_DAILY_EDITORIAL: missing application headline or takeaway")
            daily.append((item, {"headline": _text(headline), "takeaway": _text(takeaway)}))
        else:
            professional.append(item)
    if len(seen) != len(items):
        raise ValueError("AI_DAILY_EDITORIAL: incomplete source coverage")
    return daily, professional


def build_daily_nodes(report, *, editorial):
    """Present application takeaways and details first, then specialist coverage."""
    items = _daily_items(report)
    daily, professional = _split_audiences(items, editorial)
    limit = int(ai_daily_config["node_max_chars"])
    if limit < 200:
        raise ValueError("AI_DAILY_LAYOUT: node_max_chars must be at least 200")
    nodes = [_overview_node(report["date"], [takeaway for _, takeaway in daily], limit, has_news=bool(items))]
    ordered = [item for item, _ in daily] + professional
    for index, item in enumerate(ordered, 1):
        parts = [f"{index:02d}｜{_text(item['title'])}", _text(item.get("summary")), _original_link(item)]
        block = "\n\n".join(part for part in parts if part)
        if index == len(daily) + 1:
            block = (_text(ai_daily_config["section_divider"]) + "\n\n前沿观察\n"
                     + _text(ai_daily_config["professional_description"]) + "\n\n" + block)
        nodes.extend(_split_node(block, limit))
    if len(nodes) > int(ai_daily_config["max_nodes"]):
        raise ValueError(f"AI_DAILY_LAYOUT: {len(nodes)} nodes exceed configured limit")
    return nodes


def ai_daily_check_and_push():
    from .. import zapi, zfunc
    from ..utils.message_sender import add_group_forward_msg

    if not ai_daily_config.get("enabled", False):
        return {"status": "disabled"}
    today = epoch_to_text(current_epoch_seconds(), "%Y-%m-%d", timezone_name=ai_daily_config["timezone"])
    delivery_id = f"ai_daily:{confs['QQBot']['group_qid']}:{today}"
    if zfunc.forward_delivery_status(delivery_id):
        return {"status": "duplicate", "date": today}
    report = zapi.aihot_latest_daily()
    if report["date"] != today:
        raise ValueError(f"AI_DAILY_STALE: expected={today} received={report['date']}")
    editorial = _request_editorial(_daily_items(report))
    nodes = build_daily_nodes(report, editorial=editorial)
    queued = add_group_forward_msg(nodes, group_qid=confs["QQBot"]["group_qid"],
                                   sender_name=ai_daily_config["sender_name"], title=ai_daily_config["title"],
                                   delivery_id=delivery_id,
                                   delivery_ttl=int(ai_daily_config["delivery_ttl_seconds"]))
    return {"status": "queued" if queued else "duplicate", "date": today, "nodes": len(nodes)}
