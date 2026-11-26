"""Per-conversation lineup enqueue deduplication, separate from QQ receipts."""
import hashlib
import json
import re

RETENTION_SECONDS = 86400
_PREFIX = "hok:watch:lineup:"
_ENQUEUE = """
if redis.call('exists', KEYS[1]) == 1 then return 0 end
redis.call('lpush', KEYS[2], ARGV[1])
redis.call('set', KEYS[1], ARGV[2], 'EX', ARGV[3])
return 1
"""
_FINISH = """
if redis.call('get', KEYS[1]) ~= ARGV[1] then return 0 end
if ARGV[2] == 'failed' then return redis.call('del', KEYS[1]) end
return redis.call('set', KEYS[1], ARGV[2], 'KEEPTTL')
"""


def lineup_key(*, bot_id, channel, recipient, battle_id):
    if channel not in {"group", "private"} or not str(battle_id).strip():
        raise ValueError("Invalid lineup scope")
    scope = [str(bot_id), channel, str(recipient), str(battle_id)]
    return _PREFIX + hashlib.sha256(json.dumps(scope).encode()).hexdigest()


def _validate(key):
    if not re.fullmatch(re.escape(_PREFIX) + r"[a-f0-9]{64}", key):
        raise ValueError("Invalid lineup key")


def already_queued(key):
    from glorybond import runtime
    _validate(key)
    return bool(runtime.redis_deamon.exists(key))


def enqueue_once(key, payload):
    from glorybond import runtime
    from glorybond.config.settings import REDIS_KEY_MESSAGE_OUTBOUND_QUEUE
    _validate(key)
    return bool(runtime.redis_deamon.eval(_ENQUEUE, 2, key, REDIS_KEY_MESSAGE_OUTBOUND_QUEUE,
        json.dumps(payload, ensure_ascii=False), "queued:" + payload["delivery_id_internal"], RETENTION_SECONDS))


def record_outcome(payload, status):
    from glorybond import runtime
    key = payload.get("watch_lineup_key")
    if not key:
        return
    _validate(key)
    if status not in {"sent", "failed", "unknown"}:
        raise ValueError("Invalid lineup receipt status")
    token = payload["delivery_id_internal"]
    runtime.redis_deamon.eval(_FINISH, 1, key, "queued:" + token,
                             "failed" if status == "failed" else status + ":" + token)
