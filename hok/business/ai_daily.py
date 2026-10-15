"""AI daily editorial layout and scheduled workflow, without transport or state IO."""

from ..zstatic import ai_daily_config, confs
from ..ztime import current_epoch_seconds, epoch_to_text
from ..tools.chat_text import normalize_qq_text


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


def _overview_node(date, items, limit):
    """Keep every numbered takeaway in the first node, shortening only long titles."""
    heading = f"{_text(ai_daily_config['title'])} · {date}\n\n今日要点"
    if not items:
        return heading + "\n\n本期无新增资讯。"
    prefixes = [f"\n\n{index:02d}｜" for index in range(1, len(items) + 1)]
    title_budget = (limit - len(heading) - sum(map(len, prefixes))) // len(items)
    if title_budget < 8:
        raise ValueError("AI_DAILY_LAYOUT: complete overview cannot fit in the first node")
    lines = [heading]
    for prefix, item in zip(prefixes, items):
        title = " ".join(_text(item["title"]).split())
        if len(title) > title_budget:
            title = title[:title_budget - 1] + "…"
        lines.append(prefix + title)
    return "".join(lines)


def build_daily_nodes(report):
    """Start with all takeaways; expand the same numbers with text and original links."""
    items, seen = [], set()
    for section in report["sections"]:
        for item in section["items"]:
            identity = item["links"].get("original") or item["title"]
            if identity not in seen:
                seen.add(identity)
                items.append(item)
    for item in report["flashes"]:
        identity = item["links"].get("original") or item["title"]
        if identity not in seen:
            seen.add(identity)
            items.append(item)
    limit = int(ai_daily_config["node_max_chars"])
    if limit < 200:
        raise ValueError("AI_DAILY_LAYOUT: node_max_chars must be at least 200")
    nodes = [_overview_node(report["date"], items, limit)]
    for index, item in enumerate(items, 1):
        parts = [f"{index:02d}｜{_text(item['title'])}", _text(item.get("summary")), _original_link(item)]
        block = "\n\n".join(part for part in parts if part)
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
    nodes = build_daily_nodes(report)
    queued = add_group_forward_msg(nodes, group_qid=confs["QQBot"]["group_qid"],
                                   sender_name=ai_daily_config["sender_name"], title=ai_daily_config["title"],
                                   delivery_id=delivery_id,
                                   delivery_ttl=int(ai_daily_config["delivery_ttl_seconds"]))
    return {"status": "queued" if queued else "duplicate", "date": today, "nodes": len(nodes)}
