"""Orchestrates inbound webhook processing — the seam that keeps the
(future) conversation engine channel-agnostic (see
``docs/architecture/channels.md``): this service never creates a
Conversation/Message row (those tables don't exist until M13) — it only
verifies, parses, and publishes ``message.received`` domain events. The
conversation engine will consume those events, never call a provider.
"""

from uuid import UUID

from blinkengage.application.services.inbound_message_events import (
    publish_inbound_message_events,
)
from blinkengage.domain.channels import WebhookAck, WebhookRequest
from blinkengage.domain.events import DomainEventPublisher
from blinkengage.domain.exceptions import AuthenticationError, EntityNotFoundError
from blinkengage.infrastructure.channels.factory import ChannelProviderFactory
from blinkengage.infrastructure.repositories.channel_config_repository import (
    ChannelConfigRepository,
)


class WebhookIngestService:
    def __init__(
        self,
        *,
        channel_configs: ChannelConfigRepository,
        factory: ChannelProviderFactory,
        events: DomainEventPublisher,
    ) -> None:
        self._channel_configs = channel_configs
        self._factory = factory
        self._events = events

    async def ingest(self, *, channel_config_id: UUID, request: WebhookRequest) -> WebhookAck:
        config = await self._channel_configs.get_by_id_any_company(channel_config_id)
        if config is None or not config.is_active:
            raise EntityNotFoundError("ChannelConfig", channel_config_id)

        provider = self._factory.build(config)
        if not provider.verify_signature(request):
            raise AuthenticationError("Invalid webhook signature")

        messages, ack = await provider.webhook(request)
        await publish_inbound_message_events(self._events, config=config, messages=messages)
        return ack
