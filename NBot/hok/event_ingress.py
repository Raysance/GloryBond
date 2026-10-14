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
