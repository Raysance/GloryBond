"""Battle-power and game-time event parsing and dispatch."""

import asyncio


async def battle_power_reply(event):
    from ..event_rules import get_validated_name
    from ..zfunc import power_rank_process, qid2nick, recent_power_process

    message = event.get_plaintext().replace("我", qid2nick(event.get_user_id()))
    if "排行" in message or "排名" in message:
        text, image_path = await asyncio.to_thread(power_rank_process, 7)
        return {"kind": "image" if image_path else "text", "text": text, "image_path": image_path}
    realname = get_validated_name(event)
    if not realname:
        return {"kind": "text", "text": "Name Not Found"}
    text = await asyncio.to_thread(recent_power_process, realname, 7)
    return {"kind": "text", "text": text}


async def game_time_reply(event):
    from ..zfunc import (
        extract_name,
        gametime_rank_process,
        qid2nick,
        recentgames_process,
    )

    message = (
        event.get_plaintext()
        .replace("我", qid2nick(event.get_user_id()))
        .replace("的", "")
        .replace("时长", "")
    )
    if "排行" in message or "排名" in message:
        text, image_path = await asyncio.to_thread(gametime_rank_process)
        return {"kind": "image" if image_path else "text", "text": text, "image_path": image_path}
    realname = extract_name(from_text=message, precise=False)
    if not realname:
        return {"kind": "text", "text": "未识别到玩家名字"}
    text = await asyncio.to_thread(recentgames_process, realname=realname)
    return {"kind": "text", "text": text}
