
from .zutil import *
from .zstatic import *
from . import zdynamic as dmc
from .utils.message_sender import add_msg
from .utils.message_sender import add_group_poke_task
from . import zscheduler

import nonebot
import asyncio
from nonebot import require
from nonebot.rule import Rule
from nonebot.adapters.onebot.v11 import Bot, Event, Message,MessageEvent,MessageSegment
from nonebot.adapters.onebot.v11.event import PokeNotifyEvent
from nonebot.plugin import on_message,on_notice,on_keyword,on_fullmatch
require("nonebot_plugin_apscheduler")
driver = nonebot.get_driver()

_all_messages = on_message(priority=0, block=False)

from .event_ingress import capture_group_message
from .event_rules import (
    check_repair,
    check_sleep,
    get_validated_name as _get_validated_name,
    judge_bili_video_latest,
    judge_bili_video_mine,
    judge_bili_video_subscribe,
    judge_bili_video_unsubscribe,
    judge_bot_addressed,
    judge_direct_ai_request,
    judge_herostatistics_query,
    judge_honor_power_query,
    judge_not_duration_rank,
    judge_qid_blocked,
    judge_representative_battle_query,
    judge_super_command,
    judge_to_me,
    judge_unsuper,
)


def get_validated_name(event):
    matching_name = _get_validated_name(event)
    if not matching_name:
        add_msg("Name Not Found", event=event)
    return matching_name


@_all_messages.handle()
async def handle_all_messages(event: MessageEvent):
    await capture_group_message(event)

# EVENT
_group_poke = on_notice()
_qid_blocked=on_message(rule=judge_qid_blocked,priority=1, block=True)
_repair=on_fullmatch("##r",rule=judge_super_command,priority=1, block=True)
_execute=on_keyword({"##e"},rule=judge_super_command,priority=1, block=True)
_test=on_keyword({"##t"},rule=judge_super_command,priority=1, block=True)
_update_local=on_keyword({"##u"},rule=judge_super_command,priority=1, block=True)
_forward=on_keyword({"##f"},rule=judge_super_command,priority=1, block=True)
_dailyrepbattle=on_keyword({"##srep"},rule=judge_super_command,priority=1, block=True)
_representative_range_debug=on_keyword({"##rep3"},rule=judge_super_command,priority=1, block=True)
_pure_chat=on_keyword({"##c"},rule=judge_super_command,priority=1, block=True)
_emoji_gen = on_keyword({"##emoji"},rule=judge_super_command,priority=1, block=True)
_kpl_push = on_keyword({"##kpl"},rule=judge_super_command,priority=1, block=True)
_bili_video_admin = on_keyword({"##bili"},rule=judge_super_command,priority=1, block=True)

_sleep_blocked = on_message(rule=Rule(judge_bot_addressed,check_sleep), priority=2, block=True)
_blocked=on_message(rule=Rule(judge_bot_addressed,check_repair,judge_unsuper),priority=2, block=True)

_direct_chat=on_message(rule=judge_direct_ai_request,priority=3,block=True)

_show_code=on_fullmatch("code",rule=judge_to_me,priority=3, block=True)
_forget_me=on_fullmatch(("#清除记忆", "＃清除记忆"),rule=judge_to_me,priority=3, block=True)
_manual=on_fullmatch("#帮助",rule=judge_to_me,priority=3, block=True)
_peak_rank=on_fullmatch(
    ("#巅峰排名", "＃巅峰排名", "#巅峰排行", "＃巅峰排行"),
    rule=judge_to_me,
    priority=3,
    block=True,
)
_hero_tier=on_fullmatch(("#梯度", "＃梯度"),rule=judge_to_me,priority=3,block=True)
_honor_power_query = on_message(
    rule=judge_honor_power_query,
    priority=3,
    block=True,
)
_bili_video_latest = on_message(rule=Rule(judge_to_me, judge_bili_video_latest), priority=3, block=True)
_bili_video_mine = on_message(rule=Rule(judge_to_me, judge_bili_video_mine), priority=3, block=True)
_bili_video_unsubscribe = on_message(rule=Rule(judge_to_me, judge_bili_video_unsubscribe), priority=3, block=True)
_bili_video_subscribe = on_message(rule=Rule(judge_to_me, judge_bili_video_subscribe), priority=3, block=True)
_representative_battle = on_keyword(
    set(representative_battle_keywords),
    rule=Rule(judge_to_me, judge_representative_battle_query),
    priority=3,
    block=True,
)

_atall=on_fullmatch(tuple(atall_keywords),priority=4, block=True)
_btlview=on_keyword(set(btlview_keywords),rule=judge_to_me,priority=4, block=True)
_btldetail=on_keyword(set(btldetail_keywords),rule=judge_to_me,priority=4, block=True)
_heropower=on_keyword(set(heropower_keywords),rule=judge_to_me,priority=4, block=True)
_history_query=on_keyword({"查询"},rule=judge_to_me,priority=4, block=True)
_herostatistics=on_message(rule=Rule(judge_herostatistics_query),priority=4, block=True)
_todayhero=on_keyword({"今日英雄"},rule=judge_to_me,priority=4, block=True)
_showonline=on_keyword({"在线"},rule=judge_to_me,priority=4, block=True)
_gradeanalyze=on_keyword({"分析"},rule=judge_to_me,priority=4, block=True)
_watchbattle=on_keyword({"ob"},rule=judge_to_me,priority=4, block=True)
_spoiler=on_keyword({"预言"},rule=judge_to_me,priority=4, block=True)
_recentpower=on_keyword({"底蕴"},rule=judge_to_me,priority=4, block=True)
_recentgames = on_keyword({"时长"}, rule=judge_to_me, priority=4, block=True)
_diycode = on_keyword({"diy"},rule=judge_to_me,priority=4, block=True)
_exporthistory = on_keyword({"exp"},rule=judge_to_me,priority=4, block=True)
_emoji_gen = on_keyword({"emoji"},rule=judge_to_me,priority=4, block=True)

_rnk=on_keyword(set(rnk_keywords),rule=Rule(judge_to_me,judge_not_duration_rank),priority=5, block=True)
_single=on_keyword(set(single_keywords),rule=judge_to_me,priority=5, block=True)

_chat=on_message(rule=judge_to_me,priority=6, block=True)
# HANDLER
@_qid_blocked.handle()
async def f_qid_blocked(event):
    user_qid = event.get_user_id()
    log_message(f"QID_ACCESS_DENIED: {user_qid}")
    add_msg("access denied", event=event)
    await _qid_blocked.finish()

@_exporthistory.handle()
async def f_exporthistory(event):
    from .event_handlers.history_export import export_history_replies

    replies = await export_history_replies(event.get_plaintext())
    for reply in replies:
        add_msg(reply, event=event)


@_representative_battle.handle()
async def f_representative_battle(event: MessageEvent):
    from .event_handlers.representative import representative_query_reply
    from .zfile import existing_absolute_path

    raw_msg = event.get_plaintext().strip()
    try:
        result = await representative_query_reply(raw_msg)
        if result["kind"] == "text":
            add_msg(result["text"], event=event)
            return

        final_msg = Message(result["text"])
        image_path = existing_absolute_path(result["image_path"])
        if image_path:
            final_msg += MessageSegment.image(f"file://{image_path}")
        if result["commentary"]:
            final_msg += MessageSegment.text(f"\n{result['commentary']}")
        add_msg(final_msg, event=event)
    except ValueError as error:
        add_msg(str(error), event=event)
    except Exception as error:
        log_message(
            "REPRESENTATIVE_BATTLE_QUERY_ERROR: "
            f"query={raw_msg!r} error={error!r}\n{traceback.format_exc()}"
        )
        add_msg(f"代表局查询失败：query={raw_msg!r} error={error!r}", event=event)


@_dailyrepbattle.handle()
async def f_dailyrepbattle(event: MessageEvent):
    from .event_handlers.representative import daily_representative_debug_reply
    from .zfile import existing_absolute_path

    try:
        result = await daily_representative_debug_reply(event.get_plaintext())
        if result["kind"] == "text":
            add_msg(result["text"], event=event)
            return
        final_msg = Message(result["text"])
        image_path = existing_absolute_path(result["image_path"])
        if image_path:
            final_msg += MessageSegment.image(f"file://{image_path}")
        if result["commentary"]:
            final_msg += MessageSegment.text(f"\n{result['commentary']}")
        add_msg(final_msg, event=event)
        add_msg(result["acknowledgement"], event=event)

    except Exception as e:
        import traceback
        add_msg(f"调试执行崩溃：\n{traceback.format_exc()}", event=event)


@_representative_range_debug.handle()
async def f_representative_range_debug(event: MessageEvent):
    from .event_handlers.representative import representative_range_debug_replies

    raw_msg = event.get_plaintext().strip()
    try:
        for day_report in await representative_range_debug_replies(raw_msg):
            add_msg(day_report, event=event)
    except ValueError as error:
        add_msg(str(error), event=event)
    except Exception as error:
        log_message(
            "REPRESENTATIVE_BATTLE_RANGE_DEBUG_ERROR: "
            f"query={raw_msg!r} error={error!r}\n{traceback.format_exc()}"
        )
        add_msg(f"代表局区间调试失败：query={raw_msg!r} error={error!r}", event=event)


@_kpl_push.handle()
async def f_kpl_push(event: MessageEvent):
    from .zfunc import kpl_check_and_push
    import traceback

    raw_msg = event.get_plaintext().strip()
    args = raw_msg.replace("##kpl", "").strip().split()
    force = any(x.lower() in {"force", "f"} for x in args)
    preview_only = any(x.lower() in {"preview", "p"} for x in args)

    try:
        res = await asyncio.to_thread(kpl_check_and_push, debug=True, event=event, force=force, preview_only=preview_only)
        debug_text = res.get("debug") or ""
        if preview_only:
            if res.get("cid"):
                add_msg(f"KPL 预览完成 cid={res.get('cid')}（未生图）", event=event)
            else:
                add_msg("KPL 本轮未发现可预览战局", event=event)
        else:
            if "KPL_PUSH paused" in debug_text:
                add_msg("KPL 推送已暂停", event=event)
            elif res.get("pushed"):
                add_msg(f"KPL 推送完成 cid={res.get('cid')}", event=event)
            else:
                add_msg("KPL 本轮未发现可推送战局", event=event)
        if debug_text:
            add_msg(debug_text, msg_type="private", to_id=confs["QQBot"]["super_qid"])
    except Exception:
        add_msg("KPL 手动触发崩溃，堆栈已私聊", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])

@_bili_video_admin.handle()
async def f_bili_video_admin(event: MessageEvent):
    from .event_handlers.bili_video import admin_reply

    try:
        result = await admin_reply(event)
        add_msg(result, event=event)
    except Exception:
        add_msg("B站订阅管理崩溃，堆栈已私聊", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])

@_blocked.handle()
async def f_blocked(event):
    from .zfunc import qid2nick
    log_message("AT UNDER REPAIR")
    add_msg(Message(f"🤖暂时离线，{qid2nick(event.get_user_id())}请稍等。"), event=event)
    await _blocked.finish()
@_sleep_blocked.handle()
async def f_sleep_blocked(event):
    from .zfunc import qid2nick
    from .ztime import minutes_until_daily_window_end
    remaining_minutes = minutes_until_daily_window_end(bound_hour, bound_minute)
    add_msg(Message(f"🤖暂时离线，{qid2nick(event.get_user_id())}请稍等，{remaining_minutes} 分钟后恢复"), event=event)
    await _sleep_blocked.finish()
@_execute.handle()
async def f_execute(event):
    rcv_msg=event.get_plaintext().replace("##e","")
    from . import zapi
    from . import zevent
    from . import zfile
    from . import zfunc
    from . import zscheduler
    from . import ztime
    from . import zdebug
    try:
        ret = str(await asyncio.to_thread(eval, rcv_msg))
        add_msg(Message(ret), event=event)
    except Exception as e:
        add_msg(f"Execute Error: {str(e)}", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
    await _execute.finish()

@_update_local.handle()
async def f_update_local(event):
    from .zfile import read_dynamic_variables

    try:
        varia = read_dynamic_variables()
        vars(dmc).update(varia)
        await asyncio.to_thread(load_yesterday, 1)
        add_msg(Message("变量配置已更新"), event=event)
    except Exception as e:
        add_msg(f"Update Local Error: {str(e)}", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
    await _update_local.finish()

@_test.handle()
async def f_test(event):
    rcv_msg=event.get_plaintext()
    add_msg(Message(rcv_msg), event=event)
    await _test.finish()

@_forward.handle()
async def f_forward(bot,event):
    log_message("FORWARD")
    snd_msg=event.get_plaintext().replace("##f","")
    log_message("SEND: "+snd_msg)
    add_msg(snd_msg, msg_type="group", to_id=confs["QQBot"]["group_qid"])
@_pure_chat.handle()
async def f_pure_chat(bot,event):
    from .zfunc import ai_parser
    rcv_msg=event.get_plaintext()
    for k in sorted(common_expr.keys(), key=len, reverse=True):
        rcv_msg = re.sub(re.escape(k), common_expr[k], rcv_msg)

    snd_msg=""
    try:
        snd_msg += await asyncio.to_thread(ai_parser, [rcv_msg], "pure_chat")
        add_msg(snd_msg, event=event)
    except Exception as e:
        add_msg(str(e), event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
        return
@_repair.handle()
async def f_repair(bot,event):
    if (dmc.repair):
        log_message("REPAIR: 1->0")
        dmc.repair=False
        add_msg(Message("关闭repair"), event=event)
        await _repair.finish()
    else:
        log_message("REPAIR: 0->1")
        dmc.repair=True
        add_msg(Message("开启repair"), event=event)
        await _repair.finish()

@_show_code.handle()
async def f_show_code(bot,event):
    add_msg(Message("Code on Github："), event=event)
    add_msg("https://github.com/Raysance/HOK_QQBot_showcase/", event=event)

@_emoji_gen.handle()
async def f_emoji_gen(event):
    from .event_handlers.emoji import generate_emoji

    try:
        meta = await generate_emoji(event)
        add_msg(
            "PROMPT:\n"+meta["prompt"]+"\n\nREQUEST:\n"+json.dumps(meta.get("request", {}), ensure_ascii=False, indent=2),
            msg_type="private",
            to_id=confs["QQBot"]["super_qid"],
        )
        add_msg(MessageSegment.image(meta["image_path"]), event=event)
    except Exception as e:
        add_msg(f"emoji_gen_error: {str(e)}", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
    await _emoji_gen.finish()

@_group_poke.handle()
async def f_group_poke(bot, event):
    from .event_handlers.poke import group_poke_reply

    if not isinstance(event, PokeNotifyEvent):
        return
    result = await group_poke_reply(event)
    if result["kind"] == "none":
        return
    if result["kind"] == "blocked":
        await f_blocked(event)
        return
    if result["kind"] == "error":
        add_msg(result["text"], event=event)
        add_msg(
            result["traceback"],
            msg_type="private",
            to_id=confs["QQBot"]["super_qid"],
        )
        return
    if result["kind"] == "image":
        snd_msg = MessageSegment.image(result["image_path"])
    elif result["kind"] == "battle":
        snd_msg = MessageSegment.text(result["text"])
        if result["image_path"]:
            snd_msg += MessageSegment.image(result["image_path"])
        if result["with_ai_analysis"] and result["analysis"]:
            snd_msg += MessageSegment.text("\n" + result["analysis"])
    else:
        snd_msg = MessageSegment.text(result["text"])
    add_msg(snd_msg, event=event)



@_forget_me.handle()
async def f_forget_me(event): # 清除当前会话上下文和本人长期事实
    from .zfunc import agent_clear_memory
    await agent_clear_memory(event.get_user_id(), getattr(event, "group_id", None))
    add_msg(Message("成功清除记忆"), event=event)
    await _forget_me.finish()

@_peak_rank.handle()
async def f_peak_rank(event):
    from .zfunc import peak_rank_process

    try:
        result = await asyncio.to_thread(peak_rank_process)
        add_msg(result, event=event)
    except Exception as e:
        add_msg(
            f"巅峰排名失败：location=zevent.f_peak_rank params={{'source': 'local_json'}} error={repr(e)}",
            event=event,
        )
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])


@_hero_tier.handle()
async def f_hero_tier(event):
    from .zfile import existing_absolute_path
    from .zfunc import hero_tier_query_process

    try:
        image_path = await asyncio.to_thread(hero_tier_query_process)
        absolute_path = existing_absolute_path(image_path)
        if not absolute_path:
            raise Exception(f"hero_tier_image_missing: path={image_path!r}")
        add_msg(MessageSegment.image(f"file://{absolute_path}"), event=event)
    except Exception as error:
        add_msg(
            f"梯度查询失败：location=zevent.f_hero_tier params={{'command': '#梯度'}} error={error!r}",
            event=event,
        )
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])


@_bili_video_subscribe.handle()
async def f_bili_video_subscribe(event: MessageEvent):
    from .event_handlers.bili_video import subscribe_reply

    try:
        result = await subscribe_reply(event)
        add_msg(result, event=event)
    except Exception:
        add_msg("B站订阅失败，堆栈已私聊", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])


@_bili_video_unsubscribe.handle()
async def f_bili_video_unsubscribe(event: MessageEvent):
    from .event_handlers.bili_video import unsubscribe_reply

    try:
        result = await unsubscribe_reply(event)
        add_msg(result, event=event)
    except Exception:
        add_msg("B站取消订阅失败，堆栈已私聊", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])


@_bili_video_latest.handle()
async def f_bili_video_latest(event: MessageEvent):
    from .event_handlers.bili_video import latest_reply

    try:
        result = await latest_reply(event)
        add_msg(result, event=event)
    except Exception:
        add_msg("B站最新视频查询失败，堆栈已私聊", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])


@_bili_video_mine.handle()
async def f_bili_video_mine(event: MessageEvent):
    from .event_handlers.bili_video import my_subscription_reply

    try:
        result = await my_subscription_reply(event)
        add_msg(result, event=event)
    except Exception:
        add_msg("B站订阅查询失败，堆栈已私聊", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])


@_manual.handle()
async def f_manual(event):
    log_message("CMD: MANUAL")
    add_msg(Message("Code on Github："), event=event)
    add_msg("https://github.com/Raysance/HOK_QQBot_showcase/", event=event)


@_atall.handle()
async def f_atall(bot,event):
    from .zfunc import ai_parser
    from .ztime import current_datetime_text

    # at_msg=""
    # for name,id in qid.items():
    #     at_msg+=MessageSegment.at(str(id))
    # await _atall.send(at_msg)
    try:
        urge_msg = await asyncio.to_thread(ai_parser, [current_datetime_text(), str(namenick), dmc.today_news], "urge_game")
        add_msg(urge_msg, event=event)
    except Exception as e:
        add_msg(f"Urge Error: {str(e)}", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
    return
@_showonline.handle()
async def f_showonline(bot,event):
    from .event_handlers.player_reports import online_reply
    try:
        result = await online_reply()
        add_msg(result["text"], event=event)
        if result["error_report"]:
            add_msg(result["error_report"], msg_type="private", to_id=confs["QQBot"]["super_qid"])
    except Exception as e:
        add_msg(f"Online Check Error: {str(e)}", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
@_rnk.handle()
async def f_rnk(bot,event):
    from .event_handlers.player_reports import ranking_reply

    log_message("VISIT: RANK_FUNCTION")
    group_id = getattr(event, "group_id", None)
    if group_id:
        add_group_poke_task(event.get_user_id(), group_qid=group_id, source="rank_query")
    try:
        result = await ranking_reply(event)
    except Exception as e:
        add_msg(str(e), event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
        return
    add_msg(result["text"], event=event)
    if result["error_report"]:
        add_msg(result["error_report"], msg_type="private", to_id=confs["QQBot"]["super_qid"])
@_single.handle()
async def f_single(bot,event):
    from .event_handlers.player_reports import (
        single_last_battle_reply,
        single_summary_reply,
    )

    log_message("VISIT: SINGLEPLAYER_FUNCTION")
    group_id = getattr(event, "group_id", None)
    if group_id:
        add_group_poke_task(event.get_user_id(), group_qid=group_id, source="single_query")
    try:
        summary = await single_summary_reply(event)
    except Exception as e:
        add_msg(str(e), event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
        return
    if not summary:
        return
    add_msg(summary["text"], event=event)
    try:
        battle = await single_last_battle_reply(summary)
    except Exception as e:
        add_msg(str(e), event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
        return
    if battle:
        add_msg(MessageSegment.text(battle["text"])+MessageSegment.image(battle["image_path"]), event=event)
@_btlview.handle()
async def f_btlview(bot,event):
    from .event_handlers.player_reports import battle_view_reply
    try:
        snd_msg = await battle_view_reply(event)
        add_msg(snd_msg, event=event)
    except Exception as e:
        add_msg(f"View Error: {str(e)}", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
    return
@_btldetail.handle()
async def f_btldetail(bot,event):
    from .event_handlers.player_reports import last_battle_detail_reply
    try:
        result = await last_battle_detail_reply()
        add_msg(result["text"], event=event)
    except Exception as e:
        add_msg(f"BtlDetail Error: {str(e)}", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
@_heropower.handle()
async def f_heropower(bot,event):
    from .event_handlers.hero_visuals import hero_power_reply
    try:
        result = await hero_power_reply(event)
        add_msg(result["text"], event=event)
    except Exception as e:
        add_msg(f"HeroPower Error: {str(e)}", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])


@_honor_power_query.handle()
async def f_honor_power_query(bot, event):
    from .event_handlers.hero import honor_power_reply

    realname = None
    try:
        realname, snd_msg = await honor_power_reply(event)
        add_msg(snd_msg, event=event)
    except Exception as e:
        add_msg(
            f"战力查询失败：location=zevent.f_honor_power_query "
            f"params={{'realname': {realname!r}}} error={repr(e)}",
            event=event,
        )
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])


@_herostatistics.handle()
async def f_herostatistics(bot,event):
    from .event_handlers.hero import hero_statistics_reply

    try:
        snd_msg = await hero_statistics_reply(event)
        add_msg(snd_msg, event=event)
    except Exception as e:
        add_msg(str(e), event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
@_todayhero.handle()
async def f_todayhero(bot,event):
    from .event_handlers.hero_visuals import today_hero_reply

    try:
        result = await today_hero_reply(event)
        if result["kind"] == "image":
            message = MessageSegment.text(result["text"])
            message += MessageSegment.image(result["image_path"])
            message += MessageSegment.text(result["suffix"])
            add_msg(message, event=event)
        else:
            add_msg(result["text"], event=event)
    except Exception as e:
        add_msg(str(e), event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])

# @_allhero.handle()
# async def f_allhero(bot,event):
#     from .zfunc import allhero_process
#     from .zfunc import qid2nick

#     userqid=event.get_user_id()
#     rcv_msg=event.get_plaintext().replace("我",qid2nick(userqid))

#     snd_msg=allhero_process(rcv_msg)

#     await _allhero.send(snd_msg)
@_gradeanalyze.handle()
async def f_gradeanalyze(bot,event):
    from .event_handlers.hero_visuals import grade_analysis_reply
    try:
        result = await grade_analysis_reply(event)
        if result["kind"] == "image":
            add_msg(MessageSegment.image(result["image_path"]), event=event)
        else:
            add_msg(result["text"], event=event)
    except Exception as e:
        add_msg(f"GradeAnalyze Error: {str(e)}", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
@_watchbattle.handle()
async def f_watchbattle(bot,event):
    from .event_handlers.hero_visuals import watch_battle_reply
    try:
        result = await watch_battle_reply(event)
        if result["kind"] == "image":
            add_msg(MessageSegment.image(result["image_path"]), event=event)
        elif result["kind"] == "text":
            add_msg(result["text"], event=event)
    except Exception as e:
        add_msg(f"WatchBattle Error: {str(e)}", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])

@_spoiler.handle()
async def f_spoiler(bot, event):
    from .event_handlers.spoiler import (
        prepare_spoiler_request,
        run_spoiler_request,
    )

    try:
        prepared = await prepare_spoiler_request(event)
    except Exception as e:
        add_msg(f"获取实时战局失败: {str(e)}", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
        return
    if prepared["kind"] == "text":
        add_msg(prepared["text"], event=event)
        return
    add_msg(prepared["status"], event=event)
    try:
        result = await run_spoiler_request(prepared)
        message = MessageSegment.text(result["text"])
        message += MessageSegment.image(result["image_path"])
        add_msg(message, event=event)
    except Exception as e:
        add_msg(f"底蕴计算失败: {str(e)}", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])

@_recentpower.handle()
async def f_recentpower(bot,event):
    from .event_handlers.activity import battle_power_reply
    from .zfile import existing_absolute_path
    is_rank = "排行" in event.get_plaintext() or "排名" in event.get_plaintext()
    try:
        result = await battle_power_reply(event)
        image_path = existing_absolute_path(result.get("image_path"))
        if result["kind"] == "image" and image_path:
            add_msg(MessageSegment.image(f"file:///{image_path}"), event=event)
        else:
            add_msg(result["text"], event=event)
    except Exception as e:
        label = "底蕴排行失败" if is_rank else "底蕴统计失败"
        add_msg(f"{label}: {str(e)}", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])

@_diycode.handle()
async def f_diycode(bot: Bot, event: Event):
    from .zdiy import handle_diy_request
    user_input = event.get_plaintext().replace("#diy", "").replace("＃diy", "").strip()
    if not user_input:
        add_msg("请输入具体需求，例如：#diy 获取我的战绩并发送", event=event)
        return

    add_msg("正在生成代码并执行，请稍候...", event=event)
    try:
        result = await asyncio.to_thread(handle_diy_request, event, user_input)
        add_msg(str(result), event=event)
    except Exception as e:
        add_msg(f"Error: {str(e)}", event=event)

@_recentgames.handle()
async def f_recentgames(event):
    from .event_handlers.activity import game_time_reply
    from .zfile import existing_absolute_path
    is_rank = "排行" in event.get_plaintext() or "排名" in event.get_plaintext()
    try:
        result = await game_time_reply(event)
        image_path = existing_absolute_path(result.get("image_path"))
        if result["kind"] == "image" and image_path:
            add_msg(MessageSegment.image(f"file:///{image_path}"), event=event)
        else:
            add_msg(result["text"], event=event)
    except Exception as e:
        label = "时长排行失败" if is_rank else "获取时长失败"
        add_msg(f"{label}: {str(e)}", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])

@_history_query.handle()
async def f_history_query(event: Event):
    from .event_handlers.history_query import (
        HistoryQueryDetailError,
        history_query_reply,
    )

    try:
        result = await history_query_reply(event)
        if result["kind"] == "battle":
            message = MessageSegment.text(result["text"])
            message += MessageSegment.image(result["image_path"])
            add_msg(message, event=event)
        else:
            add_msg(result["text"], event=event)
    except HistoryQueryDetailError as error:
        add_msg(error.prefix + f"解析局内详情异常: {error}", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
    except Exception as e:
        add_msg(f"查询错误: {str(e)}", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])

@_direct_chat.handle()
@_chat.handle()
async def f_chat(bot,event):
    from .event_handlers.chat import prepare_chat_request, read_quoted_message
    from .zfunc import agent_chat

    request = prepare_chat_request(event, common_expr, dmc.use_mem)
    request["quoted_message"] = await read_quoted_message(event, bot.get_msg)
    if request["group_id"]:
        add_group_poke_task(
            request["user_id"],
            group_qid=request["group_id"],
            source="chat",
        )
    try:
        await agent_chat(**request)
    except Exception as e:
        add_msg(
            "AI对话失败：location=zevent.f_chat "
            f"params={{'user_id': {request['user_id']!r}, "
            f"'group_id': {request['group_id']!r}}} error={e!r}",
            event=event,
        )
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
        return
