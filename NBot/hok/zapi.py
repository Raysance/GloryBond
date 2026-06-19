
from .zutil import *
from .zstatic import *
from . import zdynamic as dmc

from openai import OpenAI
import requests
from ratelimit import limits, sleep_and_retry

def _wait_official_low_priority_turn():
    import time

    while True:
        active_until = getattr(dmc, "OfficialForegroundActiveUntil", 0)
        now = time.time()
        if now < active_until:
            time.sleep(min(active_until - now, 3))
            continue
        shared_queue = getattr(dmc, "redis_deamon_share_btl", None)
        analyze_queue = getattr(dmc, "redis_deamon_analyze_btl", None)
        try:
            if shared_queue and shared_queue.llen("Shared_queue"):
                time.sleep(3)
                continue
            if analyze_queue and analyze_queue.llen("Analyze_queue"):
                time.sleep(3)
                continue
        except Exception as e:
            log_message(f"OFFICIAL_LOW_PRIORITY_QUEUE_CHECK_ERROR: {str(e)}")
        return

def wzry_get_official(reqtype,userid=-1,roleid=0,gameseq=-1,gameSvrId=-1,relaySvrId=-1,pvptype=-1,heroid=-1,rankId=-1,rankSegment=-1,battle_id=-1,priority="normal"):
    import time

    if priority == "low":
        _wait_official_low_priority_turn()
    else:
        dmc.OfficialForegroundActiveUntil = time.time() + 5
    return _wzry_get_official_impl(reqtype, userid, roleid, gameseq, gameSvrId, relaySvrId, pvptype, heroid, rankId, rankSegment, battle_id)

@sleep_and_retry
@limits(calls=1, period=1)
def _wzry_get_official_impl(reqtype,userid=-1,roleid=0,gameseq=-1,gameSvrId=-1,relaySvrId=-1,pvptype=-1,heroid=-1,rankId=-1,rankSegment=-1,battle_id=-1):
    import time
    from .tools.endecoder import decrypt_game_data
    from .tools.endecoder import get_full_request_params

    encoded_params = get_full_request_params(confs["wzry"]["pubkey"],confs["wzry"]["roleid"],confs["wzry"]["encoderes"])
    print(f"crand: {encoded_params['crand']}")
    print(f"encodeparam: {encoded_params['encodeparam']}")
    print(f"traceparent: {encoded_params['traceparent']}")
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
    print(watchbattle_data)
    
    match reqtype:
        case "btldetail":
            url=btldetail_url
            data=btldetail_data
        case "btlist":
            url=btlist_url
            data=btlist_data
        case "btlist_url":
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
    # import os
    # import jso
    # save_path = os.path.join("resources","wzry_data_format", f"{reqtype}.json")
    # with open(save_path, 'w', encoding='utf-8') as sf:
    #     json.dump(res, sf, ensure_ascii=False, indent=2)
    return res

@sleep_and_retry
@limits(calls=100, period=1)
def ai_api(user_query,temperature): # deepseek官方模型-不联网
    from .zfile import writera
    log_message("VISIT: ai_api_common")
    try:
        client = OpenAI(api_key=confs["QQBot"]["deepseek_key"], base_url=deepseek_url)
        
        response = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "user", "content": user_query},
            ],
            stream=False,
            temperature=temperature,
            timeout=20   # 20秒超时
        )
        # writera("deepseek_output.txt",user_query)
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

def ark_images_generate(*, prompt: str, reference_image_url: str, size: str):
    api_key = confs["QQBot"].get("ark_image_key") or confs["QQBot"].get("ark_key") or ""
    if not api_key:
        raise Exception("ark_images_generate_error: missing config.yaml QQBot.ark_image_key")

    base_url = "https://ark.cn-beijing.volces.com/api/v3"
    client = OpenAI(base_url=base_url, api_key=api_key)
    model = getattr(dmc, "EmojiImageModel", None) or "doubao-seedream-5-0-260128"
    extra_body = {"image": reference_image_url, "watermark": False}
    request_payload = {
        "base_url": base_url,
        "model": model,
        "prompt": prompt,
        "size": size,
        "response_format": "url",
        "extra_body": extra_body,
    }
    images_response = client.images.generate(model=model, prompt=prompt, size=size, response_format="url", extra_body=extra_body)
    if not images_response or not getattr(images_response, "data", None) or not images_response.data:
        raise Exception("ark_images_generate_error: empty response")
    url = getattr(images_response.data[0], "url", None)
    if not url:
        raise Exception("ark_images_generate_error: missing url in response")
    return {"url": url, "request": request_payload}

def apimart_images_generate(*, prompt: str, reference_image_url: str, size: str, resolution: str, task_timeout_seconds=None, task_poll_interval_seconds=None):
    api_key = confs["QQBot"].get("apimart_key") or ""
    if not api_key:
        raise Exception("apimart_images_generate_error: missing config.yaml QQBot.apimart_key")

    base_url = "https://api.apimart.ai/v1/images/generations"
    model = getattr(dmc, "EmojiImageModel", None) or "gpt-image-2"
    payload = {"model": model, "prompt": prompt, "n": 1, "size": size, "resolution": resolution}
    if reference_image_url:
        payload["image"] = reference_image_url

    request_payload = {
        "base_url": base_url,
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "resolution": resolution,
    }
    if reference_image_url:
        request_payload["image"] = reference_image_url

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        response = requests.post(base_url, json=payload, headers=headers, timeout=120)
        response.raise_for_status()
        res = response.json()
    except Exception as e:
        raise Exception(f"apimart_images_generate_error: {repr(e)}")

    if not isinstance(res, dict) or res.get("code") != 200:
        raise Exception(f"apimart_images_generate_error: unexpected response {str(res)[:500]}")

    data = res.get("data")
    if not isinstance(data, list) or not data:
        raise Exception(f"apimart_images_generate_error: missing task_id {str(res)[:500]}")

    task_id = (data[0] or {}).get("task_id")
    if not task_id:
        raise Exception(f"apimart_images_generate_error: missing task_id {str(res)[:500]}")

    request_payload["task_id"] = task_id

    task_url = f"https://api.apimart.ai/v1/tasks/{task_id}"
    timeout_seconds = task_timeout_seconds or 120
    poll_interval_seconds = task_poll_interval_seconds or 2
    poll_request_payload = {"base_url": task_url, "task_id": task_id, "timeout_seconds": timeout_seconds, "poll_interval_seconds": poll_interval_seconds}
    request_payload["poll"] = poll_request_payload

    last_status = None
    for _ in range(max(1, int(timeout_seconds / poll_interval_seconds))):
        try:
            task_resp = requests.get(task_url, headers=headers, timeout=60)
            task_resp.raise_for_status()
            task_res = task_resp.json()
        except Exception as e:
            raise Exception(f"apimart_task_query_error: {repr(e)}")

        if not isinstance(task_res, dict) or task_res.get("code") != 200:
            raise Exception(f"apimart_task_query_error: unexpected response {str(task_res)[:500]}")

        task_data = task_res.get("data") or {}
        status = task_data.get("status")
        last_status = status
        if status == "completed":
            result = task_data.get("result") or {}
            images = result.get("images") or []
            if not images:
                raise Exception(f"apimart_task_query_error: completed without images {str(task_res)[:500]}")
            first = images[0] or {}
            url_list = first.get("url") or []
            if isinstance(url_list, list) and url_list:
                url = url_list[0]
            else:
                url = None
            if not url:
                raise Exception(f"apimart_task_query_error: missing image url {str(task_res)[:500]}")
            return {"url": url, "request": request_payload}

        if status in {"failed", "cancelled"}:
            raise Exception(f"apimart_task_query_error: status={status} {str(task_res)[:500]}")

        import time as _time
        _time.sleep(poll_interval_seconds)

    raise Exception(f"apimart_task_query_error: timeout last_status={last_status} task_id={task_id}")

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
def steam_api_user_status(api_key, steam_id):
    url = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"
    params = {
        'key': api_key,
        'steamids': steam_id
    }
    
    response = requests.get(url, params=params)
    data = response.json()
    
    players = data.get('response', {}).get('players', [])
    if players:
        player = players[0]
        name = player.get('personaname')
        # 0=离线, 1=在线, 其他为忙碌/离开等
        state = player.get('personastate') 
        game = player.get('gameextrainfo', "未在游戏中")
        
        # print(f"用户: {name}")
        # print(f"状态码: {state} (1为在线)")
        # print(f"正在玩: {game}")
        return player
    else:
        return {}
def steam_api_recent_games(api_key, steam_id):
    """
    获取指定用户最近14天玩过的游戏及总时长
    :param api_key: 你的 Steam Web API Key
    :param steam_id: 目标用户的 64位 SteamID
    """
    url = "https://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v0001/"
    params = {
        'key': api_key,
        'steamid': steam_id,
        'format': 'json'
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()  # 检查 HTTP 状态码
        data = response.json()
        
        # 获取游戏列表
        games = data.get('response', {}).get('games', [])
        
        return games
    
        # game_info = {
        #     'name': game.get('name'),
        #     'appid': game.get('appid'),
        #     'playtime_2weeks': game.get('playtime_2weeks'), # 最近两周时长（分钟）
        #     'playtime_forever': game.get('playtime_forever') # 历史总时长（分钟）
        # }
            

    except Exception as e:
        raise Exception("STEAM Exception: "+str(e))
