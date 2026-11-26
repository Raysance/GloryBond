"""Group-poke decision workflow without NoneBot adapter dependencies."""

import asyncio
import logging
import random
import traceback

from glorybond import runtime as dmc


async def _text_reply(event, user_qid):
    from agent_runtime import Principal
    from glorybond.features.facade import ai_parser, poke_chat_context, qid2nick
    from glorybond.time import current_epoch_seconds, epoch_to_text

    now = current_epoch_seconds()
    event_time = getattr(event, "time", None)
    boundary = min(now, int(event_time)) if isinstance(event_time, (int, float)) and event_time > 0 else now
    context_call = asyncio.wait_for(asyncio.to_thread(
        poke_chat_context, user_qid, getattr(event, "group_id", None), as_of=boundary), timeout=3)
    calls = [context_call]
    roles = getattr(getattr(dmc, "qq_agent_service", None), "roles", None)
    if roles is not None:
        calls.append(asyncio.wait_for(roles.manage(Principal(user_qid, frozenset({"roleplay.use"}))), timeout=3))
    results = await asyncio.gather(*calls, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            logging.getLogger(__name__).warning("Poke context unavailable: error_type=%s", type(result).__name__)
    messages = results[0] if isinstance(results[0], list) else []
    role = results[1] if len(results) > 1 and isinstance(results[1], dict) else None
    text = await asyncio.to_thread(ai_parser,
        [qid2nick(user_qid), epoch_to_text(boundary, timezone_name="Asia/Shanghai"), messages, role], "poke")
    return {"kind": "text", "text": text}


async def group_poke_reply(event):
    from glorybond.storage.files import file_exist, watch_battle_shot_path
    from glorybond.features.facade import battle_power_process
    from glorybond.time import add_second, calc_gap, str_to_time, time_r, time_to_str

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
                "error": error,
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
    if random.random() < getattr(dmc, "EmojiImageProb", 0.25):
        from glorybond.rendering.gen_emoji_image import EmojiTemplatesUnavailable, generate_user_emoji_image

        try:
            meta = await asyncio.to_thread(
                generate_user_emoji_image, user_qid=user_qid, group_id=getattr(event, "group_id", None)
            )
        except EmojiTemplatesUnavailable:
            logging.getLogger(__name__).warning("Poke emoji templates unavailable; using text reply", exc_info=True)
        except Exception as error:
            return {
                "kind": "error",
                "error": error,
                "text": f"emoji_gen_error: {error}",
                "traceback": traceback.format_exc(),
            }
        else:
            return {"kind": "image", "image_path": meta["image_path"]}
    try:
        return await _text_reply(event, user_qid)
    except Exception as error:
        return {"kind": "error", "error": error, "text": str(error), "traceback": traceback.format_exc()}
