
from .zutil import *
from .zstatic import *
from . import zdynamic as dmc

from openai import OpenAI
import requests
from ratelimit import limits, sleep_and_retry

def wzry_get_official(reqtype,userid=-1, roleid=0,gameseq=-1,gamesvr=-1,relaysvr=-1,pvptype=-1):
    roleid=str(roleid)
    userid=str(userid)
    btldetail_url = "https://kohcamp.qq.com/game/battledetail"
    btlist_url = "https://kohcamp.qq.com/game/morebattlelist"
    profile_url = "https://kohcamp.qq.com/game/koh/profile"
    season_url = "https://kohcamp.qq.com/game/curseasonpage"
    heropower_url = "https://kohcamp.qq.com/game/profile/herolist"

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
        "gameSvr": gamesvr,
        "gameSeq": gameseq,
        "targetRoleId": roleid,
        "relaySvr": relaysvr,
        "battleType": int(pvptype)
    }
    print(btldetail_data)
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
    match reqtype:
        case "btldetail":
            url=btldetail_url
            data=btldetail_data
            # headers["content-length"]="131"
        case "btlist":
            url=btlist_url
            data=btlist_data
            # headers["content-length"]="133"
        case "profile":
            url=profile_url
            data=profile_data
            # headers["content-length"]="122"
        case "season":
            url=season_url
            data=season_data
        case "heropower":
            url=heropower_url
            data=heropower_data
    # print(userid,roleid)
    response = requests.post(url, headers=headers, json=data)
    # print(response.text)
    return response.json().get("data",{})

@sleep_and_retry    # 当达到限制时自动等待
@limits(calls=1, period=2)  # 每2秒最多调用1次 #太快返回不了
def wzry_api(userid,roleid):
    log_message("VISIT: wzry_api "+str(f"{userid} {roleid}"))
    btlist_data=wzry_get_official(reqtype="btlist",userid=userid,roleid=roleid)
    profile_data=wzry_get_official(reqtype="profile",userid=userid,roleid=roleid)
    # rnk_data
    combined_data = {
        "btlist": btlist_data,
        "profile": profile_data
    }
    # print(combined_data)
    return combined_data

@sleep_and_retry    # 当达到限制时自动等待
@limits(calls=1, period=1)  # 每1秒最多调用1次
def ai_api(user_query,temperature=1.5): # deepseek官方模型-不联网
    log_message("VISIT: ai_api_common")
    try:
        client = OpenAI(api_key=confs["QQBot"]["deepseek_key"], base_url=deepseek_url)
        
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "user", "content": user_query},
            ],
            stream=False,
            temperature=temperature
        ).
    except Exception as e:
        raise Exception("deepseek_api_error: "+str(e))
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

