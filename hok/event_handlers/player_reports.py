"""Player report, ranking, view, and detail event dispatch."""

import asyncio

from .. import zdynamic as dmc
from ..zstatic import analyze_time_gap
from .. import ztime


async def online_reply():
    from ..zfunc import online_process

    result = await asyncio.to_thread(online_process)
    if isinstance(result, tuple):
        text, error_report = result
    else:
        text, error_report = result, ""
    return {"text": text, "error_report": error_report}


async def ranking_reply(event):
    from ..zfunc import generate_greeting, qid2nick, rnk_process

    dmc.rank_query_late = ztime.time_r()
    user_id = event.get_user_id()
    nickname = qid2nick(user_id)
    received = event.get_plaintext()
    ranking = await asyncio.to_thread(
        rnk_process,
        rcv_msg=received,
        caller=nickname,
        show_zero=False,
        show_analyze=True,
        debug="#" in received,
    )
    if not ranking:
        return {
            "text": "王者荣耀数据源错误，暂无可用排行数据",
            "error_report": "",
            "user_id": user_id,
            "group_id": getattr(event, "group_id", None),
        }
    return {
        "text": f"{nickname} {generate_greeting()}\n{ranking[0]}",
        "error_report": ranking[2] if len(ranking) > 2 else "",
        "user_id": user_id,
        "group_id": getattr(event, "group_id", None),
    }


async def single_summary_reply(event):
    from ..zfunc import qid2nick, single_process

    user_id = event.get_user_id()
    message = event.get_plaintext().replace("我", qid2nick(user_id))
    result = await asyncio.to_thread(single_process, message)
    if not result:
        return None
    return {
        "text": result[0],
        "battle_params": result[3],
        "battle_roleid": result[4],
        "user_id": user_id,
        "group_id": getattr(event, "group_id", None),
    }


async def single_last_battle_reply(summary):
    from ..zfunc import btldetail_process

    if not summary or not summary["battle_params"]:
        return None
    text, image_path, map_name = await asyncio.to_thread(
        btldetail_process,
        **summary["battle_params"],
        roleid=summary["battle_roleid"],
        gen_image=True,
    )
    if not text:
        return None
    return {"text": text, "image_path": image_path, "map_name": map_name}


def _view_time_gap(message):
    last_dash = message.rfind("-")
    if last_dash == -1:
        return analyze_time_gap
    digits = "".join(filter(str.isdigit, message[last_dash + 1 :]))
    return int(digits) if digits else analyze_time_gap


async def battle_view_reply(event):
    from ..zfunc import view_process

    message = event.get_plaintext()
    return await asyncio.to_thread(
        view_process,
        rcv_msg=message,
        time_gap=_view_time_gap(message),
    )


async def last_battle_detail_reply():
    from ..zfunc import btldetail_process

    params = dmc.last_request_btllist[0]["Params"]
    link, image_path, map_name = await asyncio.to_thread(btldetail_process, **params)
    return {"text": link, "image_path": image_path, "map_name": map_name}
