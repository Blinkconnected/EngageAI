"""Erasure — the operation that must actually complete.

See ``docs/architecture/memory-platform.md``.

**Erasure is not forgetting**, and keeping the two apart is the most
important distinction in this platform:

| | Forgetting | Erasure |
|---|---|---|
| Cause | Decay, retention | A legal request, or a deleted customer |
| Trigger | Scheduled | On demand, must complete |
| Scope | One fact | Every fact, evidence row and vector for a subject |
| Reversible | Until purge | **Never, by design** |
| Answer to an auditor | "It decayed" | "It is gone" |

"It was forgotten" is not an answer to *"prove this customer's data is
deleted"*, which is why this is a separate service with its own audit
record rather than a flag on the decay sweep.

**The half that is easy to miss.** Deleting the facts *about* a customer
is obvious. The subtle half is the aggregate facts their conversations
*contributed to* — "card declines spike at month-end" is a fact about the
business, not about them, and it survives. But its support must be
recomputed once their evidence is gone, or it keeps claiming a confidence
it can no longer justify. An erasure that deleted those would remove more
than it was asked to; one that left them untouched would leave a number
standing on evidence that no longer exists. Neither is acceptable, so this
does the third thing.

Aggregate facts survive erasure only because they are non-attributable by
construction: a fact supported by a single customer is not aggregate, and
the distinct-customer floor in the confidence formula is what keeps that
line real rather than asserted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.memory import SubjectRef, SubjectType
from blinkengage.domain.memory_ports import SupportsFactRecompute, SupportsOwnerDeletion
from blinkengage.infrastructure.database.models.memory import OWNER_MEMORY_FACT
from blinkengage.infrastructure.repositories.memory_repository import (
    MemoryEvidenceRepository,
    MemoryFactRepository,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ErasureReport:
    """What an erasure actually removed.

    Returned and audited rather than logged, because the whole value of
    this operation is being able to say precisely what happened. "We ran
    erasure" is not evidence; "42 facts deleted, 118 evidence rows deleted,
    7 aggregate facts recomputed, 42 vectors deleted" is.
    """

    subject: SubjectRef
    facts_deleted: int
    evidence_deleted: int
    aggregate_facts_recomputed: int
    aggregate_facts_archived: int
    embeddings_deleted: int
    erased_at: datetime

    @property
    def anything_removed(self) -> bool:
        return bool(self.facts_deleted or self.evidence_deleted or self.embeddings_deleted)


class MemoryErasureService:
    """Removes a subject from memory, completely and irreversibly.

    Separate from ``MemoryManager`` deliberately. The Manager's job is to
    *keep* memory correctly; this one's job is to destroy it on request,
    and giving both to one component would mean the class that writes
    facts also holds the method that deletes a customer's history. They
    have different callers, different permissions and different review
    expectations.

    It still writes through the same repositories inside one transaction,
    so an erasure is atomic: a run that deleted facts but failed before
    deleting evidence would leave orphaned pointers to a person who asked
    to be forgotten.
    """

    def __init__(
        self,
        *,
        facts: MemoryFactRepository,
        evidence: MemoryEvidenceRepository,
        embeddings: SupportsOwnerDeletion | None,
        events: DomainEventPublisher,
        recompute: SupportsFactRecompute | None = None,
    ) -> None:
        self._facts = facts
        self._evidence = evidence
        self._embeddings = embeddings
        self._events = events
        # The Memory Manager, when one is available. Optional because
        # erasure must succeed even in a context that has no Manager wired
        # — an aggregate fact left with stale counters is a lesser failure
        # than an erasure that did not happen.
        self._recompute = recompute

    async def erase_customer(
        self, *, company_id: UUID, customer_id: UUID, now: datetime | None = None
    ) -> ErasureReport:
        """Erase everything memory holds about one customer.

        Order matters and is not arbitrary:

        1. Find the aggregate facts they contributed to **first**, while
           their evidence still exists to identify them. After step 3 that
           link is gone and those facts would be unfindable.
        2. Delete the facts about them, and their vectors.
        3. Delete their evidence everywhere else.
        4. Recompute what is left, so no surviving fact claims support it
           no longer has.
        """
        moment = now or datetime.now(UTC)
        subject = SubjectRef(subject_type=SubjectType.CUSTOMER, subject_id=customer_id)

        contributed_to = set(
            await self._facts.ids_supported_by_customer(
                company_id=company_id, customer_id=customer_id
            )
        )
        own_facts = await self._facts.ids_for_subject(company_id=company_id, subject=subject)
        # A fact about the customer is being deleted outright; recomputing
        # it afterwards would be recomputing a row that no longer exists.
        contributed_to -= set(own_facts)

        embeddings_deleted = 0
        if self._embeddings is not None and own_facts:
            embeddings_deleted = await self._embeddings.delete_for_owners(
                company_id=company_id, owner_type=OWNER_MEMORY_FACT, owner_ids=own_facts
            )

        # Evidence for the deleted facts goes with them by FK cascade, but
        # deleting explicitly keeps the report honest and does not rely on
        # a cascade the SQLite test backend applies differently.
        evidence_deleted = await self._evidence.delete_for_facts(
            company_id=company_id, fact_ids=own_facts
        )
        facts_deleted = await self._facts.delete_by_ids(company_id=company_id, fact_ids=own_facts)
        evidence_deleted += await self._evidence.delete_for_customer(
            company_id=company_id, customer_id=customer_id
        )

        recomputed = 0
        archived = 0
        for fact_id in sorted(contributed_to):
            fact = await self._facts.get_by_id(company_id=company_id, fact_id=fact_id)
            if fact is None:
                continue
            if self._recompute is not None:
                await self._recompute.recompute(fact=fact, now=moment)
                recomputed += 1
                if fact.lifecycle_state == "archived":
                    # It lost the last of its support. Archived rather than
                    # deleted: the row is the record that the platform once
                    # believed this, and an erasure request did not ask for
                    # the company's own history to be rewritten.
                    archived += 1

        report = ErasureReport(
            subject=subject,
            facts_deleted=facts_deleted,
            evidence_deleted=evidence_deleted,
            aggregate_facts_recomputed=recomputed,
            aggregate_facts_archived=archived,
            embeddings_deleted=embeddings_deleted,
            erased_at=moment,
        )

        # Audited with counts and ids only. An erasure event naming what
        # was erased would defeat the erasure — the audit log has longer
        # retention than the rows it describes.
        await self._events.publish(
            DomainEvent(
                event_type="memory.subject_erased",
                company_id=company_id,
                aggregate_type="memory_subject",
                aggregate_id=customer_id,
                payload={
                    "subject_type": subject.subject_type.value,
                    "facts_deleted": facts_deleted,
                    "evidence_deleted": evidence_deleted,
                    "aggregate_facts_recomputed": recomputed,
                    "aggregate_facts_archived": archived,
                    "embeddings_deleted": embeddings_deleted,
                },
            )
        )
        logger.info(
            "memory_subject_erased",
            extra={
                "company_id": str(company_id),
                "subject": str(subject),
                "facts_deleted": facts_deleted,
                "evidence_deleted": evidence_deleted,
            },
        )
        return report

    async def erase_subject(
        self,
        *,
        company_id: UUID,
        subject: SubjectRef,
        now: datetime | None = None,
    ) -> ErasureReport:
        """Erase any subject.

        Customers take the fuller path above because they are the only
        subject whose evidence is scattered across other subjects' facts.
        An agent or a company subject owns its facts outright.
        """
        if subject.subject_type is SubjectType.CUSTOMER:
            return await self.erase_customer(
                company_id=company_id, customer_id=subject.subject_id, now=now
            )

        moment = now or datetime.now(UTC)
        own_facts = await self._facts.ids_for_subject(company_id=company_id, subject=subject)

        embeddings_deleted = 0
        if self._embeddings is not None and own_facts:
            embeddings_deleted = await self._embeddings.delete_for_owners(
                company_id=company_id, owner_type=OWNER_MEMORY_FACT, owner_ids=own_facts
            )
        evidence_deleted = await self._evidence.delete_for_facts(
            company_id=company_id, fact_ids=own_facts
        )
        facts_deleted = await self._facts.delete_by_ids(company_id=company_id, fact_ids=own_facts)

        report = ErasureReport(
            subject=subject,
            facts_deleted=facts_deleted,
            evidence_deleted=evidence_deleted,
            aggregate_facts_recomputed=0,
            aggregate_facts_archived=0,
            embeddings_deleted=embeddings_deleted,
            erased_at=moment,
        )
        await self._events.publish(
            DomainEvent(
                event_type="memory.subject_erased",
                company_id=company_id,
                aggregate_type="memory_subject",
                aggregate_id=subject.subject_id,
                payload={
                    "subject_type": subject.subject_type.value,
                    "facts_deleted": facts_deleted,
                    "evidence_deleted": evidence_deleted,
                    "embeddings_deleted": embeddings_deleted,
                },
            )
        )
        return report


__all__ = ["ErasureReport", "MemoryErasureService"]
