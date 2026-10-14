"""Player battle-list collection and daily export workflows."""

import json
import logging

from .. import zdynamic as dmc
from .. import zdb, zfile, ztime
from ..zstatic import fin, mapname_replace_rule, ranklist


def _runtime():
    from .. import zfunc

    return zfunc


def wzry_data(realname,savepath=None,target_userid=None,target_roleid=None,target_date=None,sync_battle_visibility=False): # 单人的战绩parser
    runtime = _runtime()
    def get_star_today_most_recent(today_details):
        for detail in today_details[::-1]:
            if (detail["MapType"]==1):
                return detail["StarAfterGame"]
        return -1

    def get_star_before_today_most_recent(target_id, target_date_obj=None):
        if target_date_obj:
            today_dt = ztime.datetime_from_parts(target_date_obj.year, target_date_obj.month, target_date_obj.day)
            yesterday_sul = ztime.time_delta(today_dt, -1)
        else:
            yesterday_sul = ztime.time_delta(ztime.time_sul(), -1)
        try:
            database_star = zdb.latest_rank_star_before(target_id, yesterday_sul.strftime("%Y-%m-%d"))
            if database_star is not None:
                return database_star
        except Exception as exc:
            runtime.log_message(
                f"POSTGRES_LATEST_STAR_FALLBACK: userid={target_id} before={yesterday_sul} error={repr(exc)}",
                logging.WARNING,
            )

        for history_date in zfile.list_history_dates_descending():
            if history_date > yesterday_sul.strftime("%Y-%m-%d"):
                continue
            for player in zfile.read_history_date(history_date):
                if int(player["id"]) != int(target_id):
                    continue
                for detail in player["details"][::-1]:
                    if detail["MapType"] == 1:
                        return detail["StarAfterGame"]
        return -1

    runtime.log_message("VISIT: wzry_data")

    userid=target_userid if target_userid else runtime.userlist[realname]
    roleid=target_roleid if target_roleid else runtime.roleidlist[realname]

    btlist_data=runtime.wzry_get_official(reqtype="btlist",userid=userid,roleid=roleid)
    profile_data=runtime.wzry_get_official(reqtype="profile",userid=userid,roleid=roleid)
    res = {
        "btlist": btlist_data,
        "profile": profile_data
    }

    if (savepath):
        zfile.writerl(savepath,res)
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
    if sync_battle_visibility:
        runtime.sync_battle_visibility_state(realname, BtlVisible)
    isGaming=res["btlist"]["isGaming"] and res["btlist"]["gaming"]
    real_date=ztime.time_r().strftime("%m-%d")
    sul_time=ztime.time_sul()
    target_date_obj = ztime.str_to_time(target_date).date() if target_date else sul_time.date()
    starUp=starNum-(dmc.infolast.get(realname,{}).get("star",0)) # 如果战绩不可见 使用该算法强行填充
    peakUp=[]
    today_num=totalNum-(dmc.infolast.get(realname,{}).get("total_num",0)) # 如果战绩不可见 使用该算法强行填充
    today_up_tourna=fin
    today_up_peak=fin
    today_btl_aver=fin # 今日平均评分
    today_btl_contribute_aver=fin # 今日平均贡献
    today_details=[] # 今日所有战局
    today_game_cnt={} # 今日每个地图局数
    gaming_info={} # 当前正在进行的游戏信息
    if(BtlVisible):
        from ..tools.representative_battle import build_battle_keywords

        today_btl = [game for game in res['btlist']['list'] if (ztime.time_sul(ztime.stamp_to_time(int(game['dtEventTime']))).date()==target_date_obj)]
        # today_btl = [game for game in res['btlist']['list'] if (ztime.time_sul(ztime.stamp_to_time(int(game['dtEventTime']))).date()==date_roleback().date())]
        today_details=[{\
            'GameTime':game['gametime'],\
            'GameTime_Timestamp':int(game['dtEventTime']),\
            'HeroName':runtime.safe_hero_name(game.get('heroId')),\
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
            'Params':runtime.extract_url_params(game['detailUrl']),\
            'Others':build_battle_keywords(game)\
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
        star_before_today_most_recent=get_star_before_today_most_recent(userid, target_date_obj)
        # print(star_today_most_recent,star_before_today_most_recent)
        starUp= 0 if (star_today_most_recent==-1) else (star_today_most_recent-star_before_today_most_recent)
        # except Exception as e:
        #     _runtime().log_message(str(e))
        peakUp=runtime.get_peak_alter_list(details=today_details,processed=False)
        gamegrades = [
            round(float(game["gradeGame"]), 1)
            for game in today_btl
            if runtime.check_btl_official(game["mapName"])
        ]
        today_btl_aver = round(sum(gamegrades) / len(gamegrades), 3) if gamegrades else 0
        today_btl_max=-fin if len(gamegrades)==0 else max(gamegrades)
        today_btl_min= fin if len(gamegrades)==0 else min(gamegrades)

    if (isGaming):
        gaming_info={
                    "in_game":True,\
                    "map_name":res["btlist"]["gaming"]["mapName"],\
                    "hero_name":runtime.safe_hero_name(res["btlist"]["gaming"].get("heroId")),\
                    "duration_minute":res["btlist"]["gaming"]["duration"],\
                    "battle_num_this_hero":res["btlist"]["gaming"]["gameNum"],\
                    "win_rate_this_hero":res["btlist"]["gaming"]["winRate"],\
                    "can_be_watched":res["btlist"]["gaming"]["canBeWatch"],\
                    "battle_id":res["btlist"]["gaming"]["battleId"],\
        }
    # export_btl_thread = threading.Thread(target=export_btldetail, args=(gameinfo=today_details))
    # export_btl_thread.start()
    unaccessible_battles=runtime.export_btldetail(today_details,roleid)
    enrich_battle_list_skills_from_cache(res, roleid)
    if savepath:
        zfile.writerl(savepath, res)
    if (BtlVisible):
        today_btl_contribute_aver = runtime.calculate_official_battle_contribution_average(today_details, roleid)
    return {"id":userid,"roleid":roleid,"key":realname,"nickname":nickname,"date":str(real_date),"today_num":today_num,"rank_name":rankName,"rank_star":rankStar,"total_num":totalNum,"up_tourna":today_up_tourna,"up_peak":today_up_peak,"map_cnt":today_game_cnt,"btl_aver":today_btl_aver,"btl_contribute_aver":today_btl_contribute_aver,"rank":rankName,"star":starNum,"star_up":starUp,"peak_up":peakUp,"details":today_details,"gaming_info":gaming_info,"visible":BtlVisible,"unaccessible_battles":unaccessible_battles}

def enrich_battle_list_skills_from_cache(payload, roleid):
    """从本地战局详情为单人战绩卡片补齐召唤师技能。"""
    battle_list = payload.get("btlist", {}).get("list", [])
    for battle in battle_list:
        if battle.get("skill", {}).get("skillIcon"):
            continue
        detail = zfile.read_battle_detail(battle.get("gameSeq"))
        if not detail:
            continue
        for player in detail.get("redRoles", []) + detail.get("blueRoles", []):
            if str(player.get("basicInfo", {}).get("roleId")) != str(roleid):
                continue
            skill = player.get("battleRecords", {}).get("skill", {}) or {}
            if skill.get("skillIcon"):
                battle["skill"] = {
                    "skillId": skill.get("skillId"),
                    "skillIcon": skill.get("skillIcon", ""),
                    "skillName": skill.get("skillName", ""),
                }
            break


def dump_specific_user(userid, roleid, target_date):
    """
    模仿zscheduler中的dump_today，调用wzry_data函数导出具体用户、具体日期的数据。
    :param userid: 指定的用户ID
    :param roleid: 指定的角色ID
    :param target_date: 导出的日期，格式为 '%Y-%m-%d' (精确到天)
    """
    _runtime().log_message(f"DUMPBEGIN specific user {userid} date: {target_date}.json")

    # 获取真正的realname (key)
    realname = "unknown"
    for k, v in _runtime().userlist.items():
        if v == userid:
            realname = k
            break

    gameinfo = []
    try:
        data = _runtime().wzry_data(
            realname=realname,
            savepath=zfile.personal_history_path(target_date, userid),
            target_userid=userid,
            target_roleid=roleid,
            target_date=target_date
        )
        gameinfo.append(data)
    except Exception as e:
        _runtime().log_message(f"Dump specific user {userid} failed: {e}")

    aggregated_filename = zfile.daily_history_path(target_date)
    try:
        existing_data = zfile.read_history_date(target_date) or []
        existing_data = [d for d in existing_data if str(d.get("id")) != str(userid)]
        existing_data.extend(gameinfo)
        zfile.writerl(aggregated_filename, existing_data)
    except Exception as e:
        _runtime().log_message(f"Failed to update aggregated file {aggregated_filename}: {e}")

    _runtime().log_message(f"DUMPEND specific user {userid} date: {target_date}.json")
    return gameinfo[0]


def export_battle_details(gameinfo, roleid):
    runtime = _runtime()
    inaccessible_battles = []
    for battle in gameinfo:
        gameseq = battle["GameSeq"]
        if zfile.battle_detail_exists(gameseq):
            continue
        if not runtime.check_btl_official_with_matching_with_entertain(
            battle["MapName"]
        ):
            continue
        try:
            response = runtime.wzry_get_official(
                reqtype="btldetail",
                roleid=roleid,
                **battle["Params"],
            )
            zfile.writerl(zfile.battle_detail_path(gameseq), response)
        except Exception as exc:
            inaccessible_battles.append(
                {
                    "roleid": roleid,
                    "GameSeq": gameseq,
                    "Error": str(exc),
                }
            )
    return inaccessible_battles
