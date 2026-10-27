"""History-export command parsing and async business dispatch."""

import asyncio
import traceback

from ..zstatic import roleidlist, userlist


def parse_export_command(raw_message):
    arguments = (
        str(raw_message or "")
        .replace("#exp", "")
        .replace("exp", "")
        .strip()
        .split()
    )
    if len(arguments) < 2:
        return None, None
    return arguments[0], arguments[1]


async def export_history_replies(raw_message):
    from ..zfunc import dump_specific_user

    realname, target_date = parse_export_command(raw_message)
    if not realname:
        return ["参数错误，格式：#exp realname date"]

    if realname.lower() == "all":
        replies = [f"开始导出所有用户数据: {target_date}"]
        inaccessible = []
        try:
            for name, userid in userlist.items():
                roleid = roleidlist.get(name)
                if roleid is None:
                    continue
                gameinfo = await asyncio.to_thread(
                    dump_specific_user,
                    userid,
                    roleid,
                    target_date,
                )
                inaccessible.extend(gameinfo.get("unaccessible_battles") or [])
        except Exception as exc:
            replies.append(f"全部导出失败: {exc}")
            return replies
        if inaccessible:
            replies.append(f"全部导出battle失败: {inaccessible}")
        else:
            replies.append("全部导出完成")
        return replies

    if realname not in userlist or realname not in roleidlist:
        return [f"未找到玩家: {realname}"]

    replies = [f"开始导出特定用户数据: {realname} {target_date}"]
    try:
        gameinfo = await asyncio.to_thread(
            dump_specific_user,
            userlist[realname],
            roleidlist[realname],
            target_date,
        )
        inaccessible = gameinfo.get("unaccessible_battles") or []
        if inaccessible:
            replies.append(f"导出battle失败: {inaccessible}")
        else:
            replies.append("导出完成")
    except Exception as exc:
        replies.append(f"导出失败: {exc}{traceback.format_exc()}")
    return replies
