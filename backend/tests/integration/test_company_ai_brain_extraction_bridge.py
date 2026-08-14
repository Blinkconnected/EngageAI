"""The 4D → 4E bridge, against a real database.

Structural assertions were enough while the pieces were separate. This is where
they meet, so these run against real jobs, real documents and real
``knowledge_records`` rows — the questions being asked are "what is actually in
the table afterwards" and "what happens when the same work runs twice", and
neither can be answered by reading the source.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import orjson
import pytest
from sqlalchemy import select

from blinkengage.application.brain.extraction_bridge import ExtractionBridge
from blinkengage.application.brain.fact_extraction import FactExtractionService
from blinkengage.application.brain.ingestion_jobs import IngestionJobService, JobView
from blinkengage.application.services.knowledge_record_service import (
    KnowledgeRecordService,
)
from blinkengage.domain.brain.ingestion_jobs import JobState
from blinkengage.domain.brain.retrieval_policy import CrossTenantAccessError
from blinkengage.domain.knowledge_records import KnowledgeLifecycleState
from blinkengage.infrastructure.database.models.knowledge_record import KnowledgeRecord
from blinkengage.infrastructure.database.models.knowledge_source import (
    KnowledgeDocument,
)
from blinkengage.infrastructure.repositories.knowledge_record_repository import (
    KnowledgeRecordRepository,
)

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "blinkengage"
BRIDGE = SRC / "application" / "brain" / "extraction_bridge.py"

FACT = {
    "record_type": "PRICE",
    "subject_label": "DIA 500 Mbps",
    "attributes": {"amount": "195", "currency": "JOD"},
    "source_passage": "From 1 September, DIA 500 Mbps will be 195 JOD.",
    "confidence": "HIGH",
    "effective_from": "2026-09-01",
}


class _Provider:
    """Stands in for AiProvider. Never a real model."""

    model_identifier = "test-model-1"

    def __init__(self, reply: str | None = None, error: Exception | None = None) -> None:
        self._reply = reply if reply is not None else orjson.dumps({"facts": [FACT]}).decode()
        self._error = error
        self.calls = 0

    async def complete(self, **_: Any) -> str:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._reply


class _NullEvents:
    async def publish(self, event: Any) -> None:
        return None


@pytest.mark.usefixtures("registered_owner")
class TestBridge:
    @staticmethod
    async def _company_id(app: Any) -> UUID:
        from blinkengage.infrastructure.database.models.company import Company

        async with app.state.container.session_factory()() as session:
            company = (await session.execute(select(Company))).scalars().first()
            assert company is not None
            return company.id

    @staticmethod
    async def _document(session: Any, company_id: UUID, text: str | None = "price list") -> UUID:
        document = KnowledgeDocument(
            company_id=company_id,
            filename="pricing.pdf",
            content_hash=uuid4().hex,
            size_bytes=10,
            status="EXTRACTED",
            extracted_text=text,
        )
        session.add(document)
        await session.flush()
        return document.id

    @staticmethod
    def _bridge(session: Any, provider: Any) -> tuple[ExtractionBridge, IngestionJobService]:
        jobs = IngestionJobService(session=session, events=_NullEvents())
        records = KnowledgeRecordService(
            records=KnowledgeRecordRepository(session), events=_NullEvents()
        )
        extraction = FactExtractionService(session=session, records=records, provider=provider)
        return ExtractionBridge(jobs=jobs, extraction=extraction), jobs

    async def _job_at_extracted(
        self, session: Any, jobs: IngestionJobService, company_id: UUID
    ) -> JobView:
        job = await jobs.ensure(company_id=company_id, source_message_id=uuid4())
        job = await jobs.claim(job)
        return await jobs.transition(job, JobState.EXTRACTED)

    @staticmethod
    async def _drafts(session: Any, company_id: UUID) -> list[KnowledgeRecord]:
        found = await session.execute(
            select(KnowledgeRecord).where(KnowledgeRecord.company_id == company_id)
        )
        return list(found.scalars().all())

    # --- the happy path -------------------------------------------------

    async def test_extracted_becomes_proposed_and_creates_a_draft(self, app: Any) -> None:
        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            bridge, jobs = self._bridge(session, _Provider())
            job = await self._job_at_extracted(session, jobs, company_id)
            document_id = await self._document(session, company_id)

            outcome = await bridge.process(
                job=job, document_id=document_id, source_reference="email:msg-1"
            )
            await session.commit()

            drafts = await self._drafts(session, company_id)

        assert outcome.job.state is JobState.PROPOSED
        assert outcome.drafts is not None
        assert len(outcome.drafts.created) == 1
        assert len(drafts) == 1

    async def test_the_draft_keeps_its_evidence_and_provenance(self, app: Any) -> None:
        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            bridge, jobs = self._bridge(session, _Provider())
            job = await self._job_at_extracted(session, jobs, company_id)
            document_id = await self._document(session, company_id)
            await bridge.process(job=job, document_id=document_id, source_reference="email:msg-1")
            await session.commit()
            draft = (await self._drafts(session, company_id))[0]

        reference = draft.source_reference or ""
        assert "From 1 September" in reference, "the passage must survive"
        assert "confidence=HIGH" in reference
        assert "model=test-model-1" in reference
        assert "extractor=" in reference
        assert "email:msg-1" in reference
        assert draft.effective_from == datetime(2026, 9, 1, tzinfo=UTC)
        assert draft.attributes["amount"] == "195"

    async def test_nothing_created_is_active(self, app: Any) -> None:
        """The whole point. Extraction proposes; only a human publishes."""
        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            bridge, jobs = self._bridge(session, _Provider())
            job = await self._job_at_extracted(session, jobs, company_id)
            document_id = await self._document(session, company_id)
            await bridge.process(job=job, document_id=document_id, source_reference="s")
            await session.commit()

            for draft in await self._drafts(session, company_id):
                assert draft.lifecycle_state == KnowledgeLifecycleState.DRAFT
                assert draft.approved_by_user_id is None
                assert draft.approved_at is None

    async def test_a_document_with_no_facts_still_reaches_proposed(self, app: Any) -> None:
        """Work was done; "nothing to propose" is an answer, not a failure."""
        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            bridge, jobs = self._bridge(session, _Provider(reply='{"facts": []}'))
            job = await self._job_at_extracted(session, jobs, company_id)
            document_id = await self._document(session, company_id)

            outcome = await bridge.process(job=job, document_id=document_id, source_reference="s")
            await session.commit()

        assert outcome.job.state is JobState.PROPOSED
        assert await self._drafts(session, company_id) == []

    # --- idempotency ----------------------------------------------------

    async def test_a_replay_does_not_create_a_second_draft(self, app: Any) -> None:
        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            bridge, jobs = self._bridge(session, _Provider())
            job = await self._job_at_extracted(session, jobs, company_id)
            document_id = await self._document(session, company_id)

            await bridge.process(job=job, document_id=document_id, source_reference="s")
            await session.commit()

            # The same work again, from a stale view of the job.
            replay = JobView(
                id=job.id, company_id=company_id, state=JobState.EXTRACTED, attempts=job.attempts
            )
            second = await bridge.process(job=replay, document_id=document_id, source_reference="s")
            await session.commit()

            drafts = await self._drafts(session, company_id)

        assert len(drafts) == 1, "the second run must not duplicate the draft"
        assert second.drafts is not None
        assert second.drafts.duplicate == 1
        assert second.drafts.created == ()

    async def test_a_job_already_moved_by_another_worker_is_left_alone(self, app: Any) -> None:
        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            bridge, jobs = self._bridge(session, _Provider())
            job = await self._job_at_extracted(session, jobs, company_id)
            document_id = await self._document(session, company_id)
            await jobs.transition(job, JobState.PROPOSED)
            await session.commit()

            stale = JobView(id=job.id, company_id=company_id, state=JobState.PROPOSED, attempts=1)
            outcome = await bridge.process(job=stale, document_id=document_id, source_reference="s")

        # Not in EXTRACTED, so the bridge declines without calling a provider.
        assert outcome.lost is True

    # --- failure classification ------------------------------------------

    async def test_a_provider_error_is_retryable(self, app: Any) -> None:
        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            bridge, jobs = self._bridge(session, _Provider(error=TimeoutError("gateway timeout")))
            job = await self._job_at_extracted(session, jobs, company_id)
            document_id = await self._document(session, company_id)

            outcome = await bridge.process(job=job, document_id=document_id, source_reference="s")
            await session.commit()

        assert outcome.job.state is JobState.FAILED_RETRYABLE

    async def test_unparseable_output_is_retryable(self, app: Any) -> None:
        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            bridge, jobs = self._bridge(session, _Provider(reply="I cannot help."))
            job = await self._job_at_extracted(session, jobs, company_id)
            document_id = await self._document(session, company_id)

            outcome = await bridge.process(job=job, document_id=document_id, source_reference="s")
            await session.commit()

        assert outcome.job.state is JobState.FAILED_RETRYABLE

    async def test_all_invalid_facts_are_terminal(self, app: Any) -> None:
        """The same document fails the same way; retrying is waste."""
        company_id = await self._company_id(app)
        broken = dict(FACT, source_passage="")

        async with app.state.container.session_factory()() as session:
            bridge, jobs = self._bridge(
                session, _Provider(reply=orjson.dumps({"facts": [broken]}).decode())
            )
            job = await self._job_at_extracted(session, jobs, company_id)
            document_id = await self._document(session, company_id)

            outcome = await bridge.process(job=job, document_id=document_id, source_reference="s")
            await session.commit()

            row = await session.get(
                __import__(
                    "blinkengage.infrastructure.database.models.knowledge_source",
                    fromlist=["KnowledgeIngestionJob"],
                ).KnowledgeIngestionJob,
                job.id,
            )

        assert outcome.job.state is JobState.FAILED_TERMINAL
        assert row is not None
        assert row.failure_reason == "EXTRACTION_INVALID"

    async def test_an_empty_document_is_terminal(self, app: Any) -> None:
        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            bridge, jobs = self._bridge(session, _Provider())
            job = await self._job_at_extracted(session, jobs, company_id)
            document_id = await self._document(session, company_id, text="")

            outcome = await bridge.process(job=job, document_id=document_id, source_reference="s")
            await session.commit()

        assert outcome.job.state is JobState.FAILED_TERMINAL

    async def test_a_failed_job_creates_no_draft(self, app: Any) -> None:
        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            bridge, jobs = self._bridge(session, _Provider(error=TimeoutError("x")))
            job = await self._job_at_extracted(session, jobs, company_id)
            document_id = await self._document(session, company_id)
            await bridge.process(job=job, document_id=document_id, source_reference="s")
            await session.commit()

            assert await self._drafts(session, company_id) == []

    # --- provider absence -------------------------------------------------

    async def test_no_provider_leaves_the_job_where_it_was(self, app: Any) -> None:
        """Deferred, not settled. Recording an empty extraction that never
        happened would lose the document silently."""
        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            bridge, jobs = self._bridge(session, None)
            job = await self._job_at_extracted(session, jobs, company_id)
            document_id = await self._document(session, company_id)

            outcome = await bridge.process(job=job, document_id=document_id, source_reference="s")
            await session.commit()

        assert outcome.deferred is True
        assert outcome.job.state is JobState.EXTRACTED
        assert await self._drafts(session, company_id) == []

    # --- tenant isolation --------------------------------------------------

    async def test_a_document_from_another_company_raises_and_is_not_a_failure_state(
        self, app: Any
    ) -> None:
        """A leak must not be absorbed into "we will try again later"."""
        from blinkengage.infrastructure.database.models.company import Company

        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            other = Company(name="Other", slug=f"o-{uuid4().hex[:8]}")
            session.add(other)
            await session.flush()

            bridge, jobs = self._bridge(session, _Provider())
            job = await self._job_at_extracted(session, jobs, company_id)
            foreign_document = await self._document(session, other.id)

            with pytest.raises(CrossTenantAccessError):
                await bridge.process(job=job, document_id=foreign_document, source_reference="s")

    async def test_drafts_belong_to_the_jobs_company(self, app: Any) -> None:
        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            bridge, jobs = self._bridge(session, _Provider())
            job = await self._job_at_extracted(session, jobs, company_id)
            document_id = await self._document(session, company_id)
            await bridge.process(job=job, document_id=document_id, source_reference="s")
            await session.commit()

            for draft in await self._drafts(session, company_id):
                assert draft.company_id == company_id


class TestStructuralGuards:
    def test_the_bridge_never_publishes(self) -> None:
        tree = ast.parse(BRIDGE.read_text(), filename=str(BRIDGE))
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

        for forbidden in ("publish", "supersede", "archive", "publication_gate"):
            assert forbidden not in called, forbidden

    def test_the_bridge_offers_no_tools_and_adds_no_orchestration(self) -> None:
        source = BRIDGE.read_text()

        assert "complete_with_tools" not in source
        for needle in ("apscheduler", "dramatiq", "kafka", "rq.Queue", "celery"):
            assert needle not in source.lower(), needle

    def test_cross_tenant_errors_are_re_raised_not_settled(self) -> None:
        """Asserted structurally as well as behaviourally: the re-raise is one
        line and easy to delete while 'tidying' the handler."""
        source = BRIDGE.read_text()

        assert "except CrossTenantAccessError:" in source
        assert "raise" in source
