"""Battle classification and contribution metrics."""

import re

from ..zstatic import roleidlist


def _zfunc_call(name, *args, **kwargs):
    from .. import zfunc

    return getattr(zfunc, name)(*args, **kwargs)


def get_peak_alter_list(*args, **kwargs):
    return _zfunc_call("get_peak_alter_list", *args, **kwargs)


def fetch_battle(*args, **kwargs):
    return _zfunc_call("fetch_battle", *args, **kwargs)

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
    res["btl_aver"] = calculate_official_battle_average(res["details"])
    res["btl_contribute_aver"] = calculate_official_battle_contribution_average(res["details"], res["roleid"])

    return res
def calculate_official_battle_average(details):
    official_btls_grades = [
        float(btl["GameGrade"])
        for btl in details
        if check_btl_official(btl["MapName"]) and not btl.get("GradeMissing")
    ]
    average = sum(official_btls_grades) / len(official_btls_grades) if official_btls_grades else 0
    return round(average, 3)
def _battle_all_roles(battle_detail):
    return battle_detail.get("redRoles", []) + battle_detail.get("blueRoles", [])
def _find_battle_role(battle_detail, roleid=None, userid=None):
    for role in _battle_all_roles(battle_detail):
        basic_info = role.get("basicInfo", {})
        if roleid is not None and str(basic_info.get("roleId")) == str(roleid):
            return role
        if userid is not None and str(basic_info.get("userId")) == str(userid):
            return role
    return None
def _battle_role_has_assist_equip(role):
    for equipment in role.get("battleRecords", {}).get("finalEquips", []):
        equip_name = equipment.get("equipName", "")
        if any(keyword in equip_name for keyword in {"学识宝石", "近卫", "极影"}):
            return True
    return False
def calculate_battle_contribution_factor(battle_detail, roleid=None, userid=None, role=None):
    head = battle_detail.get("head", {})
    target_role = role or _find_battle_role(
        battle_detail,
        roleid=roleid if roleid is not None else head.get("roleId"),
        userid=userid if userid is not None else head.get("userId"),
    )
    if not target_role:
        return None
    target_camp = target_role.get("basicInfo", {}).get("acntCamp")
    team_roles = [
        item for item in _battle_all_roles(battle_detail)
        if item.get("basicInfo", {}).get("acntCamp") == target_camp
    ]
    if not team_roles:
        return None
    stats = target_role.get("battleStats", {})
    my_grade = float(stats.get("gradeGame", 0))
    my_money = float(stats.get("money", 0))
    team_total_grade = sum(float(item.get("battleStats", {}).get("gradeGame", 0)) for item in team_roles)
    team_total_money = sum(float(item.get("battleStats", {}).get("money", 0)) for item in team_roles)
    if team_total_grade <= 0 or team_total_money <= 0 or my_money <= 0:
        return None
    money_ratio = 5 * my_money / team_total_money
    if _battle_role_has_assist_equip(target_role):
        money_ratio /= 0.9
    return (5 * my_grade / team_total_grade) * pow(money_ratio, -0.5)
def calculate_official_battle_contribution_average(details, roleid):
    official_btls_contributes = []
    for btl in details:
        if btl.get("Source") == "player_client" or not check_btl_official(btl.get("MapName", "")):
            continue
        gameseq = btl.get("GameSeq")
        if not gameseq:
            continue
        battle_detail = fetch_battle(gameseq, roleid)
        if not battle_detail:
            continue
        contribution = calculate_battle_contribution_factor(battle_detail, roleid=roleid)
        if contribution is not None:
            official_btls_contributes.append(contribution)
    average = sum(official_btls_contributes) / len(official_btls_contributes) if official_btls_contributes else 0
    return round(average, 3)
def check_btl_official(btlname):
    btlname=str.lower(btlname)
    if re.search(r'1v1|2v2|3v3', btlname):
        return False
    if re.search(r'排位|巅峰|战队', btlname):
        return True
    return False
def check_btl_official_only_rank(btlname):
    btlname=str.lower(btlname)
    if re.search(r'1v1|2v2|3v3', btlname):
        return False
    if re.search(r'排位', btlname):
        return True
    return False
def check_btl_official_with_matching(btlname):
    btlname=str.lower(btlname)
    if re.search(r'1v1|2v2|3v3', btlname):
        return False
    if re.search(r'排位|巅峰|战队|匹配|王者峡谷', btlname):
        return True
    return False
def check_btl_official_with_matching_with_entertain(btlname):
    btlname=str.lower(btlname)
    if re.search(r'1v1|2v2|3v3', btlname):
        return False
    if re.search(r'排位|巅峰|战队|匹配|王者峡谷|梦境|火焰山|无限乱斗', btlname):
        return True
    return False
