"""A Jordanian company, billed in dinars, end to end.

The point of these is that *nothing downstream* silently reverts to
dollars. Currency has to survive signup, pricing resolution, the usage
snapshot, the invoice and the ledger — and a single call site reading the
installation default instead of the company's currency would produce an
invoice that looks right and is denominated wrongly.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from httpx import AsyncClient

from tests.integration.test_pricing_engine import platform_headers
from tests.integration.test_usage_engine import conversation_created, meter

JORDAN_SIGNUP = {
    "company_name": "Amman Retail",
    "owner_full_name": "Layla Owner",
    "owner_email": "layla@amman-retail.example",
    "owner_password": "correct-horse-battery-9",
    "country_code": "JO",
}


async def register(client: AsyncClient, app: Any, **overrides: Any) -> dict:
    response = await client.post(
        "/api/v1/auth/register", json={**JORDAN_SIGNUP, **overrides}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    # Verified so the company can act — the gate is covered elsewhere.
    await _verify(app, body["user"]["company"]["id"])
    return body


async def _verify(app: Any, company_id: str) -> None:
    import uuid as _uuid

    from sqlalchemy import update

    from blinkengage.infrastructure.database.models.company import Company

    async with app.state.container.session_factory()() as session:
        await session.execute(
            update(Company)
            .where(Company.id == _uuid.UUID(company_id))
            .values(verified_at=datetime.now(UTC))
        )
        await session.commit()


class TestSignup:
    async def test_a_jordanian_company_is_billed_in_dinars(
        self, client: AsyncClient, app: Any
    ) -> None:
        account = await register(client, app)
        assert account["user"]["company"]["billing_currency"] == "JOD"
        assert account["user"]["company"]["country_code"] == "JO"

    async def test_the_rest_of_the_world_is_billed_in_dollars(
        self, client: AsyncClient, app: Any
    ) -> None:
        account = await register(
            client, app, country_code="GB", owner_email="uk@example.example"
        )
        assert account["user"]["company"]["billing_currency"] == "USD"

    async def test_omitting_the_country_yields_the_default(
        self, client: AsyncClient, app: Any
    ) -> None:
        """Existing clients keep working, and existing companies stay on
        the currency they have always been billed in."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "company_name": "No Country Co",
                "owner_full_name": "Anon Owner",
                "owner_email": "anon@example.example",
                "owner_password": "correct-horse-battery-9",
            },
        )
        assert response.status_code == 201
        assert response.json()["user"]["company"]["billing_currency"] == "USD"

    async def test_an_unknown_country_is_refused(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/auth/register",
            json={**JORDAN_SIGNUP, "country_code": "XX", "owner_email": "x@example.example"},
        )
        assert response.status_code >= 400

    async def test_the_picker_tells_you_the_currency_before_you_sign_up(
        self, client: AsyncClient
    ) -> None:
        """The currency cannot be changed afterwards, so it must not be a
        surprise."""
        response = await client.get("/api/v1/auth/countries")
        assert response.status_code == 200
        jordan = next(row for row in response.json() if row["code"] == "JO")
        assert jordan["currency"] == "JOD"
        assert jordan["currency_symbol"] == "JD"


class TestBillingInDinars:
    async def test_usage_prices_from_the_dinar_rate_not_the_dollar_one(
        self, client: AsyncClient, app: Any
    ) -> None:
        """The whole point. A Jordanian company resolving the dollar
        global default would be invoiced 0.050 JOD for something priced at
        $0.050 — a silent mispricing nothing downstream could detect."""
        headers = await platform_headers(client, app)
        account = await register(client, app)
        company_id = account["user"]["company"]["id"]
        # Seed a dinar global price, since a fresh test database has none.
        seeded = await client.put(
            "/api/v1/platform/pricing/global/metrics/BILLABLE_MESSAGE",
            headers=headers,
            json={
                "unit_amount": "0.035000",
                "effective_from": datetime(2020, 1, 1, tzinfo=UTC).isoformat(),
                "reason": "JOD default",
                "currency": "JOD",
                # Backdated on purpose: the price has to cover usage
                # metered before it was configured, and the engine
                # requires this said out loud.
                "allow_backdating": True,
            },
        )
        assert seeded.status_code in (200, 201), seeded.text

        for _ in range(4):
            await meter(app, conversation_created(company_id, str(uuid4()), datetime.now(UTC)))

        current = await client.get(
            f"/api/v1/platform/usage/companies/{company_id}/current", headers=headers
        )
        period_id = current.json()["period"]["id"]
        closed = await client.post(
            f"/api/v1/platform/usage/periods/{period_id}/close", headers=headers
        )

        assert closed.status_code == 200, closed.text
        snapshot = await client.get(
            f"/api/v1/platform/usage/periods/{period_id}/snapshot", headers=headers
        )
        line = snapshot.json()["lines"][0]
        assert line["currency"] == "JOD"
        assert Decimal(line["unit_amount"]) == Decimal("0.035")

    async def test_the_invoice_and_ledger_stay_in_dinars(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        account = await register(client, app)
        company_id = account["user"]["company"]["id"]
        await client.put(
            "/api/v1/platform/pricing/global/metrics/BILLABLE_MESSAGE",
            headers=headers,
            json={
                "unit_amount": "0.035000",
                "effective_from": datetime(2020, 1, 1, tzinfo=UTC).isoformat(),
                "reason": "JOD default",
                "currency": "JOD",
                # Backdated on purpose: the price has to cover usage
                # metered before it was configured, and the engine
                # requires this said out loud.
                "allow_backdating": True,
            },
        )
        # Past the free allowance, so the invoice is a real charge.
        await client.post(
            "/api/v1/platform/usage/records",
            headers=headers,
            json={
                "company_id": company_id,
                "metric_code": "BILLABLE_MESSAGE",
                "quantity": "150",
                "occurred_at": datetime.now(UTC).isoformat(),
                "idempotency_key": f"jod-{company_id}",
                "note": "Above the allowance",
            },
        )
        current = await client.get(
            f"/api/v1/platform/usage/companies/{company_id}/current", headers=headers
        )
        period_id = current.json()["period"]["id"]
        await client.post(f"/api/v1/platform/usage/periods/{period_id}/close", headers=headers)
        detail = await client.post(
            f"/api/v1/platform/invoices/generate/{period_id}", headers=headers
        )
        invoice_id = detail.json()["invoice"]["id"]
        await client.post(f"/api/v1/platform/invoices/{invoice_id}/issue", headers=headers)

        assert detail.json()["invoice"]["currency"] == "JOD"
        # 50 billable at 0.035 = 1.750 — and three decimal places survive.
        assert Decimal(detail.json()["invoice"]["total_amount"]) == Decimal("1.75")

        position = await client.get(
            f"/api/v1/platform/ledger/{company_id}", headers=headers
        )
        assert position.json()["currency"] == "JOD"
        assert Decimal(position.json()["outstanding"]) == Decimal("1.75")

    async def test_a_payment_is_recorded_in_the_companys_currency(
        self, client: AsyncClient, app: Any
    ) -> None:
        """A dinar customer's payment recorded as dollars would be
        unallocatable against their invoice, and the mismatch would only
        surface as a balance that refuses to settle."""
        headers = await platform_headers(client, app)
        account = await register(client, app)
        company_id = account["user"]["company"]["id"]

        payment = await client.post(
            "/api/v1/platform/invoices/payments",
            headers=headers,
            json={
                "company_id": company_id,
                "amount": "5.000",
                "received_at": datetime.now(UTC).isoformat(),
                "reference": "CLIQ-1",
            },
        )

        assert payment.status_code in (200, 201), payment.text
        assert payment.json()["currency"] == "JOD"

    async def test_the_trial_balance_is_reported_per_currency(
        self, client: AsyncClient, app: Any
    ) -> None:
        """Adding dinars to dollars produces a number that means nothing,
        and no exchange rate is stored to make it mean something."""
        headers = await platform_headers(client, app)
        jordan = await register(client, app)
        await client.post(
            "/api/v1/platform/invoices/payments",
            headers=headers,
            json={
                "company_id": jordan["user"]["company"]["id"],
                "amount": "5.000",
                "received_at": datetime.now(UTC).isoformat(),
            },
        )
        world = await register(
            client, app, country_code="US", owner_email="us@example.example"
        )
        await client.post(
            "/api/v1/platform/invoices/payments",
            headers=headers,
            json={
                "company_id": world["user"]["company"]["id"],
                "amount": "10.00",
                "received_at": datetime.now(UTC).isoformat(),
            },
        )

        books = await client.get("/api/v1/platform/ledger/trial-balance", headers=headers)

        by_currency = {row["currency"]: row for row in books.json()}
        assert set(by_currency) == {"JOD", "USD"}
        # Each set balances on its own.
        assert all(row["in_balance"] for row in books.json())
        assert Decimal(by_currency["JOD"]["total_debits"]) == Decimal("5")
        assert Decimal(by_currency["USD"]["total_debits"]) == Decimal("10")
