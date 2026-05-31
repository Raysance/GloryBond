from openai import OpenAI
import requests
from ratelimit import limits, sleep_and_retry
import json
import yaml
import time
import os

confs={}
with open('../NBot/config.yaml', 'r') as file:
    confs = yaml.load(file, Loader=yaml.FullLoader)

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
    file_path = os.path.join(f"../NBot/history/battles/{gameseq}.json")
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
def check_battle_local_exist(gameseq,roleid=0): # 本地是否储存了战局详情
    file_path = os.path.join(f"../NBot/history/battles/{gameseq}.json")
    return file_exist(file_path)
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