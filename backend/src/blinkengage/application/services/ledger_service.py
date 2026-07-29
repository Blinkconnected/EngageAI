"""The financial ledger: writing entries, and deriving figures from them.

See ``docs/architecture/billing.md``.

The ledger is the financial source of truth. Invoices, credit notes and
payments are documents that *describe* commitments; the ledger records
what those documents did to the money, and any balance is a question
about the ledger rather than a column on a document.

**Entries are written on the same session as the operation they
describe.** A ledger on a separate connection, or published through a
broker, is one that can disagree with the thing it is recording — and a
ledger that disagrees is worse than none, because it will be believed.
Either the invoice is issued and the entry exists, or neither happened.

**The denormalized columns on documents remain, as a projection.**
``invoices.amount_paid`` is read on every list screen, and summing the
ledger per row to render a table would be an N+1. They are a *cache* of
what the ledger says, not a second record of it — and ``reconcile()``
proves the two agree. A cache nobody checks is just a second source of
truth with extra steps.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.core.correlation import get_correlation_id
from blinkengage.domain.ledger import (
    STATEMENT_ACCOUNTS,
    LedgerAccount,
    LedgerEntryType,
    balance_of,
    posting_for,
    validate_accounts,
    validate_amount,
)
from blinkengage.domain.money import BILLING_CURRENCY, currency_for, to_storage, zero
from blinkengage.infrastructure.database.models.ledger import LedgerEntry
from blinkengage.infrastructure.repositories.invoicing_repository import (
    DocumentNumberRepository,
)
from blinkengage.infrastructure.repositories.ledger_repository import (
    LEDGER_SEQUENCE_PREFIX,
    LEDGER_SEQUENCE_YEAR,
    LedgerRepository,
)


@dataclass(frozen=True, slots=True)
class AccountBalance:
    account: LedgerAccount
    debits: Decimal
    credits: Decimal
    #: In the account's own natural direction: positive means it holds
    #: what it normally holds. Callers get "how much" without needing to
    #: know which way the account runs.
    balance: Decimal


@dataclass(frozen=True, slots=True)
class TrialBalance:
    """Every account in one currency, and the proof that it balances.

    **Per currency, never combined.** Adding dinars to dollars produces a
    number that means nothing, and this build stores no exchange rate to
    make it mean something. A set of books per currency is also what an
    accountant expects.

    ``in_balance`` is the single most important number in the system: if
    total debits ever stop equalling total credits, something has written
    an entry that cannot exist, and every derived figure is suspect.
    """

    currency: str
    accounts: tuple[AccountBalance, ...]
    total_debits: Decimal
    total_credits: Decimal
    entry_count: int

    @property
    def in_balance(self) -> bool:
        return self.total_debits == self.total_credits


@dataclass(frozen=True, slots=True)
class ReconciliationRow:
    """One company's ledger position against the document projection."""

    company_id: uuid.UUID
    #: What the ledger says is outstanding.
    ledger_receivable: Decimal
    #: What the invoice columns say is outstanding.
    document_receivable: Decimal
    #: Unallocated money held on the customer's behalf.
    customer_credit: Decimal

    @property
    def difference(self) -> Decimal:
        return self.ledger_receivable - self.document_receivable

    @property
    def agrees(self) -> bool:
        return self.difference == zero()


class LedgerService:
    def __init__(
        self, *, entries: LedgerRepository, numbers: DocumentNumberRepository
    ) -> None:
        self._entries = entries
        self._numbers = numbers

    # --- writing -----------------------------------------------------

    async def record(
        self,
        *,
        entry_type: LedgerEntryType,
        company_id: uuid.UUID | None,
        amount: Decimal,
        reference_entity: str,
        reference_id: uuid.UUID | None,
        description: str,
        reference_number: str | None = None,
        occurred_at: datetime | None = None,
        debit: LedgerAccount | None = None,
        credit: LedgerAccount | None = None,
        currency: str | None = None,
    ) -> LedgerEntry:
        """Posts one balanced entry.

        The accounts come from the operation's posting rule
        (``domain/ledger.py``) unless both are given explicitly, which is
        only how a manual adjustment works. Passing one and not the other
        is refused rather than half-inferred — an entry with a guessed
        side is exactly the kind of plausible-looking mistake that is
        found months later.
        """
        if (debit is None) != (credit is None):
            raise ValueError(
                "Give both accounts or neither: an entry with one inferred side "
                "would post somewhere plausible rather than somewhere correct."
            )
        if debit is None or credit is None:
            posting = posting_for(entry_type)
            debit, credit = posting.debit, posting.credit

        validate_amount(amount)
        validate_accounts(debit, credit)

        entry_number = await self._numbers.next_value(
            prefix=LEDGER_SEQUENCE_PREFIX, year=LEDGER_SEQUENCE_YEAR
        )
        return await self._entries.add(
            LedgerEntry(
                entry_number=entry_number,
                occurred_at=occurred_at or datetime.now(UTC),
                company_id=company_id,
                entry_type=entry_type,
                debit_account=debit,
                credit_account=credit,
                amount=to_storage(amount),
                currency=currency or BILLING_CURRENCY.code,
                reference_entity=reference_entity,
                reference_id=reference_id,
                reference_number=reference_number,
                # Read from ambient context rather than passed in, so
                # every entry produced by one action shares it without
                # each call site having to remember.
                correlation_id=get_correlation_id(),
                description=description,
                reconstructed=False,
            )
        )

    # --- deriving ----------------------------------------------------

    async def balances(
        self, company_id: uuid.UUID | None = None, *, currency: str | None = None
    ) -> list[AccountBalance]:
        """Every account's balance, from the entries alone.

        Scoped to one currency when given. A caller that omits it for a
        company is safe — a company is billed in exactly one currency —
        but omitting it installation-wide mixes currencies, which is why
        the trial balance always passes one.
        """
        debits, credits = await self._entries.sums_by_account(
            company_id=company_id, currency=currency
        )
        rows: list[AccountBalance] = []
        for account in STATEMENT_ACCOUNTS:
            debited = debits.get(account, zero())
            credited = credits.get(account, zero())
            rows.append(
                AccountBalance(
                    account=account,
                    debits=debited,
                    credits=credited,
                    balance=balance_of(account, debits=debited, credits=credited),
                )
            )
        return rows

    async def account_balance(
        self,
        account: LedgerAccount,
        *,
        company_id: uuid.UUID | None = None,
        currency: str | None = None,
    ) -> Decimal:
        for row in await self.balances(company_id, currency=currency):
            if row.account is account:
                return row.balance
        return zero()

    async def outstanding(self, company_id: uuid.UUID) -> Decimal:
        """What a company owes, according to the ledger.

        The authoritative answer. The invoice columns hold the same
        figure as a projection, and ``reconcile()`` proves they match.
        """
        return await self.account_balance(
            LedgerAccount.ACCOUNTS_RECEIVABLE, company_id=company_id
        )

    async def credit_balance(self, company_id: uuid.UUID) -> Decimal:
        """Money held on the company's behalf and not yet applied."""
        return await self.account_balance(
            LedgerAccount.CUSTOMER_CREDIT, company_id=company_id
        )

    async def company_currency(self, company_id: uuid.UUID) -> str:
        """Which currency this company's figures are in.

        Taken from the currency its own entries carry rather than from the
        company row: the ledger is the source of truth, and an entry
        stating its currency is a stronger answer than a column that
        could in principle have been edited afterwards.
        """
        entries = await self._entries.statement(company_id=company_id, limit=1)
        if entries:
            return str(entries[0].currency)
        return BILLING_CURRENCY.code

    async def trial_balance(self, currency: str) -> TrialBalance:
        """One currency's books."""
        code = currency_for(currency).code
        rows = await self.balances(currency=code)
        return TrialBalance(
            currency=code,
            accounts=tuple(rows),
            total_debits=sum((row.debits for row in rows), start=zero()),
            total_credits=sum((row.credits for row in rows), start=zero()),
            entry_count=await self._entries.entry_count(currency=code),
        )

    async def trial_balances(self) -> list[TrialBalance]:
        """A set of books per currency the ledger holds entries in.

        Returned as a list rather than a combined total, because there is
        no honest way to combine them.
        """
        present = await self._entries.currencies_present()
        return [await self.trial_balance(code) for code in present or [BILLING_CURRENCY.code]]


class LedgerReconciliation:
    """Proves the document projection still agrees with the ledger.

    The invoice columns (``amount_paid``, ``amount_credited``) are a
    cache of what the ledger says, kept because "what is still owed" is
    read on every list screen and summing the ledger per row would be an
    N+1. A cache nobody checks is just a second source of truth with
    extra steps, so this is the check — and it is exposed, not buried in
    a log, because the only useful response to a divergence is a person
    looking at it.

    Separate from ``LedgerService`` because reconciliation is inherently
    a question spanning both records, and giving the ledger service a
    dependency on invoices would make the source of truth depend on the
    thing it is the source of truth for.
    """

    def __init__(self, *, session: AsyncSession, ledger: LedgerService) -> None:
        self._session = session
        self._ledger = ledger

    async def rows(self, *, company_id: uuid.UUID | None = None) -> list[ReconciliationRow]:
        from blinkengage.domain.invoicing import OPEN_STATES
        from blinkengage.infrastructure.database.models.invoicing import Invoice

        # What the documents say is outstanding, per company. Only OPEN
        # states owe anything: a draft was never billed and a cancelled
        # invoice was withdrawn, and neither posts to the ledger either.
        stmt = select(
            Invoice.company_id,
            func.coalesce(
                func.sum(
                    Invoice.total_amount - Invoice.amount_paid - Invoice.amount_credited
                ),
                0,
            ),
        ).where(Invoice.status.in_(tuple(OPEN_STATES)))
        if company_id is not None:
            stmt = stmt.where(Invoice.company_id == company_id)
        document = {
            row[0]: Decimal(str(row[1]))
            for row in (await self._session.execute(stmt.group_by(Invoice.company_id))).all()
        }

        ledger_by_company = await self._receivable_by_company(company_id)

        rows: list[ReconciliationRow] = []
        # The union of both sides, so a company present in one and absent
        # from the other is reported rather than silently skipped —
        # which is precisely the divergence worth catching.
        for cid in sorted(set(document) | set(ledger_by_company), key=str):
            rows.append(
                ReconciliationRow(
                    company_id=cid,
                    ledger_receivable=ledger_by_company.get(cid, zero()),
                    document_receivable=document.get(cid, zero()),
                    customer_credit=await self._ledger.credit_balance(cid),
                )
            )
        return rows

    async def _receivable_by_company(
        self, company_id: uuid.UUID | None
    ) -> dict[uuid.UUID, Decimal]:
        """Receivable balances straight from the entries, in one pass."""
        totals: dict[uuid.UUID, Decimal] = {}
        for column, sign in (
            (LedgerEntry.debit_account, Decimal(1)),
            (LedgerEntry.credit_account, Decimal(-1)),
        ):
            stmt = select(
                LedgerEntry.company_id, func.coalesce(func.sum(LedgerEntry.amount), 0)
            ).where(column == LedgerAccount.ACCOUNTS_RECEIVABLE)
            if company_id is not None:
                stmt = stmt.where(LedgerEntry.company_id == company_id)
            for row in (await self._session.execute(stmt.group_by(LedgerEntry.company_id))).all():
                if row[0] is None:
                    continue
                totals[row[0]] = totals.get(row[0], zero()) + sign * Decimal(str(row[1]))
        return totals

    async def divergences(
        self, *, company_id: uuid.UUID | None = None
    ) -> list[ReconciliationRow]:
        return [row for row in await self.rows(company_id=company_id) if not row.agrees]


__all__ = [
    "AccountBalance",
    "LedgerReconciliation",
    "LedgerService",
    "ReconciliationRow",
    "TrialBalance",
]
