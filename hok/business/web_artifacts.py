"""Pure identifiers, routes, and payloads for public web artifacts."""

import hashlib
import secrets


ROUTES = {
    "all": "all",
    "single_oneday": "person",
    "single_period": "period",
    "btldetail": "battle",
    "query_select": "query",
    "benefit": "benefit",
    "bili_video": "bili-video",
}


def make_hash(seed=None):
    source = str(seed) if seed is not None else secrets.token_hex(16)
    return hashlib.sha256(source.encode()).hexdigest()[:16]


def route_url(sitetype, hash_key, server_domain):
    route = ROUTES.get(sitetype)
    if not route:
        return ""
    return f"https://hok.{server_domain}/{route}?key={hash_key}"


def history_route_payload(filename_hashed, caller="", time_text="", extra=None):
    payload = {
        "filename": filename_hashed,
        "caller": caller,
        "time": time_text,
    }
    if extra:
        payload.update(extra)
    return payload
