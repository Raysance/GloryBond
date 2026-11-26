"""Short-lived reply prompts and durable, at-most-once battle report jobs."""
import hashlib
import json
import uuid

PROMPT_SECONDS = 120
WAIT_SECONDS = 7200
RETENTION_SECONDS = 86400
CHECK_SECONDS = 60
_PREFIX = "hok:watch:report:"


def _hash(parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def _db():
    from glorybond import runtime
    return runtime.redis_deamon


def prompt_key(scope):
    return _PREFIX + "prompt:" + _hash(scope)


def job_key(scope, reference, role_id):
    return _PREFIX + "job:" + _hash([*scope[:3], str(role_id), reference["params"]])


def _index(bot):
    return _PREFIX + "due:" + str(bot)


def pending(scope):
    raw = _db().get(prompt_key(scope))
    return json.loads(raw) if raw else None


def dismiss(scope):
    _db().delete(prompt_key(scope))


def offer(scope, target, reference, payload, *, now):
    key = job_key(scope, reference, target["roleid"])
    record = {"scope": scope, "target": target, "reference": reference, "key": key,
              "token": uuid.uuid4().hex, "offered_at": now}
    from glorybond.config.settings import REDIS_KEY_MESSAGE_OUTBOUND_QUEUE
    return bool(_db().eval("""
        if redis.call('exists', KEYS[2]) == 1 then redis.call('del', KEYS[1]); return 0 end
        local pending = redis.call('get', KEYS[1])
        if pending and cjson.decode(pending).key == KEYS[2] then return 0 end
        redis.call('del', KEYS[1])
        redis.call('lpush', KEYS[3], ARGV[1])
        redis.call('set', KEYS[1], ARGV[2], 'EX', ARGV[3])
        return 1
        """, 3, prompt_key(scope), key, REDIS_KEY_MESSAGE_OUTBOUND_QUEUE,
        json.dumps(payload, ensure_ascii=False), json.dumps(record, ensure_ascii=False), PROMPT_SECONDS))


def answer(scope, record, accepted, *, now):
    job = {**record, "state": "pending", "deadline": now + WAIT_SECONDS}
    return _db().eval("""
        local raw = redis.call('get', KEYS[1])
        if not raw or cjson.decode(raw).token ~= ARGV[1] then return 0 end
        if ARGV[2] == 'yes' and redis.call('exists', KEYS[2]) == 0 and redis.call('zcard', KEYS[3]) >= 20 then return -1 end
        redis.call('del', KEYS[1])
        if ARGV[2] == 'yes' and redis.call('exists', KEYS[2]) == 0 then
            redis.call('set', KEYS[2], ARGV[3], 'EX', ARGV[4])
            redis.call('zadd', KEYS[3], ARGV[5], KEYS[2])
        end
        return 1
        """, 3, prompt_key(scope), record["key"], _index(scope[0]),
        record["token"], "yes" if accepted else "no", json.dumps(job, ensure_ascii=False),
        RETENTION_SECONDS, now)


def claim_due(bot, *, now):
    db = _db()
    jobs = []
    for key in db.zrangebyscore(_index(bot), "-inf", now, start=0, num=5):
        key = key.decode() if isinstance(key, bytes) else key
        token = uuid.uuid4().hex
        raw = db.eval("""
            local raw = redis.call('get', KEYS[1])
            if not raw then redis.call('zrem', KEYS[3], KEYS[1]); return nil end
            if not redis.call('set', KEYS[2], ARGV[1], 'NX', 'EX', 900) then return nil end
            redis.call('zadd', KEYS[3], ARGV[2], KEYS[1])
            return raw
            """, 3, key, key + ":lock", _index(bot), token, now + CHECK_SECONDS)
        if raw:
            job = json.loads(raw)
            job["lock_token"] = token
            jobs.append(job)
    return jobs


def release(job):
    _db().eval("""
        if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end
        return 0
        """, 1, job["key"] + ":lock", job["lock_token"])


def finish(job, *, payload=None, state="failed"):
    """Transition and queue together, refusing a worker whose lease expired."""
    from glorybond.config.settings import REDIS_KEY_MESSAGE_OUTBOUND_QUEUE
    saved = {key: value for key, value in job.items() if key != "lock_token"}
    saved["state"] = "queued" if payload else state
    if payload:
        saved["delivery_id"] = payload["delivery_id_internal"]
    return bool(_db().eval("""
        if redis.call('get', KEYS[2]) ~= ARGV[1] then return 0 end
        local raw = redis.call('get', KEYS[1])
        if not raw or cjson.decode(raw).state ~= 'pending' then return 0 end
        if ARGV[3] ~= '' then redis.call('lpush', KEYS[4], ARGV[3]) end
        redis.call('set', KEYS[1], ARGV[2], 'EX', ARGV[4])
        redis.call('zrem', KEYS[3], KEYS[1])
        redis.call('del', KEYS[2])
        return 1
        """, 4, job["key"], job["key"] + ":lock", _index(job["scope"][0]),
        REDIS_KEY_MESSAGE_OUTBOUND_QUEUE, job["lock_token"], json.dumps(saved, ensure_ascii=False),
        json.dumps(payload, ensure_ascii=False) if payload else "", RETENTION_SECONDS))


def record_outcome(payload, status):
    key = payload.get("watch_report_key")
    if not key or not key.startswith(_PREFIX + "job:") or status not in {"sent", "failed", "unknown"}:
        return
    _db().eval("""
        local raw = redis.call('get', KEYS[1])
        if not raw then return 0 end
        local value = cjson.decode(raw)
        if value.state ~= 'queued' or value.delivery_id ~= ARGV[1] then return 0 end
        value.state = ARGV[2]
        return redis.call('set', KEYS[1], cjson.encode(value), 'KEEPTTL')
        """, 1, key, payload["delivery_id_internal"], status)
