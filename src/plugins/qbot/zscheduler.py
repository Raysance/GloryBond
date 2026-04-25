
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
    from .zfile import readerl

    yesterday_date=(time_sul()-datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    log_message("LOADLIST "+yesterday_date+".json")
    try:
        filename=os.path.join("history",yesterday_date+".json")
        gameinfo=readerl(filename)
        for item in gameinfo:
            dmc.infolast[item['key']]={}
            for key,value in item.items():
                dmc.infolast[item['key']][key]=value
    except Exception:
        return
    return


@scheduler.scheduled_job("cron", hour=bound_hour, minute=bound_minute-5, second=00, id="dump_today")
async def dump_today():
    return _dump_today_impl()
# @scheduler.scheduled_job("cron", hour=bound_hour, minute=bound_minute+5, second=00, id="dump_today_dupli")
# async def dump_today_dupli():
#     return _dump_today_impl()

def _dump_today_impl():
    from .ztime import time_sul
    from .zfunc import wzry_data
    from .zfile import writerl

    dump_date=time_sul().strftime("%Y-%m-%d")
    log_message("DUMPBEGIN "+dump_date+".json")
    retry_time=3
    gameinfo=[]
    while retry_time:
        if (not gameinfo): visitfield=userlist
        else: visitfield=dmc.DumpTodayFailedList
        for key in visitfield:
            try:
                gameinfo.append(wzry_data(realname=key,savepath=os.path.join("history", "personal", dump_date, str(userlist[key]) + ".json")))
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
    filename=os.path.join("history",dump_date+".json")
    writerl(filename,gameinfo)
    log_message("DUMPEND "+dump_date+".json")
    return

@scheduler.scheduled_job("cron", hour=bound_hour, minute=bound_minute, second=00, id="daily_user_summary")
def daily_user_summary():
    """每天深夜总结每个人的发言并存入长期记忆 (支持并行并行处理)"""
    from .zmemory import instance as zm
    from .zfunc import ai_parser, qid2nick
    from .zstatic import qid as qid_list
    import concurrent.futures
    import datetime

    log_message("DAILY_SUMMARY: Starting daily user chat summary...")
    
    now_str = datetime.datetime.now().strftime("%Y-%m-%d")

    def process_single_user(realname, user_qid):
        user_qid = str(user_qid)
        raw_logs = zm.get_passive_logs(user_qid)
        
        if not raw_logs:
            return
            
        logs_text = "\n".join(raw_logs)
        nick = qid2nick(user_qid)
        
        # 构造总结请求
        prompt = f"以下是用户 {nick} (QID: {user_qid}) 在过去 24 小时内的聊天记录片段：\n\n{logs_text}\n\n请用一两句话总结该用户的今日状态、提到的重要事项或表现出的偏好特点。直接返回总结内容，不要包含‘本段记录显示’等废话。"
        
        try:
            # 使用 ai_parser 进行总结
            summary = ai_parser([prompt], "summary", network=False)
            if summary and "Error" not in summary:
                # 记录内容包含时间、用户名和总结内容
                memory_content = f"[{now_str}] 整理自{nick}发言: {summary}"
                # 存入提炼记忆 (Summary memory)
                zm.save_summary_memory(user_qid, memory_content)
                log_message(f"DAILY_SUMMARY: Saved summary for {nick}")
                # 清除原始日志 (被动记忆)
                zm.clear_passive_logs(user_qid)
        except Exception as e:
            log_message(f"DAILY_SUMMARY_ERROR: {str(e)} for user {nick}")

    # 使用线程池并行处理
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(process_single_user, name, qid) for name, qid in qid_list.items()]
        concurrent.futures.wait(futures)
    
    log_message("DAILY_SUMMARY: All summaries completed.")

@scheduler.scheduled_job("cron", hour=23, minute=30,second=00, id="notify_msg")
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

        # 处理元组类型（文本, 图片路径），转换为 MessageSegment
        final_msg = msg
        if isinstance(msg, (list, tuple)) and len(msg) == 2:
            text_part, img_path = msg
            if img_path:
                from nonebot.adapters.onebot.v11 import MessageSegment
                import os
                final_msg = text_part + MessageSegment.image(f"file:///{os.path.abspath(img_path)}")
            else:
                final_msg = text_part
            
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

def _fetch_news_impl():
    from .zapi import ark_api
    from .ztime import date_r
    from .zfile import file_exist
    from .zfile import readera
    from .zfile import writera

    log_message("FETCH_NEWS")

    current_date = date_r()
    news_dir = "news"
    file_path = os.path.join(news_dir, f"{current_date}.txt")

    if file_exist(file_path):
        dmc.today_news = readera(file_path)
    else:
        dmc.today_news = ark_api(fetch_news_pmpt)
        writera(file_path, dmc.today_news)
    return None


def _fetch_herorank_impl():
    from .zapi import wzry_get_official
    from .ztime import date_r
    from .zfile import file_exist
    from .zfile import readerl
    from .zfile import writerl

    current_date = date_r()
    herorank_dir = "herorank"
    file_path = os.path.join(herorank_dir, f"{current_date}.json")

    if file_exist(file_path):
        dmc.herorank = readerl(file_path)
    else:
        for _, rankId in hero_ranklist_rankids.items():
            dmc.herorank[rankId] = wzry_get_official(reqtype="heroranklist", rankId=rankId, rankSegment=4)
        writerl(file_path, dmc.herorank)

    return None

def _fetch_hero_tier_impl():
    from .zapi import tianyuanzhiyi_tier_api
    from .ztime import date_r
    from .zfile import file_exist
    from .zfile import readerl
    from .zfile import writerl

    current_date = date_r()
    herotier_dir = "herotier"
    file_path = os.path.join(herotier_dir, f"{current_date}.json")

    if file_exist(file_path):
        dmc.herotier = readerl(file_path)
    else:
        tierinfo=tianyuanzhiyi_tier_api()
        for heroinfo in tierinfo["tiers"]:
            dmc.herotier[heroinfo["heroName"]]=heroinfo["finalNormalizedTierScore"]
        writerl(file_path, dmc.herotier)

    return None

@scheduler.scheduled_job("interval", seconds=3, id="web_shared_processor")
async def run_web_shared_btls_processor():
    from .zfunc import btldetail_process

    result=dmc.redis_deamon_share_btl.rpop("Shared_queue")
    if (not result): return
    params_json=result
    params=json.loads(params_json)

    try:
        snd_msg =   "───来自网页分享───\n\n"
        btl_msg, pic_path, mapname = await asyncio.to_thread(btldetail_process, **params, gen_image=True, show_profile=True)
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
    from .zfunc import coplayer_process
    from .zfunc import btldetail_process
    from .ztime import wait

    result = dmc.redis_deamon_analyze_btl.rpop("Analyze_queue")
    
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

        btl_msg, pic_path,_ = await asyncio.to_thread(coplayer_process, **game_params,spoiler_info={},from_web=True)
        snd_msg += MessageSegment.text(btl_msg)+MessageSegment.image(pic_path)
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
