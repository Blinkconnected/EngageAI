"""Shared by every inbound ingestion path (the generic HTTP webhook route
and the Web Chat WebSocket gateway): turns parsed ``InboundMessage``s into
``message.received`` domain events. One place owns this mapping so every
channel — HTTP-push or bidirectional-socket — feeds the bus identically.
See ``docs/architecture/channels.md`` and ``docs/architecture/web-chat.md``.
"""

from blinkengage.domain.channels import InboundMessage
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.infrastructure.database.models.channel_config import ChannelConfig


async def publish_inbound_message_events(
    events: DomainEventPublisher,
    *,
    config: ChannelConfig,
    messages: list[InboundMessage],
) -> None:
    for message in messages:
        await events.publish(
            DomainEvent(
                event_type="message.received",
                company_id=config.company_id,
                aggregate_type="message",
                aggregate_id=None,
                payload={
                    "channel_config_id": str(config.id),
                    "channel_type": config.channel_type,
                    "external_message_id": message.external_message_id,
                    "external_thread_id": message.external_thread_id,
                    "external_customer_id": message.external_customer_id,
                    "external_customer_name": message.external_customer_name,
                    "body": message.body,
                    "reply_to_external_message_id": message.reply_to_external_message_id,
                    "attachments": [
                        {
                            "external_id": attachment.external_id,
                            "content_type": attachment.content_type,
                            "size_bytes": attachment.size_bytes,
                            "filename": attachment.filename,
                        }
                        for attachment in message.attachments
                    ],
                },
            )
        )
