"""Web Chat visitor session store, backed by Redis. See
``docs/architecture/web-chat.md``: an opaque, revocable session token
mapped to ``(customer_id, channel_config_id, company_id)`` — the same
"token as a Redis key" pattern ``infrastructure.cache.refresh_tokens``
established for a different trust domain (agent login sessions). Redis
lookup succeeding *is* the verification; there's no signature to decode.
"""

import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import orjson
from redis.asyncio import Redis


def _key(session_token: str) -> str:
    return f"webchat_session:{session_token}"


@dataclass(frozen=True, slots=True)
class ChatSessionData:
    customer_id: UUID
    channel_config_id: UUID
    company_id: UUID


class ChatSessionStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def create(self, *, data: ChatSessionData, ttl: timedelta) -> str:
        token = secrets.token_urlsafe(32)
        await self._redis.set(
            _key(token),
            orjson.dumps(
                {
                    "customer_id": str(data.customer_id),
                    "channel_config_id": str(data.channel_config_id),
                    "company_id": str(data.company_id),
                }
            ),
            ex=int(ttl.total_seconds()),
        )
        return token

    async def get(self, session_token: str) -> ChatSessionData | None:
        raw = await self._redis.get(_key(session_token))
        if raw is None:
            return None
        parsed = orjson.loads(raw)
        return ChatSessionData(
            customer_id=UUID(parsed["customer_id"]),
            channel_config_id=UUID(parsed["channel_config_id"]),
            company_id=UUID(parsed["company_id"]),
        )

    async def touch(self, session_token: str, *, ttl: timedelta) -> None:
        """Slides the TTL forward — called whenever a session is resumed."""
        await self._redis.expire(_key(session_token), int(ttl.total_seconds()))
