"""Tests for the M24 outbound sync consumer — binds ``customer.created``
and syncs to ERPNext only for companies with an active ``ErpConfig``,
silently (and safely) doing nothing otherwise. See
``docs/architecture/erp-integration.md``.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.infrastructure.database.models.erp import ErpCustomerLink
from blinkengage.infrastructure.events.consumers.erp_sync_consumer import handle_event


class FakeErpClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create_customer(self, *, name: str, email: str | None, phone: str | None) -> str:
        self.calls.append({"name": name, "email": email, "phone": phone})
        return "CUST-AUTO-0001"

    async def list_records(self, *, doctype: str, customer_name: str) -> list[dict[str, Any]]:
        return []

    async def health_check(self) -> bool:
        return True


def _event(*, company_id: str, customer_id: str) -> dict[str, Any]:
    return {
        "event_type": "customer.created",
        "company_id": company_id,
        "aggregate_type": "customer",
        "aggregate_id": customer_id,
        "actor_user_id": None,
        "payload": {"full_name": "Jane Doe"},
        "occurred_at": datetime(2026, 6, 1, tzinfo=UTC).isoformat(),
    }


async def _company_id(client: AsyncClient, owner_headers: dict) -> str:
    me = await client.get("/api/v1/auth/me", headers=owner_headers)
    return str(me.json()["company"]["id"])


async def _create_erp_config(client: AsyncClient, owner_headers: dict) -> None:
    response = await client.post(
        "/api/v1/erp-configs",
        json={
            "base_url": "https://erp.acme.example",
            "credentials": {"api_key": "key", "api_secret": "secret"},
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text


async def _create_customer(client: AsyncClient, owner_headers: dict) -> str:
    response = await client.post(
        "/api/v1/customers", json={"full_name": "Jane Doe"}, headers=owner_headers
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


class TestAutoSync:
    async def test_no_op_when_erp_not_configured(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        customer_id = await _create_customer(client, owner_headers)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            await handle_event(_event(company_id=company_id, customer_id=customer_id), session)
            await session.commit()

        async with session_factory() as session:
            links = (await session.execute(select(ErpCustomerLink))).scalars().all()
        assert links == []

    async def test_syncs_when_erp_configured(
        self, client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeErpClient()
        monkeypatch.setattr(
            "blinkengage.application.services.erp_sync_service.build_erp_client",
            lambda config: fake,
        )
        company_id = await _company_id(client, owner_headers)
        await _create_erp_config(client, owner_headers)
        customer_id = await _create_customer(client, owner_headers)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            await handle_event(_event(company_id=company_id, customer_id=customer_id), session)
            await session.commit()

        async with session_factory() as session:
            link = (await session.execute(select(ErpCustomerLink))).scalar_one()
        assert link.erp_customer_name == "CUST-AUTO-0001"
        assert len(fake.calls) == 1

    async def test_erp_client_failure_does_not_raise(
        self, client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class ExplodingClient(FakeErpClient):
            async def create_customer(
                self, *, name: str, email: str | None, phone: str | None
            ) -> str:
                raise RuntimeError("ERPNext is down")

        monkeypatch.setattr(
            "blinkengage.application.services.erp_sync_service.build_erp_client",
            lambda config: ExplodingClient(),
        )
        company_id = await _company_id(client, owner_headers)
        await _create_erp_config(client, owner_headers)
        customer_id = await _create_customer(client, owner_headers)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            await handle_event(_event(company_id=company_id, customer_id=customer_id), session)
            await session.commit()  # must not raise
