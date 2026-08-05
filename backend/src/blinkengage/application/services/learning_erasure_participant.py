"""Learning's part in an erasure.

See [the charter](../../../../../docs/architecture/learning-platform-charter.md).

**B5 from the architecture freeze review**, closed. Erasure previously
reached Memory and nothing else, because Memory was the only context
holding subject data. Learning holds observations, their traces and their
features — all keyed to a customer — so an ``ErasureReport`` that omitted
them would assert complete deletion while four tables still held the
subject, and that report is described as the thing somebody forwards to a
regulator.

Each context erases its own store. That is the same rule that keeps
``MemoryManager`` the only writer of memory, applied to deletion: erasure
fans out and *asks*, rather than reaching across boundaries itself.

A failure here makes the whole erasure **incomplete** rather than being
swallowed — the composite report names this participant, and a caller
must treat that as a failure rather than a partial success.
"""

from __future__ import annotations

import logging
from uuid import UUID

from blinkengage.infrastructure.repositories.learning_repository import (
    LearningObservationRepository,
)

logger = logging.getLogger(__name__)


class LearningErasureParticipant:
    """Removes everything Learning holds about a subject.

    Only ``customer`` subjects have anything here. An observation is about
    a unit of work, and the only person it is *about* is the customer on
    the conversation — an agent appears in participants but is not the
    subject, and erasing an agent must not delete the company's record of
    work that happened.
    """

    participant_name = "learning"

    def __init__(self, *, observations: LearningObservationRepository) -> None:
        self._observations = observations

    async def erase_subject(
        self, *, company_id: UUID, subject_type: str, subject_id: UUID
    ) -> dict[str, int]:
        if subject_type != "customer":
            return {
                "observations_deleted": 0,
                "features_deleted": 0,
                "content_refs_deleted": 0,
            }

        # Observations, their features and their traces, each deleted
        # explicitly rather than left to a cascade — see
        # ``LearningObservationRepository.delete_by_ids``. The counts are
        # reported because "we ran erasure" is not evidence.
        deleted = await self._observations.delete_for_customer(
            company_id=company_id, customer_id=subject_id
        )
        logger.info(
            "learning_subject_erased",
            extra={"company_id": str(company_id), **deleted},
        )
        return {
            "observations_deleted": deleted["observations"],
            "features_deleted": deleted["features"],
            "content_refs_deleted": deleted["content_refs"],
        }


__all__ = ["LearningErasureParticipant"]
