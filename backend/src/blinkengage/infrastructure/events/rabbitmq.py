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
from blinkengage.core.correlation import set_correlation_id
from blinkengage.core.logging import get_logger
from blinkengage.infrastructure.events.retry import (
    DEFAULT_MAX_ATTEMPTS,
    RetryTopology,
    attempts_of,
    declare_topology,
    quarantine,
    schedule_retry,
)

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
    channel: AbstractChannel,
    settings: Settings,
    *,
    routing_key: str,
    body: bytes,
    correlation_id: str | None = None,
) -> None:
    exchange = await declare_events_exchange(channel, settings)
    await exchange.publish(
        aio_pika.Message(
            body=body,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            # The AMQP standard property rather than a custom header, so
            # it survives the retry queue's dead-letter round trip and is
            # visible in the RabbitMQ management UI without decoding a
            # payload.
            correlation_id=correlation_id,
        ),
        routing_key=routing_key,
    )


async def _handle_one(
    message: AbstractIncomingMessage,
    *,
    handler: Callable[[AbstractIncomingMessage], Awaitable[None]],
    topology: RetryTopology,
    queue_name: str,
    max_attempts: int,
) -> None:
    """Run one message through the handler, then decide its fate.

    ``requeue=False`` is the important argument. Requeueing was what made
    a failing handler spin: the broker put the message straight back at
    the head of the queue and redelivered it immediately, forever. Here a
    failure is *acked* and the message is deliberately republished — to
    the retry queue with a delay, or to the DLQ when its attempts are
    spent. Either way it is still durable, and either way the consumer
    moves on to the next message instead of stalling behind this one.
    """
    # The publisher's correlation id, adopted for the whole handler so
    # every log line it emits ties back to the request that caused the
    # event. Falls back to a fresh id when the publisher had none.
    correlation_id = set_correlation_id(message.correlation_id)
    attempt = attempts_of(message) + 1
    try:
        async with message.process(requeue=False):
            await handler(message)
    except Exception as error:  # noqa: BLE001 — the point is to catch everything
        if attempt >= max_attempts:
            await quarantine(topology, message, queue_name=queue_name, attempt=attempt, error=error)
        else:
            await schedule_retry(
                topology, message, queue_name=queue_name, attempt=attempt, error=error
            )
        logger.exception(
            "event_handler_failed",
            queue_name=queue_name,
            attempt=attempt,
            max_attempts=max_attempts,
            correlation_id=correlation_id,
        )


async def run_consumer(
    settings: Settings,
    *,
    queue_name: str,
    routing_keys: list[str],
    handler: Callable[[AbstractIncomingMessage], Awaitable[None]],
    prefetch_count: int = 10,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> None:
    """Declare ``queue_name`` (durable) with its retry and dead-letter
    queues, bind ``routing_keys`` on the shared events exchange, and
    consume forever.

    Delivery is still at-least-once, but a failing handler no longer
    blocks the queue: the message is retried with exponential backoff and
    quarantined in ``<queue_name>.dlq`` once its attempts are spent. See
    ``events/retry.py`` for the topology and why it is shaped that way.

    Adding a new consumer means calling this with a new ``queue_name``/
    ``routing_keys``/``handler`` from a new module — nothing here, the
    relay, or any other consumer needs to change.
    """
    connection = await connect(settings)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=prefetch_count)
        exchange = await declare_events_exchange(channel, settings)
        topology = await declare_topology(channel, queue_name=queue_name, events_exchange=exchange)
        for routing_key in routing_keys:
            await topology.main.bind(exchange, routing_key=routing_key)
        # The return path. A message whose retry TTL expires is
        # dead-lettered to the events exchange with the *queue name* as
        # its routing key, so the main queue needs a binding on that key
        # or the redelivery would be silently discarded.
        await topology.main.bind(exchange, routing_key=queue_name)

        logger.info(
            "event_consumer_started",
            queue_name=queue_name,
            routing_keys=routing_keys,
            max_attempts=max_attempts,
        )
        async with topology.main.iterator() as queue_iter:
            async for message in queue_iter:
                await _handle_one(
                    message,
                    handler=handler,
                    topology=topology,
                    queue_name=queue_name,
                    max_attempts=max_attempts,
                )
