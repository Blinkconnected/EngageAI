"""Persistence for the financial ledger.

See ``docs/architecture/billing.md``.

Exposes **no update and no delete**. A ledger mistake is corrected by
posting the opposite entry, never by amending one, and a repository that
offers no way to amend makes that rule structural rather than a
convention. On PostgreSQL a trigger enforces the same thing, so it holds
against a ``psql`` session too.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from blinkengage.domain.ledger import LedgerAccount, LedgerEntryType
from blinkengage.infrastructure.database.models.ledger import LedgerEntry

#: The ledger's own counter in ``document_number_sequences``. Year 0
#: because a ledger sequence must never restart — invoice numbers are
#: year-scoped by accounting convention, but entry 1 of 2027 sorting
#: alongside entry 1 of 2026 would destroy the ordering the column
#: exists to provide.
LEDGER_SEQUENCE_PREFIX = "LEDGER"
LEDGER_SEQUENCE_YEAR = 0


class LedgerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entry: LedgerEntry) -> LedgerEntry:
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def add_all(self, entries: Sequence[LedgerEntry]) -> None:
        self._session.add_all(list(entries))
        await self._session.flush()

    # --- reads -------------------------------------------------------

    async def for_reference(
        self, *, reference_entity: str, reference_id: uuid.UUID
    ) -> list[LedgerEntry]:
        """Everything the ledger says about one document."""
        result = await self._session.execute(
            select(LedgerEntry)
            .where(
                LedgerEntry.reference_entity == reference_entity,
                LedgerEntry.reference_id == reference_id,
            )
            .order_by(LedgerEntry.entry_number)
        )
        return list(result.scalars().all())

    async def for_correlation(self, correlation_id: str) -> list[LedgerEntry]:
        result = await self._session.execute(
            select(LedgerEntry)
            .where(LedgerEntry.correlation_id == correlation_id)
            .order_by(LedgerEntry.entry_number)
        )
        return list(result.scalars().all())

    async def statement(
        self,
        *,
        company_id: uuid.UUID | None = None,
        account: LedgerAccount | None = None,
        entry_type: LedgerEntryType | None = None,
        since: datetime | None = None,
        limit: int = 200,
    ) -> list[LedgerEntry]:
        stmt = select(LedgerEntry)
        if company_id is not None:
            stmt = stmt.where(LedgerEntry.company_id == company_id)
        if account is not None:
            # Either side: an account's statement is every movement it
            # took part in, whichever direction.
            stmt = stmt.where(
                (LedgerEntry.debit_account == account)
                | (LedgerEntry.credit_account == account)
            )
        if entry_type is not None:
            stmt = stmt.where(LedgerEntry.entry_type == entry_type)
        if since is not None:
            stmt = stmt.where(LedgerEntry.occurred_at >= since)
        result = await self._session.execute(
            stmt.order_by(LedgerEntry.entry_number.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def currencies_present(self) -> list[str]:
        """Which currencies the ledger actually holds entries in.

        The trial balance is reported per currency: adding dinars to
        dollars produces a number that means nothing, and no exchange rate
        is stored to make it mean something.
        """
        result = await self._session.execute(
            select(LedgerEntry.currency).distinct().order_by(LedgerEntry.currency)
        )
        return [str(row[0]) for row in result.all()]

    async def sums_by_account(
        self,
        *,
        company_id: uuid.UUID | None = None,
        currency: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[dict[LedgerAccount, Decimal], dict[LedgerAccount, Decimal]]:
        """Total debited and total credited, per account.

        Two grouped queries rather than one per account: the number of
        accounts will grow, and a query per account is how a balance
        screen becomes an N+1.

        ``since``/``until`` bound it to a window, which is what separates a
        *balance* from a *period figure*. Without them every revenue number
        is all-time, and "revenue" that only ever grows is not something a
        finance team can run a month on. Half-open ``[since, until)``, like
        every other range in the billing engine, so a boundary entry is
        counted once.
        """

        async def _sums(
            column: InstrumentedAttribute[LedgerAccount],
        ) -> dict[LedgerAccount, Decimal]:
            stmt = select(column, func.coalesce(func.sum(LedgerEntry.amount), 0))
            if company_id is not None:
                stmt = stmt.where(LedgerEntry.company_id == company_id)
            if currency is not None:
                stmt = stmt.where(LedgerEntry.currency == currency)
            if since is not None:
                stmt = stmt.where(LedgerEntry.occurred_at >= since)
            if until is not None:
                stmt = stmt.where(LedgerEntry.occurred_at < until)
            result = await self._session.execute(stmt.group_by(column))
            # Keyed by the enum member, not by a string. SQLAlchemy
            # converts the stored NAME back to a LedgerAccount on read,
            # while `str()` on a StrEnum yields its *value* — so keying
            # by either spelling silently missed every row and every
            # derived balance read zero.
            return {LedgerAccount(row[0]): Decimal(str(row[1])) for row in result.all()}

        return await _sums(LedgerEntry.debit_account), await _sums(LedgerEntry.credit_account)

    async def entry_count(self, *, currency: str | None = None) -> int:
        stmt = select(func.count()).select_from(LedgerEntry)
        if currency is not None:
            stmt = stmt.where(LedgerEntry.currency == currency)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())


__all__ = ["LEDGER_SEQUENCE_PREFIX", "LEDGER_SEQUENCE_YEAR", "LedgerRepository"]
