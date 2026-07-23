"""``ErpSyncService`` — outbound customer sync, manual record pull, and
inbound webhook ingestion for the ERPNext integration. See
``docs/architecture/erp-integration.md``.
"""

import hmac
from datetime import datetime
from typing import Any
from uuid import UUID

from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import (
    AuthenticationError,
    EntityNotFoundError,
    ErpNotConfiguredError,
)
from blinkengage.infrastructure.database.models.erp import ErpCustomerLink, ErpSyncedRecord
from blinkengage.infrastructure.erp.factory import build_erp_client
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository
from blinkengage.infrastructure.repositories.erp_config_repository import ErpConfigRepository
from blinkengage.infrastructure.repositories.erp_customer_link_repository import (
    ErpCustomerLinkRepository,
)
from blinkengage.infrastructure.repositories.erp_synced_record_repository import (
    ErpSyncedRecordRepository,
)

_DEFAULT_CUSTOMER_FIELD = "customer"


class ErpSyncService:
    def __init__(
        self,
        *,
        erp_configs: ErpConfigRepository,
        customer_links: ErpCustomerLinkRepository,
        synced_records: ErpSyncedRecordRepository,
        customers: CustomerRepository,
        events: DomainEventPublisher,
    ) -> None:
        self._erp_configs = erp_configs
        self._customer_links = customer_links
        self._synced_records = synced_records
        self._customers = customers
        self._events = events

    async def sync_customer(self, *, company_id: UUID, customer_id: UUID) -> ErpCustomerLink | None:
        """Idempotent: returns the existing link if this customer was
        already synced. Returns ``None`` (silently) rather than raising
        when the company has no active ERPNext connection — most
        companies won't have one configured, and this is called
        automatically on every new customer via
        ``erp_sync_consumer``, which must not error/log-spam for the
        common case."""
        existing = await self._customer_links.get_by_customer(customer_id)
        if existing is not None:
            return existing

        erp_config = await self._erp_configs.get_active_for_company(company_id=company_id)
        if erp_config is None:
            return None

        customer = await self._customers.get_by_id(company_id=company_id, customer_id=customer_id)
        if customer is None:
            raise EntityNotFoundError("Customer", customer_id)

        client = build_erp_client(erp_config)
        erp_customer_name = await client.create_customer(
            name=customer.full_name, email=customer.email, phone=customer.phone
        )
        link = await self._customer_links.add(
            ErpCustomerLink(
                company_id=company_id, customer_id=customer_id, erp_customer_name=erp_customer_name
            )
        )
        await self._events.publish(
            DomainEvent(
                event_type="erp.customer_synced",
                company_id=company_id,
                aggregate_type="customer",
                aggregate_id=customer_id,
                payload={"erp_customer_name": erp_customer_name},
            )
        )
        return link

    async def sync_customer_or_raise(
        self, *, company_id: UUID, customer_id: UUID
    ) -> ErpCustomerLink:
        """The explicit, agent-triggered counterpart to ``sync_customer``
        (``POST /customers/{id}/erp-sync``) — unlike the automatic
        consumer, a deliberate manual action against an unconfigured ERP
        connection should surface as an error, not silently no-op."""
        link = await self.sync_customer(company_id=company_id, customer_id=customer_id)
        if link is None:
            raise ErpNotConfiguredError()
        return link

    async def list_synced_records(
        self, *, company_id: UUID, customer_id: UUID, doctype: str | None
    ) -> list[ErpSyncedRecord]:
        return await self._synced_records.list_for_customer(
            company_id=company_id, customer_id=customer_id, doctype=doctype
        )

    async def pull_records(
        self, *, company_id: UUID, customer_id: UUID, doctype: str
    ) -> list[ErpSyncedRecord]:
        erp_config = await self._erp_configs.get_active_for_company(company_id=company_id)
        if erp_config is None:
            raise ErpNotConfiguredError()

        link = await self._customer_links.get_by_customer(customer_id)
        if link is None:
            raise EntityNotFoundError("ErpCustomerLink", customer_id)

        client = build_erp_client(erp_config)
        records = await client.list_records(doctype=doctype, customer_name=link.erp_customer_name)
        results = []
        for record in records:
            external_name = record.get("name")
            if not external_name:
                continue
            results.append(
                await self._synced_records.upsert(
                    company_id=company_id,
                    customer_id=customer_id,
                    doctype=doctype,
                    external_name=str(external_name),
                    data=record,
                    external_modified_at=_parse_modified(record.get("modified")),
                )
            )
        return results

    async def record_webhook_payload(
        self,
        *,
        erp_config_id: UUID,
        doctype: str,
        payload: dict[str, Any],
        webhook_secret: str | None,
    ) -> ErpSyncedRecord:
        erp_config = await self._erp_configs.get_by_id_any_company(erp_config_id)
        if erp_config is None or not erp_config.is_active:
            raise EntityNotFoundError("ErpConfig", erp_config_id)
        if not erp_config.webhook_secret or not hmac.compare_digest(
            webhook_secret or "", erp_config.webhook_secret
        ):
            raise AuthenticationError("Invalid ERPNext webhook signature")
        company_id = erp_config.company_id

        external_name = payload.get("name")
        if not external_name:
            raise ValueError("Webhook payload is missing a 'name' field")

        customer_id: UUID | None = None
        erp_customer_name = payload.get(_DEFAULT_CUSTOMER_FIELD)
        if erp_customer_name:
            link = await self._customer_links.get_by_erp_customer_name(
                company_id=company_id, erp_customer_name=str(erp_customer_name)
            )
            if link is not None:
                customer_id = link.customer_id

        return await self._synced_records.upsert(
            company_id=company_id,
            customer_id=customer_id,
            doctype=doctype,
            external_name=str(external_name),
            data=payload,
            external_modified_at=_parse_modified(payload.get("modified")),
        )


def _parse_modified(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None
