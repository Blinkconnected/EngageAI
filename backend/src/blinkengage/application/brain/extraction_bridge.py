"""The seam between a finished extraction job and the facts inside it.

4D knows a document has been read. 4E knows how to read facts out of text.
Neither called the other, so nothing ever moved past ``EXTRACTED``. This is
that call, and deliberately nothing more: it owns the *ordering* and the
failure classification, and delegates every decision to the components that
already make it.

The ordering is the part worth stating. Facts are drafted **before** the job
advances, so a crash between the two costs a repeat rather than a loss — the
repeat finds its drafts already present and creates none. Advancing first and
drafting after would produce a job claiming work that never happened, which is
the one outcome no later phase could detect.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from blinkengage.application.brain.fact_extraction import (
    DraftOutcome,
    FactExtractionService,
)
from blinkengage.application.brain.ingestion_jobs import (
    IngestionJobService,
    JobClaimLost,
    JobView,
)
from blinkengage.core.logging import get_logger
from blinkengage.domain.brain.extraction import ExtractionFailure
from blinkengage.domain.brain.ingestion_jobs import JobState
from blinkengage.domain.brain.retrieval_policy import CrossTenantAccessError

logger = get_logger(__name__)

#: Failures that may succeed on another attempt. Everything else is permanent.
_RETRYABLE: frozenset[ExtractionFailure] = frozenset(
    {ExtractionFailure.PROVIDER_ERROR, ExtractionFailure.UNPARSEABLE_OUTPUT}
)


@dataclass(frozen=True, slots=True)
class BridgeOutcome:
    """What happened to one job. ``deferred`` is not a failure."""

    job: JobView
    drafts: DraftOutcome | None = None
    #: No provider configured. The job is left in ``EXTRACTED`` untouched so a
    #: later run can do the work — settling it would mean recording an empty
    #: extraction that never happened.
    deferred: bool = False
    #: Another worker moved the job first. This one stops.
    lost: bool = False


class ExtractionBridge:
    """Runs 4E against a job that 4D has taken as far as ``EXTRACTED``."""

    def __init__(self, *, jobs: IngestionJobService, extraction: FactExtractionService) -> None:
        self._jobs = jobs
        self._extraction = extraction

    async def process(
        self,
        *,
        job: JobView,
        document_id: UUID,
        source_reference: str,
        actor_user_id: UUID | None = None,
    ) -> BridgeOutcome:
        """``EXTRACTED`` → facts → DRAFTs → ``PROPOSED``.

        Never raises for a bad extraction: every outcome is a job state. The
        single exception is :class:`CrossTenantAccessError`, which is a
        security failure rather than an availability one and must not be
        absorbed into a retry — a leak recorded as "we will try again later"
        is a leak nobody investigates.
        """
        if job.state is not JobState.EXTRACTED:
            # Somebody else already moved it, or the caller is confused. Both
            # are reasons to stop rather than to work.
            return BridgeOutcome(job=job, lost=True)

        if not self._extraction.available:
            logger.info(
                "extraction_deferred_no_provider",
                company_id=str(job.company_id),
                job_id=str(job.id),
            )
            return BridgeOutcome(job=job, deferred=True)

        # Deliberately outside the try: a cross-tenant access must propagate,
        # not become a failure state.
        result = await self._extraction.extract(company_id=job.company_id, document_id=document_id)

        if result.failure is not None:
            return await self._settle_failure(job, result.failure)

        if result.all_invalid:
            # Candidates were offered and none survived validation. The same
            # document will fail the same way, so retrying is waste.
            return await self._settle_failure(job, ExtractionFailure.EXTRACTION_INVALID)

        try:
            # Drafts first. A crash here costs a repeat, and the repeat finds
            # them already present; advancing first would leave a job claiming
            # work that never happened.
            drafts = await self._extraction.draft(
                company_id=job.company_id,
                result=result,
                source_reference=source_reference,
                actor_user_id=actor_user_id,
            )
        except CrossTenantAccessError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "extraction_draft_failed",
                company_id=str(job.company_id),
                job_id=str(job.id),
                exc_info=True,
            )
            return await self._settle_failure(
                job, ExtractionFailure.PROVIDER_ERROR, detail=str(exc)
            )

        try:
            # A document that stated no facts still reaches PROPOSED: the work
            # was done, and "nothing to propose" is an answer.
            moved = await self._jobs.transition(job, JobState.PROPOSED)
        except JobClaimLost:
            # Another worker finished first. Its drafts are the same drafts —
            # creation is idempotent per subject — so stopping loses nothing.
            logger.info(
                "extraction_job_claim_lost",
                company_id=str(job.company_id),
                job_id=str(job.id),
            )
            return BridgeOutcome(job=job, drafts=drafts, lost=True)

        return BridgeOutcome(job=moved, drafts=drafts)

    async def _settle_failure(
        self, job: JobView, failure: ExtractionFailure, *, detail: str = ""
    ) -> BridgeOutcome:
        """Record the failure at the right severity, through 4D's own guard."""
        try:
            settled = await self._jobs.fail(
                job,
                retryable=failure in _RETRYABLE,
                reason=failure.value,
                detail=detail or failure.value,
            )
        except JobClaimLost:
            return BridgeOutcome(job=job, lost=True)
        return BridgeOutcome(job=settled)


__all__ = ["BridgeOutcome", "ExtractionBridge"]
