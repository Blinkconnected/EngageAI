"""Shared by every inbound ingestion path (the generic HTTP webhook route
and the Web Chat WebSocket gateway): turns parsed ``InboundMessage``s into
``message.received`` domain events. One place owns this mapping so every
channel — HTTP-push or bidirectional-socket — feeds the bus identically.
See ``docs/architecture/channels.md`` and ``docs/architecture/web-chat.md``.
"""

import uuid

from blinkengage.domain.brain.ingestion import ChannelPurpose, parse_channel_purpose
from blinkengage.domain.channels import InboundMessage
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.infrastructure.database.models.channel_config import ChannelConfig


class NotCustomerSupportChannelError(Exception):
    """A non-support channel reached the customer conversation pipeline.

    Always a routing bug. Returning quietly would leave the caller believing
    the message was handled while it was silently dropped — and dropping a
    customer's message is the one failure this pipeline exists to prevent.
    """

    def __init__(self, channel_config_id: uuid.UUID, purpose: ChannelPurpose) -> None:
        super().__init__(
            f"channel {channel_config_id} has purpose {purpose.value}; "
            "it must not publish customer message events"
        )
        self.channel_config_id = channel_config_id
        self.purpose = purpose


async def publish_inbound_message_events(
    events: DomainEventPublisher,
    *,
    config: ChannelConfig,
    messages: list[InboundMessage],
) -> None:
    """Publish ``message.received`` for a customer-support channel.

    **Refuses anything else, and that refusal is the point.** Every caller
    already branches on purpose before reaching here, so this is defence in
    depth: it is the last shared point before a message becomes a customer and
    a conversation, and a knowledge mailbox that reached it would manufacture a
    customer record for the company's own finance team.

    ``parse_channel_purpose`` raises on a value this build does not recognise,
    so an unknown purpose fails closed rather than defaulting into the customer
    pipeline.
    """
    purpose = parse_channel_purpose(config.purpose)
    if purpose is not ChannelPurpose.CUSTOMER_SUPPORT:
        raise NotCustomerSupportChannelError(config.id, purpose)

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
