"""Request/response schemas for the financial ledger.

Amounts cross the wire as **strings**, like everywhere else in billing: a
JSON number becomes a float in the browser and reintroduces the drift
``Decimal`` exists to prevent.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from blinkengage.domain.ledger import LedgerAccount, LedgerEntryType

Money = Annotated[Decimal, PlainSerializer(str, return_type=str)]
MoneyIn = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=6)]


class LedgerEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entry_number: int
    occurred_at: datetime
    company_id: uuid.UUID | None
    entry_type: LedgerEntryType
    debit_account: LedgerAccount
    credit_account: LedgerAccount
    amount: Money
    currency: str
    reference_entity: str
    reference_id: uuid.UUID | None
    reference_number: str | None
    correlation_id: str | None
    description: str
    #: True for entries reconstructed from documents when the ledger was
    #: introduced, rather than recorded as they happened. Surfaced
    #: because a reconstructed entry is an inference, and a reader is
    #: entitled to know which rows are which.
    reconstructed: bool


class AccountBalanceResponse(BaseModel):
    account: LedgerAccount
    debits: Money
    credits: Money
    #: In the account's own natural direction — positive means the
    #: account holds what it normally holds.
    balance: Money


class TrialBalanceResponse(BaseModel):
    #: Which set of books this is. Reported per currency because there is
    #: no honest way to add dinars to dollars.
    currency: str
    accounts: list[AccountBalanceResponse]
    total_debits: Money
    total_credits: Money
    entry_count: int
    #: The single most important number here. If this is ever false,
    #: something has written an entry that cannot exist and every derived
    #: figure is suspect.
    in_balance: bool


class CompanyLedgerPositionResponse(BaseModel):
    company_id: uuid.UUID
    #: The currency this company is billed in. Every figure below is in it.
    currency: str
    #: What the ledger says is owed — the authoritative figure.
    outstanding: Money
    #: Money held on the company's behalf, not yet applied to anything.
    credit_balance: Money
    accounts: list[AccountBalanceResponse]


class LedgerStatementRowResponse(BaseModel):
    """One entry, as it appears on a statement for one account.

    ``debit`` and ``credit`` are this entry's effect **on the account the
    statement is running down**, which is why exactly one of them is ever
    set: the entry's own ``amount`` is always positive and says nothing
    about direction on its own — direction is carried by which account
    was debited.

    The entry is nested rather than flattened so that ``amount`` (what
    moved, immutable, on the record) cannot be mistaken for ``balance``
    (what the account stood at, derived here, on read).
    """

    entry: LedgerEntryResponse
    #: Set when this entry debited the account being run down; ``None``
    #: otherwise. Never both — an entry that debits and credits the same
    #: account is refused by the domain and by a check constraint.
    debit: Money | None
    credit: Money | None
    #: The running balance **including** this row, in the account's own
    #: natural direction — positive means the account holds what it
    #: normally holds, the same convention ``balance_of`` gives the trial
    #: balance.
    balance: Money


class LedgerStatementResponse(BaseModel):
    """One company's ledger entries in chronological order, with the
    balance of a single account carried down the page.

    **One currency, named.** Every figure here — the opening balance, the
    rows, the closing balance — is in ``currency``, and rows in any other
    currency are not in the window, the total or any balance. Nothing in
    this build converts and no exchange rate is stored, so a balance run
    across currencies would be a number with no meaning.
    ``available_currencies`` reports what the company actually has entries
    in, so a second currency is *visible* rather than silently omitted.
    """

    company_id: uuid.UUID
    #: The account being run down the page. Explicit because the running
    #: balance is meaningless without it: ``accounts_receivable`` answers
    #: "what does the customer owe", ``customer_credit`` answers "what do
    #: we hold for them", and the two run in opposite directions.
    account: LedgerAccount
    currency: str
    #: Every currency this company holds entries in. Normally one — a
    #: company is billed in a single currency and can never be
    #: re-denominated — and if it is ever two, that is a data problem a
    #: statement must not hide by quietly answering about one of them.
    available_currencies: list[str]
    #: The half-open window ``[since, until)``, echoed as the UTC instants
    #: actually queried.
    since: datetime | None
    until: datetime | None
    #: The account's balance immediately before the window. Zero when no
    #: ``since`` was given: the window then starts at the first entry
    #: there is, and nothing precedes it.
    opening_balance: Money
    #: The balance the first row of **this page** opens from — "balance
    #: brought forward". Equal to ``opening_balance`` on the first page.
    #: Paging must not restart the running balance at the window's
    #: opening, or page two would state a figure the customer never held.
    page_opening_balance: Money
    #: The balance after the last row of the **window**, not of the page.
    closing_balance: Money
    rows: list[LedgerStatementRowResponse]
    #: Entries in the window, independent of ``limit``/``offset``. A page
    #: with no total cannot render honest pagination.
    total: int
    limit: int
    offset: int


class ReconciliationRowResponse(BaseModel):
    company_id: uuid.UUID
    ledger_receivable: Money
    document_receivable: Money
    customer_credit: Money
    difference: Money
    agrees: bool


class ReconciliationResponse(BaseModel):
    rows: list[ReconciliationRowResponse]
    #: How many companies disagree. Zero is the only acceptable value in
    #: a healthy installation.
    divergences: int


class WriteOffRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ChargebackRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ManualAdjustmentRequest(BaseModel):
    """An operator-posted entry.

    Both accounts are required. There is no posting rule to fall back
    on, and inferring one side would post somewhere plausible rather than
    somewhere correct.
    """

    company_id: uuid.UUID | None = None
    debit_account: LedgerAccount
    credit_account: LedgerAccount
    amount: MoneyIn
    #: Mandatory. A manual entry with no stated reason is the single
    #: hardest thing to explain to an auditor a year later.
    description: str = Field(min_length=3, max_length=500)


__all__ = [
    "AccountBalanceResponse",
    "ChargebackRequest",
    "CompanyLedgerPositionResponse",
    "LedgerEntryResponse",
    "LedgerStatementResponse",
    "LedgerStatementRowResponse",
    "ManualAdjustmentRequest",
    "ReconciliationResponse",
    "ReconciliationRowResponse",
    "TrialBalanceResponse",
    "WriteOffRequest",
]
