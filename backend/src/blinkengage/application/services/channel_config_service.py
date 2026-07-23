"""Application service for per-company channel configuration. See
``docs/architecture/channels.md``.
"""

from typing import Any
from uuid import UUID

from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import EntityNotFoundError, InvalidChannelTypeError
from blinkengage.infrastructure.channels.registry import ChannelRegistry
from blinkengage.infrastructure.database.models.channel_config import ChannelConfig
from blinkengage.infrastructure.repositories.channel_config_repository import (
    ChannelConfigRepository,
)


class ChannelConfigService:
    def __init__(
        self, *, channel_configs: ChannelConfigRepository, events: DomainEventPublisher
    ) -> None:
        self._channel_configs = channel_configs
        self._events = events

    async def create(
        self,
        *,
        company_id: UUID,
        channel_type: str,
        display_name: str,
        credentials: dict[str, Any],
        webhook_secret: str | None,
        actor_user_id: UUID | None = None,
    ) -> ChannelConfig:
        if channel_type not in ChannelRegistry.known_channel_types():
            raise InvalidChannelTypeError(channel_type)
        channel_config = await self._channel_configs.add(
            ChannelConfig(
                company_id=company_id,
                channel_type=channel_type,
                display_name=display_name,
                credentials=credentials,
                webhook_secret=webhook_secret,
            )
        )
        await self._events.publish(
            DomainEvent(
                event_type="channel_config.created",
                company_id=company_id,
                aggregate_type="channel_config",
                aggregate_id=channel_config.id,
                actor_user_id=actor_user_id,
                payload={"channel_type": channel_type, "display_name": display_name},
            )
        )
        return channel_config

    async def get(self, *, company_id: UUID, channel_config_id: UUID) -> ChannelConfig:
        channel_config = await self._channel_configs.get_by_id(
            company_id=company_id, channel_config_id=channel_config_id
        )
        if channel_config is None:
            raise EntityNotFoundError("ChannelConfig", channel_config_id)
        return channel_config

    async def list_channel_configs(
        self, *, company_id: UUID, offset: int, limit: int
    ) -> tuple[list[ChannelConfig], int]:
        return await self._channel_configs.list_for_company(
            company_id=company_id, offset=offset, limit=limit
        )

    async def update(
        self,
        *,
        company_id: UUID,
        channel_config_id: UUID,
        display_name: str | None,
        credentials: dict[str, Any] | None,
        webhook_secret: str | None,
        is_active: bool | None,
        actor_user_id: UUID | None = None,
    ) -> ChannelConfig:
        channel_config = await self.get(company_id=company_id, channel_config_id=channel_config_id)
        if display_name is not None:
            channel_config.display_name = display_name
        if credentials is not None:
            channel_config.credentials = credentials
        if webhook_secret is not None:
            channel_config.webhook_secret = webhook_secret
        if is_active is not None:
            channel_config.is_active = is_active
        await self._events.publish(
            DomainEvent(
                event_type="channel_config.updated",
                company_id=company_id,
                aggregate_type="channel_config",
                aggregate_id=channel_config.id,
                actor_user_id=actor_user_id,
                payload={
                    "display_name": channel_config.display_name,
                    "is_active": channel_config.is_active,
                },
            )
        )
        return channel_config

    async def delete(
        self, *, company_id: UUID, channel_config_id: UUID, actor_user_id: UUID | None = None
    ) -> None:
        channel_config = await self.get(company_id=company_id, channel_config_id=channel_config_id)
        await self._channel_configs.soft_delete(channel_config)
        await self._events.publish(
            DomainEvent(
                event_type="channel_config.deleted",
                company_id=company_id,
                aggregate_type="channel_config",
                aggregate_id=channel_config.id,
                actor_user_id=actor_user_id,
                payload={"display_name": channel_config.display_name},
            )
        )
