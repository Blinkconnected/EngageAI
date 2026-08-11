"""Invoice administration — `/api/v1/platform/invoices/*`.

Gated at registration by `get_platform_auth`, like pricing and usage.
There is deliberately **no** endpoint that edits an issued invoice or
its lines: the way to change what a customer owes after issuance is a
credit note, and an API that offered both would make the rule advisory.

Route order: every literal path is declared before `/{invoice_id}`.
FastAPI matches in declaration order, so a literal added underneath it is
parsed as an invoice UUID and 422s — a collision this repository has
already shipped twice.
"""

import csv
import io
import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.api.deps import (
    deny_read_only_writes,
    get_company_service,
    get_db_session,
    get_financial_audit_repository,
    get_invoice_document_service,
    get_invoice_service,
    get_platform_auth,
    get_settings_dep,
)
from blinkengage.api.schemas.invoicing import (
    AllocatePaymentRequest,
    CancelInvoiceRequest,
    CreditableLinesResponse,
    CreditNotePreviewResponse,
    CreditNoteResponse,
    FinancialAuditEventResponse,
    FinancialAuditPageResponse,
    InvoiceDetailResponse,
    InvoiceEmailResponse,
    InvoiceLineResponse,
    InvoiceResponse,
    InvoiceSearchCurrencyGroup,
    InvoiceSearchResponse,
    IssueCreditNoteRequest,
    PaymentResponse,
    PreviewCreditNoteRequest,
    RecordPaymentRequest,
)
from blinkengage.application.services.billing_contacts import billing_contact_emails
from blinkengage.application.services.company_service import CompanyService
from blinkengage.application.services.financial_audit_service import (
    AuditActor,
    FinancialAuditRecorder,
)
from blinkengage.application.services.invoice_document_service import InvoiceDocumentService
from blinkengage.application.services.invoice_service import (
    InvoiceSearchResult,
    InvoiceService,
)
from blinkengage.core.auth_context import PlatformContext
from blinkengage.core.config import Settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.credit_notes import LineSelection
from blinkengage.domain.financial_audit import FinancialEntityType, FinancialEventType
from blinkengage.domain.invoicing import InvoiceStatus, amount_owed
from blinkengage.domain.money import currency_for, format_amount
from blinkengage.infrastructure.database.models.invoicing import Invoice
from blinkengage.infrastructure.documents.invoice_pdf import render_invoice_pdf
from blinkengage.infrastructure.email.mailer import Attachment, send_plain_email
from blinkengage.infrastructure.repositories.financial_audit_repository import (
    FinancialAuditRepository,
)
from blinkengage.infrastructure.repositories.invoicing_repository import InvoiceSearchFilters
from blinkengage.infrastructure.repositories.user_repository import UserRepository

logger = get_logger(__name__)

router = APIRouter(
    prefix="/platform/invoices",
    tags=["platform-invoicing"],
    # Both gates at construction: platform authority, and — for anything
    # that is not a GET — an operator who may change things. A route added
    # to this router inherits both rather than shipping unguarded.
    dependencies=[Depends(get_platform_auth), Depends(deny_read_only_writes)],
)


async def _actor(platform: PlatformContext, session: AsyncSession) -> AuditActor:
    """Resolves the operator behind a financial action.

    The email and name are captured as *values* on the audit row, not
    only as a foreign key, so an action stays attributable after the
    person who took it has left — which is the second question every
    investigation asks.
    """
    user = await UserRepository(session).get_by_id(platform.user_id)
    if user is None:
        return AuditActor(user_id=platform.user_id)
    return AuditActor(user_id=user.id, email=user.email, name=user.full_name)


async def _detail(service: InvoiceService, invoice_id: uuid.UUID) -> InvoiceDetailResponse:
    invoice = await service.get(invoice_id)
    lines = await service.lines_for(invoice_id)
    notes = await service.credit_notes_for(invoice_id)
    return InvoiceDetailResponse(
        invoice=InvoiceResponse.model_validate(invoice),
        lines=[InvoiceLineResponse.model_validate(line) for line in lines],
        credit_notes=[CreditNoteResponse.model_validate(note) for note in notes],
        amount_outstanding=amount_owed(
            status=invoice.status,
            written_off=invoice.written_off_at is not None,
            total=invoice.total_amount,
            paid=invoice.amount_paid,
            credited=invoice.amount_credited,
        ),
    )


@router.post(
    "/generate/{period_id}",
    response_model=InvoiceDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_invoice(
    period_id: uuid.UUID,
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> InvoiceDetailResponse:
    """Builds a draft invoice from a closed period's frozen snapshot.

    A **copy** — nothing is re-aggregated from usage records and nothing
    is re-priced. Idempotent: a period that already has an invoice
    returns it rather than producing a second bill for the same month.
    """
    invoice = await service.generate_for_period(period_id, actor=await _actor(platform, session))
    return await _detail(service, invoice.id)


# --- The financial audit trail ---------------------------------------
#
# Declared BEFORE `/{invoice_id}`: FastAPI matches in registration
# order, so with the parameterised route first, "audit" is parsed as an
# invoice UUID and every one of these 422s.


@router.get(
    "/audit/entity/{entity_type}/{entity_id}", response_model=list[FinancialAuditEventResponse]
)
async def audit_for_entity(
    entity_type: FinancialEntityType,
    entity_id: uuid.UUID,
    repository: Annotated[FinancialAuditRepository, Depends(get_financial_audit_repository)],
) -> list[FinancialAuditEventResponse]:
    """One document's complete history, oldest first.

    The order an investigator reads it in: what it was, what happened to
    it, who did each thing and why.
    """
    return [
        FinancialAuditEventResponse.model_validate(event)
        for event in await repository.for_entity(entity_type=entity_type.value, entity_id=entity_id)
    ]


@router.get(
    "/audit/correlation/{correlation_id}",
    response_model=list[FinancialAuditEventResponse],
)
async def audit_for_correlation(
    correlation_id: str,
    repository: Annotated[FinancialAuditRepository, Depends(get_financial_audit_repository)],
) -> list[FinancialAuditEventResponse]:
    """Everything that happened because of one action.

    Allocating a payment touches the allocation *and* the invoice;
    issuing a credit note touches the note *and* settles the invoice.
    Matching those by timestamp stops working the moment two operators
    act in the same second, which is why they share an id instead.
    """
    return [
        FinancialAuditEventResponse.model_validate(event)
        for event in await repository.for_correlation(correlation_id)
    ]


@router.get("/audit", response_model=FinancialAuditPageResponse)
async def search_audit(
    repository: Annotated[FinancialAuditRepository, Depends(get_financial_audit_repository)],
    company_id: Annotated[uuid.UUID | None, Query()] = None,
    entity_type: Annotated[FinancialEntityType | None, Query()] = None,
    event_type: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FinancialAuditPageResponse:
    """The financial audit trail, newest first.

    Returns the total alongside the page. The repository already counts
    the matches, and a paginated endpoint that discards it leaves a reader
    unable to tell "these are all of them" from "there are four hundred
    more" — on the one screen whose whole purpose is completeness.

    ``limit`` and ``offset`` are bounded rather than silently clamped: an
    out-of-range page is a caller's mistake, and answering a different
    question than the one asked is how it stays a mistake.
    """
    events, total = await repository.search(
        company_id=company_id,
        entity_type=entity_type.value if entity_type else None,
        event_type=event_type,
        limit=limit,
        offset=offset,
    )
    return FinancialAuditPageResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[FinancialAuditEventResponse.model_validate(event) for event in events],
    )


# --- Cross-company search --------------------------------------------
#
# Declared BEFORE `/{invoice_id}`, for the same reason as the audit
# routes above: with the parameterised route first, "search" is parsed as
# an invoice UUID and every request 422s.

#: The most rows one CSV export writes.
#:
#: An unbounded export of every invoice ever issued is a request that
#: times out holding a database connection, and a finance team that gets
#: nothing back simply retries it. Five thousand rows is comfortably a
#: large installation's full year, opens in a spreadsheet without
#: complaint, and renders in well under a second.
#:
#: A filter matching more is truncated rather than refused — a partial
#: answer beats no answer — but never *silently*: the cap is stated in
#: the JSON response before anybody downloads anything, and the export
#: itself says so in three places, including its own filename, which is
#: the only one still visible to whoever opens the file next week.
EXPORT_ROW_CAP = 5000

_CSV_MEDIA_TYPE = "text/csv"

#: `currency` sits immediately before the first amount rather than at the
#: end of the row: a spreadsheet full of bare numbers in two currencies
#: is exactly the document this API refuses to produce a total for.
_CSV_COLUMNS = (
    "invoice_number",
    "status",
    "customer_name",
    "customer_slug",
    "company_id",
    "currency",
    "subtotal_amount",
    "total_amount",
    "amount_paid",
    "amount_credited",
    "amount_outstanding",
    "issued_at",
    "due_date",
    "paid_at",
    "written_off_at",
    "period_start",
    "period_end",
    "invoice_id",
    "billing_period_id",
)


#: Characters a spreadsheet treats as the start of a formula rather than
#: text. Tab and carriage return are here because Excel strips them and
#: then evaluates whatever follows.
_FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")


def _defuse(text: str) -> str:
    """Stops a spreadsheet executing a cell it was handed as data.

    Customer names are written by tenants and read by our finance team in
    Excel, which is the one place a cell beginning ``=`` stops being text
    and becomes a command. A leading apostrophe is the standard, lossless
    guard: Excel and LibreOffice both render the value unchanged and
    neither evaluates it.

    Applied to text only. Amounts, dates and identifiers are generated
    here and cannot begin with a formula character — quoting a negative
    amount would corrupt the very figures the export exists to carry.
    """
    return f"'{text}" if text.startswith(_FORMULA_LEAD) else text


def _cell(value: object) -> str:
    """A CSV cell. Amounts stay decimal strings — never floats, never
    formatted with a symbol or thousands separators, so what a
    spreadsheet parses is exactly what the database holds."""
    if value is None:
        return ""
    if isinstance(value, Decimal | uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, InvoiceStatus):
        return value.value
    return _defuse(str(value))


def _csv_body(invoices: list[InvoiceResponse]) -> str:
    """Renders the page as RFC 4180 CSV.

    Built from the same ``InvoiceResponse`` objects the JSON branch
    returns, so the export and the screen cannot drift apart.

    There is deliberately **no totals row**. A column of amounts in two
    currencies has no honest sum, and a spreadsheet's own ``SUM()`` over
    the column would produce one anyway — but that is the reader's
    arithmetic, not a figure this API stood behind.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_COLUMNS)
    for invoice in invoices:
        writer.writerow(
            [
                _cell(invoice.invoice_number),
                _cell(invoice.status),
                _cell(invoice.customer_name),
                _cell(invoice.customer_slug),
                _cell(invoice.company_id),
                _cell(invoice.currency),
                _cell(invoice.subtotal_amount),
                _cell(invoice.total_amount),
                _cell(invoice.amount_paid),
                _cell(invoice.amount_credited),
                _cell(
                    amount_owed(
                        status=invoice.status,
                        written_off=invoice.written_off_at is not None,
                        total=invoice.total_amount,
                        paid=invoice.amount_paid,
                        credited=invoice.amount_credited,
                    )
                ),
                _cell(invoice.issued_at),
                _cell(invoice.due_date),
                _cell(invoice.paid_at),
                _cell(invoice.written_off_at),
                _cell(invoice.period_start),
                _cell(invoice.period_end),
                _cell(invoice.id),
                _cell(invoice.billing_period_id),
            ]
        )
    # A byte-order mark, because this is a finance export and Excel reads
    # a BOM-less UTF-8 file as the local codepage — which turns an Arabic
    # customer name into mojibake on the one screen somebody reconciles
    # against. Every CSV reader in common use tolerates it.
    return "﻿" + buffer.getvalue()


def _csv_export(result: InvoiceSearchResult) -> Response:
    invoices = [InvoiceResponse.model_validate(invoice) for invoice in result.invoices]
    truncated = result.total > len(invoices)
    stamp = datetime.now(UTC).date().isoformat()
    # The truncation is in the *filename* as well as the headers because
    # the headers are gone the moment the file lands on a disk, and a
    # finance team reconciling against a short file has no way to know it
    # is short. `X-Export-*` needs `Access-Control-Expose-Headers` to be
    # readable from a browser at all; a filename never does.
    filename = (
        f"invoices-{stamp}-TRUNCATED-{len(invoices)}-of-{result.total}.csv"
        if truncated
        else f"invoices-{stamp}.csv"
    )
    return Response(
        content=_csv_body(invoices),
        media_type=_CSV_MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Export-Row-Cap": str(EXPORT_ROW_CAP),
            "X-Export-Row-Count": str(len(invoices)),
            "X-Export-Total-Matched": str(result.total),
            "X-Export-Truncated": "true" if truncated else "false",
        },
    )


def _search_response(
    result: InvoiceSearchResult, *, limit: int, offset: int
) -> InvoiceSearchResponse:
    """Partitions the page into its currencies' groups.

    The groups come from the subtotals, which are computed over the same
    predicate on the same session as the page — so every invoice on the
    page has a group to land in, and no row can be silently dropped by
    the regrouping.
    """
    page: dict[str, list[InvoiceResponse]] = {}
    for invoice in result.invoices:
        page.setdefault(invoice.currency, []).append(InvoiceResponse.model_validate(invoice))
    return InvoiceSearchResponse(
        total=result.total,
        limit=limit,
        offset=offset,
        currencies=[
            InvoiceSearchCurrencyGroup(
                currency=subtotal.currency,
                invoice_count=subtotal.invoice_count,
                total_amount=subtotal.total_amount,
                amount_paid=subtotal.amount_paid,
                amount_credited=subtotal.amount_credited,
                amount_outstanding=subtotal.amount_outstanding,
                items=page.get(subtotal.currency, []),
            )
            for subtotal in result.subtotals
        ],
        export_row_cap=EXPORT_ROW_CAP,
    )


@router.get(
    "/search",
    # Declared explicitly rather than inferred from the return
    # annotation, which is a union FastAPI cannot turn into a schema.
    # Without this the console's one cross-company screen would be the
    # only billing endpoint with no documented response shape — and a
    # returned `Response` still short-circuits serialization, so the CSV
    # branch is unaffected.
    response_model=InvoiceSearchResponse,
    responses={
        200: {
            "content": {
                "text/csv": {
                    "schema": {"type": "string", "format": "binary"},
                    "example": "invoice_number,status,...",
                }
            },
            "description": "The page, or the whole filter as CSV when `export=csv`.",
        }
    },
)
async def search_invoices(
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
    company_id: Annotated[uuid.UUID | None, Query()] = None,
    invoice_status: Annotated[InvoiceStatus | None, Query(alias="status")] = None,
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    issued_from: Annotated[date | None, Query()] = None,
    issued_to: Annotated[date | None, Query()] = None,
    # No minimum length: a console that clears its search box sends
    # `q=`, and an empty box means "no text filter" rather than a
    # validation error.
    q: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    export: Annotated[Literal["csv"] | None, Query()] = None,
) -> InvoiceSearchResponse | Response:
    """Invoices across every company, narrowed by any of the filters.

    Every parameter is optional — including ``company_id``, which is the
    gap this fills: ``GET /platform/invoices`` requires one, so a finance
    team could not answer "which invoices are overdue" at all without
    already knowing whose.

    ``q`` matches an invoice **number**, case-insensitively, anywhere in
    it. A draft has no number, so a text search never returns one; that
    is correct, since a draft is an operator's working copy rather than a
    document anybody could be quoting a number from.

    ``issued_from`` / ``issued_to`` are inclusive **dates** and bound
    ``issued_at``, so a never-issued draft falls outside any date range.

    **Amounts are grouped by currency.** This installation bills in more
    than one, converts nothing and stores no exchange rate, so there is
    no response field here holding a figure that spans them — see
    ``InvoiceSearchCurrencyGroup``. The one cross-currency number is
    ``total``, and it is a count.

    ``?export=csv`` returns the **current filter** as a file rather than
    the current page: ``limit`` and ``offset`` are ignored, and the
    export stops at ``export_row_cap`` rows. Truncation is announced in
    ``X-Export-Truncated``, ``X-Export-Total-Matched`` and the filename.
    """
    if issued_from is not None and issued_to is not None and issued_from > issued_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"issued_from ({issued_from}) is after issued_to ({issued_to}); that range "
                "cannot match anything. Returning an empty page would look like an answer."
            ),
        )

    filters = InvoiceSearchFilters(
        company_id=company_id,
        status=invoice_status,
        # Rejects a currency this build cannot bill in (422) rather than
        # filtering on it and returning an empty page — "no invoices" and
        # "no such currency" are different answers.
        currency=currency_for(currency).code if currency else None,
        issued_from=datetime.combine(issued_from, time.min, tzinfo=UTC) if issued_from else None,
        # Exclusive, at the start of the day *after* `issued_to`. An
        # inclusive bound compared against a timestamp would drop every
        # invoice issued after midnight on the last day of the range —
        # which is all of them.
        issued_before=(
            datetime.combine(issued_to + timedelta(days=1), time.min, tzinfo=UTC)
            if issued_to
            else None
        ),
        number_query=q,
    )

    if export is not None:
        return _csv_export(await service.search(filters, limit=EXPORT_ROW_CAP, offset=0))
    return _search_response(
        await service.search(filters, limit=limit, offset=offset), limit=limit, offset=offset
    )


@router.get("/{invoice_id}", response_model=InvoiceDetailResponse)
async def get_invoice(
    invoice_id: uuid.UUID,
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> InvoiceDetailResponse:
    return await _detail(service, invoice_id)


@router.get("", response_model=list[InvoiceResponse])
async def list_invoices(
    company_id: uuid.UUID,
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
    invoice_status: InvoiceStatus | None = None,
) -> list[InvoiceResponse]:
    return [
        InvoiceResponse.model_validate(invoice)
        for invoice in await service.list_for_company(company_id, status=invoice_status)
    ]


@router.post("/{invoice_id}/issue", response_model=InvoiceDetailResponse)
async def issue_invoice(
    invoice_id: uuid.UUID,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> InvoiceDetailResponse:
    """Assigns the next number in the series and freezes the document.

    After this it cannot be edited — only credited or cancelled.
    """
    await service.issue(
        invoice_id=invoice_id,
        actor_user_id=platform.user_id,
        actor=await _actor(platform, session),
    )
    return await _detail(service, invoice_id)


@router.post("/{invoice_id}/cancel", response_model=InvoiceDetailResponse)
async def cancel_invoice(
    invoice_id: uuid.UUID,
    payload: CancelInvoiceRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> InvoiceDetailResponse:
    """Withdraws an invoice that should never have existed.

    A *partly* wrong invoice is corrected with a credit note instead.
    The number stays consumed — reusing it would mean two documents
    shared a number.
    """
    await service.cancel(
        invoice_id=invoice_id,
        reason=payload.reason,
        actor_user_id=platform.user_id,
        actor=await _actor(platform, session),
    )
    return await _detail(service, invoice_id)


# --- the printed document -------------------------------------------


def _pdf_response(pdf: bytes, number: str) -> Response:
    """One rendered invoice, as a download.

    ``inline`` rather than ``attachment``: an operator on the phone with a
    customer wants to *look* at the document, and every browser's own PDF
    viewer gives them print, zoom and save for free. The filename is still
    supplied, so saving it produces something recognisable rather than the
    invoice id.
    """
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{number}.pdf"'},
    )


async def _render(
    invoice: Invoice,
    documents: InvoiceDocumentService,
    companies: CompanyService,
) -> bytes:
    """The document, with the customer's logo when there is one.

    A logo that cannot be fetched is never a reason an invoice fails to
    render — the storage backend being briefly unreachable must not stop a
    customer downloading their bill. Same rule as every other export in
    this codebase.
    """
    document = await documents.build(invoice)
    try:
        logo = await companies.get_logo(company_id=invoice.company_id)
    except Exception:  # noqa: BLE001 — see the docstring: never fatal.
        logo = None
    return render_invoice_pdf(document, logo=logo)


@router.get(
    "/{invoice_id}/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "The invoice."}},
)
async def invoice_pdf(
    invoice_id: uuid.UUID,
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
    documents: Annotated[InvoiceDocumentService, Depends(get_invoice_document_service)],
    companies: Annotated[CompanyService, Depends(get_company_service)],
) -> Response:
    """An issued invoice, rendered from its frozen snapshot.

    **A draft has no PDF.** It carries no number, nothing has been sent to
    anybody, and a document that looks like an invoice but is not one is
    the single most confusing thing this endpoint could produce.

    Nothing here is recalculated. Every figure — each line's price, the
    tier that selected it, the totals — is read from what was written when
    the invoice was issued, which is why this can be reprinted years later
    and still say what the customer was charged.
    """
    invoice = await service.get(invoice_id)
    if invoice.status is InvoiceStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This invoice is still a draft. Issue it first — a draft has no number.",
        )
    return _pdf_response(
        await _render(invoice, documents, companies), invoice.invoice_number or str(invoice.id)
    )


@router.post("/{invoice_id}/email", response_model=InvoiceEmailResponse)
async def email_invoice(
    invoice_id: uuid.UUID,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
    documents: Annotated[InvoiceDocumentService, Depends(get_invoice_document_service)],
    companies: Annotated[CompanyService, Depends(get_company_service)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> InvoiceEmailResponse:
    """Sends the invoice to the customer's billing contacts, as a PDF.

    The same people a dunning notice reaches — see ``billing_contacts``. An
    invoice going to one set of addresses and the overdue notice about it
    going to another is how each recipient comes to assume the other was
    told.

    Refuses rather than half-succeeding when a company has nobody with
    billing access: "sent to nobody" reported as success is the worst
    possible answer, because the operator stops chasing it.

    Audited, with the recipients recorded: six months later, "did we ever
    send it?" is the question, and the audit trail is where it is answered.
    """
    invoice = await service.get(invoice_id)
    if invoice.status is InvoiceStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This invoice is still a draft, so there is nothing to send.",
        )

    recipients = await billing_contact_emails(session, invoice.company_id)
    if not recipients:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Nobody at this company has billing access, so there is nowhere to send it. "
                "Grant somebody the billing permission first."
            ),
        )

    number = invoice.invoice_number or str(invoice.id)
    attachment = Attachment(
        filename=f"{number}.pdf",
        content_type="application/pdf",
        data=await _render(invoice, documents, companies),
    )
    subject = f"{settings.app_name} invoice {number}"
    body = (
        f"Your {settings.app_name} invoice {number} is attached.\n\n"
        f"Amount: {format_amount(invoice.total_amount, currency=currency_for(invoice.currency))} "
        f"{invoice.currency}\n"
        f"Due: {invoice.due_date.isoformat() if invoice.due_date else 'on receipt'}\n"
    )
    # Each address is attempted, and what happened to each is recorded —
    # including when the relay fails partway. Letting the first failure
    # propagate would leave earlier recipients holding the invoice, later
    # ones with nothing, and no audit row at all: the operator would see a
    # 500 and reasonably conclude nothing was sent.
    sent: list[str] = []
    failed: list[str] = []
    for address in recipients:
        try:
            await send_plain_email(
                settings,
                to_address=address,
                subject=subject,
                body=body,
                attachments=[attachment],
            )
        except Exception as error:  # noqa: BLE001 — recorded, then reported.
            logger.warning(
                "invoice_email.failed",
                invoice_id=str(invoice.id),
                recipient=address,
                error=str(error),
            )
            failed.append(address)
        else:
            sent.append(address)

    await FinancialAuditRecorder(FinancialAuditRepository(session)).record(
        event_type=FinancialEventType.INVOICE_EMAILED,
        entity_type=FinancialEntityType.INVOICE,
        entity_id=invoice.id,
        company_id=invoice.company_id,
        actor=await _actor(platform, session),
        previous_state=None,
        new_state=None,
        amount=invoice.total_amount,
        currency=invoice.currency,
        details={"invoice_number": number, "recipients": sent, "failed": failed},
    )
    if not sent:
        # Every address failed. Reporting success here would be the worst
        # possible answer, because the operator stops chasing it.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "The invoice could not be delivered to anybody. "
                "Check the outbound mail settings and try again."
            ),
        )
    return InvoiceEmailResponse(invoice_id=invoice.id, sent_to=sent, failed=failed)


# --- credit notes ----------------------------------------------------


def _selections(payload: PreviewCreditNoteRequest) -> list[LineSelection]:
    """The wire form, as the domain wants it.

    Note what does not appear: a description, a price or an amount. Those
    come from the invoice line being credited, which is what makes every
    figure on a credit note traceable to something that was actually
    billed.
    """
    return [
        LineSelection(
            invoice_line_id=line.invoice_line_id,
            quantity=line.quantity,
            reason=line.reason,
        )
        for line in payload.lines
    ]


@router.get("/{invoice_id}/creditable", response_model=CreditableLinesResponse)
async def creditable_lines(
    invoice_id: uuid.UUID,
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> CreditableLinesResponse:
    """What is still creditable on this invoice, line by line.

    The read behind the credit dialog. Every figure comes from documents
    already written — the issued line, and what earlier credit notes took
    off it — so a screen can show a quantity field bounded by something
    real instead of letting an operator discover the limit by being
    refused.

    Note the two ceilings. The line remainders can add up to more than
    ``amount_creditable`` when an older whole-invoice credit note consumed
    credit without naming a line; the difference is reported as
    ``unattributed_credited_amount`` rather than silently shrinking the
    lines, because a console that cannot explain the gap will be asked to.
    """
    return CreditableLinesResponse.model_validate(await service.creditable_lines(invoice_id))


@router.post("/{invoice_id}/credit-notes/preview", response_model=CreditNotePreviewResponse)
async def preview_credit_note(
    invoice_id: uuid.UUID,
    payload: PreviewCreditNoteRequest,
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> CreditNotePreviewResponse:
    """What the credit note would say, before anything is written.

    A POST that writes nothing — the selection is a list, which does not
    belong in a query string. It runs the **write path's own** validation
    and arithmetic, so a total an operator approves here is the total the
    document will carry, and a selection accepted here cannot be refused a
    moment later by the save.
    """
    return CreditNotePreviewResponse.model_validate(
        await service.preview_credit_note(invoice_id=invoice_id, selections=_selections(payload))
    )


@router.post(
    "/{invoice_id}/credit-notes",
    response_model=CreditNoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def issue_credit_note(
    invoice_id: uuid.UUID,
    payload: IssueCreditNoteRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CreditNoteResponse:
    """The only way to change what a customer owes after issuance.

    The invoice keeps saying exactly what it said; the credit note says
    what was given back. Both documents exist for anybody reconciling
    them later.
    """
    note = await service.issue_credit_note(
        invoice_id=invoice_id,
        selections=_selections(payload),
        reason=payload.reason,
        actor_user_id=platform.user_id,
        actor=await _actor(platform, session),
    )
    return CreditNoteResponse.model_validate(note)


@router.post("/payments", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def record_payment(
    payload: RecordPaymentRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PaymentResponse:
    """Records money received, independently of any invoice.

    Allocation is a separate call, which is what lets one bank transfer
    clear three invoices and lets an overpayment sit as a credit balance.
    """
    payment = await service.record_payment(
        company_id=payload.company_id,
        amount=payload.amount,
        received_at=payload.received_at,
        reference=payload.reference,
        note=payload.note,
        actor_user_id=platform.user_id,
        actor=await _actor(platform, session),
    )
    return PaymentResponse.model_validate(payment)


@router.get("/payments/company/{company_id}", response_model=list[PaymentResponse])
async def list_payments(
    company_id: uuid.UUID,
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> list[PaymentResponse]:
    return [
        PaymentResponse.model_validate(payment)
        for payment in await service.payments_for_company(company_id)
    ]


@router.post("/payments/{payment_id}/allocate", response_model=InvoiceDetailResponse)
async def allocate_payment(
    payment_id: uuid.UUID,
    payload: AllocatePaymentRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> InvoiceDetailResponse:
    """Applies part of a payment to an invoice.

    Refuses to allocate more of a payment than was received, or more to
    an invoice than it still owes — both would show up later as a
    balance nobody can explain.
    """
    await service.allocate(
        payment_id=payment_id,
        invoice_id=payload.invoice_id,
        amount=payload.amount,
        actor_user_id=platform.user_id,
        actor=await _actor(platform, session),
    )
    return await _detail(service, payload.invoice_id)
