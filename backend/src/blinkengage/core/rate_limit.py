"""Redis-backed fixed-window rate limiting.

Used to protect brute-forceable endpoints (login, register) independently
of any per-user auth state, since the whole point is to throttle
unauthenticated/pre-auth requests.
"""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any, cast

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Rate limit exceeded; retry after {retry_after_seconds}s")


class FixedWindowRateLimiter:
    """A simple INCR+EXPIRE fixed-window limiter.

    Not a sliding-window/token-bucket limiter — deliberately simple for a
    first pass. Fine for its purpose (blunt brute-force protection on a
    handful of endpoints); revisit if precise burst control is needed.
    """

    def __init__(self, redis: Redis, *, scope: str, limit: int, window_seconds: int = 60) -> None:
        self._redis = redis
        self._scope = scope
        self._limit = limit
        self._window_seconds = window_seconds

    async def check(self, identifier: str) -> None:
        key = f"ratelimit:{self._scope}:{identifier}"
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, self._window_seconds)
        if count > self._limit:
            ttl = await self._redis.ttl(key)
            raise RateLimitExceeded(retry_after_seconds=max(ttl, 1))


def client_identifier(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def enforce_rate_limit(limiter: FixedWindowRateLimiter, identifier: str) -> None:
    try:
        await limiter.check(identifier)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc


def _get_redis_from_request(request: Request) -> Redis:
    # Deliberately duplicated from api/deps.get_redis rather than imported:
    # core/ must not depend on api/ (dependency-direction rule), and this is
    # two lines.
    return cast(Redis, request.app.state.container.redis())


def rate_limit_dependency(
    *, scope: str, limit: int, window_seconds: int = 60
) -> Callable[..., Coroutine[Any, Any, None]]:
    """Build a FastAPI dependency enforcing a per-client rate limit on one route.

    ``limit``/``window_seconds`` are passed explicitly by the caller (rather
    than read from ``Settings`` here) so different endpoints can have
    different thresholds — e.g. login can be stricter than a generic
    authenticated endpoint.
    """

    async def _dependency(
        request: Request,
        redis: Annotated[Redis, Depends(_get_redis_from_request)],
    ) -> None:
        limiter = FixedWindowRateLimiter(
            redis, scope=scope, limit=limit, window_seconds=window_seconds
        )
        await enforce_rate_limit(limiter, client_identifier(request))

    return _dependency
