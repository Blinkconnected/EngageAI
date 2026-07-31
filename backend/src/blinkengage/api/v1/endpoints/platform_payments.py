"""Payment processing and collections — `/api/v1/platform/payments/*`.

Gated at registration by ``get_platform_auth``, like the rest of
billing.

Route order matters here and is not incidental: every literal path is
registered **before** any `/{id}` path. FastAPI matches in declaration
order, so `/collections/run` declared after `/{payment_id}` would be
parsed as a payment id and rejected as a malformed UUID — a bug this
codebase has already shipped twice, once on the PayPal webhook and once
on the invoice audit route.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.api.deps import (
    deny_read_only_writes,
    get_collections_service,
    get_db_session,
    get_payment_providers,
    get_payment_service,
    get_platform_auth,
)
from blinkengage.api.schemas.payments import (
    AgingReportResponse,
    AutoSuspendExemptionRequest,
    CheckoutSessionResponse,
    CollectionsRunResponse,
    CompanyBillingStatusResponse,
    DunningNoticeResponse,
    PaymentAllocationCurrencyGroupResponse,
    PaymentAllocationPageResponse,
    PaymentAllocationResponse,
    PaymentIntentResponse,
    RefundableResponse,
    RefundRequest,
    RefundResponse,
    ReinstateRequest,
    ReverseAllocationRequest,
    StartCheckoutRequest,
)
from blinkengage.application.services.collections_service import (
    CollectionsService,
)
from blinkengage.application.services.financial_audit_service import (
    AuditActor,
    FinancialAuditRecorder,
)
from blinkengage.application.services.payment_service import PaymentService
from blinkengage.core.auth_context import PlatformContext
from blinkengage.domain.collections import DEFAULT_DUNNING_POLICY
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.domain.financial_audit import FinancialEntityType, FinancialEventType
from blinkengage.infrastructure.database.models.collections import DunningNotice
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.invoicing import (
    Invoice,
    Payment,
    PaymentAllocation,
)
from blinkengage.infrastructure.payments.registry import PaymentProviderRegistry
from blinkengage.infrastructure.repositories.financial_audit_repository import (
    FinancialAuditRepository,
)
from blinkengage.infrastructure.repositories.payments_repository import (
    PaymentIntentRepository,
)
from blinkengage.infrastructure.repositories.user_repository import UserRepository

router = APIRouter(
    prefix="/platform/payments",
    tags=["platform-payments"],
    # Both gates at construction: platform authority, and — for anything
    # that is not a GET — an operator who may change things. A route added
    # to this router inherits both rather than shipping unguarded.
    dependencies=[Depends(get_platform_auth), Depends(deny_read_only_writes)],
)


async def _actor(platform: PlatformContext, session: AsyncSession) -> AuditActor:
    user = await UserRepository(session).get_by_id(platform.user_id)
    if user is None:
        return AuditActor(user_id=platform.user_id)
    return AuditActor(user_id=user.id, email=user.email, name=user.full_name)


# --- providers -------------------------------------------------------


@router.get("/providers", response_model=list[str])
async def list_providers(
    providers: Annotated[PaymentProviderRegistry, Depends(get_payment_providers)],
) -> list[str]:
    """Which gateways this deployment can actually use.

    Read from configuration rather than hardcoded, so a console never
    offers a "Pay with PayPal" button on a deployment that has no PayPal
    credentials.
    """
    return providers.available()


# --- collections -----------------------------------------------------


@router.post("/collections/run", response_model=CollectionsRunResponse)
async def run_collections(
    collections: Annotated[CollectionsService, Depends(get_collections_service)],
    today: Annotated[date | None, Query()] = None,
) -> CollectionsRunResponse:
    """Runs the dunning sweep now.

    The same code path the scheduled task uses, exposed so an operator
    can run it deliberately — and so its behaviour can be observed
    rather than inferred from what customers received overnight.
    """
    run = await collections.run(today=today)
    return CollectionsRunResponse(
        marked_overdue=run.marked_overdue,
        notices_sent=run.notices_sent,
        suspended=run.suspended,
        reinstated=run.reinstated,
    )


@router.get("/collections/status", response_model=list[CompanyBillingStatusResponse])
async def billing_standing(
    collections: Annotated[CollectionsService, Depends(get_collections_service)],
    only_behind: Annotated[bool, Query()] = True,
) -> list[CompanyBillingStatusResponse]:
    """Every company's billing standing, worst first.

    The computation moved into ``CollectionsService`` so this and the
    per-company endpoint cannot disagree — which they did the moment
    written-off invoices stopped counting as debt in one place and not the
    other.

    No pagination, and it queries per company. A page-load-once figure, not a
    live tile.
    """
    return [
        CompanyBillingStatusResponse.model_validate(standing)
        for standing in await collections.standing_all(only_behind=only_behind)
    ]


@router.get("/collections/aging", response_model=AgingReportResponse)
async def aging(
    collections: Annotated[CollectionsService, Depends(get_collections_service)],
    company_id: Annotated[uuid.UUID | None, Query()] = None,
) -> AgingReportResponse:
    """Open invoices bucketed by how overdue they are.

    **Grouped by currency, with no figure above the grouping.** This
    installation bills in more than one currency and nothing converts —
    no exchange rate is stored anywhere, on purpose — so a single "total
    outstanding" spanning dollars and dinars is a number that means
    nothing in either. The response has nowhere to put one: every total
    lives inside a currency, so a caller cannot combine them without
    first inventing a rate this build does not have.

    Written-off invoices are excluded, as they are everywhere else in
    collections. A debt finance has abandoned is not a receivable
    anybody is waiting on, and ageing it through the report indefinitely
    would overstate what is collectable — the figure this page exists to
    report.

    ``company_id`` scopes it to one customer. An unknown one is a 404
    rather than an empty report, because "owes nothing" and "no such
    company" are different answers.
    """
    return AgingReportResponse.model_validate(await collections.aging(company_id=company_id))


@router.get("/collections/notices/{invoice_id}", response_model=list[DunningNoticeResponse])
async def notices_for_invoice(
    invoice_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[DunningNoticeResponse]:
    """What the customer was actually told about this invoice, and when.

    The first thing anybody asks when a suspension is disputed.
    """
    rows = await session.execute(
        select(DunningNotice).where(DunningNotice.invoice_id == invoice_id)
    )
    notices = [DunningNoticeResponse.model_validate(row) for row in rows.scalars().all()]
    # Ordered by the policy sequence, not by ``sent_at``. A sweep
    # catching up after an outage writes several notices in the same
    # instant, so sorting by timestamp returns them in an arbitrary
    # order — and "which notice came first" is exactly what somebody
    # reading this is trying to establish.
    order = {step.stage: index for index, step in enumerate(DEFAULT_DUNNING_POLICY)}
    notices.sort(key=lambda row: (row.sent_at, order.get(row.stage, len(order))))
    return notices


@router.post("/collections/{company_id}/reinstate", status_code=status.HTTP_204_NO_CONTENT)
async def reinstate_company(
    company_id: uuid.UUID,
    payload: ReinstateRequest,
    collections: Annotated[CollectionsService, Depends(get_collections_service)],
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> None:
    """Lifts a billing suspension by hand.

    Needed for the wire transfer that has been sent but not cleared. It
    recomputes the resulting status rather than assuming ACTIVE, so a
    company with a second unpaid invoice comes back as overdue rather
    than looking settled.
    """
    await collections.reinstate(
        company_id=company_id,
        reason=payload.reason,
        actor=await _actor(platform, session),
    )


@router.put("/collections/{company_id}/exemption", status_code=status.HTTP_204_NO_CONTENT)
async def set_auto_suspend_exemption(
    company_id: uuid.UUID,
    payload: AutoSuspendExemptionRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
) -> None:
    """Exempts a company from automatic suspension.

    For enterprise and government accounts on payment cycles longer than
    any sane dunning sequence. Notices still go out and invoices still
    show as overdue — only the enforcement is withheld, and the fact
    that it was withheld is itself audited on every sweep.
    """
    company = await session.get(Company, company_id)
    if company is None:
        raise EntityNotFoundError("Company", company_id)
    previous = company.billing_never_auto_suspend
    company.billing_never_auto_suspend = payload.never_auto_suspend
    await session.flush()

    audit = FinancialAuditRecorder(FinancialAuditRepository(session))
    await audit.record(
        event_type=FinancialEventType.BILLING_REINSTATED
        if not payload.never_auto_suspend
        else FinancialEventType.BILLING_SUSPENDED,
        entity_type=FinancialEntityType.COMPANY_BILLING,
        entity_id=company_id,
        company_id=company_id,
        actor=await _actor(platform, session),
        previous_state=f"auto_suspend={not previous}",
        new_state=f"auto_suspend={not payload.never_auto_suspend}",
        reason=payload.reason,
    )


# --- checkout --------------------------------------------------------


@router.post(
    "/checkout/{invoice_id}",
    response_model=CheckoutSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def start_checkout(
    invoice_id: uuid.UUID,
    payload: StartCheckoutRequest,
    payments: Annotated[PaymentService, Depends(get_payment_service)],
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CheckoutSessionResponse:
    """Opens a gateway payment for an invoice's outstanding balance."""
    result = await payments.start_checkout(
        invoice_id=invoice_id,
        provider=payload.provider,
        actor=await _actor(platform, session),
    )
    return CheckoutSessionResponse(
        intent_id=result.intent_id,
        provider=result.provider,
        provider_reference=result.provider_reference,
        approval_url=result.approval_url,
        amount=result.amount,
        currency=result.currency,
        reused=result.reused,
    )


@router.post("/capture/{provider}/{provider_reference}", response_model=PaymentIntentResponse)
async def capture(
    provider: str,
    provider_reference: str,
    payments: Annotated[PaymentService, Depends(get_payment_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
) -> PaymentIntentResponse:
    """Captures an approved payment.

    Safe to call repeatedly — the second call finds the intent already
    settled and returns it rather than taking the money again.
    """
    await payments.capture(
        provider=provider,
        provider_reference=provider_reference,
        actor=await _actor(platform, session),
    )
    intent = await PaymentIntentRepository(session).get_by_reference(
        provider=provider, reference=provider_reference
    )
    if intent is None:
        raise EntityNotFoundError("PaymentIntent", provider_reference)
    return PaymentIntentResponse.model_validate(intent)


@router.post("/reconcile", response_model=int)
async def reconcile(
    payments: Annotated[PaymentService, Depends(get_payment_service)],
    minutes: Annotated[int, Query(ge=1, le=10_080)] = 30,
) -> int:
    """Re-reads pending intents the provider never told us about.

    The safety net for a webhook that was never delivered: a customer
    who has paid but looks unpaid is on a path towards being suspended
    for it.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=minutes)
    return await payments.reconcile_pending(older_than=cutoff)


@router.get("/intents/{company_id}", response_model=list[PaymentIntentResponse])
async def list_intents(
    company_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[PaymentIntentResponse]:
    intents = await PaymentIntentRepository(session).list_for_company(company_id, limit=limit)
    return [PaymentIntentResponse.model_validate(intent) for intent in intents]


# --- allocations ------------------------------------------------------
#
# `/allocations` is declared **above** `/allocations/{allocation_id}/…`
# and above every `/{payment_id}` route below, per the rule at the top of
# this module.


@router.get("/allocations", response_model=PaymentAllocationPageResponse)
async def list_allocations(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    company_id: Annotated[uuid.UUID | None, Query()] = None,
    payment_id: Annotated[uuid.UUID | None, Query()] = None,
    invoice_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaymentAllocationPageResponse:
    """Which payments settled which invoices, newest first.

    Reversal has existed since the payment engine shipped with no way to
    *find* an allocation to reverse: the id lived only in the database,
    so the console could offer the action but never the row. This is that
    row — and it is a read, so a read-only operator can investigate an
    allocation they are not permitted to undo.

    Grouped by currency, and every total is per currency. Nothing in this
    build converts, so a figure spanning dinars and dollars would be
    meaningless; the shape is what prevents one being computed, rather
    than a note asking callers not to.
    """
    # The invoice's company, which is also the payment's: allocating
    # across companies is refused when the allocation is written, so
    # either side answers the same question and one join is enough.
    filters: list[ColumnElement[bool]] = []
    if company_id is not None:
        filters.append(Invoice.company_id == company_id)
    if payment_id is not None:
        filters.append(PaymentAllocation.payment_id == payment_id)
    if invoice_id is not None:
        filters.append(PaymentAllocation.invoice_id == invoice_id)

    # Live and reversed are summed separately rather than netted: an
    # allocation is never deleted, and "0.20 applied" reads very
    # differently from "0.20 applied, 0.20 taken back".
    live = case((PaymentAllocation.reversed.is_(False), PaymentAllocation.amount), else_=None)
    undone = case((PaymentAllocation.reversed.is_(True), PaymentAllocation.amount), else_=None)
    totals = (
        await session.execute(
            select(
                Invoice.currency,
                func.count(),
                func.coalesce(func.sum(live), 0),
                func.coalesce(func.sum(undone), 0),
            )
            .select_from(PaymentAllocation)
            .join(Invoice, Invoice.id == PaymentAllocation.invoice_id)
            .where(*filters)
            .group_by(Invoice.currency)
            .order_by(Invoice.currency)
        )
    ).all()

    rows = (
        await session.execute(
            select(
                PaymentAllocation.id,
                PaymentAllocation.payment_id,
                Payment.reference,
                PaymentAllocation.invoice_id,
                Invoice.invoice_number,
                PaymentAllocation.amount,
                Invoice.currency,
                PaymentAllocation.created_at,
                PaymentAllocation.reversed,
                PaymentAllocation.reversed_at,
                PaymentAllocation.reversal_reason,
            )
            .select_from(PaymentAllocation)
            .join(Payment, Payment.id == PaymentAllocation.payment_id)
            .join(Invoice, Invoice.id == PaymentAllocation.invoice_id)
            .where(*filters)
            # The id breaks ties rather than leaving the order to the
            # database. Allocations written in one transaction share a
            # timestamp to the microsecond, so ordering by time alone is
            # unstable — and an unstable order under limit/offset shows a
            # row on two pages or on none.
            .order_by(PaymentAllocation.created_at.desc(), PaymentAllocation.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    page: dict[str, list[PaymentAllocationResponse]] = {}
    for row in rows:
        page.setdefault(row.currency, []).append(
            PaymentAllocationResponse(
                id=row.id,
                payment_id=row.payment_id,
                payment_reference=row.reference,
                invoice_id=row.invoice_id,
                invoice_number=row.invoice_number,
                amount=row.amount,
                currency=row.currency,
                allocated_at=row.created_at,
                reversed=row.reversed,
                reversed_at=row.reversed_at,
                reversal_reason=row.reversal_reason,
            )
        )

    # Groups come from the aggregate, not from the page, so every
    # currency the filter matched is reported with its totals even when
    # this page holds none of its rows — and so the per-currency counts
    # always add up to ``total``.
    groups = [
        PaymentAllocationCurrencyGroupResponse(
            currency=currency,
            matching=matching,
            allocated_total=allocated,
            reversed_total=reversed_amount,
            allocations=page.get(currency, []),
        )
        for currency, matching, allocated, reversed_amount in totals
    ]
    return PaymentAllocationPageResponse(
        # The one sum this shape allows, because a row count has no
        # currency to be wrong in.
        total=sum(group.matching for group in groups),
        limit=limit,
        offset=offset,
        currencies=groups,
    )


# --- reversal and refunds --------------------------------------------


@router.post("/allocations/{allocation_id}/reverse", status_code=status.HTTP_200_OK)
async def reverse_allocation(
    allocation_id: uuid.UUID,
    payload: ReverseAllocationRequest,
    payments: Annotated[PaymentService, Depends(get_payment_service)],
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, str]:
    """Un-applies money from an invoice.

    The allocation is marked reversed, never deleted, and the invoice
    reopens if it had been settled — to OVERDUE rather than ISSUED when
    its due date has passed, because a reversal does not make a late
    invoice punctual.
    """
    invoice = await payments.reverse_allocation(
        allocation_id=allocation_id,
        reason=payload.reason,
        actor=await _actor(platform, session),
    )
    return {
        "invoice_id": str(invoice.id),
        "invoice_number": invoice.invoice_number or "",
        "status": invoice.status.value,
        "amount_paid": str(invoice.amount_paid),
    }


@router.get("/{payment_id}/refundable", response_model=RefundableResponse)
async def refundable(
    payment_id: uuid.UUID,
    payments: Annotated[PaymentService, Depends(get_payment_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RefundableResponse:
    # ``Payment`` is imported at module scope now that the allocation
    # listing needs it; the local import this replaced was redundant.
    amount = await payments.refundable_amount(payment_id)
    currency = (
        await session.execute(select(Payment.currency).where(Payment.id == payment_id))
    ).scalar_one()
    return RefundableResponse(payment_id=payment_id, refundable=amount, currency=currency)


@router.post(
    "/{payment_id}/refund",
    response_model=RefundResponse,
    status_code=status.HTTP_201_CREATED,
)
async def refund(
    payment_id: uuid.UUID,
    payload: RefundRequest,
    payments: Annotated[PaymentService, Depends(get_payment_service)],
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RefundResponse:
    """Sends money back.

    Refuses to refund anything still allocated to an invoice: reverse
    the allocation first, stating why, so the invoice correctly reopens
    as unpaid. A refund that silently leaves an invoice marked paid is
    how a ledger drifts from reality without anybody noticing.
    """
    record = await payments.refund(
        payment_id=payment_id,
        amount=payload.amount,
        reason=payload.reason,
        actor=await _actor(platform, session),
    )
    return RefundResponse.model_validate(record)


@router.get("/{payment_id}/refunds", response_model=list[RefundResponse])
async def list_refunds(
    payment_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[RefundResponse]:
    from blinkengage.infrastructure.repositories.payments_repository import (
        PaymentRefundRepository,
    )

    rows = await PaymentRefundRepository(session).for_payment(payment_id)
    return [RefundResponse.model_validate(row) for row in rows]


__all__ = ["router"]
