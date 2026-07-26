"""Application service for a company's ERPNext connection settings. See
``docs/architecture/erp-integration.md`` and
``docs/architecture/company-onboarding.md``. Mirrors
``ChannelConfigService`` exactly — same CRUD shape, same "credentials are
write-only, never echoed back" contract.

Every mutating/reading method requires the company's ERP master switch
(``Company.settings["erp"]["enabled"]``) to be on first — see
``_ensure_enabled``. This is the backend enforcement half of "ERP must be
completely hidden unless enabled": the frontend also hides the nav item/
route/tab, but an API client that bypassed the UI must be refused too.
"""

from typing import Any
from uuid import UUID

from blinkengage.domain.company_settings import is_erp_enabled
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import EntityNotFoundError, ErpNotConfiguredError
from blinkengage.infrastructure.database.models.erp import ErpConfig
from blinkengage.infrastructure.erp.factory import build_erp_client
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.erp_config_repository import ErpConfigRepository


class ErpConfigService:
    def __init__(
        self,
        *,
        erp_configs: ErpConfigRepository,
        companies: CompanyRepository,
        events: DomainEventPublisher,
    ) -> None:
        self._erp_configs = erp_configs
        self._companies = companies
        self._events = events

    async def _ensure_enabled(self, company_id: UUID) -> None:
        company = await self._companies.get_by_id(company_id)
        if company is None or not is_erp_enabled(company.settings):
            raise ErpNotConfiguredError()

    async def create(
        self,
        *,
        company_id: UUID,
        base_url: str,
        credentials: dict[str, Any],
        webhook_secret: str | None,
        actor_user_id: UUID | None = None,
    ) -> ErpConfig:
        await self._ensure_enabled(company_id)
        erp_config = await self._erp_configs.add(
            ErpConfig(
                company_id=company_id,
                base_url=base_url,
                credentials=credentials,
                webhook_secret=webhook_secret,
            )
        )
        await self._events.publish(
            DomainEvent(
                event_type="erp_config.created",
                company_id=company_id,
                aggregate_type="erp_config",
                aggregate_id=erp_config.id,
                actor_user_id=actor_user_id,
                payload={"base_url": base_url},
            )
        )
        return erp_config

    async def list_erp_configs(
        self, *, company_id: UUID, offset: int, limit: int
    ) -> tuple[list[ErpConfig], int]:
        await self._ensure_enabled(company_id)
        return await self._erp_configs.list_for_company(
            company_id=company_id, offset=offset, limit=limit
        )

    async def get(self, *, company_id: UUID, erp_config_id: UUID) -> ErpConfig:
        await self._ensure_enabled(company_id)
        erp_config = await self._erp_configs.get_by_id(
            company_id=company_id, erp_config_id=erp_config_id
        )
        if erp_config is None:
            raise EntityNotFoundError("ErpConfig", erp_config_id)
        return erp_config

    async def update(
        self,
        *,
        company_id: UUID,
        erp_config_id: UUID,
        base_url: str | None,
        credentials: dict[str, Any] | None,
        webhook_secret: str | None,
        is_active: bool | None,
        actor_user_id: UUID | None = None,
    ) -> ErpConfig:
        erp_config = await self.get(company_id=company_id, erp_config_id=erp_config_id)
        if base_url is not None:
            erp_config.base_url = base_url
        if credentials is not None:
            erp_config.credentials = credentials
        if webhook_secret is not None:
            erp_config.webhook_secret = webhook_secret
        if is_active is not None:
            erp_config.is_active = is_active
        await self._events.publish(
            DomainEvent(
                event_type="erp_config.updated",
                company_id=company_id,
                aggregate_type="erp_config",
                aggregate_id=erp_config.id,
                actor_user_id=actor_user_id,
                payload={"is_active": erp_config.is_active},
            )
        )
        return erp_config

    async def delete(
        self, *, company_id: UUID, erp_config_id: UUID, actor_user_id: UUID | None = None
    ) -> None:
        erp_config = await self.get(company_id=company_id, erp_config_id=erp_config_id)
        await self._erp_configs.soft_delete(erp_config)
        await self._events.publish(
            DomainEvent(
                event_type="erp_config.deleted",
                company_id=company_id,
                aggregate_type="erp_config",
                aggregate_id=erp_config.id,
                actor_user_id=actor_user_id,
                payload={},
            )
        )

    async def test_connection(
        self, *, company_id: UUID, erp_config_id: UUID
    ) -> tuple[bool, str | None]:
        """Manual re-check against an already-saved connection — same
        reasoning as ``ChannelConfigService.test_connection``. Doesn't
        persist a health status anywhere (unlike Channels, ERP has no
        periodic health-monitoring sweep in this milestone — "Test
        Connection" is an on-demand action only, see
        ``docs/architecture/company-onboarding.md``)."""
        erp_config = await self.get(company_id=company_id, erp_config_id=erp_config_id)
        client = build_erp_client(erp_config)
        return await client.health_check()

    async def test_connection_ephemeral(
        self, *, company_id: UUID, base_url: str, credentials: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """Tests connection details the operator has typed into the
        wizard/settings form but not saved yet — mirrors
        ``ChannelConfigService.test_connection_ephemeral``. Requires the
        company's ERP master switch to already be on, same as every
        other method here."""
        await self._ensure_enabled(company_id)
        client = build_erp_client(
            ErpConfig(company_id=company_id, base_url=base_url, credentials=credentials)
        )
        return await client.health_check()
