
from .zutil import *
from .zstatic import *
from . import zdynamic as dmc
from .utils.message_sender import add_msg
from . import zscheduler

import nonebot
import asyncio
import time
from nonebot import get_plugin_config,require
from nonebot_plugin_apscheduler import scheduler
from nonebot.rule import to_me,Rule
from nonebot.adapters import Message
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11 import Bot, Event, Message,MessageEvent,MessageSegment
from nonebot.adapters import MessageTemplate
from nonebot.adapters.onebot.v11.event import PokeNotifyEvent
from nonebot.plugin import on_message,on_notice,on_request,on_keyword,on_command,on_regex,on_fullmatch
require("nonebot_plugin_apscheduler")
driver = nonebot.get_driver()


async def judge_to_me(event)->bool:
    return event.get_plaintext().startswith("#") or event.get_plaintext().startswith("＃")
async def judge_herostatistics_query(event)->bool:
    from .zfunc import qid2nick
    from .zfunc import extract_name,extract_heroname
    userqid=event.get_user_id()
    rcv_msg=event.get_plaintext().replace("我",qid2nick(userqid))
    if not (rcv_msg.startswith("#") or rcv_msg.startswith("＃")):
        return False
    raw = rcv_msg.lstrip("#＃").strip()

    if "的" not in raw:
        return False
    left, right = raw.split("的", 1)
    left = left.strip()
    right = right.strip()
    if not left or not right:
        return False

    left_ok = False
    if left == "群u":
        left_ok = True
    elif extract_name(left,precise=True):
        left_ok = True
    right_ok = False
    if right == "英雄":
        right_ok = True
    elif extract_heroname(right,precise=True):
        right_ok = True
    return left_ok and right_ok

def get_validated_name(event):
    from .zfunc import qid2nick, extract_name
    userqid = event.get_user_id()
    rcv_msg = event.get_plaintext().replace("我", qid2nick(userqid))
    matching_name = extract_name(rcv_msg)
    if not matching_name:
        add_msg("Name Not Found", event=event)
        return None
    return matching_name

async def judge_super(event)->bool:
    return str(confs["QQBot"]["super_qid"])==str(event.get_user_id())
async def judge_unsuper(event)->bool:
    return str(confs["QQBot"]["super_qid"])!=str(event.get_user_id())
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

_blocked=on_message(rule=Rule(judge_to_me,check_repair,judge_unsuper),priority=2, block=True)

_show_code=on_fullmatch("code",rule=judge_to_me,priority=3, block=True)
_empty_cache = on_keyword({"empty_cache"},rule=judge_to_me,priority=3, block=True)
_show_cache = on_keyword({"show_cache"},rule=judge_to_me,priority=3, block=True)
_forget_me=on_keyword({"清除记忆"},rule=judge_to_me,priority=3, block=True)
_manual=on_fullmatch("#帮助",rule=judge_to_me,priority=3, block=True)
_forever_mem=on_keyword({"记住"},rule=judge_to_me,priority=3, block=True)

_atall=on_fullmatch(tuple(atall_keywords),priority=4, block=True)
_rnk=on_keyword(set(rnk_keywords),rule=judge_to_me,priority=4, block=True)
_single=on_keyword(set(single_keywords),rule=judge_to_me,priority=4, block=True)
_btlview=on_keyword(set(btlview_keywords),rule=judge_to_me,priority=4, block=True)
_btldetail=on_keyword(set(btldetail_keywords),rule=judge_to_me,priority=4, block=True)
_heropower=on_keyword(set(heropower_keywords),rule=judge_to_me,priority=4, block=True)
_history_query=on_keyword({"查询"},rule=judge_to_me,priority=4, block=True)
_herostatistics=on_message(rule=Rule(judge_herostatistics_query),priority=4, block=True)
_todayhero=on_keyword({"今日英雄"},rule=judge_to_me,priority=4, block=True)
_showonline=on_keyword({"在线"},rule=judge_to_me,priority=4, block=True)
_gradeanalyze=on_keyword({"分析"},rule=judge_to_me,priority=4, block=True)
_watchbattle=on_keyword({"ob"},rule=judge_to_me,priority=4, block=True)
_diycode = on_keyword({"diy"},rule=judge_to_me,priority=4, block=True)

_chat=on_message(rule=judge_to_me,priority=6, block=True)
# HANDLER
@_blocked.handle()
async def f_blocked(event):
    from .zfunc import qid2nick
    log_message("AT UNDER REPAIR")
    add_msg(Message(f"🤖暂时离线，{qid2nick(event.get_user_id())}请稍等。"), event=event)
    await _blocked.finish()

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
    add_msg(Message(ret), event=event)
    await _execute.finish()

@_update_local.handle()
async def f_update_local(event):
    # global confs
    with open('variables_dynamic.json', 'r', encoding='utf-8') as file:
        varia = json.load(file)
    vars(dmc).update(varia)
    # with open('config.yaml', 'r') as file:
    #     confs = yaml.load(file, Loader=yaml.FullLoader)
    load_yesterday(1)
    add_msg(Message("变量配置已更新"), event=event)
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
        snd_msg+=ai_parser([rcv_msg],"pure_chat")
    except Exception as e:
        add_msg(str(e), event=event)
        return
    add_msg(snd_msg, event=event)
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
    add_msg("https://github.com/zhdxlz/HOK_QQBot_showcase/", event=event)

@_group_poke.handle()
async def f_group_poke(bot, event):
    from .zfunc import qid2nick
    from .zfunc import ai_parser
    from .zfunc import get_emoji_url
    from .zfunc import coplayer_process
    from .ztime import time_r
    from .ztime import str_to_time,time_to_str
    from .ztime import calc_gap
    from .zfile import file_exist
    from .ztime import add_second
    
    if isinstance(event, PokeNotifyEvent):
        if event.target_id == event.self_id: 
            if (not dmc.repair):
                if (dmc.RTMPStatus):
                    res=dmc.RTMPListener.screenshot()
                    pic_path="/usr/local/nginx/html/wzry_btl_shot/"+str(dmc.RTMPPlayer)+".png"
                    
                    if (res and file_exist(pic_path)): snd_msg = MessageSegment.image(pic_path)
                    else: snd_msg=MessageSegment.text("最快10秒ob一次")
                    add_msg(snd_msg, event=event)
                    return
                elif (dmc.LastBtlMsgStatus and calc_gap(time_r(),str_to_time(dmc.LastBtlMsgTime))<600):
                    dmc.LastBtlMsgStatus=False
                    dmc.LastBtlMsgCoolDownTime=time_to_str(add_second(time_r(),30))
                    try:
                        ret_msg=coplayer_process(**dmc.LastBtlParams,roleid=dmc.LastBtlRoleId)
                    except Exception as e:
                        add_msg(str(e), event=event)
                        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
                        return
                    txt_msg,pic_path=ret_msg
                    snd_msg=MessageSegment.text(txt_msg)+MessageSegment.image(pic_path)
                    add_msg(snd_msg, event=event)
                    return
                elif (time_r()<str_to_time(dmc.LastBtlMsgCoolDownTime)):# 若两条戳一戳时间较近，防止误触发戳一戳消息，直接屏蔽
                    return
                else:
                    user_id = event.user_id
                    userqid=event.get_user_id()
                    try:
                        groupqid=event.group_id
                    except Exception as e:
                        groupqid=None

                    send_type=(random.random()>-1)
                    if send_type:
                        snd_msg=ai_parser([qid2nick(userqid),str(datetime.datetime.now())],"poke")
                    else:
                        pic_index=random.randint(1,emoji_amount+1)
                        emoji_url=get_emoji_url(pic_index)
                        snd_msg = MessageSegment.image(emoji_url)
                    add_msg(snd_msg, event=event)
                    return
                    # time.sleep(0.3)
                    # await bot.group_poke(group_id=groupqid, user_id=userqid)
            else:
                await f_blocked(event)
                return
                
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
    add_msg(Message("成功清空缓存"), event=event)
    await _empty_cache.finish()

@_show_cache.handle()
async def f_show_cache(event):
    log_message("CMD: SHOW_CACHE")
    add_msg(Message("缓存内容："+"".join(dmc.ai_memory)), event=event)
    await _show_cache.finish()

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
    add_msg(Message("成功清除记忆"), event=event)
    await _forget_me.finish()

@_forever_mem.handle()
async def f_forever_mem(event):
    from .zfile import mem_dumper
    from .zfunc import qid2nick
    log_message("CMD: FOREVER")
    userqid=event.get_user_id()
    rcv_msg=event.get_plaintext()
    mem_dumper(userqid,rcv_msg)
    snd_msg=rcv_msg.replace("记住", "").replace("我",qid2nick(userqid)).replace("不会","一定不会").replace("哦","").replace(","," ")
    add_msg(Message("好的，我记住了哦："+snd_msg), event=event)
    await _forever_mem.finish()

@_manual.handle()
async def f_manual(event):
    log_message("CMD: MANUAL")
    add_msg(Message("Code on Github："), event=event)
    add_msg("https://github.com/zhdxlz/HOK_QQBot_showcase/", event=event)

@_super_only.handle()
async def f_super_only(event):
    log_message("CMD: AMNESIA")
    dmc.amnesia=True
    add_msg(Message("AMNESIA success"), event=event)
    await _super_only.finish()

@_all_only.handle()
async def f_all_only(event):
    log_message("CMD: RECOVERY")
    dmc.amnesia=False
    add_msg(Message("RECOVERY success"), event=event)
    await _all_only.finish()

@_atall.handle()
async def f_atall(bot,event):
    from .zfunc import ai_parser

    # at_msg=""
    # for name,id in qid.items():
    #     at_msg+=MessageSegment.at(str(id))
    # await _atall.send(at_msg)
    urge_msg=ai_parser([str(datetime.datetime.now()),str(namenick),dmc.today_news],"urge_game")
    add_msg(urge_msg, event=event)
    return
@_showonline.handle()
async def f_showonline(bot,event):
    from .zfunc import online_process
    snd_msg=online_process()
    add_msg(snd_msg, event=event)
@_rnk.handle()
async def f_rnk(bot,event):
    from .zfunc import qid2nick
    from .zfunc import generate_greeting
    from .zfunc import rnk_process
    from .ztime import time_r
    from .ztime import calc_gap
    
    dmc.rank_query_late=datetime.datetime.now()
    rcv_msg=event.get_plaintext()
    debug="#" in rcv_msg
    log_message("VISIT: RANK_FUNCTION")
    # if (calc_gap(time_r(),dmc.LastAllRequestTime)<180): return # 防止重复冗余请求
    # dmc.LastAllRequestTime=time_r()
    userqid=event.get_user_id()
    try:
        groupqid=event.group_id
    except Exception as e:
        groupqid=None
    snd_msg=qid2nick(userqid)+" "+generate_greeting()+"\n"
    if (groupqid):
        await bot.group_poke(group_id=groupqid, user_id=userqid)
    try:
        rnk_info=rnk_process(rcv_msg=rcv_msg,caller=qid2nick(userqid),show_zero=False,show_analyze=True,debug=debug)
        snd_msg+=rnk_info[0]
    except Exception as e:
        add_msg(str(e), event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
        return
    add_msg(snd_msg, event=event)
    # if (groupqid):
    #     for poked in rnk_info[1]:
    #         if (poked!="" and poked in idname):
    #             await bot.group_poke(group_id=groupqid, user_id=qid[idname[poked]])
    return
@_single.handle()
async def f_single(bot,event):
    log_message("VISIT: SINGLEPLAYER_FUNCTION")
    from .zfunc import qid2nick
    from .zfunc import single_process
    from .zfunc import get_emoji
    from .zfunc import get_emoji_url
    from .zfunc import btldetail_process # 附带解析最后一局
    from .zfunc import check_btl_official_with_matching

    whether_emoji=(random.random()>1)
    userqid=event.get_user_id()
    rcv_msg=event.get_plaintext().replace("我",qid2nick(userqid))
    try:
        groupqid=event.group_id
    except Exception as e:
        groupqid=None
    if (groupqid):
        await bot.group_poke(group_id=groupqid, user_id=userqid)
    try:
        sgl_info=single_process(rcv_msg)
    except Exception as e:
        add_msg(str(e), event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
        # await _single.send(traceback.format_exc())
        return
    if (not sgl_info): return
        
    add_msg(sgl_info[0], event=event)
    
    if (whether_emoji):
        emoji_random=random.random()
        if (emoji_random<0.2): pic_index=random.randint(1,emoji_amount+1)
        else: pic_index=get_emoji(sgl_info[0])
    if (sgl_info[2] and whether_emoji):
        emoji_url=get_emoji_url(pic_index)
        emoji_data =  MessageSegment.image(emoji_url)
        add_msg(emoji_data, event=event)

    if (sgl_info[3]): # 有合法的局
        last_btl_roleid=sgl_info[4]
        try:
            btl_info,picpath=btldetail_process(**sgl_info[3],roleid=last_btl_roleid,gen_image=True)
        except Exception as e:
            add_msg(str(e), event=event)
            add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
            # await _single.send(traceback.format_exc())
            return
        if (btl_info):
            snd_msg=MessageSegment.text(btl_info)+MessageSegment.image(picpath)
            add_msg(snd_msg, event=event)

    # if (groupqid):
    #     for poked in sgl_info[1]:
    #         await bot.group_poke(group_id=groupqid, user_id=qid[idname[poked]])
        
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
    add_msg(snd_msg, event=event)
    return
@_btldetail.handle()
async def f_btldetail(bot,event):
    from .zfunc import btldetail_process
    last_btl_params=dmc.last_request_btllist[0]['Params']
    linkurl,picpath=btldetail_process(**last_btl_params)
    add_msg(linkurl, event=event)
@_heropower.handle()
async def f_heropower(bot,event):
    from .zfunc import heropower_process
    
    matching_name = get_validated_name(event)
    if not matching_name: return

    snd_msg=heropower_process(matching_name)
    
    add_msg(snd_msg, event=event)
@_herostatistics.handle()
async def f_herostatistics(bot,event):
    from .zfunc import (
        single_player_single_hero_process,
        single_player_mult_hero_process,
        mult_player_mult_hero_process,
        mult_player_single_hero_process,
        extract_name,
        extract_heroname,
        qid2nick,
    )

    userqid = event.get_user_id()
    rcv_msg = event.get_plaintext().replace("我", qid2nick(userqid))
    try:
        player_plural=False
        hero_plural=False
        rcv_msg = rcv_msg.lstrip("#＃").strip()
        rcv_left, rcv_right = rcv_msg.split("的", 1)
        if ("群u" in rcv_left): player_plural=True
        else: matching_name = extract_name(rcv_left,precise=True)
        if ("英雄" in rcv_right): hero_plural=True
        else: heroid, heroname = extract_heroname(rcv_right,precise=True)

        try:
            if (not player_plural and not hero_plural):
                snd_msg = single_player_single_hero_process(matching_name, heroid, heroname)
            elif (not player_plural and hero_plural):
                snd_msg = single_player_mult_hero_process(matching_name)
            elif (player_plural and not hero_plural):
                snd_msg = mult_player_single_hero_process(heroid,heroname)
            else:
                snd_msg = mult_player_mult_hero_process()
        except Exception as e:
            snd_msg = str(e)

        add_msg(snd_msg, event=event)
    except Exception as e:
        add_msg(str(e), event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
@_todayhero.handle()
async def f_todayhero(bot,event):
    from .zfunc import qid2realname
    from .zfunc import todayhero_process

    userqid=event.get_user_id()
    realname=qid2realname(userqid)
    rcv_msg=event.get_plaintext()
    if ("的" in rcv_msg): snd_msg="只能查询自己的今日英雄"
    else:
        ai_comment=False if ("$" in rcv_msg) else True
        ignore_limit=True if ("%" in rcv_msg) else False
        appoint_realname=True if ("~" in rcv_msg) else False
        if (appoint_realname):
            matching_name = get_validated_name(event)
            if not matching_name: return
            realname = matching_name
        try:
            hero_msg,play_reason,pic_path=todayhero_process(realname,ignore_limit,ai_comment)
        except Exception as e:
            add_msg(str(e), event=event)
            add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
            return
        snd_msg=MessageSegment.text(hero_msg)+MessageSegment.image(pic_path)+MessageSegment.text(play_reason)

    add_msg(snd_msg, event=event)
    
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
    from .zfunc import gradeanalyze_process

    matching_name = get_validated_name(event)
    if not matching_name: return

    img_url,analyze_msg=gradeanalyze_process(matching_name)
    # print(img_url)
    # await _gradeanalyze.send(MessageSegment.image(img_url)+MessageSegment.text(analyze_msg))
    add_msg(MessageSegment.image(img_url), event=event)
@_watchbattle.handle()
async def f_watchbattle(bot,event):
    from .zfunc import watchbattle_process
    from .zfile import file_exist

    matching_name = get_validated_name(event)
    if not matching_name: return

    img_url,analyze_msg=watchbattle_process(matching_name)
    # print(img_url)
    # await _gradeanalyze.send(MessageSegment.image(img_url)+MessageSegment.text(analyze_msg))
    if (file_exist(img_url)):
        add_msg(MessageSegment.image(img_url), event=event)

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

@_history_query.handle()
async def f_history_query(event: Event):
    from .zfunc import history_query_handler, qid2nick, extract_name, btldetail_process, fetch_battle, create_website
    import traceback
    import json
    from .zfile import writerl
    import hashlib

    userqid = event.get_user_id()
    rcv_msg = event.get_plaintext().replace("我", qid2nick(userqid))
    

    try:
        res = await history_query_handler(rcv_msg)
        if isinstance(res, str):
            add_msg(res, event=event)
            return
            
        query_target, matches, query_desc, stats = res
        prefix = f"🔍查询条件：{query_desc}\n\n"

        if isinstance(matches, str):
            add_msg(prefix + matches, event=event)
            return
        
        if stats:
            total = stats.get('total', 0)
            prefix += f"📊 统计概览 ({total}场)：\n"
            prefix += f"胜率: {stats.get('win_rate', 0):.1f}% ({stats.get('wins', 0)}胜{total - stats.get('wins', 0)}负)\n"
            prefix += f"平均评分: {stats.get('avg_grade', 0):.1f}\n"
            prefix += f"场均KDA: {stats.get('total_k',0)/total:.1f}/{stats.get('total_d',0)/total:.1f}/{stats.get('total_a',0)/total:.1f} ({stats.get('avg_kda', 0):.2f})\n\n"

        if len(matches) == 1:
            detail, realname = matches[0]
            roleid = roleidlist[realname]
            try:
                # 调用btldetail_process解析该局详情，逻辑参考其他单局解析处
                btl_info, picpath = btldetail_process(**detail['Params'], roleid=roleid, gen_image=True,individual_show=True)
                snd_msg = MessageSegment.text(prefix + btl_info) + MessageSegment.image(picpath)
                add_msg(snd_msg, event=event)
            except Exception as e:
                add_msg(prefix + f"解析局内详情异常: {str(e)}", event=event)
                add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
        elif len(matches) > 1:
            packed_data = []
            now_time = time.strftime("%Y-%m-%d %H:%M:%S")
            exact_now_time = str(round(time.time()*1000000))
            for detail, realname in matches:
                gameseq = detail['GameSeq']
                roleid = roleidlist[realname]
                battle_res = fetch_battle(gameseq)
                
                nickname = ""
                if battle_res:
                    for role in battle_res.get('redRoles', []) + battle_res.get('blueRoles', []):
                        if int(role['basicInfo']['roleId']) == int(roleid):
                            nickname = role['basicInfo']['roleName']
                            break
                            
                info = {
                    "realname": realname,
                    "Nickname": nickname,
                    "roleId": roleid,
                    "GameTime": detail.get("GameTime_Timestamp"),
                    "Duration": detail.get("Duration_Second"),
                    "HeroName": detail.get("HeroName"),
                    "MapName": detail.get("MapName"),
                    "KillCnt": detail.get('KillCnt'),
                    "DeadCnt": detail.get('DeadCnt'),
                    "AssistCnt": detail.get('AssistCnt'),
                    "Result": detail.get("Result"),
                    "GameGrade": detail.get("GameGrade"),
                    "GameSeq":gameseq,
                    "Others": detail.get("Others")
                }
                packed_data.append(info)
                
            filename_hashed = hashlib.sha256(exact_now_time.encode()).hexdigest()[:16]
            filepath = os.path.join(nginx_path, "wzry_history", filename_hashed + ".json")
            writerl(filepath,packed_data)
            website_link = create_website(json.dumps({"filename": filename_hashed, "caller": query_target, "time": now_time}), "query_select")
            add_msg(prefix + f"找到 {len(matches)} 局符合条件的战绩，点击链接查看详情：(视角随机)\n" + website_link, event=event)
        else:
            add_msg(prefix + "未找到符合条件的战绩。", event=event)
    except Exception as e:
        add_msg(f"查询错误: {str(e)}", event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])

@_chat.handle()
async def f_chat(bot,event):
    from .zfile import chats_loader
    from .zfile import chats_dumper
    from .zfile import mem_loader
    from .zfunc import qid2nick
    from .zfunc import ai_parser
    
    userqid=event.get_user_id()
    
    try:
        groupqid=event.group_id
    except Exception as e:
        groupqid=None
        
    if (groupqid):
        await bot.group_poke(group_id=groupqid, user_id=userqid)
    my_temp_msg=chats_loader(userqid)
    perp_msg=mem_loader(userqid)
    rcv_msg=event.get_plaintext().replace("我",qid2nick(userqid))
    
    for k in sorted(common_expr.keys(), key=len, reverse=True):
        rcv_msg = re.sub(re.escape(k), common_expr[k], rcv_msg)
    
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
        add_msg(str(e), event=event)
        add_msg(traceback.format_exc(), msg_type="private", to_id=confs["QQBot"]["super_qid"])
        return
    dmc.use_mem=ori_use_mem
    chats_dumper(userqid,rcv_msg,snd_msg)
    add_msg(snd_msg, event=event)
    return
