"""Redis fixed-window rate limiting.

If Redis is unavailable the limiter fails OPEN (requests proceed) and logs a warning:
availability is preferred over blocking all traffic. Authentication and tenant isolation do
not depend on Redis.
"""

from __future__ import annotations

import time

import structlog
from fastapi import Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from sellerscope.core.errors import AppError

log = structlog.get_logger()


class RateLimiter:
    def __init__(self, redis: Redis, *, enabled: bool = True) -> None:
        self._redis = redis
        self.enabled = enabled

    async def check(self, key: str, limit: int, window_s: int) -> None:
        """Raise 429 if `key` exceeded `limit` hits in the current window."""
        if not self.enabled:
            return
        now = time.time()
        bucket = int(now // window_s)
        redis_key = f"rl:{key}:{bucket}"
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(redis_key)
                pipe.expire(redis_key, window_s + 1)
                count, _ = await pipe.execute()
        except RedisError:
            log.warning("rate_limit_unavailable", key=key)
            return
        if int(count) > limit:
            retry_after = max(1, int(window_s - (now % window_s)))
            raise AppError(
                429,
                "rate_limited",
                "Too many requests",
                f"Limit of {limit} requests per {window_s}s exceeded",
                headers={"Retry-After": str(retry_after)},
            )


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
