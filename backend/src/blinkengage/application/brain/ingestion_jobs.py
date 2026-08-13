"""Ingestion work, made durable and safe to run twice.

Two guarantees, and both are enforced by the database rather than by care:

**One job per unit of work.** ``UNIQUE(company_id, job_key)`` — a replay, a
redelivery or a second worker finds the existing job instead of creating a
rival. An application-level "does one exist?" cannot do this; both readers see
*no* before either writes.

**A transition only happens once.** Every move is a conditional UPDATE that
names the state it expects to find. Two workers racing to claim the same job
both issue it; one matches a row and one matches nothing, and the one that
matched nothing is told so rather than proceeding on a stale read. That is what
makes "claimed by somebody else" different from "claimed by me".

Crash safety follows from those: a worker that dies mid-extraction leaves the
job in ``EXTRACTING`` with its attempt counted. The sweep does not silently
reclaim it — ``EXTRACTING -> RECEIVED`` is not a legal move, because a job
somebody abandoned is not the same as one nobody has touched, and losing that
distinction loses the only signal that something is wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.core.logging import get_logger
from blinkengage.domain.brain.ingestion_jobs import (
    MAX_ATTEMPTS,
    JobState,
    assert_transition,
    failure_state,
)
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.infrastructure.database.models.knowledge_source import (
    KnowledgeIngestionJob,
)

logger = get_logger(__name__)


class JobClaimLost(Exception):
    """Another worker moved this job first.

    Not an error condition to log and continue past: the caller believed it
    owned the work and it does not, so continuing would mean two workers
    extracting the same document and both writing the result.
    """


@dataclass(frozen=True, slots=True)
class JobView:
    """A job, as a value. Detached from the session on purpose."""

    id: UUID
    company_id: UUID
    state: JobState
    attempts: int


def job_key(*, source_message_id: UUID | None, document_id: UUID | None) -> str:
    """Deterministic identity for one unit of work.

    ``-`` for the absent half rather than leaving it out, so a message-level
    job and a document-level job can never collide on the same string.
    """
    return f"{source_message_id or '-'}:{document_id or '-'}"


class IngestionJobService:
    """Creates, claims and settles ingestion jobs for one session."""

    def __init__(
        self, *, session: AsyncSession, events: DomainEventPublisher | None = None
    ) -> None:
        self._session = session
        self._events = events

    async def ensure(
        self,
        *,
        company_id: UUID,
        source_message_id: UUID | None = None,
        document_id: UUID | None = None,
    ) -> JobView:
        """The job for this work, creating it only if it does not exist.

        Idempotent by constraint, not by check-then-insert: a redelivered
        message and a re-run sweep both land on the same row.
        """
        key = job_key(source_message_id=source_message_id, document_id=document_id)
        existing = await self._find(company_id=company_id, key=key)
        if existing is not None:
            return existing

        row = KnowledgeIngestionJob(
            company_id=company_id,
            source_message_id=source_message_id,
            document_id=document_id,
            job_key=key,
            state=JobState.RECEIVED.value,
            attempts=0,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError:
            # Lost the race. The winner's row is the job.
            await self._session.rollback()
            found = await self._find(company_id=company_id, key=key)
            if found is None:  # pragma: no cover - the constraint just fired
                raise
            return found

        await self._publish("knowledge.ingestion.job_created", row.id, company_id, key)
        return JobView(id=row.id, company_id=company_id, state=JobState.RECEIVED, attempts=0)

    async def _find(self, *, company_id: UUID, key: str) -> JobView | None:
        """Company-scoped, always. There is no lookup by id alone here."""
        result = await self._session.execute(
            select(
                KnowledgeIngestionJob.id,
                KnowledgeIngestionJob.company_id,
                KnowledgeIngestionJob.state,
                KnowledgeIngestionJob.attempts,
            ).where(
                KnowledgeIngestionJob.company_id == company_id,
                KnowledgeIngestionJob.job_key == key,
            )
        )
        row = result.first()
        if row is None:
            return None
        return JobView(
            id=row.id, company_id=row.company_id, state=JobState(row.state), attempts=row.attempts
        )

    async def claim(self, job: JobView) -> JobView:
        """Move a resumable job into ``EXTRACTING``, or refuse.

        The attempt is counted here rather than on failure. A worker that dies
        without recording anything has still consumed one, and counting only
        failures would let a crash loop run forever against the same document.
        """
        return await self.transition(job, JobState.EXTRACTING, increment_attempt=True)

    async def transition(
        self,
        job: JobView,
        target: JobState,
        *,
        increment_attempt: bool = False,
        failure_reason: str | None = None,
        failure_detail: str | None = None,
    ) -> JobView:
        """Apply one legal move, atomically.

        Raises :class:`InvalidJobTransition` for a move the machine forbids —
        a defect, not a case — and :class:`JobClaimLost` when the row is no
        longer in the state this caller read.
        """
        assert_transition(job.state, target)

        attempts = job.attempts + 1 if increment_attempt else job.attempts
        values: dict[str, object] = {"state": target.value, "attempts": attempts}
        if failure_reason is not None:
            values["failure_reason"] = failure_reason[:40]
        if failure_detail is not None:
            values["failure_detail"] = failure_detail
        if target not in {JobState.FAILED_RETRYABLE, JobState.FAILED_TERMINAL}:
            # A job that recovered must not keep wearing its last failure.
            values.setdefault("failure_reason", None)
            values.setdefault("failure_detail", None)

        result = await self._session.execute(
            update(KnowledgeIngestionJob)
            .where(
                KnowledgeIngestionJob.id == job.id,
                # Tenant scope in the predicate, not merely in the caller.
                KnowledgeIngestionJob.company_id == job.company_id,
                # The compare-and-set. Matching zero rows means somebody else
                # moved it between our read and our write.
                KnowledgeIngestionJob.state == job.state.value,
            )
            .values(**values)
        )
        if result.rowcount == 0:
            raise JobClaimLost(f"job {job.id} is no longer {job.state.value}")

        await self._publish(
            f"knowledge.ingestion.{target.value.lower()}", job.id, job.company_id, None
        )
        return JobView(id=job.id, company_id=job.company_id, state=target, attempts=attempts)

    async def fail(
        self,
        job: JobView,
        *,
        retryable: bool,
        reason: str,
        detail: str = "",
        max_attempts: int = MAX_ATTEMPTS,
    ) -> JobView:
        """Record a failure and decide whether it may be tried again.

        A retryable failure that has exhausted its attempts becomes terminal.
        A job that is retryable forever is a job nobody ever looks at.
        """
        target = failure_state(
            retryable=retryable, attempts=job.attempts, max_attempts=max_attempts
        )
        logger.warning(
            "knowledge_ingestion_job_failed",
            company_id=str(job.company_id),
            job_id=str(job.id),
            state=target.value,
            reason=reason,
            attempts=job.attempts,
        )
        return await self.transition(
            job, target, failure_reason=reason, failure_detail=detail or reason
        )

    async def resumable(self, *, limit: int = 50) -> list[JobView]:
        """Jobs a sweep may pick up, oldest first.

        Deliberately **not** company-filtered: this is the platform sweep, and
        every row it returns carries its own ``company_id`` which every
        subsequent call scopes by. Isolation comes from the transition
        predicate, not from remembering to filter here.
        """
        result = await self._session.execute(
            select(
                KnowledgeIngestionJob.id,
                KnowledgeIngestionJob.company_id,
                KnowledgeIngestionJob.state,
                KnowledgeIngestionJob.attempts,
            )
            .where(
                KnowledgeIngestionJob.state.in_(
                    [JobState.RECEIVED.value, JobState.FAILED_RETRYABLE.value]
                )
            )
            .order_by(KnowledgeIngestionJob.updated_at)
            .limit(limit)
        )
        return [
            JobView(
                id=row.id,
                company_id=row.company_id,
                state=JobState(row.state),
                attempts=row.attempts,
            )
            for row in result.all()
        ]

    async def _publish(
        self, event_type: str, job_id: UUID, company_id: UUID, key: str | None
    ) -> None:
        """On the existing outbox. No second event mechanism."""
        if self._events is None:
            return
        await self._events.publish(
            DomainEvent(
                event_type=event_type,
                company_id=company_id,
                aggregate_type="knowledge_ingestion_job",
                aggregate_id=job_id,
                payload={"job_key": key} if key else {},
            )
        )


__all__ = ["IngestionJobService", "JobClaimLost", "JobView", "job_key"]
