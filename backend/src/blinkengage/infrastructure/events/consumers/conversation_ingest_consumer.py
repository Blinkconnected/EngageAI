"""Consumes ``message.received`` events and turns them into
``Conversation``/``Message`` rows — the "conversation engine" M11/M12
promised would exist. See ``docs/architecture/conversations.md``.

Never imports a ``ChannelProvider`` — inbound normalization already
happened in the webhook route/WebSocket gateway before the event was
published. This module only persists.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import orjson
from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.core.config import get_settings
from blinkengage.core.logging import get_logger
from blinkengage.infrastructure.database.models.conversation import Conversation, ConversationStatus
from blinkengage.infrastructure.database.models.customer import Customer
from blinkengage.infrastructure.database.models.message import (
    Message,
    MessageDirection,
    MessageType,
)
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.rabbitmq import run_consumer
from blinkengage.infrastructure.repositories.conversation_repository import (
    ConversationRepository,
)
from blinkengage.infrastructure.repositories.message_repository import MessageRepository

logger = get_logger(__name__)

QUEUE_NAME = "conversation-ingest"
ROUTING_KEYS = ["message.received"]

_REOPEN_ON_NEW_MESSAGE = frozenset({ConversationStatus.RESOLVED, ConversationStatus.CLOSED})


async def _resolve_customer_id(
    *, channel_type: str, external_customer_id: str, company_id: UUID, session: AsyncSession
) -> UUID | None:
    """Per-channel customer identity resolution.

    Only ``web_chat`` exists today, and its ``external_customer_id`` *is*
    our own ``Customer.id`` — the visitor session already resolved
    identity before the first message arrived (see ``web-chat.md``). Every
    future provider-pushed channel needs real matching/merge logic against
    existing customers by phone number, platform user id, etc. — that's
    the "multi-channel identity resolution" M8 explicitly deferred until a
    channel existed to need it, and it's still deferred: this function
    gets a new branch per channel type as each is actually built, not a
    speculative generic resolver now.
    """
    if channel_type == "web_chat":
        try:
            customer_id = UUID(external_customer_id)
        except ValueError:
            return None
        result = await session.execute(
            select(Customer.id).where(Customer.id == customer_id, Customer.company_id == company_id)
        )
        return result.scalar_one_or_none()
    return None


async def handle_message_received(event: dict[str, Any], session: AsyncSession) -> None:
    company_id_raw = event.get("company_id")
    if company_id_raw is None:
        logger.warning("message_received_skipped_no_company")
        return
    company_id = UUID(company_id_raw)
    data = event["payload"]
    channel_config_id = UUID(data["channel_config_id"])
    channel_type = data["channel_type"]
    external_thread_id = data["external_thread_id"]
    external_message_id = data.get("external_message_id")

    customer_id = await _resolve_customer_id(
        channel_type=channel_type,
        external_customer_id=data["external_customer_id"],
        company_id=company_id,
        session=session,
    )
    if customer_id is None:
        logger.warning(
            "message_received_customer_unresolved",
            channel_type=channel_type,
            channel_config_id=str(channel_config_id),
        )
        return

    conversations = ConversationRepository(session)
    conversation = await conversations.get_by_thread(
        channel_config_id=channel_config_id, external_thread_id=external_thread_id
    )
    if conversation is None:
        conversation = await conversations.add(
            Conversation(
                company_id=company_id,
                customer_id=customer_id,
                channel_config_id=channel_config_id,
                external_thread_id=external_thread_id,
            )
        )

    messages = MessageRepository(session)
    if external_message_id is not None:
        existing = await messages.get_by_external_id(
            channel_config_id=channel_config_id, external_message_id=external_message_id
        )
        if existing is not None:
            return  # already ingested — idempotent under at-least-once delivery

    reply_to_message_id: UUID | None = None
    reply_to_external_id = data.get("reply_to_external_message_id")
    if reply_to_external_id is not None:
        replied_to = await messages.get_by_external_id(
            channel_config_id=channel_config_id, external_message_id=reply_to_external_id
        )
        reply_to_message_id = replied_to.id if replied_to is not None else None

    await messages.add(
        Message(
            company_id=company_id,
            channel_type=channel_type,
            channel_config_id=channel_config_id,
            conversation_id=conversation.id,
            customer_id=customer_id,
            external_message_id=external_message_id,
            direction=MessageDirection.INBOUND,
            message_type=MessageType.TEXT,
            body=data.get("body"),
            reply_to_message_id=reply_to_message_id,
        )
    )

    conversation.last_message_at = datetime.now(UTC)
    if conversation.status in _REOPEN_ON_NEW_MESSAGE:
        conversation.status = ConversationStatus.OPEN


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    async def _handler(message: AbstractIncomingMessage) -> None:
        event = orjson.loads(message.body)
        async with session_scope(session_factory) as session:
            await handle_message_received(event, session)

    await run_consumer(settings, queue_name=QUEUE_NAME, routing_keys=ROUTING_KEYS, handler=_handler)


if __name__ == "__main__":
    asyncio.run(main())
