
from .zutil import *
from .zstatic import *
from . import zdynamic as dmc

import redis
from wcwidth import wcswidth
import math
from concurrent.futures import ThreadPoolExecutor, as_completed

_BATTLE_INVISIBLE_DISABLED_QIDS_REDIS_KEY = "hok:battle:invisible_disabled_qids"
_GROUP_CHAT_HISTORY_REDIS_PREFIX = "hok:chat:group:"


def _redis_get_json(key, default=None):
    raw = dmc.redis_deamon.get(key)
    if not raw:
        return default
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def _redis_set_json(key, value):
    dmc.redis_deamon.set(key, json.dumps(value, ensure_ascii=False))


def _wait_official_low_priority_turn():
    """Yield background official-API work to interactive web queues."""
    from .ztime import current_timestamp, sleep_seconds

    while True:
        now = current_timestamp()
        active_until = getattr(dmc, "OfficialForegroundActiveUntil", 0)
        if now < active_until:
            sleep_seconds(min(active_until - now, 3))
            continue
        try:
            if dmc.redis_deamon.llen(REDIS_KEY_BATTLE_SHARE_QUEUE):
                sleep_seconds(3)
                continue
            if dmc.redis_deamon.llen(REDIS_KEY_BATTLE_ANALYZE_QUEUE):
                sleep_seconds(3)
                continue
        except Exception as error:
            log_message(f"OFFICIAL_LOW_PRIORITY_QUEUE_CHECK_ERROR: {error}")
        wait_seconds = (
            getattr(dmc, "OfficialLowPriorityLastVisitAt", 0)
            + 5
            - current_timestamp()
        )
        if wait_seconds > 0:
            sleep_seconds(wait_seconds)
            continue
        dmc.OfficialLowPriorityLastVisitAt = current_timestamp()
        return


def wzry_get_official(*args, priority="normal", **kwargs):
    """Apply business priority rules, then call the stateless API adapter."""
    from . import zapi
    from .ztime import current_timestamp

    if priority == "low":
        _wait_official_low_priority_turn()
    else:
        dmc.OfficialForegroundActiveUntil = current_timestamp() + 5
    return zapi.wzry_get_official(*args, **kwargs)


def get_battle_invisible_disabled_qids():
    try:
        value = _redis_get_json(_BATTLE_INVISIBLE_DISABLED_QIDS_REDIS_KEY, default=[])
    except Exception as error:
        log_message(f"BATTLE_VISIBILITY_REDIS_READ_ERROR: {repr(error)}")
        value = []
    if not isinstance(value, list):
        value = []
    return sorted({str(item) for item in value if str(item or "").strip()})


def save_battle_invisible_disabled_qids(disabled_qids):
    disabled_qids = sorted({str(item) for item in disabled_qids if str(item or "").strip()})
    _redis_set_json(_BATTLE_INVISIBLE_DISABLED_QIDS_REDIS_KEY, disabled_qids)
    return disabled_qids


def _battle_visibility_qids(realname):
    from .business.battle_visibility import resolve_visibility_qids

    target_qids, missing_names = resolve_visibility_qids(
        realname,
        globals().get("sameuser", {}),
        qid,
    )
    for name in missing_names:
        log_message(f"WZRY_VISIBILITY_QID_NOT_FOUND: {name}")
    return target_qids


def sync_battle_visibility_state(realname, visible):
    from .business.battle_visibility import update_disabled_qids
    from .utils.message_sender import BATTLE_INVISIBLE_MUTE_SECONDS
    from .utils.message_sender import add_group_ban_task

    target_qids = _battle_visibility_qids(realname)
    if not target_qids:
        log_message(f"WZRY_VISIBILITY_QID_NOT_FOUND: {realname}")
        return []

    disabled_qids, changed_qids = update_disabled_qids(
        get_battle_invisible_disabled_qids(),
        target_qids,
        visible=visible,
    )
    action = "ENABLE" if visible else "DISABLE"
    for user_qid in changed_qids:
        log_message(f"WZRY_VISIBILITY_{action}_QID: {realname} {user_qid}")

    if changed_qids:
        save_battle_invisible_disabled_qids(disabled_qids)
        duration = 0 if visible else BATTLE_INVISIBLE_MUTE_SECONDS
        source = f"battle_visibility:{realname}:{'visible' if visible else 'invisible'}"
        for user_qid in target_qids:
            add_group_ban_task(user_qid, duration=duration, source=source)
    return changed_qids


def _group_chat_history_key(group_id):
    return f"{_GROUP_CHAT_HISTORY_REDIS_PREFIX}{str(group_id)}"


def record_group_chat_message(group_id, user_id, text, *, message_id=None, reply_to_message_id=None):
    """Persist one inbound group message for on-demand AI retrieval.

    ``ChatHistoryMaxMessages`` is an optional safety cap.  A value less than or
    equal to zero keeps the complete history and never trims the Redis list.
    """
    from .ztime import current_datetime_text, current_epoch_seconds

    normalized_text = str(text or "").strip()
    if not normalized_text:
        return None
    key = _group_chat_history_key(group_id)
    if message_id in (None, ""):
        message_id = f"{current_epoch_seconds()}:{user_id}"
    record = {
        "group_id": str(group_id),
        "user_id": str(user_id),
        "message_id": str(message_id),
        "reply_to_message_id": str(reply_to_message_id) if reply_to_message_id not in (None, "") else None,
        "time": current_datetime_text(),
        "timestamp": current_epoch_seconds(),
        "text": normalized_text,
    }
    redis_client = dmc.redis_deamon
    redis_client.rpush(key, json.dumps(record, ensure_ascii=False))
    max_messages = int(getattr(dmc, "ChatHistoryMaxMessages", 0) or 0)
    if max_messages > 0:
        redis_client.ltrim(key, -max_messages, -1)
    return record


def load_group_chat_history(group_id, limit=None):
    key = _group_chat_history_key(group_id)
    if limit is None:
        raw_records = dmc.redis_deamon.lrange(key, 0, -1)
    else:
        raw_records = dmc.redis_deamon.lrange(key, -max(1, int(limit)), -1)
    records = []
    for raw in raw_records:
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            record = json.loads(raw)
        except Exception:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def search_group_chat_history(group_id, queries, *, user_ids=None, time_start=None, time_end=None,
                              limit=8, exclude_message_id=None):
    from .zmemory import search_history_records
    from .ztime import parse_chat_time_bound

    records = load_group_chat_history(group_id)
    start_timestamp = parse_chat_time_bound(time_start, is_end=False)
    end_timestamp = parse_chat_time_bound(time_end, is_end=True)
    if start_timestamp is not None:
        records = [record for record in records if int(record.get("timestamp") or 0) >= start_timestamp]
    if end_timestamp is not None:
        records = [record for record in records if int(record.get("timestamp") or 0) <= end_timestamp]
    return search_history_records(
        records,
        queries,
        user_ids=user_ids,
        limit=limit,
        exclude_message_id=exclude_message_id,
    )


def fetch_group_chat_context(group_id, message_id, *, before=5, after=8):
    from .zmemory import fetch_history_context

    records = load_group_chat_history(group_id)
    return fetch_history_context(
        records,
        message_id,
        before=before,
        after=after,
        max_chars=max(500, int(getattr(dmc, "ChatHistoryContextChars", 6000))),
    )


def fetch_group_chat_reply_thread(group_id, message_id, *, max_depth=4):
    from .zmemory import fetch_history_reply_thread

    return fetch_history_reply_thread(
        load_group_chat_history(group_id),
        message_id,
        max_depth=max_depth,
    )

def _to_pinyin(s):
    from pypinyin import lazy_pinyin
    
    return "".join(lazy_pinyin(str(s))).lower()

def safe_hero_name(hero_id, default=None):
    if hero_id is None:
        return default or "未知英雄"
    hero_id = str(hero_id)
    return HeroList.get(hero_id, default or f"未知英雄({hero_id})")


def hero_tier_query_process():
    from .zapi import tianyuanzhiyi_hero_avatars_api, tianyuanzhiyi_tier_api
    from .zfile import (
        hero_tier_image_path,
        load_hero_tier_avatar_cache,
        save_hero_tier_avatar_cache,
    )
    from .tools.gen_hero_tier import generate_hero_tier_image

    tier_data = tianyuanzhiyi_tier_api()
    if not isinstance(tier_data, dict) or not tier_data.get("tiers"):
        raise Exception(f"hero_tier_query_error: empty response {tier_data!r}")
    avatar_bytes, missing_items = load_hero_tier_avatar_cache(tier_data["tiers"])
    if missing_items:
        downloaded = tianyuanzhiyi_hero_avatars_api(missing_items)
        save_hero_tier_avatar_cache(missing_items, downloaded)
        avatar_bytes.update(downloaded)
    output_path = hero_tier_image_path()
    generate_hero_tier_image(tier_data, output_path, avatar_bytes=avatar_bytes)
    return output_path


def _battle_matchup_composition(detail_list):
    composition = {}
    for player in detail_list:
        battle_records = player.get("battleRecords") or {}
        used_hero = battle_records.get("usedHero") or {}
        position = battle_records.get("position")
        hero_id = used_hero.get("heroId")
        try:
            position = int(position)
            hero_id = int(hero_id)
        except (TypeError, ValueError):
            continue
        if 0 <= position <= 4:
            composition[str(position)] = hero_id
    return composition


def hero_matchup_process(my_detail, op_detail, matchup_api=None):
    if matchup_api is None:
        from .zapi import tianyuanzhiyi_matchup_api

        matchup_api = tianyuanzhiyi_matchup_api
    my_heroes = _battle_matchup_composition(my_detail)
    op_heroes = _battle_matchup_composition(op_detail)
    if len(my_heroes) + len(op_heroes) < 2:
        return {"winRate": None, "sampleMatches": 0, "queryMode": "unavailable"}
    try:
        exact = matchup_api(my_heroes, op_heroes, days=30)
        exact_matches = int(exact.get("totalMatchesFound") or 0)
        if exact_matches:
            return {
                "winRate": float(exact.get("camp1WinRate") or 0),
                "sampleMatches": exact_matches,
                "queryMode": "exact",
                "queryCount": 1,
            }

        samples = []
        queried_pairs = 0
        for position in sorted(set(my_heroes) & set(op_heroes), key=int):
            queried_pairs += 1
            result = matchup_api(
                {position: my_heroes[position]},
                {position: op_heroes[position]},
                days=30,
            )
            match_count = int(result.get("totalMatchesFound") or 0)
            if match_count:
                samples.append((float(result.get("camp1WinRate") or 0), match_count))
        total_matches = sum(match_count for _, match_count in samples)
        if not total_matches:
            return {"winRate": None, "sampleMatches": 0, "queryMode": "lane_pairs", "queryCount": queried_pairs}
        weighted_rate = sum(rate * match_count for rate, match_count in samples) / total_matches
        return {
            "winRate": weighted_rate,
            "sampleMatches": total_matches,
            "queryMode": "lane_pairs",
            "queryCount": queried_pairs,
        }
    except Exception as error:
        log_message(f"TIANYUAN_MATCHUP_ERROR: {repr(error)}")
        return {"winRate": None, "sampleMatches": 0, "queryMode": "error", "error": repr(error)}


_BATTLE_POSITION_NAMES = {
    0: "对抗路",
    1: "中路",
    2: "发育路",
    3: "打野",
    4: "游走",
}


def _battle_lineup_items(detail_list):
    items = []
    for player in detail_list:
        battle_records = player.get("battleRecords") or {}
        used_hero = battle_records.get("usedHero") or {}
        try:
            position = int(battle_records.get("position"))
        except (TypeError, ValueError):
            position = -1
        hero_name = used_hero.get("heroName") or safe_hero_name(used_hero.get("heroId"))
        items.append({"position": position, "heroName": hero_name})
    return items


def _format_battle_lineup_ai_text(value):
    text = str(value or "").strip()
    if not text:
        return ""
    lines = [line.strip() for line in text.replace("\r\n", "\n").split("\n") if line.strip()]
    if len(lines) > 1:
        return "\n".join(lines)
    sentences = [item.strip() for item in re.findall(r"[^。！？!?]+[。！？!?]?", text) if item.strip()]
    return "\n".join(sentences)


def battle_lineup_ai_process(my_lineup, op_lineup, ai_func=None):
    if ai_func is None:
        ai_func = ai_parser

    def position_value(item):
        try:
            return int(item.get("position", -1))
        except (TypeError, ValueError):
            return -1

    def format_side(lineup):
        ordered = sorted(lineup, key=position_value)
        return "、".join(
            f"{_BATTLE_POSITION_NAMES.get(position_value(item), '未知分路')}{item.get('heroName') or '未知英雄'}"
            for item in ordered
        )

    context = f"我方：{format_side(my_lineup)}；对方：{format_side(op_lineup)}。"
    try:
        return _format_battle_lineup_ai_text(ai_func([context], "battle_lineup"))
    except Exception as error:
        log_message(f"BATTLE_LINEUP_AI_ERROR: {repr(error)}")
        return ""


def _compact_report_value(value, max_len=220):
    try:
        text = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
    except Exception:
        text = repr(value)
    text = str(text).replace("\n", " ").replace("\r", " ")
    if len(text) > max_len:
        text = text[:max_len - 3] + "..."
    return text


def _build_traversal_error(source, realname, params, error):
    return {
        "source": source,
        "name": realname,
        "nickname": namenick.get(realname, realname),
        "params": params,
        "error": repr(error),
    }


def format_traversal_error_report(title, errors):
    if not errors:
        return ""
    lines = [f"{title}异常汇总 count={len(errors)}"]
    for index, item in enumerate(errors, 1):
        name = item.get("name", "")
        nickname = item.get("nickname", name)
        source = item.get("source", "")
        params = _compact_report_value(item.get("params", {}), 260)
        error = _compact_report_value(item.get("error", ""), 180)
        lines.append(f"{index}. {source} {nickname}/{name} params={params} err={error}")
    return "\n".join(lines)


def peak_rank_process(player_names=None):
    """Build the peak-score ranking exclusively from local history JSON."""
    from .zfile import list_history_dates_descending, read_history_date

    requested_names = set(player_names if player_names is not None else userlist.keys())
    latest_records = {}

    for history_date in list_history_dates_descending(start_date=this_season_start_date):
        if not requested_names:
            break
        daily_data = read_history_date(history_date)
        if not isinstance(daily_data, list):
            continue
        for player in daily_data:
            if not isinstance(player, dict):
                continue
            realname = str(player.get("key") or "").strip()
            if realname not in requested_names:
                continue

            valid_details = []
            for index, detail in enumerate(player.get("details") or []):
                if not isinstance(detail, dict):
                    continue
                try:
                    peak_score = int(detail.get("PeakGradeAfterGame"))
                except (TypeError, ValueError):
                    continue
                if peak_score <= 0:
                    continue
                try:
                    timestamp = int(detail.get("GameTime_Timestamp") or 0)
                except (TypeError, ValueError):
                    timestamp = 0
                valid_details.append((timestamp, index, peak_score))

            if not valid_details:
                continue
            _, _, peak_score = max(valid_details, key=lambda item: (item[0], item[1]))
            latest_records[realname] = {
                "realname": realname,
                "name": namenick.get(realname) or player.get("nickname") or realname,
                "score": peak_score,
                "date": history_date,
            }
            requested_names.remove(realname)

    ranking = sorted(
        latest_records.values(),
        key=lambda item: (-item["score"], item["name"], item["realname"]),
    )
    if not ranking:
        return "【巅峰排名】\n本地历史中暂无有效巅峰数据"

    lines = ["【巅峰排名】"]
    for index, item in enumerate(ranking, 1):
        lines.append(f"{index}. {item['name']}  {item['score']}")
    return "\n".join(lines)


def wzry_data(realname,savepath=None,target_userid=None,target_roleid=None,target_date=None,sync_battle_visibility=False): # 单人的战绩parser
    def get_star_today_most_recent(today_details):
        for detail in today_details[::-1]:
            if (detail["MapType"]==1):
                return detail["StarAfterGame"]
        return -1
        
    def get_star_before_today_most_recent(target_id, target_date_obj=None):
        from .ztime import time_sul

        if target_date_obj:
            today_dt = datetime.datetime.combine(target_date_obj, datetime.datetime.min.time())
            yesterday_sul = today_dt - datetime.timedelta(days=1)
        else:
            yesterday_sul = time_sul() - datetime.timedelta(days=1)
        try:
            from .zdb import latest_rank_star_before

            database_star = latest_rank_star_before(target_id, yesterday_sul.strftime("%Y-%m-%d"))
            if database_star is not None:
                return database_star
        except Exception as exc:
            log_message(
                f"POSTGRES_LATEST_STAR_FALLBACK: userid={target_id} before={yesterday_sul} error={repr(exc)}",
                logging.WARNING,
            )

        from .zfile import list_history_dates_descending, read_history_date

        for history_date in list_history_dates_descending():
            if history_date > yesterday_sul.strftime("%Y-%m-%d"):
                continue
            for player in read_history_date(history_date):
                if int(player["id"]) != int(target_id):
                    continue
                for detail in player["details"][::-1]:
                    if detail["MapType"] == 1:
                        return detail["StarAfterGame"]
        return -1

    from .ztime import time_r
    from .ztime import time_sul
    from .ztime import stamp_to_time
    from .ztime import date_roleback
    from .zfile import writerl
    from .zfunc import extract_url_params

    log_message("VISIT: wzry_data")
    
    userid=target_userid if target_userid else userlist[realname]
    roleid=target_roleid if target_roleid else roleidlist[realname]
    
    btlist_data=wzry_get_official(reqtype="btlist",userid=userid,roleid=roleid)
    profile_data=wzry_get_official(reqtype="profile",userid=userid,roleid=roleid)
    res = {
        "btlist": btlist_data,
        "profile": profile_data
    }

    if (savepath):
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
    if sync_battle_visibility:
        sync_battle_visibility_state(realname, BtlVisible)
    isGaming=res["btlist"]["isGaming"] and res["btlist"]["gaming"]
    real_date=time_r().strftime("%m-%d")
    sul_time=time_sul()
    target_date_obj = datetime.datetime.strptime(target_date, "%Y-%m-%d").date() if target_date else sul_time.date()
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
        from .tools.representative_battle import build_battle_keywords

        today_btl = [game for game in res['btlist']['list'] if (time_sul(stamp_to_time(int(game['dtEventTime']))).date()==target_date_obj)]
        # today_btl = [game for game in res['btlist']['list'] if (time_sul(stamp_to_time(int(game['dtEventTime']))).date()==date_roleback().date())]
        today_details=[{\
            'GameTime':game['gametime'],\
            'GameTime_Timestamp':int(game['dtEventTime']),\
            'HeroName':safe_hero_name(game.get('heroId')),\
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
        #     log_message(str(e))
        peakUp=get_peak_alter_list(details=today_details,processed=False)
        gamegrades = [
            round(float(game["gradeGame"]), 1)
            for game in today_btl
            if check_btl_official(game["mapName"])
        ]
        today_btl_aver = round(sum(gamegrades) / len(gamegrades), 3) if gamegrades else 0
        today_btl_max=-fin if len(gamegrades)==0 else max(gamegrades)
        today_btl_min= fin if len(gamegrades)==0 else min(gamegrades)
    
    if (isGaming):
        gaming_info={
                    "in_game":True,\
                    "map_name":res["btlist"]["gaming"]["mapName"],\
                    "hero_name":safe_hero_name(res["btlist"]["gaming"].get("heroId")),\
                    "duration_minute":res["btlist"]["gaming"]["duration"],\
                    "battle_num_this_hero":res["btlist"]["gaming"]["gameNum"],\
                    "win_rate_this_hero":res["btlist"]["gaming"]["winRate"],\
                    "can_be_watched":res["btlist"]["gaming"]["canBeWatch"],\
                    "battle_id":res["btlist"]["gaming"]["battleId"],\
        }
    # export_btl_thread = threading.Thread(target=export_btldetail, args=(gameinfo=today_details))
    # export_btl_thread.start()
    unaccessible_battles=export_btldetail(today_details,roleid)
    _enrich_battle_list_skills_from_cache(res, roleid)
    if savepath:
        writerl(savepath, res)
    if (BtlVisible):
        today_btl_contribute_aver = calculate_official_battle_contribution_average(today_details, roleid)
    return {"id":userid,"roleid":roleid,"key":realname,"nickname":nickname,"date":str(real_date),"today_num":today_num,"rank_name":rankName,"rank_star":rankStar,"total_num":totalNum,"up_tourna":today_up_tourna,"up_peak":today_up_peak,"map_cnt":today_game_cnt,"btl_aver":today_btl_aver,"btl_contribute_aver":today_btl_contribute_aver,"rank":rankName,"star":starNum,"star_up":starUp,"peak_up":peakUp,"details":today_details,"gaming_info":gaming_info,"visible":BtlVisible,"unaccessible_battles":unaccessible_battles}

def _enrich_battle_list_skills_from_cache(payload, roleid):
    """从本地战局详情为单人战绩卡片补齐召唤师技能。"""
    from .zfile import read_battle_detail

    battle_list = payload.get("btlist", {}).get("list", [])
    for battle in battle_list:
        if battle.get("skill", {}).get("skillIcon"):
            continue
        detail = read_battle_detail(battle.get("gameSeq"))
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
    from .zfile import read_history_date, writerl

    log_message(f"DUMPBEGIN specific user {userid} date: {target_date}.json")
    
    # 获取真正的realname (key)
    realname = "unknown"
    for k, v in userlist.items():
        if v == userid:
            realname = k
            break
    
    gameinfo = []
    try:
        data = wzry_data(
            realname=realname, 
            savepath=os.path.join("data","history", "personal", target_date, str(userid) + ".json"),
            target_userid=userid,
            target_roleid=roleid,
            target_date=target_date
        )
        gameinfo.append(data)
    except Exception as e:
        log_message(f"Dump specific user {userid} failed: {e}")

    aggregated_filename = os.path.join("data","history", target_date + ".json")
    try:
        existing_data = read_history_date(target_date) or []
        existing_data = [d for d in existing_data if str(d.get("id")) != str(userid)]
        existing_data.extend(gameinfo)
        writerl(aggregated_filename, existing_data)
    except Exception as e:
        log_message(f"Failed to update aggregated file {aggregated_filename}: {e}")
        
    log_message(f"DUMPEND specific user {userid} date: {target_date}.json")
    return gameinfo[0]

def export_past():
    import json
    import glob

    directory = "data/history/"
    result = {f: json.load(open(f, 'r', encoding='utf-8')) for f in glob.glob(f"{directory}/2026-02*.json")}
    for k,v in result.items():
        for player in v:
            export_btldetail(player["details"],player["roleid"])
def ai_parser(user_query,msg_type,network=False,use_mem=None):
    from .zapi import ai_api,ark_api
    from .ztime import get_timebased_rand
    from .chat_roles import build_role_prompt

    if use_mem is None:
        use_mem = dmc.use_mem

    ai_temperature=1.5
    style_templates_index=get_timebased_rand(len(pmpt_style_templates),30)
    style_template=pmpt_style_templates[style_templates_index]
    
    whole_query=""

    match msg_type:
        case "rnk":
            whole_query += remind_news_pmpt + dmc.today_news + rnk_pmpt + user_query[0]
        case "best_battle":
            whole_query += "你是一个幽默的王者荣耀解说，请用夸张、幽默且具有生活气息的语言，对以下这局今日最有代表性的对局进行一句话点评（70字以内，不用双引号，不用Markdown）：" + user_query[0]
        case "single_parser":
            whole_query += name_pmpt[0] + str(nameref) + name_pmpt[1]+ user_query[0] + name_pmpt[2]
            ai_temperature=2
        case "single_player":
            whole_query += single_pmpt1 + user_query[0] + user_query[1] + single_pmpt2 + user_query[2]
        case "tq":
            whole_query += tq_pmpt + user_query[0]
        case "chat":
            role_prompt = build_role_prompt(chat_role)
            if use_mem:
                context_msg = f"""
                【情境信息】
                - 当前用户: {user_query[2]} (QID: {user_query[3]})
                
                - 当前用户与 Bot 的近期直接对话（仅来自 chat event）:
                {user_query[1]}
                
                【重要指令】
                以上信息仅作为对话背景。
                只使用当前用户此前直接对 Bot 说过的话和 Bot 对该用户的回复延续语境。
                不要假设其中包含其他用户的发言、群聊旁观内容、提炼总结或其他来源的记忆。
                请自然地融合在回复中，不要直接提及“记忆模块”“系统提示”等内部实现。
                
                当前请求: {user_query[0]}
                """
                whole_query += role_prompt + style_template + context_msg + chat_pmpt
            else:
                whole_query += role_prompt + style_template + "这是这次的请求：（" + user_query[0] + "）" + chat_pmpt + "回答中不用透露出现有记住/记录这些，自然一些,并保持礼貌文明用语。"
        case "poke":
            whole_query = poke_pmpt[0] + user_query[0] + poke_pmpt[1] + user_query[1] + poke_pmpt[2]
        case "battle_lineup":
            whole_query = battle_lineup_pmpt + user_query[0]
        case "festival":
            whole_query = festival_pmpt[0] + user_query[0] + festival_pmpt[1]
        case "raise_question":
            whole_query = raise_question_pmpte
        case "pure_chat":
            whole_query = user_query[0]
        case "urge_game":
            whole_query = urge_game_pmpt[0] + user_query[0] + urge_game_pmpt[1] + user_query[1] + urge_game_pmpt[2] + user_query[2] + urge_game_pmpt[3]
        case "summary":
            whole_query = user_query[0]
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

    return ai_back

class WebArtifacts:
    @staticmethod
    def make_hash(seed=None):
        """Create a short stable hash from seed or a random token."""
        from .business.web_artifacts import make_hash

        return make_hash(seed)

    @staticmethod
    def history_json_path(filename_hashed):
        """Build the public history JSON path."""
        from .zfile import web_history_json_path

        return web_history_json_path(filename_hashed)

    @staticmethod
    def history_artifact(seed=None):
        """Create a public history JSON filename and path pair."""
        filename_hashed=WebArtifacts.make_hash(seed)
        return filename_hashed,WebArtifacts.history_json_path(filename_hashed)

    @staticmethod
    def route_url(sitetype,hash_key):
        """Build a public route URL for a stored web payload."""
        from .business.web_artifacts import route_url

        return route_url(sitetype, hash_key, confs["WebService"]["server_domain"])

    @staticmethod
    def create_route_link(contents,sitetype):
        """Store route contents in Redis and return the public URL."""
        hash_key=WebArtifacts.make_hash()
        redis_key = f"{REDIS_KEY_WEB_ARTIFACT_PREFIX}{hash_key}"
        dmc.redis_deamon.set(redis_key,contents,ex=REDIS_TEXT_EXPIRE_SECONDS)
        return WebArtifacts.route_url(sitetype,hash_key)

    @staticmethod
    def history_route_link(filename_hashed,sitetype,caller="",time_text="",extra=None):
        """Create a route link for a history JSON artifact."""
        from .business.web_artifacts import history_route_payload

        payload = history_route_payload(filename_hashed, caller, time_text, extra)
        return WebArtifacts.create_route_link(json.dumps(payload,ensure_ascii=False),sitetype)

    @staticmethod
    def publish_history_json_route(payload,sitetype):
        """Publish a JSON payload to the history JSON path, then return a route URL."""
        from .zfile import write_web_history_payload

        filename_hashed = WebArtifacts.make_hash()
        write_web_history_payload(filename_hashed, payload)
        return WebArtifacts.route_url(sitetype,filename_hashed)

    @staticmethod
    def bili_video_route_link(payload):
        """Publish a Bilibili video payload to Redis and return its public detail page."""
        return WebArtifacts.create_route_link(json.dumps(payload,ensure_ascii=False),"bili_video")

def online_process():
    from .zapi import steam_api_user_status

    def process_user(realname):
        userid = userlist[realname]
        roleid = roleidlist[realname]
        errors = []

        try:
            profile_res = wzry_get_official(reqtype="profile", userid=userid, roleid=roleid)
        except Exception as e:
            errors.append(_build_traversal_error(
                "online.profile",
                realname,
                {"reqtype": "profile", "userid": userid, "roleid": roleid},
                e,
            ))
            return {'online_cnt': 0, 'battle_info': None, 'nickname': '', 'errors': errors}

        
        user_online_cnt = 0
        user_battle_info = None
        user_nickname = ''
        
        for role_info in profile_res["roleList"]:
            online = role_info["gameOnline"]
            if online:
                if not user_nickname:
                    user_nickname = role_info['roleName']
                user_online_cnt += 1

                params = {
                    "reqtype": "btlist",
                    "userid": userid,
                    "roleid": roleid,
                    "roleName": role_info.get("roleName"),
                    "shortRoleJobName": role_info.get("shortRoleJobName"),
                }
                try:
                    btlist_res = wzry_get_official(reqtype="btlist", userid=userid, roleid=roleid)
                except Exception as e:
                    errors.append(_build_traversal_error("online.btlist", realname, params, e))
                    if not user_battle_info:
                        user_battle_info = {
                            'battleId': None,
                            'job': role_info.get('shortRoleJobName', ''),
                            'mapName': None,
                            'heroName': None,
                            'duration': None
                        }
                    continue

                if btlist_res["isGaming"]:
                    user_battle_info = {
                        'battleId': btlist_res['gaming'].get('battleId', ''),
                        'job': role_info['shortRoleJobName'],
                        'mapName': btlist_res['gaming']['mapName'],
                        'heroName': safe_hero_name(btlist_res['gaming'].get('heroId')),
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
        
        return {'online_cnt': user_online_cnt, 'battle_info': user_battle_info, 'nickname': user_nickname, 'errors': errors}

    snd_msg = ""
    total_online_cnt = 0
    battle_groups = {}  # 按战局ID分组: {battleId: [玩家信息]}
    idle_users = []  # 在线但不在游戏中的玩家
    steam_online_users = []
    traversal_errors = []
    
    def process_steam_user(steam_id):
        return steam_api_user_status(confs['Steam']['api_key'], steam_id)
        
    workers = len(userlist) + len(steam_userlist)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_to_user = {
            executor.submit(process_user, realname): ('wzry', realname)
            for realname in userlist
        }
        for realname, steam_id in steam_userlist.items():
            future_to_user[executor.submit(process_steam_user, steam_id)] = ('steam', realname)

        for future in as_completed(future_to_user):
            req_type, realname = future_to_user[future]
            if req_type == 'wzry':
                try:
                    result = future.result()
                except Exception as e:
                    traversal_errors.append(_build_traversal_error(
                        "online.wzry_future",
                        realname,
                        {
                            "userid": userlist.get(realname),
                            "roleid": roleidlist.get(realname),
                        },
                        e,
                    ))
                    continue
                traversal_errors.extend(result.get('errors', []))
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
            elif req_type == 'steam':
                steam_id = steam_userlist.get(realname)
                try:
                    result = future.result()
                    if result:
                        state = result.get('personastate', 0)
                        game = result.get('gameextrainfo', '')
                        # 如果有游戏信息或者状态不为 0 (离线)，则认为在线
                        if state > 0 or game:
                            steam_online_users.append({
                                'name': result.get('personaname', realname),
                                'game': game,
                                'state': state
                            })
                except Exception as e:
                    traversal_errors.append(_build_traversal_error(
                        "online.steam_status",
                        realname,
                        {"steam_id": steam_id},
                        e,
                    ))
    
    if total_online_cnt or steam_online_users:
        if total_online_cnt:
            snd_msg += f"在线 {total_online_cnt} 人\n"
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
                    
        if steam_online_users:
            if total_online_cnt:
                snd_msg = snd_msg.rstrip('\n') + "\n\n"
            snd_msg += f"Steam 在线 {len(steam_online_users)} 人\n"
            snd_msg += "─────────────\n"
            for user in steam_online_users:
                game = user.get('game')
                if game:
                    snd_msg += f"🎮 {user['name']}  {game}\n"
                else:
                    snd_msg += f"💤 {user['name']}  在线\n"
        
        snd_msg = snd_msg.rstrip('\n')
    else:
        snd_msg = "🐟🐟无人在线"
    
    return snd_msg, format_traversal_error_report("在线遍历", traversal_errors)
def rnk_process(rcv_msg,caller=None,show_zero=True,show_analyze=False,debug=False):
    if (caller==None): caller=""
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
    filename_hashed,filepath=WebArtifacts.history_artifact(round(time.time()*1000000))
    website_link=WebArtifacts.history_route_link(filename_hashed,"all",caller=caller,time_text=now_time)
    gameinfo=[]
    traversal_errors = []

    def visit_wzry_data(key):
        try:
            game_data = wzry_data(realname=key)
            return {"data": game_data, "error": None}
        except Exception as e:
            params = {
                "realname": key,
                "calls": [
                    {"reqtype": "btlist", "userid": userlist.get(key), "roleid": roleidlist.get(key)},
                    {"reqtype": "profile", "userid": userlist.get(key), "roleid": roleidlist.get(key)},
                ],
            }
            return {"data": None, "error": _build_traversal_error("rank.wzry_data", key, params, e)}

    gameinfo = []
    with ThreadPoolExecutor(max_workers=1) as executor:
        future_to_key = {executor.submit(visit_wzry_data, key): key for key in userlist}
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            try:
                result = future.result()
            except Exception as e:
                traversal_errors.append(_build_traversal_error(
                    "rank.future",
                    key,
                    {
                        "realname": key,
                        "calls": [
                            {"reqtype": "btlist", "userid": userlist.get(key), "roleid": roleidlist.get(key)},
                            {"reqtype": "profile", "userid": userlist.get(key), "roleid": roleidlist.get(key)},
                        ],
                    },
                    e,
                ))
                continue
            if result.get("error"):
                traversal_errors.append(result["error"])
            if result.get("data") is not None:
                gameinfo.append(result["data"])
    if (not gameinfo):
        log_message(f"ERROR: 王者荣耀数据源错误")
        return [
            str(time_r().strftime("%Y-%m-%d %H:%M")) + "\n\n王者荣耀数据源错误，暂无可用排行数据",
            [],
            format_traversal_error_report("排行遍历", traversal_errors),
        ]
    filename_export=os.path.join("data","history",today_sul_date+".json")
    writerl(filename_export,gameinfo)
    if (not show_zero): gameinfo=[item for item in gameinfo if item['today_num']!=0]
    sorted_star=sorted(gameinfo, key=lambda item: (item['star_up']) ,reverse=True)
    sorted_btl=sorted(gameinfo, key=lambda item: (item['today_num']) ,reverse=True)
    dumpfile_raw1=[{k: v for k, v in d.items() if k != "key"} for d in sorted_star]
    writerl(filepath,dumpfile_raw1)
    snd_msg+=str(time_r().strftime("%Y-%m-%d %H:%M"))+"\n"
    if (not gameinfo or sorted_btl[0]['today_num']==0): 
        snd_msg+="\n今日还没有战绩哦"
        return [snd_msg, [], format_traversal_error_report("排行遍历", traversal_errors)]
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
        return [snd_msg,{toppoint_gamenick,bottompoint_gamenick,topplay_gamenick},format_traversal_error_report("排行遍历", traversal_errors)]
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
    from .zfile import readerl
    from .zfile import read_history_date
    from .zfile import read_personal_history
    from .zfile import list_history_dates_descending
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
        yesterday_date=str(time_r()-datetime.timedelta(days=1))

        filename_hashed,website_filepath=WebArtifacts.history_artifact(round(time.time()*1000000))
        history_query=extract_history_query(rcv_msg)
        battle_visible=True
        if (history_query[0]==1): # 追溯过去某一天
            ai_feedback=False
            show_map_cnt_total=True
            traceback_cnt=history_query[1][0]
            traceback_date=str(time_r_delta(traceback_cnt).strftime("%Y-%m-%d"))
            exhibit_date_woyear=str(time_r_delta(traceback_cnt).strftime("%m-%d"))
            available_dates = set(list_history_dates_descending())
            if traceback_date not in available_dates:
                traceback_date = str(record_begin_date)
            histories=read_history_date(traceback_date)
            gameinfo=[history for history in histories if (history["id"]==userlist[matching_name])][0]
            
            if ("roleid" not in gameinfo): gameinfo["roleid"]=str(roleidlist[gameinfo["key"]])
            if ("visible" not in gameinfo): gameinfo["visible"]=True
            
            try:
                personal_payload = read_personal_history(traceback_date, userlist[matching_name])
                if not personal_payload:
                    raise FileNotFoundError(f"personal snapshot missing: {traceback_date}/{userlist[matching_name]}")
                writerl(website_filepath, personal_payload)
            except Exception as e:
                exhibit_date_woyear+=" 链接失效"
            website_link=WebArtifacts.history_route_link(filename_hashed,"single_oneday")
        elif (history_query[0]==2): # 追溯时间段
            ai_feedback=False
            show_map_cnt_total=True
            lost_info_date=[]
            traceback_from=history_query[1][0]
            traceback_to=history_query[1][1]
            if (traceback_from<traceback_to): traceback_to,traceback_from=traceback_from,traceback_to
            traceback_date_from=time_r_delta(traceback_from)
            traceback_date_to=time_r_delta(traceback_to)
            available_dates = set(list_history_dates_descending())
            if traceback_date_from.strftime('%Y-%m-%d') not in available_dates:
                traceback_date_from=str_to_time(record_begin_date)
            if traceback_date_to.strftime('%Y-%m-%d') not in available_dates:
                traceback_date_to=str_to_time(record_begin_date)
            
            gameinfo_raw=[]
            
            scan_date=traceback_date_from
            while(scan_date<=traceback_date_to):
                scan_date_text = scan_date.strftime('%Y-%m-%d')
                if scan_date_text in available_dates:
                    histories=read_history_date(scan_date_text)
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
            website_link=WebArtifacts.history_route_link(filename_hashed,"single_period",extra={"DateFrom":traceback_date_from.strftime("%m-%d"),"DateTo":traceback_date_to.strftime("%m-%d")})
        else: # 当天战局
            gameinfo=wzry_data(matching_name,website_filepath,sync_battle_visibility=True)
            
            # Update today's structured history snapshot.
            today_sul_date=str(time_sul().strftime("%Y-%m-%d"))
            filename_export=os.path.join("data","history",today_sul_date+".json")
            current_history = read_history_date(today_sul_date) or []
            current_history = [item for item in current_history if item.get('key') != matching_name]
            current_history.append(gameinfo)
            writerl(filename_export, current_history)
            
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
            if (gameinfo["gaming_info"]):
                dmc.spoiler_cache = {
                    "time": time.time(),
                    "realname": matching_name,
                    "battleID": gameinfo["gaming_info"]["battle_id"],
                }
            website_link=WebArtifacts.history_route_link(filename_hashed,"single_oneday")

        # 历史数据中的 btl_aver 可能由旧口径生成，查询时统一按正式对局重算。
        gameinfo["btl_aver"] = calculate_official_battle_average(gameinfo.get("details", []))
        gameinfo["btl_contribute_aver"] = calculate_official_battle_contribution_average(
            gameinfo.get("details", []),
            gameinfo.get("roleid", roleidlist[matching_name]),
        )
        
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
                f"        平均贡献: {gameinfo.get('btl_contribute_aver', 0):.2f}\n"
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
        payload=Analyses.get_benefit_debug_payload(time_gap=time_gap)
        snd_msg+=WebArtifacts.publish_history_json_route(payload,"benefit")+"\n"
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
def btldetail_process(gameSvrId, relaySvrId, gameseq, pvptype,roleid,gen_image=False,show_profile=False,from_web=False,individual_show=False,strict_filter=True):
    from .zfile import writerl
    from .zfunc import check_btl_official_with_matching
    from .tools import gen_battle_res
    import json
    import os

    res = fetch_battle(gameseq,roleid)

    if not res:
        res=wzry_get_official(reqtype="btldetail",gameseq=gameseq,gameSvrId=gameSvrId,relaySvrId=relaySvrId,roleid=roleid,pvptype=pvptype)
    
    if ('head' not in res): return None,None,None
    if (strict_filter and not check_btl_official_with_matching(res['head']['mapName'])): return None,None,res['head']['mapName']
    
    my_team_detail=res['redRoles'] if (res['redTeam']['acntCamp']==res['head']['acntCamp']) else res['blueRoles']
    team_contribute_factor=calculate_battle_contribution_factor(res) or 0
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
    filename_hashed,json_output_path=WebArtifacts.history_artifact(round(time.time()*1000000))
    linkurl=WebArtifacts.history_route_link(filename_hashed,"btldetail")
    picpath=""
    writerl(json_output_path,res)
    if (gen_image):
        picpath=os.path.join(temp_path,"temp_files","exhibit.png")
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
    return snd_message,picpath,res['head']['mapName']
def heropower_process(realname):
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


from .business import hero_statistics as _hero_statistics_business
from .business import honor_power as _honor_power_business


def _honor_hero_from_query(query_text):
    return _honor_power_business._honor_hero_from_query(query_text)


def _honor_region_name_without_suffix(region_name):
    return _honor_power_business._honor_region_name_without_suffix(region_name)


def _honor_district_entries(district_payload):
    return _honor_power_business._honor_district_entries(district_payload)


def resolve_honor_district(region_query, district_payload=None):
    return _honor_power_business.resolve_honor_district(
        region_query, district_payload=district_payload
    )


def _honor_rank_percentile_points(rank_list):
    return _honor_power_business._honor_rank_percentile_points(rank_list)


def honor_power_query_process(realname, query_text):
    return _honor_power_business.honor_power_query_process(realname, query_text)


def single_player_single_hero_process(
    username, heroid, heroname, this_season=True
):
    return _hero_statistics_business.single_player_single_hero_process(
        username, heroid, heroname, this_season=this_season
    )


def single_player_mult_hero_process(
    username, days=30, top_n=3, min_games=2, this_season=False
):
    return _hero_statistics_business.single_player_mult_hero_process(
        username,
        days=days,
        top_n=top_n,
        min_games=min_games,
        this_season=this_season,
    )


def mult_player_mult_hero_process(
    days=30, top_n=5, min_games=5, this_season=False
):
    return _hero_statistics_business.mult_player_mult_hero_process(
        days=days,
        top_n=top_n,
        min_games=min_games,
        this_season=this_season,
    )


def mult_player_single_hero_process(
    hero_id, hero_name, days=30, min_games=3, top_n=5, this_season=False
):
    return _hero_statistics_business.mult_player_single_hero_process(
        hero_id,
        hero_name,
        days=days,
        min_games=min_games,
        top_n=top_n,
        this_season=this_season,
    )

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
        skin_folder_path=os.path.join("resources","wzry_images","skins")
        hero_names = [d for d in os.listdir(skin_folder_path) 
              if os.path.isdir(os.path.join(skin_folder_path, d))]
        hero_name,selected_info=get_hero_name(realname,hero_names)
        # hero_name = random.choice(hero_names)
        hero_path = os.path.join(skin_folder_path, hero_name)
        
        skin_files = [f for f in os.listdir(hero_path) 
                if os.path.isfile(os.path.join(hero_path, f))]
        
        skin_file = random.choice(skin_files)
        skin_name=os.path.splitext(skin_file)[0]
        pic_path = os.path.join(project_root,hero_path,skin_file)
        return hero_name, skin_name,pic_path,selected_info
    def get_hero_skin(realname,ignore_limit):
        import redis
        from .ztime import time_r
        current_date = time_r().strftime("%Y-%m-%d")
        if (ignore_limit): hero_info_str=None
        else:
            hero_info_str = dmc.TodayHeroPool.get(f"{REDIS_KEY_HERO_TODAY_PREFIX}{realname}")
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
        dmc.TodayHeroPool.set(f"{REDIS_KEY_HERO_TODAY_PREFIX}{realname}", json.dumps(new_data))

        history_key = f"{REDIS_KEY_HERO_HISTORY_PREFIX}{realname}"
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
        
        skill_raw=readerl(os.path.join("resources","wzry_images",'hero_skills',heroid+".json"))
        for skill in skill_raw["skillList1"]:
            all_skills.append(skill["desc"])
        return all_skills

    hero_name,skin_name,pic_path,selected_info=get_hero_skin(realname,ignore_limit=ignore_limit)
    heroid=[heroid_ for heroid_,heroname_ in HeroList.items() if heroname_==hero_name][0]

    hero_skills=get_hero_skills(heroid)
    hero_statistics=single_player_single_hero_process(realname,heroid,hero_name)

    if (ai_comment): 
        play_reason = ai_parser(msg_type="skill_advantage", user_query=[hero_name, namenick[realname], str(hero_skills), str(selected_info), hero_statistics], use_mem=False)
    else: 
        play_reason = str(selected_info)

    former_msg=f"{namenick[realname]}的今日英雄：{hero_name}"
    latter_msg=play_reason
    return former_msg,latter_msg,pic_path

def allhero_process(realname):
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
    from .ztime import str_to_time, time_r

    userid=userlist[realname]
    pic_visit_path=os.path.join(temp_path,"wzry_grade_chart","grade_chart.png")
    pic_save_path=os.path.join(temp_path,"wzry_grade_chart")
    history_data, _ = fetch_history(
        userid=userid,
        start_date=str_to_time(record_begin_date),
        end_date=time_r(),
        filter_official=True,
    )
    analyze_msg=gen_grade_chart.gen_from_history(
        userid,
        namenick.get(realname, realname),
        history_data.get(realname, []),
        pic_save_path,
    )
    
    return pic_visit_path,analyze_msg
def watchbattle_process(realname):
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

    save_path=os.path.join(temp_path,"wzry_btl_shot",str(roleid)+".png")
    if(dmc.RTMPListener): dmc.RTMPListener.stop()
    dmc.RTMPListener = gen_battle_shot.RTMPListener(dmc.streamurl,save_path=save_path,roleid=roleid)
    dmc.RTMPListener.start()  # 开始后台监听

    dmc.RTMPListener.screenshot()   # 截图一次
    return save_path,None
def watchbattleinfo_to_coplayer_res(watchbattle_json, roleid=None, game_result=None):
    """将 watchbattleinfo 响应转换为 coplayer_process 所需的最小 res 结构（严格模式）。"""

    def _int(value, field_name):
        if value is None:
            raise ValueError(f"missing required field: {field_name}")
        return int(value)

    def _extract_acnt_camp_from_url(url):
        if not isinstance(url, str) or "?" not in url:
            raise ValueError("missing required field: battleInfo.battleDetailUrl")
        query = url.split("?", 1)[1]
        params = {}
        for pair in query.split("&"):
            if "=" in pair:
                key, value = pair.split("=", 1)
                params[key] = value
        if "acntCamp" not in params:
            raise ValueError("missing required field: acntCamp in battleDetailUrl")
        return int(params["acntCamp"])

    def _is_auth(raw_player):
        rid = _int(raw_player["roleId"], "roleId")
        uid = _int(raw_player["userId"], "userId")
        role_name = raw_player["roleInfo"]["roleName"]
        return rid != 0 and uid != 0 and role_name != "未授权游戏信息"

    def _convert_player(raw_player):
        return {
            "basicInfo": {
                "roleId": _int(raw_player["roleId"], "roleId"),
                "userId": _int(raw_player["userId"], "userId"),
                "roleName": raw_player["roleInfo"]["roleName"],
                "isGameAuth": _is_auth(raw_player),
            },
            "heroBehavior": {
                "winNum": _int(raw_player["win"], "win"),
                "loseNum": _int(raw_player["lost"], "lost"),
                "avgScore": "8.0",
                "winRate": raw_player["winRate"],
            },
            "battleRecords": {
                "usedHero": {
                    "heroName": raw_player["heroName"],
                    "heroIcon": raw_player["heroIcon"],
                }
            },
            "battleStats": {
                "fightPower": _int(raw_player["heroFightValue"], "heroFightValue"),
            },
        }

    if not isinstance(watchbattle_json, dict):
        raise TypeError("watchbattle_json must be dict")

    source = watchbattle_json["data"] if "data" in watchbattle_json else watchbattle_json
    battle_info = source["battleInfo"] if "battleInfo" in source else source
    if not isinstance(battle_info, dict):
        raise TypeError("battle_info must be dict")

    camp1 = battle_info["camp1"]
    camp2 = battle_info["camp2"]
    red_roles = [_convert_player(player) for player in camp1]
    blue_roles = [_convert_player(player) for player in camp2]

    target_roleid = int(roleid) if roleid is not None else int(battle_info["roleInfo"]["roleId"])

    head_acnt_camp = None
    for player in camp1:
        if int(player["roleId"]) == target_roleid:
            head_acnt_camp = 1
            break
    if head_acnt_camp is None:
        for player in camp2:
            if int(player["roleId"]) == target_roleid:
                head_acnt_camp = 2
                break

    if head_acnt_camp is None:
        head_acnt_camp = _extract_acnt_camp_from_url(battle_info["battleDetailUrl"])

    # if game_result is None:
    #     raise ValueError("missing required arg: game_result")

    return {
        "head": {
            "acntCamp": int(head_acnt_camp),
            "gameResult": True,
        },
        "redTeam": {
            "acntCamp": 1,
        },
        "redRoles": red_roles,
        "blueRoles": blue_roles,
    }
def spoiler_process(battle_id,roleid,userid):
    import math
    raw_res=wzry_get_official(reqtype="watchbattle",battle_id=battle_id,roleid=roleid,userid=userid)
    res=watchbattleinfo_to_coplayer_res(raw_res)
    coplayer_txt,pic_path,stats=coplayer_process(-1,-1,-1,-1,-1,spoiler_info=res)
    
    # 计算预测胜率
    # 结合底蕴(level)和英雄梯度(tier)
    # 修正逻辑：
    # 底蕴：范围 [10, 70]，差值一般在 [-20, 20]，权重约 0.05
    # 梯度：范围 [20, 70]，差值可能较大，权重约 0.04
    def win_rate_sigmoid(level_diff, tier_diff):
        # 权重设置：底蕴权重 0.05, 梯度权重 0.04
        score = level_diff * 0.05 + tier_diff * 0.04
        return 1 / (1 + math.exp(-score))

    level_diff = stats["my_side_level"] - stats["op_side_level"]
    tier_diff = stats["my_side_tier"] - stats["op_side_tier"]
    
    predicted_win_rate = win_rate_sigmoid(level_diff, tier_diff)
    win_rate_str = f"预测我方胜率：{round(predicted_win_rate * 100, 2)}%\n"

    describe_txt=f"对局预言：{raw_res['battleID']}\n{raw_res['battleInfo']['roleInfo']['roleInfo']['roleName']}  {raw_res['battleInfo']['mapName']}  {raw_res['battleInfo']['roleInfo']['heroName']}\n\n"
    # ret_txt=describe_txt + win_rate_str + coplayer_txt
    ret_txt=describe_txt + coplayer_txt
    return ret_txt,pic_path
def coplayer_process(gameSvrId, relaySvrId, gameseq, pvptype,roleid,spoiler_info,from_web=False,return_power_data=False,official_priority="normal",save_power_history=False,with_ai_analysis=False):
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
            result['profile_res'] = wzry_get_official(reqtype="profile", roleid=roleid, userid=userid, priority=official_priority)
        except Exception as e:
            result['errors'].append(str(e))
        try:
            result['heropower_res'] = wzry_get_official(reqtype="heropower", roleid=roleid, userid=userid, priority=official_priority)
        except Exception as e:
            result['errors'].append(str(e))
        try:
            result['recentbtl_res'] = wzry_get_official(reqtype="btlist_url", roleid=roleid, userid=userid, priority=official_priority)
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
        player_power_data=[]
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
                    if (official_btls):
                        if (len(official_btls)>=10):
                            RecentWinRate=sum(1 for btl in official_btls if (btl["result"]))/len(official_btls)
                        RecentAvgScore=sum(btl["grade"] for btl in official_btls)/len(official_btls)
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
                * pow((8.0 + RecentAvgScore) / 2, 1)                       # avgScore          该英雄历史场次平均评分 + 近期场次平均评分                       1
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
            player_power_data.append({
                "side": "my" if is_my_side else "op",
                "roleId": roleid,
                "userId": userid,
                "nickname": nickname,
                "isAuth": is_auth,
                "heroName": heroName,
                "position": player.get("battleRecords", {}).get("position"),
                "playerAvatarUrl": player_avatar_url,
                "heroAvatarUrl": heroAvatar,
                "heroPower": heroPower,
                "heroTag": heroTag,
                "maxHeroTag": MaxHeroTag,
                "winNum": winNum,
                "loseNum": loseNum,
                "heroShowCnt": HeroShowCnt,
                "heroAvgScore": avgScore,
                "heroWinRate": winRate,
                "rankName": rankName,
                "rankStar": rankStar,
                "starNum": starNum,
                "peakScore": peakScore,
                "equivStar": equiv_star,
                "powerNum": PowerNum,
                "totalCnt": TotalCnt,
                "mvpCnt": MVPCnt,
                "mvpRate": MVPRate,
                "recentWinRate": RecentWinRate,
                "recentAvgScore": RecentAvgScore,
                "betterHeroPower": BetterHeroPower,
                "maxHeroPower": MaxHeroPower,
                "singleLevel": single_level if is_auth else 0,
                "requestErrors": cached_data.get('errors', []) if is_auth else [],
            })
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
        return ret_level,auth_cnt,req_error,player_power_data

    gen_inst=CoPlayerProcess()
    is_spoiler=1 if spoiler_info else 0
    if (is_spoiler):
        res=spoiler_info
    else:
        res = fetch_battle(gameseq,roleid)
        if not res:
            res=wzry_get_official(reqtype="btldetail",gameseq=gameseq,gameSvrId=gameSvrId,relaySvrId=relaySvrId,roleid=roleid,pvptype=pvptype,priority=official_priority)
    if ('head' not in res): return None
    gameres=res['head']['gameResult']
    my_side_detail=res['redRoles'] if (res['redTeam']['acntCamp']==res['head']['acntCamp']) else res['blueRoles']
    op_side_detail=res['redRoles'] if (res['redTeam']['acntCamp']!=res['head']['acntCamp']) else res['blueRoles']
    lineup_ai_future = None
    lineup_ai_executor = None
    if with_ai_analysis and not is_spoiler:
        lineup_ai_executor = ThreadPoolExecutor(max_workers=1)
        lineup_ai_future = lineup_ai_executor.submit(
            battle_lineup_ai_process,
            _battle_lineup_items(my_side_detail),
            _battle_lineup_items(op_side_detail),
        )
    # my_side_detail=my_side_detail[0:1]
    # op_side_detail=op_side_detail[0:1]
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

    my_side_total_level,my_side_auth_cnt,my_side_req_error,my_side_power_data=get_player_power(my_side_detail,1,player_data_cache)
    op_side_total_level,op_side_auth_cnt,op_side_req_error,op_side_power_data=get_player_power(op_side_detail,0,player_data_cache)
    
    my_side_total_tier = get_hero_tier(my_side_detail)
    op_side_total_tier = get_hero_tier(op_side_detail)
    matchup = hero_matchup_process(my_side_detail, op_side_detail)
    ai_analysis = ""
    if lineup_ai_future:
        try:
            ai_analysis = lineup_ai_future.result()
        except Exception as error:
            log_message(f"BATTLE_LINEUP_AI_FUTURE_ERROR: {repr(error)}")
        finally:
            lineup_ai_executor.shutdown(wait=False)

    delta_level=my_side_total_level-op_side_total_level

    if (op_side_total_level and my_side_total_level):
        from .ztime import current_datetime_text

        record = {
            'created_at': current_datetime_text(),
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
        redis_client.rpush(REDIS_KEY_BATTLE_EVALUATOR_RECORDS, json.dumps(record, ensure_ascii=False))
        max_records = max(1, int(getattr(dmc, "BtlAnalyzeEvaluatorMaxRecords", 10000)))
        redis_client.ltrim(REDIS_KEY_BATTLE_EVALUATOR_RECORDS, -max_records, -1)

    snd_msg=(
        f"实力天平倾斜度：{round(delta_level,2) if op_side_total_level else "unknown"}\n"
        f"我方底蕴：{round(my_side_total_level,2) if my_side_total_level else "unknown"}\n"
        f"我方英雄梯度：{round(my_side_total_tier,2)}\n"
        f"对方底蕴：{round(op_side_total_level,2) if op_side_total_level else "unknown"}\n"
        f"对方英雄梯度：{round(op_side_total_tier,2)}\n"
        + (
            f"英雄对位胜率：{round(matchup['winRate'] * 100, 1)}%（近30天，{matchup['sampleMatches']}局）\n"
            if matchup.get("winRate") is not None
            else "英雄对位胜率：暂无有效样本\n"
        )
    )
    save_path=os.path.join(temp_path,"temp_files","coplayer_analyses.png")

    pic_title="对局预言" if is_spoiler else "对局底蕴"
    matchup_subtitle = (
        f"英雄对位胜率 {matchup['winRate'] * 100:.1f}% · 近30天 {matchup['sampleMatches']} 局"
        if matchup.get("winRate") is not None
        else "英雄对位胜率 · 暂无有效样本"
    )
    out_path, ok = gen_inst.gen(save_path,title=pic_title,subtitle=matchup_subtitle)

    stats = {
        "my_side_level": my_side_total_level,
        "op_side_level": op_side_total_level,
        "my_side_tier": my_side_total_tier,
        "op_side_tier": op_side_total_tier,
        "matchup": matchup,
    }

    if (return_power_data):
        power_data = {
            "GameSeq": str(gameseq),
            "gameSvrId": gameSvrId,
            "relaySvrId": relaySvrId,
            "pvptype": pvptype,
            "roleid": roleid,
            "mapName": res.get("head", {}).get("mapName") or res.get("battle", {}).get("mapName", ""),
            "gameTime": res.get("head", {}).get("dtEventTime") or res.get("battle", {}).get("dtEventTime", ""),
            "gameResult": gameres,
            "mySide": {
                "level": my_side_total_level,
                "tier": my_side_total_tier,
                "authCnt": my_side_auth_cnt,
                "requestErrors": my_side_req_error,
            },
            "opSide": {
                "level": op_side_total_level,
                "tier": op_side_total_tier,
                "authCnt": op_side_auth_cnt,
                "requestErrors": op_side_req_error,
            },
            "players": my_side_power_data + op_side_power_data,
            "matchup": matchup,
            "aiAnalysis": ai_analysis,
        }
        if (save_power_history and not is_spoiler):
            from .ztime import time_r

            power_data["evaluatedAt"] = time_r().strftime("%Y-%m-%d %H:%M:%S")
            BattlePowerHistory.save(power_data)
        return snd_msg,save_path,stats,power_data

    return snd_msg,save_path,stats

class BattlePowerHistory:
    @staticmethod
    def path(gameseq):
        return os.path.join("data","history","power",f"{gameseq}.json")

    @staticmethod
    def failed_path(gameseq):
        return os.path.join("data","history","power_failed",f"{gameseq}.json")

    @staticmethod
    def side(power_data, side_key):
        return power_data.get(side_key, {}) if isinstance(power_data, dict) else {}

    @staticmethod
    def display_value(value):
        return round(value, 2) if value else "unknown"

    @staticmethod
    def message(power_data):
        my_side = BattlePowerHistory.side(power_data, "mySide")
        op_side = BattlePowerHistory.side(power_data, "opSide")
        my_side_level = my_side.get("level") or 0
        op_side_level = op_side.get("level") or 0
        my_side_tier = my_side.get("tier") or 0
        op_side_tier = op_side.get("tier") or 0
        delta_level = my_side_level - op_side_level
        matchup = power_data.get("matchup") or {}
        return (
            f"实力天平倾斜度：{BattlePowerHistory.display_value(delta_level) if op_side_level else "unknown"}\n"
            f"我方底蕴：{BattlePowerHistory.display_value(my_side_level)}\n"
            f"我方英雄梯度：{round(my_side_tier,2)}\n"
            f"对方底蕴：{BattlePowerHistory.display_value(op_side_level)}\n"
            f"对方英雄梯度：{round(op_side_tier,2)}\n"
            + (
                f"英雄对位胜率：{round(matchup['winRate'] * 100, 1)}%（近30天，{matchup.get('sampleMatches', 0)}局）\n"
                if matchup.get("winRate") is not None
                else "英雄对位胜率：暂无有效样本\n"
            )
        )

    @staticmethod
    def stats(power_data):
        my_side = BattlePowerHistory.side(power_data, "mySide")
        op_side = BattlePowerHistory.side(power_data, "opSide")
        return {
            "my_side_level": my_side.get("level") or 0,
            "op_side_level": op_side.get("level") or 0,
            "my_side_tier": my_side.get("tier") or 0,
            "op_side_tier": op_side.get("tier") or 0,
            "matchup": power_data.get("matchup") or {},
        }

    @staticmethod
    def add_player_to_image(gen_inst, player):
        hero_show_cnt = int(player.get("heroShowCnt") or 0)
        win_rate = float(player.get("heroWinRate") or 0)
        win_num = player.get("winNum")
        lose_num = player.get("loseNum")
        if win_num is None or lose_num is None:
            win_num = int(round(hero_show_cnt * win_rate))
            lose_num = max(hero_show_cnt - win_num, 0)
        gen_inst.add_player(
            nickname=player.get("nickname", "未知玩家"),
            is_auth=bool(player.get("isAuth")),
            is_my_side=player.get("side") == "my",
            winNum=int(win_num or 0),
            loseNum=int(lose_num or 0),
            avgScore=float(player.get("heroAvgScore") or 0),
            winRate=win_rate,
            avatarUrl=player.get("playerAvatarUrl", ""),
            starNum=player.get("starNum"),
            peakScore=player.get("peakScore"),
            PowerNum=player.get("powerNum"),
            TotalCnt=player.get("totalCnt"),
            MVPCnt=player.get("mvpCnt"),
            rankName=player.get("rankName"),
            rankStar=player.get("rankStar"),
            single_level=player.get("singleLevel"),
            HeroAvatar=player.get("heroAvatarUrl", ""),
            HeroPower=player.get("heroPower"),
            HeroTag=player.get("heroTag", ""),
            MaxHeroTag=player.get("maxHeroTag", ""),
        )

    @staticmethod
    def image(power_data):
        from .tools.gen_coplayer_analyses import CoPlayerProcess

        gen_inst = CoPlayerProcess()
        for player in power_data.get("players", []):
            BattlePowerHistory.add_player_to_image(gen_inst, player)
        save_path=os.path.join(temp_path,"temp_files","coplayer_analyses.png")
        matchup = power_data.get("matchup") or {}
        subtitle = (
            f"英雄对位胜率 {matchup['winRate'] * 100:.1f}% · 近30天 {matchup.get('sampleMatches', 0)} 局"
            if matchup.get("winRate") is not None
            else "英雄对位胜率 · 暂无有效样本"
        )
        gen_inst.gen(save_path,title="对局底蕴",subtitle=subtitle)
        return save_path

    @staticmethod
    def rounded(data):
        if isinstance(data, float):
            return round(data, 3)
        if isinstance(data, list):
            return [BattlePowerHistory.rounded(item) for item in data]
        if isinstance(data, dict):
            return {key: BattlePowerHistory.rounded(value) for key, value in data.items()}
        return data

    @staticmethod
    def load(gameseq):
        from .zfile import readerl
        from .zfile import file_exist

        if not gameseq:
            return None
        try:
            from .zdb import read_battle_power

            database_payload = read_battle_power(gameseq)
            if isinstance(database_payload, dict):
                return database_payload
        except Exception as exc:
            log_message(f"POSTGRES_POWER_READ_FALLBACK: GameSeq={gameseq} error={repr(exc)}", logging.WARNING)
        if not file_exist(BattlePowerHistory.path(gameseq)):
            return None
        saved_power_data = readerl(BattlePowerHistory.path(gameseq))
        if isinstance(saved_power_data, dict):
            return saved_power_data
        raise Exception(f"load_battle_power_history_error: invalid saved data GameSeq={gameseq}")

    @staticmethod
    def exists(gameseq):
        if not gameseq:
            return False
        try:
            from .zdb import battle_power_exists

            if battle_power_exists(gameseq):
                return True
        except Exception as exc:
            log_message(f"POSTGRES_POWER_EXISTS_FALLBACK: GameSeq={gameseq} error={repr(exc)}", logging.WARNING)
        from .zfile import file_exist

        return file_exist(BattlePowerHistory.path(gameseq))

    @staticmethod
    def save(power_data):
        from .zfile import ensure_dir
        from .zfile import writerl
        from .zfile import file_exist

        gameseq = power_data.get("GameSeq")
        if not gameseq:
            raise Exception("save_battle_power_history_error: missing GameSeq")
        map_name = power_data.get("mapName", "")
        if not check_btl_official(map_name):
            log_message(f"SKIP_SAVE_BATTLE_POWER_NON_OFFICIAL: GameSeq={gameseq} mapName={map_name}")
            return None
        ensure_dir(os.path.join("data","history","power"))
        power_data = BattlePowerHistory.rounded(power_data)
        writerl(BattlePowerHistory.path(gameseq), power_data)
        if not file_exist(BattlePowerHistory.path(gameseq)):
            raise Exception(f"save_battle_power_history_error: write failed GameSeq={gameseq}")
        return BattlePowerHistory.path(gameseq)

    @staticmethod
    def failed_exists(gameseq):
        from .zfile import file_exist

        return bool(gameseq and file_exist(BattlePowerHistory.failed_path(gameseq)))

    @staticmethod
    def mark_failed(gameseq, reason, candidate=None):
        from .zfile import ensure_dir
        from .zfile import writerl
        from .ztime import time_r

        if not gameseq:
            raise Exception("mark_battle_power_failed_error: missing GameSeq")
        ensure_dir(os.path.join("data","history","power_failed"))
        failed_data = {
            "GameSeq": str(gameseq),
            "failedAt": time_r().strftime("%Y-%m-%d %H:%M:%S"),
            "reason": str(reason),
            "candidate": candidate or {},
        }
        writerl(BattlePowerHistory.failed_path(gameseq), failed_data)
        return BattlePowerHistory.failed_path(gameseq)

    @staticmethod
    def normalize_params(game_params):
        params = dict(game_params)
        if "gameseq" not in params and "GameSeq" in params:
            params["gameseq"] = params["GameSeq"]
        return params

    @staticmethod
    def saved_response(power_data, gen_image, with_ai_analysis=False):
        if with_ai_analysis and not power_data.get("aiAnalysis"):
            my_lineup = [player for player in power_data.get("players", []) if player.get("side") == "my"]
            op_lineup = [player for player in power_data.get("players", []) if player.get("side") == "op"]
            power_data["aiAnalysis"] = battle_lineup_ai_process(my_lineup, op_lineup)
        stats = BattlePowerHistory.stats(power_data)
        pic_path = BattlePowerHistory.image(power_data) if gen_image else ""
        return BattlePowerHistory.message(power_data),pic_path,stats,power_data

    @staticmethod
    def parse_game_time(detail, gameseq):
        import datetime

        game_time = detail.get("GameTime_Timestamp")
        if not game_time:
            return None
        try:
            return datetime.datetime.fromtimestamp(int(game_time))
        except Exception as e:
            log_message(f"HISTORY_POWER_TIME_PARSE_ERROR: {gameseq} {str(e)}")
            return None

    @staticmethod
    def should_skip_candidate(gameseq, excluded_gameseqs):
        from .zfile import file_exist

        if not gameseq or gameseq in excluded_gameseqs:
            return True
        if BattlePowerHistory.exists(gameseq):
            return True
        if BattlePowerHistory.failed_exists(gameseq):
            return True
        return False

    @staticmethod
    def begin_in_progress(gameseq):
        gameseq = str(gameseq)
        with dmc.BattlePowerInProgressLock:
            progress = dmc.BattlePowerInProgress.get(gameseq)
            if progress:
                return progress, False
            progress = {
                "event": threading.Event(),
                "error": "",
            }
            dmc.BattlePowerInProgress[gameseq] = progress
            return progress, True

    @staticmethod
    def finish_in_progress(gameseq, progress, error=None):
        gameseq = str(gameseq)
        if error:
            progress["error"] = str(error)
        with dmc.BattlePowerInProgressLock:
            current_progress = dmc.BattlePowerInProgress.get(gameseq)
            if current_progress is progress:
                dmc.BattlePowerInProgress.pop(gameseq, None)
        progress["event"].set()

    @staticmethod
    def wait_in_progress(gameseq, progress, gen_image, with_ai_analysis=False):
        gameseq = str(gameseq)
        log_message(f"BATTLE_POWER_WAIT_IN_PROGRESS: GameSeq={gameseq}")
        progress["event"].wait()
        saved_power_data = BattlePowerHistory.load(gameseq)
        if saved_power_data:
            return BattlePowerHistory.saved_response(saved_power_data, gen_image, with_ai_analysis)
        if progress.get("error"):
            raise Exception(f"battle_power_process_wait_failed: GameSeq={gameseq} {progress['error']}")
        if BattlePowerHistory.failed_exists(gameseq):
            raise Exception(f"battle_power_process_wait_skipped_failed: GameSeq={gameseq}")
        raise Exception(f"battle_power_process_wait_missing_result: GameSeq={gameseq}")

def mark_battle_power_failed(gameseq, reason, candidate=None):
    return BattlePowerHistory.mark_failed(gameseq, reason, candidate)

def battle_power_process(gameSvrId, relaySvrId, gameseq, pvptype, roleid, spoiler_info=None, from_web=False, official_priority="normal", save_power_history=True, gen_image=True, with_ai_analysis=False):
    from .ztime import time_r

    spoiler_info = spoiler_info or {}
    progress = None
    is_owner = False
    if (not spoiler_info):
        saved_power_data = BattlePowerHistory.load(gameseq)
        if saved_power_data:
            return BattlePowerHistory.saved_response(saved_power_data, gen_image, with_ai_analysis)
        if BattlePowerHistory.failed_exists(gameseq):
            raise Exception(f"battle_power_process_skipped_failed: GameSeq={gameseq}")
        if save_power_history:
            progress, is_owner = BattlePowerHistory.begin_in_progress(gameseq)
            if not is_owner:
                return BattlePowerHistory.wait_in_progress(gameseq, progress, gen_image, with_ai_analysis)
    try:
        ret = coplayer_process(
            gameSvrId,
            relaySvrId,
            gameseq,
            pvptype,
            roleid,
            spoiler_info=spoiler_info,
            from_web=from_web,
            return_power_data=True,
            official_priority=official_priority,
            save_power_history=save_power_history,
            with_ai_analysis=with_ai_analysis,
        )
        snd_msg,pic_path,stats,power_data = ret
        if (save_power_history and not spoiler_info and not power_data.get("evaluatedAt")):
            power_data["evaluatedAt"] = time_r().strftime("%Y-%m-%d %H:%M:%S")
            BattlePowerHistory.save(power_data)
        return snd_msg,pic_path,stats,power_data
    except Exception as e:
        if progress and is_owner:
            progress["error"] = repr(e)
        raise
    finally:
        if progress and is_owner:
            BattlePowerHistory.finish_in_progress(gameseq, progress)

def evaluate_battle_power_history(game_params, roleid, official_priority="low"):
    from .ztime import time_r

    params = BattlePowerHistory.normalize_params(game_params)
    gameseq = params.get("gameseq")
    saved_power_data = BattlePowerHistory.load(gameseq)
    if saved_power_data:
        return saved_power_data
    if BattlePowerHistory.failed_exists(gameseq):
        raise Exception(f"evaluate_battle_power_history_skipped_failed: GameSeq={gameseq}")
    _, _, _, power_data = battle_power_process(
        params.get("gameSvrId"),
        params.get("relaySvrId"),
        params.get("gameseq"),
        params.get("pvptype"),
        roleid,
        spoiler_info={},
        official_priority=official_priority,
        save_power_history=True,
    )
    if not power_data.get("evaluatedAt"):
        power_data["evaluatedAt"] = time_r().strftime("%Y-%m-%d %H:%M:%S")
        BattlePowerHistory.save(power_data)
    return power_data

def find_pending_battle_power_candidate(days=7, excluded_gameseqs=None, start_date_str=None):
    from .ztime import time_r
    import datetime

    end_date = time_r()
    if start_date_str:
        start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d")
    else:
        start_date = end_date - datetime.timedelta(days=days)
    history_data, _ = fetch_history(start_date=start_date, end_date=end_date, filter_official=True)
    candidates = []
    seen = set()
    excluded_gameseqs = {str(item) for item in (excluded_gameseqs or set())}
    for realname, details in history_data.items():
        roleid = roleidlist.get(realname)
        if not roleid:
            continue
        for detail in details:
            gameseq = str(detail.get("GameSeq") or "")
            if not gameseq or gameseq in seen:
                continue
            seen.add(gameseq)
            if BattlePowerHistory.should_skip_candidate(gameseq, excluded_gameseqs):
                continue
            game_time = detail.get("GameTime_Timestamp")
            game_time_obj = BattlePowerHistory.parse_game_time(detail, gameseq)
            if not game_time_obj:
                continue
            if game_time_obj < start_date or game_time_obj > end_date:
                continue
            params = detail.get("Params") or {}
            if not params:
                continue
            candidates.append({
                "realname": realname,
                "roleid": roleid,
                "GameSeq": gameseq,
                "GameTime": game_time,
                "Params": params,
            })
    candidates.sort(key=lambda item: item.get("GameTime") or 0, reverse=True)
    return candidates[0] if candidates else None

def recent_power_process(realname, days=7):
    from .zfile import readerl
    from .zfile import file_exist
    from .ztime import time_r
    import datetime

    roleid = roleidlist.get(realname)
    if not roleid:
        return "未找到该玩家的 roleid"
    end_date = time_r()
    start_date = end_date - datetime.timedelta(days=days)
    history_data, _ = fetch_history(userid=userlist.get(realname), start_date=start_date, end_date=end_date, filter_official=True)
    details = history_data.get(realname, [])
    valid_details = [detail for detail in details if check_btl_official(detail.get("MapName", ""))]
    rows = []
    missing = 0
    for detail in valid_details:
        gameseq = detail.get("GameSeq")
        if not gameseq or not BattlePowerHistory.exists(gameseq):
            missing += 1
            continue
        power_data = BattlePowerHistory.load(gameseq)
        if not isinstance(power_data, dict):
            missing += 1
            continue
        player_record = None
        for player in power_data.get("players", []):
            if str(player.get("roleId")) == str(roleid):
                player_record = player
                break
        if not player_record:
            missing += 1
            continue
        own_key = "mySide" if player_record.get("side") == "my" else "opSide"
        rival_key = "opSide" if own_key == "mySide" else "mySide"
        own_side = power_data.get(own_key, {})
        rival_side = power_data.get(rival_key, {})
        own_level = float(own_side.get("level") or 0)
        rival_level = float(rival_side.get("level") or 0)
        single_level = float(player_record.get("singleLevel") or 0)
        battle_player_levels = [
            float(player.get("singleLevel") or 0)
            for player in power_data.get("players", [])
            if float(player.get("singleLevel") or 0) > 0
        ]
        battle_player_avg_level = sum(battle_player_levels) / len(battle_player_levels) if battle_player_levels else 0
        rows.append({
            "GameSeq": gameseq,
            "HeroName": detail.get("HeroName"),
            "Result": detail.get("Result"),
            "GameGrade": detail.get("GameGrade"),
            "MapName": detail.get("MapName"),
            "ownLevel": own_level,
            "rivalLevel": rival_level,
            "battlePlayerAvgLevel": battle_player_avg_level,
            "singleLevelPercent": single_level / battle_player_avg_level * 100 if battle_player_avg_level else 0,
            "levelDiff": own_level - rival_level,
            "ownTier": float(own_side.get("tier") or 0),
            "rivalTier": float(rival_side.get("tier") or 0),
            "ownAuthCnt": int(own_side.get("authCnt") or 0),
            "rivalAuthCnt": int(rival_side.get("authCnt") or 0),
            "singleLevel": single_level,
        })
    if not rows:
        return f"最近{days}天没有可用的底蕴历史数据（官方对局{len(valid_details)}局，待后台评估{missing}局）"

    count = len(rows)
    avg_own = sum(row["ownLevel"] for row in rows) / count
    avg_rival = sum(row["rivalLevel"] for row in rows) / count
    avg_diff = sum(row["levelDiff"] for row in rows) / count
    avg_own_tier = sum(row["ownTier"] for row in rows) / count
    avg_rival_tier = sum(row["rivalTier"] for row in rows) / count
    avg_single = sum(row["singleLevel"] for row in rows) / count
    avg_single_percent = sum(row["singleLevelPercent"] for row in rows) / count
    win_count = sum(1 for row in rows if row["Result"] == "胜利")
    display_name = namenick.get(realname, realname)
    lines = [
        f"【{display_name}】最近{days}天对局底蕴统计",
    ]
    if missing:
        lines.append(f"已评估/官方对局：{count}/{len(valid_details)}（待评估{missing}）")
    lines.extend([
        f"胜率：{round(win_count / count * 100, 1)}%（{win_count}胜{count - win_count}负）",
        f"我方底蕴：{round(avg_own, 2)}",
        f"对方底蕴：{round(avg_rival, 2)}",
        f"底蕴差：{round(avg_diff, 2)}",
        f"个人底蕴/队友对手底蕴：{round(avg_single_percent, 1)}%",
        f"个人单人底蕴：{round(avg_single, 2)}",
        f"我方/对方英雄梯度：{round(avg_own_tier, 2)} / {round(avg_rival_tier, 2)}",
    ])
    return "\n".join(lines)

def power_rank_process(days=7):
    from .ztime import time_r
    from .zfile import ensure_dir
    from .zfile import readerl
    from .zfile import file_exist
    from .tools import gen_power_rank_table
    import datetime

    end_date = time_r()
    start_date = end_date - datetime.timedelta(days=days)
    history_data, _ = fetch_history(start_date=start_date, end_date=end_date, filter_official=True)

    rows = []
    columns = ["总局数", "我方底蕴", "对方底蕴", "个人底蕴/队友对手底蕴", "个人单人底蕴", "我方英雄梯度", "对方英雄梯度"]
    metric_keys = ["平均底蕴", "我方底蕴", "对方底蕴", "个人底蕴/队友对手底蕴", "个人单人底蕴", "我方英雄梯度", "对方英雄梯度"]
    for realname, details in history_data.items():
        roleid = roleidlist.get(realname)
        if not roleid:
            continue
        accum = {key: 0.0 for key in metric_keys}
        count = 0
        for detail in details:
            gameseq = detail.get("GameSeq")
            if not gameseq or not BattlePowerHistory.exists(gameseq):
                continue
            power_data = BattlePowerHistory.load(gameseq)
            if not isinstance(power_data, dict):
                continue
            player_record = None
            for player in power_data.get("players", []):
                if str(player.get("roleId")) == str(roleid):
                    player_record = player
                    break
            if not player_record:
                continue
            own_key = "mySide" if player_record.get("side") == "my" else "opSide"
            rival_key = "opSide" if own_key == "mySide" else "mySide"
            own_side = power_data.get(own_key, {})
            rival_side = power_data.get(rival_key, {})
            own_level = float(own_side.get("level") or 0)
            rival_level = float(rival_side.get("level") or 0)
            own_tier = float(own_side.get("tier") or 0)
            rival_tier = float(rival_side.get("tier") or 0)
            single_level = float(player_record.get("singleLevel") or 0)
            battle_player_levels = [
                float(player.get("singleLevel") or 0)
                for player in power_data.get("players", [])
                if float(player.get("singleLevel") or 0) > 0
            ]
            battle_player_avg_level = sum(battle_player_levels) / len(battle_player_levels) if battle_player_levels else 0
            accum["平均底蕴"] += (own_level + rival_level) / 2
            accum["我方底蕴"] += own_level
            accum["对方底蕴"] += rival_level
            accum["个人底蕴/队友对手底蕴"] += single_level / battle_player_avg_level * 100 if battle_player_avg_level else 0
            accum["个人单人底蕴"] += single_level
            accum["我方英雄梯度"] += own_tier
            accum["对方英雄梯度"] += rival_tier
            count += 1
        if not count:
            continue
        games = {key: accum[key] / count for key in accum}
        games["总局数"] = count
        rows.append({
            "realname": realname,
            "player": namenick.get(realname, realname),
            "total": games["平均底蕴"],
            "games": games,
            "rank_value": games["平均底蕴"],
            "subs": [],
        })

    if not rows:
        return f"最近{days}天没有可用的底蕴排行数据", ""
    rows.sort(key=lambda item: float(item.get("rank_value") or 0), reverse=True)

    ts = str(round(time.time() * 1000000))
    filename_hashed = WebArtifacts.make_hash(ts)
    out_dir = ensure_dir(os.path.join("resources","wzry_images", "tmp"))
    pic_path = os.path.join(out_dir, f"power_rank_{filename_hashed}.png")
    gen_power_rank_table.gen(rows, columns, pic_path, title=f"最近{days}天底蕴排行（排位、巅峰、战队赛）")
    return "", pic_path

def fetch_history(userid=None,start_date=None,end_date=None,filter_official=True): # 所有历史数据
    from .zfile import readerl
    from .zfile import writerl
    from .ztime import str_to_time,time_r

    if (not start_date or start_date<str_to_time(record_begin_date)): start_date=str_to_time(record_begin_date)
    if (not end_date): end_date=time_r()
    try:
        from .zdb import fetch_history as fetch_history_from_db

        return fetch_history_from_db(
            userid=userid,
            start_date=start_date,
            end_date=end_date,
            filter_official=filter_official,
        )
    except Exception as exc:
        log_message(
            f"POSTGRES_FETCH_HISTORY_FALLBACK: userid={userid} start={start_date} "
            f"end={end_date} official={filter_official} error={repr(exc)}",
            logging.WARNING,
        )
    gamedetails={}
    filenames=sorted(os.listdir(os.path.join("data","history")),reverse=True)
    duration=0
    for filename in filenames:
        if not os.path.isfile(os.path.join("data","history",filename)): continue
        history_date=os.path.splitext(os.path.basename(filename))[0]
        if not bool(re.fullmatch(r'^\d{4}-\d{2}-\d{2}$', history_date)): continue
        date_parsed=str_to_time(history_date)
        if (date_parsed>end_date or date_parsed<start_date): continue
        duration+=1
        full_path=os.path.join("data","history",filename)
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

def recentgames_process(realname):
    from .ztime import time_r
    from .zapi import steam_api_recent_games
    import datetime

    # 1. 获取名字（优先使用 namenick）
    display_name = namenick.get(realname, realname)

    # 2. 获取王者荣耀时长 (最近2周)
    end_date = time_r()
    start_date = end_date - datetime.timedelta(days=14)
    
    userid = userlist.get(realname)
    wzry_seconds = 0
    if userid:
        gamedetails, _ = fetch_history(userid=userid, start_date=start_date, end_date=end_date)
        player_details = gamedetails.get(realname, [])
        for detail in player_details:
            wzry_seconds += detail.get("Duration_Second", 0)
    
    wzry_hours = round(wzry_seconds / 3600, 1)

    # 3. 获取 Steam 时长 (最近2周)
    steam_id = steam_userlist.get(realname)
    steam_hours = 0.0
    game_list = []
    
    # 将王者荣耀作为一个“游戏”加入列表
    if wzry_hours > 0:
        game_list.append(f"👑 王者荣耀: {wzry_hours}h")

    if steam_id:
        steam_api_key = confs.get("Steam", {}).get("api_key")
        if steam_api_key:
            games = steam_api_recent_games(steam_api_key, steam_id)
            if games:
                for game in games:
                    # playtime_2weeks 是分钟
                    game_2weeks_mins = game.get("playtime_2weeks", 0)
                    h = round(game_2weeks_mins / 60, 1)
                    if h > 0:
                        steam_hours += h
                        game_list.append(f"♨️ {game.get('name')}: {h}h")
    
    total_hours = round(wzry_hours + steam_hours, 1)

    # 4. 构造返回文字
    res_msg = f"🎮 {display_name} 最近2周的游戏时长：\n"
    if game_list:
        res_msg += "\n".join(game_list)
        res_msg += f"\n\n📊 总计时长：{total_hours}h"
    else:
        res_msg += "最近2周没有游戏记录哦~"
    
    return res_msg

def gametime_rank_process(days=14):
    from .ztime import time_r
    from .zfile import ensure_dir
    from .tools import gen_gametime_table
    from .zapi import steam_api_recent_games
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import datetime
    import hashlib

    end_date = time_r()
    start_date = end_date - datetime.timedelta(days=days)

    steam_api_key = confs.get("Steam", {}).get("api_key")
    steam_games_by_realname = {}
    if steam_api_key:
        steam_tasks = [(realname, steam_userlist.get(realname)) for realname in steam_userlist]
        steam_tasks = [(realname, steam_id) for realname, steam_id in steam_tasks if steam_id]
        if steam_tasks:
            max_workers = min(8, max(1, len(steam_tasks)))
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                fut_map = {ex.submit(steam_api_recent_games, steam_api_key, steam_id): realname for realname, steam_id in steam_tasks}
                for fut in as_completed(fut_map):
                    realname = fut_map[fut]
                    try:
                        steam_games_by_realname[realname] = fut.result() or []
                    except Exception as e:
                        raise Exception(f"steam_recent_games_error: {realname} {repr(e)}")

    def calc_recent_gametime(realname):
        display_name = namenick.get(realname, realname)

        userid = userlist.get(realname)
        wzry_seconds = 0
        if userid:
            gamedetails, _ = fetch_history(userid=userid, start_date=start_date, end_date=end_date)
            player_details = gamedetails.get(realname, [])
            for detail in player_details:
                wzry_seconds += detail.get("Duration_Second", 0)

        wzry_hours = wzry_seconds / 3600.0
        per_game = {}
        if wzry_hours > 0:
            per_game["王者荣耀"] = wzry_hours

        steam_id = steam_userlist.get(realname)
        steam_hours = 0.0
        if steam_id:
            games = steam_games_by_realname.get(realname, [])
            if games:
                for game in games:
                    game_2weeks_mins = game.get("playtime_2weeks", 0)
                    h = game_2weeks_mins / 60.0
                    if h > 0:
                        steam_hours += h
                        game_name = game.get("name") or "Unknown"
                        per_game[game_name] = per_game.get(game_name, 0) + h

        total_hours = wzry_hours + steam_hours
        return display_name, total_hours, per_game

    realnames = sorted(set(list(userlist.keys()) + list(steam_userlist.keys())))
    all_games = set()

    raw_rows = []
    for realname in realnames:
        display_name, total_hours, per_game = calc_recent_gametime(realname)
        if total_hours <= 0:
            continue
        raw_rows.append({"realname": realname, "player": display_name, "total": float(total_hours), "games": per_game or {}})
        for g in (per_game or {}):
            all_games.add(g)

    from .tools.gen_gametime_table import merge_gametime_rows
    rows = merge_gametime_rows(raw_rows, globals().get("sameuser", {}), namenick=namenick)

    if not rows:
        return f"最近{days}天没有可用的时长记录", ""

    ts = str(round(time.time() * 1000000))
    filename_hashed = WebArtifacts.make_hash(ts)
    out_dir = ensure_dir(os.path.join("resources","wzry_images", "tmp"))
    pic_path = os.path.join(out_dir, f"gametime_rank_{filename_hashed}.png")

    def sort_games(rows, all_games):
        if not all_games:
            return []
        sums = {}
        for item in rows:
            per_game = item.get("games") or {}
            for g, v in per_game.items():
                sums[g] = sums.get(g, 0) + float(v or 0)
        games_other = [g for g in all_games if g != "王者荣耀"]
        games_other.sort(key=lambda g: sums.get(g, 0), reverse=True)
        return (["王者荣耀"] if "王者荣耀" in all_games else []) + games_other

    game_list = sort_games(rows, all_games)
    title = f"最近{days}天游戏时长排行"
    gen_gametime_table.gen(rows, game_list, pic_path, title=title)
    return "", pic_path

def fetch_battle(gameseq,roleid=0): # 读取单局战绩具体内容
    from .zfile import read_battle_detail
    res=read_battle_detail(gameseq)
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
    def summarize_player_benefit_infos(analyzed_infos):
        summary={}
        for k,v in analyzed_infos.items():
            if (len(v["hero_info"])==0): continue
            count=sum(heroinfo[1] for heroname,heroinfo in v["hero_info"].items())
            if (count==0): continue
            wins=sum(heroinfo[0] for heroname,heroinfo in v["hero_info"].items())
            grade_sum=sum(sum(heroinfo[2]) for heroname,heroinfo in v["hero_info"].items())
            summary[k]={"count":count,"wins":wins,"grade_sum":grade_sum,"win_rate":float(wins)/count,"avg_grade":float(grade_sum)/count}
        return summary

    @staticmethod
    def build_benefit_shrinkage_rows(userid=None,time_gap=analyze_time_gap):
        from .ztime import time_r
        from .ztime import time_r_delta
        from .ztime import time_delta
        from .ztime import time_to_str

        end_date=time_r()
        start_date=time_r_delta(time_gap)
        prior_end_date=time_delta(start_date,-1)
        prior_start_date=time_r_delta(time_gap+benefit_history_gap)
        analyzed_infos=Analyses.analyze_history(userid=userid,start_date=start_date,end_date=end_date)
        prior_analyzed_infos=Analyses.analyze_history(userid=userid,start_date=prior_start_date,end_date=prior_end_date)
        recent_summary=Analyses.summarize_player_benefit_infos(analyzed_infos)
        prior_summary=Analyses.summarize_player_benefit_infos(prior_analyzed_infos)
        rows=[]
        for k,v in recent_summary.items():
            recent_win_rate=v["win_rate"]
            recent_avg_grade=v["avg_grade"]
            posterior_win_rate=recent_win_rate
            posterior_avg_grade=recent_avg_grade
            prior_info=prior_summary.get(k)
            prior_weight=0
            if (prior_info):
                prior_weight=min(prior_info["count"],max(benefit_prior_min_games,v["count"]),benefit_prior_max_games)
                posterior_win_rate=(v["wins"]+prior_info["win_rate"]*prior_weight)/(v["count"]+prior_weight)
                posterior_avg_grade=(v["grade_sum"]+prior_info["avg_grade"]*prior_weight)/(v["count"]+prior_weight)
            posterior_metric=pow(posterior_avg_grade,2)/(math.exp(posterior_win_rate))
            recent_metric=pow(recent_avg_grade,2)/(math.exp(recent_win_rate))
            rows.append({
                "player": k,
                "nickname": namenick.get(k,k),
                "recent_count": v["count"],
                "recent_wins": v["wins"],
                "recent_win_rate": recent_win_rate,
                "recent_avg_grade": recent_avg_grade,
                "recent_metric": recent_metric,
                "prior_count": prior_info["count"] if prior_info else 0,
                "prior_wins": prior_info["wins"] if prior_info else 0,
                "prior_win_rate": prior_info["win_rate"] if prior_info else None,
                "prior_avg_grade": prior_info["avg_grade"] if prior_info else None,
                "prior_weight": prior_weight,
                "posterior_win_rate": posterior_win_rate,
                "posterior_avg_grade": posterior_avg_grade,
                "posterior_metric": posterior_metric,
                "metric_delta": posterior_metric-recent_metric,
            })
        rows=sorted(rows,key=lambda item:item["posterior_metric"])
        meta={
            "time_gap": time_gap,
            "benefit_history_gap": benefit_history_gap,
            "benefit_prior_min_games": benefit_prior_min_games,
            "benefit_prior_max_games": benefit_prior_max_games,
            "recent_start": time_to_str(start_date,"%Y-%m-%d"),
            "recent_end": time_to_str(end_date,"%Y-%m-%d"),
            "prior_start": time_to_str(prior_start_date,"%Y-%m-%d"),
            "prior_end": time_to_str(prior_end_date,"%Y-%m-%d"),
            "formula": "posterior_avg_grade^2 / exp(posterior_win_rate)",
        }
        return rows,meta

    @staticmethod
    def get_benefit_debug_payload(userid=None,time_gap=analyze_time_gap):
        from .ztime import time_r
        from .ztime import time_to_str

        rows,meta=Analyses.build_benefit_shrinkage_rows(userid=userid,time_gap=time_gap)
        meta["generated_at"]=time_to_str(time_r())
        return {"meta":meta,"rows":rows}

    @staticmethod
    def get_benefit_data(userid=None,time_gap=analyze_time_gap): # 评分^2/exp(胜率)： exp防止胜率0附近斜率过大 # 值越大越受害 值越小越受益
        rows,meta=Analyses.build_benefit_shrinkage_rows(userid=userid,time_gap=time_gap)
        # print(analyzed_infos)

        user_low_grade_winrate_ratio="" # 评分胜率比最低
        user_high_grade_winrate_ratio="" # 评分胜率比最高
        low_grade_winrate_ratio=10000
        high_grade_winrate_ratio=0
        player_benefit={}
        for item in rows: # 为了评判机制受益程度，或许评分与上星比值更为合理（评分：实力，上星：受益），胜率与上星无必然关联
            k=item["player"]
            win_rate=item["posterior_win_rate"]
            aver_grade=item["posterior_avg_grade"]
            grade_winrate_ratio=item["posterior_metric"]
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
    emoji_url=f"http://{confs['WebService']['server_domain']}/doraemon_emojis/{index}.jpg"
    return emoji_url


_BILI_VIDEO_SUBSCRIPTIONS_REDIS_KEY = "hok:bili:subscriptions"


from .business import bili_video as _bili_video_business


def _bili_video_normalize_subscription_item(item):
    return _bili_video_business._bili_video_normalize_subscription_item(item)


def _bili_video_normalize_subscriptions(subscriptions):
    return _bili_video_business._bili_video_normalize_subscriptions(subscriptions)


def _bili_video_get_subscriptions():
    try:
        subscriptions = _bili_video_normalize_subscriptions(
            _redis_get_json(_BILI_VIDEO_SUBSCRIPTIONS_REDIS_KEY, default={})
        )
        return subscriptions
    except Exception as error:
        log_message(f"BILI_VIDEO_SUBSCRIPTION_REDIS_READ_ERROR: {repr(error)}")
        return {}


def _bili_video_save_subscriptions(subscriptions):
    subscriptions = _bili_video_normalize_subscriptions(subscriptions)
    _redis_set_json(_BILI_VIDEO_SUBSCRIPTIONS_REDIS_KEY, subscriptions)


def _bili_video_subscription_items_for_user(subscriptions, user_qid):
    return _bili_video_business._bili_video_subscription_items_for_user(
        subscriptions, user_qid
    )


def _bili_video_set_subscription_items_for_user(subscriptions, user_qid, items):
    return _bili_video_business._bili_video_set_subscription_items_for_user(
        subscriptions, user_qid, items
    )


def _bili_video_iter_subscription_items(subscriptions):
    return _bili_video_business._bili_video_iter_subscription_items(subscriptions)


def _bili_video_identity_key(up_mid, up_name=""):
    return _bili_video_business._bili_video_identity_key(up_mid, up_name)


def _bili_video_seen_key(up_mid, up_name=""):
    return _bili_video_business._bili_video_seen_key(up_mid, up_name)


def _bili_video_seen_exists(up_mid, up_name, bvid):
    return bool(dmc.redis_deamon.sismember(_bili_video_seen_key(up_mid, up_name), str(bvid)))


def _bili_video_mark_seen(up_mid, up_name, bvids):
    clean_bvids = [str(bvid).strip() for bvid in bvids if str(bvid or "").strip()]
    if not clean_bvids:
        return 0
    return dmc.redis_deamon.sadd(_bili_video_seen_key(up_mid, up_name), *clean_bvids)


def _bili_video_seen_initialized(up_mid, up_name):
    return bool(dmc.redis_deamon.exists(_bili_video_seen_key(up_mid, up_name)))


def _bili_video_acquire_push_lock():
    from .ztime import current_epoch_seconds

    return bool(
        dmc.redis_deamon.set(
            "hok:lock:bili:video_push",
            str(current_epoch_seconds()),
            nx=True,
            ex=600,
        )
    )


def _bili_video_release_push_lock():
    return dmc.redis_deamon.delete("hok:lock:bili:video_push")


def _bili_video_send_group_message(message):
    from .utils.message_sender import add_msg

    return add_msg(message, msg_type="group", to_id=confs["QQBot"]["group_qid"])


def _bili_video_subscribed_at_epoch(item):
    return _bili_video_business._bili_video_subscribed_at_epoch(item)


def _bili_video_subscribers_by_up():
    return _bili_video_business._bili_video_subscribers_by_up()


def _bili_video_update_subscription_identity(identity, *, up_mid=None, up_name=None):
    return _bili_video_business._bili_video_update_subscription_identity(
        identity,
        up_mid=up_mid,
        up_name=up_name,
    )


def _bili_video_format_subscriber_list(user_qids):
    return _bili_video_business._bili_video_format_subscriber_list(user_qids)


def _bili_video_format_subscription_label(item):
    return _bili_video_business._bili_video_format_subscription_label(item)


def _bili_video_find_matching_items(items, query_text):
    return _bili_video_business._bili_video_find_matching_items(items, query_text)


def _bili_video_app_url(aid):
    return _bili_video_business._bili_video_app_url(aid)


def _bili_video_mobile_url(bvid):
    return _bili_video_business._bili_video_mobile_url(bvid)


def _bili_video_pic_url(video):
    return _bili_video_business._bili_video_pic_url(video)


def _cq_escape(value):
    return _bili_video_business._cq_escape(value)


def _bili_video_pic_message_segment(video):
    return _bili_video_business._bili_video_pic_message_segment(video)


def _bili_video_page_link(up_name, video):
    return _bili_video_business._bili_video_page_link(up_name, video)


def _bili_video_format_video_message(up_name, video):
    return _bili_video_business._bili_video_format_video_message(up_name, video)


def _bili_video_format_push_message(up_name, video, subscribers):
    return _bili_video_business._bili_video_format_push_message(
        up_name, video, subscribers
    )


def _bili_video_format_latest_message(up_name, video):
    return _bili_video_business._bili_video_format_latest_message(up_name, video)


def _bili_video_similarity(query, candidate_name):
    return _bili_video_business._bili_video_similarity(query, candidate_name)


def _bili_video_resolve_best_up(query):
    return _bili_video_business._bili_video_resolve_best_up(query)


def bili_video_subscribe_user(user_qid, up_name):
    return _bili_video_business.bili_video_subscribe_user(user_qid, up_name)


def bili_video_unsubscribe_user(user_qid, query_text=""):
    return _bili_video_business.bili_video_unsubscribe_user(user_qid, query_text)


def bili_video_my_subscription(user_qid):
    return _bili_video_business.bili_video_my_subscription(user_qid)


def _bili_video_latest_for_item(item):
    return _bili_video_business._bili_video_latest_for_item(item)


def bili_video_latest_for_user(user_qid):
    return _bili_video_business.bili_video_latest_for_user(user_qid)


def bili_video_list_subscriptions():
    return _bili_video_business.bili_video_list_subscriptions()


def bili_video_check_and_push(*, debug=False):
    return _bili_video_business.bili_video_check_and_push(debug=debug)


def bili_video_admin_command(raw_msg):
    return _bili_video_business.bili_video_admin_command(raw_msg)


def generate_user_emoji_image(*, user_qid: str, size=None):
    from .tools.gen_emoji_image import generate_user_emoji_image as _impl
    return _impl(user_qid=user_qid, size=size)
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
from .business import battle_metrics as _battle_metrics_business


def merge_crossday_gamedata(gamedata):
    return _battle_metrics_business.merge_crossday_gamedata(gamedata)


def calculate_official_battle_average(details):
    return _battle_metrics_business.calculate_official_battle_average(details)


def _battle_all_roles(battle_detail):
    return _battle_metrics_business._battle_all_roles(battle_detail)


def _find_battle_role(battle_detail, roleid=None, userid=None):
    return _battle_metrics_business._find_battle_role(
        battle_detail, roleid=roleid, userid=userid
    )


def _battle_role_has_assist_equip(role):
    return _battle_metrics_business._battle_role_has_assist_equip(role)


def calculate_battle_contribution_factor(
    battle_detail, roleid=None, userid=None, role=None
):
    return _battle_metrics_business.calculate_battle_contribution_factor(
        battle_detail,
        roleid=roleid,
        userid=userid,
        role=role,
    )


def calculate_official_battle_contribution_average(details, roleid):
    return _battle_metrics_business.calculate_official_battle_contribution_average(
        details, roleid
    )


def check_btl_official(btlname):
    return _battle_metrics_business.check_btl_official(btlname)


def check_btl_official_only_rank(btlname):
    return _battle_metrics_business.check_btl_official_only_rank(btlname)


def check_btl_official_with_matching(btlname):
    return _battle_metrics_business.check_btl_official_with_matching(btlname)


def check_btl_official_with_matching_with_entertain(btlname):
    return _battle_metrics_business.check_btl_official_with_matching_with_entertain(
        btlname
    )
def export_btldetail(gameinfo,roleid):
    from .zfile import writerl
    from .zfile import battle_detail_exists
    unaccessible_battles=[]
    for btl in gameinfo:
        savepath=os.path.join("data","history","battles",str(btl["GameSeq"])+".json")
        if (battle_detail_exists(btl["GameSeq"]) or not check_btl_official_with_matching_with_entertain(btl["MapName"])): continue
        try:
            res=wzry_get_official(reqtype="btldetail",roleid=roleid,**btl['Params'])
            writerl(savepath,res)
        except Exception as e:
            unaccessible_battles.append({"roleid":roleid,"GameSeq":btl["GameSeq"],"Error":str(e)})

    return unaccessible_battles

def notify_msg_impl():
    from .zutil import log_message
    from .zstatic import confs
    import datetime
    import traceback

    log_message("NOTIFY"+str(datetime.date.today()))
    snd_msg="今日王者战报(每日23:30推送)：\n"
    try:
        from .zfunc import rnk_process
        snd_msg += rnk_process(rcv_msg="", caller=None, show_zero=False, show_analyze=True)[0]
    except Exception:
        return [traceback.format_exc()] # 返回错误信息列表
    
    messages = [snd_msg]

    # 定时发送保留正式文字、图片和图片下方的 AI 文案。
    try:
        rep_btl_res = get_daily_representative_battle()
        if rep_btl_res:
            match_text, battle_image, best_battle = rep_btl_res
            messages.append((match_text, battle_image, best_battle.get("AiCommentary")))
    except Exception:
        log_message(
            "GET_REPRESENTATIVE_BATTLE_ERROR: "
            f"target_date=auto error={traceback.format_exc()}"
        )

    return messages

_KPL_PUSH_LOCK_KEY = "hok:lock:kpl:push"
_KPL_PUSH_PENDING_KEY = "hok:kpl:push_pending"
_KPL_PUSHED_CIDS_KEY = "hok:kpl:pushed_cids"


from .business import kpl as _kpl_business


def _kpl_acquire_push_lock():
    from .ztime import current_epoch_seconds

    return bool(
        dmc.redis_deamon.set(
            _KPL_PUSH_LOCK_KEY,
            str(current_epoch_seconds()),
            nx=True,
            ex=600,
        )
    )


def _kpl_release_push_lock():
    return dmc.redis_deamon.delete(_KPL_PUSH_LOCK_KEY)


def _kpl_mark_push_pending():
    return dmc.redis_deamon.set(_KPL_PUSH_PENDING_KEY, "1", ex=3600)


def _kpl_take_push_pending():
    pending = dmc.redis_deamon.get(_KPL_PUSH_PENDING_KEY)
    if pending:
        dmc.redis_deamon.delete(_KPL_PUSH_PENDING_KEY)
        return True
    return False


def _kpl_was_pushed(cid):
    return bool(dmc.redis_deamon.sismember(_KPL_PUSHED_CIDS_KEY, str(cid)))


def _kpl_mark_pushed(cid):
    return dmc.redis_deamon.sadd(_KPL_PUSHED_CIDS_KEY, str(cid))


def _kpl_save_push_image(image_url, cid, date_text):
    from .zfile import save_kpl_push_image

    return save_kpl_push_image(image_url, cid, date_text)


def _kpl_send_push_message(text, image_path, event=None):
    from .utils.message_sender import add_text_image_msg

    return add_text_image_msg(
        text,
        image_path,
        event=event,
        msg_type="group",
        to_id=confs["QQBot"]["group_qid"],
    )


def kpl_check_and_push(
    *,
    debug: bool = False,
    event=None,
    force: bool = False,
    preview_only: bool = False,
):
    return _kpl_business.kpl_check_and_push(
        debug=debug,
        event=event,
        force=force,
        preview_only=preview_only,
    )


def kpl_match_image_generate(*, match_content: dict, size: str, resolution: str):
    return _kpl_business.kpl_match_image_generate(
        match_content=match_content,
        size=size,
        resolution=resolution,
    )


def kpl_build_match_image_prompt(*, match_content: dict):
    return _kpl_business.kpl_build_match_image_prompt(match_content=match_content)


from .business import history_query as _history_query_business
from .business import representative_battle as _representative_battle_business


def _build_representative_battle_text(best_battle, title_date):
    return _representative_battle_business._build_representative_battle_text(
        best_battle, title_date
    )


def get_daily_representative_battle(target_date=None, candidates_only=False):
    return _representative_battle_business.get_daily_representative_battle(
        target_date=target_date,
        candidates_only=candidates_only,
    )


def representative_battle_query_impl(query_text):
    return _representative_battle_business.representative_battle_query_impl(query_text)


def _build_representative_category_leader_text(category_label, candidate):
    return _representative_battle_business._build_representative_category_leader_text(
        category_label, candidate
    )


def get_representative_battle_category_leaders(target_date):
    return _representative_battle_business.get_representative_battle_category_leaders(
        target_date
    )


def representative_battle_range_debug_impl(query_text):
    return _representative_battle_business.representative_battle_range_debug_impl(
        query_text
    )


def extract_heroname(origin_text, precise=False):
    return _history_query_business.extract_heroname(origin_text, precise=precise)


def txt_contain(x, y, precise, is_origin):
    return _history_query_business.txt_contain(x, y, precise, is_origin)


def history_query_handler(rcv_msg):
    return _history_query_business.history_query_handler(rcv_msg)


def format_history_query_prefix(query_desc, stats):
    return _history_query_business.format_history_query_prefix(query_desc, stats)


def history_query_single_match(detail, realname):
    return btldetail_process(
        **detail["Params"],
        roleid=roleidlist[realname],
        gen_image=True,
        individual_show=True,
    )


def history_query_multiple_matches_link(query_target, matches):
    from .zfile import write_web_history_payload
    from .ztime import current_datetime_text, current_timestamp

    now_time = current_datetime_text()
    packed_data = _history_query_business.pack_history_query_matches(
        matches,
        roleidlist,
        fetch_battle,
    )
    filename_hashed = WebArtifacts.make_hash(round(current_timestamp() * 1000000))
    write_web_history_payload(filename_hashed, packed_data)
    return WebArtifacts.history_route_link(
        filename_hashed,
        "query_select",
        query_target,
        now_time,
    )
