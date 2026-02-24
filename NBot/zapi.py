
from .zutil import *
from .zstatic import *
from . import zdynamic as dmc

from openai import OpenAI
import requests
from ratelimit import limits, sleep_and_retry

@sleep_and_retry    # 当达到限制时自动等待
@limits(calls=1, period=1)
def wzry_get_official(reqtype,userid=-1,roleid=0,gameseq=-1,gameSvrId=-1,relaySvrId=-1,pvptype=-1,heroid=-1,rankId=-1,rankSegment=-1):
    import time
    roleid=str(roleid)
    userid=str(userid)
    headers = {
        "Host": "kohcamp.qq.com",
        "istrpcrequest": "true",
        "cchannelid": "10035044",
        "cclientversioncode": "2047937708",
        "cclientversionname": "9.104.0903",
        "ccurrentgameid": "20001",
        "cgameid": "20001",
        "cgzip": "1",
        "cisarm64": "true",
        "crand": '1758455866028',
        "csupportarm64": "true",
        "csystem": "android",
        "csystemversioncode": "32",
        "csystemversionname": "12",
        "cpuhardware": "HONOR",
        "encodeparam": confs["wzry"]["encodeparam"],
        "gameareaid": "1",
        "gameid": "20001",
        "gameopenid": confs["wzry"]["gameopenid"],
        "gameroleid": confs["wzry"]["gameroleid"],
        "gameserverid": "1533",
        "gameusersex": "1",
        "openid": confs["wzry"]["openid"],
        "tinkerid": confs["wzry"]["tinkerid"],
        "token": confs["wzry"]["token"],
        "userid": confs["wzry"]["userid"],
        "content-encrypt": "",
        "accept-encrypt": "",
        "noencrypt": "1",
        "x-client-proto": "https",
        "x-log-uid": confs["wzry"]["x-log-uid"],
        "kohdimgender": "2",
        "content-type": "application/json; charset=UTF-8",
        "accept-encoding": "gzip",
        "user-agent": "okhttp/4.9.1",
        "traceparent": confs["wzry"]["traceparent"]
    }

    btldetail_data = {
        "recommendPrivacy": 0,
        "gameSvr": gameSvrId,
        "gameSeq": gameseq,
        "targetRoleId": roleid,
        "relaySvr": relaySvrId,
        "battleType": int(pvptype)
    }
    # print(btldetail_data)
    btlist_data = {
        "lastTime": 0,
        "recommendPrivacy": 0,
        "apiVersion": 5,
        "friendRoleId": roleid,
        "isMultiGame": 1,
        "friendUserId": userid,
        "option": 0
    }
    profile_data = {
        "resVersion": 3,
        "recommendPrivacy": 0,
        "apiVersion": 2,
        "targetUserId": userid,
        "targetRoleId": roleid,
        "itsMe": False
    }
    season_data = {
        "recommendPrivacy": 0,
        "roleId": roleid
    }
    heropower_data = {
        "recommendPrivacy": 0,
        "targetUserId":userid,
        "targetRoleId":roleid
    }
    allhero_data = {
        'recommendPrivacy': 0,
        'uniqueRoleId': roleid,
        'cChannelId': 10035044,
        'cClientVersionCode': 2047937708,
        'cClientVersionName': '9.104.0903',
        'cCurrentGameId': 20001,
        'cGameId': 20001,
        'cGzip': 1,
        'cIsArm64': 'true',
        'cRand': 1760970708548,
        'cSupportArm64': 'true',
        'cSystem': 'android',
        'cSystemVersionCode': 32,
        'cSystemVersionName': '12',
        'cpuHardware': 'HONOR',
        'encodeParam': confs["wzry"]["encodeparam"],
        'gameAreaId': 1,
        'gameId': 20001,
        'gameOpenId': confs["wzry"]["gameopenid"],
        'gameRoleId': confs["wzry"]["roleid"],
        'gameServerId': 1533,
        'gameUserSex': 1,
        'openId': confs["wzry"]["openid"],
        'tinkerId': confs["wzry"]["tinkerid"],
        'token': confs["wzry"]["token"],
        'userId': confs["wzry"]["userid"]
    }
    herostatistics_data={
        "recommendPrivacy": 0,
        "toOpenid": confs["wzry"]["openid"],
        "roleId": roleid,
        "roleName": "",
        "heroid": heroid,
        "h5Get": 1
    }
    heroranklist_data={
        "recommendPrivacy": 0,
        "bottomTab": "",
        "apiVersion": 1,
        "rankId": rankId,
        "segment": rankSegment,
        "position": 0
        # 热度榜 0
        # 输出榜 7
        # MVP榜 13
        # 金牌榜 14

        # Segment
        # 所有段位 1
        # 巅峰1350+ 3
        # 顶端排位 4
        # 赛事 5
    }
    match reqtype:
        case "btldetail":
            url=btldetail_url
            data=btldetail_data
        case "btlist":
            url=btlist_url
            data=btlist_data
        case "profile":
            url=profile_url
            data=profile_data
        case "season":
            url=season_url
            data=season_data
        case "heropower":
            url=heropower_url
            data=heropower_data
        case "allhero":
            url=allhero_url
            data=allhero_data
        case "herostatistics":
            url=herostatistics_url
            data=herostatistics_data
        case "heroranklist":
            url=heroranklist_url
            data=heroranklist_data
    retry_time=5
    error_msg=""
    while(retry_time):
        response = requests.post(url, headers=headers, json=data)
        # print(response.text)
        # print(headers,data)
        res=response.json().get("data",{})
        error_msg=response.json().get("returnMsg","")
        if res: break
        if ("登录态失效" in error_msg or "操作频繁" in error_msg):
            retry_time=0
            break
        time.sleep(2)
        retry_time-=1
    if (not retry_time): raise Exception(str("HOK Exception: "+error_msg))
    # import os
    # import json
    # save_path = os.path.join("wzry_data_format", f"{reqtype}.json")
    # with open(save_path, 'w', encoding='utf-8') as sf:
    #     json.dump(res, sf, ensure_ascii=False, indent=2)
    return res

@sleep_and_retry
@limits(calls=100, period=1)
def ai_api(user_query,temperature): # deepseek官方模型-不联网
    log_message("VISIT: ai_api_common")
    try:
        client = OpenAI(api_key=confs["QQBot"]["deepseek_key"], base_url=deepseek_url)
        
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "user", "content": user_query},
            ],
            stream=False,
            temperature=temperature,
            timeout=20   # 20秒超时
        )
    except Exception as e:
        raise Exception("deepseek_api_error: "+str(e))
    random.seed(int(time.time() * 1000) % 1000000 + os.getpid())
    return response.choices[0].message.content
def ai_function(user_query):
    log_message("VISIT: ai_api_function_call")
    try:
        client = OpenAI(api_key=confs["QQBot"]["deepseek_key"], base_url=deepseek_url)
        
        response = client.chat.completions.create(
            model="deepseek-reasoner",
            messages=[
                {"role": "user", "content": user_query},
            ],
            stream=False,
            temperature=1
        )
    except Exception as e:
        raise Exception("deepseek_api_error: "+str(e))
    return response.choices[0].message.content
def ark_api(user_query): # 火山引擎-豆包联网模型
    log_message("VISIT: ark_api_common")
    try:
        client = OpenAI(api_key=confs["QQBot"]["ark_key"], base_url=ark_app_url)

        completion = client.chat.completions.create(
            model=confs["QQBot"]["ark_bot_id"],
            messages=[
                {"role": "user", "content": user_query},
            ],
        )
    except Exception as e:
        raise Exception("ark_api_error: "+str(e))
    return completion.choices[0].message.content

def tianyuanzhiyi_tier_api():
    url = "https://tianyuanzhiyi.com/api/global/tier"
    headers = {
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "priority": "u=1, i",
        "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144", "Microsoft Edge";v="144"',
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": '"Android"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.exceptions.HTTPError as e:
        return {}
