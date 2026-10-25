"""Hero-query parsing and business dispatch for event handlers."""

import asyncio


async def honor_power_reply(event):
    from ..zfunc import honor_power_query_process, qid2realname

    realname = qid2realname(event.get_user_id())
    reply = await asyncio.to_thread(
        honor_power_query_process,
        realname,
        event.get_plaintext(),
    )
    return realname, reply


async def hero_statistics_reply(event, *, as_report=False):
    from ..zfunc import (
        extract_heroname,
        extract_name,
        mult_player_mult_hero_process,
        mult_player_single_hero_process,
        qid2nick,
        single_player_mult_hero_process,
        single_player_single_hero_process,
    )

    raw_message = event.get_plaintext().replace("我", qid2nick(event.get_user_id()))
    this_season = "本赛季" in raw_message
    message = raw_message.replace("本赛季", "").lstrip("#＃").strip()
    player_text, hero_text = message.split("的", 1)
    player_plural = "群u" in player_text
    hero_plural = "英雄" in hero_text
    matching_name = None if player_plural else extract_name(player_text, precise=True)
    if hero_plural:
        hero_id = hero_name = None
    else:
        hero_id, hero_name = extract_heroname(hero_text, precise=True)

    try:
        if not player_plural and not hero_plural:
            return await asyncio.to_thread(
                single_player_single_hero_process,
                matching_name,
                hero_id,
                hero_name,
            )
        if not player_plural and hero_plural:
            options = {"this_season": this_season}
            if as_report:
                options["as_report"] = True
            return await asyncio.to_thread(
                single_player_mult_hero_process,
                matching_name,
                **options,
            )
        if player_plural and not hero_plural:
            return await asyncio.to_thread(
                mult_player_single_hero_process,
                hero_id,
                hero_name,
                this_season=this_season,
            )
        return await asyncio.to_thread(
            mult_player_mult_hero_process,
            this_season=this_season,
        )
    except Exception as error:
        return str(error)
