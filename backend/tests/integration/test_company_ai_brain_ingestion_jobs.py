"""Phase 4D: ingestion work that survives a crash and cannot run twice.

The inputs were already durable — the message and the document outlive a
restart. What did not survive was the knowledge that work had been *started*
and abandoned, and that is the gap a job closes.

Everything here is about what happens when things go wrong: two workers reach
the same job, a worker dies mid-parse, a document fails forever, a replay
arrives. The happy path is one test; the rest are the reason the table exists.
"""

from __future__ import annotations

import ast
import pathlib
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from blinkengage.application.brain.ingestion_jobs import (
    IngestionJobService,
    JobClaimLost,
    JobView,
    job_key,
)
from blinkengage.domain.brain.ingestion_jobs import (
    LEGAL_TRANSITIONS,
    MAX_ATTEMPTS,
    RESUMABLE_STATES,
    InvalidJobTransition,
    JobState,
    assert_transition,
    can_transition,
    failure_state,
    grants_authority,
)
from blinkengage.infrastructure.database.models.knowledge_source import (
    KnowledgeIngestionJob,
)

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "blinkengage"
COMPANY_B = UUID("22222222-2222-2222-2222-222222222222")


# =====================================================================
# Pure state machine
# =====================================================================


class TestStateMachine:
    def test_the_happy_path_is_legal(self) -> None:
        assert can_transition(JobState.RECEIVED, JobState.EXTRACTING)
        assert can_transition(JobState.EXTRACTING, JobState.EXTRACTED)

    def test_extracting_cannot_go_back_to_received(self) -> None:
        """A job somebody abandoned is not one nobody has touched.

        Allowing the reset would erase the only signal that a worker died
        mid-parse, and the stuck job would look brand new forever.
        """
        assert not can_transition(JobState.EXTRACTING, JobState.RECEIVED)

    def test_work_cannot_be_skipped(self) -> None:
        """A retryable failure goes back through EXTRACTING, never straight
        to EXTRACTED: the work has to actually happen again."""
        assert not can_transition(JobState.FAILED_RETRYABLE, JobState.EXTRACTED)
        assert not can_transition(JobState.RECEIVED, JobState.EXTRACTED)

    def test_terminal_states_are_terminal(self) -> None:
        for state in (JobState.FAILED_TERMINAL, JobState.APPROVED, JobState.REJECTED):
            assert LEGAL_TRANSITIONS[state] == frozenset(), state

    def test_an_illegal_transition_raises(self) -> None:
        with pytest.raises(InvalidJobTransition):
            assert_transition(JobState.FAILED_TERMINAL, JobState.EXTRACTING)

    def test_every_state_has_an_entry(self) -> None:
        """A state missing from the table would silently permit nothing, which
        reads as 'terminal' and is a very quiet way to lose work."""
        for state in JobState:
            assert state in LEGAL_TRANSITIONS, state

    def test_resumable_states_are_exactly_the_two_a_sweep_may_take(self) -> None:
        assert frozenset({JobState.RECEIVED, JobState.FAILED_RETRYABLE}) == RESUMABLE_STATES

    def test_a_terminal_failure_is_never_retryable(self) -> None:
        assert failure_state(retryable=False, attempts=0) is JobState.FAILED_TERMINAL

    def test_retries_are_bounded(self) -> None:
        assert failure_state(retryable=True, attempts=0) is JobState.FAILED_RETRYABLE
        assert failure_state(retryable=True, attempts=MAX_ATTEMPTS) is JobState.FAILED_TERMINAL

    def test_no_state_grants_authority(self) -> None:
        """Work completing is not approval. Publication is a human act behind
        ``publication_gate()``, and no job state may substitute for it."""
        for state in JobState:
            assert grants_authority(state) is False, state


class TestJobKey:
    def test_it_is_deterministic(self) -> None:
        message, document = uuid4(), uuid4()
        assert job_key(source_message_id=message, document_id=document) == job_key(
            source_message_id=message, document_id=document
        )

    def test_message_level_and_document_level_keys_differ(self) -> None:
        message = uuid4()
        assert job_key(source_message_id=message, document_id=None) != job_key(
            source_message_id=message, document_id=uuid4()
        )


# =====================================================================
# Against the database
# =====================================================================


@pytest.mark.usefixtures("registered_owner")
class TestJobsAgainstTheDatabase:
    @staticmethod
    async def _company_id(app: Any) -> UUID:
        from blinkengage.infrastructure.database.models.company import Company

        async with app.state.container.session_factory()() as session:
            company = (await session.execute(select(Company))).scalars().first()
            assert company is not None
            return company.id

    @staticmethod
    async def _service(app: Any, session: Any) -> IngestionJobService:
        return IngestionJobService(session=session)

    async def test_a_job_is_created_once_however_often_it_is_requested(self, app: Any) -> None:
        """Replay, redelivery and a re-run sweep all land on the same row."""
        company_id = await self._company_id(app)
        message_id = uuid4()

        async with app.state.container.session_factory()() as session:
            service = IngestionJobService(session=session)
            first = await service.ensure(company_id=company_id, source_message_id=message_id)
            second = await service.ensure(company_id=company_id, source_message_id=message_id)
            await session.commit()

            rows = (await session.execute(select(KnowledgeIngestionJob))).scalars().all()

        assert first.id == second.id
        assert len(rows) == 1
        assert rows[0].state == JobState.RECEIVED.value

    async def test_a_claim_moves_the_job_and_counts_the_attempt(self, app: Any) -> None:
        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            service = IngestionJobService(session=session)
            job = await service.ensure(company_id=company_id, source_message_id=uuid4())
            claimed = await service.claim(job)
            await session.commit()

        assert claimed.state is JobState.EXTRACTING
        assert claimed.attempts == 1

    async def test_two_workers_racing_to_claim_produce_one_winner(self, app: Any) -> None:
        """The compare-and-set is the whole guarantee.

        Both workers read RECEIVED; both issue the update; one matches a row
        and one matches nothing. Without this they would both extract the same
        document and both write the result.
        """
        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            service = IngestionJobService(session=session)
            job = await service.ensure(company_id=company_id, source_message_id=uuid4())
            await session.commit()

            stale = JobView(id=job.id, company_id=company_id, state=JobState.RECEIVED, attempts=0)
            await service.claim(job)
            await session.commit()

            with pytest.raises(JobClaimLost):
                await service.claim(stale)

    async def test_a_crashed_worker_leaves_the_job_visibly_in_progress(self, app: Any) -> None:
        """Durability across a restart: a new session sees EXTRACTING and the
        attempt that was consumed, rather than a job that looks untouched."""
        company_id = await self._company_id(app)
        message_id = uuid4()

        async with app.state.container.session_factory()() as session:
            service = IngestionJobService(session=session)
            job = await service.ensure(company_id=company_id, source_message_id=message_id)
            await service.claim(job)
            await session.commit()
        # ... worker dies here, with nothing else recorded ...

        async with app.state.container.session_factory()() as session:
            row = (await session.execute(select(KnowledgeIngestionJob))).scalars().one()

        assert row.state == JobState.EXTRACTING.value
        assert row.attempts == 1

    async def test_a_retryable_failure_can_be_worked_again(self, app: Any) -> None:
        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            service = IngestionJobService(session=session)
            job = await service.ensure(company_id=company_id, source_message_id=uuid4())
            job = await service.claim(job)
            job = await service.fail(job, retryable=True, reason="PROVIDER_TIMEOUT")
            await session.commit()

            assert job.state is JobState.FAILED_RETRYABLE

            retried = await service.claim(job)
            await session.commit()

        assert retried.state is JobState.EXTRACTING
        assert retried.attempts == 2

    async def test_retries_stop_at_the_cap(self, app: Any) -> None:
        """A job that is retryable forever is a job nobody ever looks at."""
        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            service = IngestionJobService(session=session)
            job = await service.ensure(company_id=company_id, source_message_id=uuid4())
            for _ in range(MAX_ATTEMPTS):
                job = await service.claim(job)
                job = await service.fail(job, retryable=True, reason="PROVIDER_TIMEOUT")
            await session.commit()

        assert job.state is JobState.FAILED_TERMINAL
        assert job.attempts == MAX_ATTEMPTS

    async def test_a_terminal_failure_records_its_reason(self, app: Any) -> None:
        """A terminal failure with no stated reason is indistinguishable from
        one nobody diagnosed."""
        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            service = IngestionJobService(session=session)
            job = await service.ensure(company_id=company_id, source_message_id=uuid4())
            job = await service.claim(job)
            await service.fail(
                job, retryable=False, reason="ENCRYPTED", detail="password-protected"
            )
            await session.commit()

            row = (await session.execute(select(KnowledgeIngestionJob))).scalars().one()

        assert row.state == JobState.FAILED_TERMINAL.value
        assert row.failure_reason == "ENCRYPTED"
        assert row.failure_detail == "password-protected"

    async def test_a_recovered_job_does_not_keep_wearing_its_last_failure(self, app: Any) -> None:
        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            service = IngestionJobService(session=session)
            job = await service.ensure(company_id=company_id, source_message_id=uuid4())
            job = await service.claim(job)
            job = await service.fail(job, retryable=True, reason="PROVIDER_TIMEOUT")
            job = await service.claim(job)
            await service.transition(job, JobState.EXTRACTED)
            await session.commit()

            row = (await session.execute(select(KnowledgeIngestionJob))).scalars().one()

        assert row.state == JobState.EXTRACTED.value
        assert row.failure_reason is None

    async def test_an_illegal_transition_is_refused_against_the_database(self, app: Any) -> None:
        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            service = IngestionJobService(session=session)
            job = await service.ensure(company_id=company_id, source_message_id=uuid4())

            with pytest.raises(InvalidJobTransition):
                await service.transition(job, JobState.EXTRACTED)

    async def test_a_job_cannot_be_moved_from_another_company(self, app: Any) -> None:
        """Tenant scope is in the UPDATE predicate, not merely in the caller.

        A view carrying the wrong company matches no row, so the move fails
        rather than reaching across the boundary.
        """
        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            service = IngestionJobService(session=session)
            job = await service.ensure(company_id=company_id, source_message_id=uuid4())
            await session.commit()

            impersonated = JobView(
                id=job.id, company_id=COMPANY_B, state=JobState.RECEIVED, attempts=0
            )
            with pytest.raises(JobClaimLost):
                await service.claim(impersonated)

    async def test_the_same_key_in_two_companies_is_two_jobs(self, app: Any) -> None:
        from blinkengage.infrastructure.database.models.company import Company

        company_id = await self._company_id(app)
        message_id = uuid4()

        async with app.state.container.session_factory()() as session:
            other = Company(name="Other Co", slug=f"other-{uuid4().hex[:8]}")
            session.add(other)
            await session.commit()
            other_id = other.id

            service = IngestionJobService(session=session)
            first = await service.ensure(company_id=company_id, source_message_id=message_id)
            second = await service.ensure(company_id=other_id, source_message_id=message_id)
            await session.commit()

        assert first.id != second.id

    async def test_the_sweep_returns_only_resumable_work(self, app: Any) -> None:
        company_id = await self._company_id(app)

        async with app.state.container.session_factory()() as session:
            service = IngestionJobService(session=session)
            waiting = await service.ensure(company_id=company_id, source_message_id=uuid4())
            done = await service.ensure(company_id=company_id, source_message_id=uuid4())
            done = await service.claim(done)
            await service.transition(done, JobState.EXTRACTED)
            await session.commit()

            resumable = await service.resumable()

        ids = {job.id for job in resumable}
        assert waiting.id in ids
        assert done.id not in ids


# =====================================================================
# Structural guards
# =====================================================================


class TestStructuralGuards:
    FILES = (
        SRC / "domain" / "brain" / "ingestion_jobs.py",
        SRC / "application" / "brain" / "ingestion_jobs.py",
    )

    def test_jobs_never_write_knowledge_or_call_a_model(self) -> None:
        """4E and publication are not authorized."""
        for path in self.FILES:
            tree = ast.parse(path.read_text(), filename=str(path))
            imported = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names
            } | {(node.module or "") for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
            for needle in (
                "KnowledgeRecord",
                "KnowledgeProposal",
                "publication_gate",
                "AiService",
                "ai_provider",
            ):
                assert not any(needle in name for name in imported), f"{path.name}: {needle}"

    def test_no_second_queue_or_scheduler_is_introduced(self) -> None:
        """Reuse Celery and the outbox. A second orchestration system is two
        places to look when ingestion stops."""
        for path in self.FILES:
            text = path.read_text()
            for needle in ("apscheduler", "rq.Queue", "dramatiq", "kafka"):
                assert needle not in text, f"{path.name}: {needle}"

    def test_every_transition_goes_through_the_guarded_helper(self) -> None:
        """A direct UPDATE of ``state`` would bypass both the legality check
        and the compare-and-set, which are the whole point of this module."""
        path = SRC / "application" / "brain" / "ingestion_jobs.py"
        tree = ast.parse(path.read_text(), filename=str(path))

        updates = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "update"
        ]
        assert len(updates) == 1, "state is written in exactly one place"
