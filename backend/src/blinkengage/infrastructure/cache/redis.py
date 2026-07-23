"""Async Redis client factory.

A single client instance is created per application process (see
``core.container.Container``) and shared across rate limiting, refresh
token revocation, and (in later milestones) caching/pub-sub.
"""

from typing import cast

from redis.asyncio import Redis

from blinkengage.core.config import Settings


def create_redis_client(settings: Settings) -> Redis:
    return cast(Redis, Redis.from_url(settings.redis_url, decode_responses=True))
