"""Realtime battle-prediction event preparation and dispatch."""

import asyncio

from .. import zdynamic as dmc
from .. import ztime
from ..zstatic import namenick, roleidlist, userlist


async def prepare_spoiler_request(event):
    from ..zfunc import extract_name, qid2nick, wzry_get_official

    received = event.get_plaintext().replace(
        "我",
        qid2nick(event.get_user_id()),
    )
    raw_message = received.lstrip("#＃").strip()
    cache = getattr(dmc, "spoiler_cache", None)
    now = ztime.current_timestamp()

    if "的预言" in raw_message:
        realname = extract_name(received)
        if not realname:
            return {"kind": "text", "text": "没有提到玩家名字哦"}
        battle_list = await asyncio.to_thread(
            wzry_get_official,
            reqtype="btlist",
            userid=userlist[realname],
            roleid=roleidlist[realname],
        )
        gaming = battle_list.get("gaming") if battle_list.get("isGaming") else None
        if not gaming:
            display_name = namenick.get(realname, "未知玩家")
            return {
                "kind": "text",
                "text": f"【{display_name}】当前不在对局中，暂时无法预言",
            }
        cache = {
            "time": now,
            "realname": realname,
            "battleID": gaming.get("battleId"),
        }
        dmc.spoiler_cache = cache

    if not cache or now - cache["time"] > 300:
        return {"kind": "text", "text": "不存在待预言对局"}
    realname = cache["realname"]
    display_name = namenick.get(realname, "未知玩家")
    return {
        "kind": "ready",
        "status": f"正在获取【{display_name}】实时战局并计算底蕴...",
        "battle_id": cache["battleID"],
        "roleid": roleidlist.get(realname),
        "userid": userlist.get(realname),
    }


async def run_spoiler_request(prepared):
    from ..zfunc import spoiler_process

    text, image_path = await asyncio.to_thread(
        spoiler_process,
        prepared["battle_id"],
        prepared["roleid"],
        prepared["userid"],
    )
    return {"text": text, "image_path": image_path}
