from ..zstatic import REDIS_KEY_MESSAGE_OUTBOUND_QUEUE, confs
from .. import zdynamic as dmc
import nonebot
import asyncio
import time
import json
from nonebot.adapters.onebot.v11 import Message, MessageSegment

driver = nonebot.get_driver()

MESSAGE_SEND_INTERVAL = 3
MESSAGE_CHECK_INTERVAL = 0.1
BATTLE_INVISIBLE_MUTE_SECONDS = 24 * 60 * 60


@driver.on_startup
async def _start_message_sender_loop() -> None:
    asyncio.create_task(message_sender_loop())
    add_msg("HOK_QQBot 已启动成功", msg_type="private", to_id=confs["QQBot"]["super_qid"])


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


def _enqueue_payload(payload):
    return dmc.MessageQueue.lpush(REDIS_KEY_MESSAGE_OUTBOUND_QUEUE, json.dumps(payload, ensure_ascii=False))


def _format_group_ban_action(duration):
    try:
        duration = int(duration)
    except (TypeError, ValueError):
        duration = 0
    return "禁言" if duration > 0 else "解禁"


async def _handle_group_ban(bot, msg_json):
    group_id = _normalize_target_id(msg_json.get("group_id") or confs["QQBot"]["group_qid"])
    user_id = _normalize_target_id(msg_json.get("user_id"))
    try:
        duration = int(msg_json.get("duration", 0))
    except (TypeError, ValueError):
        duration = 0
    source = msg_json.get("source", "")
    action = _format_group_ban_action(duration)
    if group_id is None or user_id is None:
        add_msg(
            f"GROUP_BAN_TASK_ERROR: invalid target action={action} group_id={group_id} user_id={user_id} source={source}",
            msg_type="private",
            to_id=confs["QQBot"]["super_qid"],
        )
        return
    try:
        await bot.set_group_ban(group_id=group_id, user_id=user_id, duration=duration)
    except Exception as e:
        add_msg(
            f"GROUP_BAN_TASK_FAILED: action={action} group_id={group_id} user_id={user_id} "
            f"duration={duration} source={source} error={repr(e)}",
            msg_type="private",
            to_id=confs["QQBot"]["super_qid"],
        )
        return


async def _handle_group_poke(bot, msg_json):
    group_id = _normalize_target_id(msg_json.get("group_id") or confs["QQBot"]["group_qid"])
    user_id = _normalize_target_id(msg_json.get("user_id"))
    source = msg_json.get("source", "")
    if group_id is None or user_id is None:
        add_msg(
            f"GROUP_POKE_TASK_ERROR: invalid target group_id={group_id} user_id={user_id} source={source}",
            msg_type="private",
            to_id=confs["QQBot"]["super_qid"],
        )
        return
    try:
        await bot.group_poke(group_id=group_id, user_id=user_id)
    except Exception as e:
        add_msg(
            f"GROUP_POKE_TASK_FAILED: group_id={group_id} user_id={user_id} source={source} error={repr(e)}",
            msg_type="private",
            to_id=confs["QQBot"]["super_qid"],
        )
        return



async def message_sender_loop():
    while True:
        last_ts = getattr(dmc, "last_msg_send_ts", 0)
        if time.time() - last_ts < MESSAGE_SEND_INTERVAL:
            await asyncio.sleep(MESSAGE_CHECK_INTERVAL)
            continue
        result = dmc.MessageQueue.rpop(REDIS_KEY_MESSAGE_OUTBOUND_QUEUE)
        if not result:
            await asyncio.sleep(MESSAGE_CHECK_INTERVAL)
            continue
        try:
            bot = nonebot.get_bot(confs["QQBot"]["bot_qid"])
        except KeyError:
            await asyncio.sleep(MESSAGE_CHECK_INTERVAL)
            dmc.MessageQueue.rpush(REDIS_KEY_MESSAGE_OUTBOUND_QUEUE, result)
            continue
        msg_json = json.loads(result)
        if msg_json.get("kind") == "group_ban":
            await _handle_group_ban(bot, msg_json)
            dmc.last_msg_send_ts = time.time()
            continue
        if msg_json.get("kind") == "group_poke":
            await _handle_group_poke(bot, msg_json)
            dmc.last_msg_send_ts = time.time()
            continue
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
    return _enqueue_payload(payload)


def add_text_image_msg(text, image_path, *, event=None, msg_type=None, to_id=None):
    message = MessageSegment.text(str(text)) + MessageSegment.image(
        f"file:///{image_path}"
    )
    return add_msg(message, event=event, msg_type=msg_type, to_id=to_id)


def add_chat_result_msg(result, *, event=None, destination=None):
    """Queue an AI reply with a native mention bound by the trusted QQ entry."""
    mention_id = None
    if destination is not None:
        if destination.get("platform") != "qq" or destination.get("channel") not in {"group", "private"}:
            raise ValueError("Invalid trusted QQ destination")
        if destination["channel"] == "group":
            mention_id = destination.get("mention_user_id")
    elif event is not None and getattr(event, "group_id", None):
        mention_id = getattr(event, "user_id", None)
        if mention_id is None and hasattr(event, "get_user_id"):
            mention_id = event.get_user_id()
    message = Message()
    if mention_id is not None:
        if isinstance(mention_id, bool) or not isinstance(mention_id, (str, int)):
            raise ValueError("Invalid trusted QQ mention target")
        mention_id = _normalize_target_id(mention_id)
        if type(mention_id) is not int or mention_id <= 0:
            raise ValueError("Invalid trusted QQ mention target")
        message += MessageSegment.at(str(mention_id))
        message += MessageSegment.text(" ")
    message += MessageSegment.text(str(result["text"]))
    for artifact in result.get("artifacts", []):
        message += MessageSegment.image(artifact["path"])
    if result.get("trace_url"):
        message += MessageSegment.text("\n\n运行记录：" + result["trace_url"])
    elif result.get("trace_error"):
        message += MessageSegment.text("\n\n运行记录链接暂不可用（" + result["trace_error"] + "）")
    if destination is not None:
        return add_msg(message, msg_type=destination["channel"], to_id=destination["recipient_id"])
    return add_msg(message, event=event)


def add_group_ban_task(user_qid, *, duration=BATTLE_INVISIBLE_MUTE_SECONDS, group_qid=None, source=""):
    payload = {
        "kind": "group_ban",
        "group_id": _normalize_target_id(group_qid or confs["QQBot"]["group_qid"]),
        "user_id": _normalize_target_id(user_qid),
        "duration": int(duration),
        "source": str(source),
    }
    return _enqueue_payload(payload)


def add_group_poke_task(user_qid, *, group_qid=None, source=""):
    payload = {
        "kind": "group_poke",
        "group_id": _normalize_target_id(group_qid or confs["QQBot"]["group_qid"]),
        "user_id": _normalize_target_id(user_qid),
        "source": str(source),
    }
    return _enqueue_payload(payload)
