import requests
import json

def make_koh_profile_request():
    """
    发送POST请求到 /game/koh/profile 接口
    """
    # 请求URL
    url = "https://kohcamp.qq.com/game/koh/profile"
    
    # 请求头
    headers = {
        'Host': 'kohcamp.qq.com',
        'istrpcrequest': 'true',
        'cchannelid': '10035044',
        'cclientversioncode': '2047937708',
        'cclientversionname': '9.104.0903',
        'ccurrentgameid': '20001',
        'cgameid': '20001',
        'cgzip': '1',
        'cisarm64': 'true',
        'crand': '1758455866028',
        'csupportarm64': 'true',
        'csystem': 'android',
        'csystemversioncode': '32',
        'csystemversionname': '12',
        'cpuhardware': 'HONOR',
        'encodeparam': 'ZNOmzPRNyzelMHHRYvC5Wq7WOqsfZERp9S0ONnm8u%2FS4YAdub8BfmOkgYbdtr8kjCC%2Fp4ks5C90gcB8wbWiEUzH%2FWvRVgY%2FOGo2071jPm5ZKJT45i3ScjurNFcHHB8FCpLORjA%3D%3D',
        'gameareaid': '1',
        'gameid': '20001',
        'gameopenid': 'REDACTED_CREDENTIAL',
        'gameroleid': '2000000107',
        'gameserverid': '1533',
        'gameusersex': '1',
        'openid': 'REDACTED_CREDENTIAL',
        'tinkerid': '2047937708_64_0',
        'token': 'L1MO9TSoDI4M_H88HvFwCZQrVY-25xnRxb2lERfAtu0bkbBF3Q18MII_dwYjWlrrBQBSFym4YLLLrSqx7TbYLLUW-MYd8COHkgFSPg~~',
        'userid': '2000000018',
        'content-encrypt': '',
        'accept-encrypt': '',
        'noencrypt': '1',
        'x-client-proto': 'https',
        'x-log-uid': '7CC1515C-5141-498E-B693-20FC254FAEA3',
        'kohdimgender': '2',
        'content-type': 'application/json; charset=UTF-8',
        'accept-encoding': 'gzip',
        'user-agent': 'okhttp/4.9.1',
        'traceparent': '00-cebf193b7e0d2330024864bd4ea88f8b-661c2bc460c4dae8-01'
    }
    
    # 请求体数据
    payload = {
        "resVersion": 3,
        "recommendPrivacy": 0,
        "apiVersion": 2,
        "targetUserId": "2000000039",
        "targetRoleId": "2000000100",
        "itsMe": False
    }
    
    try:
        # 发送POST请求
        response = requests.post(
            url=url,
            headers=headers,
            json=payload,  # 使用json参数自动序列化并设置Content-Type
            timeout=10  # 设置超时时间
        )
        
        # 检查响应状态
        response.raise_for_status()
        
        # 解析响应数据
        result = response.json()
        
        print("请求成功!")
        print(f"状态码: {response.status_code}")
        print("响应数据:")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        
        return result
        
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"JSON解析失败: {e}")
        print(f"原始响应: {response.text}")
        return None

# 发送请求
if __name__ == "__main__":
    make_koh_profile_request()