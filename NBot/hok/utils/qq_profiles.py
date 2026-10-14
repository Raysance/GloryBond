"""Read-only QQ adapter boundary; no business decisions or message sending."""

import nonebot
from ..zstatic import confs


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
