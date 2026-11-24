import json
import time
import os
import logging

from web.database import battle_exists as postgres_battle_exists
from web.database import fetch_battle as postgres_fetch_battle
from web.database import ping as postgres_ping
from web.runtime_config import RUNTIME, load_shared_config

confs = load_shared_config()
POSTGRES_DSN = str(
    os.environ.get("HOK_DATABASE_DSN")
    or confs.get("PostgreSQL", {}).get("dsn")
    or ""
)


def check_postgres_health():
    started = time.time()
    try:
        postgres_ping(POSTGRES_DSN)
        return {"status": "ok", "latency_ms": round((time.time() - started) * 1000, 2)}
    except Exception as exc:
        return {"status": "down", "error": repr(exc)}

def writerl(filepath,data):
    try:
        with open(filepath, 'w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
        return None
    except Exception as e:
        return None
def readerl(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as file:
            data = json.load(file)
        return data
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        return []

def fetch_battle(gameseq,roleid=0): # 读取单局战绩具体内容
    file_path = os.path.join(RUNTIME.data_dir, "history", "battles", f"{gameseq}.json")
    try:
        res = postgres_fetch_battle(POSTGRES_DSN, gameseq)
    except Exception as exc:
        logging.warning("POSTGRES_BATTLE_READ_FALLBACK GameSeq=%s error=%r", gameseq, exc)
        res = None
    if not res:
        res=readerl(file_path)
    if (res and roleid):
        # 找到对应的玩家信息并更新head
        target_role = None
        for role in res.get('redRoles', []) + res.get('blueRoles', []):
            if str(role['basicInfo'].get('roleId')) == str(roleid):
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
def check_battle_local_exist(gameseq,roleid=0): # 本地是否储存了战局详情
    try:
        if postgres_battle_exists(POSTGRES_DSN, gameseq):
            return True
    except Exception as exc:
        logging.warning("POSTGRES_BATTLE_EXISTS_FALLBACK GameSeq=%s error=%r", gameseq, exc)
    file_path = os.path.join(RUNTIME.data_dir, "history", "battles", f"{gameseq}.json")
    return file_exist(file_path)

def wzry_get_official(reqtype, userid=-1, roleid=0, gameseq=-1, gameSvrId=-1,
                      relaySvrId=-1, pvptype=-1, heroid=-1, rankId=-1, rankSegment=-1,
                      battle_id=-1, *, last_time=0, honor_adcode=156):
    from shared.camp import query, session_path
    return query(session_path(RUNTIME.data_dir), reqtype, userid, roleid, gameseq,
                 gameSvrId, relaySvrId, pvptype, heroid, rankId, rankSegment,
                 battle_id, honor_adcode, last_time=last_time)


def file_exist(file_path):
    return os.path.exists(file_path)
def retry_until_true(func, timeout=1, *args, **kwargs):
    """
    重试函数直到返回True或超时
    :param func: 要重试的函数
    :param timeout: 超时时间（秒）
    :param args, kwargs: 函数的参数
    :return: 最终结果
    """
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        result = func(*args, **kwargs)
        if result:
            return result
        time.sleep(0.01)  # 短暂休眠，避免CPU占用过高
    
    # 超时后最后尝试一次
    return func(*args, **kwargs)
