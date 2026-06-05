from ..zstatic import confs
from .. import zdynamic as dmc
import nonebot
import asyncio
import time
import json
from nonebot.adapters.onebot.v11 import Message, MessageSegment

driver = nonebot.get_driver()

MESSAGE_SEND_INTERVAL = 3
MESSAGE_CHECK_INTERVAL = 0.1


@driver.on_startup
async def _start_message_sender_loop() -> None:
    asyncio.create_task(message_sender_loop())


def _stringify_message_content(content):
    if content is None:
        return ""
    if isinstance(content, Message):
        return str(content)
    if isinstance(content, MessageSegment):
        return str(Message(content))
    return str(content)


def _normalize_target_id(target):
    if target is None:
        return None
    try:
        return int(target)
    except (TypeError, ValueError):
        return target


def _resolve_destination(event=None, msg_type=None, to_id=None):
    if event is not None:
        group_id = getattr(event, "group_id", None)
        if group_id:
            return "group", group_id
        user_id = getattr(event, "user_id", None)
        if not user_id and hasattr(event, "get_user_id"):
            user_id = event.get_user_id()
        return "private", user_id
    if msg_type is None:
        msg_type = "group"
    if to_id is None:
        defaults = {
            "group": confs["QQBot"]["group_qid"],
            "private": confs["QQBot"]["super_qid"],
        }
        to_id = defaults.get(msg_type)
    return msg_type, to_id



async def message_sender_loop():
    while True:
        last_ts = getattr(dmc, "last_msg_send_ts", 0)
        if time.time() - last_ts < MESSAGE_SEND_INTERVAL:
            await asyncio.sleep(MESSAGE_CHECK_INTERVAL)
            continue
        result = dmc.MessageQueue.rpop("MessageQueue")
        if not result:
            await asyncio.sleep(MESSAGE_CHECK_INTERVAL)
            continue
        try:
            bot = nonebot.get_bot(confs["QQBot"]["bot_qid"])
        except KeyError:
            await asyncio.sleep(MESSAGE_CHECK_INTERVAL)
            dmc.MessageQueue.lpush("MessageQueue", result)
            continue
        msg_json = json.loads(result)
        msg_type = msg_json.get("type")
        to_id = msg_json.get("toid")
        msg_raw = msg_json.get("content", "")
        msg_content = Message(msg_raw)
        if msg_type == "group":
            await bot.send_group_msg(group_id=_normalize_target_id(to_id), message=msg_content)
        elif msg_type == "private":
            await bot.send_private_msg(user_id=_normalize_target_id(to_id), message=msg_content)
        dmc.last_msg_send_ts = time.time()



def add_msg(content, *, event=None, msg_type=None, to_id=None):
    resolved_type, resolved_id = _resolve_destination(event=event, msg_type=msg_type, to_id=to_id)
    resolved_id = _normalize_target_id(resolved_id)
    if resolved_type not in {"group", "private"} or resolved_id is None:
        raise ValueError("Invalid message target")
    payload = {
        "type": resolved_type,
        "toid": resolved_id,
        "content": _stringify_message_content(content),
    }
    return dmc.MessageQueue.lpush("MessageQueue", json.dumps(payload, ensure_ascii=False))
