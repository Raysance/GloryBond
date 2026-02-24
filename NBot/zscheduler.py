
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


@scheduler.scheduled_job("cron", hour=23, minute=30,second=00, id="notify_msg")
async def notify_msg():
    from .zfunc import rnk_process

    log_message("NOTIFY"+str(datetime.date.today()))
    snd_msg="今日王者战报(每日23:30推送)：\n"
    try:
        snd_msg+=rnk_process(rcv_msg="",caller=None,show_zero=False,show_analyze=True)[0]
    except Exception:
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
        return
    log_message("SEND: "+snd_msg)
    add_msg(snd_msg, msg_type="group", to_id=confs["QQBot"]["group_qid"])


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

    snd_msg =   "───来自网页分享───\n\n"
    btl_msg,pic_path=btldetail_process(**params,gen_image=True,show_profile=True)
    snd_msg += MessageSegment.text(btl_msg)+MessageSegment.image(pic_path)
    snd_msg += "\n\n───来自网页分享───"
    # add_msg(snd_msg, msg_type="private", to_id=confs["QQBot"]["super_qid"])
    add_msg(snd_msg, msg_type="group", to_id=confs["QQBot"]["group_qid"])

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
    print(game_params)
    Special=result["Special"]

    snd_msg =  "───来自网页分享───\n\n"
    btl_msg,pic_path=btldetail_process(**game_params,gen_image=True,show_profile=True,from_web=True)
    snd_msg += MessageSegment.text(btl_msg)+MessageSegment.image(pic_path)

    snd_msg += "\n\n"

    btl_msg,pic_path=coplayer_process(**game_params,from_web=True)
    snd_msg += MessageSegment.text(btl_msg)+MessageSegment.image(pic_path)
    snd_msg += "\n\n───来自网页分享───"
    
    if (Special):
        snd_msg = "Private Message\n" + snd_msg
        add_msg(snd_msg, msg_type="private", to_id=confs["QQBot"]["super_qid"])
    else:
        add_msg(snd_msg, msg_type="group", to_id=confs["QQBot"]["group_qid"])
        # add_msg(snd_msg, msg_type="private", to_id=confs["QQBot"]["super_qid"])

    return
