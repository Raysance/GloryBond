"""Initial group-message capture before NoneBot business routing."""

import asyncio
import logging

from .zutil import log_message


async def capture_group_message(event):
    from .zfunc import record_group_chat_message

    user_id = event.get_user_id()
    msg_text = event.get_plaintext().strip()
    group_id = getattr(event, "group_id", None)
    if group_id and msg_text:
        reply_to_message_id = None
        for segment in getattr(event, "original_message", ()) or ():
            if getattr(segment, "type", None) == "reply":
                reply_to_message_id = getattr(segment, "data", {}).get("id")
                break
        try:
            await asyncio.to_thread(
                record_group_chat_message,
                group_id,
                user_id,
                msg_text,
                message_id=getattr(event, "message_id", None),
                reply_to_message_id=reply_to_message_id,
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
    from .zstatic import confs
    from .ztime import current_epoch_seconds
    from .zfunc import automation_publish_event

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
