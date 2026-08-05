"""Reading memory.

Separate from ``MemoryManager`` on purpose, and the separation is the
point of the whole platform: the Manager is the **only writer**, and a
class that both read and wrote would make "who can write memory?" a
question about which method you called rather than which object you hold.
Consumers — the AI Engine, the Customer Timeline, CRM, Reporting,
Analytics — are handed this one, which has no write method to reach for.

It is a thin composition over the repositories, and deliberately so.
Anything that decides *what memory means* belongs in ``domain/memory*.py``
where it is pure; anything that changes memory belongs to the Manager.
What is left is reading, filtering and shaping — which is this.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from blinkengage.api.schemas.memory import MemoryStatusResponse
from blinkengage.domain.company_settings import is_memory_enabled, memory_retention_days
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.domain.memory import LifecycleState, MemoryTier, SubjectRef
from blinkengage.domain.memory_confidence import decayed_confidence
from blinkengage.domain.memory_lifecycle import RetentionPolicy
from blinkengage.infrastructure.database.models.memory import MemoryEvidence, MemoryFact
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.memory_repository import (
    MemoryEvidenceRepository,
    MemoryFactRepository,
)


def effective_confidence(fact: MemoryFact, *, now: datetime | None = None) -> float:
    """What a consumer should act on.

    The stored column is a cache that was correct when the sweep last
    touched it. Finishing the decay here means a stale cache produces a
    slightly conservative number rather than a wrong one — which is what
    makes the sweep's throughput a performance concern instead of a
    correctness one.

    One function, so the AI Engine, the Customer Timeline, Reporting and
    Analytics cannot disagree about how confident the platform is.
    """
    # SQLite returns naive datetimes where PostgreSQL returns aware ones,
    # and comparing the two raises. The same storage artifact
    # ``UtcDateTime`` corrects for the pricing tables and ``MemoryManager``
    # corrects at its own boundary — corrected here rather than inside the
    # pure function, which has no business knowing which backend it ran on.
    computed_at = fact.confidence_computed_at
    if computed_at is not None and computed_at.tzinfo is None:
        computed_at = computed_at.replace(tzinfo=UTC)

    return decayed_confidence(
        stored=float(fact.confidence),
        computed_at=computed_at,
        now=now or datetime.now(UTC),
        fact_type=fact.fact_type,
    )


class MemoryQueryService:
    def __init__(
        self,
        *,
        facts: MemoryFactRepository,
        evidence: MemoryEvidenceRepository,
        companies: CompanyRepository,
        recompute_interval_seconds: int = 21600,
    ) -> None:
        self._facts = facts
        self._evidence = evidence
        self._companies = companies
        self._recompute_interval_seconds = recompute_interval_seconds

    async def list_for_company(
        self,
        *,
        company_id: UUID,
        tier: MemoryTier | None = None,
        fact_type: str | None = None,
        lifecycle_state: LifecycleState | None = None,
        retrievable_only: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[MemoryFact], int]:
        return await self._facts.list_for_company(
            company_id=company_id,
            tier=tier,
            fact_type=fact_type,
            lifecycle_state=lifecycle_state,
            retrievable_only=retrievable_only,
            limit=limit,
            offset=offset,
        )

    async def list_for_subject(
        self,
        *,
        company_id: UUID,
        subject: SubjectRef,
        fact_types: Sequence[str] | None = None,
        retrievable_only: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[MemoryFact], int]:
        return await self._facts.list_for_subject(
            company_id=company_id,
            subject=subject,
            retrievable_only=retrievable_only,
            fact_types=fact_types,
            limit=limit,
            offset=offset,
        )

    async def get_with_evidence(
        self, *, company_id: UUID, fact_id: UUID
    ) -> tuple[MemoryFact, list[MemoryEvidence]]:
        fact = await self._facts.get_by_id(company_id=company_id, fact_id=fact_id)
        if fact is None:
            raise EntityNotFoundError("MemoryFact", fact_id)
        return fact, await self._evidence.list_for_fact(fact_id=fact.id)

    async def status(self, *, company_id: UUID) -> MemoryStatusResponse:
        """What is held, and under what retention.

        The retention numbers are resolved the same way the decay sweep
        resolves them — company override, else platform default — so an
        operator reading this sees the windows that will actually be
        applied rather than the defaults the platform ships. A status
        screen that reported different numbers than the sweep enforces
        would be worse than no status screen.
        """
        company = await self._companies.get_by_id(company_id)
        settings = company.settings if company is not None else {}
        default = RetentionPolicy()
        dormant, archive, purge = memory_retention_days(settings)

        # The number that would have made a not-keeping-up sweep visible
        # immediately instead of never: how many facts are carrying a
        # confidence older than the recompute interval promises.
        stale_before = datetime.now(UTC) - timedelta(seconds=self._recompute_interval_seconds)
        return MemoryStatusResponse(
            memory_enabled=is_memory_enabled(settings),
            facts_by_tier=await self._facts.counts_by_tier(company_id=company_id),
            facts_by_lifecycle=await self._facts.counts_by_state(company_id=company_id),
            facts_awaiting_recompute=await self._facts.stale_count(
                company_id=company_id, stale_before=stale_before
            ),
            retention_dormant_after_days=dormant or default.dormant_after_days,
            retention_archive_after_days=archive or default.archive_after_days,
            retention_purge_after_days=purge or default.purge_after_days,
        )


__all__ = ["MemoryQueryService"]
