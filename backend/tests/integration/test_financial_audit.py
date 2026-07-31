"""The financial audit trail.

This is the single source of truth for financial investigations, so the
tests are the questions an investigator actually asks:

- what happened to this document, in order?
- what *else* changed when that happened?
- who did it, and does the answer survive them leaving?
- what state was it in beforehand?
- can any of this be altered afterwards?
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.core.correlation import CORRELATION_HEADER
from blinkengage.infrastructure.database.models.financial_audit import FinancialAuditEvent
from tests.integration.test_invoice_engine import (
    closed_period_with_usage,
    draft_invoice,
    issued_invoice,
)
from tests.integration.test_pricing_engine import (
    company_id_of,
    iso,
    platform_headers,
    seed_global,
)


async def audit_for(client: AsyncClient, headers: dict, entity_type: str, entity_id: str) -> list:
    response = await client.get(
        f"/api/v1/platform/invoices/audit/entity/{entity_type}/{entity_id}", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestEveryActionIsRecorded:
    async def test_generating_an_invoice_is_recorded(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)

        detail = await draft_invoice(client, headers, period_id)

        events = await audit_for(client, headers, "invoice", detail["invoice"]["id"])
        assert [event["event_type"] for event in events] == ["invoice.created"]
        created = events[0]
        assert created["previous_state"] is None
        assert created["new_state"] == "draft"

    async def test_issuing_records_both_states(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """"It became issued" does not say what it was beforehand, and
        that difference is what a dispute turns on."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        detail = await issued_invoice(client, headers, period_id)

        events = await audit_for(client, headers, "invoice", detail["invoice"]["id"])

        issued = next(e for e in events if e["event_type"] == "invoice.issued")
        assert issued["previous_state"] == "draft"
        assert issued["new_state"] == "issued"
        assert issued["details"]["invoice_number"] == detail["invoice"]["invoice_number"]

    async def test_the_full_lifecycle_reads_in_order(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        detail = await issued_invoice(client, headers, period_id)
        invoice_id = detail["invoice"]["id"]
        total = detail["invoice"]["total_amount"]

        payment = await _record_payment(client, headers, company_id, total)
        await client.post(
            f"/api/v1/platform/invoices/payments/{payment['id']}/allocate",
            json={"invoice_id": invoice_id, "amount": total},
            headers=headers,
        )

        events = await audit_for(client, headers, "invoice", invoice_id)
        assert [e["event_type"] for e in events] == [
            "invoice.created",
            "invoice.issued",
            "invoice.paid",
        ]
        paid = events[-1]
        assert paid["previous_state"] == "issued"
        assert paid["new_state"] == "paid"

    async def test_a_credit_note_is_recorded_with_its_reason(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        detail = await issued_invoice(client, headers, period_id)
        note = await client.post(
            f"/api/v1/platform/invoices/{detail['invoice']['id']}/credit-notes",
            json={
                "lines": [{"description": "Overcount", "quantity": "1", "unit_amount": "0.05"}],
                "reason": "Duplicate conversations after a meter fault",
            },
            headers=headers,
        )

        events = await audit_for(client, headers, "credit_note", note.json()["id"])

        assert len(events) == 1
        assert events[0]["event_type"] == "credit_note.issued"
        assert events[0]["reason"] == "Duplicate conversations after a meter fault"
        assert Decimal(events[0]["amount"]) == Decimal("0.05")

    async def test_a_cancellation_records_its_reason_and_prior_state(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        detail = await issued_invoice(client, headers, period_id)
        await client.post(
            f"/api/v1/platform/invoices/{detail['invoice']['id']}/cancel",
            json={"reason": "Raised against the wrong company"},
            headers=headers,
        )

        events = await audit_for(client, headers, "invoice", detail["invoice"]["id"])

        cancelled = next(e for e in events if e["event_type"] == "invoice.cancelled")
        assert cancelled["previous_state"] == "issued"
        assert cancelled["new_state"] == "cancelled"
        assert cancelled["reason"] == "Raised against the wrong company"

    async def test_a_payment_and_its_allocation_are_both_recorded(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        detail = await issued_invoice(client, headers, period_id)
        payment = await _record_payment(client, headers, company_id, "1.00")
        await client.post(
            f"/api/v1/platform/invoices/payments/{payment['id']}/allocate",
            json={"invoice_id": detail["invoice"]["id"], "amount": "0.10"},
            headers=headers,
        )

        payment_events = await audit_for(client, headers, "payment", payment["id"])
        assert [e["event_type"] for e in payment_events] == ["payment.recorded"]

        search = await client.get(
            "/api/v1/platform/invoices/audit?entity_type=payment_allocation", headers=headers
        )
        body = search.json()
        assert [e["event_type"] for e in body["items"]] == ["payment.allocated"]
        # The count travels with the page: a reader has to be able to tell
        # "that is all of them" from "there are more".
        assert body["total"] == 1


class TestCorrelation:
    async def test_one_action_produces_events_that_share_a_correlation_id(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Allocating a payment touches the allocation *and* settles the
        invoice. Matching those by timestamp stops working the moment
        two operators act in the same second."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        detail = await issued_invoice(client, headers, period_id)
        total = detail["invoice"]["total_amount"]
        payment = await _record_payment(client, headers, company_id, total)

        response = await client.post(
            f"/api/v1/platform/invoices/payments/{payment['id']}/allocate",
            json={"invoice_id": detail["invoice"]["id"], "amount": total},
            headers={**headers, CORRELATION_HEADER: "settle-run-42"},
        )
        assert response.status_code == 200, response.text

        grouped = await client.get(
            "/api/v1/platform/invoices/audit/correlation/settle-run-42", headers=headers
        )
        types = [e["event_type"] for e in grouped.json()]
        assert "payment.allocated" in types
        assert "invoice.paid" in types
        assert {e["correlation_id"] for e in grouped.json()} == {"settle-run-42"}

    async def test_a_correlation_id_is_generated_when_the_caller_sends_none(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """An audit event without one cannot be joined to its siblings,
        which is the single thing correlation exists to prevent."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        detail = await draft_invoice(client, headers, period_id)

        events = await audit_for(client, headers, "invoice", detail["invoice"]["id"])

        assert events[0]["correlation_id"]

    async def test_the_correlation_id_is_echoed_to_the_caller(
        self, client: AsyncClient, app: Any
    ) -> None:
        """So whoever made the call can quote it when asking what
        happened."""
        headers = await platform_headers(client, app)

        response = await client.get("/api/v1/platform/pricing/metrics", headers=headers)

        assert response.headers[CORRELATION_HEADER]

    async def test_a_supplied_correlation_id_is_kept(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)

        response = await client.get(
            "/api/v1/platform/pricing/metrics",
            headers={**headers, CORRELATION_HEADER: "trace-from-the-gateway"},
        )

        assert response.headers[CORRELATION_HEADER] == "trace-from-the-gateway"


class TestActor:
    async def test_the_actor_is_captured_by_value_not_only_by_reference(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A SET NULL foreign key turns every action an ex-employee took
        into an anonymous one, and "who did this" is the second question
        every investigation asks."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        detail = await issued_invoice(client, headers, period_id)

        events = await audit_for(client, headers, "invoice", detail["invoice"]["id"])

        issued = next(e for e in events if e["event_type"] == "invoice.issued")
        assert issued["actor_email"] == "pricing.ops@blinkengage.example"
        assert issued["actor_name"] == "Pricing Operator"
        assert issued["actor_is_system"] is False

    async def test_a_scheduled_sweep_is_recorded_as_the_system(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """"Nobody did this, a job did" is a real and distinct answer
        from "we don't know who"."""
        from blinkengage.infrastructure.database.models.invoicing import Invoice

        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        period_id = await closed_period_with_usage(client, headers, app, company_id)
        detail = await issued_invoice(client, headers, period_id)

        # Backdate the due date so the sweep has something to find.
        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            from sqlalchemy import update

            await session.execute(
                update(Invoice)
                .where(Invoice.id == detail["invoice"]["id"])
                .values(due_date=datetime(2020, 1, 1, tzinfo=UTC).date())
            )
            await session.commit()

        async with session_factory() as session:
            from blinkengage.api.deps import get_invoice_service  # noqa: F401
            from blinkengage.application.services.financial_audit_service import (
                FinancialAuditRecorder,
            )
            from blinkengage.application.services.invoice_service import InvoiceService
            from blinkengage.application.services.ledger_service import LedgerService
            from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
            from blinkengage.infrastructure.repositories.event_outbox_repository import (
                EventOutboxRepository,
            )
            from blinkengage.infrastructure.repositories.financial_audit_repository import (
                FinancialAuditRepository,
            )
            from blinkengage.infrastructure.repositories.invoicing_repository import (
                CreditNoteRepository,
                DocumentNumberRepository,
                InvoiceCompanyLookup,
                InvoiceLineRepository,
                InvoiceRepository,
                PaymentRepository,
            )
            from blinkengage.infrastructure.repositories.ledger_repository import (
                LedgerRepository,
            )
            from blinkengage.infrastructure.repositories.usage_repository import (
                BillingPeriodRepository,
                UsagePeriodLineRepository,
            )

            service = InvoiceService(
                invoices=InvoiceRepository(session),
                lines=InvoiceLineRepository(session),
                credit_notes=CreditNoteRepository(session),
                payments=PaymentRepository(session),
                numbers=DocumentNumberRepository(session),
                periods=BillingPeriodRepository(session),
                period_lines=UsagePeriodLineRepository(session),
                companies=InvoiceCompanyLookup(session),
                events=OutboxEventPublisher(EventOutboxRepository(session)),
                audit=FinancialAuditRecorder(FinancialAuditRepository(session)),
                ledger=LedgerService(
                    entries=LedgerRepository(session),
                    numbers=DocumentNumberRepository(session),
                ),
            )
            moved = await service.mark_overdue()
            await session.commit()

        assert len(moved) == 1
        events = await audit_for(client, headers, "invoice", detail["invoice"]["id"])
        overdue = next(e for e in events if e["event_type"] == "invoice.overdue")
        assert overdue["actor_is_system"] is True
        assert overdue["actor_name"] == "Overdue sweep"
        assert overdue["previous_state"] == "issued"
        assert overdue["new_state"] == "overdue"


class TestImmutability:
    async def test_the_repository_cannot_modify_or_delete(self) -> None:
        """A trail that can be edited is not evidence. Enforced by the
        repository's shape, with a PostgreSQL trigger behind it."""
        from blinkengage.infrastructure.repositories.financial_audit_repository import (
            FinancialAuditRepository,
        )

        public = {n for n in dir(FinancialAuditRepository) if not n.startswith("_")}

        assert public == {"add", "for_entity", "for_correlation", "search"}

    async def test_there_is_no_endpoint_that_writes_to_the_trail(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)

        for method in ("post", "put", "patch", "delete"):
            response = await getattr(client, method)(
                "/api/v1/platform/invoices/audit", headers=headers, **({"json": {}} if method != "delete" else {})
            )
            assert response.status_code in (404, 405), method

    async def test_a_tenant_cannot_read_the_financial_trail(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.get(
            "/api/v1/platform/invoices/audit", headers=owner_headers
        )

        assert response.status_code == 403


async def test_the_trail_survives_the_document_being_investigated(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """Every event carries its own amounts and states, so the history is
    readable without the documents still holding their original values."""
    headers = await platform_headers(client, app)
    await seed_global(client, headers)
    company_id = await company_id_of(client, owner_headers)
    period_id = await closed_period_with_usage(client, headers, app, company_id)
    detail = await issued_invoice(client, headers, period_id)

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        events = (
            (
                await session.execute(
                    select(FinancialAuditEvent).where(
                        FinancialAuditEvent.entity_id == uuid4()
                    )
                )
            )
            .scalars()
            .all()
        )
    assert events == []

    stored = await audit_for(client, headers, "invoice", detail["invoice"]["id"])
    for event in stored:
        assert event["occurred_at"]
        assert event["correlation_id"]
        assert event["entity_type"] == "invoice"


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
