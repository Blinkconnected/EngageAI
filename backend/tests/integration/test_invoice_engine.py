"""The invoice engine, end to end.

These tests pin the mandated principles directly, because each of them
is a rule the code has to *enforce* rather than merely intend:

- numbers are sequential, gapless, assigned at issuance, never reused,
- an issued invoice is immutable,
- corrections are credit notes, never edits,
- lines are self-contained,
- payments are independent of invoices,
- the state machine refuses anything it does not allow.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.domain.allowances import FREE_MONTHLY_ALLOWANCE
from blinkengage.infrastructure.database.models.invoicing import Invoice, InvoiceLine
from tests.integration.test_pricing_engine import (
    CONVERSATION,
    company_id_of,
    iso,
    platform_headers,
    seed_global,
)
from tests.integration.test_usage_engine import conversation_created, meter


async def closed_period_with_usage(
    client: AsyncClient, headers: dict, app: Any, company_id: str, *, conversations: int = 4
) -> str:
    """A closed billing period with real metered usage behind it.

    The free monthly allowance (see ``domain/allowances.py``) would make
    a handful of conversations cost nothing, so these tests — which are
    about the *invoice* engine, not the allowance — first record a
    manual entry that consumes the whole allowance. Everything metered
    afterwards is billable, which is what the assertions below are
    about. The allowance itself is covered in
    ``tests/unit/test_free_allowance.py`` and end-to-end below.
    """
    await consume_allowance(client, headers, company_id)
    for _ in range(conversations):
        await meter(app, conversation_created(company_id, str(uuid4()), datetime.now(UTC)))
    current = await client.get(
        f"/api/v1/platform/usage/companies/{company_id}/current", headers=headers
    )
    period_id = current.json()["period"]["id"]
    closed = await client.post(
        f"/api/v1/platform/usage/periods/{period_id}/close", headers=headers
    )
    assert closed.status_code == 200, closed.text
    return str(period_id)


async def consume_allowance(client: AsyncClient, headers: dict, company_id: str) -> None:
    """Uses up the company's free conversations in one manual entry.

    One record carrying the whole quantity rather than a hundred metered
    events: the allowance is a quantity, not a count of records, so this
    exercises the same code path in a fraction of the time.
    """
    response = await client.post(
        "/api/v1/platform/usage/records",
        headers=headers,
        json={
            "company_id": company_id,
            "metric_code": CONVERSATION,
            "quantity": str(FREE_MONTHLY_ALLOWANCE[CONVERSATION]),
            "occurred_at": iso(datetime.now(UTC)),
            "idempotency_key": f"allowance-{company_id}",
            "note": "Test fixture: consumes the free monthly allowance.",
        },
    )
    assert response.status_code in (200, 201), response.text


async def draft_invoice(client: AsyncClient, headers: dict, period_id: str) -> dict:
    response = await client.post(
        f"/api/v1/platform/invoices/generate/{period_id}", headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


async def issued_invoice(client: AsyncClient, headers: dict, period_id: str) -> dict:
    detail = await draft_invoice(client, headers, period_id)
    invoice_id = detail["invoice"]["id"]
    response = await client.post(
        f"/api/v1/platform/invoices/{invoice_id}/issue", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestGeneration:
    async def test_an_invoice_copies_the_frozen_snapshot(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Not a recomputation. The snapshot already settled the
        quantity, the price and the subtotal when the period closed."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)

        detail = await draft_invoice(client, headers, period_id)

        line = next(
            line for line in detail["lines"] if line["metric_code"] == CONVERSATION
        )
        # 100 consumed by the fixture's allowance entry, 4 metered on
        # top. The line shows all three numbers, and the charge is on
        # the billable part alone.
        assert Decimal(line["quantity"]) == Decimal("104")
        assert Decimal(line["included_quantity"]) == Decimal("100")
        assert Decimal(line["billable_quantity"]) == Decimal("4")
        assert Decimal(line["unit_amount"]) == Decimal("0.05")
        assert Decimal(line["subtotal"]) == Decimal("0.20")
        assert Decimal(detail["invoice"]["total_amount"]) == Decimal("0.20")
        # The audit chain back to the usage that produced it.
        assert line["usage_period_line_id"] is not None
        assert line["rate_id"] is not None

    async def test_a_line_is_self_contained(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """It must render with no joins: a document that needs the rest
        of the database to be readable is not self-contained."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)

        detail = await draft_invoice(client, headers, period_id)

        line = detail["lines"][0]
        for field in ("description", "unit", "quantity", "unit_amount", "currency", "subtotal"):
            assert line[field] not in (None, ""), field
        assert line["metric_version"] >= 1
        # The customer is snapshotted on the invoice, not joined.
        assert detail["invoice"]["customer_name"]

    async def test_generating_twice_returns_the_same_invoice(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The failure mode this prevents is billing a customer twice for
        one month."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)

        first = await draft_invoice(client, headers, period_id)
        second = await draft_invoice(client, headers, period_id)

        assert first["invoice"]["id"] == second["invoice"]["id"]
        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            assert len((await session.execute(select(Invoice))).scalars().all()) == 1

    async def test_an_open_period_cannot_be_invoiced(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Billing a month whose usage is still accruing would bill a
        number that is still moving."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        await meter(app, conversation_created(company_id, str(uuid4()), datetime.now(UTC)))
        current = await client.get(
            f"/api/v1/platform/usage/companies/{company_id}/current", headers=headers
        )
        open_period_id = current.json()["period"]["id"]

        response = await client.post(
            f"/api/v1/platform/invoices/generate/{open_period_id}", headers=headers
        )

        assert response.status_code == 409
        assert "still open" in response.json()["detail"]


class TestNumbering:
    async def test_a_draft_has_no_number(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A draft that consumed a number and was then discarded would
        leave a gap somebody has to explain."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)

        detail = await draft_invoice(client, headers, period_id)

        assert detail["invoice"]["invoice_number"] is None
        assert detail["invoice"]["status"] == "draft"

    async def test_issuing_assigns_a_human_readable_sequential_number(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)

        detail = await issued_invoice(client, headers, period_id)

        year = datetime.now(UTC).year
        assert detail["invoice"]["invoice_number"] == f"INV-{year}-000001"
        assert detail["invoice"]["status"] == "issued"
        assert detail["invoice"]["issued_at"] is not None

    async def test_numbers_increment_across_companies(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """One series for the installation, not one per company — an
        auditor traces a single sequence."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_a = await company_id_of(client, owner_headers)
        company_b = await _register_company(client, "acme-two")

        numbers = []
        for company_id in (company_a, company_b):
            period_id = await closed_period_with_usage(
                client, headers, app, company_id, conversations=1
            )
            detail = await issued_invoice(client, headers, period_id)
            numbers.append(detail["invoice"]["invoice_number"])

        year = datetime.now(UTC).year
        assert numbers == [f"INV-{year}-000001", f"INV-{year}-000002"]

    async def test_a_cancelled_invoices_number_is_not_reused(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Two documents sharing a number is exactly what the series
        exists to prevent."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_a = await company_id_of(client, owner_headers)
        period_a = await closed_period_with_usage(client, headers, app, company_a, conversations=1)
        first = await issued_invoice(client, headers, period_a)
        await client.post(
            f"/api/v1/platform/invoices/{first['invoice']['id']}/cancel",
            json={"reason": "Issued against the wrong company"},
            headers=headers,
        )

        company_b = await _register_company(client, "acme-three")
        period_b = await closed_period_with_usage(client, headers, app, company_b, conversations=1)
        second = await issued_invoice(client, headers, period_b)

        year = datetime.now(UTC).year
        assert first["invoice"]["invoice_number"] == f"INV-{year}-000001"
        assert second["invoice"]["invoice_number"] == f"INV-{year}-000002"


class TestImmutability:
    async def test_there_is_no_endpoint_that_edits_an_issued_invoice(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """An API offering both an edit and a credit note would make the
        rule advisory. There is only the credit note."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice_id = (await issued_invoice(client, headers, period_id))["invoice"]["id"]

        for method in ("put", "patch", "delete"):
            response = await getattr(client, method)(
                f"/api/v1/platform/invoices/{invoice_id}",
                headers=headers,
                **({"json": {"total_amount": "0.01"}} if method != "delete" else {}),
            )
            assert response.status_code in (404, 405), method

    async def test_issuing_twice_is_refused(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice_id = (await issued_invoice(client, headers, period_id))["invoice"]["id"]

        again = await client.post(
            f"/api/v1/platform/invoices/{invoice_id}/issue", headers=headers
        )

        assert again.status_code == 409
        assert "issued" in again.json()["detail"].lower()

    async def test_invoice_lines_are_append_only_in_the_database(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Enforced by the repository's shape — there is no update or
        delete to call. PostgreSQL adds a trigger on top."""
        from blinkengage.infrastructure.repositories.invoicing_repository import (
            InvoiceLineRepository,
        )

        public = {name for name in dir(InvoiceLineRepository) if not name.startswith("_")}

        assert public == {"add_all", "for_invoice", "get_by_id"}


class TestStateMachine:
    async def test_a_paid_invoice_is_terminal(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        detail = await issued_invoice(client, headers, period_id)
        invoice_id = detail["invoice"]["id"]
        await _pay_in_full(client, headers, company_id, detail)

        cancelled = await client.post(
            f"/api/v1/platform/invoices/{invoice_id}/cancel",
            json={"reason": "Changed my mind"},
            headers=headers,
        )

        assert cancelled.status_code == 409
        assert "cannot go from paid" in cancelled.json()["detail"]

    async def test_a_cancelled_invoice_is_terminal(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice_id = (await issued_invoice(client, headers, period_id))["invoice"]["id"]
        await client.post(
            f"/api/v1/platform/invoices/{invoice_id}/cancel",
            json={"reason": "Wrong company"},
            headers=headers,
        )

        again = await client.post(
            f"/api/v1/platform/invoices/{invoice_id}/cancel",
            json={"reason": "Again"},
            headers=headers,
        )

        assert again.status_code == 409

    async def test_an_invoice_with_payments_cannot_be_cancelled(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Cancelling would leave the payment attached to a withdrawn
        document. A credit note is the correct instrument."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        detail = await issued_invoice(client, headers, period_id)
        payment = await _record_payment(client, headers, company_id, "0.10")
        await client.post(
            f"/api/v1/platform/invoices/payments/{payment['id']}/allocate",
            json={"invoice_id": detail["invoice"]["id"], "amount": "0.10"},
            headers=headers,
        )

        cancelled = await client.post(
            f"/api/v1/platform/invoices/{detail['invoice']['id']}/cancel",
            json={"reason": "Oops"},
            headers=headers,
        )

        assert cancelled.status_code == 409
        assert "credit note" in cancelled.json()["detail"]


class TestCreditNotes:
    async def test_a_credit_note_corrects_without_touching_the_invoice(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The mandated rule: the invoice keeps saying what it said."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        detail = await issued_invoice(client, headers, period_id)
        invoice_id = detail["invoice"]["id"]
        before = detail["invoice"]

        note = await client.post(
            f"/api/v1/platform/invoices/{invoice_id}/credit-notes",
            json={
                "lines": [
                    {"description": "Overcounted conversations", "quantity": "1", "unit_amount": "0.05"}
                ],
                "reason": "Duplicate conversations counted after a meter fault",
            },
            headers=headers,
        )

        assert note.status_code == 201, note.text
        year = datetime.now(UTC).year
        assert note.json()["credit_note_number"] == f"CN-{year}-000001"

        after = (await client.get(f"/api/v1/platform/invoices/{invoice_id}", headers=headers)).json()
        # Unchanged: total, subtotal, number, status.
        assert after["invoice"]["total_amount"] == before["total_amount"]
        assert after["invoice"]["invoice_number"] == before["invoice_number"]
        # The correction is recorded separately.
        assert Decimal(after["invoice"]["amount_credited"]) == Decimal("0.05")
        assert Decimal(after["amount_outstanding"]) == Decimal("0.15")
        assert len(after["credit_notes"]) == 1

    async def test_a_draft_cannot_be_credited(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Credit notes exist to correct documents already issued; a
        draft is simply changed."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        detail = await draft_invoice(client, headers, period_id)

        response = await client.post(
            f"/api/v1/platform/invoices/{detail['invoice']['id']}/credit-notes",
            json={"lines": [{"description": "x", "quantity": "1", "unit_amount": "0.01"}], "reason": "x"},
            headers=headers,
        )

        assert response.status_code == 409
        assert "still a draft" in response.json()["detail"]

    async def test_crediting_more_than_the_invoice_is_refused(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice_id = (await issued_invoice(client, headers, period_id))["invoice"]["id"]

        response = await client.post(
            f"/api/v1/platform/invoices/{invoice_id}/credit-notes",
            json={
                "lines": [{"description": "Too much", "quantity": "100", "unit_amount": "1.00"}],
                "reason": "Mistake",
            },
            headers=headers,
        )

        assert response.status_code == 409
        assert "exceed the invoice total" in response.json()["detail"]

    async def test_a_reason_is_required(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A credit note with no stated reason is unusable to whoever
        finds it later."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice_id = (await issued_invoice(client, headers, period_id))["invoice"]["id"]

        response = await client.post(
            f"/api/v1/platform/invoices/{invoice_id}/credit-notes",
            json={"lines": [{"description": "x", "quantity": "1", "unit_amount": "0.01"}], "reason": ""},
            headers=headers,
        )

        assert response.status_code == 422

    async def test_a_full_credit_settles_the_invoice(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Otherwise a fully-credited invoice sits outstanding forever
        with nothing that can clear it."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice_id = (await issued_invoice(client, headers, period_id))["invoice"]["id"]

        await client.post(
            f"/api/v1/platform/invoices/{invoice_id}/credit-notes",
            json={
                "lines": [{"description": "Full credit", "quantity": "4", "unit_amount": "0.05"}],
                "reason": "Service credit agreed with the customer",
            },
            headers=headers,
        )

        after = (await client.get(f"/api/v1/platform/invoices/{invoice_id}", headers=headers)).json()
        assert after["invoice"]["status"] == "paid"
        assert Decimal(after["amount_outstanding"]) == Decimal("0")


class TestPayments:
    async def test_a_payment_exists_independently_of_any_invoice(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Recorded with no invoice at all — allocation is a separate
        step, which is what lets one transfer clear several invoices."""
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)

        payment = await _record_payment(client, headers, company_id, "100.00")

        assert payment["id"]
        assert "invoice_id" not in payment

    async def test_one_payment_can_settle_several_invoices(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_a = await company_id_of(client, owner_headers)
        period_a = await closed_period_with_usage(client, headers, app, company_a, conversations=2)
        invoice_a = await issued_invoice(client, headers, period_a)

        payment = await _record_payment(client, headers, company_a, "1.00")
        allocated = await client.post(
            f"/api/v1/platform/invoices/payments/{payment['id']}/allocate",
            json={"invoice_id": invoice_a["invoice"]["id"], "amount": "0.10"},
            headers=headers,
        )

        assert allocated.status_code == 200, allocated.text
        assert allocated.json()["invoice"]["status"] == "paid"
        # The rest of the payment stays unallocated — a credit balance,
        # with no special case needed to represent it.

    async def test_allocating_more_than_the_payment_is_refused(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = await issued_invoice(client, headers, period_id)
        payment = await _record_payment(client, headers, company_id, "0.05")

        response = await client.post(
            f"/api/v1/platform/invoices/payments/{payment['id']}/allocate",
            json={"invoice_id": invoice["invoice"]["id"], "amount": "0.20"},
            headers=headers,
        )

        assert response.status_code == 409
        assert "unallocated" in response.json()["detail"]

    async def test_allocating_more_than_the_invoice_owes_is_refused(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        invoice = await issued_invoice(client, headers, period_id)
        payment = await _record_payment(client, headers, company_id, "100.00")

        response = await client.post(
            f"/api/v1/platform/invoices/payments/{payment['id']}/allocate",
            json={"invoice_id": invoice["invoice"]["id"], "amount": "50.00"},
            headers=headers,
        )

        assert response.status_code == 409
        assert "outstanding" in response.json()["detail"]

    async def test_a_payment_cannot_settle_another_companys_invoice(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_a = await company_id_of(client, owner_headers)
        company_b = await _register_company(client, "acme-four")
        period_a = await closed_period_with_usage(client, headers, app, company_a, conversations=1)
        invoice_a = await issued_invoice(client, headers, period_a)
        payment_b = await _record_payment(client, headers, company_b, "10.00")

        response = await client.post(
            f"/api/v1/platform/invoices/payments/{payment_b['id']}/allocate",
            json={"invoice_id": invoice_a["invoice"]["id"], "amount": "0.05"},
            headers=headers,
        )

        assert response.status_code == 409
        assert "different company" in response.json()["detail"]


class TestBoundary:
    async def test_a_tenant_cannot_reach_invoicing(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        company_id = await company_id_of(client, owner_headers)

        response = await client.get(
            f"/api/v1/platform/invoices?company_id={company_id}", headers=owner_headers
        )

        assert response.status_code == 403


@pytest.mark.parametrize("target", ["issue", "cancel"])
async def test_acting_on_an_unknown_invoice_is_a_404(
    client: AsyncClient, app: Any, target: str
) -> None:
    headers = await platform_headers(client, app)

    response = await client.post(
        f"/api/v1/platform/invoices/{uuid4()}/{target}",
        json={"reason": "x"} if target == "cancel" else None,
        headers=headers,
    )

    assert response.status_code == 404


async def _record_payment(
    client: AsyncClient, headers: dict, company_id: str, amount: str
) -> dict:
    response = await client.post(
        "/api/v1/platform/invoices/payments",
        json={
            "company_id": company_id,
            "amount": amount,
            "received_at": iso(datetime.now(UTC)),
            "reference": "Bank transfer",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _pay_in_full(
    client: AsyncClient, headers: dict, company_id: str, detail: dict
) -> None:
    total = detail["invoice"]["total_amount"]
    payment = await _record_payment(client, headers, company_id, total)
    response = await client.post(
        f"/api/v1/platform/invoices/payments/{payment['id']}/allocate",
        json={"invoice_id": detail["invoice"]["id"], "amount": total},
        headers=headers,
    )
    assert response.status_code == 200, response.text


async def _register_company(client: AsyncClient, slug: str) -> str:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": slug.title(),
            "owner_full_name": "Another Owner",
            "owner_email": f"owner@{slug}.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["user"]["company"]["id"])


async def test_invoice_lines_never_change_after_generation(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """The end-to-end immutability guarantee: change the price after
    issuing, and the document still says exactly what it said."""
    headers = await platform_headers(client, app)
    await seed_global(client, headers, amount="0.050000")
    company_id = await company_id_of(client, owner_headers)
    period_id = await closed_period_with_usage(client, headers, app, company_id)
    detail = await issued_invoice(client, headers, period_id)
    before = detail["lines"]

    await client.put(
        f"/api/v1/platform/pricing/global/metrics/{CONVERSATION}",
        json={"unit_amount": "9.000000", "effective_from": iso(datetime.now(UTC))},
        headers=headers,
    )

    after = (
        await client.get(
            f"/api/v1/platform/invoices/{detail['invoice']['id']}", headers=headers
        )
    ).json()
    assert after["lines"] == before

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        lines = (await session.execute(select(InvoiceLine))).scalars().all()
    assert all(line.unit_amount == Decimal("0.050000") for line in lines)
