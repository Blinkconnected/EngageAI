"""The customer statement: a running balance over the ledger.

Every other figure this API reports is one the engine already computed
and froze. A running balance is the exception — it is derived on read,
per request — so these tests pin the things that can only go wrong here:

- the rows arrive oldest first, or the balance beside them is not a
  balance,
- the balance uses the account's own direction, so the statement and the
  trial balance never disagree,
- the window's opening balance holds everything before it,
- paging does not restart the balance halfway down,
- one currency per statement, named, and never summed with another.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from httpx import AsyncClient

from tests.integration.test_financial_ledger import record_payment
from tests.integration.test_invoice_engine import closed_period_with_usage, issued_invoice
from tests.integration.test_jordan_billing import register as register_jordanian
from tests.integration.test_pricing_engine import (
    company_id_of,
    platform_headers,
    seed_global,
)

LEDGER = "/api/v1/platform/ledger"
STATEMENT = f"{LEDGER}/statement"


async def statement_for(client: AsyncClient, headers: dict, company_id: str, **params: Any) -> dict:
    response = await client.get(f"{STATEMENT}/{company_id}", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return dict(response.json())


async def billed_and_part_paid(
    client: AsyncClient, headers: dict, app: Any, company_id: str
) -> dict:
    """One company's whole story, in three entries.

    An issued invoice, money arriving, and that money being applied — the
    smallest sequence that touches both a debit-normal account
    (``accounts_receivable``) and a credit-normal one
    (``customer_credit``), which is what makes the sign convention
    testable at all.
    """
    period_id = await closed_period_with_usage(client, headers, app, company_id)
    invoice = (await issued_invoice(client, headers, period_id))["invoice"]
    payment_id = await record_payment(client, headers, company_id, "1.00")
    allocated = await client.post(
        f"/api/v1/platform/invoices/payments/{payment_id}/allocate",
        headers=headers,
        json={"invoice_id": invoice["id"], "amount": invoice["total_amount"]},
    )
    assert allocated.status_code == 200, allocated.text
    return dict(invoice)


class TestOrder:
    async def test_the_statement_reads_oldest_first(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The opposite of ``/entries``, deliberately. A running balance
        only reads as a balance if the rows arrive in the order they
        happened."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        await billed_and_part_paid(client, headers, app, company_id)

        entries = (
            await client.get(
                f"{LEDGER}/entries", headers=headers, params={"company_id": company_id}
            )
        ).json()
        newest_first = [
            row["entry_number"]
            for row in entries
            if "accounts_receivable" in (row["debit_account"], row["credit_account"])
        ]

        page = await statement_for(client, headers, company_id)

        assert [row["entry"]["entry_number"] for row in page["rows"]] == list(
            reversed(newest_first)
        )

    async def test_rows_are_ordered_by_entry_number_not_by_timestamp(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Entries written in one transaction share a timestamp to the
        microsecond, so ordering by time alone can put a payment above the
        invoice it settles — and the balance beside it would then move
        backwards."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        await billed_and_part_paid(client, headers, app, company_id)

        page = await statement_for(client, headers, company_id)

        numbers = [row["entry"]["entry_number"] for row in page["rows"]]
        assert numbers == sorted(numbers)


class TestTheRunningBalance:
    async def test_the_balance_carries_down_the_page(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        invoice = await billed_and_part_paid(client, headers, app, company_id)
        total = Decimal(invoice["total_amount"])

        page = await statement_for(client, headers, company_id)

        # Billed, then settled: what they owe goes up by the invoice and
        # back down by the allocation.
        billed, settled = page["rows"]
        assert billed["entry"]["entry_type"] == "invoice.issued"
        assert Decimal(billed["debit"]) == total and billed["credit"] is None
        assert Decimal(billed["balance"]) == total
        assert settled["entry"]["entry_type"] == "payment.allocated"
        assert Decimal(settled["credit"]) == total and settled["debit"] is None
        assert Decimal(settled["balance"]) == Decimal("0")
        assert Decimal(page["closing_balance"]) == Decimal("0")

    async def test_the_closing_balance_is_what_the_company_position_says(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The statement and ``GET /{company_id}`` derive the same figure
        two different ways. A customer reading one and an operator reading
        the other must not see different money."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        await issued_invoice(client, headers, period_id)

        page = await statement_for(client, headers, company_id)
        position = (await client.get(f"{LEDGER}/{company_id}", headers=headers)).json()

        assert Decimal(page["closing_balance"]) == Decimal(position["outstanding"])

    async def test_a_credit_normal_account_runs_the_other_way(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The reason the row delta goes through ``balance_of`` instead of
        a local sign rule. ``customer_credit`` is a liability: money
        arriving *credits* it and that is an increase. A statement that
        assumed debit-positive would report every held balance negative,
        and would disagree with the trial balance on the same rows.
        """
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        invoice = await billed_and_part_paid(client, headers, app, company_id)

        page = await statement_for(client, headers, company_id, account="customer_credit")
        position = (await client.get(f"{LEDGER}/{company_id}", headers=headers)).json()

        received, applied = page["rows"]
        # Money arriving is credited to the liability, and the balance is
        # positive — they are owed it.
        assert received["entry"]["entry_type"] == "payment.received"
        assert received["credit"] is not None and received["debit"] is None
        assert Decimal(received["balance"]) == Decimal("1.00")
        # Applying it to an invoice debits the liability back down.
        assert applied["entry"]["entry_type"] == "payment.allocated"
        assert applied["debit"] is not None and applied["credit"] is None
        assert Decimal(applied["balance"]) == Decimal("1.00") - Decimal(invoice["total_amount"])
        assert Decimal(page["closing_balance"]) == Decimal(position["credit_balance"])

    async def test_the_account_being_run_down_is_named_in_the_response(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A balance with no account beside it is not an answer: the
        receivable and the credit balance run in opposite directions."""
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)

        default = await statement_for(client, headers, company_id)
        asked = await statement_for(client, headers, company_id, account="cash")

        assert default["account"] == "accounts_receivable"
        assert asked["account"] == "cash"

    async def test_an_entry_touching_neither_side_is_not_on_the_statement(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A payment arriving moves cash and a liability; it does not
        touch the receivable, and a row with a flat balance would invite
        the reader to look for the movement that is not there."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        await record_payment(client, headers, company_id, "5.00")

        page = await statement_for(client, headers, company_id)

        assert page["rows"] == []
        assert page["total"] == 0
        assert Decimal(page["closing_balance"]) == Decimal("0")


class TestTheWindow:
    async def test_the_opening_balance_holds_everything_before_the_window(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Otherwise a statement for March opens at zero and tells a
        customer who has owed money since January that they owe nothing.
        """
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        invoice = await billed_and_part_paid(client, headers, app, company_id)
        everything = await statement_for(client, headers, company_id)
        allocation = everything["rows"][-1]

        page = await statement_for(
            client, headers, company_id, since=allocation["entry"]["occurred_at"]
        )

        # The invoice is behind the window, so it is in the opening
        # balance rather than on the page.
        assert Decimal(page["opening_balance"]) == Decimal(invoice["total_amount"])
        assert [row["entry"]["id"] for row in page["rows"]] == [allocation["entry"]["id"]]
        assert Decimal(page["closing_balance"]) == Decimal("0")

    async def test_the_window_is_half_open(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """``[since, until)``, like effective dating and billing periods
        everywhere else, so an entry on a boundary belongs to exactly one
        of two adjacent windows instead of being counted twice."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        await billed_and_part_paid(client, headers, app, company_id)
        everything = await statement_for(client, headers, company_id)
        boundary = everything["rows"][-1]["entry"]["occurred_at"]

        from_boundary = await statement_for(client, headers, company_id, since=boundary)
        to_boundary = await statement_for(client, headers, company_id, until=boundary)

        assert boundary in [row["entry"]["occurred_at"] for row in from_boundary["rows"]]
        assert boundary not in [row["entry"]["occurred_at"] for row in to_boundary["rows"]]

    async def test_a_window_that_can_never_contain_anything_is_refused(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A swapped pair of arguments would otherwise return a
        confidently empty statement, which in a finance console is
        indistinguishable from a customer with no history."""
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)

        response = await client.get(
            f"{STATEMENT}/{company_id}",
            headers=headers,
            params={
                "since": datetime(2026, 3, 1, tzinfo=UTC).isoformat(),
                "until": datetime(2026, 2, 1, tzinfo=UTC).isoformat(),
            },
        )

        assert response.status_code == 422

    async def test_a_naive_instant_is_refused(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """ "1 March" is a different moment in Amman and Los Angeles, and
        the difference decides which entries are in the opening balance
        rather than on the page. Guessing one would be a silently wrong
        statement."""
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)

        response = await client.get(
            f"{STATEMENT}/{company_id}",
            headers=headers,
            params={"since": "2026-03-01T00:00:00"},
        )

        assert response.status_code == 422


class TestPagination:
    async def test_the_total_counts_the_window_not_the_page(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A list with limit/offset and no total cannot render honest
        pagination — there is nothing to say how many pages there are."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        await billed_and_part_paid(client, headers, app, company_id)

        page = await statement_for(client, headers, company_id, limit=1)

        assert len(page["rows"]) == 1
        assert page["total"] == 2
        assert page["limit"] == 1
        assert page["offset"] == 0

    async def test_paging_does_not_restart_the_running_balance(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Page two carries on from where page one stopped. Restarting at
        the window's opening would print a balance the customer never
        held, on a document they are being asked to pay against."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        await billed_and_part_paid(client, headers, app, company_id)
        everything = await statement_for(client, headers, company_id)

        first = await statement_for(client, headers, company_id, limit=1, offset=0)
        second = await statement_for(client, headers, company_id, limit=1, offset=1)

        assert [row["balance"] for row in first["rows"] + second["rows"]] == [
            row["balance"] for row in everything["rows"]
        ]
        # What the second page opens from is what the first page closed
        # at — the figure a statement prints as "brought forward".
        assert second["page_opening_balance"] == first["rows"][-1]["balance"]
        assert first["page_opening_balance"] == everything["opening_balance"]

    async def test_the_closing_balance_is_the_windows_not_the_pages(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A closing balance that stopped at the end of page one would
        make "what do they owe now" depend on the page size."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        await billed_and_part_paid(client, headers, app, company_id)

        page = await statement_for(client, headers, company_id, limit=1)
        position = (await client.get(f"{LEDGER}/{company_id}", headers=headers)).json()

        assert Decimal(page["closing_balance"]) == Decimal(position["outstanding"])
        assert Decimal(page["rows"][-1]["balance"]) != Decimal(page["closing_balance"])


class TestCurrency:
    async def test_every_amount_crosses_the_wire_as_a_string(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A JSON number becomes a float in the browser, which
        reintroduces exactly the drift ``Decimal`` exists to prevent."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        await billed_and_part_paid(client, headers, app, company_id)

        response = await client.get(f"{STATEMENT}/{company_id}", headers=headers)

        body = json.loads(response.text)
        for figure in ("opening_balance", "page_opening_balance", "closing_balance"):
            assert isinstance(body[figure], str), figure
        for row in body["rows"]:
            assert isinstance(row["balance"], str)
            assert isinstance(row["entry"]["amount"], str)
            assert row["debit"] is None or isinstance(row["debit"], str)
            assert row["credit"] is None or isinstance(row["credit"], str)

    async def test_a_dinar_company_gets_a_dinar_statement(
        self, client: AsyncClient, app: Any
    ) -> None:
        """The currency is taken from the company's own entries, not from
        the installation default — reading the default here would state a
        Jordanian balance in dollars."""
        headers = await platform_headers(client, app)
        company_id = (await register_jordanian(client, app))["user"]["company"]["id"]
        await record_payment(client, headers, company_id, "10.00")

        page = await statement_for(client, headers, company_id, account="customer_credit")

        assert page["currency"] == "JOD"
        assert page["available_currencies"] == ["JOD"]
        assert Decimal(page["closing_balance"]) == Decimal("10")

    async def test_another_currencys_rows_are_absent_rather_than_added(
        self, client: AsyncClient, app: Any
    ) -> None:
        """Nothing converts and no exchange rate is stored, so a balance
        run across currencies would be a number with no meaning. Asking
        for a currency this company does not bill in yields an empty
        statement — and ``available_currencies`` says what it does bill
        in, so the omission is visible rather than silent."""
        headers = await platform_headers(client, app)
        company_id = (await register_jordanian(client, app))["user"]["company"]["id"]
        await record_payment(client, headers, company_id, "10.00")

        page = await statement_for(
            client, headers, company_id, account="customer_credit", currency="USD"
        )

        assert page["currency"] == "USD"
        assert page["rows"] == []
        assert page["total"] == 0
        assert Decimal(page["closing_balance"]) == Decimal("0")
        assert page["available_currencies"] == ["JOD"]

    async def test_a_currency_this_build_cannot_bill_in_is_refused(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Rather than defaulting. Quietly answering about dollars because
        "EUR" was not recognised is how a statement states the wrong
        money."""
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)

        response = await client.get(
            f"{STATEMENT}/{company_id}", headers=headers, params={"currency": "EUR"}
        )

        assert response.status_code == 422


class TestBoundary:
    async def test_the_statement_route_is_declared_above_the_company_route(self, app: Any) -> None:
        """``/{company_id}`` matches anything, so a literal path
        registered after it never runs. This collision has shipped twice
        in this repository."""
        paths = [getattr(route, "path", "") for route in app.routes]

        assert paths.index("/api/v1/platform/ledger/statement/{company_id}") < paths.index(
            "/api/v1/platform/ledger/{company_id}"
        )

    async def test_a_tenant_cannot_read_a_statement(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """Platform authority, inherited from the router. A tenant reading
        `/platform/*` at all is the failure this gate exists for."""
        company_id = await company_id_of(client, owner_headers)

        response = await client.get(f"{STATEMENT}/{company_id}", headers=owner_headers)

        assert response.status_code == 403

    async def test_a_read_only_operator_may_read_a_statement(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Auditing what a customer is charged is the main reason to grant
        read-only platform access at all; a GET must not be caught by the
        write gate."""
        from sqlalchemy import update

        from blinkengage.infrastructure.database.models.user import User

        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)
        async with app.state.container.session_factory()() as session:
            await session.execute(
                update(User)
                .where(User.is_platform_admin.is_(True), User.company_id.is_(None))
                .values(platform_read_only=True)
            )
            await session.commit()

        response = await client.get(f"{STATEMENT}/{company_id}", headers=headers)

        assert response.status_code == 200
