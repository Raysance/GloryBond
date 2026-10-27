"""Pure routing predicates shared by NoneBot matcher declarations."""

from . import zdynamic as dmc
from .zstatic import *


def is_registered_qid(user_qid):
    return str(user_qid) in {str(item) for item in qid.values()}


def is_battle_visible_qid_enabled(user_qid):
    from .zfunc import get_battle_invisible_disabled_qids

    disabled_qids = get_battle_invisible_disabled_qids()
    return str(user_qid) not in {str(item) for item in disabled_qids}


def is_bot_request_message(event):
    raw_msg = event.get_plaintext().strip()
    return raw_msg.startswith("#") or raw_msg.startswith("＃")


async def judge_qid_blocked(event):
    if not (is_bot_request_message(event) or is_direct_bot_mention(event)):
        return False
    return (not is_registered_qid(event.get_user_id())) or (
        not is_battle_visible_qid_enabled(event.get_user_id())
    )


async def judge_to_me(event):
    return is_bot_request_message(event)


def is_direct_bot_mention(event):
    """Inspect this message's own segments, not inferred to_me or quoted content."""
    bot_id = str(getattr(event, "self_id", "") or "")
    if not bot_id:
        return False
    segments = getattr(event, "original_message", None)
    if segments is None:
        segments = getattr(event, "message", ())
    for segment in segments or ():
        kind = segment.get("type") if isinstance(segment, dict) else getattr(segment, "type", None)
        data = segment.get("data", {}) if isinstance(segment, dict) else getattr(segment, "data", {})
        if kind == "at" and str(data.get("qq", "")) == bot_id:
            return True
    return False


async def judge_direct_ai_request(event):
    return is_direct_bot_mention(event) and not is_bot_request_message(event)


async def judge_bot_addressed(event):
    return is_bot_request_message(event) or is_direct_bot_mention(event)


async def judge_x_subscription(event):
    from .event_handlers.x_subscription import parse_x_command

    command = parse_x_command(event.get_plaintext())
    return command is not None and command[0] != "admin"


async def judge_x_subscription_admin(event):
    from .event_handlers.x_subscription import parse_x_command

    command = parse_x_command(event.get_plaintext())
    return command is not None and command[0] == "admin"


def bili_video_plain_command(event):
    return event.get_plaintext().strip().lstrip("#＃").strip()


async def judge_bili_video_subscribe(event):
    if await judge_x_subscription(event):
        return False
    raw = bili_video_plain_command(event)
    if raw in {"订阅", "订阅最新视频", "订阅UP最新视频", "订阅up最新视频"}:
        return False
    return raw.startswith(("订阅B站", "订阅b站", "订阅"))


async def judge_bili_video_unsubscribe(event):
    if await judge_x_subscription(event):
        return False
    raw = bili_video_plain_command(event)
    return raw in {"取消B站订阅", "取消b站订阅", "取消订阅"} or raw.startswith(
        ("取消B站订阅", "取消b站订阅", "取消订阅")
    )


async def judge_bili_video_latest(event):
    return bili_video_plain_command(event) in {
        "最新视频",
        "查询最新视频",
        "订阅最新视频",
        "查询订阅最新视频",
        "我的最新视频",
        "我的订阅最新视频",
        "订阅UP最新视频",
        "订阅up最新视频",
    }


async def judge_bili_video_mine(event):
    return bili_video_plain_command(event) in {
        "我的订阅",
        "我的UP订阅",
        "我的up订阅",
        "我的B站订阅",
        "我的b站订阅",
        "订阅状态",
        "查询订阅",
    }


async def judge_not_duration_rank(event):
    raw = event.get_plaintext()
    return "时长排行" not in raw and "时长排名" not in raw


async def judge_representative_battle_query(event):
    return is_registered_qid(event.get_user_id()) and is_battle_visible_qid_enabled(
        event.get_user_id()
    )


async def judge_herostatistics_query(event):
    from .zfunc import extract_heroname, extract_name, qid2nick

    rcv_msg = event.get_plaintext().replace("我", qid2nick(event.get_user_id())).replace(
        "本赛季", ""
    )
    if not rcv_msg.startswith(("#", "＃")):
        return False
    raw = rcv_msg.lstrip("#＃").strip()
    if "的" not in raw:
        return False
    left, right = (part.strip() for part in raw.split("的", 1))
    if not left or not right:
        return False
    left_ok = left == "群u" or bool(extract_name(left, precise=True))
    right_ok = right == "英雄" or bool(extract_heroname(right, precise=True))
    return left_ok and right_ok


async def judge_honor_power_query(event):
    raw = event.get_plaintext()
    return (
        is_bot_request_message(event)
        and "战力" in raw
        and "查询" in raw
        and is_registered_qid(event.get_user_id())
        and is_battle_visible_qid_enabled(event.get_user_id())
    )


def get_validated_name(event):
    from .zfunc import extract_name, qid2nick

    rcv_msg = event.get_plaintext().replace("我", qid2nick(event.get_user_id()))
    return extract_name(rcv_msg)


async def judge_super(event):
    return str(confs["QQBot"]["super_qid"]) == str(event.get_user_id())


async def judge_super_command(event):
    return is_bot_request_message(event) and await judge_super(event)


async def judge_unsuper(event):
    return str(confs["QQBot"]["super_qid"]) != str(event.get_user_id())


async def check_repair(event):
    return dmc.repair


async def check_btl_request(event):
    return last_request_btllist != []


async def check_sleep(event):
    from .ztime import is_within_daily_time_window

    return is_within_daily_time_window(bound_hour, bound_minute, window_seconds=600)

async def judge_player_client(event):
    from .event_handlers.player_client import parse_client_request

    return is_bot_request_message(event) and parse_client_request(event.get_plaintext()) is not None
