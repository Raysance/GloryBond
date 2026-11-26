"""Fetch QQ avatar pixels through a configured QQ endpoint, without ambient proxies."""

import requests


def qq_avatar_bytes(user_id, *, config):
    user = str(user_id)
    if not user.isascii() or not user.isdecimal() or int(user) <= 0:
        raise ValueError("头像读取需要有效 QQ")
    with requests.Session() as session:
        session.trust_env = False
        with session.get(
            config["avatar_endpoint"], params={"b": "qq", "nk": user, "s": config["avatar_size"]},
            timeout=config["timeout_seconds"], stream=True, allow_redirects=False,
        ) as response:
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError("QQ 头像端点没有返回图片")
            raw = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                raw.extend(chunk)
                if len(raw) > config["max_avatar_bytes"]:
                    raise ValueError("QQ 头像超过大小限制")
            return bytes(raw)
