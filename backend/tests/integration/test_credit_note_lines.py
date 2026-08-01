"""Line-based credit notes, through ``InvoiceService`` against a real
database.

The domain rules are unit-tested in ``tests/unit/test_credit_notes.py``.
What can only be shown here is that the remainders are read from
documents already written: crediting a line twice narrows what is left
because the *second* call re-reads the first note, not because anything
remembered it. So these tests credit, then credit again, then ask for one
unit too many.

Driven through the service rather than the HTTP routes deliberately — the
routes for these operations are wired separately, and the service is the
boundary where "never allow an amount that cannot be traced to a line"
either holds or does not.
"""

import uuid
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.application.services.financial_audit_service import (
    AuditActor,
    FinancialAuditRecorder,
)
from blinkengage.application.services.invoice_service import InvoiceService
from blinkengage.application.services.ledger_service import LedgerService
from blinkengage.domain.credit_notes import CreditNoteSelectionError, CreditRefusal, LineSelection
from blinkengage.domain.exceptions import InvoiceStateError
from blinkengage.domain.invoicing import InvoiceStatus
from blinkengage.domain.money import currency_for, to_billable_amount, to_storage
from blinkengage.domain.usage import BillingPeriodStatus
from blinkengage.infrastructure.database.models.invoicing import (
    CreditNote,
    CreditNoteLine,
    Invoice,
    InvoiceLine,
)
from blinkengage.infrastructure.database.models.usage import BillingPeriod
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.repositories.event_outbox_repository import EventOutboxRepository
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
from blinkengage.infrastructure.repositories.ledger_repository import LedgerRepository
from blinkengage.infrastructure.repositories.usage_repository import (
    BillingPeriodRepository,
    UsagePeriodLineRepository,
)
from tests.integration.test_pricing_engine import company_id_of

#: Two priced lines, so "credit one line" can be seen not to touch the
#: other — the whole point of crediting by line.
MESSAGES = ("BILLABLE_MESSAGE", "Billable messages", "message", "4", "0.050000")
STORAGE = ("STORAGE_GB", "Storage", "GB-month", "2", "1.000000")


def build_service(session: AsyncSession) -> InvoiceService:
    """The same wiring ``api/deps.get_invoice_service`` builds.

    On one session, like production: the audit row and the ledger entry
    commit with the credit note or none of them exist.
    """
    return InvoiceService(
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
            entries=LedgerRepository(session), numbers=DocumentNumberRepository(session)
        ),
    )


async def issued_invoice(
    session: AsyncSession,
    company_id: uuid.UUID,
    *,
    lines: tuple[tuple[str, str, str, str, str], ...] = (MESSAGES,),
    currency: str = "USD",
    month: int = 3,
) -> Invoice:
    """An issued invoice with the given lines, written directly.

    Built rather than metered because these tests need **two priced
    lines** and a second invoice for another period, and only one metric
    has a meter today. Every field is what generation would have written:
    the line carries its own quantity, price and subtotal, and the
    invoice's total is the sum rounded to the currency exactly once.
    """
    period = BillingPeriod(
        company_id=company_id,
        period_start=datetime(2026, month, 1, tzinfo=UTC),
        period_end=datetime(2026, month + 1, 1, tzinfo=UTC),
        status=BillingPeriodStatus.CLOSED,
        closed_at=datetime(2026, month + 1, 1, tzinfo=UTC),
        currency=currency,
    )
    session.add(period)
    await session.flush()

    subtotals = [to_storage(Decimal(quantity) * Decimal(unit)) for *_, quantity, unit in lines]
    subtotal = to_storage(sum(subtotals, Decimal(0)))
    invoice = Invoice(
        company_id=company_id,
        billing_period_id=period.id,
        invoice_number=f"INV-2026-{month:06d}",
        status=InvoiceStatus.ISSUED,
        customer_name="Test Company",
        customer_slug="test-company",
        period_start=period.period_start,
        period_end=period.period_end,
        subtotal_amount=subtotal,
        total_amount=to_storage(to_billable_amount(subtotal, currency=currency_for(currency))),
        currency=currency,
        amount_paid=Decimal(0),
        amount_credited=Decimal(0),
        issued_at=datetime(2026, month + 1, 2, tzinfo=UTC),
    )
    session.add(invoice)
    await session.flush()
    session.add_all(
        [
            InvoiceLine(
                invoice_id=invoice.id,
                metric_code=code,
                metric_version=1,
                description=description,
                unit=unit,
                quantity=Decimal(quantity),
                included_quantity=Decimal(0),
                billable_quantity=Decimal(quantity),
                unit_amount=Decimal(unit_amount),
                currency=currency,
                subtotal=to_storage(Decimal(quantity) * Decimal(unit_amount)),
            )
            for code, description, unit, quantity, unit_amount in lines
        ]
    )
    await session.flush()
    return invoice


async def line_named(session: AsyncSession, invoice: Invoice, description: str) -> InvoiceLine:
    for line in await InvoiceLineRepository(session).for_invoice(invoice.id):
        if line.description == description:
            return line
    raise AssertionError(f"no line {description!r} on {invoice.invoice_number}")


@pytest.fixture
async def session(app: Any):
    factory = app.state.container.session_factory()
    async with factory() as db_session:
        yield db_session


@pytest.fixture
async def company(client: AsyncClient, owner_headers: dict) -> uuid.UUID:
    return uuid.UUID(await company_id_of(client, owner_headers))


class TestWhatIsCreditable:
    async def test_each_line_reports_what_it_has_left(
        self, session: AsyncSession, company: uuid.UUID
    ) -> None:
        invoice = await issued_invoice(session, company, lines=(MESSAGES, STORAGE))

        creditable = await build_service(session).creditable_lines(invoice.id)

        messages = next(
            line for line in creditable.lines if line.description == "Billable messages"
        )
        assert messages.billable_quantity == Decimal(4)
        assert messages.quantity_credited == Decimal(0)
        assert messages.quantity_creditable == Decimal(4)
        assert messages.amount_creditable == Decimal("0.20")
        assert messages.unit_amount == Decimal("0.05")
        # The invoice-level ceiling travels with the lines: 0.20 + 2.00.
        assert creditable.amount_creditable == Decimal("2.20")
        assert creditable.unattributed_credited_amount == Decimal(0)

    async def test_a_draft_reports_nothing_because_it_cannot_be_credited(
        self, session: AsyncSession, company: uuid.UUID
    ) -> None:
        """A read that described a draft as creditable would offer an
        operator a form whose submit button cannot work."""
        invoice = await issued_invoice(session, company)
        invoice.status = InvoiceStatus.DRAFT
        await session.flush()

        with pytest.raises(InvoiceStateError, match="still a draft"):
            await build_service(session).creditable_lines(invoice.id)


class TestCreditingOneLine:
    async def test_one_line_of_a_multi_line_invoice(
        self, session: AsyncSession, company: uuid.UUID
    ) -> None:
        """The correction is against the line that was wrong. The other
        line is untouched, and says so afterwards."""
        service = build_service(session)
        invoice = await issued_invoice(session, company, lines=(MESSAGES, STORAGE))
        messages = await line_named(session, invoice, "Billable messages")

        note = await service.issue_credit_note(
            invoice_id=invoice.id,
            selections=[LineSelection(messages.id, Decimal(2), reason="Sent during the outage")],
            reason="Duplicate messages after a meter fault",
        )

        assert note.total_amount == Decimal("0.10")
        assert note.currency == "USD"
        lines = await CreditNoteRepository(session).lines_for(note.id)
        assert len(lines) == 1
        # The price is the invoice line's, carried through untouched.
        assert lines[0].invoice_line_id == messages.id
        assert lines[0].unit_amount == Decimal("0.05")
        assert lines[0].description == "Billable messages"

        after = await service.creditable_lines(invoice.id)
        credited = next(line for line in after.lines if line.invoice_line_id == messages.id)
        untouched = next(line for line in after.lines if line.description == "Storage")
        assert credited.quantity_creditable == Decimal(2)
        assert untouched.quantity_creditable == Decimal(2)
        assert untouched.quantity_credited == Decimal(0)

    async def test_the_invoice_records_the_credit_without_changing(
        self, session: AsyncSession, company: uuid.UUID
    ) -> None:
        """The mandated rule: the invoice keeps saying what it said."""
        service = build_service(session)
        invoice = await issued_invoice(session, company, lines=(MESSAGES, STORAGE))
        messages = await line_named(session, invoice, "Billable messages")
        before = invoice.total_amount

        await service.issue_credit_note(
            invoice_id=invoice.id,
            selections=[LineSelection(messages.id, Decimal(2))],
            reason="Duplicate messages after a meter fault",
        )

        after = await service.get(invoice.id)
        assert after.total_amount == before
        assert after.amount_credited == Decimal("0.10")
        assert after.invoice_number == invoice.invoice_number

    async def test_a_full_credit_of_every_line_settles_the_invoice(
        self, session: AsyncSession, company: uuid.UUID
    ) -> None:
        """Otherwise a fully-credited invoice sits outstanding forever
        with nothing able to clear it."""
        service = build_service(session)
        invoice = await issued_invoice(session, company, lines=(MESSAGES, STORAGE))
        creditable = await service.creditable_lines(invoice.id)

        await service.issue_credit_note(
            invoice_id=invoice.id,
            selections=[
                LineSelection(line.invoice_line_id, line.quantity_creditable)
                for line in creditable.lines
            ],
            reason="Service credit agreed with the customer",
        )

        assert (await service.get(invoice.id)).status is InvoiceStatus.PAID


class TestExhaustingALine:
    async def test_partial_then_partial_again_then_refused(
        self, session: AsyncSession, company: uuid.UUID
    ) -> None:
        """Each call re-reads what earlier notes took off the line, so the
        third one is refused by the same arithmetic the first two used —
        nothing here is remembered between calls."""
        service = build_service(session)
        invoice = await issued_invoice(session, company)
        messages = await line_named(session, invoice, "Billable messages")

        await service.issue_credit_note(
            invoice_id=invoice.id,
            selections=[LineSelection(messages.id, Decimal(1))],
            reason="First correction",
        )
        await service.issue_credit_note(
            invoice_id=invoice.id,
            selections=[LineSelection(messages.id, Decimal(3))],
            reason="Second correction",
        )

        exhausted = (await service.creditable_lines(invoice.id)).lines[0]
        assert exhausted.quantity_credited == Decimal(4)
        assert exhausted.quantity_creditable == Decimal(0)
        assert exhausted.amount_creditable == Decimal(0)

        with pytest.raises(CreditNoteSelectionError) as refused:
            await service.issue_credit_note(
                invoice_id=invoice.id,
                selections=[LineSelection(messages.id, Decimal(1))],
                reason="One too many",
            )
        assert refused.value.reason is CreditRefusal.QUANTITY_EXCEEDS_REMAINDER
        assert refused.value.available == Decimal(0)

    async def test_the_refused_third_note_leaves_nothing_behind(
        self, session: AsyncSession, company: uuid.UUID
    ) -> None:
        """A refusal must not consume a credit note number or move the
        invoice — the number would leave a hole in the series."""
        service = build_service(session)
        invoice = await issued_invoice(session, company)
        messages = await line_named(session, invoice, "Billable messages")
        await service.issue_credit_note(
            invoice_id=invoice.id,
            selections=[LineSelection(messages.id, Decimal(4))],
            reason="Whole line",
        )
        credited_before = (await service.get(invoice.id)).amount_credited

        with pytest.raises(CreditNoteSelectionError):
            await service.issue_credit_note(
                invoice_id=invoice.id,
                selections=[LineSelection(messages.id, Decimal(1))],
                reason="One too many",
            )

        assert (await service.get(invoice.id)).amount_credited == credited_before
        assert len(await service.credit_notes_for(invoice.id)) == 1


class TestUntraceableSelections:
    async def test_a_line_from_another_invoice_is_refused(
        self, session: AsyncSession, company: uuid.UUID
    ) -> None:
        """The dangerous one: crediting March's invoice against April's
        line would leave both documents impossible to reconcile."""
        service = build_service(session)
        march = await issued_invoice(session, company, month=3)
        april = await issued_invoice(session, company, month=4)
        april_line = await line_named(session, april, "Billable messages")

        with pytest.raises(CreditNoteSelectionError) as refused:
            await service.issue_credit_note(
                invoice_id=march.id,
                selections=[LineSelection(april_line.id, Decimal(1))],
                reason="Wrong document",
            )

        assert refused.value.reason is CreditRefusal.LINE_NOT_ON_INVOICE
        assert refused.value.invoice_line_id == april_line.id
        assert len(await service.credit_notes_for(march.id)) == 0

    async def test_a_line_id_that_exists_nowhere_is_a_different_answer(
        self, session: AsyncSession, company: uuid.UUID
    ) -> None:
        """A stale console and an operator working on the wrong invoice
        are different problems, and only one of them is dangerous."""
        service = build_service(session)
        invoice = await issued_invoice(session, company)

        with pytest.raises(CreditNoteSelectionError) as refused:
            await service.issue_credit_note(
                invoice_id=invoice.id,
                selections=[LineSelection(uuid.uuid4(), Decimal(1))],
                reason="Nothing there",
            )

        assert refused.value.reason is CreditRefusal.UNKNOWN_LINE


class TestTheInvoiceCeiling:
    async def test_it_still_holds_when_the_lines_alone_would_allow_it(
        self, session: AsyncSession, company: uuid.UUID
    ) -> None:
        """An older whole-invoice credit note names no line. It reduces no
        line's remainder — attributing it would be a guess — but it did
        consume credit, so the invoice-level ceiling is what stops the same
        money being given back twice.
        """
        service = build_service(session)
        invoice = await issued_invoice(session, company)
        messages = await line_named(session, invoice, "Billable messages")
        # Written the way the old whole-invoice path wrote them:
        # `invoice_line_id` NULL, so nothing links it to a line.
        await CreditNoteRepository(session).add(
            CreditNote(
                company_id=company,
                invoice_id=invoice.id,
                credit_note_number="CN-2026-000900",
                customer_name=invoice.customer_name,
                subtotal_amount=Decimal("0.15"),
                total_amount=Decimal("0.15"),
                currency=invoice.currency,
                reason="Whole-invoice credit, before credits were line-based",
                issued_at=datetime(2026, 4, 3, tzinfo=UTC),
            ),
            [
                CreditNoteLine(
                    credit_note_id=uuid.uuid4(),
                    invoice_line_id=None,
                    description="Goodwill",
                    quantity=Decimal(1),
                    unit_amount=Decimal("0.15"),
                    currency=invoice.currency,
                    subtotal=Decimal("0.15"),
                )
            ],
        )
        await session.flush()

        creditable = await service.creditable_lines(invoice.id)

        # The line still offers everything it billed — nothing was
        # attributed to it — while the invoice has only 0.05 left.
        assert creditable.lines[0].quantity_creditable == Decimal(4)
        assert creditable.lines[0].amount_creditable == Decimal("0.20")
        assert creditable.amount_creditable == Decimal("0.05")
        assert creditable.unattributed_credited_amount == Decimal("0.15")

        with pytest.raises(CreditNoteSelectionError) as refused:
            await service.issue_credit_note(
                invoice_id=invoice.id,
                selections=[LineSelection(messages.id, Decimal(4))],
                reason="More than is left",
            )
        assert refused.value.reason is CreditRefusal.EXCEEDS_INVOICE_REMAINDER

        # What does fit is still allowed, so the unattributed credit costs
        # nobody the rest of their remedy.
        note = await service.issue_credit_note(
            invoice_id=invoice.id,
            selections=[LineSelection(messages.id, Decimal(1))],
            reason="What is left",
        )
        assert note.total_amount == Decimal("0.05")


class TestPreview:
    async def test_the_preview_is_what_issuing_produces(
        self, session: AsyncSession, company: uuid.UUID
    ) -> None:
        """The figures an operator approves are the figures stored. A
        preview computed a second way is worth less than none."""
        service = build_service(session)
        invoice = await issued_invoice(session, company, lines=(MESSAGES, STORAGE))
        messages = await line_named(session, invoice, "Billable messages")
        storage = await line_named(session, invoice, "Storage")
        selections = [
            LineSelection(messages.id, Decimal(3), reason="Meter fault"),
            LineSelection(storage.id, Decimal(1)),
        ]

        preview = await service.preview_credit_note(invoice_id=invoice.id, selections=selections)
        note = await service.issue_credit_note(
            invoice_id=invoice.id, selections=selections, reason="Agreed with the customer"
        )

        assert preview.total_amount == note.total_amount == Decimal("1.15")
        assert preview.subtotal_amount == note.subtotal_amount
        assert preview.currency == note.currency
        stored = {
            line.invoice_line_id: (line.quantity, line.unit_amount, line.subtotal)
            for line in await CreditNoteRepository(session).lines_for(note.id)
        }
        assert stored == {
            line.invoice_line_id: (line.quantity, line.unit_amount, line.subtotal)
            for line in preview.lines
        }

    async def test_the_preview_writes_nothing(
        self, session: AsyncSession, company: uuid.UUID
    ) -> None:
        service = build_service(session)
        invoice = await issued_invoice(session, company)
        messages = await line_named(session, invoice, "Billable messages")

        await service.preview_credit_note(
            invoice_id=invoice.id, selections=[LineSelection(messages.id, Decimal(2))]
        )

        assert await service.credit_notes_for(invoice.id) == []
        assert (await service.get(invoice.id)).amount_credited == Decimal(0)

    async def test_the_preview_refuses_exactly_what_issuing_refuses(
        self, session: AsyncSession, company: uuid.UUID
    ) -> None:
        """Otherwise an operator approves a selection and is told no when
        they commit it — the drift this repository already had in pricing
        quotes."""
        service = build_service(session)
        invoice = await issued_invoice(session, company)
        messages = await line_named(session, invoice, "Billable messages")
        selections = [LineSelection(messages.id, Decimal(5))]

        with pytest.raises(CreditNoteSelectionError) as previewed:
            await service.preview_credit_note(invoice_id=invoice.id, selections=selections)
        with pytest.raises(CreditNoteSelectionError) as issued:
            await service.issue_credit_note(
                invoice_id=invoice.id, selections=selections, reason="Too much"
            )

        assert previewed.value.reason is issued.value.reason
        assert str(previewed.value) == str(issued.value)


class TestAudit:
    async def test_the_audit_event_names_the_lines_it_credited(
        self, session: AsyncSession, company: uuid.UUID
    ) -> None:
        """A bare "0.15 was credited" is true and useless. Which lines, how
        much of each, and why, is what makes a credit note auditable."""
        service = build_service(session)
        invoice = await issued_invoice(session, company, lines=(MESSAGES, STORAGE))
        messages = await line_named(session, invoice, "Billable messages")

        note = await service.issue_credit_note(
            invoice_id=invoice.id,
            selections=[LineSelection(messages.id, Decimal(2), reason="Sent during the outage")],
            reason="Duplicate messages after a meter fault",
            actor=AuditActor(email="ops@example.com", name="Ops"),
        )

        events = await FinancialAuditRepository(session).for_entity(
            entity_type="credit_note", entity_id=note.id
        )
        assert len(events) == 1
        details = events[0].details
        assert details["credit_note_number"] == note.credit_note_number
        assert details["lines"] == [
            {
                "invoice_line_id": str(messages.id),
                "description": "Billable messages",
                "quantity": "2.000000",
                "unit_amount": "0.050000",
                "subtotal": "0.100000",
                "reason": "Sent during the outage",
            }
        ]
        # Attributable after the person has left: identity by value.
        assert events[0].actor_email == "ops@example.com"


class TestJordanianInvoice:
    async def test_a_dinar_credit_rounds_to_three_places(
        self, session: AsyncSession, company: uuid.UUID
    ) -> None:
        """The credit note rounds exactly as the invoice it corrects. A
        dinar note rounded to cents is wrong on every line."""
        service = build_service(session)
        invoice = await issued_invoice(
            session,
            company,
            lines=(("BILLABLE_MESSAGE", "Billable messages", "message", "300", "0.000700"),),
            currency="JOD",
        )
        messages = await line_named(session, invoice, "Billable messages")

        note = await service.issue_credit_note(
            invoice_id=invoice.id,
            selections=[LineSelection(messages.id, Decimal(150))],
            reason="Half the month was unusable",
        )

        assert note.currency == "JOD"
        assert note.subtotal_amount == Decimal("0.105")
        assert note.total_amount == Decimal("0.105")


class TestTheInvariantWithNoConstraintBehindIt:
    """``amount_credited`` may never exceed the invoice total.

    There is no database constraint on that column — not even ``>= 0`` — so
    these tests are the only thing between a bug and a customer's books.

    Issuing a credit note is a check-then-write: read what is still
    creditable, decide the selection fits, write the note and add to
    ``amount_credited``. Without a lock on the invoice row, two requests
    interleave between the read and the write and both are told yes. Eight
    concurrent notes against a $500 invoice each passed the remainder check
    and each was written, leaving $4,000 credited against a $500 document.

    ``InvoiceRepository.lock`` closes that, and the guarantee lives on
    PostgreSQL, where ``SELECT ... FOR UPDATE`` means something. These tests
    run on SQLite, where it does not — so what they assert is the property
    the lock preserves (a later credit sees what an earlier one took), not
    the concurrency itself, which is proven against PostgreSQL by hand.
    """

    async def test_a_second_credit_sees_what_the_first_one_took(
        self, session: AsyncSession, company: uuid.UUID
    ) -> None:
        service = build_service(session)
        invoice = await issued_invoice(session, company)
        line = await line_named(session, invoice, "Billable messages")
        everything = line.billable_quantity

        await service.issue_credit_note(
            invoice_id=invoice.id,
            selections=[LineSelection(invoice_line_id=line.id, quantity=everything)],
            reason="The whole line, credited once.",
        )

        with pytest.raises(CreditNoteSelectionError) as refused:
            await service.issue_credit_note(
                invoice_id=invoice.id,
                selections=[LineSelection(invoice_line_id=line.id, quantity=everything)],
                reason="The same line, credited again.",
            )

        assert refused.value.reason is CreditRefusal.QUANTITY_EXCEEDS_REMAINDER

    async def test_repeated_attempts_never_credit_past_the_total(
        self, session: AsyncSession, company: uuid.UUID
    ) -> None:
        service = build_service(session)
        invoice = await issued_invoice(session, company)
        line = await line_named(session, invoice, "Billable messages")

        for attempt in range(4):
            # Refusals are the point: only the first may land.
            with suppress(InvoiceStateError):
                await service.issue_credit_note(
                    invoice_id=invoice.id,
                    selections=[
                        LineSelection(invoice_line_id=line.id, quantity=line.billable_quantity)
                    ],
                    reason=f"Attempt {attempt}",
                )

        await session.refresh(invoice)
        assert invoice.amount_credited <= invoice.total_amount

    async def test_the_invoice_row_is_locked_before_the_remainders_are_read(
        self, session: AsyncSession, company: uuid.UUID
    ) -> None:
        """Structural, because the ordering is the whole guarantee.

        A lock taken *after* the remainders are read protects nothing: the
        decision has already been made against figures another transaction
        may have moved. Asserting the call order here is what stops a later
        refactor quietly reintroducing the race that eight concurrent
        requests exposed.
        """
        service = build_service(session)
        invoice = await issued_invoice(session, company)
        line = await line_named(session, invoice, "Billable messages")

        calls: list[str] = []
        repository = service._invoices  # noqa: SLF001 — pinning call order
        original_lock = repository.lock
        original_credited = service._credit_notes.credited_by_invoice_line  # noqa: SLF001

        async def watched_lock(invoice_id: uuid.UUID):
            calls.append("lock")
            return await original_lock(invoice_id)

        async def watched_credited(invoice_id: uuid.UUID):
            calls.append("read")
            return await original_credited(invoice_id)

        repository.lock = watched_lock  # type: ignore[method-assign]
        service._credit_notes.credited_by_invoice_line = watched_credited  # type: ignore[method-assign]  # noqa: SLF001
        try:
            await service.issue_credit_note(
                invoice_id=invoice.id,
                selections=[LineSelection(invoice_line_id=line.id, quantity=Decimal("1"))],
                reason="Order check.",
            )
        finally:
            repository.lock = original_lock  # type: ignore[method-assign]
            service._credit_notes.credited_by_invoice_line = original_credited  # type: ignore[method-assign]  # noqa: SLF001

        assert calls[0] == "lock", f"the remainders were read before the lock: {calls}"
