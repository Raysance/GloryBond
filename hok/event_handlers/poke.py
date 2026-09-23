"""Group-poke decision workflow without NoneBot adapter dependencies."""

import asyncio
import random
import traceback

from .. import zdynamic as dmc


async def group_poke_reply(event):
    from ..zfile import file_exist, watch_battle_shot_path
    from ..zfunc import ai_parser, battle_power_process, qid2nick
    from ..ztime import (
        add_second,
        calc_gap,
        current_datetime_text,
        str_to_time,
        time_r,
        time_to_str,
    )

    if event.target_id != event.self_id:
        return {"kind": "none"}
    if dmc.repair:
        return {"kind": "blocked"}
    if dmc.RTMPStatus:
        captured = dmc.RTMPListener.screenshot()
        image_path = watch_battle_shot_path(dmc.RTMPPlayer)
        if captured and await asyncio.to_thread(file_exist, image_path):
            return {"kind": "image", "image_path": image_path}
        return {"kind": "text", "text": "最快10秒ob一次"}
    if dmc.LastBtlMsgStatus and calc_gap(
        time_r(), str_to_time(dmc.LastBtlMsgTime)
    ) < 600:
        dmc.LastBtlMsgStatus = False
        dmc.LastBtlMsgCoolDownTime = time_to_str(add_second(time_r(), 30))
        try:
            text, image_path, _, power_data = await asyncio.to_thread(
                battle_power_process,
                **dmc.LastBtlParams,
                roleid=dmc.LastBtlRoleId,
                spoiler_info={},
                with_ai_analysis=False,
            )
        except Exception as error:
            return {
                "kind": "error",
                "text": str(error),
                "traceback": traceback.format_exc(),
            }
        return {
            "kind": "battle",
            "text": text,
            "image_path": image_path,
            "analysis": power_data.get("aiAnalysis") if power_data else None,
            "with_ai_analysis": False,
        }
    if time_r() < str_to_time(dmc.LastBtlMsgCoolDownTime):
        return {"kind": "none"}

    user_qid = event.get_user_id()
    send_text = random.random() > -1
    if random.random() < (getattr(dmc, "EmojiImageProb", None) or 0):
        from ..tools.gen_emoji_image import generate_user_emoji_image

        try:
            meta = await asyncio.to_thread(
                generate_user_emoji_image, user_qid=user_qid
            )
        except Exception as error:
            return {
                "kind": "error",
                "text": f"emoji_gen_error: {error}",
                "traceback": traceback.format_exc(),
            }
        return {"kind": "image", "image_path": meta["image_path"]}
    if send_text:
        text = await asyncio.to_thread(
            ai_parser,
            [qid2nick(user_qid), current_datetime_text()],
            "poke",
        )
        return {"kind": "text", "text": text}

    from ..zfunc import get_emoji_url
    from ..zstatic import emoji_amount

    image_index = random.randint(1, emoji_amount + 1)
    return {"kind": "image", "image_path": get_emoji_url(image_index)}
