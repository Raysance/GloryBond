
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


def _today_hero_cached(realname, current_date, *, ignore_limit=False):
    if ignore_limit:
        return None
    raw = dmc.TodayHeroPool.get(f"{REDIS_KEY_HERO_TODAY_PREFIX}{realname}")
    if not raw:
        return None
    payload = json.loads(raw)
    if payload.get("date") != current_date:
        return None
    return payload


def _today_hero_store(realname, payload):
    current_date = payload["date"]
    dmc.TodayHeroPool.set(
        f"{REDIS_KEY_HERO_TODAY_PREFIX}{realname}",
        json.dumps(payload),
    )
    history_key = f"{REDIS_KEY_HERO_HISTORY_PREFIX}{realname}"
    history_entry = {
        "date": current_date,
        "heroname": payload.get("heroname"),
        "skinname": payload.get("skinname"),
        "selectinfo": payload.get("selectinfo"),
    }
    history_items = dmc.TodayHeroPool.lrange(history_key, 0, -1)
    for index, raw in enumerate(history_items):
        if json.loads(raw).get("date") == current_date:
            dmc.TodayHeroPool.lset(history_key, index, json.dumps(history_entry))
            return payload
    dmc.TodayHeroPool.rpush(history_key, json.dumps(history_entry))
    return payload


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

from .business import online_status as _online_status_business


def online_process():
    return _online_status_business.online_process()
from .business import rankings as _rankings_business


def rnk_process(rcv_msg, caller=None, show_zero=True, show_analyze=False, debug=False):
    return _rankings_business.rnk_process(
        rcv_msg,
        caller=caller,
        show_zero=show_zero,
        show_analyze=show_analyze,
        debug=debug,
    )
from .business import player_report as _player_report_business


def single_process(rcv_msg):
    return _player_report_business.single_process(rcv_msg)
from .business import battle_detail as _battle_detail_business


def view_process(rcv_msg, time_gap=analyze_time_gap):
    return _battle_detail_business.view_process(rcv_msg, time_gap=time_gap)


def btldetail_process(
    gameSvrId,
    relaySvrId,
    gameseq,
    pvptype,
    roleid,
    gen_image=False,
    show_profile=False,
    from_web=False,
    individual_show=False,
    strict_filter=True,
):
    return _battle_detail_business.btldetail_process(
        gameSvrId,
        relaySvrId,
        gameseq,
        pvptype,
        roleid,
        gen_image=gen_image,
        show_profile=show_profile,
        from_web=from_web,
        individual_show=individual_show,
        strict_filter=strict_filter,
    )
from .business import hero_profiles as _hero_profiles_business


def heropower_process(realname):
    return _hero_profiles_business.heropower_process(realname)


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

from .business import today_hero as _today_hero_business


def todayhero_process(realname, ignore_limit=False, ai_comment=True):
    return _today_hero_business.todayhero_process(
        realname,
        ignore_limit=ignore_limit,
        ai_comment=ai_comment,
    )
def allhero_process(realname):
    return _hero_profiles_business.allhero_process(realname)
from .business import player_visuals as _player_visuals_business


def gradeanalyze_process(realname):
    return _player_visuals_business.gradeanalyze_process(realname)


def watchbattle_process(realname):
    return _player_visuals_business.watchbattle_process(realname)
from .business import battle_watch as _battle_watch_business


def watchbattleinfo_to_coplayer_res(watchbattle_json, roleid=None, game_result=None):
    return _battle_watch_business.watchbattleinfo_to_coplayer_res(
        watchbattle_json,
        roleid=roleid,
        game_result=game_result,
    )
def spoiler_process(battle_id,roleid,userid):
    return _battle_watch_business.spoiler_process(battle_id, roleid, userid)
from .business import battle_power as _battle_power_business

BattlePowerHistory = _battle_power_business.BattlePowerHistory


def record_battle_evaluator(record):
    redis_client = dmc.BtlAnalyzeEvaluatorPool
    redis_client.rpush(
        REDIS_KEY_BATTLE_EVALUATOR_RECORDS,
        json.dumps(record, ensure_ascii=False),
    )
    max_records = max(
        1,
        int(getattr(dmc, "BtlAnalyzeEvaluatorMaxRecords", 10000)),
    )
    redis_client.ltrim(REDIS_KEY_BATTLE_EVALUATOR_RECORDS, -max_records, -1)


def coplayer_process(
    gameSvrId,
    relaySvrId,
    gameseq,
    pvptype,
    roleid,
    spoiler_info,
    from_web=False,
    return_power_data=False,
    official_priority="normal",
    save_power_history=False,
    with_ai_analysis=False,
):
    return _battle_power_business.coplayer_process(
        gameSvrId,
        relaySvrId,
        gameseq,
        pvptype,
        roleid,
        spoiler_info,
        from_web=from_web,
        return_power_data=return_power_data,
        official_priority=official_priority,
        save_power_history=save_power_history,
        with_ai_analysis=with_ai_analysis,
    )

def mark_battle_power_failed(gameseq, reason, candidate=None):
    return _battle_power_business.mark_battle_power_failed(
        gameseq,
        reason,
        candidate,
    )


def battle_power_process(
    gameSvrId,
    relaySvrId,
    gameseq,
    pvptype,
    roleid,
    spoiler_info=None,
    from_web=False,
    official_priority="normal",
    save_power_history=True,
    gen_image=True,
    with_ai_analysis=False,
):
    return _battle_power_business.battle_power_process(
        gameSvrId,
        relaySvrId,
        gameseq,
        pvptype,
        roleid,
        spoiler_info=spoiler_info,
        from_web=from_web,
        official_priority=official_priority,
        save_power_history=save_power_history,
        gen_image=gen_image,
        with_ai_analysis=with_ai_analysis,
    )


def evaluate_battle_power_history(game_params, roleid, official_priority="low"):
    return _battle_power_business.evaluate_battle_power_history(
        game_params,
        roleid,
        official_priority=official_priority,
    )


def find_pending_battle_power_candidate(
    days=7,
    excluded_gameseqs=None,
    start_date_str=None,
):
    return _battle_power_business.find_pending_battle_power_candidate(
        days=days,
        excluded_gameseqs=excluded_gameseqs,
        start_date_str=start_date_str,
    )


def recent_power_process(realname, days=7):
    return _battle_power_business.recent_power_process(realname, days=days)


def power_rank_process(days=7):
    return _battle_power_business.power_rank_process(days=days)

from .business import history_data as _history_data_business


def fetch_history(
    userid=None,
    start_date=None,
    end_date=None,
    filter_official=True,
):
    return _history_data_business.fetch_history(
        userid=userid,
        start_date=start_date,
        end_date=end_date,
        filter_official=filter_official,
    )

from .business import game_activity as _game_activity_business


def recentgames_process(realname):
    return _game_activity_business.recentgames_process(realname)


def gametime_rank_process(days=14):
    return _game_activity_business.gametime_rank_process(days=days)

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
