
from .zutil import *
from .zstatic import *
from . import zdynamic as dmc
from .utils.message_sender import add_msg

import os
import schedule
import datetime
import json
import random
import time
import traceback
import asyncio
# from apscheduler.schedulers.background import BackgroundScheduler
# from apscheduler.util import timezone

import nonebot
from nonebot_plugin_apscheduler import scheduler
from nonebot.adapters.onebot.v11 import MessageSegment
from apscheduler.executors.pool import ThreadPoolExecutor, ProcessPoolExecutor


@nonebot.get_driver().on_startup
async def _start_qq_agent():
    from .zfunc import agent_runtime_start
    if confs.get("QQAgent", {}).get("enabled", True):
        await agent_runtime_start()
        log_message("QQ_AGENT_READY shared agent_runtime initialized")


@nonebot.get_driver().on_shutdown
async def _stop_qq_agent():
    from .zfunc import agent_runtime_stop, player_client_close
    await agent_runtime_stop()
    await asyncio.to_thread(player_client_close)


@nonebot.get_driver().on_startup
async def _initialize_business_cache():
    await asyncio.to_thread(_initialize_business_cache_impl)


def _initialize_business_cache_impl():
    """An unavailable legacy API must not unregister the whole QQ plugin."""
    loaders = (
        ("yesterday", lambda: load_yesterday(1)),
        ("news", init_fetch_news),
        ("hero_rank", init_fetch_heroranklist),
        ("hero_tier", init_fetch_hero_tier),
    )
    for name, loader in loaders:
        try:
            loader()
        except Exception as error:
            log_message(f"BUSINESS_CACHE_INIT_FAILED: component={name} error_type={type(error).__name__}", logging.WARNING)


@scheduler.scheduled_job("interval", seconds=confs.get("QQAgent", {}).get("task_poll_seconds", 1),
                         id="qq_agent_tasks", max_instances=1, coalesce=True)
async def qq_agent_tasks():
    from .zfunc import agent_task_tick
    await agent_task_tick()


@scheduler.scheduled_job("interval", seconds=player_client_config.get("heartbeat_interval_seconds", 3),
                         id="player_client_heartbeat", max_instances=1, coalesce=True)
async def player_client_heartbeat():
    from .zfunc import player_client_heartbeat as maintain_connection
    await asyncio.to_thread(maintain_connection)

# 配置执行器和作业默认值，确保在任务运行时间不可控时不轻易跳过任务
# - 使用线程池以支持并发执行
# - 提高 max_instances 以允许多个并发实例
# - 关闭 coalesce，确保错过的多次触发不会合并成一次
# - 增大 misfire_grace_time，允许延迟一段时间内补执行

# scheduler.configure(
#     executors={
#         'default': ThreadPoolExecutor(10)
#     },
#     job_defaults={
#         'max_instances': 20,
#         'coalesce': False,
#         'misfire_grace_time': 3600
#     }
# )



@scheduler.scheduled_job("cron", hour=bound_hour, minute=bound_minute+10, second=00, id="load_yesterday")
def load_yesterday(imple_type=0):
    from .ztime import time_sul
    from .zfile import read_history_date

    yesterday_date=(time_sul()-datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    log_message("LOADLIST "+yesterday_date+".json")
    try:
        gameinfo=read_history_date(yesterday_date)
        for item in gameinfo:
            dmc.infolast[item['key']]={}
            for key,value in item.items():
                dmc.infolast[item['key']][key]=value
    except Exception:
        return
    return


@scheduler.scheduled_job(
    "cron",
    hour=bound_hour,
    minute=bound_minute-5,
    second=00,
    coalesce=False,
    max_instances=20,
    misfire_grace_time=3600,
    id="dump_today",
)
async def dump_today():
    return _dump_today_impl()
# @scheduler.scheduled_job("cron", hour=bound_hour, minute=bound_minute+5, second=00, id="dump_today_dupli")
# async def dump_today_dupli():
#     return _dump_today_impl()

def _dump_today_impl():
    from .ztime import time_sul
    from .zfunc import wzry_data
    from .zfile import daily_history_path, personal_history_path, writerl

    dump_date=time_sul().strftime("%Y-%m-%d")
    log_message("DUMPBEGIN "+dump_date+".json")
    retry_time=3
    gameinfo=[]
    while retry_time:
        if (not gameinfo): visitfield=userlist
        else: visitfield=dmc.DumpTodayFailedList
        for key in visitfield:
            try:
                gameinfo.append(
                    wzry_data(
                        realname=key,
                        savepath=personal_history_path(dump_date, userlist[key]),
                    )
                )
                time.sleep(0.3)
            except Exception:
                if (key not in dmc.DumpTodayFailedList):
                    dmc.DumpTodayFailedList.append(key)
        if (not dmc.DumpTodayFailedList):
            break
        time.sleep(10)
        retry_time-=1
    if (not retry_time): 
        add_msg("Dump failed for "+str(dmc.DumpTodayFailedList), msg_type="private", to_id=confs["QQBot"]["super_qid"])
        dmc.DumpTodayFailedList=[]
    filename = daily_history_path(dump_date)
    writerl(filename,gameinfo)
    log_message("DUMPEND "+dump_date+".json")
    return

@scheduler.scheduled_job(
    "cron",
    hour=23,
    minute=30,
    second=00,
    coalesce=False,
    max_instances=20,
    misfire_grace_time=3600,
    id="notify_msg",
)
async def notify_msg():
    from .zfunc import notify_msg_impl
    from .utils.message_sender import add_msg
    from .zutil import log_message
    from .zstatic import confs

    messages = notify_msg_impl()
    if not messages:
        return

    # 处理返回的结果
    for i, msg in enumerate(messages):
        # 如果第一条包含错误堆栈（通常很长），发给管理员
        if i == 0 and "Traceback" in str(msg):
            add_msg(msg, msg_type="private", to_id=confs["QQBot"]["super_qid"])
            continue

        # 处理（文本, 图片路径, 图片下方文案），保持发送顺序。
        final_msg = msg
        if isinstance(msg, (list, tuple)) and len(msg) in {2, 3}:
            from .zfile import existing_absolute_path
            from nonebot.adapters.onebot.v11 import Message, MessageSegment

            text_part, img_path = msg[:2]
            commentary = msg[2] if len(msg) == 3 else None
            final_msg = Message(text_part)
            image_path = existing_absolute_path(img_path)
            if image_path:
                final_msg += MessageSegment.image(f"file://{image_path}")
            if commentary:
                final_msg += MessageSegment.text(f"\n{commentary}")
            
        log_message(f"SEND_NOTIFY_{i}: {str(final_msg)[:100]}...")
        add_msg(final_msg, msg_type="group", to_id=confs["QQBot"]["group_qid"])


@scheduler.scheduled_job("cron", hour=6, minute=00,second=00, id="fetch_news")
async def fetch_news():
    return _fetch_news_impl()


@scheduler.scheduled_job("cron", hour=6, minute=30,second=00, id="fetch_herorank")
async def fetch_herorank():
    return _fetch_herorank_impl()

@scheduler.scheduled_job("cron", hour=7, minute=00,second=00, id="fetch_hero_tier")
async def fetch_hero_tier():
    return _fetch_hero_tier_impl()

def init_fetch_news():
    return _fetch_news_impl()

def init_fetch_heroranklist():
    return _fetch_herorank_impl()

def init_fetch_hero_tier():
    return _fetch_hero_tier_impl()


# @scheduler.scheduled_job(
#     "interval",
#     minutes=getattr(dmc, "KplPushIntervalMinutes", 2),
#     coalesce=False,
#     max_instances=20,
#     misfire_grace_time=3600,
#     id="kpl_match_push",
# )
async def kpl_match_push():
    from .zfunc import kpl_check_and_push
    try:
        await asyncio.to_thread(kpl_check_and_push, debug=False)
    except Exception:
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
        raise


@scheduler.scheduled_job(
    "interval",
    minutes=getattr(dmc, "BiliVideoPollIntervalMinutes", 5),
    id="bili_video_push",
    max_instances=1,
    coalesce=True,
    next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=60),
)
async def bili_video_push():
    from .zfunc import bili_video_check_and_push

    try:
        await asyncio.to_thread(bili_video_check_and_push, debug=False)
    except Exception:
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
        raise


@scheduler.scheduled_job(
    "interval",
    minutes=x_subscription_config["poll_interval_minutes"],
    id="x_subscription_push",
    max_instances=1,
    coalesce=True,
)
async def x_subscription_push():
    from .zfunc import x_check_and_push

    result = await asyncio.to_thread(x_check_and_push)
    if result.get("errors"):
        log_message("X_SUBSCRIPTION_PUSH: " + str(result["errors"]))


@scheduler.scheduled_job(
    "cron", hour=ai_daily_config.get("hour", 9), minute=ai_daily_config.get("minute", 0),
    second=0, timezone=ai_daily_config.get("timezone", "Asia/Shanghai"),
    id="ai_daily_push", max_instances=1, coalesce=True, misfire_grace_time=3600,
)
async def ai_daily_push():
    from .zfunc import ai_daily_check_and_push

    try:
        result = await asyncio.to_thread(ai_daily_check_and_push)
        log_message("AI_DAILY_PUSH: " + str(result))
    except Exception as error:
        log_message(f"AI_DAILY_PUSH_FAILED: {error!r}")
        add_msg(f"AI_DAILY_PUSH_FAILED: {error!r}", msg_type="private", to_id=confs["QQBot"]["super_qid"])


def _fetch_news_impl():
    from .zapi import ark_api
    from .ztime import date_r
    from .zfile import file_exist, news_text_path, readera, writera

    log_message("FETCH_NEWS")

    current_date = date_r()
    file_path = news_text_path(current_date)

    if file_exist(file_path):
        dmc.today_news = readera(file_path)
    else:
        dmc.today_news = ark_api(fetch_news_pmpt)
        writera(file_path, dmc.today_news)
    return None


def _fetch_herorank_impl():
    from .zapi import wzry_get_official
    from .ztime import date_r
    from .zfile import hero_rank_archive_path, read_hero_rank, writerl

    current_date = date_r()
    file_path = hero_rank_archive_path(current_date)

    stored_rank = read_hero_rank(current_date)
    if stored_rank:
        dmc.herorank = stored_rank
    else:
        for _, rankId in hero_ranklist_rankids.items():
            dmc.herorank[rankId] = wzry_get_official(reqtype="heroranklist", rankId=rankId, rankSegment=4)
        writerl(file_path, dmc.herorank)

    return None

def _fetch_hero_tier_impl():
    from .zapi import tianyuanzhiyi_tier_api
    from .ztime import date_r
    from .zfile import hero_tier_archive_path, read_hero_tier, writerl

    current_date = date_r()
    file_path = hero_tier_archive_path(current_date)

    stored_tier = read_hero_tier(current_date)
    if stored_tier:
        dmc.herotier = stored_tier
    else:
        tierinfo=tianyuanzhiyi_tier_api()
        for heroinfo in tierinfo["tiers"]:
            dmc.herotier[heroinfo["heroName"]]=heroinfo["finalNormalizedTierScore"]
        writerl(file_path, dmc.herotier)

    return None

@scheduler.scheduled_job("interval", seconds=3, id="web_shared_processor")
async def run_web_shared_btls_processor():
    from .zfunc import btldetail_process

    result=dmc.redis_deamon_share_btl.rpop(REDIS_KEY_BATTLE_SHARE_QUEUE)
    if (not result): return
    params_json=result
    params=json.loads(params_json)

    try:
        snd_msg =   "───来自网页分享───\n\n"
        btl_msg, pic_path, mapname = await asyncio.to_thread(
            btldetail_process, **params, gen_image=True, show_profile=True, from_web=True, strict_filter=False)
        snd_msg += MessageSegment.text(btl_msg)+MessageSegment.image(pic_path)
        snd_msg += "\n\n───来自网页分享───"
        # add_msg(snd_msg, msg_type="private", to_id=confs["QQBot"]["super_qid"])
        add_msg(snd_msg, msg_type="group", to_id=confs["QQBot"]["group_qid"])
    except Exception as e:
        add_msg(f"Shared Processor Error: {str(e)}", msg_type="private", to_id=confs["QQBot"]["super_qid"])
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])

    return 


@scheduler.scheduled_job("interval", seconds=3, id="web_analyze_processor")
async def run_web_analyze_btls_processor():
    from .zfunc import battle_power_process
    from .zfunc import btldetail_process
    from .ztime import wait

    result = dmc.redis_deamon_analyze_btl.rpop(REDIS_KEY_BATTLE_ANALYZE_QUEUE)
    
    if (not result): return
    result=json.loads(result)
    game_params=result["game_params"]
    del game_params['Special']
    print(game_params)
    Special=result["Special"]

    try:
        snd_msg =  "───来自网页分享───\n\n"
        btl_msg, pic_path, mapname = await asyncio.to_thread(btldetail_process, **game_params, gen_image=True, show_profile=True, from_web=True, strict_filter=False)
        snd_msg += MessageSegment.text(btl_msg)+MessageSegment.image(pic_path)

        snd_msg += "\n\n"

        with_ai_analysis = False
        btl_msg, pic_path,_,power_data = await asyncio.to_thread(
            battle_power_process,
            **game_params,
            spoiler_info={},
            from_web=True,
            with_ai_analysis=with_ai_analysis,
        )
        snd_msg += MessageSegment.text(btl_msg)
        if pic_path:
            snd_msg += MessageSegment.image(pic_path)
        if with_ai_analysis and power_data.get("aiAnalysis"):
            snd_msg += MessageSegment.text("\n" + power_data["aiAnalysis"])
        snd_msg += "\n\n───来自网页分享───"
        
        if (Special):
            snd_msg = "Private Message\n" + snd_msg
            add_msg(snd_msg, msg_type="private", to_id=confs["QQBot"]["super_qid"])
        else:
            add_msg(snd_msg, msg_type="group", to_id=confs["QQBot"]["group_qid"])
            # add_msg(snd_msg, msg_type="private", to_id=confs["QQBot"]["super_qid"])
    except Exception as e:
        add_msg(f"Analyze Processor Error: {str(e)}", msg_type="private", to_id=confs["QQBot"]["super_qid"])
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])

    return

@scheduler.scheduled_job(
    "interval",
    minutes=5,
    id="history_power_idle_processor",
    max_instances=1,
    coalesce=True,
    next_run_time=datetime.datetime.now() + datetime.timedelta(seconds=30),
)
async def run_history_power_idle_processor():
    from .zfunc import find_pending_battle_power_candidate
    from .zfunc import evaluate_battle_power_history
    from .zfunc import mark_battle_power_failed

    def has_higher_priority_task():
        active_until = getattr(dmc, "OfficialForegroundActiveUntil", 0)
        if active_until and time.time() < active_until:
            return True
        try:
            return bool(
                dmc.redis_deamon_share_btl.llen(REDIS_KEY_BATTLE_SHARE_QUEUE)
                or dmc.redis_deamon_analyze_btl.llen(REDIS_KEY_BATTLE_ANALYZE_QUEUE)
            )
        except Exception as e:
            log_message(f"HISTORY_POWER_QUEUE_CHECK_ERROR: {str(e)}")
            return False

    if getattr(dmc, "HistoryPowerIdleRunning", False):
        return
    dmc.HistoryPowerIdleRunning = True
    try:
        log_message("HISTORY_POWER_BEGIN")
        skipped_gameseqs = set()
        while True:
            if has_higher_priority_task():
                log_message("HISTORY_POWER_YIELD: higher priority task found")
                return
            candidate = await asyncio.to_thread(
                find_pending_battle_power_candidate,
                days=1,
                excluded_gameseqs=skipped_gameseqs,
            )
            if not candidate:
                log_message("HISTORY_POWER_IDLE_EMPTY")
                return
            try:
                power_data = await asyncio.to_thread(
                    evaluate_battle_power_history,
                    candidate["Params"],
                    candidate["roleid"],
                    "low",
                )
                log_message(f"HISTORY_POWER_DONE: {power_data.get('GameSeq')}")
            except Exception as e:
                gameseq = candidate.get("GameSeq")
                error_msg = f"HISTORY_POWER_ERROR: {gameseq} {str(e)}"
                log_message(error_msg)
                try:
                    await asyncio.to_thread(mark_battle_power_failed, gameseq, str(e), candidate)
                except Exception as mark_error:
                    error_msg += f"\nmark_failed_error: {str(mark_error)}"
                    log_message(f"HISTORY_POWER_MARK_FAILED_ERROR: {gameseq} {str(mark_error)}")
                add_msg(error_msg, msg_type="private", to_id=confs["QQBot"]["super_qid"])
                skipped_gameseqs.add(str(gameseq))
            await asyncio.sleep(0)
    finally:
        dmc.HistoryPowerIdleRunning = False
