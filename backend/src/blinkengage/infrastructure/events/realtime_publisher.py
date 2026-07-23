"""Ephemeral realtime signal publisher — Redis pub/sub, no durability.

See ``docs/architecture/event-bus.md`` for why this is a separate,
simpler mechanism from the durable domain event bus
(``domain.events``/``OutboxEventPublisher``): typing indicators, presence,
and live delivery ticks don't need at-least-once delivery, and paying for
that guarantee would only add latency to something inherently
latency-sensitive. First subscriber: the Web Chat WebSocket gateway (see
``docs/architecture/web-chat.md``), which subscribes per-session and
forwards published frames straight to the socket — the mechanism that
lets a reply published from any app server reach the one process actually
holding the visitor's connection, with zero new distributed state.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import orjson
from redis.asyncio import Redis
from redis.asyncio.client import PubSub


class RealtimePublisher:
    """Structurally satisfies ``domain.events.RealtimeSignalPublisher``."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        await self._redis.publish(channel, orjson.dumps(payload))

    @asynccontextmanager
    async def subscribe(self, channel: str) -> AsyncIterator[PubSub]:
        """Yields a subscribed ``PubSub`` handle; iterate it with
        ``async for message in pubsub.listen()``. Always unsubscribes and
        closes on exit, including on cancellation (a WebSocket disconnect)."""
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            yield pubsub
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()  # type: ignore[no-untyped-call]
