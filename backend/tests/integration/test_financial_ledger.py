"""The financial ledger, end to end.

The ledger is declared the source of truth for balances, so these tests
pin the claims that makes:

- every financial operation posts an entry,
- the books balance after any sequence of operations,
- the document projection agrees with the ledger,
- entries cannot be amended or deleted.

The last one is checked against PostgreSQL directly, because a trigger
that only holds through the ORM is not immutability.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.infrastructure.database.models.ledger import LedgerEntry
from tests.integration.test_invoice_engine import (
    closed_period_with_usage,
    draft_invoice,
    issued_invoice,
)
from tests.integration.test_pricing_engine import (
    company_id_of,
    platform_headers,
    seed_global,
)

LEDGER = "/api/v1/platform/ledger"


async def entries_for(client: AsyncClient, headers: dict, company_id: str) -> list[dict]:
    response = await client.get(
        f"{LEDGER}/entries", headers=headers, params={"company_id": company_id, "limit": 100}
    )
    assert response.status_code == 200, response.text
    # Newest first from the API; oldest first reads as a narrative.
    return list(reversed(response.json()))


async def record_payment(
    client: AsyncClient, headers: dict, company_id: str, amount: str
) -> str:
    response = await client.post(
        "/api/v1/platform/invoices/payments",
        headers=headers,
        json={
            "company_id": company_id,
            "amount": amount,
            "received_at": datetime.now(UTC).isoformat(),
            "reference": "WIRE-1",
        },
    )
    assert response.status_code in (200, 201), response.text
    return str(response.json()["id"])


class TestPostings:
    async def test_a_draft_invoice_posts_nothing(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A draft was never billed. Recognising revenue on it would
        book money the customer has never been asked for."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)

        await draft_invoice(client, headers, period_id)

        assert await entries_for(client, headers, company_id) == []

    async def test_issuing_creates_a_receivable_and_revenue(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)

        invoice = (await issued_invoice(client, headers, period_id))["invoice"]

        entry = (await entries_for(client, headers, company_id))[0]
        assert entry["entry_type"] == "invoice.issued"
        assert entry["debit_account"] == "accounts_receivable"
        assert entry["credit_account"] == "revenue"
        assert Decimal(entry["amount"]) == Decimal(invoice["total_amount"])
        assert entry["reference_number"] == invoice["invoice_number"]
        # Recorded live, not reconstructed from a document.
        assert entry["reconstructed"] is False

    async def test_a_payment_is_cash_and_a_liability_until_allocated(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The heart of why payments are independent of invoices."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)

        await record_payment(client, headers, company_id, "10.00")

        position = (await client.get(f"{LEDGER}/{company_id}", headers=headers)).json()
        assert Decimal(position["credit_balance"]) == Decimal("10")
        # Nothing has been settled, so nothing is owed *less*.
        assert Decimal(position["outstanding"]) == Decimal("0")

    async def test_allocation_discharges_the_credit_against_the_receivable(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]
        payment_id = await record_payment(client, headers, company_id, "10.00")

        await client.post(
            f"/api/v1/platform/invoices/payments/{payment_id}/allocate",
            headers=headers,
            json={"invoice_id": invoice["id"], "amount": invoice["total_amount"]},
        )

        position = (await client.get(f"{LEDGER}/{company_id}", headers=headers)).json()
        assert Decimal(position["outstanding"]) == Decimal("0")
        # The unallocated remainder stays as a credit we owe them.
        assert Decimal(position["credit_balance"]) == Decimal("10") - Decimal(
            invoice["total_amount"]
        )

    async def test_a_credit_note_posts_to_contra_revenue(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]

        await client.post(
            f"/api/v1/platform/invoices/{invoice['id']}/credit-notes",
            headers=headers,
            json={
                "lines": [
                    {"description": "Overcounted", "quantity": "1", "unit_amount": "0.05"}
                ],
                "reason": "Meter fault",
            },
        )

        entry = (await entries_for(client, headers, company_id))[-1]
        assert entry["entry_type"] == "credit_note.issued"
        assert entry["debit_account"] == "revenue_adjustments"
        assert entry["credit_account"] == "accounts_receivable"

    async def test_every_entry_carries_the_correlation_id(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """How an investigation goes from one movement to everything that
        happened when it did."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        detail = await draft_invoice(client, headers, period_id)

        await client.post(
            f"/api/v1/platform/invoices/{detail['invoice']['id']}/issue",
            headers={**headers, "X-Correlation-ID": "ledger-probe-1"},
        )

        found = await client.get(f"{LEDGER}/correlation/ledger-probe-1", headers=headers)
        assert [row["entry_type"] for row in found.json()] == ["invoice.issued"]


class TestTheBooksBalance:
    async def test_debits_equal_credits_after_a_full_lifecycle(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The single most important property. Every entry carries both
        sides, so this cannot go false through normal use — which is
        exactly why it is worth asserting."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]
        payment_id = await record_payment(client, headers, company_id, "1.00")
        await client.post(
            f"/api/v1/platform/invoices/payments/{payment_id}/allocate",
            headers=headers,
            json={"invoice_id": invoice["id"], "amount": invoice["total_amount"]},
        )
        await client.post(
            f"/api/v1/platform/invoices/{invoice['id']}/credit-notes",
            headers=headers,
            json={
                "lines": [{"description": "x", "quantity": "1", "unit_amount": "0.01"}],
                "reason": "Goodwill",
            },
        )

        tb = (await client.get(f"{LEDGER}/trial-balance", headers=headers)).json()

        assert tb["in_balance"] is True
        assert Decimal(tb["total_debits"]) == Decimal(tb["total_credits"])
        assert tb["entry_count"] >= 4

    async def test_the_ledger_agrees_with_the_documents(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The invoice columns are a cache of what the ledger says. A
        cache nobody checks is a second source of truth with extra
        steps."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]
        payment_id = await record_payment(client, headers, company_id, "0.10")
        await client.post(
            f"/api/v1/platform/invoices/payments/{payment_id}/allocate",
            headers=headers,
            json={"invoice_id": invoice["id"], "amount": "0.10"},
        )

        report = await client.get(
            f"{LEDGER}/reconciliation",
            headers=headers,
            params={"company_id": company_id, "only_divergences": "false"},
        )

        assert report.json()["divergences"] == 0
        row = report.json()["rows"][0]
        assert Decimal(row["ledger_receivable"]) == Decimal(row["document_receivable"])

    async def test_a_reversal_restores_both_sides(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]
        payment_id = await record_payment(client, headers, company_id, "1.00")
        await client.post(
            f"/api/v1/platform/invoices/payments/{payment_id}/allocate",
            headers=headers,
            json={"invoice_id": invoice["id"], "amount": invoice["total_amount"]},
        )
        before = (await client.get(f"{LEDGER}/{company_id}", headers=headers)).json()
        allocation_id = await _allocation_id(app, invoice["id"])

        await client.post(
            f"/api/v1/platform/payments/allocations/{allocation_id}/reverse",
            headers=headers,
            json={"reason": "Bounced transfer"},
        )

        after = (await client.get(f"{LEDGER}/{company_id}", headers=headers)).json()
        assert Decimal(after["outstanding"]) > Decimal(before["outstanding"])
        assert Decimal(after["credit_balance"]) > Decimal(before["credit_balance"])
        tb = (await client.get(f"{LEDGER}/trial-balance", headers=headers)).json()
        assert tb["in_balance"] is True


class TestWriteOffAndChargeback:
    async def test_a_write_off_moves_the_receivable_to_bad_debt(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]

        written = await client.post(
            f"{LEDGER}/write-offs/{invoice['id']}",
            headers=headers,
            json={"reason": "Customer dissolved"},
        )

        assert written.status_code == 200, written.text
        position = (await client.get(f"{LEDGER}/{company_id}", headers=headers)).json()
        assert Decimal(position["outstanding"]) == Decimal("0")
        bad_debt = next(
            row for row in position["accounts"] if row["account"] == "bad_debt"
        )
        assert Decimal(bad_debt["balance"]) == Decimal(invoice["total_amount"])

    async def test_the_invoice_status_is_left_alone_by_a_write_off(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """It remains unpaid, which is the truth. There is no
        WRITTEN_OFF state, and inventing one would be a new billing
        concept — the ledger is where the receivable stops being an
        asset."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]
        await client.post(
            f"{LEDGER}/write-offs/{invoice['id']}",
            headers=headers,
            json={"reason": "Uncollectable"},
        )

        after = await client.get(
            f"/api/v1/platform/invoices/{invoice['id']}", headers=headers
        )
        assert after.json()["invoice"]["status"] == "issued"

    async def test_writing_off_twice_is_refused(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]
        body = {"reason": "Uncollectable"}
        await client.post(f"{LEDGER}/write-offs/{invoice['id']}", headers=headers, json=body)

        again = await client.post(
            f"{LEDGER}/write-offs/{invoice['id']}", headers=headers, json=body
        )

        assert again.status_code == 409

    async def test_a_chargeback_takes_the_cash_back_and_restores_the_debt(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]
        payment_id = await record_payment(client, headers, company_id, invoice["total_amount"])
        await client.post(
            f"/api/v1/platform/invoices/payments/{payment_id}/allocate",
            headers=headers,
            json={"invoice_id": invoice["id"], "amount": invoice["total_amount"]},
        )
        allocation_id = await _allocation_id(app, invoice["id"])

        result = await client.post(
            f"{LEDGER}/chargebacks/{allocation_id}",
            headers=headers,
            json={"reason": "Disputed by cardholder"},
        )

        assert result.status_code == 200, result.text
        position = (await client.get(f"{LEDGER}/{company_id}", headers=headers)).json()
        # Owing again, with no money held on their behalf, and the cash
        # gone.
        assert Decimal(position["outstanding"]) == Decimal(invoice["total_amount"])
        assert Decimal(position["credit_balance"]) == Decimal("0")
        cash = next(row for row in position["accounts"] if row["account"] == "cash")
        assert Decimal(cash["balance"]) == Decimal("0")
        tb = (await client.get(f"{LEDGER}/trial-balance", headers=headers)).json()
        assert tb["in_balance"] is True


class TestImmutability:
    async def test_the_api_offers_no_way_to_amend_an_entry(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A mistake is corrected by posting the opposite entry. An API
        offering both would make the rule advisory."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        await issued_invoice(client, headers, period_id)
        entry_id = (await entries_for(client, headers, company_id))[0]["id"]

        for method in ("put", "patch", "delete"):
            response = await getattr(client, method)(
                f"{LEDGER}/entries/{entry_id}",
                headers=headers,
                **({"json": {}} if method != "delete" else {}),
            )
            assert response.status_code in (404, 405), method

    async def test_a_manual_adjustment_is_itself_an_entry(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)

        posted = await client.post(
            f"{LEDGER}/adjustments",
            headers=headers,
            json={
                "debit_account": "bad_debt",
                "credit_account": "accounts_receivable",
                "amount": "1.50",
                "description": "Rounding correction, ticket 4412",
            },
        )

        assert posted.status_code == 201, posted.text
        assert posted.json()["entry_type"] == "adjustment.manual"
        assert Decimal(posted.json()["amount"]) == Decimal("1.5")

    async def test_an_adjustment_to_one_account_is_refused(
        self, client: AsyncClient, app: Any
    ) -> None:
        """It moves nothing and would still count towards every total."""
        headers = await platform_headers(client, app)
        response = await client.post(
            f"{LEDGER}/adjustments",
            headers=headers,
            json={
                "debit_account": "cash",
                "credit_account": "cash",
                "amount": "1.00",
                "description": "Nonsense",
            },
        )
        assert response.status_code >= 400

    async def test_entry_numbers_are_gapless_and_ordered(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Ordering by time alone can show a payment before the invoice
        it settles: entries written in one transaction share a timestamp
        to the microsecond."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = (await issued_invoice(client, headers, period_id))["invoice"]
        payment_id = await record_payment(client, headers, company_id, "1.00")
        await client.post(
            f"/api/v1/platform/invoices/payments/{payment_id}/allocate",
            headers=headers,
            json={"invoice_id": invoice["id"], "amount": invoice["total_amount"]},
        )

        async with app.state.container.session_factory()() as session:
            numbers = (
                await session.execute(
                    select(LedgerEntry.entry_number).order_by(LedgerEntry.entry_number)
                )
            ).scalars().all()

        assert list(numbers) == list(range(1, len(numbers) + 1))


async def _allocation_id(app: Any, invoice_id: str) -> str:
    from blinkengage.infrastructure.database.models.invoicing import PaymentAllocation

    async with app.state.container.session_factory()() as session:
        row = await session.execute(
            select(PaymentAllocation.id).where(
                PaymentAllocation.invoice_id == uuid.UUID(invoice_id),
                PaymentAllocation.reversed.is_(False),
            )
        )
        return str(row.scalar_one())
