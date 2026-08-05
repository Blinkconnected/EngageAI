"""Reading and changing a company's clustering thresholds.

Production pilot. Two jobs, and the second is the reason this is a
service rather than a settings write:

**Every change is recorded.** A threshold change silently reshapes every
cluster the platform will produce, and clusters are what phase 3 proposes
from. Six months later, "why did the platform stop finding anything in
March?" has to be answerable, and the answer is usually a number somebody
changed. So each change publishes a domain event carrying the old value,
the new value and who did it — which the audit-log consumer turns into a
row that outlives the setting.

**Changes invalidate clusters, and say so.** A different join threshold
produces a different grouping of the same corpus, so the clusters that
exist were built under the old number and are not comparable to the ones
that follow. The response says which, and by how many — because an
operator who does not know that will read the next sweep's output as a
change in the business.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from blinkengage.domain.company_settings import (
    LEARNING_THRESHOLD_BOUNDS,
    learning_thresholds,
    validate_learning_threshold,
)
from blinkengage.domain.events import DomainEvent
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.learning_analysis_repository import (
    LearningClusterRepository,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ThresholdChange:
    name: str
    previous: float
    current: float


@dataclass(frozen=True)
class ThresholdUpdate:
    """What changed, and what it invalidated."""

    thresholds: dict[str, float]
    changes: list[ThresholdChange]
    #: Clusters built under the previous thresholds. Not deleted — they
    #: are the record of what the platform believed, and deleting them
    #: would destroy the comparison that makes a threshold change
    #: reviewable. Reported so nobody reads the next sweep as news.
    clusters_invalidated: int


class LearningSettingsService:
    """The one door for threshold changes."""

    def __init__(
        self,
        *,
        companies: CompanyRepository,
        clusters: LearningClusterRepository,
        events: OutboxEventPublisher,
        platform_defaults: dict[str, float],
    ) -> None:
        self._companies = companies
        self._clusters = clusters
        self._events = events
        self._defaults = platform_defaults

    async def read(self, *, company_id: UUID) -> dict[str, object]:
        company = await self._companies.get_by_id(company_id)
        if company is None:
            raise EntityNotFoundError("Company", company_id)
        resolved = learning_thresholds(company.settings or {}, defaults=self._defaults)
        stored = (company.settings or {}).get("learning") or {}
        return {
            "thresholds": resolved,
            "platform_defaults": dict(self._defaults),
            # Which of these the company actually set, as opposed to
            # inherited. An operator reading a number needs to know
            # whether changing the platform default would move it.
            "overridden": sorted(
                name for name in self._defaults if isinstance(stored.get(name), int | float)
            ),
            "bounds": {
                name: {"min": low, "max": high}
                for name, (low, high) in LEARNING_THRESHOLD_BOUNDS.items()
            },
        }

    async def update(
        self,
        *,
        company_id: UUID,
        actor_user_id: UUID | None,
        values: dict[str, float],
        reason: str | None = None,
    ) -> ThresholdUpdate:
        """Change one or more thresholds, with the change on the record.

        Out-of-bounds values are **refused, not clamped**. Clamping would
        accept the request and quietly do something else, and the
        operator would leave believing a number that is not in effect.
        """
        company = await self._companies.get_by_id(company_id)
        if company is None:
            raise EntityNotFoundError("Company", company_id)

        before = learning_thresholds(company.settings or {}, defaults=self._defaults)
        for name, value in values.items():
            if name not in self._defaults:
                raise EntityNotFoundError("LearningThreshold", name)
            validate_learning_threshold(name, float(value))

        settings = dict(company.settings or {})
        section = dict(settings.get("learning") or {})
        section.update({name: float(value) for name, value in values.items()})
        settings["learning"] = section
        company.settings = settings

        after = learning_thresholds(settings, defaults=self._defaults)
        changes = [
            ThresholdChange(name=name, previous=before[name], current=after[name])
            for name in sorted(self._defaults)
            if before[name] != after[name]
        ]

        invalidated = 0
        if changes:
            invalidated = await self._clusters.member_count(company_id=company_id)
            await self._events.publish(
                DomainEvent(
                    event_type="learning.thresholds_changed",
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    aggregate_type="company",
                    aggregate_id=company_id,
                    payload={
                        # Old and new together: a trail recording only the
                        # new value cannot answer "what did we change it
                        # from", which is the question actually asked.
                        "changes": [
                            {
                                "threshold": change.name,
                                "previous": change.previous,
                                "current": change.current,
                            }
                            for change in changes
                        ],
                        "reason": reason,
                        "clusters_built_under_previous_thresholds": invalidated,
                    },
                )
            )
            logger.info(
                "learning_thresholds_changed",
                extra={
                    "company_id": str(company_id),
                    "changed": [change.name for change in changes],
                },
            )

        return ThresholdUpdate(thresholds=after, changes=changes, clusters_invalidated=invalidated)


__all__ = ["LearningSettingsService", "ThresholdChange", "ThresholdUpdate"]
