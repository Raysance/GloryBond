
from glorybond.common import *
from glorybond.config.settings import *
from glorybond import runtime as dmc
from glorybond.apps.qq.message_sender import add_msg
from glorybond.apps.qq.errors import report_exception, report_error_text
from glorybond.apps.qq.message_sender import add_group_poke_task
from glorybond.apps.qq import scheduler as zscheduler

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

from glorybond.apps.qq.ingress import capture_group_message
from glorybond.apps.qq.rules import check_repair, check_sleep, get_validated_name as _get_validated_name, judge_bili_video_latest, judge_bili_video_mine, judge_bili_video_subscribe, judge_bili_video_unsubscribe, judge_bili_share, judge_player_client, judge_x_subscription, judge_x_subscription_admin, judge_bot_addressed, judge_direct_ai_request, judge_herostatistics_query, judge_honor_power_query, judge_not_duration_rank, judge_qid_blocked, judge_representative_battle_query, judge_super_command, judge_to_me, judge_live_watch, judge_unsuper


def get_validated_name(event):
    matching_name = _get_validated_name(event)
    if not matching_name:
        add_msg("Name Not Found", event=event)
    return matching_name


@_all_messages.handle()
async def handle_all_messages(event: MessageEvent):
    from glorybond.storage.files import refresh_login_credentials
    refresh_login_credentials()
    await capture_group_message(event)

# EVENT
_group_poke = on_notice()
_chat_recall = on_notice(priority=0, block=False)
_qid_blocked=on_message(rule=judge_qid_blocked,priority=1, block=True)
_repair=on_fullmatch("##r",rule=judge_super_command,priority=1, block=True)
_service_health = on_fullmatch({"##health", "＃＃health", "##连通性检查", "＃＃连通性检查"}, rule=judge_super_command, priority=1, block=True)
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
_x_subscription_admin = on_message(rule=Rule(judge_super_command, judge_x_subscription_admin), priority=1, block=True)

_sleep_blocked = on_message(rule=Rule(judge_bot_addressed,check_sleep), priority=2, block=True)
_blocked=on_message(rule=Rule(judge_bot_addressed,check_repair,judge_unsuper),priority=2, block=True)
_bili_share = on_message(rule=judge_bili_share, priority=2, block=True)

_player_client = on_message(rule=judge_player_client, priority=3, block=True)
_live_watch = on_message(rule=Rule(judge_to_me, judge_live_watch), priority=3, block=True)

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
_inactivity_rank = on_fullmatch(
    ("#多久没打了", "＃多久没打了", "#多久没打排名", "＃多久没打排名",
     "#多久没打排行", "＃多久没打排行", "#多久没打了排名", "＃多久没打了排名",
     "#多久没打了排行", "＃多久没打了排行"),
    rule=judge_to_me, priority=3, block=True,
)
_skin_votes = on_fullmatch(
    ("#皮肤返场", "＃皮肤返场", "#返场排行", "＃返场排行", "#返场排名", "＃返场排名",
     "#皮肤返场排行", "＃皮肤返场排行", "#皮肤返场排名", "＃皮肤返场排名",
     "#皮肤返场查询", "＃皮肤返场查询"),
    rule=judge_to_me, priority=3, block=True,
)
_honor_power_query = on_message(
    rule=judge_honor_power_query,
    priority=3,
    block=True,
)
_bili_video_latest = on_message(rule=Rule(judge_to_me, judge_bili_video_latest), priority=3, block=True)
_x_subscription = on_message(rule=Rule(judge_to_me, judge_x_subscription), priority=3, block=True)
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
@_bili_share.handle()
async def f_bili_share(event: MessageEvent):
    from glorybond.apps.qq.handlers.bili_video import iter_share_replies

    async for reply in iter_share_replies(event, on_error=lambda error: report_exception(error, operation="B站视频处理", event=event)):
        add_msg(reply, event=event, metadata={"source": "bili_share"})


@_qid_blocked.handle()
async def f_qid_blocked(event):
    user_qid = event.get_user_id()
    log_message(f"QID_ACCESS_DENIED: {user_qid}")
    add_msg("access denied", event=event)
    await _qid_blocked.finish()

@_exporthistory.handle()
async def f_exporthistory(event):
    from glorybond.apps.qq.handlers.history_export import export_history_replies

    replies = await export_history_replies(event.get_plaintext(), on_error=lambda error: report_exception(error, operation="战绩导出", event=event, partial=True))
    for reply in replies:
        add_msg(reply, event=event)


@_representative_battle.handle()
async def f_representative_battle(event: MessageEvent):
    from glorybond.apps.qq.handlers.representative import representative_query_reply
    from glorybond.storage.files import existing_absolute_path

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
    except Exception as error:
        report_exception(error, operation='代表局查询', event=event)


@_dailyrepbattle.handle()
async def f_dailyrepbattle(event: MessageEvent):
    from glorybond.apps.qq.handlers.representative import daily_representative_debug_reply
    from glorybond.storage.files import existing_absolute_path

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
            
    except Exception as error:
        report_exception(error, operation='代表局调试', event=event)


@_representative_range_debug.handle()
async def f_representative_range_debug(event: MessageEvent):
    from glorybond.apps.qq.handlers.representative import representative_range_debug_replies

    raw_msg = event.get_plaintext().strip()
    try:
        for day_report in await representative_range_debug_replies(raw_msg):
            add_msg(day_report, event=event)
    except Exception as error:
        report_exception(error, operation='代表局区间查询', event=event)


@_kpl_push.handle()
async def f_kpl_push(event: MessageEvent):
    from glorybond.features.facade import kpl_check_and_push

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
    except Exception as error:
        report_exception(error, operation='KPL 推送', event=event)

@_bili_video_admin.handle()
async def f_bili_video_admin(event: MessageEvent):
    from glorybond.apps.qq.handlers.bili_video import admin_reply

    try:
        result = await admin_reply(event, on_error=lambda error: report_exception(error, operation="B站订阅检查", event=event, partial=True))
        add_msg(result, event=event)
    except Exception as error:
        report_exception(error, operation='B站订阅管理', event=event)

@_blocked.handle()
async def f_blocked(event):
    from glorybond.features.facade import qid2nick
    log_message("AT UNDER REPAIR")
    add_msg(Message(f"🤖暂时离线，{qid2nick(event.get_user_id())}请稍等。"), event=event)
    await _blocked.finish()
@_sleep_blocked.handle()
async def f_sleep_blocked(event):
    from glorybond.features.facade import qid2nick
    from glorybond.time import minutes_until_daily_window_end
    remaining_minutes = minutes_until_daily_window_end(bound_hour, bound_minute)
    add_msg(Message(f"🤖暂时离线，{qid2nick(event.get_user_id())}请稍等，{remaining_minutes} 分钟后恢复"), event=event)
    await _sleep_blocked.finish()
@_execute.handle()
async def f_execute(event):
    rcv_msg=event.get_plaintext().replace("##e","")
    from glorybond.integrations import api as zapi
    from glorybond.apps.qq import events as zevent
    from glorybond.storage import files as zfile
    from glorybond.features import facade as zfunc
    from glorybond.apps.qq import scheduler as zscheduler
    from glorybond import time as ztime
    from tools.debugger import legacy as zdebug
    try:
        ret = str(await asyncio.to_thread(eval, rcv_msg))
        add_msg(Message(ret), event=event)
    except Exception as error:
        report_exception(error, operation='管理命令执行', event=event)
    await _execute.finish()

@_update_local.handle()
async def f_update_local(event):
    from glorybond.storage.files import read_dynamic_variables

    try:
        varia = read_dynamic_variables()
        vars(dmc).update(varia)
        await asyncio.to_thread(load_yesterday, 1)
        add_msg(Message("变量配置已更新"), event=event)
    except Exception as error:
        report_exception(error, operation='配置更新', event=event)
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
    from glorybond.features.facade import ai_parser
    rcv_msg=event.get_plaintext()
    for k in sorted(common_expr.keys(), key=len, reverse=True):
        rcv_msg = re.sub(re.escape(k), common_expr[k], rcv_msg)

    snd_msg=""
    try:
        snd_msg += await asyncio.to_thread(ai_parser, [rcv_msg], "pure_chat")
        add_msg(snd_msg, event=event)
    except Exception as error:
        report_exception(error, operation='AI 简单对话', event=event)
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
    from glorybond.apps.qq.handlers.emoji import generate_emoji

    try:
        meta = await generate_emoji(event)
        add_msg(
            "PROMPT:\n"+meta["prompt"]+"\n\nREQUEST:\n"+json.dumps(meta.get("request", {}), ensure_ascii=False, indent=2),
            msg_type="private",
            to_id=confs["QQBot"]["super_qid"],
        )
        add_msg(MessageSegment.image(meta["image_path"]), event=event)
    except Exception as error:
        report_exception(error, operation='表情生成', event=event)
    await _emoji_gen.finish()

@_group_poke.handle()
async def f_group_poke(bot, event):
    from glorybond.apps.qq.handlers.poke import group_poke_reply

    if not isinstance(event, PokeNotifyEvent):
        return
    result = await group_poke_reply(event)
    if result["kind"] == "none":
        return
    if result["kind"] == "blocked":
        await f_blocked(event)
        return
    if result["kind"] == "error":
        report_exception(result["error"], operation="戳一戳处理", event=event)
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
    from glorybond.features.facade import agent_clear_memory
    await agent_clear_memory(event.get_user_id(), getattr(event, "group_id", None))
    add_msg(Message("成功清除记忆"), event=event)
    await _forget_me.finish()

@_peak_rank.handle()
async def f_peak_rank(event):
    from glorybond.features.facade import peak_rank_process

    try:
        result = await asyncio.to_thread(peak_rank_process)
        add_msg(result, event=event)
    except Exception as error:
        report_exception(error, operation='巅峰排名', event=event)


@_inactivity_rank.handle()
async def f_inactivity_rank(event):
    from glorybond.features.facade import inactivity_rank_process

    try:
        result = await asyncio.to_thread(inactivity_rank_process)
        add_msg(result, event=event)
    except Exception as error:
        report_exception(error, operation='最近对局排名', event=event)


@_hero_tier.handle()
async def f_hero_tier(event):
    from glorybond.storage.files import existing_absolute_path
    from glorybond.features.facade import hero_tier_query_process

    try:
        image_path = await asyncio.to_thread(hero_tier_query_process)
        absolute_path = existing_absolute_path(image_path)
        if not absolute_path:
            raise Exception(f"hero_tier_image_missing: path={image_path!r}")
        add_msg(MessageSegment.image(f"file://{absolute_path}"), event=event)
    except Exception as error:
        report_exception(error, operation='英雄梯度查询', event=event)


@_skin_votes.handle()
async def f_skin_votes(event):
    from glorybond.apps.qq.handlers.skin_votes import skin_votes_reply
    from glorybond.storage.files import existing_absolute_path

    try:
        result = await skin_votes_reply()
        message = MessageSegment.text(result["text"])
        if result.get("image_path"):
            path = existing_absolute_path(result["image_path"])
            if path:
                message += MessageSegment.image(f"file://{path}")
            else:
                message += MessageSegment.text("\n返场排行图片未找到，请稍后重试（zevent.f_skin_votes）")
        add_msg(message, event=event)
    except Exception as error:
        report_exception(error, operation='皮肤返场排行', event=event)


@_x_subscription_admin.handle()
@_x_subscription.handle()
async def f_x_subscription(event: MessageEvent):
    from glorybond.apps.qq.handlers.x_subscription import command_reply

    try:
        reply = await command_reply(event, on_error=lambda error: report_exception(error, operation="X 订阅查询", event=event, partial=True))
        if reply:
            add_msg(reply, event=event)
    except Exception as error:
        report_exception(error, operation='X 订阅处理', event=event)


@_service_health.handle()
async def f_service_health(event: MessageEvent):
    from glorybond.apps.qq.handlers.service_health import command_reply
    from glorybond.apps.qq.message_sender import add_forward_msg

    add_msg("开始最小服务连通性检查，请稍候。", event=event)
    try:
        replies = await command_reply()
        if len(replies) == 2:
            add_forward_msg(replies, event=event, title="Bot 服务检查")
        else:
            add_msg(replies[0], event=event)
    except Exception as error:
        report_exception(error, operation='服务连通性检查', event=event)


@_bili_video_subscribe.handle()
async def f_bili_video_subscribe(event: MessageEvent):
    from glorybond.apps.qq.handlers.bili_video import subscribe_reply

    try:
        result = await subscribe_reply(event, on_error=lambda error: report_exception(error, operation="B站订阅视频获取", event=event, partial=True))
        for reply in result if isinstance(result, list) else [result]:
            add_msg(reply, event=event)
    except Exception as error:
        report_exception(error, operation='B站订阅', event=event)


@_bili_video_unsubscribe.handle()
async def f_bili_video_unsubscribe(event: MessageEvent):
    from glorybond.apps.qq.handlers.bili_video import unsubscribe_reply

    try:
        result = await unsubscribe_reply(event)
        add_msg(result, event=event)
    except Exception as error:
        report_exception(error, operation='B站取消订阅', event=event)


@_bili_video_latest.handle()
async def f_bili_video_latest(event: MessageEvent):
    from glorybond.apps.qq.handlers.bili_video import latest_reply

    try:
        result = await latest_reply(event, on_error=lambda error: report_exception(error, operation="B站最新视频", event=event, partial=True))
        for reply in result if isinstance(result, list) else [result]:
            add_msg(reply, event=event)
    except Exception as error:
        report_exception(error, operation='B站最新视频', event=event)


@_bili_video_mine.handle()
async def f_bili_video_mine(event: MessageEvent):
    from glorybond.apps.qq.handlers.bili_video import my_subscription_reply

    try:
        result = await my_subscription_reply(event)
        add_msg(result, event=event)
    except Exception as error:
        report_exception(error, operation='B站订阅查询', event=event)


@_manual.handle()
async def f_manual(event):
    log_message("CMD: MANUAL")
    add_msg(Message("Code on Github："), event=event)
    add_msg("https://github.com/Raysance/HOK_QQBot_showcase/", event=event)


@_atall.handle()
async def f_atall(bot,event):
    from glorybond.features.facade import ai_parser
    from glorybond.time import current_datetime_text

    # at_msg=""
    # for name,id in qid.items():
    #     at_msg+=MessageSegment.at(str(id))
    # await _atall.send(at_msg)
    try:
        urge_msg = await asyncio.to_thread(ai_parser, [current_datetime_text(), str(namenick), dmc.today_news], "urge_game")
        add_msg(urge_msg, event=event)
    except Exception as error:
        report_exception(error, operation='游戏邀请', event=event)
    return
@_showonline.handle()
async def f_showonline(bot,event):
    from glorybond.apps.qq.handlers.player_reports import online_reply
    try:
        result = await online_reply()
        add_msg(result["text"], event=event)
        if result["error_report"]:
            report_error_text(result["error_report"], operation="战报数据采集", event=event, partial=True)
    except Exception as error:
        report_exception(error, operation='在线状态查询', event=event)
@_rnk.handle()
async def f_rnk(bot,event):
    from glorybond.apps.qq.handlers.player_reports import ranking_reply
    from glorybond.storage.files import existing_absolute_path

    log_message("VISIT: RANK_FUNCTION")
    group_id = getattr(event, "group_id", None)
    if group_id:
        add_group_poke_task(event.get_user_id(), group_qid=group_id, source="rank_query")
    try:
        result = await ranking_reply(event)
    except Exception as error:
        report_exception(error, operation='战报排行', event=event)
        return
    image_path = existing_absolute_path(result["image_path"])
    if image_path:
        add_msg(MessageSegment.image(f"file://{image_path}"), event=event)
    else:
        add_msg(result["text"] or "战报图片生成失败，请稍后重试。", event=event)
    if result["error_report"]:
        report_error_text(result["error_report"], operation="战报数据采集", event=event, partial=True)
@_single.handle()
async def f_single(bot,event):
    from glorybond.apps.qq.handlers.player_reports import single_last_battle_reply, single_summary_reply

    log_message("VISIT: SINGLEPLAYER_FUNCTION")
    group_id = getattr(event, "group_id", None)
    if group_id:
        add_group_poke_task(event.get_user_id(), group_qid=group_id, source="single_query")
    try:
        summary = await single_summary_reply(event)
    except Exception as error:
        report_exception(error, operation='个人战绩查询', event=event)
        return
    if not summary:
        return
    add_msg(summary["text"], event=event)
    try:
        battle = await single_last_battle_reply(summary)
    except Exception as error:
        report_exception(error, operation='个人战绩查询', event=event)
        return
    if battle:
        add_msg(MessageSegment.text(battle["text"])+MessageSegment.image(battle["image_path"]), event=event)
@_btlview.handle()
async def f_btlview(bot,event):
    from glorybond.apps.qq.handlers.player_reports import battle_view_reply
    try:
        snd_msg = await battle_view_reply(event)
        add_msg(snd_msg, event=event)
    except Exception as error:
        report_exception(error, operation='战局展示', event=event)
    return
@_btldetail.handle()
async def f_btldetail(bot,event):
    from glorybond.apps.qq.handlers.player_reports import last_battle_detail_reply
    try:
        result = await last_battle_detail_reply()
        add_msg(result["text"], event=event)
    except Exception as error:
        report_exception(error, operation='战局详情', event=event)
@_heropower.handle()
async def f_heropower(bot,event):
    from glorybond.apps.qq.handlers.hero_visuals import hero_power_reply
    try:
        result = await hero_power_reply(event)
        add_msg(result["text"], event=event)
    except Exception as error:
        report_exception(error, operation='英雄底蕴', event=event)


@_honor_power_query.handle()
async def f_honor_power_query(bot, event):
    from glorybond.apps.qq.handlers.hero import honor_power_reply

    realname = None
    try:
        realname, snd_msg = await honor_power_reply(event)
        add_msg(snd_msg, event=event)
    except Exception as error:
        report_exception(error, operation='英雄战力查询', event=event)


@_herostatistics.handle()
async def f_herostatistics(bot,event):
    from glorybond.apps.qq.handlers.hero import hero_statistics_reply

    try:
        snd_msg = await hero_statistics_reply(event)
        add_msg(snd_msg, event=event)
    except Exception as error:
        report_exception(error, operation='英雄统计', event=event)
@_todayhero.handle()
async def f_todayhero(bot,event):
    from glorybond.apps.qq.handlers.hero_visuals import today_hero_reply

    try:
        result = await today_hero_reply(event)
        if result["kind"] == "image":
            message = MessageSegment.text(result["text"])
            message += MessageSegment.image(result["image_path"])
            message += MessageSegment.text(result["suffix"])
            add_msg(message, event=event)
        else:
            add_msg(result["text"], event=event)
    except Exception as error:
        report_exception(error, operation='今日英雄统计', event=event)
    
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
    from glorybond.apps.qq.handlers.hero_visuals import grade_analysis_reply
    try:
        result = await grade_analysis_reply(event)
        if result["kind"] == "image":
            add_msg(MessageSegment.image(result["image_path"]), event=event)
        else:
            add_msg(result["text"], event=event)
    except Exception as error:
        report_exception(error, operation='评分分析', event=event)
@_watchbattle.handle()
async def f_watchbattle(bot,event):
    from glorybond.apps.qq.handlers.hero_visuals import watch_battle_reply
    try:
        result = await watch_battle_reply(event)
        if result["kind"] == "image":
            add_msg(MessageSegment.image(result["image_path"]), event=event)
        elif result["kind"] == "text":
            add_msg(result["text"], event=event)
    except Exception as error:
        report_exception(error, operation='观战处理', event=event)


@_live_watch.handle()
async def f_live_watch(event):
    from glorybond.apps.qq.handlers.live_watch import prepare_watch_request, run_watch_request
    from glorybond.apps.qq.message_sender import add_text_image_msg

    prepared = prepare_watch_request(event)
    if prepared["kind"] == "text":
        add_msg(prepared["text"], event=event)
        return
    add_msg(prepared["status"], event=event)
    result = await run_watch_request(prepared, on_error=lambda error: report_exception(error, operation="观战截图", event=event))
    if result["kind"] == "reported":
        return
    if result["kind"] == "image":
        add_text_image_msg(result["text"], result["image_path"], event=event)
    else:
        add_msg(result["text"], event=event)

@_spoiler.handle()
async def f_spoiler(bot, event):
    from glorybond.apps.qq.handlers.spoiler import prepare_spoiler_request, run_spoiler_request

    try:
        prepared = await prepare_spoiler_request(event)
    except Exception as error:
        report_exception(error, operation='实时战局分析', event=event)
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
    except Exception as error:
        report_exception(error, operation='实时战局分析', event=event)

@_recentpower.handle()
async def f_recentpower(bot,event):
    from glorybond.apps.qq.handlers.activity import battle_power_reply
    from glorybond.storage.files import existing_absolute_path
    is_rank = "排行" in event.get_plaintext() or "排名" in event.get_plaintext()
    try:
        result = await battle_power_reply(event)
        image_path = existing_absolute_path(result.get("image_path"))
        if result["kind"] == "image" and image_path:
            add_msg(MessageSegment.image(f"file:///{image_path}"), event=event)
        else:
            add_msg(result["text"], event=event)
    except Exception as error:
        report_exception(error, operation='底蕴统计', event=event)

@_diycode.handle()
async def f_diycode(bot: Bot, event: Event):
    from glorybond.features.custom import handle_diy_request
    user_input = event.get_plaintext().replace("#diy", "").replace("＃diy", "").strip()
    if not user_input:
        add_msg("请输入具体需求，例如：#diy 获取我的战绩并发送", event=event)
        return
    
    add_msg("正在生成代码并执行，请稍候...", event=event)
    try:
        result = await asyncio.to_thread(handle_diy_request, event, user_input)
        add_msg(str(result), event=event)
    except Exception as error:
        report_exception(error, operation='自定义任务', event=event)

@_recentgames.handle()
async def f_recentgames(event):
    from glorybond.apps.qq.handlers.activity import game_time_reply
    from glorybond.storage.files import existing_absolute_path
    is_rank = "排行" in event.get_plaintext() or "排名" in event.get_plaintext()
    try:
        result = await game_time_reply(event)
        image_path = existing_absolute_path(result.get("image_path"))
        if result["kind"] == "image" and image_path:
            add_msg(MessageSegment.image(f"file:///{image_path}"), event=event)
        else:
            add_msg(result["text"], event=event)
    except Exception as error:
        report_exception(error, operation='游戏时长统计', event=event)

@_history_query.handle()
async def f_history_query(event: Event):
    from glorybond.apps.qq.handlers.history_query import history_query_reply

    try:
        result = await history_query_reply(event)
        if result["kind"] == "battle":
            message = MessageSegment.text(result["text"])
            message += MessageSegment.image(result["image_path"])
            add_msg(message, event=event)
        else:
            add_msg(result["text"], event=event)
    except Exception as error:
        report_exception(error, operation='历史战绩查询', event=event)

@_direct_chat.handle()
@_chat.handle()
async def f_chat(bot,event):
    from glorybond.apps.qq.handlers.chat import chat_message_key, live_chat_rollouts, prepare_live_chat_request
    from glorybond.features.facade import agent_chat

    async def respond():
        request = await prepare_live_chat_request(event, common_expr, dmc.use_mem, bot.get_msg, bot.get_forward_msg, bot)
        if request is None:
            return
        if request["group_id"]:
            add_group_poke_task(
                request["user_id"],
                group_qid=request["group_id"],
                source="chat",
            )
        await agent_chat(**request)

    try:
        await live_chat_rollouts.run(chat_message_key(event), respond)
    except Exception as error:
        report_exception(error, operation='AI 对话准备', event=event)
        return


@_chat_recall.handle()
async def f_chat_recall(event: Event):
    from glorybond.apps.qq.handlers.chat import cancel_recalled_chat

    cancel_recalled_chat(event)


@_player_client.handle()
async def f_player_client(event: MessageEvent):
    from contextlib import aclosing
    from glorybond.apps.qq.handlers.player_client import reply_stream
    from glorybond.apps.qq.message_sender import add_text_image_msg

    async with aclosing(reply_stream(event)) as replies:
        async for reply in replies:
            if isinstance(reply, dict):
                if reply.get("image_path"):
                    add_text_image_msg(reply["text"], reply["image_path"], event=event)
                else:
                    add_msg(reply["text"], event=event)
            elif isinstance(reply, str):
                add_msg(reply, event=event)
            else:
                for message in reply:
                    add_msg(message, event=event)
