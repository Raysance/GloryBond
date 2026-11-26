"""Bounded topic history for variety, never a fact source or delivery receipt."""

import json

RETENTION_SECONDS = 86400
MAX_REPLIES = 12


def _key(group_id):
    group = str(group_id)
    if not group.isascii() or not group.isdecimal() or int(group) <= 0:
        raise ValueError("Poke history requires a trusted group ID")
    return "hok:poke:generated:" + group


def recent_generated(group_id, *, as_of):
    if group_id is None:
        return []
    from glorybond import runtime

    records = []
    for raw in runtime.redis_deamon.lrange(_key(group_id), -MAX_REPLIES, -1):
        try:
            row = json.loads(raw)
            timestamp, topic = int(row["timestamp"]), row["topic"]
            if int(as_of) - RETENTION_SECONDS <= timestamp <= int(as_of) and isinstance(topic, str) and topic.strip():
                sources = row.get("source_message_ids", [])
                if not isinstance(sources, list) or any(not isinstance(mid, str) for mid in sources):
                    continue
                records.append({"timestamp": timestamp, "topic": topic[:200], "source_message_ids": sources[:8]})
        except (ValueError, TypeError, KeyError):
            continue
    return records


def record_generated(group_id, topic, *, as_of, source_message_ids=()):
    if group_id is None or not topic.strip():
        return
    from glorybond import runtime

    key = _key(group_id)
    with runtime.redis_deamon.pipeline(transaction=True) as pipe:
        pipe.rpush(key, json.dumps({"timestamp": int(as_of), "topic": topic[:200],
                                   "source_message_ids": list(source_message_ids)[:8]}, ensure_ascii=False))
        pipe.ltrim(key, -MAX_REPLIES, -1)
        pipe.expire(key, RETENTION_SECONDS)
        pipe.execute()
