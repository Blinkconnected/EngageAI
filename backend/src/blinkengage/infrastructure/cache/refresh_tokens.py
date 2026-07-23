"""Refresh token allowlist, backed by Redis.

JWTs are stateless by design, but refresh tokens need to be individually
revocable (logout, logout-everywhere, compromised-token response) — so
each issued refresh token's ``jti`` is recorded here with a TTL matching
its expiry, and revocation is just deleting the key. A refresh token whose
``jti`` isn't present is treated as invalid even if its signature and
expiry are otherwise fine.
"""

from datetime import timedelta
from uuid import UUID

from redis.asyncio import Redis


def _key(user_id: UUID, jti: str) -> str:
    return f"refresh_token:{user_id}:{jti}"


class RefreshTokenStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def store(self, *, user_id: UUID, jti: str, ttl: timedelta) -> None:
        await self._redis.set(_key(user_id, jti), "1", ex=int(ttl.total_seconds()))

    async def is_valid(self, *, user_id: UUID, jti: str) -> bool:
        return bool(await self._redis.exists(_key(user_id, jti)))

    async def revoke(self, *, user_id: UUID, jti: str) -> None:
        await self._redis.delete(_key(user_id, jti))

    async def revoke_all_for_user(self, *, user_id: UUID) -> None:
        pattern = _key(user_id, "*")
        async for key in self._redis.scan_iter(match=pattern):
            await self._redis.delete(key)
