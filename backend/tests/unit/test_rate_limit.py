import pytest
from fakeredis import FakeAsyncRedis

from blinkengage.core.rate_limit import FixedWindowRateLimiter, RateLimitExceeded


@pytest.fixture
async def redis():
    client = FakeAsyncRedis(decode_responses=True)
    yield client
    await client.aclose()


async def test_allows_requests_within_limit(redis) -> None:
    limiter = FixedWindowRateLimiter(redis, scope="test", limit=3, window_seconds=60)
    for _ in range(3):
        await limiter.check("client-a")  # should not raise


async def test_rejects_requests_over_limit(redis) -> None:
    limiter = FixedWindowRateLimiter(redis, scope="test", limit=2, window_seconds=60)
    await limiter.check("client-a")
    await limiter.check("client-a")

    with pytest.raises(RateLimitExceeded):
        await limiter.check("client-a")


async def test_limits_are_isolated_per_identifier(redis) -> None:
    limiter = FixedWindowRateLimiter(redis, scope="test", limit=1, window_seconds=60)
    await limiter.check("client-a")
    await limiter.check("client-b")  # different identifier, independent counter


async def test_limits_are_isolated_per_scope(redis) -> None:
    login_limiter = FixedWindowRateLimiter(redis, scope="login", limit=1, window_seconds=60)
    register_limiter = FixedWindowRateLimiter(redis, scope="register", limit=1, window_seconds=60)
    await login_limiter.check("client-a")
    await register_limiter.check("client-a")  # different scope, independent counter
