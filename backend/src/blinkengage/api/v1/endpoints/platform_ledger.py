"""The financial ledger — `/api/v1/platform/ledger/*`.

Gated at registration by ``get_platform_auth``, like the rest of billing.

There is deliberately **no** endpoint that edits or deletes an entry. A
mistake is corrected by posting the opposite entry, and an API offering
both would make the rule advisory. The only write is a manual
adjustment, which is itself an entry.

Route order: every literal path is registered before any `/{id}` path.
FastAPI matches in declaration order, and this codebase has shipped that
collision twice — once on the PayPal webhook, once on the invoice audit
route.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.api.deps import (
    deny_read_only_writes,
    get_db_session,
    get_ledger_reconciliation,
    get_ledger_service,
    get_payment_service,
    get_platform_auth,
)
from blinkengage.api.schemas.ledger import (
    AccountBalanceResponse,
    ChargebackRequest,
    CompanyLedgerPositionResponse,
    LedgerEntryResponse,
    ManualAdjustmentRequest,
    ReconciliationResponse,
    ReconciliationRowResponse,
    TrialBalanceResponse,
    WriteOffRequest,
)
from blinkengage.application.services.financial_audit_service import AuditActor
from blinkengage.application.services.ledger_service import (
    AccountBalance,
    LedgerReconciliation,
    LedgerService,
)
from blinkengage.application.services.payment_service import PaymentService
from blinkengage.core.auth_context import PlatformContext
from blinkengage.domain.ledger import LedgerAccount, LedgerEntryType
from blinkengage.infrastructure.repositories.ledger_repository import LedgerRepository
from blinkengage.infrastructure.repositories.user_repository import UserRepository

router = APIRouter(
    prefix="/platform/ledger",
    tags=["platform-ledger"],
    # Both gates at construction: platform authority, and — for anything
    # that is not a GET — an operator who may change things. A route added
    # to this router inherits both rather than shipping unguarded.
    dependencies=[Depends(get_platform_auth), Depends(deny_read_only_writes)],
)


def _balance(row: AccountBalance) -> AccountBalanceResponse:
    return AccountBalanceResponse(
        account=row.account, debits=row.debits, credits=row.credits, balance=row.balance
    )


async def _actor(platform: PlatformContext, session: AsyncSession) -> AuditActor:
    user = await UserRepository(session).get_by_id(platform.user_id)
    if user is None:
        return AuditActor(user_id=platform.user_id)
    return AuditActor(user_id=user.id, email=user.email, name=user.full_name)


# --- the books --------------------------------------------------------


@router.get("/trial-balance", response_model=list[TrialBalanceResponse])
async def trial_balance(
    ledger: Annotated[LedgerService, Depends(get_ledger_service)],
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
) -> list[TrialBalanceResponse]:
    """Every account, and the proof that the books balance.

    **One set of books per currency**, returned as a list rather than a
    combined total: adding dinars to dollars produces a number that means
    nothing, and this build stores no exchange rate to make it mean
    something. Pass ``currency`` for one.

    ``in_balance`` is what to watch: total debits must equal total
    credits. Every entry carries both sides, so this cannot go false
    through normal use — which is exactly why it is worth checking.
    """
    books = (
        [await ledger.trial_balance(currency)]
        if currency
        else await ledger.trial_balances()
    )
    return [
        TrialBalanceResponse(
            currency=tb.currency,
            accounts=[_balance(row) for row in tb.accounts],
            total_debits=tb.total_debits,
            total_credits=tb.total_credits,
            entry_count=tb.entry_count,
            in_balance=tb.in_balance,
        )
        for tb in books
    ]


@router.get("/reconciliation", response_model=ReconciliationResponse)
async def reconciliation(
    reconciler: Annotated[LedgerReconciliation, Depends(get_ledger_reconciliation)],
    company_id: Annotated[uuid.UUID | None, Query()] = None,
    only_divergences: Annotated[bool, Query()] = True,
) -> ReconciliationResponse:
    """Does the document projection still agree with the ledger?

    The invoice columns are a cache of what the ledger says, kept because
    "what is still owed" is read on every list screen. This is the check
    that they have not drifted — exposed rather than buried in a log,
    because the only useful response to a divergence is a person looking
    at it.
    """
    rows = await reconciler.rows(company_id=company_id)
    diverged = [row for row in rows if not row.agrees]
    shown = diverged if only_divergences else rows
    return ReconciliationResponse(
        rows=[
            ReconciliationRowResponse(
                company_id=row.company_id,
                ledger_receivable=row.ledger_receivable,
                document_receivable=row.document_receivable,
                customer_credit=row.customer_credit,
                difference=row.difference,
                agrees=row.agrees,
            )
            for row in shown
        ],
        divergences=len(diverged),
    )


@router.get("/entries", response_model=list[LedgerEntryResponse])
async def entries(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    company_id: Annotated[uuid.UUID | None, Query()] = None,
    account: Annotated[LedgerAccount | None, Query()] = None,
    entry_type: Annotated[LedgerEntryType | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[LedgerEntryResponse]:
    """The ledger itself, newest first."""
    rows = await LedgerRepository(session).statement(
        company_id=company_id,
        account=account,
        entry_type=entry_type,
        since=since,
        limit=limit,
    )
    return [LedgerEntryResponse.model_validate(row) for row in rows]


@router.get("/correlation/{correlation_id}", response_model=list[LedgerEntryResponse])
async def by_correlation(
    correlation_id: str,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[LedgerEntryResponse]:
    """Every movement produced by one logical action."""
    rows = await LedgerRepository(session).for_correlation(correlation_id)
    return [LedgerEntryResponse.model_validate(row) for row in rows]


@router.get(
    "/reference/{reference_entity}/{reference_id}",
    response_model=list[LedgerEntryResponse],
)
async def by_reference(
    reference_entity: str,
    reference_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[LedgerEntryResponse]:
    """Everything the ledger says about one document."""
    rows = await LedgerRepository(session).for_reference(
        reference_entity=reference_entity, reference_id=reference_id
    )
    return [LedgerEntryResponse.model_validate(row) for row in rows]


@router.post(
    "/adjustments",
    response_model=LedgerEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def manual_adjustment(
    payload: ManualAdjustmentRequest,
    ledger: Annotated[LedgerService, Depends(get_ledger_service)],
) -> LedgerEntryResponse:
    """Posts an operator-authored entry.

    The only write on this router, and it is still an *entry* — the
    ledger has no other kind of mutation. Both accounts are required
    because there is no posting rule to fall back on.
    """
    entry = await ledger.record(
        entry_type=LedgerEntryType.MANUAL_ADJUSTMENT,
        company_id=payload.company_id,
        amount=payload.amount,
        reference_entity="manual_adjustment",
        reference_id=None,
        description=payload.description,
        debit=payload.debit_account,
        credit=payload.credit_account,
    )
    return LedgerEntryResponse.model_validate(entry)


@router.post("/write-offs/{invoice_id}", status_code=status.HTTP_200_OK)
async def write_off(
    invoice_id: uuid.UUID,
    payload: WriteOffRequest,
    payments: Annotated[PaymentService, Depends(get_payment_service)],
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, str]:
    """Abandons a receivable as uncollectable.

    Leaves the invoice's status alone: it remains unpaid and overdue,
    which is the truth. The ledger is where the receivable stops being an
    asset and becomes bad debt.
    """
    amount = await payments.write_off(
        invoice_id=invoice_id,
        reason=payload.reason,
        actor=await _actor(platform, session),
    )
    return {"invoice_id": str(invoice_id), "written_off": str(amount)}


@router.post("/chargebacks/{allocation_id}", status_code=status.HTTP_200_OK)
async def chargeback(
    allocation_id: uuid.UUID,
    payload: ChargebackRequest,
    payments: Annotated[PaymentService, Depends(get_payment_service)],
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, str]:
    """Records money taken back by a bank.

    Reverses the allocation and takes the cash out. Distinct from a
    refund because the cause matters: a refund is something we chose to
    do, a chargeback is something done to us, and a ledger where both
    look identical cannot answer "how much are we losing to disputes".
    """
    invoice = await payments.record_chargeback(
        allocation_id=allocation_id,
        reason=payload.reason,
        actor=await _actor(platform, session),
    )
    return {
        "invoice_id": str(invoice.id),
        "invoice_number": invoice.invoice_number or "",
        "status": invoice.status.value,
    }


# --- per company (registered last: `/{company_id}` matches anything) --


@router.get("/{company_id}", response_model=CompanyLedgerPositionResponse)
async def company_position(
    company_id: uuid.UUID,
    ledger: Annotated[LedgerService, Depends(get_ledger_service)],
) -> CompanyLedgerPositionResponse:
    """What one company owes and holds, derived from the entries."""
    currency = await ledger.company_currency(company_id)
    return CompanyLedgerPositionResponse(
        company_id=company_id,
        currency=currency,
        outstanding=await ledger.outstanding(company_id),
        credit_balance=await ledger.credit_balance(company_id),
        accounts=[_balance(row) for row in await ledger.balances(company_id)],
    )


__all__ = ["router"]
