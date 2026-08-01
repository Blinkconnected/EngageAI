"""Payment processing: gateways, reversal and refunds.

See ``docs/architecture/billing.md``.

Phase 4 of the billing engine. Everything here is layered *on top of*
the invoice engine rather than inside it: the invoice engine owns
documents and what they are owed, and this service owns money moving in
and out. Keeping the seam sharp is what let a gateway be added without
touching invoice generation, and is what would let a second gateway be
added without touching either.

Four operations, and the reasoning behind each:

**Starting a payment** creates an intent, not a payment. An intent is a
request that may never complete; a payment means money arrived. A
customer who opens a checkout page and closes it must leave nothing in
the ledger, and separating the two is the only way that holds.

**Completing a payment** is idempotent at three levels — the intent's
guarded UPDATE, the payment's ``(provider, provider_reference)`` unique
constraint, and PayPal's own ``PayPal-Request-Id``. Gateway webhooks are
delivered at least once, and taking the same money twice is the one
failure a payments integration cannot undo by itself.

**Reversing an allocation** un-applies money from an invoice without
erasing that it happened. The allocation is marked reversed, never
deleted, and the invoice reopens if it had been settled.

**Refunding** sends money back. It refuses to refund anything still
allocated to an invoice, which forces the operator to say — explicitly,
with a reason — which invoice stops being paid. A refund that silently
un-pays an invoice is how a ledger drifts from reality.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from blinkengage.application.services.financial_audit_service import (
    AuditActor,
    FinancialAuditRecorder,
)
from blinkengage.application.services.invoice_service import InvoiceService
from blinkengage.application.services.ledger_service import LedgerService
from blinkengage.core.config import Settings
from blinkengage.domain.exceptions import (
    EntityNotFoundError,
    PaymentProcessingError,
    RefundNotPermittedError,
)
from blinkengage.domain.financial_audit import FinancialEntityType, FinancialEventType
from blinkengage.domain.invoicing import OPEN_STATES, InvoiceStatus
from blinkengage.domain.ledger import LedgerAccount, LedgerEntryType
from blinkengage.domain.money import BILLING_CURRENCY, to_storage, zero
from blinkengage.domain.payments import (
    PaymentIntentStatus,
    PaymentProviderKind,
    RefundStatus,
)
from blinkengage.infrastructure.database.models.invoicing import Invoice, Payment
from blinkengage.infrastructure.database.models.payments import PaymentIntent, PaymentRefund
from blinkengage.infrastructure.payments.base import PaymentProviderError
from blinkengage.infrastructure.payments.registry import PaymentProviderRegistry
from blinkengage.infrastructure.repositories.invoicing_repository import (
    InvoiceRepository,
    PaymentRepository,
)
from blinkengage.infrastructure.repositories.payments_repository import (
    AllocationReversalRepository,
    PaymentIntentRepository,
    PaymentRefundRepository,
)


@dataclass(frozen=True, slots=True)
class CheckoutSession:
    """What a customer needs in order to pay.

    ``reused`` distinguishes a fresh order from returning to one already
    open. A caller that cannot tell the difference will happily create a
    new PayPal order on every page load, and the abandoned ones stay in
    the merchant's dashboard forever.
    """

    intent_id: uuid.UUID
    provider: str
    provider_reference: str
    approval_url: str | None
    amount: Decimal
    currency: str
    reused: bool


class PaymentService:
    def __init__(
        self,
        *,
        intents: PaymentIntentRepository,
        refunds: PaymentRefundRepository,
        reversals: AllocationReversalRepository,
        payments: PaymentRepository,
        invoices: InvoiceRepository,
        invoice_service: InvoiceService,
        providers: PaymentProviderRegistry,
        audit: FinancialAuditRecorder,
        ledger: LedgerService,
        settings: Settings,
    ) -> None:
        self._intents = intents
        self._refunds = refunds
        self._reversals = reversals
        self._payments = payments
        self._invoices = invoices
        self._invoice_service = invoice_service
        self._providers = providers
        self._audit = audit
        self._ledger = ledger
        self._settings = settings

    # --- starting a payment ------------------------------------------

    async def start_checkout(
        self,
        *,
        invoice_id: uuid.UUID,
        provider: str = PaymentProviderKind.PAYPAL.value,
        actor: AuditActor | None = None,
    ) -> CheckoutSession:
        """Opens a payment at the gateway for an invoice's balance."""
        invoice = await self._invoices.get_by_id(invoice_id)
        if invoice is None:
            raise EntityNotFoundError("Invoice", invoice_id)
        if invoice.status not in OPEN_STATES:
            raise PaymentProcessingError(
                f"An invoice that is {invoice.status.value} cannot be paid."
            )

        outstanding = invoice.total_amount - invoice.amount_paid - invoice.amount_credited
        if outstanding <= zero():
            raise PaymentProcessingError("This invoice has nothing outstanding to pay.")

        existing = await self._intents.open_for_invoice(invoice_id)
        if existing is not None and existing.provider == provider:
            # The customer reloaded, or came back later. Returning them
            # to the same order avoids leaving a trail of abandoned ones
            # — and avoids the case where two live orders exist and the
            # customer pays both.
            if existing.amount == to_storage(outstanding):
                return CheckoutSession(
                    intent_id=existing.id,
                    provider=existing.provider,
                    provider_reference=existing.provider_reference,
                    approval_url=existing.approval_url,
                    amount=existing.amount,
                    currency=existing.currency,
                    reused=True,
                )
            # The balance moved underneath it — a credit note, or a
            # partial payment. The open order is now for the wrong
            # amount, so it is cancelled rather than left payable.
            await self._intents.settle(
                intent_id=existing.id,
                status=PaymentIntentStatus.CANCELLED,
                failure_reason="Superseded: the invoice balance changed.",
                completed_at=datetime.now(UTC),
            )

        adapter = self._providers.get(provider)
        reference = invoice.invoice_number or str(invoice.id)
        try:
            result = await adapter.create_intent(
                amount=outstanding,
                currency=invoice.currency,
                reference=reference,
                # The customer name as it was snapshotted onto the
                # invoice, not the company's current name: the PayPal
                # receipt must match the document being paid.
                description=f"{invoice.customer_name} — invoice {reference}",
                return_url=f"{self._settings.payment_return_url}?invoice={invoice.id}",
                cancel_url=f"{self._settings.payment_cancel_url}?invoice={invoice.id}",
            )
        except PaymentProviderError as exc:
            raise PaymentProcessingError(f"The payment provider refused: {exc}") from exc

        intent = await self._intents.add(
            PaymentIntent(
                company_id=invoice.company_id,
                invoice_id=invoice.id,
                provider=provider,
                provider_reference=result.provider_reference,
                status=result.status,
                amount=to_storage(outstanding),
                currency=invoice.currency,
                approval_url=result.approval_url,
            )
        )
        await self._audit.record(
            event_type=FinancialEventType.PAYMENT_INTENT_CREATED,
            entity_type=FinancialEntityType.PAYMENT_INTENT,
            entity_id=intent.id,
            company_id=invoice.company_id,
            actor=actor or AuditActor.system_actor(),
            previous_state=None,
            new_state=PaymentIntentStatus.PENDING.value,
            amount=intent.amount,
            currency=intent.currency,
            details={
                "provider": provider,
                "provider_reference": result.provider_reference,
                "invoice_number": invoice.invoice_number,
            },
        )
        return CheckoutSession(
            intent_id=intent.id,
            provider=provider,
            provider_reference=result.provider_reference,
            approval_url=result.approval_url,
            amount=intent.amount,
            currency=intent.currency,
            reused=False,
        )

    # --- completing a payment ----------------------------------------

    async def capture(
        self,
        *,
        provider: str,
        provider_reference: str,
        actor: AuditActor | None = None,
    ) -> Payment | None:
        """Takes the money the customer approved, records it, applies it.

        Returns the payment, or ``None`` when no money moved — the
        intent is unknown, or the gateway refused it. Safe to call
        repeatedly: the second call finds the intent already settled and
        returns the payment it produced, rather than capturing again.

        A declined payment is **not** raised as an error. A card that
        bounces is an ordinary outcome, not a server fault, and raising
        here would roll the request back — taking the recorded failure
        reason with it and leaving the intent stuck at PENDING forever,
        with the one piece of information the customer needs ("your card
        was declined") discarded. The failure is recorded, and the
        caller reads it off the intent.
        """
        intent = await self._intents.get_by_reference(
            provider=provider, reference=provider_reference
        )
        if intent is None:
            return None
        if intent.status is not PaymentIntentStatus.PENDING:
            # Already handled — a redelivered webhook, or the customer
            # returning to the success page after the webhook landed.
            return await self._payments.get_by_id(intent.payment_id) if intent.payment_id else None

        adapter = self._providers.get(provider)
        try:
            result = await adapter.capture(provider_reference)
        except PaymentProviderError as exc:
            await self._fail_intent(intent, reason=str(exc), actor=actor)
            return None

        if result.status is not PaymentIntentStatus.COMPLETED:
            await self._fail_intent(
                intent, reason=f"Provider returned {result.status.value}.", actor=actor
            )
            return None

        return await self._settle_intent(
            intent,
            result_amount=result.amount,
            capture_reference=result.capture_reference,
            actor=actor,
        )

    async def _settle_intent(
        self,
        intent: PaymentIntent,
        *,
        result_amount: Decimal,
        capture_reference: str,
        actor: AuditActor | None,
    ) -> Payment:
        """Turns a captured intent into a payment applied to its invoice."""
        now = datetime.now(UTC)
        payment = await self._invoice_service.record_payment(
            company_id=intent.company_id,
            amount=result_amount,
            received_at=now,
            reference=capture_reference,
            note=f"Captured via {intent.provider}.",
            provider=intent.provider,
            # The *capture* reference, not the order's: a refund is
            # issued against the capture, and storing the order id here
            # would make the refund path unable to find it.
            provider_reference=capture_reference,
            actor=actor or AuditActor.system_actor(),
        )

        claimed = await self._intents.settle(
            intent_id=intent.id,
            status=PaymentIntentStatus.COMPLETED,
            payment_id=payment.id,
            completed_at=now,
        )
        if not claimed:
            # Another worker settled it between the capture and here.
            # The payment row is idempotent on (provider, reference), so
            # this is the same payment, not a second one.
            return payment

        await self._audit.record(
            event_type=FinancialEventType.PAYMENT_INTENT_COMPLETED,
            entity_type=FinancialEntityType.PAYMENT_INTENT,
            entity_id=intent.id,
            company_id=intent.company_id,
            actor=actor or AuditActor.system_actor(),
            previous_state=PaymentIntentStatus.PENDING.value,
            new_state=PaymentIntentStatus.COMPLETED.value,
            amount=payment.amount,
            currency=payment.currency,
            details={"payment_id": str(payment.id), "capture_reference": capture_reference},
        )

        if intent.invoice_id is not None:
            invoice = await self._invoices.get_by_id(intent.invoice_id)
            if invoice is not None and invoice.status in OPEN_STATES:
                outstanding = invoice.total_amount - invoice.amount_paid - invoice.amount_credited
                # Allocate the smaller of the two: an overpayment stays
                # on the payment as an unallocated credit rather than
                # pushing the invoice past its total, which the invoice
                # engine refuses anyway.
                applicable = min(to_storage(payment.amount), outstanding)
                if applicable > zero():
                    await self._invoice_service.allocate(
                        payment_id=payment.id,
                        invoice_id=invoice.id,
                        amount=applicable,
                        actor=actor or AuditActor.system_actor(),
                    )
        return payment

    async def _fail_intent(
        self, intent: PaymentIntent, *, reason: str, actor: AuditActor | None
    ) -> None:
        await self._intents.settle(
            intent_id=intent.id,
            status=PaymentIntentStatus.FAILED,
            failure_reason=reason,
            completed_at=datetime.now(UTC),
        )
        await self._audit.record(
            event_type=FinancialEventType.PAYMENT_INTENT_FAILED,
            entity_type=FinancialEntityType.PAYMENT_INTENT,
            entity_id=intent.id,
            company_id=intent.company_id,
            actor=actor or AuditActor.system_actor(),
            previous_state=PaymentIntentStatus.PENDING.value,
            new_state=PaymentIntentStatus.FAILED.value,
            amount=intent.amount,
            currency=intent.currency,
            reason=reason,
        )

    async def reconcile_pending(self, *, older_than: datetime, limit: int = 200) -> int:
        """Re-reads intents the provider never told us about.

        A webhook that is never delivered leaves a customer who has paid
        looking unpaid — the single most damaging billing failure there
        is, because it ends in a suspension. This sweep is the safety
        net: it asks the provider directly rather than waiting to be
        told.
        """
        settled = 0
        for intent in await self._intents.stale_pending(older_than=older_than, limit=limit):
            adapter = self._providers.get(intent.provider)
            try:
                state = await adapter.get_intent(intent.provider_reference)
            except PaymentProviderError:
                # Leave it pending. A provider that is briefly
                # unreachable must not cause an intent to be written off.
                continue
            if state.status is PaymentIntentStatus.COMPLETED:
                await self.capture(
                    provider=intent.provider,
                    provider_reference=intent.provider_reference,
                    actor=AuditActor.system_actor("Payment reconciliation"),
                )
                settled += 1
            elif state.status in {PaymentIntentStatus.FAILED, PaymentIntentStatus.CANCELLED}:
                await self._fail_intent(
                    intent,
                    reason=f"Provider reports {state.status.value}.",
                    actor=AuditActor.system_actor("Payment reconciliation"),
                )
                settled += 1
        return settled

    # --- reversal ----------------------------------------------------

    async def reverse_allocation(
        self,
        *,
        allocation_id: uuid.UUID,
        reason: str,
        actor: AuditActor | None = None,
        today: date | None = None,
    ) -> Invoice:
        """Un-applies money from an invoice, without erasing that it was.

        Needed when a payment was matched to the wrong document, when a
        transfer bounces, or when a card payment is charged back. The
        allocation row stays, marked reversed and carrying the reason;
        the invoice's paid total goes back down; and if the invoice had
        been settled it reopens — to OVERDUE rather than ISSUED when its
        due date has already passed, because a reversal does not make a
        late invoice punctual again.
        """
        if not reason.strip():
            raise PaymentProcessingError("A reversal must state a reason.")

        allocation = await self._reversals.get(allocation_id)
        if allocation is None:
            raise EntityNotFoundError("PaymentAllocation", allocation_id)
        if allocation.reversed:
            raise PaymentProcessingError("That allocation has already been reversed.")

        invoice = await self._invoices.get_by_id(allocation.invoice_id)
        if invoice is None:
            raise EntityNotFoundError("Invoice", allocation.invoice_id)
        if invoice.status is InvoiceStatus.CANCELLED:
            raise PaymentProcessingError(
                "Money allocated to a cancelled invoice cannot be reversed; "
                "refund the payment instead."
            )

        now = datetime.now(UTC)
        claimed = await self._reversals.reverse(allocation_id=allocation_id, reason=reason, at=now)
        if not claimed:
            # Lost the race to a concurrent reversal. Refusing is right:
            # both succeeding would subtract the amount twice.
            raise PaymentProcessingError("That allocation has already been reversed.")

        await self._invoices.apply_payment(
            invoice_id=invoice.id, amount=-to_storage(allocation.amount)
        )
        await self._audit.record(
            event_type=FinancialEventType.PAYMENT_ALLOCATION_REVERSED,
            entity_type=FinancialEntityType.PAYMENT_ALLOCATION,
            entity_id=allocation_id,
            company_id=invoice.company_id,
            actor=actor or AuditActor.system_actor(),
            previous_state="allocated",
            new_state="reversed",
            amount=allocation.amount,
            currency=invoice.currency,
            reason=reason,
            details={
                "payment_id": str(allocation.payment_id),
                "invoice_id": str(invoice.id),
                "invoice_number": invoice.invoice_number,
            },
        )
        # Puts the money back where it came from: the receivable is
        # restored and the customer credit reinstated. Its own entry,
        # never a deletion of the original — the history has to show that
        # money was applied and then un-applied.
        await self._ledger.record(
            entry_type=LedgerEntryType.ALLOCATION_REVERSED,
            company_id=invoice.company_id,
            amount=allocation.amount,
            reference_entity="payment_allocation",
            reference_id=allocation_id,
            reference_number=invoice.invoice_number,
            description=(
                f"Allocation to {invoice.invoice_number or 'an invoice'} reversed: {reason}"
            ),
            occurred_at=now,
            currency=invoice.currency,
        )
        await self._reopen_if_unsettled(invoice.id, reason=reason, actor=actor, today=today)
        refreshed = await self._invoices.get_by_id(invoice.id)
        assert refreshed is not None
        return refreshed

    async def _reopen_if_unsettled(
        self,
        invoice_id: uuid.UUID,
        *,
        reason: str,
        actor: AuditActor | None,
        today: date | None,
    ) -> None:
        """Takes a PAID invoice back to owing money."""
        invoice = await self._invoices.get_by_id(invoice_id)
        if invoice is None or invoice.status is not InvoiceStatus.PAID:
            return
        covered = invoice.amount_paid + invoice.amount_credited
        if covered >= invoice.total_amount:
            return

        reference_day = today or datetime.now(UTC).date()
        target = (
            InvoiceStatus.OVERDUE
            if invoice.due_date is not None and invoice.due_date < reference_day
            else InvoiceStatus.ISSUED
        )
        await self._invoices.transition(
            invoice_id=invoice_id,
            expected=InvoiceStatus.PAID,
            target=target,
            paid_at=None,
        )
        await self._audit.record(
            event_type=FinancialEventType.INVOICE_REOPENED,
            entity_type=FinancialEntityType.INVOICE,
            entity_id=invoice_id,
            company_id=invoice.company_id,
            actor=actor or AuditActor.system_actor(),
            previous_state=InvoiceStatus.PAID.value,
            new_state=target.value,
            amount=invoice.total_amount - covered,
            currency=invoice.currency,
            reason=reason,
            details={"invoice_number": invoice.invoice_number},
        )

    # --- refunds -----------------------------------------------------

    async def refund(
        self,
        *,
        payment_id: uuid.UUID,
        amount: Decimal,
        reason: str,
        actor: AuditActor | None = None,
    ) -> PaymentRefund:
        """Sends money back to the customer.

        Refuses to refund anything still allocated to an invoice. That
        is a deliberate obstacle: the alternative is a refund that
        silently leaves an invoice marked paid with no money behind it,
        and nobody discovers that until a reconciliation months later.
        Reverse the allocation first — stating why — and the invoice
        correctly reopens as unpaid.
        """
        if not reason.strip():
            raise RefundNotPermittedError("A refund must state a reason.")
        if amount <= zero():
            raise RefundNotPermittedError("A refund must be for a positive amount.")

        payment = await self._payments.get_by_id(payment_id)
        if payment is None:
            raise EntityNotFoundError("Payment", payment_id)

        allocated = await self._payments.allocated_total(payment_id)
        already_refunded = await self._refunds.refunded_total(payment_id)
        available = payment.amount - allocated - already_refunded
        if to_storage(amount) > available:
            raise RefundNotPermittedError(
                f"Only {available} of this payment can be refunded "
                f"({allocated} is allocated to invoices, {already_refunded} already refunded). "
                "Reverse the allocation first if the invoice should become unpaid."
            )

        provider = payment.provider or PaymentProviderKind.MANUAL.value
        record = await self._refunds.add(
            PaymentRefund(
                payment_id=payment_id,
                company_id=payment.company_id,
                provider=provider,
                status=RefundStatus.PENDING,
                amount=to_storage(amount),
                currency=payment.currency or BILLING_CURRENCY.code,
                reason=reason,
                requested_by_user_id=actor.user_id if actor else None,
            )
        )
        # The row is written *before* the provider is called, on purpose.
        # If the call succeeds and the process then dies, the refund is
        # recorded as pending and can be found later; the opposite order
        # loses money with no trace. For the same reason nothing below
        # raises once this row exists — an exception would roll back the
        # very record that makes the attempt visible.

        adapter = self._providers.get(provider)
        try:
            result = await adapter.refund(
                capture_reference=payment.provider_reference or str(payment.id),
                amount=amount,
                currency=record.currency,
                reason=reason,
            )
        except PaymentProviderError as exc:
            await self._refunds.complete(
                refund_id=record.id,
                status=RefundStatus.FAILED,
                provider_reference=None,
                failure_reason=str(exc),
                completed_at=datetime.now(UTC),
            )
            await self._audit.record(
                event_type=FinancialEventType.PAYMENT_REFUND_FAILED,
                entity_type=FinancialEntityType.PAYMENT_REFUND,
                entity_id=record.id,
                company_id=payment.company_id,
                actor=actor or AuditActor.system_actor(),
                previous_state=RefundStatus.PENDING.value,
                new_state=RefundStatus.FAILED.value,
                amount=record.amount,
                currency=record.currency,
                reason=str(exc),
            )
            refreshed = await self._refunds.get_by_id(record.id)
            assert refreshed is not None
            # Deliberately returned, not raised — for the same reason as
            # a declined capture. Raising would roll this request back
            # and destroy the row that records the attempt, leaving no
            # trace that a refund was tried and refused. The caller reads
            # `status` and `failure_reason` off the record.
            #
            # Note the asymmetry with RefundNotPermittedError above,
            # which *does* raise: that refusal happens before the
            # provider is contacted, so there is nothing recorded to
            # lose, and no money moved.
            return refreshed

        status = RefundStatus.COMPLETED if result.succeeded else RefundStatus.FAILED
        await self._refunds.complete(
            refund_id=record.id,
            status=status,
            provider_reference=result.refund_reference,
            failure_reason=None if result.succeeded else "The provider did not confirm.",
            completed_at=datetime.now(UTC),
        )
        await self._audit.record(
            event_type=(
                FinancialEventType.PAYMENT_REFUNDED
                if result.succeeded
                else FinancialEventType.PAYMENT_REFUND_FAILED
            ),
            entity_type=FinancialEntityType.PAYMENT_REFUND,
            entity_id=record.id,
            company_id=payment.company_id,
            actor=actor or AuditActor.system_actor(),
            previous_state=RefundStatus.PENDING.value,
            new_state=status.value,
            amount=record.amount,
            currency=record.currency,
            reason=reason,
            details={
                "payment_id": str(payment_id),
                "refund_reference": result.refund_reference,
            },
        )
        if result.succeeded:
            # Only on success: a pending or failed refund moved no money,
            # and posting one would show cash leaving that never left.
            await self._ledger.record(
                entry_type=LedgerEntryType.REFUND_ISSUED,
                company_id=payment.company_id,
                amount=record.amount,
                reference_entity="payment_refund",
                reference_id=record.id,
                description=f"Refund issued: {reason}",
                currency=record.currency,
            )

        refreshed = await self._refunds.get_by_id(record.id)
        assert refreshed is not None
        return refreshed

    # --- write-offs and chargebacks ----------------------------------

    async def write_off(
        self,
        *,
        invoice_id: uuid.UUID,
        reason: str,
        actor: AuditActor | None = None,
    ) -> Decimal:
        """Abandons a receivable as uncollectable.

        An **expense**, not a discount. A write-off says we billed
        correctly and did not get paid; a credit note says we billed too
        much. Collapsing them would make revenue look wrong in one
        direction or bad debt invisible in the other.

        Deliberately does **not** change the invoice's status. There is no
        ``WRITTEN_OFF`` state, and inventing one would be a new billing
        concept; more importantly the invoice remains unpaid and overdue,
        which is the truth. The ledger is where the receivable stops
        being an asset.

        It does stamp ``written_off_at``, which is what makes collections
        stop chasing it. Without that the write-off was ledger-only: the
        invoice stayed in ``OPEN_STATES``, so the dunning sweep kept sending
        notices and the company stayed suspended indefinitely — abandoning a
        debt never ended the pursuit of it.
        """
        if not reason.strip():
            raise PaymentProcessingError("A write-off must state a reason.")

        invoice = await self._invoices.get_by_id(invoice_id)
        if invoice is None:
            raise EntityNotFoundError("Invoice", invoice_id)

        outstanding = await self._ledger.account_balance(
            LedgerAccount.ACCOUNTS_RECEIVABLE, company_id=invoice.company_id
        )
        document_outstanding = invoice.total_amount - invoice.amount_paid - invoice.amount_credited
        # Bounded by the invoice, not by the company's whole receivable:
        # writing off "everything outstanding" when the operator named one
        # invoice would quietly clear the others too.
        amount = min(document_outstanding, outstanding) if outstanding > zero() else zero()
        if amount <= zero():
            raise PaymentProcessingError("That invoice has nothing outstanding to write off.")

        invoice.written_off_at = datetime.now(UTC)
        await self._ledger.record(
            entry_type=LedgerEntryType.WRITE_OFF,
            company_id=invoice.company_id,
            amount=amount,
            reference_entity="invoice",
            reference_id=invoice_id,
            reference_number=invoice.invoice_number,
            description=(
                f"Receivable on {invoice.invoice_number or 'an invoice'} " f"written off: {reason}"
            ),
            currency=invoice.currency,
        )
        await self._audit.record(
            event_type=FinancialEventType.RECEIVABLE_WRITTEN_OFF,
            entity_type=FinancialEntityType.INVOICE,
            entity_id=invoice_id,
            company_id=invoice.company_id,
            actor=actor or AuditActor.system_actor(),
            previous_state=invoice.status.value,
            new_state=invoice.status.value,
            amount=amount,
            currency=invoice.currency,
            reason=reason,
            details={"invoice_number": invoice.invoice_number},
        )
        return amount

    async def record_chargeback(
        self,
        *,
        allocation_id: uuid.UUID,
        reason: str,
        actor: AuditActor | None = None,
    ) -> Invoice:
        """A bank has taken the money back.

        Mechanically a reversal plus cash leaving, so it reuses the
        reversal path and then posts the cash movement. Kept distinct from
        a refund because the *cause* matters commercially — a refund is
        something we chose to do, a chargeback is something done to us —
        and a ledger where both look identical cannot answer "how much are
        we losing to disputes".
        """
        allocation = await self._reversals.get(allocation_id)
        if allocation is None:
            raise EntityNotFoundError("PaymentAllocation", allocation_id)
        amount = allocation.amount

        invoice = await self.reverse_allocation(
            allocation_id=allocation_id,
            reason=f"Chargeback: {reason}",
            actor=actor,
        )
        # The reversal restored the receivable and the customer credit;
        # this takes the cash out against that credit, leaving the
        # customer owing again with no money held on their behalf.
        await self._ledger.record(
            entry_type=LedgerEntryType.CHARGEBACK,
            company_id=invoice.company_id,
            amount=amount,
            reference_entity="payment_allocation",
            reference_id=allocation_id,
            reference_number=invoice.invoice_number,
            description=f"Chargeback on {invoice.invoice_number or 'an invoice'}: {reason}",
            currency=invoice.currency,
            debit=LedgerAccount.CUSTOMER_CREDIT,
            credit=LedgerAccount.CASH,
        )
        return invoice

    # --- reads -------------------------------------------------------

    async def refundable_amount(self, payment_id: uuid.UUID) -> Decimal:
        payment = await self._payments.get_by_id(payment_id)
        if payment is None:
            raise EntityNotFoundError("Payment", payment_id)
        allocated = await self._payments.allocated_total(payment_id)
        refunded = await self._refunds.refunded_total(payment_id)
        return payment.amount - allocated - refunded


__all__ = ["CheckoutSession", "PaymentService"]
