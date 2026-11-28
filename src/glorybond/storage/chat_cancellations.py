"""Remember withdrawn chat inputs across the outbound queue and process restarts."""
import hashlib
import json
import re

TTL_SECONDS = 86400


def normalize_key(value):
    if not isinstance(value, (tuple, list)) or len(value) != 5:
        return None
    bot, channel, recipient, user, message = map(str, value)
    if channel not in {"group", "private"}:
        return None
    if not all(re.fullmatch(r"[1-9][0-9]{0,19}", item) for item in (bot, recipient, user)):
        return None
    if not re.fullmatch(r"-?[0-9]{1,20}", message) or int(message) == 0:
        return None
    if channel == "private" and recipient != user:
        return None
    return bot, channel, recipient, user, str(int(message))


def _redis_key(key):
    normalized = normalize_key(key)
    if normalized is None:
        raise ValueError("Invalid trusted chat identity")
    digest = hashlib.sha256(json.dumps(normalized, separators=(",", ":")).encode()).hexdigest()
    return "hok:chat_recalled:" + digest


def record_recall(key, *, store=None):
    if store is None:
        from glorybond import runtime
        store = runtime.redis_deamon
    return store.set(_redis_key(key), "1", ex=TTL_SECONDS, nx=True)


def was_recalled(key, *, store=None):
    if store is None:
        from glorybond import runtime
        store = runtime.redis_deamon
    return bool(store.exists(_redis_key(key)))
