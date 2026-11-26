"""Atomic, persistent consecutive-failure state for recurring notifications."""

_RECORD_OUTCOME = """
if ARGV[1] == 'success' then
    redis.call('DEL', KEYS[1])
    return {0, 0}
end
local count = redis.call('HINCRBY', KEYS[1], 'failures', 1)
if count >= tonumber(ARGV[2]) and redis.call('HSETNX', KEYS[1], 'notified', 1) == 1 then
    return {count, 1}
end
return {count, 0}
"""


def record_interval_outcome(scope, *, failed, threshold):
    from glorybond import runtime

    count, notify = runtime.redis_deamon.eval(
        _RECORD_OUTCOME, 1, "hok:interval_failures:" + scope,
        "failure" if failed else "success", threshold,
    )
    return int(count), bool(notify)
