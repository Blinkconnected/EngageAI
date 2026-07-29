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
    "ManualAdjustmentRequest",
    "ReconciliationResponse",
    "ReconciliationRowResponse",
    "TrialBalanceResponse",
    "WriteOffRequest",
]
