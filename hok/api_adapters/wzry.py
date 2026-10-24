"""Honor of Kings official API adapter."""

import json
import logging

import requests
from ratelimit import limits, sleep_and_retry

from ..zfile import append_hok_exception_log, refresh_login_credentials
from ..zstatic import confs
from ..ztime import sleep_seconds
from ..zutil import log_message

def _redact_hok_log_value(value):
    if isinstance(value, dict):
        sensitive_keys = {"token", "openid", "gameopenid"}
        return {
            key: "***" if str(key).lower() in sensitive_keys else _redact_hok_log_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_hok_log_value(item) for item in value]
    return value


def _compact_hok_log_text(value, max_len=500):
    text = "" if value is None else str(value)
    text = text.replace("\n", " ").replace("\r", " ")
    if len(text) > max_len:
        text = text[:max_len - 3] + "..."
    return text


class WzryOfficialAPI:
    LOW_PRIORITY_PERIOD_SECONDS = 5

    @staticmethod
    @sleep_and_retry
    @limits(calls=1, period=1)
    def _get_official_impl(reqtype,userid=-1,roleid=0,gameseq=-1,gameSvrId=-1,relaySvrId=-1,pvptype=-1,heroid=-1,rankId=-1,rankSegment=-1,battle_id=-1,honor_adcode=156):
        from ..tools.endecoder import decrypt_game_data
        from ..tools.endecoder import get_full_request_params

        refresh_login_credentials()
        wzry = dict(confs["wzry"])
        encoded_params = get_full_request_params(wzry["pubkey"],wzry["userid"],wzry["encoderes"])
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
        honor_ranklist_url="https://kohcamp.qq.com/game/honor/ranklist"
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
            "gameopenid": wzry["gameopenid"],
            "gameroleid": wzry["gameroleid"],
            "gameserverid": "1545",
            "gameusersex": "1",
            "openid": wzry["openid"],
            "tinkerid": wzry["tinkerid"],
            "token": wzry["token"],
            "userid": wzry["userid"],
            "content-encrypt": "",
            "accept-encrypt": "",
            "noencrypt": "1",
            "x-client-proto": "https",
            "x-log-uid": wzry["x-log-uid"],
            "kohdimgender": "2",
            "content-type": "application/json; charset=UTF-8",
            "user-agent": "okhttp/4.9.1",
            "traceparent": encoded_params["traceparent"]
        }

        headers.update(wzry.get("client_headers", {}))

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
            'gameOpenId': wzry["gameopenid"],
            'gameRoleId': wzry["roleid"],
            'gameServerId': 1545,
            'gameUserSex': 1,
            'openId': wzry["openid"],
            'tinkerId': wzry["tinkerid"],
            'token': wzry["token"],
            'userId': wzry["userid"]
        }
        for field in allhero_data:
            if field.lower() in headers:
                allhero_data[field] = headers[field.lower()]
        herostatistics_data={
            "recommendPrivacy": 0,
            "toOpenid": wzry["openid"],
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
        honor_ranklist_data = {
            "recommendPrivacy": 0,
            "areaId": 1,
            "adcode": int(honor_adcode),
            "roleId": roleid,
            "heroId": int(heroid),
        }
        watchbattle_data = {
            "recommendPrivacy": 0,
            "battleID": battle_id,
            "roleID": roleid,
            "type": 1,
            "userID": userid
        }
        # watchbattle_data = {'recommendPrivacy': 0, 'battleID': '177399_1742766640_1774529852', 'roleID': '2000000010', 'type': 1, 'userID': '2000000061'}

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
            case "honorranklist":
                url=honor_ranklist_url
                data=honor_ranklist_data
            case "watchbattle":
                url=watchbattle_url
                data=watchbattle_data
            case _:
                raise ValueError(f"unsupported wzry reqtype: {reqtype}")
        retry_time=3
        error_msg=""
        last_status_code=None
        last_response_text=""
        last_decoded_response={}
        while(retry_time):
            try:
                encoded_response = requests.post(url, headers=headers, json=data, timeout=30)
                last_status_code = encoded_response.status_code
                last_response_text = _compact_hok_log_text(encoded_response.text)
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

                    decoded_response=decrypt_game_data(wzry["pubkey"],wzry["encoderes"],encoded_response.text)
                except Exception as e:
                    error_msg="Decode error: "+str(e)
                    retry_time=0
                    break
            last_decoded_response = decoded_response
            res=decoded_response.get("data",{})
            error_msg=decoded_response.get("returnMsg","") or decoded_response.get("msg","") or decoded_response.get("message","")
            if not error_msg and not res:
                fallback_response = last_response_text or _compact_hok_log_text(decoded_response)
                error_msg = f"empty_data status={last_status_code} response={fallback_response}"
            # print(res,error_msg)
            if res: break
            if ("登录态失效" in error_msg or "频繁" in error_msg or "繁忙" in error_msg or "不允许被观战" in error_msg or "本场对局已结束" in error_msg):
                retry_time=0
                break
            sleep_seconds(2)
            retry_time-=1
        if (not retry_time):
            hok_error = "HOK Exception: " + error_msg
            try:
                append_hok_exception_log(
                    hok_error,
                    {
                        "reqtype": reqtype,
                        "userid": userid,
                        "roleid": roleid,
                        "gameseq": gameseq,
                        "gameSvrId": gameSvrId,
                        "relaySvrId": relaySvrId,
                        "pvptype": pvptype,
                        "heroid": heroid,
                        "rankId": rankId,
                        "rankSegment": rankSegment,
                        "battle_id": battle_id,
                        "honor_adcode": honor_adcode,
                        "url": url,
                        "request_data": _redact_hok_log_value(data),
                        "returnMsg": error_msg,
                        "status_code": last_status_code,
                        "response_text": last_response_text,
                        "decoded_response": _redact_hok_log_value(last_decoded_response),
                    },
                )
            except Exception as log_error:
                log_message(f"HOK_EXCEPTION_LOG_WRITE_ERROR: {repr(log_error)}", logging.ERROR)
            raise Exception(str(hok_error))
        # import os
        # import jso
        # save_path = os.path.join("resources","wzry_data_format", f"{reqtype}.json")
        # with open(save_path, 'w', encoding='utf-8') as sf:
        #     json.dump(res, sf, ensure_ascii=False, indent=2)
        return res


def wzry_get_official(reqtype,userid=-1,roleid=0,gameseq=-1,gameSvrId=-1,relaySvrId=-1,pvptype=-1,heroid=-1,rankId=-1,rankSegment=-1,battle_id=-1,priority="normal",honor_adcode=156):
    return WzryOfficialAPI._get_official_impl(reqtype, userid, roleid, gameseq, gameSvrId, relaySvrId, pvptype, heroid, rankId, rankSegment, battle_id, honor_adcode)
