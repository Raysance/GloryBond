"""Hero-profile and player-visual event dispatch."""

import asyncio


def _validated_name(event):
    from ..event_rules import get_validated_name

    return get_validated_name(event)


async def hero_power_reply(event):
    from ..zfunc import heropower_process

    realname = _validated_name(event)
    if not realname:
        return {"kind": "text", "text": "Name Not Found"}
    text = await asyncio.to_thread(heropower_process, realname)
    return {"kind": "text", "text": text}


async def today_hero_reply(event):
    from ..zfunc import qid2realname, todayhero_process

    message = event.get_plaintext()
    if "的" in message:
        return {"kind": "text", "text": "只能查询自己的今日英雄"}
    if "rrrr" in message:
        return {"kind": "text", "text": "func unavailable"}

    realname = qid2realname(event.get_user_id())
    if "~" in message:
        realname = _validated_name(event)
        if not realname:
            return {"kind": "text", "text": "Name Not Found"}
    hero_text, reason, image_path = await asyncio.to_thread(
        todayhero_process,
        realname,
        "%" in message,
        "$" not in message,
    )
    return {
        "kind": "image",
        "text": hero_text,
        "image_path": image_path,
        "suffix": reason,
    }


async def grade_analysis_reply(event):
    from ..zfunc import gradeanalyze_process

    realname = _validated_name(event)
    if not realname:
        return {"kind": "text", "text": "Name Not Found"}
    image_path, analysis = await asyncio.to_thread(gradeanalyze_process, realname)
    return {"kind": "image", "image_path": image_path, "analysis": analysis}


async def watch_battle_reply(event):
    from .. import zfile
    from ..zfunc import watchbattle_process

    realname = _validated_name(event)
    if not realname:
        return {"kind": "text", "text": "Name Not Found"}
    image_path, analysis = await asyncio.to_thread(watchbattle_process, realname)
    exists = await asyncio.to_thread(zfile.file_exist, image_path)
    return {
        "kind": "image" if exists else "none",
        "image_path": image_path,
        "analysis": analysis,
    }
