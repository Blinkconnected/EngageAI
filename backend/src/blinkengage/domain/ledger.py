"""The financial ledger: accounts, and what each operation posts.

See ``docs/architecture/billing.md``.

This is the accounting substrate the rest of billing sits on. Invoices,
payments and credit notes are **documents**; the ledger is the record of
what those documents did to the money. A balance is a question about the
ledger, not a column on a document.

Three decisions the whole thing rests on.

**Each entry carries both sides.** One amount, one debit account, one
credit account. That makes every entry balanced *by construction* — it
is not possible to write an unbalanced ledger, because there is nowhere
to put an imbalance. The classic alternative (N signed lines per
transaction, summing to zero) is more general, and would be needed the
day a single operation posts to three accounts; taxes and multi-leg
settlement are out of scope, and a shape that cannot represent an error
is worth more here than one that can represent everything.

**Nothing is ever amended.** A mistake is corrected by posting the
opposite entry, never by editing or deleting. On PostgreSQL a trigger
enforces this, so it survives a ``psql`` session and not merely
repository discipline.

**Debit and credit are not "plus" and "minus".** Whether a debit
increases or decreases an account depends on the kind of account, which
is why ``AccountKind`` exists rather than a signed amount. Storing a
signed number instead would make every reader re-derive the sign
convention, and one of them would get it wrong.

Framework-free, like the rest of ``domain/``.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final

from blinkengage.domain.exceptions import DomainError


class AccountKind(StrEnum):
    """Which way an account moves.

    A **debit-normal** account grows when debited (assets, expenses); a
    **credit-normal** one grows when credited (liabilities, income).
    Balance calculation reads this rather than special-casing account
    names, so adding an account cannot silently get its sign wrong.
    """

    ASSET = "asset"
    LIABILITY = "liability"
    INCOME = "income"
    #: Reduces income without being an expense — where credit notes go.
    #: Kept separate from ``INCOME`` so "what did we bill" and "what did
    #: we give back" are answerable independently, which is the first
    #: thing anybody asks when revenue looks wrong.
    CONTRA_INCOME = "contra_income"
    EXPENSE = "expense"


#: Kinds that grow when debited.
DEBIT_NORMAL: Final[frozenset[AccountKind]] = frozenset(
    {AccountKind.ASSET, AccountKind.EXPENSE, AccountKind.CONTRA_INCOME}
)


class LedgerAccount(StrEnum):
    """The chart of accounts.

    Deliberately small. Every account here is one somebody actually
    asks a question about; an account nobody queries is a column that
    silently accumulates and is never reconciled.
    """

    #: What customers owe. Debited when an invoice is issued, credited as
    #: it is settled, credited off when written off.
    ACCOUNTS_RECEIVABLE = "accounts_receivable"
    #: Money that has actually arrived.
    CASH = "cash"
    #: Money held on a customer's behalf that is not yet applied to any
    #: invoice — an overpayment, or a payment recorded before it was
    #: allocated. A **liability**: it is theirs, not ours, until it
    #: settles something. This account is precisely why payments are
    #: independent of invoices in this system.
    CUSTOMER_CREDIT = "customer_credit"
    #: What was billed.
    REVENUE = "revenue"
    #: What was credited back. Contra-revenue, never a negative revenue
    #: posting — a negative line in an income account breaks every sum
    #: written before credit notes existed.
    REVENUE_ADJUSTMENTS = "revenue_adjustments"
    #: Receivables abandoned as uncollectable.
    BAD_DEBT = "bad_debt"


ACCOUNT_KINDS: Final[dict[LedgerAccount, AccountKind]] = {
    LedgerAccount.ACCOUNTS_RECEIVABLE: AccountKind.ASSET,
    LedgerAccount.CASH: AccountKind.ASSET,
    LedgerAccount.CUSTOMER_CREDIT: AccountKind.LIABILITY,
    LedgerAccount.REVENUE: AccountKind.INCOME,
    LedgerAccount.REVENUE_ADJUSTMENTS: AccountKind.CONTRA_INCOME,
    LedgerAccount.BAD_DEBT: AccountKind.EXPENSE,
}


def is_debit_normal(account: LedgerAccount) -> bool:
    return ACCOUNT_KINDS[account] in DEBIT_NORMAL


class LedgerEntryType(StrEnum):
    """Every financial operation that moves money in the ledger.

    Named as past-tense facts, like the audit trail: an entry records
    something that happened, and a name like ``issue_invoice`` invites
    the reading that it is an instruction still to be carried out.
    """

    INVOICE_ISSUED = "invoice.issued"
    INVOICE_CANCELLED = "invoice.cancelled"
    CREDIT_NOTE_ISSUED = "credit_note.issued"
    PAYMENT_RECEIVED = "payment.received"
    PAYMENT_ALLOCATED = "payment.allocated"
    ALLOCATION_REVERSED = "payment.allocation_reversed"
    REFUND_ISSUED = "payment.refunded"
    CHARGEBACK = "payment.chargeback"
    WRITE_OFF = "receivable.written_off"
    MANUAL_ADJUSTMENT = "adjustment.manual"


@dataclass(frozen=True, slots=True)
class Posting:
    """Which two accounts an operation moves value between."""

    debit: LedgerAccount
    credit: LedgerAccount


#: The posting rule for each operation. A table rather than a function
#: with branches: this *is* the accounting policy of the product, and it
#: should be readable in one screen by somebody who knows accounting and
#: not this codebase.
#:
#: Read each line as "value leaves the credit account and arrives in the
#: debit account".
POSTINGS: Final[dict[LedgerEntryType, Posting]] = {
    # Billing a customer creates a receivable and recognises revenue.
    LedgerEntryType.INVOICE_ISSUED: Posting(
        debit=LedgerAccount.ACCOUNTS_RECEIVABLE, credit=LedgerAccount.REVENUE
    ),
    # Withdrawing an issued invoice unwinds exactly what issuing it did.
    # Distinct from a credit note, and the distinction is the point: a
    # credit note says we billed too much and posts to
    # ``revenue_adjustments``, which is a figure a finance team watches. A
    # cancellation says the document should never have existed, so the
    # revenue is un-recognised rather than adjusted — an invoice raised
    # against the wrong company is not a discount to the right one.
    LedgerEntryType.INVOICE_CANCELLED: Posting(
        debit=LedgerAccount.REVENUE, credit=LedgerAccount.ACCOUNTS_RECEIVABLE
    ),
    # A credit note reduces what they owe, at the cost of revenue.
    LedgerEntryType.CREDIT_NOTE_ISSUED: Posting(
        debit=LedgerAccount.REVENUE_ADJUSTMENTS, credit=LedgerAccount.ACCOUNTS_RECEIVABLE
    ),
    # Money arriving is cash in, and a liability: it is still the
    # customer's until it settles something.
    LedgerEntryType.PAYMENT_RECEIVED: Posting(
        debit=LedgerAccount.CASH, credit=LedgerAccount.CUSTOMER_CREDIT
    ),
    # Allocation is where that liability is discharged against the
    # receivable. Neither cash nor revenue moves — which is exactly why
    # receiving and allocating are separate operations.
    LedgerEntryType.PAYMENT_ALLOCATED: Posting(
        debit=LedgerAccount.CUSTOMER_CREDIT, credit=LedgerAccount.ACCOUNTS_RECEIVABLE
    ),
    # The exact opposite. Posted as its own entry rather than by
    # deleting the original, so the history shows that money was applied
    # and then un-applied.
    LedgerEntryType.ALLOCATION_REVERSED: Posting(
        debit=LedgerAccount.ACCOUNTS_RECEIVABLE, credit=LedgerAccount.CUSTOMER_CREDIT
    ),
    # Returning money we were holding.
    LedgerEntryType.REFUND_ISSUED: Posting(
        debit=LedgerAccount.CUSTOMER_CREDIT, credit=LedgerAccount.CASH
    ),
    # A chargeback is cash taken back by the bank *and* a receivable
    # restored, in one movement the customer did not ask us to make.
    # Distinct from a refund because the cause matters commercially even
    # though the cash effect is similar.
    LedgerEntryType.CHARGEBACK: Posting(
        debit=LedgerAccount.ACCOUNTS_RECEIVABLE, credit=LedgerAccount.CASH
    ),
    # Abandoning a receivable is an expense, not a discount: it says we
    # billed correctly and did not get paid, which is a different fact
    # from a credit note saying we billed too much.
    LedgerEntryType.WRITE_OFF: Posting(
        debit=LedgerAccount.BAD_DEBT, credit=LedgerAccount.ACCOUNTS_RECEIVABLE
    ),
}


def posting_for(entry_type: LedgerEntryType) -> Posting:
    """The accounts an operation posts to.

    ``MANUAL_ADJUSTMENT`` has no fixed rule — an operator names both
    sides — so it raises rather than returning a default. A default here
    would mean a typo silently posted somewhere plausible.
    """
    try:
        return POSTINGS[entry_type]
    except KeyError:
        raise ValueError(
            f"{entry_type.value} has no fixed posting rule; both accounts must be given."
        ) from None


def balance_of(account: LedgerAccount, *, debits: Decimal, credits: Decimal) -> Decimal:
    """An account's balance, in its own natural direction.

    Returns a positive number when the account holds what it normally
    holds — a receivable with money owed, a liability with money due
    back. Callers get "how much" without having to know which way the
    account runs, which is the mistake this function exists to prevent.
    """
    return debits - credits if is_debit_normal(account) else credits - debits


#: Accounts whose balance is a customer-facing figure, in the order a
#: statement reads.
STATEMENT_ACCOUNTS: Final[tuple[LedgerAccount, ...]] = (
    LedgerAccount.ACCOUNTS_RECEIVABLE,
    LedgerAccount.CUSTOMER_CREDIT,
    LedgerAccount.CASH,
    LedgerAccount.REVENUE,
    LedgerAccount.REVENUE_ADJUSTMENTS,
    LedgerAccount.BAD_DEBT,
)


class LedgerError(DomainError):
    """A ledger entry that cannot be written as asked.

    A ``DomainError`` so the API boundary maps it to **409** rather than
    letting it escape as a 500. Refusing an entry that would post to one
    account, or move a negative amount, is a correct and expected answer
    — the caller asked for something that is not an entry — not a server
    fault.
    """


def validate_amount(amount: Decimal) -> None:
    """Every entry moves a positive amount.

    Direction is carried by *which account is debited*, never by the
    sign. A negative amount would let the same movement be expressed two
    ways, and every sum over the ledger would then depend on which way
    each writer happened to choose.
    """
    if amount <= 0:
        raise LedgerError(
            "A ledger entry must move a positive amount; direction is expressed "
            "by the debit and credit accounts, not by the sign."
        )


def validate_accounts(debit: LedgerAccount, credit: LedgerAccount) -> None:
    if debit is credit:
        raise LedgerError(
            f"An entry cannot debit and credit the same account ({debit.value}); "
            "that moves nothing and would still count towards every total."
        )


__all__ = [
    "ACCOUNT_KINDS",
    "DEBIT_NORMAL",
    "POSTINGS",
    "STATEMENT_ACCOUNTS",
    "AccountKind",
    "LedgerAccount",
    "LedgerEntryType",
    "LedgerError",
    "Posting",
    "balance_of",
    "is_debit_normal",
    "posting_for",
    "validate_accounts",
    "validate_amount",
]
