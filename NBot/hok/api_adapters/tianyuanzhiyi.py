"""Tianyuanzhiyi tier and matchup API adapters."""

import json
import secrets
from base64 import urlsafe_b64encode
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from ..ztime import epoch_ms
from ..zutil import log_message

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


def tianyuanzhiyi_hero_avatars_api(tier_items, max_workers=12):
    headers = {"user-agent": "HOK_QQBot/1.0"}

    def fetch_avatar(item):
        hero_id = str(item.get("heroId"))
        avatar_url = item.get("avatarUrl")
        if not avatar_url:
            return hero_id, None
        response = requests.get(avatar_url, headers=headers, timeout=15)
        response.raise_for_status()
        return hero_id, response.content

    avatars = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(fetch_avatar, item) for item in tier_items]
        for future in as_completed(futures):
            try:
                hero_id, content = future.result()
                if content:
                    avatars[hero_id] = content
            except Exception as error:
                log_message(f"TIANYUAN_HERO_AVATAR_ERROR: {repr(error)}")
    return avatars


def _tianyuanzhiyi_canonical_json(value):
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return json.dumps(value, separators=(",", ":"))
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(_tianyuanzhiyi_canonical_json(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(
            json.dumps(str(key), ensure_ascii=False) + ":" + _tianyuanzhiyi_canonical_json(value[key])
            for key in sorted(value, key=str)
        ) + "}"
    raise TypeError(f"unsupported canonical json value: {type(value).__name__}")


def _tianyuanzhiyi_server_action_result(response):
    response.raise_for_status()
    text = response.content.decode("utf-8", errors="replace")
    for line in text.splitlines():
        if not line.startswith("1:"):
            continue
        result = json.loads(line[2:])
        if isinstance(result, dict) and result.get("error"):
            raise Exception(f"tianyuanzhiyi_action_error: {result['error']}")
        return result
    raise Exception(f"tianyuanzhiyi_action_error: missing result {text[:300]}")


def tianyuanzhiyi_matchup_api(camp1_heroes, camp2_heroes, days=30):
    """Query the site's signed hero-combination Server Action."""
    def b64url(raw):
        return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    def fixed_int(value):
        return int(value).to_bytes(32, "big")

    private_key = ec.generate_private_key(ec.SECP256R1())
    public_numbers = private_key.public_key().public_numbers()
    public_jwk = {
        "kty": "EC",
        "crv": "P-256",
        "x": b64url(fixed_int(public_numbers.x)),
        "y": b64url(fixed_int(public_numbers.y)),
        "ext": True,
        "key_ops": ["verify"],
    }
    headers = {
        "accept": "text/x-component",
        "content-type": "text/plain;charset=UTF-8",
        "origin": "https://tianyuanzhiyi.com",
        "referer": "https://tianyuanzhiyi.com/battle",
        "user-agent": "HOK_QQBot/1.0",
    }
    session = requests.Session()
    register_response = session.post(
        "https://tianyuanzhiyi.com/battle",
        headers={**headers, "next-action": "402685878d6e9288e8aa03df6c50bbca789370014f"},
        data=json.dumps([public_jwk], ensure_ascii=False, separators=(",", ":")),
        timeout=15,
    )
    _tianyuanzhiyi_server_action_result(register_response)

    payload = {
        "camp1Heroes": {str(key): int(value) for key, value in camp1_heroes.items()},
        "camp2Heroes": {str(key): int(value) for key, value in camp2_heroes.items()},
        "camp1ExcludeHeroes": {},
        "camp2ExcludeHeroes": {},
        "days": int(days),
    }
    action = "match_find"
    timestamp = epoch_ms()
    nonce = secrets.token_hex(16)
    sign_text = "\n".join((
        "battle-sign-v1",
        action,
        str(timestamp),
        nonce,
        _tianyuanzhiyi_canonical_json(payload),
    ))
    der_signature = private_key.sign(sign_text.encode("utf-8"), ec.ECDSA(hashes.SHA256()))
    signature_r, signature_s = decode_dss_signature(der_signature)
    signature = b64url(fixed_int(signature_r) + fixed_int(signature_s))
    signature_meta = {"ts": timestamp, "nonce": nonce, "sig": signature}
    action_args = [
        payload["camp1Heroes"],
        payload["camp2Heroes"],
        payload["camp1ExcludeHeroes"],
        payload["camp2ExcludeHeroes"],
        payload["days"],
        signature_meta,
    ]
    response = session.post(
        "https://tianyuanzhiyi.com/battle",
        headers={**headers, "next-action": "7eb8d79dc4ff20fe5ad2eba7c3a003c98f4a415a19"},
        data=json.dumps(action_args, ensure_ascii=False, separators=(",", ":")),
        timeout=30,
    )
    result = _tianyuanzhiyi_server_action_result(response)
    if not isinstance(result, dict):
        raise Exception(f"tianyuanzhiyi_matchup_error: invalid result {result!r}")
    return result
