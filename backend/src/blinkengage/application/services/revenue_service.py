"""The revenue overview, composed from figures the engine already keeps.

Every number here is read from the ledger or from collections. Nothing is
computed a second way, because a dashboard that derives its own revenue is a
dashboard that will eventually disagree with the invoices — and the one people
believe is whichever they saw first.

The single derived figure is the run rate, which is why it travels with its
own method (see ``domain/revenue.py``).

Two kinds of number live side by side here and the distinction is the whole
design: *period* figures (what moved through an account in the window) and
*positions* (what stands in it right now). Revenue is a period figure —
"we billed 3,000 last month". Outstanding is a position — "we are owed 12,000",
whenever it was billed. Conflating them is how a console reports all-time
revenue as this month's.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from blinkengage.application.services.collections_service import CollectionsService
from blinkengage.application.services.ledger_service import AccountBalance, LedgerService
from blinkengage.domain.collections import BillingStatus
from blinkengage.domain.ledger import LedgerAccount
from blinkengage.domain.money import zero
from blinkengage.domain.revenue import (
    RATE_WINDOW_DAYS,
    CurrencyRevenue,
    RevenueOverview,
    run_rate,
)


def _balance(rows: list[AccountBalance], account: LedgerAccount) -> Decimal:
    for row in rows:
        if row.account is account:
            return row.balance
    return zero()


class RevenueService:
    """What a finance team sees when the Billing Console opens."""

    def __init__(self, *, ledger: LedgerService, collections: CollectionsService) -> None:
        self._ledger = ledger
        self._collections = collections

    async def overview(
        self, *, since: date | None = None, until: date | None = None
    ) -> RevenueOverview:
        """Revenue, receivables and collection standing, per currency.

        Defaults to the trailing thirty days — the same window the run rate
        is stated for, so the headline figure and the rate beside it describe
        the same period rather than quietly differing by a few days.

        Walks every company via collections, so this is a page-load figure and
        not something to poll.
        """
        end = until or (datetime.now(UTC).date() + timedelta(days=1))
        start = since or (end - timedelta(days=RATE_WINDOW_DAYS))
        window_start = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
        window_end = datetime.combine(end, datetime.min.time(), tzinfo=UTC)
        observed = max((end - start).days, 0)

        rows: list[CurrencyRevenue] = []
        for currency in await self._ledger.currencies():
            period = await self._ledger.balances(
                currency=currency, since=window_start, until=window_end
            )
            standing = await self._ledger.balances(currency=currency)
            recognised = _balance(period, LedgerAccount.REVENUE)
            rows.append(
                CurrencyRevenue(
                    currency=currency,
                    revenue=recognised,
                    outstanding=_balance(standing, LedgerAccount.ACCOUNTS_RECEIVABLE),
                    customer_credit=_balance(standing, LedgerAccount.CUSTOMER_CREDIT),
                    bad_debt=_balance(period, LedgerAccount.BAD_DEBT),
                    collected=_balance(period, LedgerAccount.CASH),
                    run_rate=run_rate(
                        recognised=recognised,
                        currency=currency,
                        days_observed=observed,
                    ),
                )
            )

        # Every company, not only those behind: a company can be suspended
        # and hold no open invoices — manual suspension, or a write-off that
        # cleared the debt without lifting the suspension — and a suspended
        # company missing from the count is the one an operator most needs
        # to see.
        standings = await self._collections.standing_all(only_behind=False)
        return RevenueOverview(
            period_from=start,
            period_to=end,
            currencies=tuple(rows),
            companies_behind=sum(1 for s in standings if s.overdue_invoices > 0),
            companies_suspended=sum(
                1 for s in standings if s.billing_status is BillingStatus.PAYMENT_SUSPENDED
            ),
            # When these figures were read. Stated rather than implied: a
            # console with no timestamp reads as live.
            as_of=datetime.now(UTC).isoformat(),
        )


__all__ = ["RevenueService"]
