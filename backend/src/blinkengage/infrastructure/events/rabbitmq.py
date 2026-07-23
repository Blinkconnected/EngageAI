"""RabbitMQ topic-exchange plumbing shared by the outbox relay (publish
side) and every consumer (subscribe side). See
``docs/architecture/event-bus.md``.

RabbitMQ is already the durable Celery broker (``core/celery_app.py``) —
this reuses it as the event bus transport rather than standing up a
second broker. The relay and consumers talk to it directly via
``aio_pika`` (an already-declared, previously-unused dependency); this is
deliberately *not* modeled as Celery tasks, since Celery's model is
single-consumer task dispatch, not topic-exchange fan-out to many
independently-bound durable queues.
"""

from collections.abc import Awaitable, Callable

import aio_pika
from aio_pika.abc import (
    AbstractChannel,
    AbstractExchange,
    AbstractIncomingMessage,
    AbstractRobustConnection,
)

from blinkengage.core.config import Settings
from blinkengage.core.logging import get_logger

logger = get_logger(__name__)


async def connect(settings: Settings) -> AbstractRobustConnection:
    """A robust connection auto-reconnects across broker restarts/network
    blips — important once this runs continuously as a long-lived consumer
    process, not just a request-scoped call."""
    return await aio_pika.connect_robust(settings.rabbitmq_url)


async def declare_events_exchange(channel: AbstractChannel, settings: Settings) -> AbstractExchange:
    return await channel.declare_exchange(
        settings.events_exchange_name, aio_pika.ExchangeType.TOPIC, durable=True
    )


async def publish_event(
    channel: AbstractChannel, settings: Settings, *, routing_key: str, body: bytes
) -> None:
    exchange = await declare_events_exchange(channel, settings)
    await exchange.publish(
        aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
        routing_key=routing_key,
    )


async def run_consumer(
    settings: Settings,
    *,
    queue_name: str,
    routing_keys: list[str],
    handler: Callable[[AbstractIncomingMessage], Awaitable[None]],
    prefetch_count: int = 10,
) -> None:
    """Declare ``queue_name`` (durable), bind ``routing_keys`` on the shared
    events exchange, and consume forever. ``handler`` is only acked on
    success (via ``message.process()``) — an exception leaves the message
    for redelivery, giving at-least-once processing.

    Adding a new consumer means calling this with a new ``queue_name``/
    ``routing_keys``/``handler`` from a new module — nothing here, the
    relay, or any other consumer needs to change.
    """
    connection = await connect(settings)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=prefetch_count)
        exchange = await declare_events_exchange(channel, settings)
        queue = await channel.declare_queue(queue_name, durable=True)
        for routing_key in routing_keys:
            await queue.bind(exchange, routing_key=routing_key)

        logger.info("event_consumer_started", queue_name=queue_name, routing_keys=routing_keys)
        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process(requeue=True):
                    await handler(message)
