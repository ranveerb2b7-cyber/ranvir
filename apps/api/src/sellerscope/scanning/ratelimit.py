"""Distributed token bucket in Redis: all workers share one budget per connector key."""

from __future__ import annotations

from redis.asyncio import Redis

# KEYS[1]=bucket; ARGV: rate (tokens/s), burst, now (ms). Returns ms to wait (0 = granted).
_LUA = """
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local tokens = tonumber(redis.call('HGET', KEYS[1], 't'))
local ts = tonumber(redis.call('HGET', KEYS[1], 'ts'))
if tokens == nil then tokens = burst; ts = now end
if now > ts then tokens = math.min(burst, tokens + (now - ts) * rate / 1000) end
local wait = 0
if tokens >= 1 then
  tokens = tokens - 1
else
  wait = math.ceil((1 - tokens) * 1000 / rate)
end
redis.call('HSET', KEYS[1], 't', tostring(tokens), 'ts', tostring(math.max(now, ts)))
redis.call('PEXPIRE', KEYS[1], math.ceil(burst * 1000 / rate) + 60000)
return wait
"""


class TokenBucket:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._script = redis.register_script(_LUA)

    async def acquire(self, key: str, *, rate: float, burst: int, now_s: float) -> float:
        """Takes one token if available. Returns seconds to wait first (0.0 = go now)."""
        wait_ms = await self._script(keys=[f"tb:{key}"], args=[rate, burst, int(now_s * 1000)])
        return int(wait_ms) / 1000.0
