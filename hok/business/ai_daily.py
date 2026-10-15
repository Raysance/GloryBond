"""AI daily editorial layout and scheduled workflow, without transport or state IO."""

from ..zstatic import ai_daily_config, confs
from ..ztime import current_epoch_seconds, epoch_to_text, parse_chat_time_bound
from ..tools.chat_text import normalize_qq_text


def _text(value):
    return normalize_qq_text(str(value or "")).strip()


def _timestamp(value):
    return epoch_to_text(parse_chat_time_bound(value), timezone_name=ai_daily_config["timezone"])


def _links(item):
    links = item.get("links") or {}
    result = []
    for key, label in (("original", "原文"), ("aihot", "AIHOT")):
        url = str(links.get(key) or "").strip()
        if url.startswith(("https://", "http://")) and not any(char.isspace() for char in url):
            result.append(f"{label}：{url}")
    return result


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


def build_daily_nodes(report):
    """Use upstream editorial order; separate overview, numbered articles and flashes."""
    sections, flashes, seen = [], [], set()
    for section in report["sections"]:
        unique = []
        for item in section["items"]:
            identity = item["links"].get("original") or item["title"]
            if identity not in seen:
                seen.add(identity)
                unique.append(item)
        if unique:
            sections.append((section["label"], unique))
    for item in report["flashes"]:
        identity = item["links"].get("original") or item["title"]
        if identity not in seen:
            seen.add(identity)
            flashes.append(item)
    total = sum(len(items) for _, items in sections)
    blocks = [f"AI 领域日报 · {report['date']}\n"
              f"统计区间：{_timestamp(report['windowStart'])} 至 {_timestamp(report['windowEnd'])}（北京时间）\n"
              f"日报生成：{_timestamp(report['generatedAt'])}\n"
              f"本期 {total} 条重点动态 · {len(flashes)} 条快讯\n"
              "阅读顺序：今日导读 → 分类动态 → 快讯 → 来源"]
    lead = report.get("lead") or {}
    if lead.get("title") or lead.get("leadParagraph"):
        blocks.append("今日导读\n" + _text(lead.get("title")) + "\n\n" + _text(lead.get("leadParagraph")))
    number = 0
    for label, items in sections:
        for index, item in enumerate(items, 1):
            number += 1
            blocks.append(f"{_text(label)} · {index}/{len(items)}\n\n"
                          f"{number:02d}｜{_text(item['title'])}\n\n"
                          f"{_text(item['summary'])}\n\n"
                          f"来源：{_text(item['source']['name'])}\n" + "\n".join(_links(item)))
    for index, item in enumerate(flashes, 1):
        published = _timestamp(item.get("publishedAt")) if item.get("publishedAt") else "未知"
        blocks.append(f"行业快讯 · {index}/{len(flashes)}\n\n"
                      f"{index:02d}｜{_text(item['title'])}\n\n"
                      f"来源：{_text(item['source']['name'])}\n发布时间：{published}（北京时间）\n"
                      + "\n".join(_links(item)))
    if not total and not flashes:
        blocks.append("本期无新增资讯，具体覆盖区间见首页。")
    blocks.append("来源与阅读说明\n\n数据来源：AIHOT\n" + "\n".join(_links(report))
                  + "\n\n按 AIHOT 日报原有分类与顺序整理。摘要为来源报道的归纳，"
                  "数字、模型能力、融资与政策等信息请结合原文核实；本日报未逐条独立核验。")
    limit = int(ai_daily_config["node_max_chars"])
    if limit < 200:
        raise ValueError("AI_DAILY_LAYOUT: node_max_chars must be at least 200")
    nodes = [part for block in blocks for part in _split_node(block, limit)]
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
                                   sender_name=ai_daily_config["sender_name"], delivery_id=delivery_id,
                                   delivery_ttl=int(ai_daily_config["delivery_ttl_seconds"]))
    return {"status": "queued" if queued else "duplicate", "date": today, "nodes": len(nodes)}
