"""Double-entry rules — the accounting policy, checked in isolation.

If these are wrong, every balance in the system is wrong and nothing
downstream will notice. They are deliberately assertions about
*accounting*, not about this codebase: somebody who knows double-entry
and not Python should be able to read them.
"""

from decimal import Decimal

import pytest

from blinkengage.domain.ledger import (
    ACCOUNT_KINDS,
    POSTINGS,
    AccountKind,
    LedgerAccount,
    LedgerEntryType,
    LedgerError,
    balance_of,
    is_debit_normal,
    posting_for,
    validate_accounts,
    validate_amount,
)


class TestChartOfAccounts:
    def test_every_account_has_a_kind(self) -> None:
        """A missing kind would make `balance_of` raise on a real
        balance query — the worst possible place to find out."""
        for account in LedgerAccount:
            assert account in ACCOUNT_KINDS

    def test_assets_and_expenses_grow_when_debited(self) -> None:
        assert is_debit_normal(LedgerAccount.ACCOUNTS_RECEIVABLE)
        assert is_debit_normal(LedgerAccount.CASH)
        assert is_debit_normal(LedgerAccount.BAD_DEBT)

    def test_liabilities_and_income_grow_when_credited(self) -> None:
        assert not is_debit_normal(LedgerAccount.CUSTOMER_CREDIT)
        assert not is_debit_normal(LedgerAccount.REVENUE)

    def test_credit_notes_are_contra_income_not_income(self) -> None:
        """So "what did we bill" and "what did we give back" stay
        separately answerable — the first question asked when revenue
        looks wrong."""
        assert ACCOUNT_KINDS[LedgerAccount.REVENUE] is AccountKind.INCOME
        assert ACCOUNT_KINDS[LedgerAccount.REVENUE_ADJUSTMENTS] is AccountKind.CONTRA_INCOME
        assert is_debit_normal(LedgerAccount.REVENUE_ADJUSTMENTS)


class TestPostings:
    def test_every_operation_has_a_rule_except_manual(self) -> None:
        for entry_type in LedgerEntryType:
            if entry_type is LedgerEntryType.MANUAL_ADJUSTMENT:
                continue
            assert entry_type in POSTINGS, entry_type

    def test_a_manual_adjustment_has_no_default(self) -> None:
        """A default would let a typo post somewhere plausible."""
        with pytest.raises(ValueError, match="no fixed posting rule"):
            posting_for(LedgerEntryType.MANUAL_ADJUSTMENT)

    def test_no_rule_debits_and_credits_the_same_account(self) -> None:
        for entry_type, posting in POSTINGS.items():
            assert posting.debit is not posting.credit, entry_type

    def test_billing_creates_a_receivable_and_recognises_revenue(self) -> None:
        posting = posting_for(LedgerEntryType.INVOICE_ISSUED)
        assert posting.debit is LedgerAccount.ACCOUNTS_RECEIVABLE
        assert posting.credit is LedgerAccount.REVENUE

    def test_receiving_money_is_cash_in_and_a_liability(self) -> None:
        """The money is still the customer's until it settles
        something. This is why payments are independent of invoices."""
        posting = posting_for(LedgerEntryType.PAYMENT_RECEIVED)
        assert posting.debit is LedgerAccount.CASH
        assert posting.credit is LedgerAccount.CUSTOMER_CREDIT

    def test_allocation_moves_no_cash_and_no_revenue(self) -> None:
        posting = posting_for(LedgerEntryType.PAYMENT_ALLOCATED)
        assert {posting.debit, posting.credit} == {
            LedgerAccount.CUSTOMER_CREDIT,
            LedgerAccount.ACCOUNTS_RECEIVABLE,
        }
        assert LedgerAccount.CASH not in {posting.debit, posting.credit}
        assert LedgerAccount.REVENUE not in {posting.debit, posting.credit}

    def test_reversal_is_the_exact_opposite_of_allocation(self) -> None:
        allocated = posting_for(LedgerEntryType.PAYMENT_ALLOCATED)
        reversed_ = posting_for(LedgerEntryType.ALLOCATION_REVERSED)
        assert reversed_.debit is allocated.credit
        assert reversed_.credit is allocated.debit

    def test_a_write_off_is_an_expense_not_a_discount(self) -> None:
        """A write-off says we billed correctly and were not paid; a
        credit note says we billed too much. Collapsing them makes
        revenue wrong in one direction or bad debt invisible in the
        other."""
        posting = posting_for(LedgerEntryType.WRITE_OFF)
        assert posting.debit is LedgerAccount.BAD_DEBT
        assert posting.credit is LedgerAccount.ACCOUNTS_RECEIVABLE
        assert (
            posting_for(LedgerEntryType.CREDIT_NOTE_ISSUED).debit
            is LedgerAccount.REVENUE_ADJUSTMENTS
        )

    def test_a_refund_returns_cash_against_the_credit_held(self) -> None:
        posting = posting_for(LedgerEntryType.REFUND_ISSUED)
        assert posting.debit is LedgerAccount.CUSTOMER_CREDIT
        assert posting.credit is LedgerAccount.CASH


class TestBalanceDirection:
    def test_a_receivable_with_money_owed_reads_positive(self) -> None:
        assert balance_of(
            LedgerAccount.ACCOUNTS_RECEIVABLE, debits=Decimal(100), credits=Decimal(30)
        ) == Decimal(70)

    def test_a_credit_balance_reads_positive_too(self) -> None:
        """Callers get "how much" without needing to know which way the
        account runs — the mistake `balance_of` exists to prevent."""
        assert balance_of(
            LedgerAccount.CUSTOMER_CREDIT, debits=Decimal(30), credits=Decimal(100)
        ) == Decimal(70)

    def test_an_over_settled_receivable_goes_negative(self) -> None:
        """Not clamped: a negative receivable means more was applied than
        was ever billed, and hiding that behind a zero would hide a bug."""
        assert balance_of(
            LedgerAccount.ACCOUNTS_RECEIVABLE, debits=Decimal(10), credits=Decimal(25)
        ) == Decimal(-15)


class TestEntryValidation:
    def test_a_zero_or_negative_amount_is_refused(self) -> None:
        """Direction is carried by which account is debited. A signed
        amount would let one movement be written two ways, and every
        total would depend on which the writer chose."""
        for amount in (Decimal(0), Decimal(-1)):
            with pytest.raises(LedgerError, match="positive amount"):
                validate_amount(amount)

    def test_an_entry_cannot_post_to_one_account_twice(self) -> None:
        with pytest.raises(LedgerError, match="same account"):
            validate_accounts(LedgerAccount.CASH, LedgerAccount.CASH)

    def test_a_valid_entry_passes(self) -> None:
        validate_amount(Decimal("0.000001"))
        validate_accounts(LedgerAccount.CASH, LedgerAccount.CUSTOMER_CREDIT)
