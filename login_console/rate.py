"""Shared atomic DB0 limits; importing performs no IO."""
RESERVE = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local blocked = tonumber(redis.call('GET', KEYS[1]) or '0')
if blocked > now then return {0, blocked-now, 1} end
local next = tonumber(redis.call('GET', KEYS[2]) or '0')
if next > now then return {0, next-now, 2} end
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', now-3600000)
local minute = redis.call('ZCOUNT', KEYS[3], now-60000, '+inf')
local hour = redis.call('ZCARD', KEYS[3])
if hour >= tonumber(ARGV[3]) then
  local first = redis.call('ZRANGE', KEYS[3], 0, 0, 'WITHSCORES')
  return {0, tonumber(first[2])+3600000-now+1, 3}
end
if minute >= tonumber(ARGV[2]) then
  local first = redis.call('ZRANGEBYSCORE', KEYS[3], now-60000, '+inf', 'WITHSCORES', 'LIMIT', 0, 1)
  return {0, tonumber(first[2])+60000-now+1, 3}
end
redis.call('ZADD', KEYS[3], now, ARGV[4])
redis.call('PEXPIRE', KEYS[3], 3601000)
redis.call('SET', KEYS[2], now+tonumber(ARGV[1]), 'PX', math.ceil(tonumber(ARGV[1])+1000))
return {1, 0, 0}
"""
COOLDOWN = """
local clock = redis.call('TIME')
local until_time = tonumber(clock[1])*1000 + math.floor(tonumber(clock[2])/1000) + tonumber(ARGV[1])
local old = tonumber(redis.call('GET', KEYS[1]) or '0')
if until_time > old then redis.call('SET', KEYS[1], until_time, 'PX', ARGV[1]) end
return 1
"""


AUTH_PREFIX = "hok:auth:"
PLAYER_RATE_PREFIX = "hok:player_client:rate"
