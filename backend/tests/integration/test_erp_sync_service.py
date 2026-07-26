"""Integration tests for ``ErpSyncService`` — outbound sync idempotency,
manual pull, and inbound webhook ingestion (secret verification +
customer resolution). ``build_erp_client`` is monkeypatched to a fake
test double so no real ERPNext server is needed — the HTTP-level
behavior of the real client is covered separately in
``tests/unit/test_erpnext_client.py``. See
``docs/architecture/erp-integration.md``.
"""

from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient

from blinkengage.application.services.erp_sync_service import ErpSyncService
from blinkengage.domain.exceptions import (
    AuthenticationError,
    EntityNotFoundError,
    ErpNotConfiguredError,
)
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository
from blinkengage.infrastructure.repositories.erp_config_repository import ErpConfigRepository
from blinkengage.infrastructure.repositories.erp_customer_link_repository import (
    ErpCustomerLinkRepository,
)
from blinkengage.infrastructure.repositories.erp_synced_record_repository import (
    ErpSyncedRecordRepository,
)
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)


class FakeErpClient:
    def __init__(
        self, *, customer_name: str = "CUST-0001", records: list[dict[str, Any]] | None = None
    ) -> None:
        self.customer_name = customer_name
        self.records = records if records is not None else []
        self.create_customer_calls: list[dict[str, Any]] = []

    async def create_customer(self, *, name: str, email: str | None, phone: str | None) -> str:
        self.create_customer_calls.append({"name": name, "email": email, "phone": phone})
        return self.customer_name

    async def list_records(self, *, doctype: str, customer_name: str) -> list[dict[str, Any]]:
        return self.records

    async def health_check(self) -> tuple[bool, str | None]:
        return True, None


def _service(app: Any, session: Any) -> ErpSyncService:
    return ErpSyncService(
        erp_configs=ErpConfigRepository(session),
        customer_links=ErpCustomerLinkRepository(session),
        synced_records=ErpSyncedRecordRepository(session),
        customers=CustomerRepository(session),
        companies=CompanyRepository(session),
        events=OutboxEventPublisher(EventOutboxRepository(session)),
    )


async def _company_id(client: AsyncClient, owner_headers: dict) -> str:
    me = await client.get("/api/v1/auth/me", headers=owner_headers)
    return str(me.json()["company"]["id"])


async def _enable_erp(client: AsyncClient, owner_headers: dict) -> None:
    response = await client.patch(
        "/api/v1/company",
        json={"settings": {"erp": {"enabled": True}}},
        headers=owner_headers,
    )
    assert response.status_code == 200, response.text


async def _create_erp_config(client: AsyncClient, owner_headers: dict) -> str:
    await _enable_erp(client, owner_headers)
    response = await client.post(
        "/api/v1/erp-configs",
        json={
            "base_url": "https://erp.acme.example",
            "credentials": {"api_key": "key", "api_secret": "secret"},
            "webhook_secret": "shh-secret",
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _create_customer(client: AsyncClient, owner_headers: dict) -> str:
    response = await client.post(
        "/api/v1/customers",
        json={"full_name": "Jane Doe", "email": "jane@example.com", "phone": "+15550001111"},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


class TestSyncCustomer:
    async def test_no_active_erp_config_returns_none(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        customer_id = await _create_customer(client, owner_headers)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            link = await _service(app, session).sync_customer(
                company_id=company_id, customer_id=customer_id
            )
        assert link is None

    async def test_creates_customer_and_link_when_configured(
        self, client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeErpClient(customer_name="CUST-9001")
        monkeypatch.setattr(
            "blinkengage.application.services.erp_sync_service.build_erp_client",
            lambda config: fake,
        )
        company_id = await _company_id(client, owner_headers)
        await _create_erp_config(client, owner_headers)
        customer_id = await _create_customer(client, owner_headers)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            link = await _service(app, session).sync_customer(
                company_id=company_id, customer_id=customer_id
            )
            await session.commit()

        assert link is not None
        assert link.erp_customer_name == "CUST-9001"
        assert fake.create_customer_calls == [
            {"name": "Jane Doe", "email": "jane@example.com", "phone": "+15550001111"}
        ]

    async def test_is_idempotent(
        self, client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeErpClient(customer_name="CUST-9002")
        monkeypatch.setattr(
            "blinkengage.application.services.erp_sync_service.build_erp_client",
            lambda config: fake,
        )
        company_id = await _company_id(client, owner_headers)
        await _create_erp_config(client, owner_headers)
        customer_id = await _create_customer(client, owner_headers)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            service = _service(app, session)
            await service.sync_customer(company_id=company_id, customer_id=customer_id)
            await service.sync_customer(company_id=company_id, customer_id=customer_id)
            await session.commit()

        assert len(fake.create_customer_calls) == 1

    async def test_sync_customer_or_raise_raises_when_unconfigured(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        customer_id = await _create_customer(client, owner_headers)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            with pytest.raises(ErpNotConfiguredError):
                await _service(app, session).sync_customer_or_raise(
                    company_id=company_id, customer_id=customer_id
                )


class TestPullRecords:
    async def test_raises_when_unconfigured(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        customer_id = await _create_customer(client, owner_headers)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            with pytest.raises(ErpNotConfiguredError):
                await _service(app, session).pull_records(
                    company_id=company_id, customer_id=customer_id, doctype="Sales Invoice"
                )

    async def test_raises_when_customer_not_yet_synced(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        await _create_erp_config(client, owner_headers)
        customer_id = await _create_customer(client, owner_headers)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            with pytest.raises(EntityNotFoundError):
                await _service(app, session).pull_records(
                    company_id=company_id, customer_id=customer_id, doctype="Sales Invoice"
                )

    async def test_pulls_and_caches_records(
        self, client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeErpClient(
            customer_name="CUST-9003",
            records=[{"name": "SINV-0001", "grand_total": 100}, {"name": "SINV-0002"}],
        )
        monkeypatch.setattr(
            "blinkengage.application.services.erp_sync_service.build_erp_client",
            lambda config: fake,
        )
        company_id = await _company_id(client, owner_headers)
        await _create_erp_config(client, owner_headers)
        customer_id = await _create_customer(client, owner_headers)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            service = _service(app, session)
            await service.sync_customer(company_id=company_id, customer_id=customer_id)
            records = await service.pull_records(
                company_id=company_id, customer_id=customer_id, doctype="Sales Invoice"
            )
            await session.commit()

        assert {r.external_name for r in records} == {"SINV-0001", "SINV-0002"}

        async with session_factory() as session:
            cached = await _service(app, session).list_synced_records(
                company_id=company_id, customer_id=customer_id, doctype="Sales Invoice"
            )
        assert len(cached) == 2


class TestWebhookIngestion:
    async def test_rejects_invalid_secret(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        erp_config_id = await _create_erp_config(client, owner_headers)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            with pytest.raises(AuthenticationError):
                await _service(app, session).record_webhook_payload(
                    erp_config_id=erp_config_id,
                    doctype="Sales Invoice",
                    payload={"name": "SINV-0001"},
                    webhook_secret="wrong-secret",
                )

    async def test_rejects_unknown_config(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            with pytest.raises(EntityNotFoundError):
                await _service(app, session).record_webhook_payload(
                    erp_config_id=str(uuid4()),
                    doctype="Sales Invoice",
                    payload={"name": "SINV-0001"},
                    webhook_secret="shh-secret",
                )

    async def test_resolves_customer_via_link_and_caches_record(
        self, client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeErpClient(customer_name="CUST-9004")
        monkeypatch.setattr(
            "blinkengage.application.services.erp_sync_service.build_erp_client",
            lambda config: fake,
        )
        company_id = await _company_id(client, owner_headers)
        erp_config_id = await _create_erp_config(client, owner_headers)
        customer_id = await _create_customer(client, owner_headers)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            await _service(app, session).sync_customer(
                company_id=company_id, customer_id=customer_id
            )
            await session.commit()

        async with session_factory() as session:
            record = await _service(app, session).record_webhook_payload(
                erp_config_id=erp_config_id,
                doctype="Sales Invoice",
                payload={"name": "SINV-1001", "customer": "CUST-9004", "grand_total": 250},
                webhook_secret="shh-secret",
            )
            await session.commit()

        assert record.customer_id is not None
        assert str(record.customer_id) == customer_id
        assert record.data["grand_total"] == 250

    async def test_missing_name_field_raises_value_error(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        erp_config_id = await _create_erp_config(client, owner_headers)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            with pytest.raises(ValueError):
                await _service(app, session).record_webhook_payload(
                    erp_config_id=erp_config_id,
                    doctype="Sales Invoice",
                    payload={"customer": "CUST-9004"},
                    webhook_secret="shh-secret",
                )
