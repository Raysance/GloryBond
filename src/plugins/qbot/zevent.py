
from .zutil import *
from .zstatic import *
from . import zdynamic as dmc

import nonebot
from nonebot import get_plugin_config,require
require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler
from nonebot.rule import to_me
from nonebot.adapters import Message
from nonebot.params import CommandArg
from nonebot.adapters import MessageTemplate
from nonebot.adapters.onebot.v11 import Bot, Event, Message,MessageEvent,MessageSegment
from nonebot.adapters.onebot.v11.event import PokeNotifyEvent
from nonebot.plugin import on_message,on_notice,on_request,on_keyword,on_command,on_regex,on_fullmatch

async def judge_name(event)->bool:
    return "示例玩家41" not in event.get_plaintext()
async def judge_super(event)->bool:
    return str(super_id)==str(event.get_user_id())
async def judge_unsuper(event)->bool:
    return str(super_id)!=str(event.get_user_id())
async def check_repair(event)->bool:
    return dmc.repair
async def check_btl_request(event)->bool:
    return last_request_btllist!=[]
# EVENT
_group_poke = on_notice()
_repair=on_keyword({"##r"},rule=judge_super,priority=1, block=True)
_execute=on_keyword({"##e"},rule=judge_super,priority=1, block=True)
_test=on_keyword({"##t"},rule=judge_super,priority=1, block=True)
_update_local=on_keyword({"##u"},rule=judge_super,priority=1, block=True)
_forward=on_keyword({"##f"},rule=judge_super,priority=1, block=True)
_pure_chat=on_keyword({"##c"},rule=judge_super,priority=1, block=True)
_super_only = on_keyword({"##amnesia"},rule=judge_super,priority=1, block=True)
_all_only = on_keyword({"##memory"},rule=judge_super,priority=1, block=True)

_blocked=on_message(rule=to_me()&check_repair&judge_unsuper,priority=2, block=True)

_show_code=on_keyword({"code"},rule=to_me(),priority=3, block=True)
_empty_cache = on_keyword({"empty_cache"},rule=to_me(),priority=3, block=True)
_show_cache = on_keyword({"show_cache"},rule=to_me(),priority=3, block=True)
_forget_me=on_keyword({"清除记忆"},rule=to_me(),priority=3, block=True)
_manual=on_keyword({"??","？？"},rule=to_me(),priority=3, block=True)
_forever_mem=on_keyword({"记住"},rule=to_me(),priority=3, block=True)
# _question=on_keyword({"谁","哪个人",},rule=to_me(),priority=3, block=True)

_atall=on_fullmatch(tuple(atall_keywords),priority=4, block=True)
_rnk=on_keyword(set(rnk_keywords),rule=to_me(),priority=4, block=True)
_single=on_keyword(set(single_keywords),rule=to_me(),priority=4, block=True)
_btlview=on_keyword(set(btlview_keywords),rule=to_me(),priority=4, block=True)
_btldetail=on_keyword(set(btldetail_keywords),rule=to_me(),priority=4, block=True)
_heropower=on_keyword(set(heropower_keywords),rule=to_me(),priority=4, block=True)
# _benefit_view=on_keyword(set(btlview_keywords),rule=to_me(),priority=4, block=True)

_tq=on_keyword({"tq",},rule=to_me(),priority=5, block=True)
# _hardworking=on_keyword({"卷","tsg","jxs"},rule=to_me()&judge_name,priority=5, block=True)

_chat=on_message(rule=to_me(),priority=6, block=True)
# HANDLER
@_blocked.handle()
async def f_blocked(event):
    from .zfunc import qid2nick
    log_message("AT UNDER REPAIR")
    await _blocked.finish(Message(f"🤖暂时离线，{qid2nick(event.get_user_id())}请稍等。"))

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
    # try:
    ret=str(eval(rcv_msg))
    # except Exception as e:
    #     ret=str(e)
    await _execute.finish(Message(ret))

@_update_local.handle()
async def f_update_local(event):
    # global confs
    with open('variables_dynamic.json', 'r', encoding='utf-8') as file:
        varia = json.load(file)
    vars(dmc).update(varia)
    # with open('config.yaml', 'r') as file:
    #     confs = yaml.load(file, Loader=yaml.FullLoader)
    load_yesterday(1)
    await _update_local.finish(Message("变量配置已更新"))

@_test.handle()
async def f_test(event):
    rcv_msg=event.get_plaintext()
    await _test.finish(Message(rcv_msg))

@_forward.handle()
async def f_forward(bot,event):
    log_message("FORWARD")
    bot = nonebot.get_bot(confs["QQBot"]["qq_num"])
    snd_msg=event.get_plaintext().replace("##f","")
    log_message("SEND: "+snd_msg)
    await bot.send_group_msg(group_id=confs["QQBot"]["main_num"], message=snd_msg)
@_pure_chat.handle()
async def f_pure_chat(bot,event):
    from .zfunc import ai_parser
    rcv_msg=event.get_plaintext()
    snd_msg=""
    try:
        snd_msg+=ai_parser([rcv_msg],"pure_chat")
    except Exception as e:
        await _pure_chat.send(str(e))
        return
    await _pure_chat.send(snd_msg)
@_repair.handle()
async def f_repair(bot,event):
    if (dmc.repair):
        log_message("REPAIR: 1->0")
        dmc.repair=False
        await _repair.finish(Message("关闭repair"))
    else:
        log_message("REPAIR: 0->1")
        dmc.repair=True
        await _repair.finish(Message("开启repair"))

@_show_code.handle()
async def f_show_code(bot,event):
    await _show_code.send(Message("QQBot code(在浏览器中打开)：👇"))
    await _show_code.send(Message(server_ip)+"/pycode/")

@_group_poke.handle()
async def f_group_poke(bot, event):
    from .zfunc import qid2nick
    from .zfunc import ai_parser
    from .zfunc import get_emoji_url

    if isinstance(event, PokeNotifyEvent):
        if event.target_id == event.self_id: 
            if (not dmc.repair):
                group_id = event.group_id
                user_id = event.user_id
                userqid=event.get_user_id()
                groupqid=event.group_id

                send_type=(random.random()>0.3)
                if send_type:
                    snd_msg=ai_parser([qid2nick(userqid),str(datetime.datetime.now())],"poke")
                else:
                    pic_index=random.randint(1,emoji_amount+1)
                    emoji_url=get_emoji_url(pic_index)
                    snd_msg = MessageSegment.image(emoji_url)

                await _group_poke.send(snd_msg)
                time.sleep(0.3)
                await bot.group_poke(group_id=groupqid, user_id=userqid)
            else:
                await f_blocked(event)
                
@_empty_cache.handle()
async def f_empty_cache(event): # 清空全局记录和用户(自己的)记录
    log_message("CMD: EMPTY_CACHE")
    dmc.ai_memory.clear()
    userqid=event.get_user_id()
    file_path=os.path.join("chats",userqid+".json")
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        pass
    await _empty_cache.finish(Message("成功清空缓存"))

@_show_cache.handle()
async def f_show_cache(event):
    log_message("CMD: SHOW_CACHE")
    await _show_cache.finish(Message("缓存内容："+"".join(dmc.ai_memory)))

@_forget_me.handle()
async def f_forget_me(event): # 清空用户记录和用户(自己的)记忆
    log_message("CMD: EMPTY_ME")
    userqid=event.get_user_id()
    file_path=os.path.join("chats",userqid+".json")
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        pass
    file_path=os.path.join("memory",userqid+".json")
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        pass
    await _forget_me.finish(Message("成功清除记忆"))

@_forever_mem.handle()
async def f_forever_mem(event):
    from .zfile import mem_dumper
    from .zfunc import qid2nick
    
    log_message("CMD: FOREVER")
    userqid=event.get_user_id()
    rcv_msg=event.get_plaintext()
    mem_dumper(userqid,rcv_msg)
    snd_msg=rcv_msg.replace("记住", "").replace("我",qid2nick(userqid)).replace("不会","一定不会").replace("哦","").replace(","," ")
    await _forever_mem.finish(Message("好的，我记住了哦："+snd_msg))

@_manual.handle()
async def f_manual(event):
    log_message("CMD: MANUAL")
    manual_url=f"http://{server_ip}/botmanual/manual.png"
    data =  MessageSegment.text("👇机器人的使用指南\n")+MessageSegment.image(manual_url)
    await _manual.finish(data)

@_super_only.handle()
async def f_super_only(event):
    log_message("CMD: AMNESIA")
    dmc.amnesia=True
    await _super_only.finish(Message("AMNESIA success"))

@_all_only.handle()
async def f_all_only(event):
    log_message("CMD: RECOVERY")
    dmc.amnesia=False
    await _all_only.finish(Message("RECOVERY success"))

@_tq.handle()
async def f_tq(event):
    from .zfunc import ai_parser

    log_message("TQ")
    rcv_msg=event.get_plaintext()
    snd_msg=ai_parser([rcv_msg],"tq")
    await _tq.finish(snd_msg)

# @_hardworking.handle()
# async def f_hardworking(event):
#     from .zfunc import ai_parser

#     rcv_msg=event.get_plaintext()
#     snd_msg=ai_parser([rcv_msg],"hardworking")
#     await _hardworking.finish(snd_msg)
@_atall.handle()
async def f_atall(bot,event):
    from .zfunc import ai_parser

    at_msg=""
    for name,id in qid.items():
        at_msg+=MessageSegment.at(str(id))
    await _atall.send(at_msg)
    urge_msg=ai_parser([str(datetime.datetime.now()),str(namenick),today_news],"urge_game")
    await _atall.send(urge_msg)
    return
@_rnk.handle()
async def f_rnk(bot,event):
    from .zfunc import qid2nick
    from .zfunc import generate_greeting
    from .zfunc import rnk_process
    
    dmc.rank_query_late=datetime.datetime.now()
    rcv_msg=event.get_plaintext()
    debug="#" in rcv_msg
    log_message("VISIT: RANK_FUNCTION")
    userqid=event.get_user_id()
    groupqid=event.group_id
    snd_msg=qid2nick(userqid)+" "+generate_greeting()+"\n"
    await bot.group_poke(group_id=groupqid, user_id=userqid)
    try:
        rnk_info=rnk_process(rcv_msg=rcv_msg,caller=qid2nick(userqid),show_zero=False,show_analyze=True,debug=debug)
        snd_msg+=rnk_info[0]
    except Exception as e:
        await bot.send_group_msg(group_id=confs["QQBot"]["group_num"], message=traceback.format_exc())
        await _rnk.send(str(e))
        return
    await _rnk.send(snd_msg)
    for poked in rnk_info[1]:
        if (poked!="" and poked in idname):
            await bot.group_poke(group_id=groupqid, user_id=qid[idname[poked]])
    return
@_single.handle()
async def f_single(bot,event):
    from .zfunc import qid2nick
    from .zfunc import single_process
    from .zfunc import get_emoji
    from .zfunc import get_emoji_url
    from .zfunc import btldetail_process # 附带解析最后一局

    whether_emoji=(random.random()>0.2)
    userqid=event.get_user_id()
    rcv_msg=event.get_plaintext().replace("我",qid2nick(userqid))
    groupqid=event.group_id
    log_message("VISIT: SINGLEPLAYER_FUNCTION")
    await bot.group_poke(group_id=groupqid, user_id=userqid)
    try:
        sgl_info=single_process(rcv_msg)
    except Exception as e:
        await bot.send_group_msg(group_id=confs["QQBot"]["group_num"], message=traceback.format_exc())
        # await _single.send(traceback.format_exc())
        await _single.send(str(e))
        return
    await _single.send(sgl_info[0])

    whether_emoji=False
    if (whether_emoji):
        emoji_random=random.random()
        if (emoji_random<0.2): pic_index=random.randint(1,emoji_amount+1)
        else: pic_index=get_emoji(sgl_info[0])
    if (sgl_info[2] and whether_emoji):
        emoji_url=get_emoji_url(pic_index)
        emoji_data =  MessageSegment.image(emoji_url)
        await _single.send(emoji_data)

    last_btl_info=None
    for item in dmc.last_request_btllist: 
        # if (abs(int(item['MapType']))<=1):
        last_btl_info=item
    if (last_btl_info): # 存在至少一局
        last_btl_roleid=dmc.last_request_roleid
        btl_info,picpath=btldetail_process(**last_btl_info['Params'],roleid=last_btl_roleid)
        # snd_msg=MessageSegment.text(btl_info)+MessageSegment.image(picpath)
        if (btl_info):
            snd_msg=btl_info
            await _single.send(snd_msg)

    try:
        for poked in sgl_info[1]:
            await bot.group_poke(group_id=groupqid, user_id=qid[idname[poked]])
    except Exception as e:
        pass
        
    return
@_btlview.handle()
async def f_btlview(bot,event):
    def get_last_number_after_dash(text):
        last_dash = text.rfind('-')
        if last_dash != -1:
            after = text[last_dash + 1:]
            # 提取连续数字
            digits = ''.join(filter(str.isdigit, after))
            return int(digits) if digits else None
        return analyze_time_gap

    from .zfunc import view_process
    rcv_msg=event.get_plaintext()
    time_gap=get_last_number_after_dash(rcv_msg)
    snd_msg=view_process(rcv_msg=rcv_msg,time_gap=time_gap)
    await _btlview.send(snd_msg)
    return
@_btldetail.handle()
async def f_btldetail(bot,event):
    from .zfunc import btldetail_process
    last_btl_params=dmc.last_request_btllist[0]['Params']
    linkurl,picpath=btldetail_process(**last_btl_params)
    await _btldetail.send(linkurl)
@_heropower.handle()
async def f_heropower(bot,event):
    from .zfunc import heropower_process
    from .zfunc import qid2nick

    userqid=event.get_user_id()
    rcv_msg=event.get_plaintext().replace("我",qid2nick(userqid))
    
    snd_msg=heropower_process(rcv_msg)
    
    await _heropower.send(snd_msg)
@_chat.handle()
async def f_chat(bot,event):
    from .zfile import chats_loader
    from .zfile import chats_dumper
    from .zfile import mem_loader
    from .zfunc import qid2nick
    from .zfunc import ai_parser
    userqid=event.get_user_id()
    groupqid=event.group_id
    my_temp_msg=chats_loader(userqid)
    perp_msg=mem_loader(userqid)
    rcv_msg=event.get_plaintext().replace("我",qid2nick(userqid))
    rcv_msg+=" "+(str(event.reply.message) if event.reply else "")+" "
    snd_msg=""
    ori_use_mem=dmc.use_mem

    network=False
    if ("&" in rcv_msg): network=True

    if ("nomem" in rcv_msg): 
        dmc.use_mem=False
    try:
        snd_msg+=ai_parser([rcv_msg,my_temp_msg,perp_msg,qid2nick(userqid)],"chat",network)
    except Exception as e:
        await bot.send_group_msg(group_id=confs["QQBot"]["group_num"], message=traceback.format_exc())
        await _rnk.send(str(e))
        return
    dmc.use_mem=ori_use_mem
    chats_dumper(userqid,rcv_msg,snd_msg)
    await _chat.send(snd_msg)
    await bot.group_poke(group_id=groupqid, user_id=userqid)
    return


@scheduler.scheduled_job("cron", hour=bound_hour, minute=bound_minute+5, second=00, id="load_yesterday") # 每日3:30定时加载昨日数据
def load_yesterday(imple_type=0):# 程序重启/定时任务
    from .ztime import time_sul
    from .zfile import readerl
    
    yesterday_date=(time_sul()-datetime.timedelta(days=1)).strftime("%Y-%m-%d") # 将真实时间减去boundary后的日期
    log_message("LOADLIST "+yesterday_date+".json")
    try:
        filename=os.path.join("history",yesterday_date+".json")
        gameinfo=readerl(filename)
        for item in gameinfo:
            dmc.infolast[item['key']]={}
            for key,value in item.items():
                dmc.infolast[item['key']][key]=value
    except Exception as e:
        # await bot.send_group_msg(group_id=confs["QQBot"]["group_num"], message=traceback.format_exc())
        # await bot.send_group_msg(group_id=confs["QQBot"]["main_num"], message="昨日数据导入错误 "+str(e))
        return
    return

@scheduler.scheduled_job("cron", hour=bound_hour, minute=bound_minute-5, second=00, id="dump_today") # 每日3:25定时导出当日数据（预留5分钟导出时间）
async def dump_today():
    from .ztime import time_sul
    from .zfunc import wzry_data
    from .zfile import writerl

    dump_date=time_sul().strftime("%Y-%m-%d") # 因为提早了5分钟，所以时间就是在导出的日期
    log_message("DUMPBEGIN "+dump_date+".json")
    try:
        gameinfo = [wzry_data(key,userlist[key],os.path.join("history", "personal", dump_date, str(userlist[key]) + ".json")) for key in userlist] # dump -- 每个人
    except Exception as e:
        await bot.send_group_msg(group_id=confs["QQBot"]["group_num"], message=traceback.format_exc())
        await bot.send_group_msg(group_id=confs["QQBot"]["main_num"], message="今日数据导出错误 "+str(e))
        return
    filename=os.path.join("history",dump_date+".json")
    writerl(filename,gameinfo)
    log_message("DUMPEND "+dump_date+".json")
    return

@scheduler.scheduled_job("cron", hour=23, minute=30,second=00, id="notify_msg")
async def notify_msg():
    from .zfunc import rnk_process
    # rank_query_now=datetime.datetime.now()
    # rank_query_delta=rank_query_now-dmc.rank_query_late
    # if (rank_query_delta and rank_query_delta.total_seconds()<=5*60):  # 上一次询问时间小于5分钟，就忽略排名推送
    #     return
    log_message("NOTIFY"+str(datetime.date.today()))
    bot = nonebot.get_bot(confs["QQBot"]["qq_num"])
    snd_msg="今日王者战报(每日23:30推送)：\n"
    try:
        snd_msg+=rnk_process(rcv_msg="",caller=None,show_zero=False,show_analyze=True)[0]
    except Exception as e:
        await bot.send_group_msg(group_id=confs["QQBot"]["main_num"], message=traceback.format_exc())
        return
    log_message("SEND: "+snd_msg)
    await bot.send_group_msg(group_id=confs["QQBot"]["main_num"], message=snd_msg)
# @scheduler.scheduled_job("cron", hour=9, minute=00,second=00, id="check_festival") # 每日9:00推送节日祝福
async def check_festival():
    from .ztime import time_r
    from .zfunc import ai_parser
    
    log_message("FESTIVAL")
    snd_msg=""
    bot = nonebot.get_bot(confs["QQBot"]["qq_num"])
    today_date=time_r().strftime("%m-%d")
    ai_back=ai_parser([today_date],"festival")
    snd_msg=ai_back
    if (snd_msg!="NONE"):
        snd_msg="来自🤖的节日祝福：\n"+snd_msg
        log_message("SEND: "+snd_msg)
        await bot.send_group_msg(group_id=confs["QQBot"]["main_num"], message=snd_msg)
@scheduler.scheduled_job("cron",hour=23,minute=6,second=16,id="raise_question")
async def raise_question():
    from .zfunc import ai_parser
    log_message("RAISE_QUESTION")
    bot = nonebot.get_bot(confs["QQBot"]["qq_num"])
    snd_msg=ai_parser([],"raise_question")
    snd_msg+=raise_question_invis_char
    if (snd_msg!="NONE"):
        log_message("SEND: "+snd_msg)
        await bot.send_group_msg(group_id=confs["QQBot"]["group_num"], message=snd_msg)
@scheduler.scheduled_job("cron", hour=7, minute=00,second=00, id="fetch_news")  # 每日7点获取当日新闻，并入提示词
async def fetch_news():
    from .zapi import ark_api
    from .ztime import date_r
    from .zfile import file_exist
    from .zfile import readera
    from .zfile import writera
    log_message("FETCH_NEWS")
    global today_news
    
    current_date = date_r()
    news_dir = "news"
    file_path = os.path.join(news_dir, f"{current_date}.txt")
    
    if file_exist(file_path):
        today_news=readera(file_path)
    else:
        today_news = ark_api(fetch_news_pmpt)
        writera(file_path,today_news)
        print(file_path,today_news)
    return None

def init_fetch_news():
    from .zapi import ark_api
    from .ztime import date_r
    from .zfile import file_exist
    from .zfile import readera
    from .zfile import writera
    log_message("FETCH_NEWS")
    global today_news
    
    current_date = date_r()
    news_dir = "news"
    file_path = os.path.join(news_dir, f"{current_date}.txt")
    
    if file_exist(file_path):
        today_news=readera(file_path)
    else:
        today_news = ark_api(fetch_news_pmpt)
        writera(file_path,today_news)
        print(file_path,today_news)
    return None