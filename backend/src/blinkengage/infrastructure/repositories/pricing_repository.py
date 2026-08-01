"""Persistence for the pricing engine. See ``docs/architecture/billing.md``.

These repositories **load candidates; they never decide.** The decision —
which of the loaded rates wins at a given instant — lives in the pure
``domain/pricing.py``, so there is exactly one implementation of the
hierarchy and an operator's preview and the eventual rating run cannot
drift apart.

Pricing is platform-scoped, not tenant-scoped: a global rate belongs to
no company, and an operator legitimately reads across companies. These
therefore do not carry the ``company_id`` filter every tenant repository
does. That is the same deliberate exception ``PlatformRepository``
documents, and the only callers are platform-gated endpoints.

``PricingRateRepository`` exposes **no ``save``, no ``update``, no
``delete``** — only ``add``, ``close_open_rate`` and ``void``, each a
single narrow one-way transition. A price that was ever in effect must
stay exactly recoverable, and the cheapest way to guarantee that is to
give the rest of the application no method with which to break it.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.pricing import AssignmentWindow, RateCandidate
from blinkengage.domain.pricing_models import PricingModel
from blinkengage.domain.pricing_scope import PricingScope
from blinkengage.domain.tiers import Tier
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.pricing import (
    CompanyPricingProfileAssignment,
    PricingAuditLog,
    PricingProfile,
    PricingRate,
    PricingRateTier,
)


def _to_candidate(rate: PricingRate, tiers: Sequence[PricingRateTier] = ()) -> RateCandidate:
    return RateCandidate(
        rate_id=rate.id,
        scope=rate.scope,
        metric_code=rate.metric_code,
        company_id=rate.company_id,
        profile_id=rate.profile_id,
        unit_amount=rate.unit_amount,
        currency=rate.currency,
        effective_from=rate.effective_from,
        effective_until=rate.effective_until,
        pricing_model=PricingModel(rate.pricing_model.lower()),
        included_quantity=rate.included_quantity,
        minimum_charge=rate.minimum_charge,
        model_params=dict(rate.model_params or {}),
        tiers=tuple(
            Tier(up_to=tier.up_to, unit_amount=tier.unit_amount)
            for tier in sorted(tiers, key=lambda row: row.sort_order)
        ),
    )


def _to_window(row: CompanyPricingProfileAssignment) -> AssignmentWindow:
    return AssignmentWindow(
        assignment_id=row.id,
        company_id=row.company_id,
        profile_id=row.profile_id,
        effective_from=row.effective_from,
        effective_until=row.effective_until,
    )


class PricingProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_all(self, *, active_only: bool = False) -> list[PricingProfile]:
        stmt = select(PricingProfile)
        if active_only:
            stmt = stmt.where(PricingProfile.is_active.is_(True))
        stmt = stmt.order_by(PricingProfile.sort_order, PricingProfile.name)
        return list((await self._session.execute(stmt)).scalars().all())

    async def get_by_id(self, profile_id: uuid.UUID) -> PricingProfile | None:
        return await self._session.get(PricingProfile, profile_id)

    async def get_by_key(self, key: str) -> PricingProfile | None:
        result = await self._session.execute(
            select(PricingProfile).where(PricingProfile.key == key)
        )
        return result.scalar_one_or_none()

    async def add(self, profile: PricingProfile) -> PricingProfile:
        self._session.add(profile)
        await self._session.flush()
        return profile


class PricingRateRepository:
    """Append-mostly. See the module docstring for why the surface is
    this small."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, rate: PricingRate) -> PricingRate:
        self._session.add(rate)
        await self._session.flush()
        return rate

    async def get_by_id(self, rate_id: uuid.UUID) -> PricingRate | None:
        return await self._session.get(PricingRate, rate_id)

    async def rate_candidates(
        self,
        *,
        metric_codes: Sequence[str],
        company_ids: Sequence[uuid.UUID],
        profile_ids: Sequence[uuid.UUID],
        window_start: datetime,
        window_end: datetime,
    ) -> list[RateCandidate]:
        """Every non-voided rate that could apply to any request in the
        batch, in **one** statement covering all three scopes.

        A superset is loaded deliberately. The candidate set for a
        (metric, target) pair intersecting even a month-wide window is a
        handful of rows, so loading it and deciding in Python is cheaper
        than a per-item query *and* strictly more correct: every request
        in the batch is then resolved at its own instant by the same pure
        function, rather than the batch sharing one instant.
        """
        if not metric_codes:
            return []

        # A rate intersects [window_start, window_end] when it starts on
        # or before the window ends and has not already closed before the
        # window begins. Half-open, matching `domain.pricing.covers`.
        intersects = (PricingRate.effective_from <= window_end) & (
            (PricingRate.effective_until.is_(None)) | (PricingRate.effective_until > window_start)
        )
        targets = PricingRate.scope == PricingScope.GLOBAL
        if company_ids:
            targets = targets | (
                (PricingRate.scope == PricingScope.COMPANY)
                & PricingRate.company_id.in_(list(company_ids))
            )
        if profile_ids:
            targets = targets | (
                (PricingRate.scope == PricingScope.PROFILE)
                & PricingRate.profile_id.in_(list(profile_ids))
            )

        result = await self._session.execute(
            select(PricingRate).where(
                PricingRate.metric_code.in_(list(metric_codes)),
                PricingRate.voided_at.is_(None),
                intersects,
                targets,
            )
        )
        rates = list(result.scalars().all())
        # Tiers in one extra query for the whole batch, not one per rate: the
        # resolver is a batch API precisely because rating a period is a batch
        # job, and a lazy load per candidate would undo that.
        tiers = await self._tiers_for([rate.id for rate in rates])
        return [_to_candidate(rate, tiers.get(rate.id, ())) for rate in rates]

    async def _tiers_for(
        self, rate_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[PricingRateTier]]:
        if not rate_ids:
            return {}
        result = await self._session.execute(
            select(PricingRateTier)
            .where(PricingRateTier.pricing_rate_id.in_(list(rate_ids)))
            .order_by(PricingRateTier.pricing_rate_id, PricingRateTier.sort_order)
        )
        grouped: dict[uuid.UUID, list[PricingRateTier]] = {}
        for tier in result.scalars().all():
            grouped.setdefault(tier.pricing_rate_id, []).append(tier)
        return grouped

    async def tiers_for_rate(self, rate_id: uuid.UUID) -> list[PricingRateTier]:
        """One rate's tiers, in order. For a console showing a table, and for
        copying a table onto a new rate when a price is edited."""
        return (await self._tiers_for([rate_id])).get(rate_id, [])

    async def add_tiers(
        self, *, rate_id: uuid.UUID, tiers: Sequence[Tier]
    ) -> list[PricingRateTier]:
        """Writes a tier table under a rate.

        Validated by ``domain/tiers.validate_tiers`` before it gets here — the
        service is where a bad table becomes a refused request, so this stays a
        plain write.
        """
        rows = [
            PricingRateTier(
                pricing_rate_id=rate_id,
                up_to=tier.up_to,
                unit_amount=tier.unit_amount,
                sort_order=order,
            )
            for order, tier in enumerate(tiers, start=1)
        ]
        self._session.add_all(rows)
        await self._session.flush()
        return rows

    async def open_rate_for(
        self,
        *,
        scope: PricingScope,
        metric_code: str,
        currency: str,
        company_id: uuid.UUID | None = None,
        profile_id: uuid.UUID | None = None,
    ) -> PricingRate | None:
        """The currently-open (``effective_until IS NULL``) rate for one
        target **in one currency**, which "editing a price" closes.

        Currency is part of the target, not a detail of the rate. Nothing
        converts, so a metric legitimately has one open rate per currency —
        and without this filter setting a dinar price was refused because a
        dollar one existed, which made a second currency unreachable through
        the API entirely.
        """
        stmt = select(PricingRate).where(
            PricingRate.scope == scope,
            PricingRate.metric_code == metric_code,
            PricingRate.currency == currency,
            PricingRate.effective_until.is_(None),
            PricingRate.voided_at.is_(None),
        )
        stmt = stmt.where(
            PricingRate.company_id == company_id
            if company_id is not None
            else PricingRate.company_id.is_(None)
        )
        stmt = stmt.where(
            PricingRate.profile_id == profile_id
            if profile_id is not None
            else PricingRate.profile_id.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def rates_for_target(
        self,
        *,
        scope: PricingScope,
        metric_code: str | None = None,
        company_id: uuid.UUID | None = None,
        profile_id: uuid.UUID | None = None,
        include_voided: bool = True,
    ) -> list[PricingRate]:
        """Every rate ever written for a target — the history view."""
        stmt = select(PricingRate).where(PricingRate.scope == scope)
        if metric_code is not None:
            stmt = stmt.where(PricingRate.metric_code == metric_code)
        if company_id is not None:
            stmt = stmt.where(PricingRate.company_id == company_id)
        if profile_id is not None:
            stmt = stmt.where(PricingRate.profile_id == profile_id)
        if not include_voided:
            stmt = stmt.where(PricingRate.voided_at.is_(None))
        stmt = stmt.order_by(PricingRate.effective_from.desc())
        return list((await self._session.execute(stmt)).scalars().all())

    async def close_open_rate(self, *, rate_id: uuid.UUID, effective_until: datetime) -> None:
        """Closes one open rate.

        Guarded on ``effective_until IS NULL`` in the WHERE clause, not
        only in the caller, so a concurrent request that already closed
        this row updates zero rows and the assertion fires — rather than
        the second writer silently overwriting the first writer's
        boundary and re-rating whatever fell between them.
        """
        result = await self._session.execute(
            update(PricingRate)
            .where(PricingRate.id == rate_id, PricingRate.effective_until.is_(None))
            .values(effective_until=effective_until)
        )
        if result.rowcount != 1:
            raise RuntimeError(
                f"Expected to close exactly one open rate {rate_id}, closed {result.rowcount}. "
                "Another request changed this price concurrently."
            )

    async def void(
        self,
        *,
        rate_id: uuid.UUID,
        voided_at: datetime,
        voided_by_user_id: uuid.UUID | None,
        reason: str,
    ) -> None:
        result = await self._session.execute(
            update(PricingRate)
            .where(PricingRate.id == rate_id, PricingRate.voided_at.is_(None))
            .values(voided_at=voided_at, voided_by_user_id=voided_by_user_id, void_reason=reason)
        )
        if result.rowcount != 1:
            raise RuntimeError(
                f"Expected to void exactly one rate {rate_id}, voided {result.rowcount}."
            )


class CompanyPricingAssignmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self, assignment: CompanyPricingProfileAssignment
    ) -> CompanyPricingProfileAssignment:
        self._session.add(assignment)
        await self._session.flush()
        return assignment

    async def windows_in(
        self,
        *,
        company_ids: Sequence[uuid.UUID],
        window_start: datetime,
        window_end: datetime,
    ) -> list[AssignmentWindow]:
        if not company_ids:
            return []
        result = await self._session.execute(
            select(CompanyPricingProfileAssignment).where(
                CompanyPricingProfileAssignment.company_id.in_(list(company_ids)),
                CompanyPricingProfileAssignment.voided_at.is_(None),
                CompanyPricingProfileAssignment.effective_from <= window_end,
                (CompanyPricingProfileAssignment.effective_until.is_(None))
                | (CompanyPricingProfileAssignment.effective_until > window_start),
            )
        )
        return [_to_window(row) for row in result.scalars().all()]

    async def open_assignment(
        self, company_id: uuid.UUID
    ) -> CompanyPricingProfileAssignment | None:
        result = await self._session.execute(
            select(CompanyPricingProfileAssignment).where(
                CompanyPricingProfileAssignment.company_id == company_id,
                CompanyPricingProfileAssignment.effective_until.is_(None),
                CompanyPricingProfileAssignment.voided_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def history(self, company_id: uuid.UUID) -> list[CompanyPricingProfileAssignment]:
        result = await self._session.execute(
            select(CompanyPricingProfileAssignment)
            .where(CompanyPricingProfileAssignment.company_id == company_id)
            .order_by(CompanyPricingProfileAssignment.effective_from.desc())
        )
        return list(result.scalars().all())

    async def close_open(self, *, assignment_id: uuid.UUID, effective_until: datetime) -> None:
        result = await self._session.execute(
            update(CompanyPricingProfileAssignment)
            .where(
                CompanyPricingProfileAssignment.id == assignment_id,
                CompanyPricingProfileAssignment.effective_until.is_(None),
            )
            .values(effective_until=effective_until)
        )
        if result.rowcount != 1:
            raise RuntimeError(
                f"Expected to close exactly one open assignment {assignment_id}, "
                f"closed {result.rowcount}."
            )

    async def companies_on_profile(self, profile_id: uuid.UUID) -> list[uuid.UUID]:
        """Which companies are currently on a profile — so a profile-rate
        change can report how many customers it actually moves."""
        result = await self._session.execute(
            select(CompanyPricingProfileAssignment.company_id).where(
                CompanyPricingProfileAssignment.profile_id == profile_id,
                CompanyPricingProfileAssignment.effective_until.is_(None),
                CompanyPricingProfileAssignment.voided_at.is_(None),
            )
        )
        return list(result.scalars().all())


class PricingAuditRepository:
    """Append-only.

    Exposes ``add`` and reads — deliberately **no** ``save``, ``update``
    or ``delete``. On PostgreSQL a trigger enforces the same thing at the
    database, so "pricing history is never deleted" survives a ``psql``
    session and not merely repository discipline.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, entry: PricingAuditLog) -> PricingAuditLog:
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def history(
        self,
        *,
        metric_code: str | None = None,
        company_id: uuid.UUID | None = None,
        profile_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[PricingAuditLog], int]:
        from sqlalchemy import func

        stmt = select(PricingAuditLog)
        if metric_code is not None:
            stmt = stmt.where(PricingAuditLog.metric_code == metric_code)
        if company_id is not None:
            stmt = stmt.where(PricingAuditLog.company_id == company_id)
        if profile_id is not None:
            stmt = stmt.where(PricingAuditLog.profile_id == profile_id)

        total = (
            await self._session.execute(
                select(func.count()).select_from(
                    stmt.with_only_columns(PricingAuditLog.id).subquery()
                )
            )
        ).scalar_one()
        result = await self._session.execute(
            stmt.order_by(PricingAuditLog.occurred_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total


class PricingCompanyLookup:
    """The one cross-tenant read the pricing engine needs: does this
    company exist, and is it still live?

    Its own tiny class rather than reaching for ``CompanyRepository``,
    because pricing needs a *batch* existence check and nothing else —
    and because an unrecognised company id must produce a clean 404
    rather than a resolution that silently falls through to the global
    price for a company that does not exist.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def billing_currencies(self, company_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        """Each company's billing currency.

        Resolution needs this because a rate is priced in a currency, and
        a Jordanian company must not be billed from a dollar rate. Read
        in the same batch as the existence check rather than per company
        — resolution is called once per usage line at close time.
        """
        if not company_ids:
            return {}
        result = await self._session.execute(
            select(Company.id, Company.billing_currency).where(
                Company.id.in_(list(company_ids)), Company.deleted_at.is_(None)
            )
        )
        return {row[0]: row[1] for row in result.all()}

    async def currencies_in_use(self) -> set[str]:
        """Every billing currency some live company is actually on.

        The coverage check needs this rather than the full ``CURRENCIES``
        table: an installation with no Jordanian customers does not need a
        dinar rate, and reporting one missing would be a false alarm that
        teaches operators to ignore the check. Equally, a metric priced only
        in dollars is *not* covered once one company bills in dinars — which
        is the failure this exists to catch.
        """
        result = await self._session.execute(
            select(Company.billing_currency).where(Company.deleted_at.is_(None)).distinct()
        )
        return {row for row in result.scalars().all() if row}

    async def existing_ids(self, company_ids: Sequence[uuid.UUID]) -> set[uuid.UUID]:
        if not company_ids:
            return set()
        result = await self._session.execute(
            select(Company.id).where(
                Company.id.in_(list(company_ids)), Company.deleted_at.is_(None)
            )
        )
        return set(result.scalars().all())

    async def names_for(self, company_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, str]:
        if not company_ids:
            return {}
        result = await self._session.execute(
            select(Company.id, Company.name).where(Company.id.in_(list(company_ids)))
        )
        return {row[0]: row[1] for row in result.all()}


__all__: list[Any] = [
    "CompanyPricingAssignmentRepository",
    "PricingAuditRepository",
    "PricingCompanyLookup",
    "PricingProfileRepository",
    "PricingRateRepository",
]
