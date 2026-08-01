"""The aging report: what is outstanding, and how late it is.

Every test here pins a rule the endpoint has to *enforce* rather than
merely intend:

- an invoice lands in exactly one bucket, so the buckets sum to the total,
- an empty bucket is still reported, so a column never silently vanishes,
- a written-off debt is not aged, because nobody is chasing it,
- dollars and dinars are separate books, and the response has nowhere to
  put a figure spanning them,
- money crosses the wire as a string, never a JSON number.

The clock is never moved. Invoices are aged by moving their **due date**
backwards, which is what the report reads: a test that depended on the
real date would pass in one week of the month and fail in another.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy import update

from blinkengage.infrastructure.database.models.invoicing import Invoice
from tests.integration.test_invoice_engine import closed_period_with_usage, issued_invoice
from tests.integration.test_jordan_billing import register
from tests.integration.test_pricing_engine import company_id_of, platform_headers, seed_global

AGING = "/api/v1/platform/payments/collections/aging"

#: What ``closed_period_with_usage`` bills: the fixture consumes the free
#: allowance, then meters four conversations at the seeded price.
DOLLAR_INVOICE_TOTAL = Decimal("0.20")

#: 150 metered against a 100-conversation allowance leaves 50 billable at
#: the seeded dinar rate of 0.035 — and three decimal places survive it.
DINAR_INVOICE_TOTAL = Decimal("1.75")


async def age_invoice(app: Any, invoice_id: str, *, days_overdue: int) -> None:
    """Moves an invoice's due date into the past.

    ``days_overdue`` of zero or less puts the due date in the future,
    which is what "not yet due" means.
    """
    due = datetime.now(UTC).date() - timedelta(days=days_overdue)
    async with app.state.container.session_factory()() as session:
        await session.execute(
            update(Invoice).where(Invoice.id == uuid.UUID(invoice_id)).values(due_date=due)
        )
        await session.commit()


async def dollar_invoice(
    client: AsyncClient, headers: dict, app: Any, company_id: str, *, days_overdue: int
) -> dict:
    period_id = await closed_period_with_usage(client, headers, app, company_id)
    invoice = (await issued_invoice(client, headers, period_id))["invoice"]
    await age_invoice(app, invoice["id"], days_overdue=days_overdue)
    return dict(invoice)


async def second_dollar_company(client: AsyncClient, app: Any, *, email: str) -> str:
    """Another company on the installation default currency.

    Needed because a company has exactly one open billing period, so two
    invoices in the same currency mean two customers — which is also the
    situation the report is actually for.
    """
    account = await register(
        client, app, country_code="US", owner_email=email, company_name="Second Co"
    )
    return str(account["user"]["company"]["id"])


async def dinar_invoice(client: AsyncClient, headers: dict, app: Any, *, email: str) -> dict:
    """An issued invoice for a Jordanian company, denominated in dinars."""
    account = await register(client, app, owner_email=email)
    company_id = str(account["user"]["company"]["id"])
    seeded = await client.put(
        "/api/v1/platform/pricing/global/metrics/BILLABLE_MESSAGE",
        headers=headers,
        json={
            "unit_amount": "0.035000",
            "effective_from": datetime(2020, 1, 1, tzinfo=UTC).isoformat(),
            "reason": "JOD default",
            "currency": "JOD",
            # Backdated on purpose: the price has to cover usage metered
            # before it was configured, and the engine requires that said
            # out loud.
            "allow_backdating": True,
        },
    )
    assert seeded.status_code in (200, 201), seeded.text

    await client.post(
        "/api/v1/platform/usage/records",
        headers=headers,
        json={
            "company_id": company_id,
            "metric_code": "BILLABLE_MESSAGE",
            "quantity": "150",
            "occurred_at": datetime.now(UTC).isoformat(),
            "idempotency_key": f"aging-jod-{company_id}",
            "note": "Above the allowance, so the invoice is a real charge.",
        },
    )
    current = await client.get(
        f"/api/v1/platform/usage/companies/{company_id}/current", headers=headers
    )
    period_id = current.json()["period"]["id"]
    await client.post(f"/api/v1/platform/usage/periods/{period_id}/close", headers=headers)
    detail = await client.post(f"/api/v1/platform/invoices/generate/{period_id}", headers=headers)
    invoice_id = detail.json()["invoice"]["id"]
    issued = await client.post(f"/api/v1/platform/invoices/{invoice_id}/issue", headers=headers)
    assert issued.status_code == 200, issued.text
    return dict(issued.json()["invoice"])


async def report(client: AsyncClient, headers: dict, **params: str) -> dict:
    response = await client.get(AGING, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return dict(response.json())


def books(report_body: dict, currency: str) -> dict:
    return next(row for row in report_body["currencies"] if row["currency"] == currency)


def bucket(report_body: dict, currency: str, name: str) -> dict:
    return next(row for row in books(report_body, currency)["buckets"] if row["bucket"] == name)


class TestBucketing:
    async def test_an_invoice_lands_in_exactly_one_bucket(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """If an invoice could be counted twice, the buckets would stop
        summing to the total and neither figure could be trusted."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        await dollar_invoice(client, headers, app, company_id, days_overdue=45)

        body = await report(client, headers)

        assert bucket(body, "USD", "days_31_60")["invoice_count"] == 1
        assert Decimal(bucket(body, "USD", "days_31_60")["amount_outstanding"]) == (
            DOLLAR_INVOICE_TOTAL
        )
        assert [row["bucket"] for row in books(body, "USD")["buckets"] if row["invoice_count"]] == [
            "days_31_60"
        ]
        assert books(body, "USD")["invoice_count"] == 1

    async def test_every_bucket_is_reported_even_when_it_is_empty(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A bucket that disappears when nothing is in it is
        indistinguishable from one the caller forgot to handle, and it
        makes a console's column vanish rather than read zero."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        await dollar_invoice(client, headers, app, company_id, days_overdue=45)

        body = await report(client, headers)

        assert [row["bucket"] for row in books(body, "USD")["buckets"]] == [
            "current",
            "days_1_30",
            "days_31_60",
            "days_61_90",
            "days_90_plus",
        ]
        empty = bucket(body, "USD", "days_90_plus")
        assert empty["invoice_count"] == 0
        # At the storage scale, like every other amount in the report. A
        # zero rendering as "0" beside amounts rendering as "0.000000"
        # reads as a bug to whoever is auditing the page.
        assert empty["amount_outstanding"] == "0.000000"

    async def test_an_invoice_that_is_not_yet_due_is_current_not_overdue(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Owed is not the same as late, and a report that conflated them
        would show a customer in arrears the day they were invoiced."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        await dollar_invoice(client, headers, app, company_id, days_overdue=-10)

        body = await report(client, headers)

        assert bucket(body, "USD", "current")["invoice_count"] == 1
        assert bucket(body, "USD", "days_1_30")["invoice_count"] == 0

    async def test_the_boundary_day_belongs_to_the_band_that_names_it(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The requirement names "61-90" and "90+", which both claim day
        90. An invoice in two buckets would double-count, so day 90 goes
        to the band that names it and the open-ended band starts at 91."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        acme = await company_id_of(client, owner_headers)
        other = await second_dollar_company(client, app, email="ninety-one@example.example")
        await dollar_invoice(client, headers, app, acme, days_overdue=90)
        await dollar_invoice(client, headers, app, other, days_overdue=91)

        body = await report(client, headers)

        assert bucket(body, "USD", "days_61_90")["invoice_count"] == 1
        assert bucket(body, "USD", "days_90_plus")["invoice_count"] == 1
        assert books(body, "USD")["invoice_count"] == 2

    async def test_only_what_is_still_owed_is_aged(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """An aging report showing the face value of a part-paid invoice
        overstates the receivable, which is the one number this page
        exists to get right."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        invoice = await dollar_invoice(client, headers, app, company_id, days_overdue=45)

        payment = await client.post(
            "/api/v1/platform/invoices/payments",
            headers=headers,
            json={
                "company_id": company_id,
                "amount": "0.05",
                "received_at": datetime.now(UTC).isoformat(),
                "reference": "part-payment",
            },
        )
        assert payment.status_code == 201, payment.text
        allocated = await client.post(
            f"/api/v1/platform/invoices/payments/{payment.json()['id']}/allocate",
            headers=headers,
            json={"invoice_id": invoice["id"], "amount": "0.05"},
        )
        assert allocated.status_code == 200, allocated.text

        body = await report(client, headers)

        aged = bucket(body, "USD", "days_31_60")
        assert aged["invoice_count"] == 1
        assert Decimal(aged["amount_outstanding"]) == DOLLAR_INVOICE_TOTAL - Decimal("0.05")


class TestWrittenOffDebtIsNotAged:
    """A debt nobody is chasing must not appear in an aging report.

    Collections already stopped dunning written-off invoices, stopped
    holding companies suspended for them and stopped counting them in a
    company's standing. An aging report that still carried them would be
    the one place an abandoned receivable kept ageing for ever — and it is
    the page finance reads to decide what is collectable.
    """

    async def test_a_written_off_invoice_leaves_the_report(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        invoice = await dollar_invoice(client, headers, app, company_id, days_overdue=120)

        before = await report(client, headers)
        assert (
            bucket(before, "USD", "days_90_plus")["invoice_count"] == 1
        ), "the fixture must actually be aged before the write-off means anything"

        written = await client.post(
            f"/api/v1/platform/ledger/write-offs/{invoice['id']}",
            headers=headers,
            json={"reason": "Customer entered administration; debt abandoned."},
        )
        assert written.status_code == 200, written.text

        after = await report(client, headers)

        # The invoice is still unpaid and still overdue — that is the
        # truth, and there is no WRITTEN_OFF status. What changed is that
        # the ledger moved the receivable to bad debt, so it is no longer
        # something anybody is waiting to collect.
        assert after["currencies"] == []


class TestNothingIsSummedAcrossCurrencies:
    async def test_dollars_and_dinars_are_reported_as_separate_books(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Nothing converts and no exchange rate is stored anywhere, so a
        combined figure could not be computed even if somebody wanted
        one."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        acme = await company_id_of(client, owner_headers)
        await dollar_invoice(client, headers, app, acme, days_overdue=45)
        jordanian = await dinar_invoice(client, headers, app, email="jod@example.example")
        await age_invoice(app, jordanian["id"], days_overdue=45)

        body = await report(client, headers)

        assert [row["currency"] for row in body["currencies"]] == ["JOD", "USD"]
        assert Decimal(books(body, "USD")["total_outstanding"]) == DOLLAR_INVOICE_TOTAL
        assert Decimal(books(body, "JOD")["total_outstanding"]) == DINAR_INVOICE_TOTAL
        # Same bucket, same age, two currencies — and two separate rows.
        assert bucket(body, "USD", "days_31_60")["invoice_count"] == 1
        assert bucket(body, "JOD", "days_31_60")["invoice_count"] == 1

    async def test_there_is_no_figure_above_the_currency_grouping(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The shape is what makes a cross-currency sum impossible rather
        than merely unwise: there is nowhere in the response to write one,
        and no bucket names a currency it could be regrouped by."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        acme = await company_id_of(client, owner_headers)
        await dollar_invoice(client, headers, app, acme, days_overdue=45)
        await dinar_invoice(client, headers, app, email="jod-shape@example.example")

        body = await report(client, headers)

        assert set(body) == {"as_of", "currencies"}
        assert set(books(body, "USD")) == {
            "currency",
            "buckets",
            "invoice_count",
            "total_outstanding",
        }
        # A bucket carrying its own currency could be lifted out of its
        # group and added to another one's.
        assert "currency" not in bucket(body, "USD", "current")

    async def test_amounts_cross_the_wire_as_strings(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A JSON number becomes a JavaScript float in the browser, which
        reintroduces exactly the drift Decimal exists to prevent."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        await dollar_invoice(client, headers, app, company_id, days_overdue=45)

        body = await report(client, headers)

        assert isinstance(books(body, "USD")["total_outstanding"], str)
        assert all(
            isinstance(row["amount_outstanding"], str) for row in books(body, "USD")["buckets"]
        )


class TestScoping:
    async def test_company_id_narrows_the_report_to_one_customer(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        acme = await company_id_of(client, owner_headers)
        other = await second_dollar_company(client, app, email="scoped@example.example")
        await dollar_invoice(client, headers, app, acme, days_overdue=45)
        await dollar_invoice(client, headers, app, other, days_overdue=45)

        everything = await report(client, headers)
        scoped = await report(client, headers, company_id=acme)

        assert books(everything, "USD")["invoice_count"] == 2
        assert books(scoped, "USD")["invoice_count"] == 1
        assert Decimal(books(scoped, "USD")["total_outstanding"]) == DOLLAR_INVOICE_TOTAL

    async def test_an_unknown_company_is_a_404_not_an_empty_report(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """ "Owes nothing" and "no such company" are different answers, and
        only one of them means the operator should check the id they
        pasted."""
        headers = await platform_headers(client, app)

        response = await client.get(
            AGING, headers=headers, params={"company_id": str(uuid.uuid4())}
        )

        assert response.status_code == 404, response.text

    async def test_the_report_says_which_day_it_measured_against(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The same invoice is in a different bucket tomorrow. A reader is
        entitled to know which day produced the buckets in front of
        them."""
        headers = await platform_headers(client, app)

        body = await report(client, headers)

        assert date.fromisoformat(body["as_of"]) == datetime.now(UTC).date()
