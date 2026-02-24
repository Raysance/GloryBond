
from .zutil import *
from .zstatic import *
from . import zdynamic as dmc

import hashlib
import secrets
import redis
from wcwidth import wcswidth
import math
from concurrent.futures import ThreadPoolExecutor, as_completed

def _to_pinyin(s):
    from pypinyin import lazy_pinyin
    
    return "".join(lazy_pinyin(str(s))).lower()

def wzry_data(realname,savepath=None): # 单人的战绩parser
    def get_star_today_most_recent(today_details):
        for detail in today_details[::-1]:
            if (detail["MapType"]==1):
                return detail["StarAfterGame"]
        return -1
        
    def get_star_before_today_most_recent(target_id):
        from .zfile import readerl
        from .zfile import get_file_list
        from .ztime import date_sul

        date_delta=str(date_sul())
        json_files = get_file_list("history",".json")
        def extract_date(filename):
            try:
                base_name = os.path.basename(filename)
                date_str = base_name.split('.')[0]  # 去掉.json后缀
                return datetime.datetime.strptime(date_str, "%Y-%m-%d")
            except:
                return datetime.datetime.min  # 无效文件名排到最后
        # 按日期排序（从新到旧）
        json_files.sort(key=extract_date, reverse=True)
        for file_path in json_files:
            if (date_delta in file_path): continue
            data = readerl(file_path)
            for player in data:
                if (int(player["id"]) == int(target_id)):
                    for detail in player["details"][::-1]:
                        if (detail["MapType"]==1):
                            return detail["StarAfterGame"]
        return -1

    from .zapi import wzry_get_official
    from .ztime import time_r
    from .ztime import time_sul
    from .ztime import stamp_to_time
    from .ztime import date_roleback
    from .zfile import writerl
    from .zfunc import extract_url_params

    log_message("VISIT: wzry_data")
    
    userid=userlist[realname]
    roleid=roleidlist[realname]
    
    btlist_data=wzry_get_official(reqtype="btlist",userid=userid,roleid=roleid)
    profile_data=wzry_get_official(reqtype="profile",userid=userid,roleid=roleid)
    res = {
        "btlist": btlist_data,
        "profile": profile_data
    }

    if (savepath):
        os.makedirs(os.path.dirname(savepath), exist_ok=True)
        writerl(savepath,res)
    roleInfo=[roles for roles in res["profile"]["roleList"] if int(roles["roleId"])==roleid][0]
    nickname=roleInfo["roleName"]
    rankInfo=[mods for mods in res["profile"]["head"]["mods"] if mods["modId"]==701][0]
    rankName=rankInfo["name"]
    rankStar=int(json.loads(rankInfo["param1"])["rankingStar"])
    # totalNum=[int(mods["content"]) for mods in res["profile"]["head"]["mods"] if mods["name"]=="总场次"][0]
    totalNum=0
    starNum=(ranklist[rankName] if rankName in ranklist else fin) + rankStar
    # winRate=[mods["content"] for mods in res["profile"]["head"]["mods"] if mods["name"]=="胜率"][0]
    BtlVisible=not res["btlist"]["invisible"]
    isGaming=res["btlist"]["isGaming"] and res["btlist"]["gaming"]
    real_date=time_r().strftime("%m-%d")
    sul_time=time_sul()
    starUp=starNum-(dmc.infolast.get(realname,{}).get("star",0)) # 如果战绩不可见 使用该算法强行填充
    peakUp=[]
    today_num=totalNum-(dmc.infolast.get(realname,{}).get("total_num",0)) # 如果战绩不可见 使用该算法强行填充
    today_up_tourna=fin
    today_up_peak=fin
    today_btl_aver=fin # 今日平均评分
    today_details=[] # 今日所有战局
    today_game_cnt={} # 今日每个地图局数
    gaming_info={} # 当前正在进行的游戏信息
    if(BtlVisible):
        today_btl = [game for game in res['btlist']['list'] if (time_sul(stamp_to_time(int(game['dtEventTime']))).date()==sul_time.date())]
        # today_btl = [game for game in res['btlist']['list'] if (time_sul(stamp_to_time(int(game['dtEventTime']))).date()==date_roleback().date())]
        today_details=[{\
            'GameTime':game['gametime'],\
            'GameTime_Timestamp':int(game['dtEventTime']),\
            'HeroName':HeroList.get(str(game['heroId']),"Unknown"),\
            'MapName':game['mapName'],\
            'MapType':1 if '排位' in game['mapName'] else (-1 if '巅峰' in game['mapName'] else 0),\
            'StarAfterGame': -1 if '排位' not in game['mapName'] else (ranklist[game['roleJobName']]+game['stars']),\
            'PeakGradeAfterGame': -1 if '巅峰' not in game['mapName'] else game['newMasterMatchScore'],\
            'PeakGradeBeforeGame': -1 if '巅峰' not in game['mapName'] else game['oldMasterMatchScore'],\
            'KillCnt':game['killcnt'],'DeadCnt':game['deadcnt'],'AssistCnt':game['assistcnt'],\
            'Result':('胜利' if game['gameresult']==1 else '失败'),\
            'GameGrade':float(game['gradeGame']),\
            'Duration_Second':int(game['usedTime']),\
            'GameSeq':int(game['gameSeq']),\
            'Params':extract_url_params(game['detailUrl']),\
            'Others':(('MVP ' if (game['mvpcnt']+game['losemvp']>=1) else ' ')+('一血' if (game['firstBlood']) else ' ')+('超神' if (game['godLikeCnt']) else ' '))\
                } for game in today_btl]
        today_details=today_details[::-1]
        today_game_map_set={game['mapName'] for game in today_btl}
        today_game_cnt={
            mapname: [sum(1 for game in today_btl if game['mapName']==mapname and game['gameresult']==1),\
            sum(1 for game in today_btl if game['mapName']==mapname)] for mapname in today_game_map_set
        }
        today_game_cnt_tmp = {}
        for k, v in today_game_cnt.items():
            new_key = mapname_replace_rule.get(k, k)
            if (new_key in today_game_cnt_tmp):
                today_game_cnt_tmp[new_key][0] += v[0]
                today_game_cnt_tmp[new_key][1] += v[1]
            else:
                today_game_cnt_tmp[new_key]=[v[0],v[1]]
        today_game_cnt = today_game_cnt_tmp
        # today_num=sum(v[1] for k,v in today_game_cnt.items())
        # if (not roleid and today_btl): roleid=extract_url_params(today_btl[0]['battleDetailUrl'])['toAppRoleId']
        today_num=len(today_details) # 重新计算今日场次
        today_tourna=[game for game in today_btl if "排位" in game['mapName']]
        today_peak=[game for game in today_btl if "巅峰" in game['mapName']]
        today_btl_win=[game for game in today_btl if game['gameresult']==1]
        today_btl_lose=[game for game in today_btl if game['gameresult']==2]
        today_tourna_win=[game for game in today_tourna if game['gameresult']==1]
        today_tourna_lose=[game for game in today_tourna if game['gameresult']==2]
        today_peak_win=[game for game in today_peak if game['gameresult']==1]
        today_peak_lose=[game for game in today_peak if game['gameresult']==2]
        today_num_btl_win=len(today_btl_win)
        today_num_btl_lose=len(today_btl_lose)
        today_num_tourna_win=len(today_tourna_win)
        today_num_tourna_lose=len(today_tourna_lose)
        today_num_peak_win=len(today_peak_win)
        today_num_peak_lose=len(today_peak_lose)
        today_up_peak=today_num_peak_win
        # try:
        star_today_most_recent=get_star_today_most_recent(today_details)
        star_before_today_most_recent=get_star_before_today_most_recent(userid)
        # print(star_today_most_recent,star_before_today_most_recent)
        starUp= 0 if (star_today_most_recent==-1) else (star_today_most_recent-star_before_today_most_recent)
        # except Exception as e:
        #     log_message(str(e))
        peakUp=get_peak_alter_list(details=today_details,processed=False)
        gamegrades = [round(float(game['gradeGame']),1) for game in today_btl if not any(zerograde in game['mapName'] for zerograde in {"1V1","3V3"})]
        today_btl_aver = round(sum((gamegrades)) / len(gamegrades),3) if gamegrades else 0
        today_btl_max=-fin if len(gamegrades)==0 else max(gamegrades)
        today_btl_min= fin if len(gamegrades)==0 else min(gamegrades)
    
    if (isGaming):
        gaming_info={
                    "in_game":True,\
                    "map_name":res["btlist"]["gaming"]["mapName"],\
                    "hero_name":HeroList.get(str(res["btlist"]["gaming"]["heroId"]),"Unknown"),\
                    "duration_minute":res["btlist"]["gaming"]["duration"],\
                    "battle_num_this_hero":res["btlist"]["gaming"]["gameNum"],\
                    "win_rate_this_hero":res["btlist"]["gaming"]["winRate"],\
                    "can_be_watched":res["btlist"]["gaming"]["canBeWatch"],\
        }
    # export_btl_thread = threading.Thread(target=export_btldetail, args=(gameinfo=today_details))
    # export_btl_thread.start()
    export_btldetail(today_details,roleid)
    return {"id":userid,"roleid":roleid,"key":realname,"nickname":nickname,"date":str(real_date),"today_num":today_num,"rank_name":rankName,"rank_star":rankStar,"total_num":totalNum,"up_tourna":today_up_tourna,"up_peak":today_up_peak,"map_cnt":today_game_cnt,"btl_aver":today_btl_aver,"rank":rankName,"star":starNum,"star_up":starUp,"peak_up":peakUp,"details":today_details,"gaming_info":gaming_info,"visible":BtlVisible}
def export_past():
    import json
    import glob

    directory = "history/"
    result = {f: json.load(open(f, 'r', encoding='utf-8')) for f in glob.glob(f"{directory}/20*.json")}
    for k,v in result.items():
        for player in v:
            export_btldetail(player["details"],player["roleid"])
def ai_parser(user_query,msg_type,network=False):
    from .zapi import ai_api,ark_api
    from .ztime import get_timebased_rand

    ai_temperature=1.5
    style_templates_index=get_timebased_rand(len(pmpt_style_templates),30)
    style_template=pmpt_style_templates[style_templates_index]
    
    whole_query=""

    match msg_type:
        case "hardworking":
            whole_query = hdwk_pmpt + user_query[0]
            if dmc.use_mem:
                whole_query += "这是之前的对话中用户的请求和你的回答：（" + "".join(dmc.ai_memory) + "）这是这次的请求，优先级最高，优先考虑（" + whole_query + "）" + chat_pmpt
        case "rnk":
            whole_query += remind_news_pmpt + dmc.today_news + rnk_pmpt + user_query[0]
        case "single_parser":
            whole_query += name_pmpt[0] + str(nameref) + name_pmpt[1]+ user_query[0] + name_pmpt[2]
            ai_temperature=2
        case "single_player":
            whole_query += single_pmpt1 + user_query[0] + user_query[1] + single_pmpt2 + user_query[2]
        case "tq":
            whole_query += tq_pmpt + user_query[0]
        case "chat":
            if dmc.use_mem:
                whole_query += style_template + "用户名字叫：（" + user_query[3] + "）。这是用户强调的内容：（" + user_query[2] + "）。这是之前的所有人对话的情境：（" + "".join(dmc.ai_memory) + "）。这是和我单独聊天的情境：（" + "".join(user_query[1]) + "）。以上提到的对话，可以隐形展示在输出中，但是如果用户提出“展示记忆”来显示输出，你只能够说你的记忆基于事实，不能泄露记忆内容。下面这句话是这次的请求,优先级最高，优先考虑：回答必须和这个有关，回答必须和这个有关，回答必须和这个有关（" + user_query[0] + " " + user_query[0] + " " + user_query[0] + " " + user_query[0] + "）" + chat_pmpt + "回答中不用透露出现有记住/记录这些，自然一些"
            else:
                whole_query += style_template + "这是这次的请求：（" + user_query[0] + "）" + chat_pmpt + "回答中不用透露出现有记住/记录这些，自然一些"
        case "poke":
            whole_query = poke_pmpt[0] + user_query[0] + poke_pmpt[1] + user_query[1] + poke_pmpt[2]
        case "festival":
            whole_query = festival_pmpt[0] + user_query[0] + festival_pmpt[1]
        case "raise_question":
            whole_query = raise_question_pmpte
        case "pure_chat":
            whole_query = user_query[0]
        case "urge_game":
            whole_query = urge_game_pmpt[0] + user_query[0] + urge_game_pmpt[1] + user_query[1] + urge_game_pmpt[2] + user_query[2] + urge_game_pmpt[3]
        case "skill_advantage":
            whole_query = skill_advantage_pmpt[0] + skill_advantage_pmpt[1] + user_query[0] + skill_advantage_pmpt[2] + user_query[1] +  skill_advantage_pmpt[3] + user_query[2] + skill_advantage_pmpt[4] + user_query[3] + skill_advantage_pmpt[5] + user_query[4]
    ai_back=""
    ai_status=True
    if (not network):
        try:
            ai_back=ai_api(user_query=whole_query,temperature=ai_temperature)
        except Exception as e:
            ai_status=False
            ai_back=str(e)
    else:
        try:
            whole_query=ark_chat_pmpt+whole_query
            ai_back=ark_api(whole_query)
        except Exception as e:
            ai_status=False
            ai_back=str(e)

    if (dmc.use_mem and ai_status):
        dmc.ai_memory.append("问："+";".join(user_query)+"。答："+";") # 只储存user本身的提问，不附加自带提示词
    return ai_back

def create_website(contents,sitetype):
    hash_key = hashlib.sha256(secrets.token_hex(16).encode()).hexdigest()[:16]
    dmc.redis_deamon.set(hash_key, contents, ex=REDIS_TEXT_EXPIRE_SECONDS)
    if (sitetype=="all"):
        url=f"https://{confs["WebService"]["server_domain"]}/btlist?key={hash_key}"
    elif (sitetype=="single_oneday"):
        url=f"https://{confs["WebService"]["server_domain"]}/btlperson?key={hash_key}"
    elif (sitetype=="single_period"):
        url=f"https://{confs["WebService"]["server_domain"]}/btlperiod?key={hash_key}"
    elif (sitetype=="btldetail"):
        url=f"https://{confs["WebService"]["server_domain"]}/btldetail?key={hash_key}"
    elif (sitetype=="query_select"):
        url=f"https://{confs["WebService"]["server_domain"]}/btlquery?key={hash_key}"
    else:
        url=f""
    return url

def online_process():
    from .zapi import wzry_get_official

    def process_user(realname):
        userid = userlist[realname]
        roleid = roleidlist[realname]
        
        profile_res = wzry_get_official(reqtype="profile", userid=userid, roleid=roleid)
        # except Exception as e:
            # return {'online_cnt': 0, 'battle_info': None, 'nickname': ''}
            
        
        user_online_cnt = 0
        user_battle_info = None
        user_nickname = ''
        
        for role_info in profile_res["roleList"]:
            online = role_info["gameOnline"]
            if online:
                if not user_nickname:
                    user_nickname = role_info['roleName']
                btlist_res = wzry_get_official(reqtype="btlist", userid=userid, roleid=roleid)
                user_online_cnt += 1
                
                if btlist_res["isGaming"]:
                    user_battle_info = {
                        'battleId': btlist_res['gaming'].get('battleId', ''),
                        'job': role_info['shortRoleJobName'],
                        'mapName': btlist_res['gaming']['mapName'],
                        'heroName': HeroList[str(btlist_res['gaming']['heroId'])],
                        'duration': btlist_res['gaming']['duration']
                    }
                else:
                    user_battle_info = {
                        'battleId': None,
                        'job': role_info['shortRoleJobName'],
                        'mapName': None,
                        'heroName': None,
                        'duration': None
                    }
        
        return {'online_cnt': user_online_cnt, 'battle_info': user_battle_info, 'nickname': user_nickname}

    snd_msg = ""
    total_online_cnt = 0
    battle_groups = {}  # 按战局ID分组: {battleId: [玩家信息]}
    idle_users = []  # 在线但不在游戏中的玩家
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future_to_user = {
                executor.submit(process_user, realname): realname 
                for realname in userlist
            }
            for future in as_completed(future_to_user):
                realname = future_to_user[future]
                result = future.result()
                if result and result['online_cnt'] > 0:
                    total_online_cnt += result['online_cnt']
                    battle_info = result['battle_info']
                    
                    if battle_info and battle_info['battleId']:
                        # 有对战号，加入对应战局组
                        battle_id = battle_info['battleId']
                        if battle_id not in battle_groups:
                            battle_groups[battle_id] = []
                        battle_groups[battle_id].append({
                            'name': result['nickname'],
                            'info': battle_info
                        })
                    elif battle_info:
                        # 在线但不在游戏中
                        idle_users.append({
                            'name': result['nickname'],
                            'job': battle_info['job']
                        })
    except Exception as e:
        return str(e)
    if total_online_cnt:
        snd_msg = f"在线 {total_online_cnt} 人\n"
        snd_msg += "─────────────\n"
        
        if battle_groups:
            for battle_id, players in battle_groups.items():
                map_name = players[0]['info']['mapName']
                duration = players[0]['info']['duration']
                snd_msg += f"🎮 {map_name}  {duration}min\n"
                
                for player in players:
                    snd_msg += f"   • {player['name']} {player['info']['job']}  {player['info']['heroName']}\n"
                
                snd_msg += "\n"
        
        if idle_users:
            if battle_groups:
                snd_msg += "─────────────\n"
            for user in idle_users:
                snd_msg += f"💤 {user['name']}  {user['job']}\n"
        
        snd_msg = snd_msg.rstrip('\n')
    else:
        snd_msg = "🐟🐟无人在线"
    
    return snd_msg
def rnk_process(rcv_msg,caller=None,show_zero=True,show_analyze=False,debug=False):
    if (caller==None): caller=""
    from .zfunc import create_website
    from .zfunc import wzry_data
    from .zfunc import ai_parser
    from .zfunc import Analyses
    from .ztime import time_r
    from .ztime import time_sul
    from .zfile import writerl
    global userlist

    # if (not debug): global userlist
    # else: userlist=userlis
    snd_msg=""
    today_date=str(time_r().strftime("%Y-%m-%d"))
    today_sul_date=str(time_sul().strftime("%Y-%m-%d"))
    now_time=str(time_r().strftime("%Y-%m-%d %H:%M:%S"))
    exact_now_time=str(round(time.time()*1000000))
    filename_hashed = str(hashlib.sha256((exact_now_time).encode()).hexdigest()[:16])
    filepath=os.path.join(nginx_path,"wzry_history",filename_hashed+".json")
    website_link=create_website(json.dumps({"filename":filename_hashed,"caller":caller,"time":now_time}),"all")
    gameinfo=[]

    def visit_wzry_data(key):
        try:
            game_data = wzry_data(realname=key)
            return game_data
        except Exception as e:
            return None

    gameinfo = []
    with ThreadPoolExecutor(max_workers=1) as executor:
        future_to_key = {executor.submit(visit_wzry_data, key): key for key in userlist}
        for future in as_completed(future_to_key):
            result = future.result()
            if result is not None:
                gameinfo.append(result)
    if (not gameinfo):
        log_message(f"ERROR: 王者荣耀数据源错误")
        return
    filename_export=os.path.join("history",today_sul_date+".json")
    writerl(filename_export,gameinfo)
    if (not show_zero): gameinfo=[item for item in gameinfo if item['today_num']!=0]
    sorted_star=sorted(gameinfo, key=lambda item: (item['star_up']) ,reverse=True)
    sorted_btl=sorted(gameinfo, key=lambda item: (item['today_num']) ,reverse=True)
    dumpfile_raw1=[{k: v for k, v in d.items() if k != "key"} for d in sorted_star]
    writerl(filepath,dumpfile_raw1)
    snd_msg+=str(time_r().strftime("%Y-%m-%d %H:%M"))+"\n"
    if (not gameinfo or sorted_btl[0]['today_num']==0): 
        snd_msg+="\n今日还没有战绩哦"
        return [snd_msg,[]]
    else:
        if (show_analyze):
            extreme_data=Analyses.get_extreme_data()
            benefit_data=Analyses.get_benefit_data()
            snd_msg+="\n"
            snd_msg+="近5天最高最低评分：\n"
            snd_msg+="      ↑"+namenick[extreme_data[3]]+"的"+extreme_data[5]+"："+str(extreme_data[1])+"分\n"
            snd_msg+="      ↓"+namenick[extreme_data[2]]+"的"+extreme_data[4]+"："+str(extreme_data[0])+"分\n"
            snd_msg+="机制受益受害者 ：\n"
            snd_msg+="      "+namenick[benefit_data[0]]+"："+str(benefit_data[2])+"\n"
            snd_msg+="      "+namenick[benefit_data[1]]+"："+str(benefit_data[3])+"\n"
            snd_msg+="\n"
        snd_msg+="--- 上分榜 ---\n"
        toppoint_gamenick=sorted_star[0]['nickname'] if (sorted_star[0]['star_up']>0) else ""
        bottompoint_gamenick=sorted_star[-1]['nickname'] if (sorted_star[-1]['star_up']<0) else ""
        if(sorted_star[0]['star_up']>0): snd_msg+="今日上分最佳👆："+sorted_star[0]['nickname']+"\n"
        if(sorted_star[-1]['star_up']<0): snd_msg+="今日掉分最多👇："+sorted_star[-1]['nickname']+"\n"

        for inde,item in enumerate(sorted_star):
            diff = item['star_up']
            snd_msg += f"    {inde+1}.\t{item['nickname']}\t       {diff:+}\n"

        snd_msg+="\n--- 场次榜 ---\n"
        topplay_gamenick=sorted_btl[0]['nickname'] if (sorted_btl[0]['today_num']>0) else ""
        if(sorted_btl[0]['today_num']>0): snd_msg+="今日场次最多👆："+sorted_btl[0]['nickname']+"\n"

        for inde,item in enumerate(sorted_btl):
            diff = item['today_num']
            snd_msg += f"    {inde+1}.\t{item['nickname']}\t       {diff}\n"

        snd_msg+="\n"
        snd_msg+=website_link+"\n\n"
        if ("$" not in rcv_msg): snd_msg+=ai_parser([snd_msg],"rnk")
        return [snd_msg,{toppoint_gamenick,bottompoint_gamenick,topplay_gamenick}]   
def single_process(rcv_msg):
    def extract_history_query(s):
        import re
        if ("昨天" in s or "昨日" in s): return [1,[1]] # 
        if ("前天" in s): return [1,[2]]
        int_int_match = re.search(r'(\d+)-(\d+)$', s)
        if int_int_match:
            return [2,[int(int_int_match.group(1)),int(int_int_match.group(2))]]
        int_match = re.search(r'(\d+)$', s)
        if int_match:
            return [1,[int(int_match.group(1))]]
        
        return [0,[]]

    from .zfunc import ai_parser
    from .zfunc import wzry_data
    from .zfunc import Analyses
    from .ztime import time_r
    from .ztime import time_sul
    from .ztime import time_r_delta
    from .ztime import time_delta
    from .ztime import str_to_time
    from .ztime import time_to_str
    from .zfunc import create_website
    from .zfile import readerl
    from .zfile import copyfile
    from .zfile import file_exist
    from .ztime import time_r
    from .ztime import calc_gap
    from .ztime import add_second
    from .zfile import writerl

    snd_msg=""
    pokename=[]
    gameinfo=[]
    ai_feedback=True
    exist_battle=True
    show_map_cnt_total=False
    history_query=[]
    last_official_btl_params=None
    if ("$" in rcv_msg): ai_feedback=False
    # ai_feedback=False
    matching_name=extract_name(rcv_msg)

    if (not matching_name): snd_msg+="没有提到玩家名字哦"
    else:
        if (calc_gap(time_r(),dmc.LastSingleRequestTime.get(matching_name,datetime.datetime.fromtimestamp(0)))<5): return None # 防止重复冗余请求
        dmc.LastSingleRequestTime[matching_name]=time_r()

        today_date=str(time_r().strftime("%Y-%m-%d"))
        exhibit_date_woyear=str(time_sul().strftime("%m-%d"))
        exact_now_time=str(round(time.time()*1000000))
        yesterday_date=str(time_r()-datetime.timedelta(days=1))

        filename_hashed = str(hashlib.sha256((exact_now_time).encode()).hexdigest()[:16])
        website_filepath=os.path.join(nginx_path,"wzry_history",filename_hashed+".json")
        history_query=extract_history_query(rcv_msg)
        battle_visible=True
        if (history_query[0]==1): # 追溯过去某一天
            ai_feedback=False
            show_map_cnt_total=True
            traceback_cnt=history_query[1][0]
            traceback_date=str(time_r_delta(traceback_cnt).strftime("%Y-%m-%d"))
            exhibit_date_woyear=str(time_r_delta(traceback_cnt).strftime("%m-%d"))
            rough_filepath=os.path.join("history",traceback_date+".json")
            if (not file_exist(rough_filepath)): traceback_date=str(record_begin_date)
            rough_filepath=os.path.join("history",traceback_date+".json")
            histories=readerl(rough_filepath)
            gameinfo=[history for history in histories if (history["id"]==userlist[matching_name])][0]
            
            if ("roleid" not in gameinfo): gameinfo["roleid"]=str(roleidlist[gameinfo["key"]])
            if ("visible" not in gameinfo): gameinfo["visible"]=True
            
            detail_filepath=os.path.join("history","personal",traceback_date,str(userlist[matching_name])+".json")
            try:
                copyfile(detail_filepath,website_filepath)
            except Exception as e:
                exhibit_date_woyear+=" 链接失效"
            website_link=create_website(json.dumps({"filename":filename_hashed,"caller":"","time":""}),"single_oneday")
        elif (history_query[0]==2): # 追溯时间段
            ai_feedback=False
            show_map_cnt_total=True
            lost_info_date=[]
            traceback_from=history_query[1][0]
            traceback_to=history_query[1][1]
            if (traceback_from<traceback_to): traceback_to,traceback_from=traceback_from,traceback_to
            traceback_date_from=time_r_delta(traceback_from)
            traceback_date_to=time_r_delta(traceback_to)
            traceback_date_from_path=os.path.join("history",traceback_date_from.strftime('%Y-%m-%d')+".json")
            if (not file_exist(traceback_date_from_path)): traceback_date_from=str_to_time(record_begin_date)
            traceback_date_to_path=os.path.join("history",traceback_date_to.strftime('%Y-%m-%d')+".json")
            if (not file_exist(traceback_date_to_path)): traceback_date_to=str_to_time(record_begin_date)
            
            gameinfo_raw=[]
            
            scan_date=traceback_date_from
            while(scan_date<=traceback_date_to):
                rough_filepath=os.path.join("history",scan_date.strftime('%Y-%m-%d')+".json")
                if (file_exist(rough_filepath)):
                    histories=readerl(rough_filepath)
                    matching_history = next((history for history in histories if history["key"] == matching_name), None)
                    if matching_history:
                        gameinfo_raw.append(matching_history)
                    else:
                        lost_info_date.append(scan_date.strftime('%m-%d'))
                scan_date=time_delta(scan_date,1)
            lost_info_msg=f"(Lost {" ".join(lost_info_date)})" if lost_info_date else ""
            exhibit_date_woyear=f"{traceback_date_from.strftime("%m-%d")} - {traceback_date_to.strftime("%m-%d")} {lost_info_msg}"
            writerl(website_filepath,gameinfo_raw)
            # 前后两句顺序不要改, merge_crossday_gamedata会修改可变字典gameinfo_raw
            gameinfo=merge_crossday_gamedata(gameinfo_raw)
            website_link=create_website(json.dumps({"filename":filename_hashed,"caller":"","DateFrom":traceback_date_from.strftime("%m-%d"),"DateTo":traceback_date_to.strftime("%m-%d")}),"single_period")
        else: # 当天战局
            gameinfo=wzry_data(matching_name,website_filepath)
            battle_visible=gameinfo['visible']
            if (gameinfo['details']):
                for item in gameinfo['details'][::-1]: 
                    if (check_btl_official_with_matching(item["MapName"])):
                        last_official_btl_params=item["Params"]
                        break
                if (last_official_btl_params):
                    dmc.LastBtlParams=last_official_btl_params
                    dmc.LastBtlRoleId=roleidlist[matching_name]
                    dmc.LastBtlMsgTime=time_to_str(time_r())
                    dmc.LastBtlMsgStatus=True
            website_link=create_website(json.dumps({"filename":filename_hashed,"caller":"","time":""}),"single_oneday")
        
        win_content= "\n".join([f"              -{mapname}WIN：{map_cnt[0]} {f' / {map_cnt[1]}' if show_map_cnt_total else ''}" 
                    for mapname, map_cnt in gameinfo['map_cnt'].items()])+"\n"
        expert_hero_info=Analyses.get_expert_hero(userlist[matching_name])
        if (matching_name not in expert_hero_info):
            expert_hero_content=""
        else:
            expert_hero_content=f"最拿手英雄：{list(expert_hero_info[matching_name][0].keys())[0]},拿手程度：{list(expert_hero_info[matching_name][0].values())[0]}\n"
        gaming_content=""
        if (gameinfo["gaming_info"]):
            gaming_content=f"👀{namenick[matching_name]}正在{gameinfo["gaming_info"]["map_name"]}中玩{gameinfo["gaming_info"]["hero_name"]}，{gameinfo["gaming_info"]["duration_minute"]}分钟前开局{"，快去看看" if gameinfo["gaming_info"]["can_be_watched"] else "，快去看看"}。\n\n"
        if (gameinfo["visible"] and "排位" in gameinfo['map_cnt']):
            StarUpContent=f"      相比前一天 +⭐: {gameinfo['star_up']}\n"
        else:
            StarUpContent=f""
        if (gameinfo["visible"] and "巅峰" in gameinfo['map_cnt']):
            PeakUpContent=f"      相比前一天 巅峰分: \n"
            for score in gameinfo['peak_up']:
                PeakUpContent+=f"             {score[0]} --> {score[1]}\n"
        else:
            PeakUpContent=""

        if (battle_visible):
            snd_msg += (
                f"{gaming_content}"
                f"🚩{gameinfo['nickname']}({exhibit_date_woyear})的战报:\n"
                f"        场次：{gameinfo['today_num']}\n"
                f"{win_content}"
                f"        平均评分: {gameinfo['btl_aver'] if gameinfo['btl_aver']!=fin else serr}\n"
                f"      当前段位: {gameinfo['rank_name']} {gameinfo['rank_star']}⭐\n"
                f"{StarUpContent}"
                f"{PeakUpContent}"
                # f"{expert_hero_content}\n"
            )
            
            snd_msg+=website_link+"\n\n"
            if (gameinfo['today_num']==0): 
                ai_feedback=False
                exist_battle=False
            pokename.append(gameinfo['nickname'])
            ai_process_gameinfo=[]
            for detail in gameinfo['details']:
                ai_process_gameinfo.append({k: v for k, v in detail.items() if k in {"GameTime","HeroName","MapName","StarAfterGame","PeakGradeAfterGame","PeakGradeBeforeGame","KillCnt","DeadCnt","AssistCnt","Result","GameGrade","Duration_Second","Others"} and not v == -1})
            if (ai_feedback): snd_msg+=ai_parser([str(ai_process_gameinfo),snd_msg,rcv_msg],"single_player")+"\n"
            # if (ai_feedback): snd_msg+=(str(ai_process_gameinfo))+"\n"
        else:
            snd_msg += (
                f"{gaming_content}"
                f"🚩{gameinfo['nickname']}({exhibit_date_woyear})的战报:\n"
                f"              -战绩不可见\n"
                f"      当前段位: {gameinfo['rank_name']} {gameinfo['rank_star']}⭐\n"
                f"{StarUpContent}"
                f"{PeakUpContent}"
            )
    return [snd_msg,pokename,exist_battle,last_official_btl_params,roleidlist[matching_name]]
def view_process(rcv_msg,time_gap=analyze_time_gap):
    from .zfunc import Analyses

    snd_msg=" "
    if ("b" in rcv_msg):
        benefit_data=Analyses.get_benefit_data(time_gap=time_gap)[4]
        snd_msg+="受益受害：(排位巅峰战队)\n"
        for k,v in benefit_data.items():
            snd_msg+=f"{namenick[k]}：\n    {str(round(v[0],2))} {str(round(v[1]*100,1))}% {str(round(v[2],2))}\n"
    if ("e" in rcv_msg):
        extreme_data=Analyses.get_extreme_data(time_gap=time_gap)
        snd_msg+=f"近{time_gap}天最高最低评分：\n"
        snd_msg+="      ↑"+namenick[extreme_data[3]]+"的"+extreme_data[5]+"："+str(round(extreme_data[1],3))+"分\n"
        snd_msg+="      ↓"+namenick[extreme_data[2]]+"的"+extreme_data[4]+"："+str(round(extreme_data[0],3))+"分\n"
    if ("k" in rcv_msg):
        expert_hero=Analyses.get_expert_hero(time_gap=time_gap)
        for k,v in expert_hero.items():
            snd_msg+=f"{namenick[k]}的最拿手英雄：{list(v[0].keys())[0]},拿手程度：{str(round(list(v[0].values())[0],3))}\n"
        snd_msg+="\n"
    if ("i" in rcv_msg):
        intersection_data=Analyses.get_intersection_data(time_gap=time_gap)
        for k,v in intersection_data.items():
            double_player=[]
            for player in k: double_player.append(player)
            snd_msg+=f"{namenick[double_player[0]]}与{namenick[double_player[1]]}：{str(int(v))}\n"
    if ("h" in rcv_msg):
        hero_overview = Analyses.get_hero_benefit_data(time_gap=30)
        hero_min, hero_max, min_val, max_val, hero_stats = hero_overview
        snd_msg+=f"英雄受益受害（近30日）：\n"
        if hero_stats:
            snd_msg+=f"  受益：{hero_min} ({min_val})\n"
            snd_msg+=f"  受害：{hero_max} ({max_val})\n"
            snd_msg+=line_delim
            snd_msg+="\n  受益榜（Top 6）：\n"
            # hero_stats 已按 metric 升序排列（越小越受益）
            for hn, vals in list(hero_stats.items())[:6]:
                snd_msg+=f"    {hn} ( {vals[3]} 场 ):\n       {round(vals[0],3)} {round(vals[1]*100,1)}% {round(vals[2],2)}\n"
            snd_msg+=line_delim
            snd_msg+="\n  受害榜（Top 6）：\n"
            for hn, vals in list(hero_stats.items())[-6:][::-1]:
                snd_msg+=f"    {hn} ( {vals[3]} 场 ):\n       {round(vals[0],3)} {round(vals[1]*100,1)}% {round(vals[2],2)}\n"
        else:
            snd_msg+="  无数据。\n"
    return snd_msg
def btldetail_process(gameSvrId, relaySvrId, gameseq, pvptype,roleid,gen_image=False,show_profile=False,from_web=False,individual_show=False):
    from .zapi import wzry_get_official
    from .zfile import writerl
    from .zfunc import create_website
    from .zfunc import check_btl_official_with_matching
    from .tools import gen_battle_res
    import json
    import os

    res = fetch_battle(gameseq,roleid)

    if not res:
        res=wzry_get_official(reqtype="btldetail",gameseq=gameseq,gameSvrId=gameSvrId,relaySvrId=relaySvrId,roleid=roleid,pvptype=pvptype)
    
    if ('head' not in res or not check_btl_official_with_matching(res['head']['mapName'])): return None,None
    my_team_detail=res['redRoles'] if (res['redTeam']['acntCamp']==res['head']['acntCamp']) else res['blueRoles']
    my_team_total_money=0
    my_team_total_grade=0
    my_money=0
    my_grade=0
    am_i_assist=False
    for single_info in my_team_detail:
        my_team_total_money+=int(single_info['battleStats']['money'])
        my_team_total_grade+=float(single_info['battleStats']['gradeGame'])
        if (single_info['basicInfo']['userId']==res['head']['userId']):
            my_money=int(single_info['battleStats']['money'])
            my_grade=float(single_info['battleStats']['gradeGame'])
            for equipments in single_info['battleRecords']['finalEquips']:
                if (any(keyword in equipments['equipName'] for keyword in {"学识宝石","近卫","极影"})):
                    am_i_assist=True
    team_contribute_factor=(5 * my_grade / my_team_total_grade) * pow((5 * my_money / my_team_total_money), -0.5)
    if (am_i_assist): team_contribute_factor*=0.9
    team_contribute_text=f"贡献: {round(team_contribute_factor,2)}"
    my_userid=res['head']['userId']
    our_player_infos_suf=[]
    our_player_infos_suf_all=[]
    our_plyaer_info_userlist=userlist|extra_useridlist
    out_player_info_namenicklist=namenick|extra_namenick
    for player in my_team_detail:
        user_id=player['basicInfo']['userId']
        for our_player_name,our_player_id in our_plyaer_info_userlist.items():
            if (int(user_id)==int(our_player_id)):
                our_player_infos_suf_all.append([our_player_name,player['battleStats']['gradeGame']])
                if (int(user_id)!=int(my_userid)):
                    our_player_infos_suf.append([our_player_name,player['battleStats']['gradeGame']])
                break
                
            
    our_player_infos=[[out_player_info_namenicklist[playername],playergrade] for playername,playergrade in our_player_infos_suf]
    our_player_infos_all=[[out_player_info_namenicklist[playername],playergrade] for playername,playergrade in our_player_infos_suf_all]
    our_player_text=""
    our_player_text_all=""
    if (our_player_infos):
        our_player_text="With: "
        for info in our_player_infos:
            our_player_text+=f"{info[0]}({info[1]}) "
        our_player_text+="\n"
    if (our_player_infos_all):
        our_player_text_all=""
        for info in our_player_infos_all:
            our_player_text_all+=f"{info[0]}({info[1]}) "
        our_player_text_all+="\n"
    exact_now_time=str(round(time.time()*1000000))
    filename_hashed = str(hashlib.sha256((exact_now_time).encode()).hexdigest()[:16])
    json_output_path=os.path.join(nginx_path,"wzry_history",filename_hashed+".json")
    linkurl=create_website(json.dumps({"filename":filename_hashed,"caller":"","time":""}),"btldetail")
    picpath=""
    writerl(json_output_path,res)
    if (gen_image):
        picpath=os.path.join(nginx_path,"wzry_history","exhibit.png")
        gen_battle_res.generate_battle_ui_image(json_output_path,picpath)
    snd_message=""
    if (individual_show):
        snd_message+=(
            f"{res['battle']['dtEventTime']} {res['head']['mapName']} {'🏆' if res['head']['gameResult']==True else '🏳️'}\n"
            f"{our_player_text_all}"
            f"{linkurl}"
        )
    elif (from_web):
        snd_message+=(
            f"{res['battle']['dtEventTime']} {res['head']['mapName']} {'🏆' if res['head']['gameResult']==True else '🏳️'}\n"
            f"{res['head']['roleName']} {res['head']['heroName']} {team_contribute_text}\n"
            f"{linkurl}"
        )
    else:
        snd_message+=(
            f"最后一局 {'🏆' if res['head']['gameResult']==True else '🏳️'} "
            f"{team_contribute_text}"
            f"\n{res['head']['mapName']} {res['head']['heroName']}: {res['head']['killCnt']}/{res['head']['deadCnt']}/{res['head']['assistCnt']} {res['head']['gradeGame']}\n"
            f"{our_player_text}"
            f"{linkurl}\n\n"
            f"戳一戳 来评估两方实力"
        )
    return snd_message,picpath
def heropower_process(realname):
    from .zapi import wzry_get_official

    userid=userlist[realname]
    roleid=roleidlist[realname]

    res=wzry_get_official(reqtype="heropower",userid=userid,roleid=roleid)
    # print(res)
    ret_text=f"{namenick[realname]}的战力英雄\n"
    ret_text+=f"─────────────\n"
    for hero in res['heroList']:
        try:
            region_name=hero['honorTitle']['desc']['full'].split("第")[0]
            metal_name=hero['honorTitle']['desc']['abbr'].split("第")[0]
            ret_text+=f"【{hero['basicInfo']['title']}】"
            ret_text+=f" {hero['basicInfo']['heroFightPower']}\n"
            ret_text+=f" {region_name}  第 {hero['honorTitle']['rank']} 名\n\n"
        except Exception as e:
            pass
    return ret_text
# 单一玩家、单一英雄
def single_player_single_hero_process(username,heroid,heroname,this_season=False):
    from .zapi import wzry_get_official
    from .ztime import time_r, time_delta,str_to_time

    userid=userlist[username]
    roleid=roleidlist[username]

    res = wzry_get_official(reqtype="herostatistics", userid=userid, roleid=roleid, heroid=heroid)

    # 提取核心数据
    hero_info = res.get("heroInfo", {})
    winNum = int(hero_info.get("winNum") or 0)
    failNum = int(hero_info.get("failNum") or 0)
    total_cnt = winNum + failNum
    win_rate = (winNum / total_cnt) if total_cnt else 0

    power_data = res.get("powerData") or []
    heropower = power_data[-1]["value"] if power_data else 0
    month_heropower_incre = (power_data[-1]["value"] - power_data[0]["value"]) if len(power_data) > 1 else 0

    month_mvp = int(hero_info.get("mvpCount") or 0)
    month_medal = int(hero_info.get("goldCount") or 0) + int(hero_info.get("silverCount") or 0) + int(hero_info.get("bestCount") or 0)

    # 获取本地历史数据（用于详细统计）
    end_date = time_r()
    if(this_season): 
        start_date = str_to_time("2025-09-25")
        TimeLim="本赛季(20250925-now)"
    else: 
        start_date = time_delta(end_date, -30)
        TimeLim="近30日"
    history, duration = fetch_history(userid=userid, start_date=start_date, end_date=end_date)
    games = history.get(username, []) if history else []
    hero_games = [g for g in games if g.get('HeroName') == heroname]

    # 组装简洁输出
    lines = []
    lines.append(f"【统计信息】 {namenick[username]}的{heroname}")
    lines.append(line_delim)
    lines.append(f"战力  {heropower}  ({month_heropower_incre:+d})")
    lines.append(f"总战绩  {winNum}胜{failNum}负  胜率{round(win_rate*100,1)}%")
    
    if hero_games:
        total_games_h = len(hero_games)
        wins_h = sum(1 for g in hero_games if g.get('Result') == '胜利')
        win_rate_h = (wins_h / total_games_h) if total_games_h else 0
        avg_grade_h = sum(float(g.get('GameGrade', 0) or 0) for g in hero_games) / total_games_h if total_games_h else 0
        mvp_h = sum(1 for g in hero_games if 'MVP' in (g.get('Others') or ''))
        avg_kill_h = sum(int(g.get('KillCnt', 0) or 0) for g in hero_games) / total_games_h if total_games_h else 0
        avg_dead_h = sum(int(g.get('DeadCnt', 0) or 0) for g in hero_games) / total_games_h if total_games_h else 0
        avg_assist_h = sum(int(g.get('AssistCnt', 0) or 0) for g in hero_games) / total_games_h if total_games_h else 0
        
        lines.append(line_delim)
        lines.append(f"{TimeLim}表现")
        lines.append(f"{total_games_h}场  胜率{round(win_rate_h*100,1)}%  均分{round(avg_grade_h,1)}")
        lines.append(f"MVP×{mvp_h}  牌子×{month_medal}  KDA {round(avg_kill_h,1)}/{round(avg_dead_h,1)}/{round(avg_assist_h,1)}")
    else:
        lines.append(line_delim)
        lines.append(f"{TimeLim}无对局记录")

    # 添加成就牌（如果有特殊成就才显示）
    medal_list = res.get("medalList") or []
    if medal_list and len(medal_list) > 0:
        lines.append(line_delim)
        lines.append("成就")
        for medal_info in medal_list[:3]:  # 最多显示3个
            info = medal_info.get("UserMedalInfo") if isinstance(medal_info, dict) else str(medal_info)
            if info:
                lines.append(f"  · {info}")

    return "\n".join(lines)
# 单一玩家、所有英雄
def single_player_mult_hero_process(username, days=30, top_n=3, min_games=2):
    """统计玩家在最近若干天内的英雄表现，返回 JSON 风格字符串和可读摘要。
    - rcv_msg: 包含用户名的消息，使用 extract_name 解析
    - days: 向前统计天数
    - top_n: 每个榜单返回的条目数
    - min_games: 计算胜率/评分榜时的最小出场次数阈值
    返回字符串（先 JSON，再人类可读摘要）。
    """
    from .ztime import time_r, time_delta
    import json

    userid = userlist[username]

    end_date = time_r()
    start_date = time_delta(end_date, -days)
    history, duration = fetch_history(userid=userid, start_date=start_date, end_date=end_date)
    games = history.get(username, []) if history else []
    total_games = len(games)
    if total_games == 0:
        return f"{namenick[username]} 在最近 {days} 天没有对局记录。"

    # 聚合每个英雄的统计
    hero_stats = {}
    tier_dict = getattr(dmc, "herotier", {})
    total_tier_val = 0
    tier_counted_games = 0
    for g in games:
        hn = g.get('HeroName', '未知')
        if hn in tier_dict:
            try:
                total_tier_val += float(tier_dict[hn])
                tier_counted_games += 1
            except:
                pass
        s = hero_stats.setdefault(hn, {'count': 0, 'wins': 0, 'grades': [], 'kills': 0, 'deads': 0, 'assists': 0, 'mvp': 0})
        s['count'] += 1
        if g.get('Result') == '胜利':
            s['wins'] += 1
        try:
            s['grades'].append(float(g.get('GameGrade') or 0))
        except:
            pass
        s['kills'] += int(g.get('KillCnt') or 0)
        s['deads'] += int(g.get('DeadCnt') or 0)
        s['assists'] += int(g.get('AssistCnt') or 0)
        if 'MVP' in (g.get('Others') or ''):
            s['mvp'] += 1

    # 计算指标
    metrics = {}
    for hn, s in hero_stats.items():
        cnt = s['count']
        wins = s['wins']
        win_rate = (wins / cnt) if cnt else 0
        avg_grade = (sum(s['grades']) / len(s['grades'])) if s['grades'] else 0
        avg_k = s['kills'] / cnt if cnt else 0
        avg_d = s['deads'] / cnt if cnt else 0
        avg_a = s['assists'] / cnt if cnt else 0
        play_rate = cnt / total_games
        metrics[hn] = {
            'hero': hn,
            'count': cnt,
            'play_rate': play_rate,
            'win_rate': win_rate,
            'avg_grade': avg_grade,
            'kda': [round(avg_k, 2), round(avg_d, 2), round(avg_a, 2)],
            'mvp': s['mvp']
        }

    # 排名列表
    top_by_play = sorted(metrics.values(), key=lambda x: x['play_rate'], reverse=True)[:top_n]
    eligible = [m for m in metrics.values() if m['count'] >= max(1, min_games)]
    top_by_win = sorted(eligible, key=lambda x: x['win_rate'], reverse=True)[:top_n]
    top_by_grade = sorted(eligible, key=lambda x: x['avg_grade'], reverse=True)[:top_n]

    # 可读摘要
    lines = []
    avg_tier = round(total_tier_val / tier_counted_games, 2) if tier_counted_games > 0 else "N/A"
    lines.append(f"【统计信息】 {namenick[username]}的英雄汇总 \n（近 {days} 天，共 {total_games} 场，均梯: {avg_tier}）")
    lines.append(line_delim)
    lines.append("出场率 TOP:")
    for it in top_by_play:
        th = it['hero']
        tier_info = f" (梯 {tier_dict[th]})" if th in tier_dict else ""
        lines.append(f"  【{th}】{tier_info}: 出场 {it['count']} 场 ({round(it['play_rate']*100,1)}%)\n  胜率 {round(it['win_rate']*100,1)}%  均分 {round(it['avg_grade'],1)}\n  KDA {it['kda'][0]}/{it['kda'][1]}/{it['kda'][2]}")
    lines.append(line_delim)
    lines.append("胜率 TOP (至少 %d 场)：" % max(1, min_games
                ))
    if top_by_win:
        for it in top_by_win:
            th = it['hero']
            tier_info = f" (梯 {tier_dict[th]})" if th in tier_dict else ""
            lines.append(f"  【{th}】{tier_info}: 胜率 {round(it['win_rate']*100,1)}% ({it['count']} 场)\n  均分 {round(it['avg_grade'],1)}")
    else:
        lines.append("  无满足最小出场次数的英雄")
    lines.append(line_delim)
    lines.append("评分 TOP：")
    if top_by_grade:
        for it in top_by_grade:
            th = it['hero']
            tier_info = f" (梯 {tier_dict[th]})" if th in tier_dict else ""
            lines.append(f"  【{th}】{tier_info}: 均分 {round(it['avg_grade'],1)} ({it['count']} 场)\n  胜率 {round(it['win_rate']*100,1)}%")
    else:
        lines.append("  无满足最小出场次数的英雄")

    return "\n".join(lines)
# 所有玩家、所有英雄
def mult_player_mult_hero_process(days=30, top_n=5, min_games=5):
    """统计所有玩家在最近若干天内的英雄总体表现，返回人类可读摘要字符串。
    - days: 向前统计天数
    - top_n: 每个榜单返回的条目数
    - min_games: 计算胜率/评分榜时的最小出场次数阈值（按英雄总出场次数）
    """
    from .ztime import time_r, time_delta

    end_date = time_r()
    start_date = time_delta(end_date, -days)

    hero_stats = {}
    total_games_all = 0

    for realname, uid in userlist.items():
        try:
            history, duration = fetch_history(userid=uid, start_date=start_date, end_date=end_date)
        except Exception:
            continue
        games = history.get(realname, []) if history else []
        total_games_all += len(games)
        for g in games:
            hn = g.get('HeroName', '未知')
            s = hero_stats.setdefault(hn, {'count': 0, 'wins': 0, 'grades': []})
            s['count'] += 1
            if g.get('Result') == '胜利':
                s['wins'] += 1
            try:
                s['grades'].append(float(g.get('GameGrade') or 0))
            except:
                pass

    if total_games_all == 0:
        return f"最近 {days} 天内所有用户没有对局数据。"

    metrics = {}
    for hn, s in hero_stats.items():
        cnt = s['count']
        wins = s['wins']
        win_rate = (wins / cnt) if cnt else 0
        avg_grade = (sum(s['grades']) / len(s['grades'])) if s['grades'] else 0
        play_rate = cnt / total_games_all
        metrics[hn] = {'hero': hn, 'count': cnt, 'play_rate': play_rate, 'win_rate': win_rate, 'avg_grade': avg_grade}

    top_by_play = sorted(metrics.values(), key=lambda x: x['play_rate'], reverse=True)[:top_n]
    eligible = [m for m in metrics.values() if m['count'] >= max(1, min_games)]
    top_by_win = sorted(eligible, key=lambda x: x['win_rate'], reverse=True)[:top_n]
    top_by_grade = sorted(eligible, key=lambda x: x['avg_grade'], reverse=True)[:top_n]

    lines = []
    lines.append(f"【统计信息】 群u的英雄汇总\n（近 {days} 天，共 {total_games_all} 场）")
    lines.append(line_delim)
    lines.append("出场率 TOP:")
    for it in top_by_play:
        lines.append(f"  {it['hero']}: 出场 {it['count']} 场 ({round(it['play_rate']*100,1)}%)  胜率 {round(it['win_rate']*100,1)}%  均分 {round(it['avg_grade'],1)}")
    lines.append(line_delim)
    lines.append(f"胜率 TOP（至少 {max(1,min_games)} 场）：")
    if top_by_win:
        for it in top_by_win:
            lines.append(f"  {it['hero']}: 胜率 {round(it['win_rate']*100,1)}% ({it['count']} 场)  均分 {round(it['avg_grade'],1)}")
    else:
        lines.append("  无满足最小出场次数的英雄")
    lines.append(line_delim)
    lines.append("评分 TOP：")
    if top_by_grade:
        for it in top_by_grade:
            lines.append(f"  {it['hero']}: 均分 {round(it['avg_grade'],1)} ({it['count']} 场)  胜率 {round(it['win_rate']*100,1)}%")
    else:
        lines.append("  无满足最小出场次数的英雄")

    return "\n".join(lines)
# 所有玩家、单一英雄
def mult_player_single_hero_process(hero_id,hero_name, days=30, min_games=3, top_n=5):
    """针对指定英雄聚合全服数据，返回人类可读摘要。
    - hero_name: 英雄名称（精确匹配 `HeroName` 字段）
    - days: 向前统计天数
    - min_games: 列入胜率/评分榜的最小出场次数阈值（按单个玩家）
    - top_n: 每个榜单返回条目数
    返回字符串，包含：总体场次、参战玩家数、总体胜率、均分、KDA、地图分布、玩家榜单等
    """
    from .ztime import time_r, time_delta
    import collections

    end_date = time_r()
    start_date = time_delta(end_date, -days)

    per_player = {}  # player -> stats
    map_counter = collections.Counter()
    total_games = 0

    for realname, uid in userlist.items():
        try:
            history, duration = fetch_history(userid=uid, start_date=start_date, end_date=end_date)
        except Exception:
            continue
        games = history.get(realname, []) if history else []
        hero_games = [g for g in games if g.get('HeroName') == hero_name]
        if not hero_games:
            continue
        stats = {'count': 0, 'wins': 0, 'grades': [], 'kills': 0, 'deads': 0, 'assists': 0, 'mvp': 0, 'maps': collections.Counter()}
        for g in hero_games:
            stats['count'] += 1
            total_games += 1
            if g.get('Result') == '胜利':
                stats['wins'] += 1
            try:
                stats['grades'].append(float(g.get('GameGrade') or 0))
            except:
                pass
            stats['kills'] += int(g.get('KillCnt') or 0)
            stats['deads'] += int(g.get('DeadCnt') or 0)
            stats['assists'] += int(g.get('AssistCnt') or 0)
            if 'MVP' in (g.get('Others') or ''):
                stats['mvp'] += 1
            mapname = g.get('MapName') or '未知'
            stats['maps'][mapname] += 1
            map_counter[mapname] += 1
        per_player[realname] = stats

    if total_games == 0:
        return f"在最近 {days} 天内未发现任何玩家使用 {hero_name} 的对局。"

    # 汇总总体指标
    total_wins = sum(s['wins'] for s in per_player.values())
    all_grades = [g for s in per_player.values() for g in s['grades']]
    overall_winrate = total_wins / total_games if total_games else 0
    overall_avg_grade = (sum(all_grades) / len(all_grades)) if all_grades else 0
    overall_k = sum(s['kills'] for s in per_player.values()) / total_games
    overall_d = sum(s['deads'] for s in per_player.values()) / total_games
    overall_a = sum(s['assists'] for s in per_player.values()) / total_games

    # 玩家榜单
    players_by_count = sorted(per_player.items(), key=lambda x: x[1]['count'], reverse=True)[:top_n]
    eligible = [(p, s) for p, s in per_player.items() if s['count'] >= max(1, min_games)]
    players_by_win = sorted(eligible, key=lambda x: (x[1]['wins'] / x[1]['count']) if x[1]['count'] else 0, reverse=True)[:top_n]
    players_by_grade = sorted(eligible, key=lambda x: (sum(x[1]['grades']) / len(x[1]['grades'])) if x[1]['grades'] else 0, reverse=True)[:top_n]

    # 地图分布前几
    top_maps = map_counter.most_common(8)

    # 组装输出
    lines = []
    lines.append(f"【统计信息】 群u的{hero_name}\n（近 {days} 天）")
    lines.append(line_delim)
    lines.append(f"总场次：{total_games}    参战玩家数：{len(per_player)}")
    lines.append(f"总胜率：{round(overall_winrate*100,1)}%    均分：{round(overall_avg_grade,2)}\n K/D/A：{round(overall_k,2)}/{round(overall_d,2)}/{round(overall_a,2)}")
    lines.append(line_delim)
    lines.append("地图分布（Top）：")
    for m, c in top_maps:
        lines.append(f"  【{m}】: {c} 场 ({round(c/total_games*100,1)}%)")
    lines.append(line_delim)
    lines.append(f"出场最多的玩家（Top {top_n}）：")
    for p, s in players_by_count:
        winr = (s['wins'] / s['count']) if s['count'] else 0
        avgg = (sum(s['grades']) / len(s['grades'])) if s['grades'] else 0
        lines.append(f"  【{namenick.get(p,p)}】: {s['count']} 场  胜率 {round(winr*100,1)}%  均分 {round(avgg,2)}  KDA {round(s['kills']/s['count'],2)}/{round(s['deads']/s['count'],2)}/{round(s['assists']/s['count'],2)}")
    lines.append(line_delim)
    lines.append(f"胜率最高（至少 {max(1,min_games)} 场）Top {top_n}: ")
    if players_by_win:
        for p, s in players_by_win:
            winr = (s['wins'] / s['count']) if s['count'] else 0
            lines.append(f"  【{namenick.get(p,p)}】: 胜率 {round(winr*100,1)}% ({s['count']} 场)  均分 {round((sum(s['grades'])/len(s['grades'])) if s['grades'] else 0,2)}")
    else:
        lines.append("  无满足最小出场次数的玩家")
    lines.append(line_delim)
    lines.append(f"评分最高（至少 {max(1,min_games)} 场）Top {top_n}: ")
    if players_by_grade:
        for p, s in players_by_grade:
            avgg = (sum(s['grades']) / len(s['grades'])) if s['grades'] else 0
            lines.append(f"  【{namenick.get(p,p)}】: 均分 {round(avgg,2)} ({s['count']} 场)  胜率 {round((s['wins']/s['count'])*100,1)}%")
    else:
        lines.append("  无满足最小出场次数的玩家")

    return "\n".join(lines)


def recentgame_process(realname):
    """基于本地 history 文件，做近30天的综合多维度分析，返回字符串。
    参数 realname 用于指定用户名。
    """
    userid = userlist[realname]
    # time window
    try:
        from .ztime import time_r, time_delta
        end_date = time_r()
        start_date = time_delta(end_date, -30)
        history, duration = fetch_history(userid=userid, start_date=start_date, end_date=end_date)
        games = history.get(realname, []) if history else []
        if not games:
            return f"未在本地 history 文件中找到 {namenick[matching_name]} 近30天的战绩。"

        total_games = len(games)
        wins = sum(1 for g in games if g.get('Result') == '胜利')
        win_rate_recent = (wins / total_games) if total_games else 0
        avg_grade = sum(float(g.get('GameGrade', 0)) for g in games) / total_games if total_games else 0
        avg_kill = sum(int(g.get('KillCnt', 0)) for g in games) / total_games if total_games else 0
        avg_dead = sum(int(g.get('DeadCnt', 0)) for g in games) / total_games if total_games else 0
        avg_assist = sum(int(g.get('AssistCnt', 0)) for g in games) / total_games if total_games else 0
        mvp_cnt = sum(1 for g in games if 'MVP' in (g.get('Others') or ''))
        # 按英雄聚合
        hero_stats = {}
        for g in games:
            hn = g.get('HeroName', '未知')
            if hn not in hero_stats:
                hero_stats[hn] = {'count': 0, 'wins': 0, 'grades': [], 'mvp': 0}
            hero_stats[hn]['count'] += 1
            if g.get('Result') == '胜利':
                hero_stats[hn]['wins'] += 1
            try:
                hero_stats[hn]['grades'].append(float(g.get('GameGrade', 0)))
            except:
                pass
            if 'MVP' in (g.get('Others') or ''):
                hero_stats[hn]['mvp'] += 1

        # 组装文本
        txt = f"{namenick[matching_name]} 近30天综合战绩分析：\n"
        txt += f"  场次：{total_games}，胜率：{round(win_rate_recent*100,2)}%，MVP：{mvp_cnt}，平均评分：{round(avg_grade,2)}\n"
        txt += f"  场均 K/D/A：{round(avg_kill,2)}/{round(avg_dead,2)}/{round(avg_assist,2)}\n"
        sorted_heroes = sorted(hero_stats.items(), key=lambda x: x[1]['count'], reverse=True)
        txt += "  热门英雄：\n"
        for hn, info in sorted_heroes[:8]:
            cnt = info['count']
            wins_h = info['wins']
            winr_h = (wins_h / cnt) if cnt else 0
            avgg = (sum(info['grades']) / len(info['grades'])) if info['grades'] else 0
            txt += f"    {hn}：{cnt}局，胜率{round(winr_h*100,2)}%，平均分{round(avgg,2)}，MVP{info['mvp']}\n"
        return txt
    except Exception as e:
        try:
            log_message(f"recentgame_process error: {e}")
        except:
            pass
        return None
def todayhero_process(realname,ignore_limit=False,ai_comment=True):
    from .zfunc import single_player_single_hero_process
    def get_hero_name(realname,hero_name_candidates):
        from .ztime import time_r,time_delta
        from .zfunc import fetch_history
        # 45% 随机
        # 35% 最近
        # 20% 榜单
        hero_selected_way=random.random()
        hero_name=""
        selected_info={"way":"","details":[]}
        initial_time_to=time_r()
        trace_back_time_to=initial_time_to
        trace_back_time_from=time_delta(trace_back_time_to,-5)
        game_details,_=fetch_history(userid=userlist[realname],start_date=trace_back_time_from,end_date=trace_back_time_to)
        game_details=game_details[realname]
        if (realname in force_choice):
            hero_name=force_choice[realname]
            selected_info["way"]="RANDOM"
            selected_info["details"]:[]
            return hero_name,selected_info
        if (hero_selected_way<0.45):
            hero_name = random.choice(hero_name_candidates)
            selected_info["way"]="RANDOM"
            selected_info["details"]=[]
        elif (hero_selected_way<0.8 and game_details):
            recent_hero_name_candidates=set()
            for game_detail in game_details:
                if (game_detail["HeroName"] in hero_name_candidates):
                    recent_hero_name_candidates.add(game_detail["HeroName"])
            hero_name = random.choice(list(recent_hero_name_candidates))
            selected_info["way"]="RECENT"
            for game_detail in game_details:
                if (game_detail["HeroName"]==hero_name):
                    selected_info["details"].append({"MapName":game_detail["MapName"],"GameGrade":game_detail["GameGrade"]})
        elif (hero_selected_way<1):
            # print(dmc.herorank)
            rankId_candidate=list(dmc.herorank.keys())
            rankId=random.choice(rankId_candidate)
            rankTitle=dmc.herorank[rankId]["title"]
            hero_name=""
            while(hero_name not in hero_name_candidates):
                rankIndex=random.randint(0,10)
                hero_name=dmc.herorank[rankId]["list"][rankIndex]["heroInfo"]["heroName"]
            hero_rankinfo=dmc.herorank[rankId]["list"][rankIndex]
            selected_info["way"]="HERORANK"
            selected_info["details"].append({})
            valid_data_type={"banRate":"顶端排位被ban率","showRate":"顶端排位出场率","winRate":"顶端排位胜率","killNum":"顶端排位场均击杀数","output":"顶端排位场均输出","mvp":"顶端排位MVP率","goldPlay":"顶端排位金牌率"}
            for k,v in hero_rankinfo.items():
                if (k in valid_data_type and v!=0):
                    selected_info["details"][0][valid_data_type[k]]=v
        return hero_name,selected_info
    def get_rand_hero_skin(realname):
        skin_folder_path=os.path.join("wzry_images","skins")
        hero_names = [d for d in os.listdir(skin_folder_path) 
              if os.path.isdir(os.path.join(skin_folder_path, d))]
        hero_name,selected_info=get_hero_name(realname,hero_names)
        # hero_name = random.choice(hero_names)
        hero_path = os.path.join(skin_folder_path, hero_name)
        
        skin_files = [f for f in os.listdir(hero_path) 
                if os.path.isfile(os.path.join(hero_path, f))]
        
        skin_file = random.choice(skin_files)
        skin_name=os.path.splitext(skin_file)[0]
        pic_path = os.path.abspath(os.path.join(os.getcwd(),hero_path, skin_file))
        return hero_name, skin_name,pic_path,selected_info
    def get_hero_skin(realname,ignore_limit):
        import redis
        from .ztime import time_r
        current_date = time_r().strftime("%Y-%m-%d")
        if (ignore_limit): hero_info_str=None
        else: hero_info_str = dmc.TodayHeroPool.get(realname)
        if (hero_info_str):
            hero_info = json.loads(hero_info_str)
            stored_date = hero_info.get("date")
            if stored_date == current_date:
                return hero_info.get("heroname"),hero_info.get("skinname"),hero_info.get("picpath"),hero_info.get("selectinfo")
            else:
                pass
        hero_name, skin_name,pic_path,selected_info=get_rand_hero_skin(realname)
        new_data = {
            "date": current_date,
            "heroname": hero_name,
            "skinname": skin_name,
            "picpath":pic_path,
            "selectinfo":selected_info
        }
        dmc.TodayHeroPool.set(realname, json.dumps(new_data))
        
        history_key = f"hero_history:{realname}"
        history_entry = {
            "date": current_date,
            "heroname": hero_name,
            "skinname": skin_name,
            "selectinfo": selected_info
        }
        
        history_list = dmc.TodayHeroPool.lrange(history_key, 0, -1)
        date_found = False
        for i, entry_str in enumerate(history_list):
            entry = json.loads(entry_str)
            if entry.get("date") == current_date:
                dmc.TodayHeroPool.lset(history_key, i, json.dumps(history_entry))
                date_found = True
                break
        if not date_found:
            dmc.TodayHeroPool.rpush(history_key, json.dumps(history_entry))
        
        return hero_name, skin_name,pic_path,selected_info
    def get_hero_skills(heroid):
        from .zfile import readerl
        all_skills=[]
        
        skill_raw=readerl(os.path.join('wzry_images','hero_skills',heroid+".json"))
        for skill in skill_raw["skillList1"]:
            all_skills.append(skill["desc"])
        return all_skills

    hero_name,skin_name,pic_path,selected_info=get_hero_skin(realname,ignore_limit=ignore_limit)
    heroid=[heroid_ for heroid_,heroname_ in HeroList.items() if heroname_==hero_name][0]

    hero_skills=get_hero_skills(heroid)
    hero_statistics=single_player_single_hero_process(realname,heroid,hero_name)
    dmc.use_mem=False
    if (ai_comment): play_reason=ai_parser(msg_type="skill_advantage",user_query=[hero_name,namenick[realname],str(hero_skills),str(selected_info),hero_statistics])
    else: play_reason=str(selected_info)
    dmc.use_mem=True
    former_msg=f"{namenick[realname]}的今日英雄：{hero_name}"
    latter_msg=play_reason
    return former_msg,latter_msg,pic_path

def allhero_process(realname):
    from .zapi import wzry_get_official

    userid=userlist[realname]
    roleid=roleidlist[realname]

    res=wzry_get_official(reqtype="allhero",userid=userid,roleid=roleid)
    ret_text=f"{namenick[realname]}的拿手英雄\n"
    hero_cnt=0
    for hero in res['heroList']:
        if (hero_cnt>5): break
        hero_cnt+=1
        # try:
        ret_text+=f"{hero['name']}： {hero['heroFightPower']}\n"
        ret_text+=f"   {hero['playNum']}场 {hero['winRate']}\n"
        # except Exception as e:
        #     pass
        # print(hero['honorTitle']['region']['provinceName'],hero['honorTitle']['desc']['full'])
        # ret_text+=f"{hero['honorTitle']['region']['provinceName']} {hero['honorTitle']['desc']['full']} "
    return ret_text
def gradeanalyze_process(realname):
    from .tools import gen_grade_chart

    userid=userlist[realname]
    data_path=os.path.join("history")
    pic_visit_path=f"/usr/local/nginx/html/wzry_grade_chart/grade_chart.png"
    pic_save_path=f"/usr/local/nginx/html/wzry_grade_chart/"
    analyze_msg=gen_grade_chart.gen(userid,data_path,pic_save_path)
    
    return pic_visit_path,analyze_msg
def watchbattle_process(realname):
    from .zapi import wzry_get_official
    from .tools import gen_battle_shot

    userid=userlist[realname]
    roleid=roleidlist[realname]

    btlist_data=wzry_get_official(reqtype="btlist",userid=userid,roleid=roleid)
    if (not btlist_data["isGaming"]): return None,None
    res=btlist_data["gaming"]
    if (not res["canBeWatch"]): return None,None

    battleId=res["battleId"]
    mapName=res["mapName"]
    duration=res["duration"]

    save_path="/usr/local/nginx/html/wzry_btl_shot/"+str(roleid)+".png"
    if(dmc.RTMPListener): dmc.RTMPListener.stop()
    dmc.RTMPListener = gen_battle_shot.RTMPListener(dmc.streamurl,save_path=save_path,roleid=roleid)
    dmc.RTMPListener.start()  # 开始后台监听

    dmc.RTMPListener.screenshot()   # 截图一次
    return save_path,None
def coplayer_process(gameSvrId, relaySvrId, gameseq, pvptype,roleid,from_web=False):
    from .zapi import wzry_get_official
    from .zfunc import check_btl_official_with_matching
    from .tools.gen_coplayer_analyses import CoPlayerProcess

    def sigmoid(x):
        return 1/(1+math.exp(-x))
    
    def fetch_player_data(player):
        roleid = player["basicInfo"]["roleId"]
        userid = player["basicInfo"]["userId"]
        is_auth = player["basicInfo"]["isGameAuth"]
        result = {
            'player': player,
            'profile_res': None,
            'heropower_res': None,
            'recentbtl_res': None,
            'errors': []
        }
        if not is_auth:
            return result
        try:
            result['profile_res'] = wzry_get_official(reqtype="profile", roleid=roleid, userid=userid)
        except Exception as e:
            result['errors'].append(str(e))
        try:
            result['heropower_res'] = wzry_get_official(reqtype="heropower", roleid=roleid, userid=userid)
        except Exception as e:
            result['errors'].append(str(e))
        try:
            result['recentbtl_res'] = wzry_get_official(reqtype="btlist_url", roleid=roleid, userid=userid)
        except Exception as e:
            result['errors'].append(str(e))
        return result
    def get_hero_tier(detail_list):
        total_tier = 0
        found_cnt = 0
        for player in detail_list:
            heroName = player["battleRecords"]["usedHero"]["heroName"]
            tier_dict = getattr(dmc, 'herotier', {})
            if heroName in tier_dict:
                tier = tier_dict[heroName]
                total_tier += tier
                found_cnt += 1
        if (found_cnt):
            total_tier = total_tier * (5 / found_cnt)
        avg_tier = total_tier / 5
        return avg_tier

    def get_player_power(detail_list, is_my_side, player_data_cache):
        auth_cnt=0      # 授权人数统计
        ret_level=0     # 返回值
        req_error=[]
        for player in detail_list:
            # 对于该队伍中的一个玩家
            winNum=10        # 当前英雄输局数
            loseNum=10       # 当前英雄胜局数
            avgScore=8      # 当前英雄平均评分
            winRate=0.5     # 当前英雄胜率
            starNum=50      # 总星数
            peakScore=1200  # 巅峰分数
            PowerNum=70000  # 总战斗力
            TotalCnt=1000   # 总场次
            MVPCnt=100      # 总MVP场次
            MVPRate=0.1
            heroPower=1000
            rankName="未知段位"
            rankStar=0
            RecentWinRate=0.55
            RecentAvgScore=8
            BetterHeroPowerList=[]
            BetterHeroPower=1
            heroTag=""
            MaxHeroPower=-1
            MaxHeroTag=""

            is_auth=player["basicInfo"]["isGameAuth"] # 营地授权与否
            roleid=player["basicInfo"]["roleId"]
            userid=player["basicInfo"]["userId"]
            nickname=player["basicInfo"]["roleName"]
            heroBehavior=player["heroBehavior"]
            heroName=player["battleRecords"]["usedHero"]["heroName"]
            heroAvatar=player["battleRecords"]["usedHero"]["heroIcon"]
            player_avatar_url=""
            if (is_auth):
                auth_cnt+=1
                winNum=heroBehavior["winNum"]
                loseNum=heroBehavior["loseNum"]
                avgScore=float(heroBehavior["avgScore"])
                winRate=float(heroBehavior["winRate"].strip('%')) / 100
                heroPower=player["battleStats"]["fightPower"]
                
                # 从缓存中获取预先并行获取的数据
                player_key = (roleid, userid)
                cached_data = player_data_cache.get(player_key, {})
                profile_res = cached_data.get('profile_res')
                heropower_res = cached_data.get('heropower_res')
                recentbtl_res = cached_data.get('recentbtl_res')
                req_error.extend(cached_data.get('errors', []))
                
                if not profile_res:
                    continue

                RoleInfo = (roles[0] if (roles := [role for role in profile_res["roleList"] if role["roleId"] == roleid]) else None)
                rankInfo = (mods[0] if (mods := [mods for mods in profile_res["head"]["mods"] if mods["modId"] == 701]) else None)
                peakInfo = (mods[0] if (mods := [mods for mods in profile_res["head"]["mods"] if mods["modId"] == 702]) else None)
                Powerinfo = (mods[0] if (mods := [mods for mods in profile_res["head"]["mods"] if mods["modId"] == 304]) else None)
                TotalNumInfo = (mods[0] if (mods := [mods for mods in profile_res["head"]["mods"] if mods["modId"] == 401]) else None)
                MVPInfo = (mods[0] if (mods := [mods for mods in profile_res["head"]["mods"] if mods["modId"] == 408]) else None)
                if (RoleInfo):
                    player_avatar_url=RoleInfo.get("roleIcon","")
                if (rankInfo):
                    rankName=rankInfo["name"]
                    rankStar=int(json.loads(rankInfo["param1"])["rankingStar"])
                    starNum=(ranklist[rankName] if rankName in ranklist else fin) + rankStar
                if (peakInfo): peakScore=int(peakInfo["content"]) or 1200
                if (Powerinfo): PowerNum=int(Powerinfo["content"])
                if (TotalNumInfo): TotalCnt=int(TotalNumInfo["content"])
                if (MVPInfo): MVPCnt=int(MVPInfo["content"])
                if (TotalNumInfo and MVPInfo): MVPRate=MVPCnt/TotalCnt
                else: MVPRate=0.25
                if (heropower_res):
                    for hero in heropower_res['heroList']:
                        try:
                            if (hero['basicInfo']['title']==heroName):
                                region_name=hero['honorTitle']['desc']['full'].split("第")[0]
                                metal_name=hero['honorTitle']['desc']['abbr'].split("第")[0]
                                heroTag=f"{region_name}\n No.{hero['honorTitle']['rank']} \n"
                        except Exception as e:
                            pass
                        if (hero['basicInfo']['heroFightPower']>=heroPower):
                            BetterHeroPowerList.append(hero['basicInfo']['heroFightPower'])
                        if (hero['basicInfo']['heroFightPower']>MaxHeroPower):
                            if ('honorTitle' in hero and hero['honorTitle']):
                                MaxHeroPower=hero['basicInfo']['heroFightPower']
                                region_name=hero['honorTitle']['desc']['full'].split("第")[0]
                                metal_name=hero['honorTitle']['desc']['abbr'].split("第")[0]
                                MaxHeroTag=f"Top {MaxHeroPower}\n{region_name}第{hero['honorTitle']['rank']}{hero['basicInfo']['title']}"
                if (recentbtl_res and recentbtl_res["list"]):
                    official_btls=[]
                    for btl in recentbtl_res["list"]:
                        if (check_btl_official(btl["mapName"])):
                            official_btls.append({"result":btl["gameresult"]==1,"grade":float(btl["gradeGame"])})
                    if (len(official_btls)>=10):
                        RecentWinRate=sum(1 for btl in official_btls if (btl["gameresult"]))/len(official_btls)
                    RecentAvgScore=sum(btl["gradeGame"] for btl in official_btls)/len(official_btls)
            BetterHeroPower=heroPower
            if (BetterHeroPowerList):
                BetterHeroPowerList=BetterHeroPowerList[:3]
                BetterHeroPower=sum(BetterHeroPowerList)/len(BetterHeroPowerList)
            HeroShowCnt=loseNum+winNum                      # 该玩家此英雄的出场局数
            equiv_star=(starNum-25)+(peakScore-1200)/15.0   # 巅峰分与星数折算成一个综合星级
            if (equiv_star<=0): equiv_star=1                # 星级下界
            single_level = (
                1
                * pow(equiv_star, 0.3)                                          # equiv_star        星级和巅峰分计算得的等价星级                                0.3
                * pow(sigmoid(MVPRate), 4)                                      # MVPRate           MVP率                                                       4
                * pow((PowerNum / 10000), 0.85)                                 # PowerNum          战斗力                                                      0.85
                * pow((avgScore + RecentAvgScore) / 2, 1)                       # avgScore          该英雄历史场次平均评分 + 近期场次平均评分                       1
                * pow(sigmoid(HeroShowCnt / 10), 1.3)                           # HeroShowCnt       该英雄历史场次数                                            1.3
                * pow(sigmoid((heroPower + BetterHeroPower) / 2 / 10000), 2)    # heroPower         该英雄当前战力 + 更高战力英雄的战力平均值(最多取更高的3个)          2
                * pow(max(RecentWinRate / 0.5, 1), 2)
            )
            # 指标1.5倍的等价条件
            # 王者0星 巅峰1200分 -> 王者50星 巅峰1600分
            # MVP率 30% -> 56%
            # 战斗力 50000 -> 80000
            # 本局使用英雄与近期场次的平均评分 8分 -> 12分
            # 本局使用英雄的总场次 10场 -> 300场
            # 本局使用英雄与高战力英雄的战力 1000 -> 6000 -> 13000

            # 高战力英雄的取法： 比该局所选英雄战力高的英雄中 取前3名

            # 生成图表中
            # 卡片右上角红色角标：营地未授权
            # 玩家卡片背景色：红色，低于所有玩家历史平均水平；绿色，高于所有玩家历史平均水平；颜色越深，差值越大
            # 底蕴值：以该局最高玩家为100%计算
            if (is_auth): ret_level+=single_level
            gen_inst.add_player(
                nickname=nickname,
                is_auth=is_auth,
                is_my_side=is_my_side,
                winNum=winNum,
                loseNum=loseNum,
                avgScore=avgScore,
                winRate=winRate,
                avatarUrl=player_avatar_url,
                starNum=starNum,
                peakScore=peakScore,
                PowerNum=PowerNum,
                TotalCnt=TotalCnt,
                MVPCnt=TotalCnt*MVPRate,
                rankName=rankName,
                rankStar=rankStar,
                single_level=single_level,
                HeroAvatar=heroAvatar,
                HeroPower=heroPower,
                HeroTag=heroTag,
                MaxHeroTag=MaxHeroTag,
            )
        ret_level=ret_level*(5/auth_cnt) if (auth_cnt) else 0
        return ret_level,auth_cnt,req_error

    gen_inst=CoPlayerProcess()
    res=wzry_get_official(reqtype="btldetail",gameSvrId=gameSvrId, relaySvrId=relaySvrId, gameseq=gameseq, pvptype=pvptype,roleid=roleid)
    if ('head' not in res): return None
    gameres=res['head']['gameResult']
    my_side_detail=res['redRoles'] if (res['redTeam']['acntCamp']==res['head']['acntCamp']) else res['blueRoles']
    op_side_detail=res['redRoles'] if (res['redTeam']['acntCamp']!=res['head']['acntCamp']) else res['blueRoles']
    # my_side_detail=[my_side_detail[0]]
    # op_side_detail=[op_side_detail[0]]
    # 并行获取所有玩家的数据
    all_players = my_side_detail + op_side_detail
    player_data_cache = {}
    
    with ThreadPoolExecutor(max_workers=1) as executor:
        future_to_player = {executor.submit(fetch_player_data, player): player for player in all_players}
        for future in as_completed(future_to_player):
            try:
                result = future.result()
                player = result['player']
                roleid = player["basicInfo"]["roleId"]
                userid = player["basicInfo"]["userId"]
                player_key = (roleid, userid)
                player_data_cache[player_key] = {
                    'profile_res': result['profile_res'],
                    'recentbtl_res': result['recentbtl_res'],
                    'heropower_res': result['heropower_res'],
                    'errors': result['errors']
                }
            except Exception as e:
                pass

    my_side_total_level,my_side_auth_cnt,my_side_req_error=get_player_power(my_side_detail,1,player_data_cache)
    op_side_total_level,op_side_auth_cnt,op_side_req_error=get_player_power(op_side_detail,0,player_data_cache)
    
    my_side_total_tier = get_hero_tier(my_side_detail)
    op_side_total_tier = get_hero_tier(op_side_detail)

    delta_level=my_side_total_level-op_side_total_level

    if (op_side_total_level and my_side_total_level):
        record = {
            'game_res': gameres,
            'my_side_total_level': my_side_total_level,
            'op_side_total_level': op_side_total_level,
            'gameSvrId': gameSvrId,
            'relaySvrId': relaySvrId,
            'gameseq': gameseq,
            'pvptype': pvptype,
            'roleid': roleid,
        }
        redis_client = dmc.BtlAnalyzeEvaluatorPool
        redis_client.rpush('records', json.dumps(record, ensure_ascii=False))

    snd_msg=(
        f"实力天平倾斜度：{round(delta_level,2) if op_side_total_level else "unknown"}\n"
        f"我方底蕴：{round(my_side_total_level,2) if my_side_total_level else "unknown"}\n"
        f"我方英雄梯度：{round(my_side_total_tier,2)}\n"
        f"对方底蕴：{round(op_side_total_level,2) if op_side_total_level else "unknown"}\n"
        f"对方英雄梯度：{round(op_side_total_tier,2)}\n"
    )
    save_path=os.path.join(nginx_path,"wzry_history","coplayer_analyses.png")
    out_path, ok = gen_inst.gen(save_path)

    return snd_msg,save_path

def fetch_history(userid=None,start_date=None,end_date=None,filter_official=True): # 所有历史数据
    from .zfile import readerl
    from .zfile import writerl
    from .ztime import str_to_time,time_r

    if (not start_date or start_date<str_to_time(record_begin_date)): start_date=str_to_time(record_begin_date)
    if (not end_date): end_date=time_r()
    gamedetails={}
    filenames=sorted(os.listdir("history"),reverse=True)
    duration=0
    for filename in filenames:
        if not os.path.isfile(os.path.join("history",filename)): continue
        history_date=os.path.splitext(os.path.basename(filename))[0]
        if not bool(re.fullmatch(r'^\d{4}-\d{2}-\d{2}$', history_date)): continue
        date_parsed=str_to_time(history_date)
        if (date_parsed>end_date or date_parsed<start_date): continue
        duration+=1
        full_path=os.path.join("history",filename)
        gameinfo=readerl(full_path)
        for player in gameinfo:
            playername=player["key"]
            playerdetails=player["details"][::-1]
            if (filter_official):
                playerdetails=[detail for detail in playerdetails if check_btl_official(detail["MapName"])]
            if (playername not in gamedetails): 
                gamedetails[playername]=playerdetails
            else:
                for playerdetail in playerdetails:
                    gamedetails[playername].append(playerdetail)
    if (userid): gamedetails={k:v for k,v in gamedetails.items() if userid==userlist[k]}
    return gamedetails,duration

def fetch_battle(gameseq,roleid=0): # 读取单局战绩具体内容
    from .zfile import readerl
    file_path = os.path.join("history", "battles", f"{gameseq}.json")
    res=readerl(file_path)
    if (res and roleid):
        # 找到对应的玩家信息并更新head
        target_role = None
        for role in res.get('redRoles', []) + res.get('blueRoles', []):
            if int(role['basicInfo']['roleId']) == int(roleid):
                target_role = role
                break
        
        if target_role:
            # 更新head信息以适应当前的查询目标
            res['head'] = {
                'userId': target_role['basicInfo']['userId'],
                'roleId': target_role['basicInfo']['roleId'],
                'roleName': target_role['basicInfo']['roleName'],
                'heroName': target_role['battleRecords']['usedHero']['heroName'],
                'acntCamp': target_role['basicInfo']['acntCamp'],
                'gameResult': (res['redTeam']['gameResult'] == 1 if target_role['basicInfo']['acntCamp'] == res['redTeam']['acntCamp'] else res['blueTeam']['gameResult'] == 1),
                'killCnt': target_role['battleStats']['killCnt'],
                'deadCnt': target_role['battleStats']['deadCnt'],
                'assistCnt': target_role['battleStats']['assistCnt'],
                'gradeGame': target_role['battleStats']['gradeGame'],
                'mapName': res.get('battle', {}).get('mapName', 'Unknown'),
                'dtEventTime': res.get('battle', {}).get('dtEventTime', '')
            }
    return res
class Analyses:
    @staticmethod
    def analyze_history(userid=None,start_date=None,end_date=None): # 返回排位巅峰战队赛
        all_history,duration=fetch_history(userid=userid,start_date=start_date,end_date=end_date)
        analyzed_infos={}
        for k,v in all_history.items():
            history_kept=v
            if (len(history_kept)==0): continue
            analyzed_info={}
            win_tourna_cnt=sum(1 for detail in history_kept if detail["Result"]=="胜利")
            total_tourna_cnt=sum(1 for detail in history_kept)
            win_rate_tourna=-1 if total_tourna_cnt==0 else float(win_tourna_cnt)/total_tourna_cnt
            hero_info={}
            for detail in history_kept:
                if (detail["HeroName"] not in hero_info): hero_info[detail["HeroName"]]=[0,1,[],0,0]
                else: hero_info[detail["HeroName"]][1]+=1
                if (detail["Result"]=="胜利"): hero_info[detail["HeroName"]][0]+=1
                hero_info[detail["HeroName"]][2].append(float(detail["GameGrade"]))
            for hero in hero_info:
                hero_info[hero][3]=float(hero_info[hero][0])/hero_info[hero][1] # 英雄胜率
                hero_info[hero][4]=float(sum(hero_info[hero][2]))/len(hero_info[hero][2]) # 英雄平均评分
            analyzed_info={"win_tourna_cnt":win_tourna_cnt,"total_tourna_cnt":total_tourna_cnt,"win_rate_tourna":win_rate_tourna,"hero_info":{k:v for k,v in hero_info.items()},"duration":duration}
            analyzed_infos[k]=analyzed_info
        # print(analyzed_infos)
        return analyzed_infos

    @staticmethod
    def get_benefit_data(userid=None,time_gap=analyze_time_gap): # 评分^2/exp(胜率)： exp防止胜率0附近斜率过大 # 值越大越受害 值越小越受益
        from .ztime import time_r
        from .ztime import time_r_delta

        end_date=time_r()
        start_date=time_r_delta(time_gap)
        analyzed_infos=Analyses.analyze_history(userid=None,start_date=start_date,end_date=end_date)
        # print(analyzed_infos)

        user_low_grade_winrate_ratio="" # 评分胜率比最低
        user_high_grade_winrate_ratio="" # 评分胜率比最高
        low_grade_winrate_ratio=10000
        high_grade_winrate_ratio=0
        player_benefit={}
        for k,v in analyzed_infos.items(): # 为了评判机制受益程度，或许评分与上星比值更为合理（评分：实力，上星：受益），胜率与上星无必然关联
            if (len(v["hero_info"])==0): continue
            win_rate=sum(heroinfo[0] for heroname,heroinfo in v["hero_info"].items())/sum(heroinfo[1] for heroname,heroinfo in v["hero_info"].items())
            aver_grade=sum(sum(heroinfo[2]) for heroname,heroinfo in v["hero_info"].items())/sum(heroinfo[1] for heroname,heroinfo in v["hero_info"].items())
            grade_winrate_ratio=pow(aver_grade,2)/(math.exp(win_rate))
            # grade_winrate_ratio=math.exp((math.log(aver_grade)-math.log(2))/(math.log(14)-math.log(2)))/(math.exp(win_rate))
            # grade_winrate_ratio=math.exp((aver_grade-2)/(14-2))/(math.exp(win_rate))
            player_benefit[k]=[grade_winrate_ratio,win_rate,aver_grade]
            # print("benefit",k,win_rate,aver_grade,grade_winrate_ratio)
            if (grade_winrate_ratio<low_grade_winrate_ratio): 
                user_low_grade_winrate_ratio=k
                low_grade_winrate_ratio=grade_winrate_ratio
            if (grade_winrate_ratio>high_grade_winrate_ratio): 
                user_high_grade_winrate_ratio=k
                high_grade_winrate_ratio=grade_winrate_ratio
        player_benefit = dict(sorted(player_benefit.items(), key=lambda item: item[1][0]))
        # print([user_low_grade_winrate_ratio,user_high_grade_winrate_ratio,round(low_grade_winrate_ratio,3),round(high_grade_winrate_ratio,3)],player_benefit)
        return [user_low_grade_winrate_ratio,user_high_grade_winrate_ratio,round(low_grade_winrate_ratio,3),round(high_grade_winrate_ratio,3),player_benefit]
    
    @staticmethod
    def get_hero_benefit_data(time_gap=analyze_time_gap):
        """按英雄聚合分析（与 get_benefit_data 对玩家的分析类似）
        - time_gap: 向前统计天数
        返回格式：[hero_min_metric, hero_max_metric, round(min_val,3), round(max_val,3), hero_stats]
        hero_stats 为 dict: {hero: [metric, win_rate, avg_grade, total_count]}
        metric 计算方式与玩家端一致： avg_grade^2 / exp(win_rate)
        值越大表示该英雄在统计期内总体上“受害”（评分高但胜率偏低），值越小表示更“受益”。
        """
        from .ztime import time_r
        from .ztime import time_r_delta

        end_date = time_r()
        start_date = time_r_delta(time_gap)
        analyzed_infos = Analyses.analyze_history(userid=None, start_date=start_date, end_date=end_date)

        hero_acc = {}  # hero -> {'count':, 'wins':, 'grades':[]}
        for player, info in analyzed_infos.items():
            for hero, hinfo in info.get('hero_info', {}).items():
                cnt = hinfo[1]
                wins = hinfo[0]
                grades = hinfo[2]
                entry = hero_acc.setdefault(hero, {'count': 0, 'wins': 0, 'grades': []})
                entry['count'] += cnt
                entry['wins'] += wins
                entry['grades'].extend(grades)

        # 只统计出场超过 3 场的英雄
        hero_acc = {h: acc for h, acc in hero_acc.items() if acc['count'] > 3}
        if not hero_acc:
            return ["", "", 0, 0, {}]

        hero_stats = {}
        min_metric = float('inf')
        max_metric = float('-inf')
        hero_min = ""
        hero_max = ""

        for hero, acc in hero_acc.items():
            total = acc['count']
            win_rate = (acc['wins'] / total) if total else 0
            all_grades = acc['grades']
            avg_grade = (sum(all_grades) / len(all_grades)) if all_grades else 0
            metric = pow(avg_grade, 2) / math.exp(win_rate) if total else 0
            hero_stats[hero] = [metric, win_rate, avg_grade, total]
            if metric < min_metric:
                min_metric = metric
                hero_min = hero
            if metric > max_metric:
                max_metric = metric
                hero_max = hero

        # 按 metric 排序（升序）
        hero_stats = dict(sorted(hero_stats.items(), key=lambda item: item[1][0]))
        return [hero_min, hero_max, round(min_metric, 3), round(max_metric, 3), hero_stats]
    
    @staticmethod
    def get_expert_hero(userid=None,time_gap=analyze_time_gap):
        from .ztime import time_r
        from .ztime import time_r_delta

        end_date=time_r()
        start_date=time_r_delta(time_gap)
        analyzed_infos=Analyses.analyze_history(userid=userid,start_date=start_date,end_date=end_date)
        exported={}
        for k,v in analyzed_infos.items(): # 英雄胜率*英雄评分*f(英雄场次)
            if (len(v["hero_info"])==0): continue
            max_factor_hero=""
            max_factor=0
            for heroname,heroinfo in v["hero_info"].items():
                factor=math.pow(heroinfo[3],0.5)*(heroinfo[4])*((math.tanh((heroinfo[1]-5)/3)+1)/2)
                if (factor>max_factor):
                    max_factor=factor
                    max_factor_hero=heroname
            exported[k]=[{max_factor_hero:round(max_factor,3)}]
        # print(exported)
        return exported

    @staticmethod
    def get_extreme_data(time_gap=analyze_time_gap):
        from .ztime import time_r
        from .ztime import time_r_delta

        end_date=time_r()
        start_date=time_r_delta(time_gap)
        history_info,_=fetch_history(userid=None,start_date=start_date,end_date=end_date)
        
        lowest_grade=16
        highest_grade=0
        lowest_player=""
        highest_player=""
        lowest_hero=""
        highest_hero=""

        for playerid,details in history_info.items():
            for detail in details:
                if (check_btl_official_with_matching(detail['MapName'])):
                    detail['GameGrade']=float(detail['GameGrade'])
                    if (detail['GameGrade']<lowest_grade):
                        lowest_grade=detail['GameGrade']
                        lowest_player=playerid
                        lowest_hero=detail['HeroName']
                    if (detail['GameGrade']>highest_grade):
                        highest_grade=detail['GameGrade']
                        highest_player=playerid
                        highest_hero=detail['HeroName']
        # print([lowest_grade,highest_grade,lowest_player,highest_player,lowest_hero,highest_hero])
        return [round(lowest_grade,1),round(highest_grade,1),lowest_player,highest_player,lowest_hero,highest_hero]

    @staticmethod
    def get_intersection_data(time_gap=analyze_time_gap):
        from .ztime import time_r
        from .ztime import time_r_delta

        end_date=time_r()
        start_date=time_r_delta(time_gap)
        history_info,_=fetch_history(userid=None,start_date=start_date,end_date=end_date)

        player_intersection={}
        for playerid_a,details_a in history_info.items():
            for playerid_b,details_b in history_info.items():
                if (playerid_a==playerid_b): continue
                for detail_a in details_a:
                    for detail_b in details_b:
                        if (detail_a['GameSeq']==detail_b['GameSeq']):
                            player_set=frozenset({playerid_a,playerid_b})
                            if (player_set not in player_intersection): player_intersection[player_set]=1/2
                            else: player_intersection[player_set]+=1/2
                            
        player_intersection = dict(sorted(player_intersection.items(), key=lambda item: item[1]))
        # print(player_intersection)
        return player_intersection

def generate_greeting():
    from .ztime import time_r
    current_time = time_r()
    current_hour = current_time.hour
    if 5 <= current_hour < 12:
        greeting = "早上好"
    elif 12 <= current_hour < 14:
        greeting = "中午好"
    elif 14 <= current_hour < 18:
        greeting = "下午好"
    elif 18 <= current_hour < 23:
        greeting = "晚上好"
    else:  # 23:00 - 5:00
        greeting = "这么晚还不睡吗"
    return greeting
def qid2nick(userqid):
    matching_nickname = [key for key, val in qid.items() if str(val) == userqid]
    if (matching_nickname and matching_nickname[0] in namenick):
        return namenick[matching_nickname[0]]
    else:
        return ""
def qid2realname(userqid):
    matching_name = [key for key, val in qid.items() if str(val) == userqid]
    if (matching_name):
        return matching_name[0]
    else:
        return None
def get_emoji(txt):
    from .zapi import ai_api
    from .zfile import readerl

    emojiref=readerl("emojiref.json")
    # print(emojiref)
    emojinew={}
    for k,v in emojiref.items():
        emojinew[k]=v["content"]
    pmpt=emoji_pmpt[0]+emoji_pmpt[1]+str(emojinew)+emoji_pmpt[2]+txt+emoji_pmpt[3]
    res=int(ai_api(pmpt,temperature=2))
    return res
def get_emoji_url(index):
    emoji_url=f"http://{confs["WebService"]["server_domain"]}/doraemon_emojis/{index}.jpg"
    return emoji_url
def extract_url_params(url):
    from urllib.parse import urlparse, parse_qs
    # 解析 URL
    parsed_url = urlparse(url)
    # 提取查询参数并转换为字典
    params = parse_qs(parsed_url.query)
    # 将值从列表转换为单个值（如果参数只有一个值）
    return {key: value[0] if len(value) == 1 else value for key, value in params.items()}
def get_peak_alter_list(details,processed,reverse=1):
    peak_alter_list=[]
    detail_dup=[]
    if (not processed):
        for detail in details:
            if (detail["MapType"]!=-1): continue
            detail_dup.append({"PeakBefore":detail["PeakGradeBeforeGame"],"PeakAfter":detail["PeakGradeAfterGame"],"used":False})
    else:
        for detail in details:
            detail_dup.append({"PeakBefore":detail[0],"PeakAfter":detail[1],"used":False})
    if (reverse==-1): detail_dup=detail_dup[::-1]
    for item_a in detail_dup:
        if (item_a["used"]): continue
        item_a["used"]=True
        PeakBefore=item_a["PeakBefore"]
        PeakAfter=item_a["PeakAfter"]
        for item_b in detail_dup:
            if (item_b["used"]): continue
            if (item_b["PeakBefore"]==PeakAfter): 
                PeakAfter=item_b["PeakAfter"]
                item_b["used"]=True
        peak_alter_list.append([PeakBefore,PeakAfter])
    return peak_alter_list
def extract_name(from_text,precise=False):
    for is_origin in [True,False]:
        for realname,nicknames in nameref.items():
            for nickname in nicknames:
                if txt_contain(nickname,from_text,precise,is_origin):
                    return realname
    for realname,_ in extra_useridlist.items():
        if txt_contain(realname,from_text,p=True,ori=True):
            return realname
    return None
def merge_crossday_gamedata(gamedata):
    if (not gamedata): return {}
    res=gamedata[-1]
    res["gaming_info"]={}
    res["btl_aver"]=0
    if ("roleid" not in res): res["roleid"]=str(roleidlist[res["key"]])
    for daydata in gamedata[-2::-1]:
        res["today_num"]+=daydata["today_num"]
        res["up_tourna"]+=daydata["up_tourna"]
        res["up_peak"]+=daydata["up_peak"]
        for mapname,mapcnt in daydata["map_cnt"].items():
            if (mapname not in res["map_cnt"]):
                res["map_cnt"][mapname]=[0,0]
            res["map_cnt"][mapname][0]+=mapcnt[0]
            res["map_cnt"][mapname][1]+=mapcnt[1]
        for peakdiff in daydata.get("peak_up",[]):
            res["peak_up"].append(peakdiff)
        res["star_up"]+=daydata["star_up"]
        for detail in daydata["details"]:
            res["details"].append(detail)
    if ("peak_up" in res):
        combined_up_peak=get_peak_alter_list(details=res["peak_up"],processed=True)
        res["peak_up"]=combined_up_peak
        combined_up_peak=get_peak_alter_list(details=res["peak_up"],processed=True,reverse=-1)
        res["peak_up"]=combined_up_peak
    else:
        res["peak_up"]=[]
    if ("visible" not in res): res["visible"]=True
    official_btls_grades = [float(btl["GameGrade"]) for btl in res["details"] if check_btl_official_with_matching(btl["MapName"])]
    res["btl_aver"] = sum(official_btls_grades) / len(official_btls_grades) if official_btls_grades else 0
    res["btl_aver"]=round(res["btl_aver"],1)

    return res
def check_btl_official(btlname):
    import re

    btlname=str.lower(btlname)
    if re.search(r'1v1|2v2|3v3', btlname):
        return False
    if re.search(r'排位|巅峰|战队', btlname):
        return True
    return False
def check_btl_official_only_rank(btlname):
    import re

    btlname=str.lower(btlname)
    if re.search(r'1v1|2v2|3v3', btlname):
        return False
    if re.search(r'排位', btlname):
        return True
    return False
def check_btl_official_with_matching(btlname):
    import re

    btlname=str.lower(btlname)
    if re.search(r'1v1|2v2|3v3', btlname):
        return False
    if re.search(r'排位|巅峰|战队|匹配|王者峡谷', btlname):
        return True
    return False
def export_btldetail(gameinfo,roleid):
    from .zfile import writerl
    from .zapi import wzry_get_official
    from .zfile import file_exist
    for btl in gameinfo:
        savepath=os.path.join("history","battles",str(btl["GameSeq"])+".json")
        if (file_exist(savepath) or not check_btl_official_with_matching(btl["MapName"])): continue
        res=wzry_get_official(reqtype="btldetail",roleid=roleid,**btl['Params'])
        writerl(savepath,res)
    return
def extract_heroname(origin_text,precise=False):
    if txt_contain("轮椅",origin_text,precise,True):
        heroid=-1
        while(True):
            heroid = random.choice(list(HeroList))
            heroname=HeroList[heroid]
            if(heroname in ["狂铁","沈梦溪","海诺","曹操","女娲","艾琳","张飞","嫦娥","元流之子(射手)","艾琳","杨戬","盾山","张飞","云缨"]):break
        return heroid,heroname
    if txt_contain("下水道",origin_text,precise,True):
        heroid=-2
        while(True):
            heroid = random.choice(list(HeroList))
            heroname=HeroList[heroid]
            if(heroname in ["安琪拉","马可波罗","扁鹊","钟无艳","伽罗","孙膑","李元芳","赵怀真","周瑜"]):break
        return heroid,heroname
    for is_origin in [True,False]:
        for heroid,heroname in HeroList.items():
            if txt_contain(heroname,origin_text,precise,is_origin):
                return heroid,heroname
        for heroid,heroname in HeroName_replacements.items():
            if txt_contain(heroname,origin_text,precise,is_origin):
                return heroid,HeroList[heroid]
    return None
def txt_contain(x,y,p,ori):
    if (ori):
        if (p):
            return x == y
        else:
            return x in y
    else:
        y_norm = str(y).lower().replace(' ', '')
        if (p):
            return _to_pinyin(x) == _to_pinyin(y_norm)
        else:
            return _to_pinyin(x) in _to_pinyin(y_norm)

async def history_query_handler(rcv_msg):
    from .zapi import ai_api
    from .zfile import get_file_list, readerl
    from .ztime import parse_fuzzy_time
    import json
    import re

    user_msg = rcv_msg.strip()
    # 预替换：将用户常用口语/短语映射为规范查询表达，便于后续AI解析
    alias_map = {
        "带飞": "评分高于",
    }
    # 优先替换较长键以避免短词匹配冲突
    for k in sorted(alias_map.keys(), key=lambda x: -len(x)):
        if k in user_msg:
            user_msg = user_msg.replace(k, alias_map[k])
    
    # 引导AI返回结构化数据
    prompt = f"""
    你是一个针对《王者荣耀》战绩历史查询的助手。请从用户的描述中提取查询条件，并返回一个JSON对象。
    支持的字段如下（如果没提到则为null）：
    - PlayerName: 字符串，查询的主体玩家名称。
    - HeroName: 字符串，指用户自己使用的英雄名称。
    - Result: "胜利" 或 "失败"
    - MapName: 字符串，地图/模式名称，仅限以下选项："排位赛", "排位赛 单排", "排位赛 双排", "排位赛 三排", "排位赛 五排", "匹配", "梦境大乱斗", "火焰山大战", "娱乐模式", "快速赛"
    - GameTime: 字符串，指游戏开始的具体时间，要求格式"yyyy-mm-dd HH:MM"。
    - FuzzyTime: 字符串，模糊时间描述，如"昨天下午","前天凌晨","上周中午"。
    - CoPlayers: 数组，同局玩家 [{{ "Name": "玩家名", "Hero": "英雄名", "Grade": 评分 }}]。
    - KDA: 数组 [击杀, 死亡, 助攻]。
    - GameGrade: 浮点数，指定具体评分(近似)。
    - Duration: 整数，游戏时长(秒)。
    - Others: 字符串列表，包含 "MVP", "超神", "一血" 等关键词。

    // 数值区间查询 (支持 "大于8分", "经济20%以上", "承伤30%到40%","伤害25%左右"(左右表示正负3%))
    - GradeRange: [min, max] 浮点数，评分区间。
    - MoneyRange: [min, max] 整数，经济占比(%)区间(0-100)。
    - DamageRange: [min, max] 整数，伤害(对英雄)占比(%)区间(0-100)。
    - DamageTakenRange: [min, max] 整数，承伤占比(%)区间(0-100)。
    - ContributeRange: [min, max] 浮点数，团队贡献系数区间(通常在0.5-2.0之间)。
    
    // 排名查询 (支持 "评分第一", "全队评分第三")
    - TeamGradeRank: 整数，队内评分排名(1-5)。
    
    // 比较查询 (如"A的评分比B高", "A的经济/伤害/承伤比B高", "A的贡献比B高")
    // Operator 只支持 ">" (高于) 或 "<" (低于)
    - ScoreComparison: {{ "PlayerA": "名字", "PlayerB": "名字", "Operator": ">" }}
    - MoneyComparison: {{ "PlayerA": "名字", "PlayerB": "名字", "Operator": ">" }}
    - DamageComparison: {{ "PlayerA": "名字", "PlayerB": "名字", "Operator": ">" }}
    - DamageTakenComparison: {{ "PlayerA": "名字", "PlayerB": "名字", "Operator": ">" }}
    - ContributeComparison: {{ "PlayerA": "名字", "PlayerB": "名字", "Operator": ">" }}
    
    用户描述：{user_msg}
    对于区间，如果只说"大于X"，则为 [X, 100]；"小于X"，则为 [0, X]。
    //以下是玩家名字的示例，请重点关注：
    //{sum(nameref.values(), [])}
    最终只需返回JSON，不要包含任何解释。
    """
    
    try:
        res_text = ai_api(prompt, temperature=0.1)
        res_text = re.sub(r'```json\n|```', '', res_text).strip()
        query_target = json.loads(res_text)
    except Exception as e:
        return f"查询失败: {str(e)}"
    
    # 预处理
    # 1. 用extract_name解析玩家名字
    PlayerName=None
    if query_target.get("PlayerName"):
        PlayerName = extract_name(query_target["PlayerName"])
        if PlayerName: query_target["PlayerName"] = PlayerName # 更新为标准化名字

    
    # 2. 用extract_heroname解析英雄名称
    if query_target.get("HeroName"):
        herores = extract_heroname(query_target["HeroName"])
        if herores: query_target["HeroName"] = herores[1]
    
    # 3. 解析同局玩家 (名字->RoleId, 英雄名标准化)
    if query_target.get("CoPlayers"):
        for player in query_target["CoPlayers"]:
            # 英雄名标准化
            if player.get("Hero"):
                herores = extract_heroname(player["Hero"])
                if herores: player["Hero"] = herores[1]
            
            # 玩家名 -> 真实名 -> RoleId
            if player.get("Name"):
                rname = extract_name(player["Name"])
                if rname:
                    player["RealName"] = rname
                    player["Name"] = namenick.get(rname, rname)
                    # 从 roleidlist 获取 RoleId
                    if rname in roleidlist:
                        player["RoleId"] = roleidlist[rname]
                    elif rname in extra_roleidlist:
                        player["RoleId"] = extra_roleidlist[rname]

    # 4. 解析 Comparison 中的名字
    comparison_fields = ["ScoreComparison", "MoneyComparison", "DamageComparison", "DamageTakenComparison", "ContributeComparison"]
    for field in comparison_fields:
        if query_target.get(field):
            sc = query_target[field]
            if sc.get("PlayerA"):
                pn = extract_name(sc["PlayerA"])
                if pn: sc["PlayerA"] = pn
                
            if sc.get("PlayerB"):
                pn = extract_name(sc["PlayerB"])
                if pn: sc["PlayerB"] = pn

    # 5. MapName 映射逻辑
    map_targets = []
    if query_target.get("MapName"):
        mn = query_target["MapName"]
        if mn == "排位赛":
            map_targets = ["排位赛", "排位赛 双排", "排位赛 三排", "排位赛 五排"]
        elif mn == "排位赛 单排":
            map_targets = ["排位赛"]
        elif mn == "匹配": # 匹配对应到王者峡谷
            map_targets = ["王者峡谷"]
        elif mn in ["娱乐", "娱乐模式"]: # 娱乐模式映射
            map_targets = ["梦境大乱斗", "火焰山大战","无限乱斗"]
        else:
            map_targets = [mn]
    
    # 将查询条件转换为自然语言描述
    desc_parts = []
    if query_target.get("PlayerName"):
        nick = namenick.get(query_target["PlayerName"], query_target["PlayerName"])
        desc_parts.append(f"玩家: {nick}")

    if query_target.get("GradeRange"):
        desc_parts.append(f"评分区间: {query_target['GradeRange']}")
    if query_target.get("MoneyRange"):
        desc_parts.append(f"经济: {query_target['MoneyRange']}")
    if query_target.get("DamageRange"):
        desc_parts.append(f"伤害: {query_target['DamageRange']}")
    if query_target.get("DamageTakenRange"):
        desc_parts.append(f"承伤: {query_target['DamageTakenRange']}")
    if query_target.get("ContributeRange"):
        desc_parts.append(f"贡献: {query_target['ContributeRange']}")
    if query_target.get("TeamGradeRank"):
        desc_parts.append(f"评分排名: 第{query_target['TeamGradeRank']}")
    comparison_labels = {
        "ScoreComparison": "评分",
        "MoneyComparison": "经济占比",
        "DamageComparison": "伤害占比",
        "DamageTakenComparison": "承伤占比",
        "ContributeComparison": "贡献"
    }
    for field, label in comparison_labels.items():
        if query_target.get(field):
            sc = query_target[field]
            nickA = namenick.get(sc.get('PlayerA'), sc.get('PlayerA'))
            nickB = namenick.get(sc.get('PlayerB'), sc.get('PlayerB'))
            op = "高于" if sc.get('Operator') == ">" else "低于"
            desc_parts.append(f"{label}比较: {nickA} {op} {nickB}")
    
    if query_target.get("FuzzyTime"):

        desc_parts.append(f"模糊时间: {query_target['FuzzyTime']}")
    elif query_target.get("GameTime"):
        desc_parts.append(f"具体时间: {query_target['GameTime']}")
        
    if query_target.get("HeroName"):
        desc_parts.append(f"英雄: {query_target['HeroName']}")
        
    if query_target.get("CoPlayers"):
        cp_texts = []
        for p in query_target["CoPlayers"]:
            p_text = f"{p.get('Name','未知')}"
            if p.get('Hero'): p_text += f"({p['Hero']})"
            if p.get('Grade'): p_text += f"[{p['Grade']}分]"
            cp_texts.append(p_text)
        desc_parts.append(f"同局: {', '.join(cp_texts)}")

    if query_target.get("MapName"):
        desc_parts.append(f"地图: {query_target['MapName']}")
        
    if query_target.get("Result"):
        desc_parts.append(f"结果: {query_target['Result']}")
        
    if query_target.get("KDA"):
        try:
            k, d, a = query_target["KDA"]
            desc_parts.append(f"KDA约: {k}/{d}/{a}")
        except: pass
        
    if query_target.get("GameGrade"):
        desc_parts.append(f"评分约: {query_target['GameGrade']}")
        
    if query_target.get("Duration"):
        try:
            mins = query_target["Duration"] // 60
            secs = query_target["Duration"] % 60
            desc_parts.append(f"时长约: {mins}分{secs}秒")
        except: pass
        
    if query_target.get("Others"):
        desc_parts.append(f"其他: {' '.join(query_target['Others'])}")
        
    query_desc = " | ".join(desc_parts) if desc_parts else "全量查询"

    # 至少指定2个条件
    condition_count = 0
    for k, v in query_target.items():
        if k == "CoPlayers" and isinstance(v, list):
            condition_count += len(v)
        elif v:
            condition_count += 1
    if condition_count < 1:
        return [query_target, f"至少指定1个查询条件", query_desc, {}]

    matches = []
    
    # 解析时间范围
    start_date, end_date = None, None
    fetch_start, fetch_end = None, None
    if query_target.get("FuzzyTime"):
        try:
            start_date, end_date = parse_fuzzy_time(query_target["FuzzyTime"])
            # fetch_history 按日期过滤，所以传整天
            fetch_start = start_date.replace(hour=0, minute=0, second=0)
            fetch_end = end_date.replace(hour=23, minute=59, second=59)
        except:
            pass

    # 获取所有玩家的指定时间对局记录
    history_data, _ = fetch_history(start_date=fetch_start, end_date=fetch_end, filter_official=False) 
    
    for realname, details in history_data.items():
        # 如果指定玩家名且不匹配，则continue
        if PlayerName and realname != PlayerName:
            continue
            
        for detail in details:
            is_match = True
            
            # 英雄名 (_to_pinyin)
            if query_target.get("HeroName"):
                if _to_pinyin(query_target["HeroName"]) not in _to_pinyin(detail.get("HeroName", "")):
                    is_match = False
            
            # 地图名 (包含匹配与映射)
            if is_match and map_targets:
                if not any(target == detail.get("MapName", "") for target in map_targets):
                    is_match = False
            
            # 评分区间 (无需详情)
            if is_match and query_target.get("GradeRange"):
               try:
                   grade = float(detail.get("GameGrade", -1))
                   mn, mx = map(float, query_target["GradeRange"])
                   if not (mn <= grade <= mx):
                       is_match = False
               except:
                   is_match = False

            
            btl_detail = None
            all_roles = None

            # ------------------------------------------------------------------
            # (1) 同局玩家查询 (CoPlayers)
            # ------------------------------------------------------------------
            if is_match and query_target.get("CoPlayers"):
                btl_detail = fetch_battle(detail["GameSeq"])
                if (not btl_detail): # 由于从1月份才开始保存battle_info
                    is_match = False # 如果指定了队友/对手，并且对局记录不存在，则直接忽略该对局
                else:
                    # 获取红蓝双方所有玩家
                    all_roles = btl_detail.get('redRoles', []) + btl_detail.get('blueRoles', [])
                    
                    found_all_coplayers = True
                    for target_p in query_target["CoPlayers"]:
                        found_this = False
                        for role in all_roles:
                            # 1. 名字/RoleId 匹配
                            if target_p.get("RoleId"):
                                if str(role.get('basicInfo', {}).get('roleId', '')) != str(target_p["RoleId"]):
                                    continue
                            elif target_p.get("Name"):
                                role_name = role.get('basicInfo', {}).get('roleName', '')
                                if target_p["Name"] not in role_name:
                                    continue

                            # 2. 英雄匹配 (已标准化)
                            used_hero = role.get('battleRecords', {}).get('usedHero', {}).get('heroName', '')
                            if target_p.get("Hero"):
                                # 此处使用标准化后的名称进行对比，所以用精确匹配或拼音匹配
                                if _to_pinyin(target_p["Hero"]) not in _to_pinyin(used_hero):
                                    # 再尝试一下模糊包含
                                    if not txt_contain(target_p["Hero"], used_hero, False, False):
                                        continue
                                
                            # 3. 评分匹配 (误差0.5以内)
                            if target_p.get("Grade"):
                                try:
                                    role_grade = float(role.get('battleStats', {}).get('gradeGame', -1))
                                    target_grade = float(target_p["Grade"])
                                    if abs(role_grade - target_grade) > 0.5: 
                                        continue
                                except:
                                    continue
                                    
                            found_this = True
                            break
                        
                        if not found_this:
                            found_all_coplayers = False
                            break
                    
                    if not found_all_coplayers:
                        is_match = False

            # ------------------------------------------------------------------
            # (2) 详细数据查询 (Money, Damage, Rank, Comparison)
            # ------------------------------------------------------------------
            need_advanced_stats = (
                query_target.get("MoneyRange") or 
                query_target.get("DamageRange") or 
                query_target.get("DamageTakenRange") or
                query_target.get("ContributeRange") or
                query_target.get("TeamGradeRank") or
                query_target.get("ScoreComparison") or
                query_target.get("MoneyComparison") or
                query_target.get("DamageComparison") or
                query_target.get("DamageTakenComparison") or
                query_target.get("ContributeComparison")
            )

            if is_match and need_advanced_stats:
                if not btl_detail:
                    btl_detail = fetch_battle(detail["GameSeq"])
                    if btl_detail:
                        all_roles = btl_detail.get('redRoles', []) + btl_detail.get('blueRoles', [])

                if (not btl_detail):
                    is_match = False
                else:
                    # 找到自己的Role (用于后续统计)
                    my_role = None
                    target_role_id = roleidlist.get(realname)
                    if target_role_id:
                        for r in all_roles:
                             if str(r.get("basicInfo",{}).get("roleId")) == str(target_role_id):
                                 my_role = r
                                 break
                    
                    if is_match and my_role:
                        my_camp = my_role.get("basicInfo", {}).get("acntCamp")
                        team_roles = [r for r in all_roles if r.get("basicInfo", {}).get("acntCamp") == my_camp]
                        
                        stats = my_role.get("battleStats", {})
                        
                        # 经济占比区间
                        if query_target.get("MoneyRange"):
                            # try:
                            total_money = sum(float(r.get("battleStats", {}).get("money", 0)) for r in team_roles)
                            my_val = float(stats.get("money", 0))
                            percent = (my_val / total_money * 100) if total_money > 0 else 0
                            mn, mx = map(float, query_target["MoneyRange"])
                            if not (mn <= percent <= mx): is_match = False
                            # except: is_match = False
                        
                        # 伤害占比区间
                        if is_match and query_target.get("DamageRange"):
                            # try:
                            total_hurt = sum(float(r.get("battleStats", {}).get("totalHeroHurtCnt", 0)) for r in team_roles)
                            my_val = float(stats.get("totalHeroHurtCnt", 0))
                            percent = (my_val / total_hurt * 100) if total_hurt > 0 else 0
                            mn, mx = map(float, query_target["DamageRange"])
                            if not (mn <= percent <= mx): is_match = False
                            # except: is_match = False
                                
                        # 承伤占比区间
                        if is_match and query_target.get("DamageTakenRange"):
                            # try:
                            total_behurt = sum(float(r.get("battleStats", {}).get("totalBeheroHurtCnt", 0)) for r in team_roles)
                            my_val = float(stats.get("totalBeheroHurtCnt", 0))
                            percent = (my_val / total_behurt * 100) if total_behurt > 0 else 0
                            mn, mx = map(float, query_target["DamageTakenRange"])
                            if not (mn <= percent <= mx): is_match = False
                            # except: is_match = False

                        # 贡献度系数区间
                        if is_match and query_target.get("ContributeRange"):
                            try:
                                total_grade = sum(float(r.get("battleStats", {}).get("gradeGame", 0)) for r in team_roles)
                                total_money = sum(float(r.get("battleStats", {}).get("money", 0)) for r in team_roles)
                                my_grade = float(stats.get("gradeGame", 0))
                                my_money = float(stats.get("money", 0))
                                
                                if total_grade > 0 and total_money > 0 and my_money > 0:
                                    # factor = (5 * my_grade / total_grade) * pow((5 * my_money / total_money), -0.5)
                                    term1 = (5 * my_grade / total_grade)
                                    term2 = pow((5 * my_money / total_money), -0.5)
                                    factor = term1 * term2
                                    mn, mx = map(float, query_target["ContributeRange"])
                                    if not (mn <= factor <= mx): is_match = False
                                else:
                                    is_match = False
                            except: is_match = False
                        
                        # 队内评分排名
                        if is_match and query_target.get("TeamGradeRank"):
                            try:
                                # 按评分降序
                                team_roles.sort(key=lambda x: float(x.get("battleStats", {}).get("gradeGame", -1)), reverse=True)
                                
                                my_rank = -1
                                for i, r in enumerate(team_roles):
                                    if r == my_role:
                                        my_rank = i + 1
                                        break
                                
                                target_rank = int(query_target["TeamGradeRank"])
                                if my_rank != target_rank:
                                    is_match = False
                            except: is_match = False

                    # 属性比较
                    if is_match:
                        def get_role_by_name(p_name):
                            rid = roleidlist.get(p_name) or extra_roleidlist.get(p_name)
                            for r in all_roles:
                                if rid:
                                    if str(r.get("basicInfo",{}).get("roleId")) == str(rid):
                                        return r
                                elif p_name and p_name in r.get("basicInfo", {}).get("roleName", ""):
                                    return r
                            return None

                        def get_stat_value(role, field_name):
                            stats = role.get("battleStats", {})
                            if field_name == "ScoreComparison":
                                return float(stats.get("gradeGame", -1))
                            
                            # 获取队伍总和
                            camp = role.get("basicInfo", {}).get("acntCamp")
                            t_roles = [x for x in all_roles if x.get("basicInfo", {}).get("acntCamp") == camp]
                            
                            if field_name == "MoneyComparison":
                                total = sum(float(x.get("battleStats", {}).get("money", 0)) for x in t_roles)
                                return (float(stats.get("money", 0)) / total * 100) if total > 0 else 0
                            elif field_name == "DamageComparison":
                                total = sum(float(x.get("battleStats", {}).get("totalHeroHurtCnt", 0)) for x in t_roles)
                                return (float(stats.get("totalHeroHurtCnt", 0)) / total * 100) if total > 0 else 0
                            elif field_name == "DamageTakenComparison":
                                total = sum(float(x.get("battleStats", {}).get("totalBeheroHurtCnt", 0)) for x in t_roles)
                                return (float(stats.get("totalBeheroHurtCnt", 0)) / total * 100) if total > 0 else 0
                            elif field_name == "ContributeComparison":
                                total_g = sum(float(x.get("battleStats", {}).get("gradeGame", 0)) for x in t_roles)
                                total_m = sum(float(x.get("battleStats", {}).get("money", 0)) for x in t_roles)
                                my_g = float(stats.get("gradeGame", 0))
                                my_m = float(stats.get("money", 0))
                                if total_g > 0 and total_m > 0 and my_m > 0:
                                    return (5 * my_g / total_g) * pow((5 * my_m / total_m), -0.5)
                                return 0
                            return -1

                        comp_fields = ["ScoreComparison", "MoneyComparison", "DamageComparison", "DamageTakenComparison", "ContributeComparison"]
                        for field in comp_fields:
                            if is_match and query_target.get(field):
                                try:
                                    sc = query_target[field]
                                    pa, pb, op = sc.get("PlayerA"), sc.get("PlayerB"), sc.get("Operator")
                                    roleA, roleB = get_role_by_name(pa), get_role_by_name(pb)

                                    if roleA and roleB:
                                        valA = get_stat_value(roleA, field)
                                        valB = get_stat_value(roleB, field)
                                        
                                        if op == ">" and not (valA > valB): is_match = False
                                        elif op == "<" and not (valA < valB): is_match = False
                                    else: is_match = False
                                except: is_match = False

            # 输赢
            if is_match and query_target.get("Result"):
                if query_target["Result"] not in detail.get("Result", ""):
                    is_match = False
            
            # KDA (略微近似, 每个值差值<=1)
            if is_match and query_target.get("KDA"):
                try:
                    tk, td, ta = query_target["KDA"]
                    dk, dd, da = detail.get("KillCnt", 0), detail.get("DeadCnt", 0), detail.get("AssistCnt", 0)
                    if abs(int(tk) - int(dk)) > 1 or abs(int(td) - int(dd)) > 1 or abs(int(ta) - int(da)) > 1:
                        is_match = False
                except:
                    pass
            
            # 评分 (略微近似, 差值<=0.5)
            if is_match and query_target.get("GameGrade"):
                try:
                    if abs(float(detail.get("GameGrade", 0)) - float(query_target["GameGrade"])) > 0.5:
                        is_match = False
                except:
                    pass
            
            # 时长 (略微近似, 差值<=60s)
            if is_match and query_target.get("Duration"):
                try:
                    if abs(int(detail.get("Duration_Second", 0)) - int(query_target["Duration"])) > 60:
                        is_match = False
                except:
                    pass
            
            # 游戏时间 (支持 30 分钟偏差)
            if is_match and query_target.get("GameTime"):
                t_time_str = str(query_target["GameTime"])
                match_time = re.search(r'(\d{1,2}:\d{1,2})', t_time_str)
                if match_time:
                    t_hhmm = match_time.group(1)
                    d_time_str = str(detail.get("GameTime", ""))
                    match_time_d = re.search(r'(\d{1,2}:\d{1,2})', d_time_str)
                    
                    if match_time_d:
                        d_hhmm = match_time_d.group(1)
                        try:
                            th, tm = map(int, t_hhmm.split(":"))
                            dh, dm = map(int, d_hhmm.split(":"))
                            diff = abs((th * 60 + tm) - (dh * 60 + dm))
                            if diff > 12 * 60:
                                diff = 24 * 60 - diff
                            
                            if diff > 30:
                                is_match = False
                        except:
                            if t_hhmm not in d_time_str:
                                is_match = False
                    elif t_hhmm not in d_time_str:
                        is_match = False
            
            # 如果有 FuzzyTime, 还需要额外过滤具体时间点 (fetch_history 只按日期过滤)
            if is_match and start_date and end_date:
                detail_time_str = str(detail.get("GameTime", ""))
                if detail_time_str:
                    try:
                        from datetime import datetime
                        # 尝试匹配完整日期格式 yyyy-mm-dd HH:MM
                        full_match = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2}):(\d{1,2})', detail_time_str)
                        current_detail_dt = None
                        
                        if full_match:
                            y, m, d, H, M = map(int, full_match.groups())
                            current_detail_dt = datetime(y, m, d, H, M)
                        else:
                            # 尝试匹配 HH:MM
                            time_match = re.search(r'(\d{1,2}):(\d{1,2})', detail_time_str)
                            if time_match:
                                dt_h, dt_m = map(int, time_match.groups())
                                current_detail_dt = start_date.replace(hour=dt_h, minute=dt_m)
                        
                        if current_detail_dt:
                            if not (start_date <= current_detail_dt <= end_date):
                                is_match = False
                    except:
                        pass

            # Others (MVP/超神/一血)
            if is_match and query_target.get("Others"):
                d_others = detail.get("Others", "")
                for keyword in query_target["Others"]:
                    if keyword not in d_others:
                        is_match = False
                        break
            
            if is_match:
                matches.append([detail, realname])
    
    # 去重: 对于gameseq相同的对局只保留一份
    unique_matches = []
    seen_gameseqs = set()
    for m in matches:
        # m[0] is detail
        gs = m[0].get("GameSeq")
        if gs and gs not in seen_gameseqs:
            seen_gameseqs.add(gs)
            unique_matches.append(m)
    matches = unique_matches

    # 统计数据
    stats = {}
    if matches:
        total = len(matches)
        wins = sum(1 for m, _ in matches if "胜利" in m.get("Result", ""))
        total_grade = sum(float(m.get("GameGrade", 0)) for m, _ in matches)
        total_k = sum(int(m.get("KillCnt", 0)) for m, _ in matches)
        total_d = sum(int(m.get("DeadCnt", 0)) for m, _ in matches)
        total_a = sum(int(m.get("AssistCnt", 0)) for m, _ in matches)
        
        stats = {
            "total": total,
            "wins": wins,
            "win_rate": (wins / total * 100) if total > 0 else 0,
            "avg_grade": (total_grade / total) if total > 0 else 0,
            "total_k": total_k,
            "total_d": total_d,
            "total_a": total_a,
            "avg_kda": (total_k + total_a) / max(total_d, 1)
        }

    return [query_target, matches, query_desc, stats]
