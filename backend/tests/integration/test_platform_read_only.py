"""Read-only platform administrators.

Platform authority is otherwise all-or-nothing, deliberately, so that no
tenant role can be edited into it. This tier does not weaken that: it only
ever **narrows** what an operator can do, and a strictly less powerful
principal cannot be an escalation path.

The pairing that matters is that reads stay open while writes close — a
read-only tier that also blocked reading would be pointless, and one that
allowed writing would be a lie.
"""

from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy import update

from blinkengage.infrastructure.database.models.user import User
from tests.integration.test_pricing_engine import company_id_of, platform_headers

PRICING = "/api/v1/platform/pricing"


async def make_read_only(app: Any) -> None:
    async with app.state.container.session_factory()() as session:
        await session.execute(
            update(User)
            .where(User.is_platform_admin.is_(True))
            .values(platform_read_only=True)
        )
        await session.commit()


class TestReadsStayOpen:
    async def test_a_read_only_operator_can_see_effective_pricing(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)
        await make_read_only(app)

        response = await client.get(
            f"{PRICING}/effective", headers=headers, params={"company_id": company_id}
        )

        assert response.status_code == 200

    async def test_a_read_only_operator_can_see_the_history(
        self, client: AsyncClient, app: Any
    ) -> None:
        """The main reason to grant read access at all: auditing what a
        customer was charged, without the authority to change it."""
        headers = await platform_headers(client, app)
        await make_read_only(app)

        assert (await client.get(f"{PRICING}/history", headers=headers)).status_code == 200

    async def test_a_read_only_operator_can_use_the_resolver_preview(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A POST, but a read: it writes nothing, and seeing what the
        resolver will decide is exactly what read access is for."""
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)
        await make_read_only(app)

        response = await client.post(
            f"{PRICING}/resolve",
            headers=headers,
            json={
                "items": [
                    {
                        "company_id": company_id,
                        "metric_code": "BILLABLE_MESSAGE",
                        "occurred_at": datetime.now(UTC).isoformat(),
                    }
                ],
                "strict": False,
            },
        )

        assert response.status_code == 200

    async def test_the_profile_reports_read_only(
        self, client: AsyncClient, app: Any
    ) -> None:
        """The console needs to know, so it can disable its controls and
        say why rather than letting somebody fill in a form that will be
        refused."""
        headers = await platform_headers(client, app)
        await make_read_only(app)

        response = await client.get("/api/v1/platform/me", headers=headers)

        assert response.json()["read_only"] is True


class TestWritesClose:
    async def test_setting_a_company_price_is_refused(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)
        await make_read_only(app)

        response = await client.put(
            f"{PRICING}/companies/{company_id}/metrics/BILLABLE_MESSAGE",
            headers=headers,
            json={
                "unit_amount": "0.010000",
                "effective_from": datetime.now(UTC).isoformat(),
                "reason": "Should not be allowed",
                "expect_no_current_rate": True,
            },
        )

        assert response.status_code == 403
        assert "read-only" in response.json()["detail"]

    async def test_changing_the_global_price_is_refused(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await make_read_only(app)

        response = await client.put(
            f"{PRICING}/global/metrics/BILLABLE_MESSAGE",
            headers=headers,
            json={
                "unit_amount": "0.010000",
                "effective_from": datetime.now(UTC).isoformat(),
                "reason": "Should not be allowed",
            },
        )

        assert response.status_code == 403

    async def test_assigning_a_profile_is_refused(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)
        await make_read_only(app)

        response = await client.put(
            f"{PRICING}/companies/{company_id}/profile",
            headers=headers,
            json={
                "profile_id": None,
                "effective_from": datetime.now(UTC).isoformat(),
                "reason": "Should not be allowed",
            },
        )

        assert response.status_code == 403

    async def test_a_full_operator_is_unaffected(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The default. Existing platform administrators keep the
        authority they had — the migration backfills the flag to false."""
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)

        response = await client.put(
            f"{PRICING}/companies/{company_id}/metrics/BILLABLE_MESSAGE",
            headers=headers,
            json={
                "unit_amount": "0.010000",
                "effective_from": datetime.now(UTC).isoformat(),
                "reason": "Negotiated",
                "expect_no_current_rate": True,
            },
        )

        assert response.status_code == 201, response.text


class TestAuditCurrency:
    async def test_the_history_records_the_rates_own_currency(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A history reading "0.028 USD" for a dinar change is unreadable,
        and worse, looks like a currency mistake somebody made."""
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)
        await client.put(
            f"{PRICING}/companies/{company_id}/metrics/BILLABLE_MESSAGE",
            headers=headers,
            json={
                "unit_amount": "0.035000",
                "effective_from": datetime.now(UTC).isoformat(),
                "reason": "Dinar rate",
                "currency": "JOD",
                "expect_no_current_rate": True,
            },
        )

        history = await client.get(
            f"{PRICING}/history", headers=headers, params={"company_id": company_id}
        )

        entry = history.json()[0]
        assert entry["currency"] == "JOD"
