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
@sleep_and_retry    # 当达到限制时自动等待
@limits(calls=3, period=1)
def wzry_get_official(reqtype,userid=-1,roleid=0,gameseq=-1,gameSvrId=-1,relaySvrId=-1,pvptype=-1,heroid=-1,rankId=-1,rankSegment=-1,battle_id=-1):
    import time
    from tools.endecoder import decrypt_game_data
    from tools.endecoder import get_full_request_params

    encoded_params = get_full_request_params(confs["wzry"]["pubkey"],confs["wzry"]["roleid"],confs["wzry"]["encoderes"])
    # print(f"crand: {encoded_params['crand']}")
    # print(f"encodeparam: {encoded_params['encodeparam']}")
    # print(f"traceparent: {encoded_params['traceparent']}")
    roleid=str(roleid)
    userid=str(userid)
    btldetail_url = "https://kohcamp.qq.com/game/battledetail"
    btlist_url = "https://kohcamp.qq.com/game/morebattlelist"
    profile_url = "https://kohcamp.qq.com/game/koh/profile"
    season_url = "https://kohcamp.qq.com/game/curseasonpage"
    heropower_url = "https://kohcamp.qq.com/game/profile/herolist"
    allhero_url= "https://ssl.kohsocialapp.qq.com/play/h5getherolist"
    herostatistics_url="https://kohcamp.qq.com/gametoolbox/hero/record/pagedetails"
    heroranklist_url="https://kohcamp.qq.com/gametoolbox/hero/getdetailranklistbyid"
    watchbattle_url = "https://kohcamp.qq.com/game/watchBattle"
    headers = {
        "Host": "kohcamp.qq.com",
        "istrpcrequest": "true",
        "cchannelid": "10360957",
        "cclientversioncode": "2057953202",
        "cclientversionname": "10.111.0205",
        "ccurrentgameid": "20001",
        "cgameid": "20001",
        "cgzip": "1",
        "cisarm64": "true",
        "crand": encoded_params["crand"],
        # "crand": "1774530804298",
        "csupportarm64": "true",
        "csystem": "android",
        "csystemversioncode": "32",
        "csystemversionname": "12",
        "cpuhardware": "Xiaomi",
        "encodeparam": encoded_params["encodeparam"],
        # "encodeparam": "26kVVHLwgvRtB6NWDBlSV3PR7wCUFoZcKrHWDx0f9awQRltcKu1U/A8eDZEc9hUhdiKMb89JkTQL7R0CCY/HM8YHZnWkRFp28HHFJGHLPNGUQu0IqQPoHMQKv25Wjqg7ZO2Sdg==",
        "gameareaid": "1",
        "gameid": "20001",
        "gameopenid": confs["wzry"]["gameopenid"],
        "gameroleid": confs["wzry"]["gameroleid"],
        "gameserverid": "1545",
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
        "user-agent": "okhttp/4.9.1",
        "traceparent": encoded_params["traceparent"]
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
        'cChannelId': 10360957,
        'cClientVersionCode': 2057953202,
        'cClientVersionName': '10.111.0205',
        'cCurrentGameId': 20001,
        'cGameId': 20001,
        'cGzip': 1,
        'cIsArm64': 'true',
        'cRand': 1774439182517,
        'cSupportArm64': 'true',
        'cSystem': 'android',
        'cSystemVersionCode': 32,
        'cSystemVersionName': '12',
        'cpuHardware': 'Xiaomi',
        'encodeParam': encoded_params["encodeparam"],
        'gameAreaId': 1,
        'gameId': 20001,
        'gameOpenId': confs["wzry"]["gameopenid"],
        'gameRoleId': confs["wzry"]["roleid"],
        'gameServerId': 1545,
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
    watchbattle_data = {
        "recommendPrivacy": 0,
        "battleID": battle_id,
        "roleID": roleid,
        "type": 1,
        "userID": userid
    }
    # watchbattle_data = {'recommendPrivacy': 0, 'battleID': '177399_1742766640_1774529852', 'roleID': '132540538', 'type': 1, 'userID': '226798579'}
    print(watchbattle_data,reqtype)
    
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
        case "watchbattle":
            url=watchbattle_url
            data=watchbattle_data
    retry_time=3
    error_msg=""
    while(retry_time):
        try:
            encoded_response = requests.post(url, headers=headers, json=data)
        except Exception as e:
            error_msg="Network error: "+str(e)
            retry_time=0
            break

        # print(encoded_response.text)
        try:
            decoded_response=json.loads(encoded_response.text)
            # print(decoded_response)

        except:
            try:

                decoded_response=decrypt_game_data(confs["wzry"]["pubkey"],confs["wzry"]["encoderes"],encoded_response.text)
            except Exception as e:
                error_msg="Decode error: "+str(e)
                retry_time=0
                break
        res=decoded_response.get("data",{})
        error_msg=decoded_response.get("returnMsg","")
        # print(res,error_msg)
        if res: break
        if ("登录态失效" in error_msg or "频繁" in error_msg or "繁忙" in error_msg or "不允许被观战" in error_msg or "本场对局已结束" in error_msg):
            retry_time=0
            break
        time.sleep(2)
        retry_time-=1
    if (not retry_time): raise Exception(str("HOK Exception: "+error_msg))
    
    # # [T调试语句] 将结果输出到文件，使用精确到毫秒的时间命名
    # import os
    # import json
    # import datetime
    
    # debug_dir = os.path.join("wzry_data_format", "debug_output")
    # os.makedirs(debug_dir, exist_ok=True)
    # time_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    # debug_filename = os.path.join(debug_dir, f"{reqtype}_{time_str}.json")
    # try:
    #     with open(debug_filename, 'w', encoding='utf-8') as f:
    #         json.dump(res, f, ensure_ascii=False, indent=4)
    #     print(f"Debug JSON saved to: {debug_filename}")
    # except Exception as e:
    #     print(f"Failed to save debug JSON: {e}")

    return res

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