"""QQ profile/account adapter boundary; no business decisions or message sending."""

import base64
import nonebot
from ..zstatic import confs


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
