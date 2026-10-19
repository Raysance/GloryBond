from ..zstatic import REDIS_KEY_MESSAGE_OUTBOUND_QUEUE, confs
from ..zutil import re, log_message
from .. import zdynamic as dmc
import nonebot
import asyncio
import time
import json
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from nonebot.adapters.onebot.v11.exception import ActionFailed

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



async def _handle_forward_msg(bot, payload):
    from ..zfunc import finish_forward_delivery
    from ..zutil import log_message

    delivery_id = payload.get("delivery_id")
    status = "sent"
    try:
        card_options = {}
        if payload.get("title"):
            card_options = {"source": payload["title"], "prompt": payload["title"]}
        target = _normalize_target_id(payload["toid"])
        if payload.get("type", "group") == "private":
            result = await bot.send_private_forward_msg(user_id=target, messages=payload["messages"], **card_options)
        else:
            result = await bot.send_group_forward_msg(group_id=target, messages=payload["messages"], **card_options)
        if not isinstance(result, dict) or not result.get("message_id"):
            raise RuntimeError("FORWARD_RESULT: missing message_id; delivery outcome unknown")
    except Exception as error:
        status = "failed"
        log_message(f"FORWARD_FAILED: type={payload.get('type', 'group')} target={payload.get('toid')} delivery={delivery_id} error={error!r}")
        try:
            add_msg(f"FORWARD_FAILED: type={payload.get('type', 'group')} target={payload.get('toid')} delivery={delivery_id} "
                    f"error={error!r}；未确认发送成功，请检查机器人日志。",
                    msg_type="private", to_id=confs["QQBot"]["super_qid"])
        except Exception as notice_error:
            log_message(f"FORWARD_NOTICE_FAILED: delivery={delivery_id} error={notice_error!r}")
    if delivery_id:
        try:
            finish_forward_delivery(delivery_id, status)
        except Exception as error:
            # The QQ call may already have succeeded. Never enqueue the report again here.
            log_message(f"FORWARD_STATE_FAILED: delivery={delivery_id} status={status} error={error!r}")


async def _send_queued_message(bot, payload):
    msg_type, to_id = payload.get("type"), payload.get("toid")
    message = Message(payload.get("content", ""))
    if msg_type == "group":
        result = await bot.send_group_msg(group_id=_normalize_target_id(to_id), message=message)
        if payload.get("task_id"):
            try:
                from ..zfunc import agent_record_task_message
                saved = await asyncio.to_thread(agent_record_task_message, group_id=to_id,
                    message_id=result.get("message_id") if isinstance(result, dict) else None,
                    task_id=payload["task_id"])
                if not saved:
                    raise RuntimeError("Task receipt association was not saved")
            except Exception as exc:
                log_message(f"TASK_MESSAGE_RECEIPT_SAVE_FAILED: task_id={payload['task_id']} error={type(exc).__name__}")
        return result
    if msg_type == "private":
        return await bot.send_private_msg(user_id=_normalize_target_id(to_id), message=message)


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
        try:
            msg_json = json.loads(result)
            if msg_json.get("kind") == "group_ban":
                await _handle_group_ban(bot, msg_json)
            elif msg_json.get("kind") == "group_poke":
                await _handle_group_poke(bot, msg_json)
            elif msg_json.get("kind") in {"group_forward", "private_forward"}:
                await _handle_forward_msg(bot, msg_json)
            else:
                await _send_queued_message(bot, msg_json)
        except Exception as exc:
            # A timeout can follow a successful QQ send. Do not replay it or
            # enqueue an error notice through the same failing connection.
            log_message(f"MESSAGE_SEND_FAILED: error={type(exc).__name__}; delivery unconfirmed; not retried")
        finally:
            dmc.last_msg_send_ts = time.time()



def add_msg(content, *, event=None, msg_type=None, to_id=None, task_id=None):
    resolved_type, resolved_id = _resolve_destination(event=event, msg_type=msg_type, to_id=to_id)
    resolved_id = _normalize_target_id(resolved_id)
    if resolved_type not in {"group", "private"} or resolved_id is None:
        raise ValueError("Invalid message target")
    payload = {
        "type": resolved_type,
        "toid": resolved_id,
        "content": _stringify_message_content(content),
    }
    if task_id is not None and resolved_type == "group":
        if not isinstance(task_id, str) or not re.fullmatch(r"[a-f0-9]{32}", task_id):
            raise ValueError("Invalid trusted task ID")
        payload["task_id"] = task_id
    return _enqueue_payload(payload)


class PrivateMessageOutcomeUnknown(RuntimeError):
    """A submitted private send must not be replayed without a receipt."""

    def __init__(self, message):
        super().__init__(message)
        self.error_details = {"phase": "qq_private_send", "error_type": type(self).__name__,
                              "outcome_unknown": True, "retryable": False}


async def send_group_member_private_message(*, group_id, user_id, text):
    """Send literal private text and await QQ's receipt through the common outlet."""
    from .qq_profiles import load_group_member_profile

    group, user = str(group_id), str(user_id)
    if any(type(value) not in (str, int) or not str(value).isascii() or not str(value).isdecimal()
           or not 0 < int(value) < 10 ** 20 for value in (group_id, user_id)):
        raise ValueError("私发消息的群号和QQ无效")
    limits = confs.get("QQAgent", {}).get("private_messages", {})
    if not limits.get("enabled", True):
        raise PermissionError("群成员私发功能已关闭")
    if not isinstance(text, str) or not text.strip() or "\x00" in text or len(text) > int(limits.get("max_chars", 4000)):
        raise ValueError("私发正文为空、无效或超过配置上限")
    bot_id = str(confs["QQBot"]["bot_qid"])
    if user == bot_id:
        raise ValueError("不能私发给机器人自身")
    bot = nonebot.get_bot(bot_id)
    if str(bot.self_id) != bot_id:
        raise ValueError("私发账号与配置机器人不一致")
    # Recheck at the send boundary; group_id supplies NapCat's temporary-session context.
    member = await load_group_member_profile(group, user)
    if str(member.get("group_id")) != group or str(member.get("user_id")) != user:
        raise ValueError("未确认私发对象的群成员身份")
    try:
        result = await bot.send_private_msg(user_id=int(user), group_id=int(group),
            message=Message(MessageSegment.text(text)), auto_escape=True)
    except ActionFailed:
        raise
    except asyncio.CancelledError:
        raise
    except Exception as error:
        raise PrivateMessageOutcomeUnknown("QQ私发响应丢失，结果未知，禁止自动重发") from error
    message_id = result.get("message_id") if isinstance(result, dict) else None
    try:
        receipt = int(message_id) if type(message_id) in (str, int) else 0
    except ValueError:
        receipt = 0
    if not receipt:
        raise PrivateMessageOutcomeUnknown("QQ未返回有效私发消息ID，结果未知，禁止自动重发")
    return {"message_id": str(receipt)}


def _forward_nodes(text_nodes, sender_name):
    if not text_nodes or any(not isinstance(text, str) or not text.strip() for text in text_nodes):
        raise ValueError("Forward requires non-empty text nodes")
    return [{"type": "node", "data": {
        "name": str(sender_name), "uin": str(confs["QQBot"]["bot_qid"]),
        "content": [{"type": "text", "data": {"text": text}}],
    }} for text in text_nodes]


def add_forward_msg(text_nodes, *, event, sender_name="机器人", title=None):
    """Queue native chat records back to the command's group or private sender."""
    msg_type, target = _resolve_destination(event=event)
    target = _normalize_target_id(target)
    if msg_type == "group":
        return add_group_forward_msg(text_nodes, group_qid=target, sender_name=sender_name, title=title)
    if msg_type != "private" or type(target) is not int or target <= 0:
        raise ValueError("Invalid private forward target")
    payload = {"kind": "private_forward", "type": "private", "toid": target,
               "messages": _forward_nodes(text_nodes, sender_name)}
    if title is not None:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Forward title must be non-empty text")
        payload["title"] = title.strip()
    return _enqueue_payload(payload)


def add_group_forward_msg(text_nodes, *, group_qid=None, sender_name="机器人", title=None, delivery_id=None, delivery_ttl=604800):
    """Queue one native merged-forward message; external content stays literal text."""
    group_id = _normalize_target_id(group_qid or confs["QQBot"]["group_qid"])
    if type(group_id) is not int or group_id <= 0:
        raise ValueError("Invalid group forward target")
    messages = _forward_nodes(text_nodes, sender_name)
    payload = {"kind": "group_forward", "type": "group", "toid": group_id, "messages": messages}
    if title is not None:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Group forward title must be non-empty text")
        payload["title"] = title.strip()
    if delivery_id:
        from ..zfunc import enqueue_forward_message
        payload["delivery_id"] = delivery_id
        return enqueue_forward_message(payload, delivery_id=delivery_id, ttl=delivery_ttl)
    return _enqueue_payload(payload)


def add_text_image_msg(text, image_path, *, event=None, msg_type=None, to_id=None):
    message = MessageSegment.text(str(text)) + MessageSegment.image(
        f"file:///{image_path}"
    )
    return add_msg(message, event=event, msg_type=msg_type, to_id=to_id)


def add_chat_result_msg(result, *, event=None, destination=None, task_id=None):
    """Queue an AI reply with a native mention validated by the QQ adapter."""
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
        if mention_id != "all":
            mention_id = _normalize_target_id(mention_id)
            if type(mention_id) is not int or mention_id <= 0:
                raise ValueError("Invalid trusted QQ mention target")
        message += MessageSegment.at(str(mention_id))
        message += MessageSegment.text(" ")
    message += MessageSegment.text(str(result["text"]))
    for artifact in result.get("artifacts", []):
        message += MessageSegment.image(artifact["path"])
    if confs.get("QQAgent", {}).get("show_trace_link", False):
        if result.get("trace_url"):
            message += MessageSegment.text("\n\n运行记录：" + result["trace_url"])
        elif result.get("trace_error"):
            message += MessageSegment.text("\n\n运行记录链接暂不可用（" + result["trace_error"] + "）")
    if destination is not None:
        return add_msg(message, msg_type=destination["channel"], to_id=destination["recipient_id"], task_id=task_id)
    return add_msg(message, event=event, task_id=task_id)


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
