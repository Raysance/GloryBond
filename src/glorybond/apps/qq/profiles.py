"""QQ profile/account adapter boundary; no business decisions or message sending."""

import asyncio
import base64
import logging
import nonebot
from glorybond.config.settings import confs


MENTION_SNAPSHOT_TIMEOUT_SECONDS = 2


async def snapshot_group_mentions(group_id, user_ids):
    """Best-effort receipt-time names for native mentions, never an identity grant."""
    mentions = [{"user_id": user, "nickname": None, "group_card": None,
                 "display_name": "全体成员" if user == "all" else None}
                for user in dict.fromkeys(map(str, user_ids))]
    members = [item for item in mentions if item["user_id"] != "all"]
    if not members:
        return mentions
    logger = logging.getLogger(__name__)
    try:
        bot = nonebot.get_bot(str(confs["QQBot"]["bot_qid"]))
        semaphore = asyncio.Semaphore(4)

        async def read(item):
            try:
                async with semaphore:
                    profile = await bot.get_group_member_info(
                        group_id=int(group_id), user_id=int(item["user_id"]), no_cache=True)
                if (not isinstance(profile, dict)
                        or str(profile.get("group_id")) != str(group_id)
                        or str(profile.get("user_id")) != item["user_id"]):
                    raise ValueError("member profile identity mismatch")
                for field, source in (("nickname", "nickname"), ("group_card", "card")):
                    value = profile.get(source)
                    item[field] = (value.strip() or None) if isinstance(value, str) else None
                item["display_name"] = item["group_card"] or item["nickname"]
            except Exception as error:
                logger.warning("GROUP_MENTION_PROFILE_UNAVAILABLE: error_type=%s", type(error).__name__)

        async with asyncio.timeout(MENTION_SNAPSHOT_TIMEOUT_SECONDS):
            await asyncio.gather(*(read(item) for item in members))
    except Exception as error:
        logger.warning("GROUP_MENTION_SNAPSHOT_INCOMPLETE: error_type=%s", type(error).__name__)
    return mentions


async def service_health_status():
    """Read the bound account's real OneBot status; never send a message."""
    bot_id = str(confs["QQBot"]["bot_qid"])
    bot = nonebot.get_bot(bot_id)
    if str(bot.self_id) != bot_id:
        return "error", "QQ适配器账号与配置不一致"
    status = await bot.call_api("get_status")
    if not isinstance(status, dict):
        return "warn", "get_status 响应结构未知"
    if status.get("online") is True and status.get("good") is True:
        return "ok", "QQ 在线，OneBot get_status 正常"
    return "error", "QQ离线或 OneBot 状态异常"


async def set_bot_avatar(image_bytes):
    """Submit verified pixels to the configured bot, including remote NapCat."""
    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise ValueError("机器人头像必须提供已验证的非空图片字节")
    bot_id = str(confs["QQBot"]["bot_qid"])
    bot = nonebot.get_bot(bot_id)
    if str(bot.self_id) != bot_id:
        raise ValueError("QQ适配器账号与配置机器人不一致")
    await bot.call_api("set_qq_avatar", file="base64://" + base64.b64encode(image_bytes).decode("ascii"))
    return {"bot_id": bot_id}


async def load_group_member_profile(group_id, user_id):
    group, user = str(group_id), str(user_id)
    if any(not value.isascii() or not value.isdecimal() or int(value) <= 0 for value in (group, user)):
        raise ValueError("群号与 QQ 必须是有效的正整数")
    bot = nonebot.get_bot(str(confs["QQBot"]["bot_qid"]))
    members = await bot.get_group_member_list(group_id=int(group))
    if not isinstance(members, list) or not any(
        isinstance(member, dict) and str(member.get("user_id")) == user
        and str(member.get("group_id")) == group for member in members
    ):
        raise ValueError("目标用户不是机器人可读取的该群成员")
    return await bot.get_group_member_info(group_id=int(group), user_id=int(user), no_cache=True)
