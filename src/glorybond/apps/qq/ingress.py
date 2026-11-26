"""Initial group-message capture before NoneBot business routing."""

import asyncio
import logging
import re

from glorybond.common import log_message


def _field(segment, name, default=None):
    return segment.get(name, default) if isinstance(segment, dict) else getattr(segment, name, default)


def _mention_id(segment):
    if _field(segment, "type") != "at":
        return None
    user = str(_field(segment, "data", {}).get("qq", ""))
    return user if user == "all" or re.fullmatch(r"[1-9][0-9]{0,19}", user) else None


def _archive_text(segments, mentions, fallback):
    """Keep native mention order visible to the existing text-only history readers."""
    targets = {item["user_id"]: item for item in mentions}
    parts = []
    for segment in segments:
        if _field(segment, "type") == "text":
            parts.append(str(_field(segment, "data", {}).get("text", "")))
        elif (user := _mention_id(segment)) in targets:
            name = targets[user]["display_name"]
            parts.append("@全体成员 " if user == "all" else f"@{name or user}(QQ:{user}) ")
    return "".join(parts).strip() or fallback


async def capture_group_message(event):
    from glorybond.features.facade import record_group_chat_message

    user_id = event.get_user_id()
    msg_text = event.get_plaintext().strip()
    group_id = getattr(event, "group_id", None)
    segments = getattr(event, "original_message", None)
    if segments is None:
        segments = getattr(event, "message", ())
    segments = list(segments or ())
    mentioned_users = list(dict.fromkeys(user for segment in segments if (user := _mention_id(segment))))
    if group_id and (msg_text or mentioned_users):
        reply_to_message_id = None
        for segment in segments:
            if _field(segment, "type") == "reply":
                reply_to_message_id = _field(segment, "data", {}).get("id")
                break
        try:
            metadata = {}
            archive_text = msg_text
            if mentioned_users:
                from glorybond.apps.qq.profiles import snapshot_group_mentions
                mentions = await snapshot_group_mentions(group_id, mentioned_users)
                archive_text = _archive_text(segments, mentions, msg_text)
                metadata = {"mentions": mentions, "plain_text": msg_text}
            await asyncio.to_thread(
                record_group_chat_message,
                group_id,
                user_id,
                archive_text,
                message_id=getattr(event, "message_id", None),
                reply_to_message_id=reply_to_message_id,
                **metadata,
            )
        except Exception as error:
            log_message(
                f"GROUP_CHAT_HISTORY_WRITE_ERROR: group_id={group_id} user_id={user_id} "
                f"message_id={getattr(event, 'message_id', None)} error={error!r}",
                level=logging.ERROR,
            )
    await observe_automation_message(event, user_id, group_id, msg_text)


async def observe_automation_message(event, user_id, group_id, text):
    """Observe independently of archive success; a self echo is already observed at send."""
    from glorybond.config.settings import confs
    from glorybond.time import current_epoch_seconds
    from glorybond.features.facade import automation_publish_event

    if str(user_id) == str(confs["QQBot"]["bot_qid"]):
        return
    identifier = getattr(event, "message_id", None)
    if identifier is None:
        return
    scope = "group:" + str(group_id) if group_id else "private:" + str(user_id)
    try:
        await asyncio.to_thread(automation_publish_event, {"id": f"qq:{scope}:{identifier}",
            "kind": "message.received", "scope": scope, "sender_id": str(user_id), "source": "chat",
            "text": text[:12000], "timestamp": int(getattr(event, "time", None) or current_epoch_seconds())})
    except Exception as error:
        log_message(f"AUTOMATION_INGRESS_FAILED: error_type={type(error).__name__}", level=logging.ERROR)
