"""Ephemeral realtime signal publisher — Redis pub/sub, no durability.

See ``docs/architecture/event-bus.md`` for why this is a separate,
simpler mechanism from the durable domain event bus
(``domain.events``/``OutboxEventPublisher``): typing indicators, presence,
and live delivery ticks don't need at-least-once delivery, and paying for
that guarantee would only add latency to something inherently
latency-sensitive. Nothing subscribes yet — that starts with the Web Chat
channel/WebSocket gateway and the Notifications module.
"""

from typing import Any

import orjson
from redis.asyncio import Redis


class RealtimePublisher:
    """Structurally satisfies ``domain.events.RealtimeSignalPublisher``."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        await self._redis.publish(channel, orjson.dumps(payload))
