"""Collections: reminders, dunning, suspension and reinstatement.

See ``docs/architecture/billing.md``.

The sweep that runs daily and does four things, in this order:

1. marks issued invoices overdue once their due date has passed;
2. sends whichever dunning notices each open invoice is owed;
3. suspends companies whose sequence has run out;
4. reinstates companies that have paid up.

Reinstatement runs in the same pass as suspension, deliberately. A
customer who pays at 09:00 must not stay locked out until a separate job
happens to run — and a reinstatement path that only exists inside the
payment handler is one that never fires when the payment arrives by bank
transfer and is keyed in by hand.

Two rules the whole engine rests on.

**A notice is sent once.** ``(invoice_id, stage)`` is unique, so a sweep
that runs twice, or a worker that dies mid-pass, cannot send a customer
a second final notice. The constraint does the work, not a status flag
somebody has to remember to check.

**Suspension never touches compliance status.** ``billing_status`` and
``status`` are separate columns for exactly this reason: a company
suspended by an operator for a compliance breach must not be quietly
reinstated because an invoice got paid.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import ColumnElement, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.application.services.billing_contacts import (
    BILLING_PERMISSION,
    billing_contact_ids,
)
from blinkengage.application.services.financial_audit_service import (
    AuditActor,
    FinancialAuditRecorder,
)
from blinkengage.application.services.invoice_service import InvoiceService
from blinkengage.application.services.notification_service import NotificationService
from blinkengage.domain.collections import (
    DEFAULT_DUNNING_POLICY,
    BillingStatus,
    DunningStage,
    DunningStep,
    next_stage_date,
    stages_due,
    status_for,
)
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.domain.financial_audit import FinancialEntityType, FinancialEventType
from blinkengage.domain.invoicing import OPEN_STATES
from blinkengage.domain.money import format_amount, to_storage, total, zero
from blinkengage.infrastructure.database.models.collections import DunningNotice
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.invoicing import Invoice

#: Notification type for every dunning notice. One type rather than one
#: per stage, so a company that turns billing reminders off in its
#: Notifications settings turns off all of them — a customer who
#: silenced "first notice" but still receives "final notice" would
#: reasonably say they were never warned.
NOTIFICATION_TYPE = "billing.dunning"

#: Who hears about an unpaid invoice. Everybody who can act on it, and
#: nobody who cannot: an agent handling conversations has no use for a
#: payment reminder and no way to act on one. Defined once, in
#: ``billing_contacts``, because everything billing sends a customer has to
#: reach the same people.
_BILLING_PERMISSION = BILLING_PERMISSION


@dataclass(slots=True)
class CompanyStanding:
    """One company's position, as a finance team reads it.

    ``amount_outstanding`` is in that company's own billing currency and is
    **never** summable across rows — nothing converts, and a total across
    companies billing in dollars and dinars is a number that means nothing.
    """

    company_id: uuid.UUID
    company_name: str
    #: The company's own billing currency. Carried on every row because
    #: this list spans companies — some billed in dollars, some in dinars
    #: — and an amount with no currency beside it in a mixed list is an
    #: invitation to add them together.
    currency: str
    billing_status: BillingStatus
    billing_suspended_at: datetime | None
    never_auto_suspend: bool
    open_invoices: int
    overdue_invoices: int
    amount_outstanding: Decimal
    next_action_on: date | None


class AgingBucket(StrEnum):
    """How overdue an open invoice is, in the bands a debtors report uses.

    Stable identifiers rather than positions in a list: a console keys its
    columns off these, and renaming one silently moves a column's meaning.
    """

    #: Issued, not yet past its due date. Owed, but not late.
    CURRENT = "current"
    DAYS_1_30 = "days_1_30"
    DAYS_31_60 = "days_31_60"
    DAYS_61_90 = "days_61_90"
    DAYS_90_PLUS = "days_90_plus"


@dataclass(frozen=True, slots=True)
class AgingBand:
    """One band of the policy: a bucket and the ages that fall in it."""

    bucket: AgingBucket
    #: Inclusive bounds, in whole days past the due date. ``None`` is
    #: open-ended — genuinely unbounded, not a sentinel number somebody
    #: eventually reaches.
    from_days: int | None
    to_days: int | None


#: The bands, in the order a report reads. Declared as data, once, so the
#: service, the response and any console all describe the same policy —
#: three places each re-deriving "which bucket is this" is three places
#: that can disagree.
#:
#: The bands are **contiguous and non-overlapping**. The requirement names
#: "61-90" and "90+", which both claim day 90; an invoice belonging to two
#: buckets would make the bucket counts stop summing to the total, so day
#: 90 belongs to the band that names it and the open-ended band starts at
#: 91.
AGING_BANDS: tuple[AgingBand, ...] = (
    AgingBand(bucket=AgingBucket.CURRENT, from_days=None, to_days=0),
    AgingBand(bucket=AgingBucket.DAYS_1_30, from_days=1, to_days=30),
    AgingBand(bucket=AgingBucket.DAYS_31_60, from_days=31, to_days=60),
    AgingBand(bucket=AgingBucket.DAYS_61_90, from_days=61, to_days=90),
    AgingBand(bucket=AgingBucket.DAYS_90_PLUS, from_days=91, to_days=None),
)


def bucket_for(days_overdue: int) -> AgingBucket:
    """Which band an age falls in. A pure function of one integer, so the
    boundaries are unit-testable without a database behind them."""
    for band in AGING_BANDS:
        if (band.from_days is None or days_overdue >= band.from_days) and (
            band.to_days is None or days_overdue <= band.to_days
        ):
            return band.bucket
    # Unreachable while the bands stay contiguous and open at both ends.
    # Kept so a future edit that leaves a gap fails loudly here rather
    # than quietly dropping invoices out of the report.
    raise ValueError(f"No aging band covers {days_overdue} days overdue.")


@dataclass(frozen=True, slots=True)
class AgingBucketTotal:
    """One bucket, within one currency.

    ``amount_outstanding`` is only ever added to other buckets **of the
    same currency**. That is why this type is never handed out on its own.
    """

    bucket: AgingBucket
    from_days: int | None
    to_days: int | None
    invoice_count: int
    amount_outstanding: Decimal


@dataclass(frozen=True, slots=True)
class CurrencyAging:
    """One currency's aging, and the only level at which a total exists.

    Nothing converts and no exchange rate is stored, so a figure spanning
    dollars and dinars could not be computed even if somebody wanted it.
    Grouping by currency is what makes that structural rather than a
    convention somebody remembers: the total lives *inside* a currency, so
    there is nowhere for a cross-currency sum to be written.
    """

    currency: str
    #: Every band, always — including the empty ones. A bucket that
    #: vanishes when nothing is in it is indistinguishable from a bucket
    #: the caller forgot to handle, and it makes a console's column
    #: disappear rather than read zero.
    buckets: tuple[AgingBucketTotal, ...]
    invoice_count: int
    total_outstanding: Decimal


@dataclass(frozen=True, slots=True)
class AgingReport:
    """Open receivables by age. Deliberately has **no** total of its own.

    ``currencies`` is the whole payload: there is no installation-wide
    amount here, because there is no honest way to produce one.
    """

    #: The day the ages were measured against. Reported rather than left
    #: implicit — an aging report read tomorrow describes a different set
    #: of buckets, and a reader is entitled to know which day it is.
    as_of: date
    currencies: tuple[CurrencyAging, ...]


@dataclass
class CollectionsRun:
    """What one sweep did. Returned rather than only logged, so the task
    that calls it can report and a test can assert."""

    marked_overdue: int = 0
    notices_sent: int = 0
    suspended: list[uuid.UUID] = field(default_factory=list)
    reinstated: list[uuid.UUID] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.marked_overdue} marked overdue, {self.notices_sent} notices sent, "
            f"{len(self.suspended)} suspended, {len(self.reinstated)} reinstated"
        )


class CollectionsService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        invoice_service: InvoiceService,
        notifications: NotificationService,
        audit: FinancialAuditRecorder,
        policy: tuple[DunningStep, ...] = DEFAULT_DUNNING_POLICY,
    ) -> None:
        self._session = session
        self._invoice_service = invoice_service
        self._notifications = notifications
        self._audit = audit
        self._policy = policy

    # --- the sweep ---------------------------------------------------

    async def run(self, *, today: date | None = None) -> CollectionsRun:
        reference_day = today or datetime.now(UTC).date()
        result = CollectionsRun()

        result.marked_overdue = len(
            await self._invoice_service.mark_overdue(today=reference_day)
        )

        for invoice in await self._open_invoices():
            if invoice.due_date is None:
                continue
            sent = await self._sent_stages(invoice.id)
            for step in stages_due(
                due_date=invoice.due_date,
                today=reference_day,
                already_sent=sent,
                policy=self._policy,
            ):
                delivered = await self._send_notice(invoice, step)
                if not delivered:
                    continue
                result.notices_sent += 1
                if step.suspends:
                    suspended = await self._suspend(
                        invoice.company_id,
                        reason=(
                            f"Invoice {invoice.invoice_number} unpaid "
                            f"{step.offset_days} days past its due date."
                        ),
                    )
                    if suspended:
                        result.suspended.append(invoice.company_id)

        result.reinstated = await self._reinstate_settled(reference_day)
        await self._refresh_statuses(reference_day)
        return result

    async def _open_invoices(self) -> list[Invoice]:
        rows = await self._session.execute(
            select(Invoice)
            .where(
                Invoice.status.in_(tuple(OPEN_STATES)),
                # Written off means we have stopped chasing it. Before this,
                # abandoning a receivable as bad debt did nothing to the
                # dunning sequence: the invoice stayed overdue, so notices
                # kept going out and the company stayed suspended — forever,
                # because nothing downstream ever made it not-overdue.
                Invoice.written_off_at.is_(None),
            )
            .order_by(Invoice.due_date)
        )
        return list(rows.scalars().all())

    async def _sent_stages(self, invoice_id: uuid.UUID) -> frozenset[DunningStage]:
        rows = await self._session.execute(
            select(DunningNotice.stage).where(DunningNotice.invoice_id == invoice_id)
        )
        return frozenset(rows.scalars().all())

    async def _send_notice(self, invoice: Invoice, step: DunningStep) -> bool:
        """Records the notice, then delivers it.

        In that order, and inside a savepoint: the unique constraint is
        what makes this idempotent, so it has to be the thing that
        decides whether the notice goes out. Delivering first and
        recording after would double-send every time the record failed.
        """
        notice = DunningNotice(
            company_id=invoice.company_id,
            invoice_id=invoice.id,
            stage=step.stage,
            invoice_number=invoice.invoice_number,
            channels="in_app",
        )
        try:
            async with self._session.begin_nested():
                self._session.add(notice)
                await self._session.flush()
        except IntegrityError:
            # Another pass got there first. Not an error — this is the
            # constraint doing exactly its job.
            return False

        recipients = await self._billing_contacts(invoice.company_id)
        title, body = _compose(invoice, step)
        for user_id in recipients:
            await self._notifications.create(
                company_id=invoice.company_id,
                user_id=user_id,
                notification_type=NOTIFICATION_TYPE,
                title=title,
                body=body,
                payload={
                    "invoice_id": str(invoice.id),
                    "invoice_number": invoice.invoice_number,
                    "stage": step.stage.value,
                    "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
                },
            )

        await self._audit.record(
            event_type=FinancialEventType.DUNNING_NOTICE_SENT,
            entity_type=FinancialEntityType.INVOICE,
            entity_id=invoice.id,
            company_id=invoice.company_id,
            actor=AuditActor.system_actor("Collections"),
            previous_state=None,
            new_state=step.stage.value,
            amount=invoice.total_amount - invoice.amount_paid - invoice.amount_credited,
            currency=invoice.currency,
            details={
                "invoice_number": invoice.invoice_number,
                "stage": step.stage.value,
                "recipients": len(recipients),
            },
        )
        return True

    async def _billing_contacts(self, company_id: uuid.UUID) -> list[uuid.UUID]:
        """Everybody at the company who can act on an unpaid invoice.

        Shared with every other thing billing sends a customer — see
        ``billing_contacts``. A dunning notice and an emailed invoice
        reaching different people is how each recipient comes to assume the
        other got it.
        """
        return await billing_contact_ids(self._session, company_id)

    # --- suspension --------------------------------------------------

    async def _suspend(self, company_id: uuid.UUID, *, reason: str) -> bool:
        company = await self._session.get(Company, company_id)
        if company is None:
            return False
        if company.billing_never_auto_suspend:
            # Still noticed, still audited, just not enforced. Silently
            # skipping would make an exempt account indistinguishable
            # from one the sweep failed to reach.
            await self._audit.record(
                event_type=FinancialEventType.DUNNING_NOTICE_SENT,
                entity_type=FinancialEntityType.COMPANY_BILLING,
                entity_id=company_id,
                company_id=company_id,
                actor=AuditActor.system_actor("Collections"),
                previous_state=company.billing_status.value,
                new_state=company.billing_status.value,
                reason=f"Suspension withheld — account is exempt. {reason}",
            )
            return False
        if company.billing_status is BillingStatus.PAYMENT_SUSPENDED:
            return False

        previous = company.billing_status.value
        # Guarded: two sweeps must not both record a suspension.
        result = await self._session.execute(
            update(Company)
            .where(
                Company.id == company_id,
                Company.billing_status != BillingStatus.PAYMENT_SUSPENDED,
            )
            .values(
                billing_status=BillingStatus.PAYMENT_SUSPENDED,
                billing_suspended_at=datetime.now(UTC),
            )
        )
        if result.rowcount != 1:
            return False

        await self._audit.record(
            event_type=FinancialEventType.BILLING_SUSPENDED,
            entity_type=FinancialEntityType.COMPANY_BILLING,
            entity_id=company_id,
            company_id=company_id,
            actor=AuditActor.system_actor("Collections"),
            previous_state=previous,
            new_state=BillingStatus.PAYMENT_SUSPENDED.value,
            reason=reason,
        )
        return True

    async def _reinstate_settled(self, today: date) -> list[uuid.UUID]:
        """Lifts billing suspension from companies with nothing overdue left.

        "Nothing overdue left" now includes debt that was written off, since
        ``_has_overdue`` skips it — which is the point of writing one off. A
        company held suspended for a receivable finance has abandoned is a
        company nobody is pursuing and nobody can serve.
        """
        rows = await self._session.execute(
            select(Company.id).where(
                Company.billing_status == BillingStatus.PAYMENT_SUSPENDED,
                Company.deleted_at.is_(None),
            )
        )
        reinstated: list[uuid.UUID] = []
        for company_id in rows.scalars().all():
            if await self._has_overdue(company_id, today):
                continue
            if await self.reinstate(
                company_id=company_id,
                reason="No overdue invoices remain — settled, credited or written off.",
                actor=AuditActor.system_actor("Collections"),
                today=today,
            ):
                reinstated.append(company_id)
        return reinstated

    async def reinstate(
        self,
        *,
        company_id: uuid.UUID,
        reason: str,
        actor: AuditActor | None = None,
        today: date | None = None,
    ) -> bool:
        """Lifts a billing suspension.

        Public because an operator sometimes needs to lift one by hand —
        a customer who has paid by wire that has not cleared, say. It
        recomputes the status rather than assuming ACTIVE: a company
        with a second unpaid invoice comes back as PAYMENT_OVERDUE, not
        as though nothing were owed.
        """
        company = await self._session.get(Company, company_id)
        if company is None:
            raise EntityNotFoundError("Company", company_id)
        if company.billing_status is not BillingStatus.PAYMENT_SUSPENDED:
            return False

        reference_day = today or datetime.now(UTC).date()
        target = await self._computed_status(company_id, reference_day, suspended=False)
        result = await self._session.execute(
            update(Company)
            .where(
                Company.id == company_id,
                Company.billing_status == BillingStatus.PAYMENT_SUSPENDED,
            )
            .values(billing_status=target, billing_suspended_at=None)
        )
        if result.rowcount != 1:
            return False

        await self._audit.record(
            event_type=FinancialEventType.BILLING_REINSTATED,
            entity_type=FinancialEntityType.COMPANY_BILLING,
            entity_id=company_id,
            company_id=company_id,
            actor=actor or AuditActor.system_actor("Collections"),
            previous_state=BillingStatus.PAYMENT_SUSPENDED.value,
            new_state=target.value,
            reason=reason,
        )
        return True

    # --- status ------------------------------------------------------

    async def _has_overdue(self, company_id: uuid.UUID, today: date) -> bool:
        rows = await self._session.execute(
            select(Invoice.id)
            .where(
                Invoice.company_id == company_id,
                Invoice.status.in_(tuple(OPEN_STATES)),
                Invoice.written_off_at.is_(None),
                Invoice.due_date < today,
            )
            .limit(1)
        )
        return rows.first() is not None

    async def _computed_status(
        self, company_id: uuid.UUID, today: date, *, suspended: bool
    ) -> BillingStatus:
        rows = await self._session.execute(
            select(Invoice.due_date).where(
                Invoice.company_id == company_id,
                Invoice.status.in_(tuple(OPEN_STATES)),
                # So a company whose only remaining debt has been written off
                # returns to ACTIVE rather than sitting overdue forever.
                Invoice.written_off_at.is_(None),
            )
        )
        due_dates = list(rows.scalars().all())
        return status_for(
            has_overdue=any(d is not None and d < today for d in due_dates),
            has_open=bool(due_dates),
            suspended=suspended,
        )

    async def _refresh_statuses(self, today: date) -> None:
        """Recomputes billing status for every company that is not
        suspended.

        Derived from the invoices rather than maintained incrementally:
        a status updated only when something happens is a status that
        goes stale the first time an event is missed, and "the dashboard
        says we are up to date but we have an overdue invoice" is not a
        bug anybody enjoys.
        """
        rows = await self._session.execute(
            select(Company.id, Company.billing_status).where(
                Company.billing_status != BillingStatus.PAYMENT_SUSPENDED,
                Company.deleted_at.is_(None),
            )
        )
        for company_id, current in rows.all():
            target = await self._computed_status(company_id, today, suspended=False)
            if target is not current:
                await self._session.execute(
                    update(Company).where(Company.id == company_id).values(billing_status=target)
                )

    # --- standing -----------------------------------------------------

    async def standing_for(self, company_id: uuid.UUID) -> CompanyStanding:
        """Where one company stands on paying its bills.

        Its own method because answering it by filtering the
        installation-wide list means walking every company to learn about
        one — the difference between a query and a sweep, on a page an
        operator opens per customer.

        Written-off invoices are excluded here as they are everywhere else in
        collections: a debt nobody is pursuing must not show as something the
        customer is behind on.
        """
        company = await self._session.get(Company, company_id)
        if company is None:
            raise EntityNotFoundError("Company", company_id)
        return await self._standing(company, datetime.now(UTC).date())

    async def standing_all(self, *, only_behind: bool = True) -> list[CompanyStanding]:
        """Every company's standing, worst first.

        No pagination, deliberately unchanged from what this replaced — but
        worth knowing before it is put behind a live tile: it walks every
        company and queries per company. It is a page-load-once figure.
        """
        today = datetime.now(UTC).date()
        rows = await self._session.execute(
            select(Company).where(Company.deleted_at.is_(None))
        )
        standings = []
        for company in rows.scalars().all():
            standing = await self._standing(company, today)
            if only_behind and standing.open_invoices == 0:
                continue
            standings.append(standing)
        standings.sort(key=lambda s: (-s.overdue_invoices, s.company_name))
        return standings

    async def _standing(self, company: Company, today: date) -> CompanyStanding:
        rows = await self._session.execute(
            select(Invoice).where(
                Invoice.company_id == company.id,
                Invoice.status.in_(tuple(OPEN_STATES)),
                Invoice.written_off_at.is_(None),
            )
        )
        invoices = list(rows.scalars().all())
        overdue = [
            invoice
            for invoice in invoices
            if invoice.due_date is not None and invoice.due_date < today
        ]
        outstanding = sum(
            (
                invoice.total_amount - invoice.amount_paid - invoice.amount_credited
                for invoice in invoices
            ),
            start=zero(),
        )
        next_on: date | None = None
        if overdue:
            oldest = min(overdue, key=lambda invoice: invoice.due_date or today)
            sent = await self._sent_stages(oldest.id)
            if oldest.due_date is not None:
                next_on = next_stage_date(
                    due_date=oldest.due_date, already_sent=sent, policy=self._policy
                )
        return CompanyStanding(
            company_id=company.id,
            company_name=company.name,
            currency=company.billing_currency,
            billing_status=company.billing_status,
            billing_suspended_at=company.billing_suspended_at,
            never_auto_suspend=company.billing_never_auto_suspend,
            open_invoices=len(invoices),
            overdue_invoices=len(overdue),
            amount_outstanding=outstanding,
            next_action_on=next_on,
        )

    # --- aging --------------------------------------------------------

    async def aging(
        self, *, company_id: uuid.UUID | None = None, today: date | None = None
    ) -> AgingReport:
        """Open invoices bucketed by how overdue they are, per currency.

        Written-off invoices are excluded, as they are everywhere else in
        collections: a debt nobody is chasing is not a receivable anybody
        is waiting on, and leaving it in would keep an abandoned balance
        ageing through the report for ever — the same defect that kept
        written-off invoices generating dunning notices.

        One query, not one per company or one per bucket. Only the five
        columns the report needs are selected: this is an
        installation-wide read an operator opens on a dashboard, and
        loading whole invoice entities to add three numbers together is
        work that shows up as latency on the page.
        """
        reference_day = today or datetime.now(UTC).date()

        # Checked rather than left to return an empty report: "this
        # company owes nothing" and "there is no such company" must not
        # look the same, and only one of them means the caller should go
        # and check the id they typed.
        if company_id is not None and await self._session.get(Company, company_id) is None:
            raise EntityNotFoundError("Company", company_id)

        conditions: list[ColumnElement[bool]] = [
            Invoice.status.in_(tuple(OPEN_STATES)),
            Invoice.written_off_at.is_(None),
        ]
        if company_id is not None:
            conditions.append(Invoice.company_id == company_id)

        rows = await self._session.execute(
            select(
                Invoice.currency,
                Invoice.due_date,
                Invoice.total_amount,
                Invoice.amount_paid,
                Invoice.amount_credited,
            ).where(*conditions)
        )

        # Grouped by the currency the *invoice* states, never the one the
        # company is on today. The document is what is owed, and a company
        # whose currency changed would otherwise re-denominate a debt that
        # was billed in something else.
        tallies: dict[str, dict[AgingBucket, list[Decimal]]] = {}
        for row in rows.all():
            due_date: date | None = row.due_date
            # An invoice with no due date cannot be past one. Filing it as
            # "90+ days overdue" would invent a fact the document does not
            # state; ``current`` says only what is known — that it is owed.
            days_overdue = (reference_day - due_date).days if due_date is not None else 0
            by_bucket = tallies.setdefault(
                row.currency, {band.bucket: [] for band in AGING_BANDS}
            )
            by_bucket[bucket_for(days_overdue)].append(
                row.total_amount - row.amount_paid - row.amount_credited
            )

        return AgingReport(
            as_of=reference_day,
            # Sorted by code so two calls that see the same data return the
            # same order. An installation with no open invoices reports no
            # currencies at all, which is the truth — inventing a row of
            # zeroes for a currency nobody bills in is a column an operator
            # then has to learn to ignore.
            currencies=tuple(_currency_aging(code, tallies[code]) for code in sorted(tallies)),
        )

    async def refresh_company(self, company_id: uuid.UUID, *, today: date | None = None) -> None:
        """Recomputes one company's status — called after a payment, so
        a customer who pays sees the change immediately rather than at
        the next sweep."""
        company = await self._session.get(Company, company_id)
        if company is None or company.billing_status is BillingStatus.PAYMENT_SUSPENDED:
            return
        reference_day = today or datetime.now(UTC).date()
        target = await self._computed_status(company_id, reference_day, suspended=False)
        if target is not company.billing_status:
            await self._session.execute(
                update(Company).where(Company.id == company_id).values(billing_status=target)
            )


def _currency_aging(currency: str, tallies: dict[AgingBucket, list[Decimal]]) -> CurrencyAging:
    """Totals one currency's buckets — and nothing wider than that.

    Summed through ``money.total`` at full working precision, then
    quantized once to the storage scale. ``to_storage`` is what gives an
    empty bucket the same shape as a populated one: ``Decimal("0")`` and
    ``Decimal("0.000000")`` compare equal but do not serialize the same,
    and a zero rendering as ``0`` beside amounts rendering as ``0.000000``
    reads as a bug to whoever is auditing the report.
    """
    buckets = tuple(
        AgingBucketTotal(
            bucket=band.bucket,
            from_days=band.from_days,
            to_days=band.to_days,
            invoice_count=len(tallies[band.bucket]),
            amount_outstanding=to_storage(total(tallies[band.bucket])),
        )
        for band in AGING_BANDS
    )
    return CurrencyAging(
        currency=currency,
        buckets=buckets,
        invoice_count=sum(bucket.invoice_count for bucket in buckets),
        total_outstanding=to_storage(total(bucket.amount_outstanding for bucket in buckets)),
    )


def _compose(invoice: Invoice, step: DunningStep) -> tuple[str, str]:
    """The words the customer actually reads.

    Escalating in tone, and every one states the amount, the number and
    the date — a reminder that makes somebody go and look up which
    invoice it means has failed at the only job it had.
    """
    outstanding = format_amount(
        invoice.total_amount - invoice.amount_paid - invoice.amount_credited
    )
    number = invoice.invoice_number or "your invoice"
    due = invoice.due_date.isoformat() if invoice.due_date else "its due date"

    match step.stage:
        case DunningStage.UPCOMING:
            return (
                f"Invoice {number} is due on {due}",
                f"{outstanding} is due on {due}. No action is needed if payment is already "
                "scheduled.",
            )
        case DunningStage.DUE_TODAY:
            return (
                f"Invoice {number} is due today",
                f"{outstanding} is due today.",
            )
        case DunningStage.FIRST_NOTICE:
            return (
                f"Invoice {number} is overdue",
                f"{outstanding} was due on {due} and has not been received.",
            )
        case DunningStage.SECOND_NOTICE:
            return (
                f"Invoice {number} remains unpaid",
                f"{outstanding} was due on {due}. Please arrange payment to avoid "
                "interruption of service.",
            )
        case DunningStage.FINAL_NOTICE:
            return (
                f"Final notice — invoice {number}",
                f"{outstanding} was due on {due}. If payment is not received, access will be "
                "suspended. Billing administrators will keep access in order to settle the "
                "account.",
            )
        case DunningStage.SUSPENDED:
            return (
                f"Service suspended — invoice {number} unpaid",
                f"{outstanding} remains unpaid since {due}, and access has been suspended. "
                "Service resumes as soon as payment is received.",
            )
    # Unreachable while every stage is handled above; kept so adding a
    # stage without a message fails loudly in review rather than sending
    # an empty notification.
    raise ValueError(f"No message defined for dunning stage {step.stage}.")


__all__ = [
    "AGING_BANDS",
    "NOTIFICATION_TYPE",
    "AgingBand",
    "AgingBucket",
    "AgingBucketTotal",
    "AgingReport",
    "CollectionsRun",
    "CollectionsService",
    "CurrencyAging",
    "bucket_for",
]
