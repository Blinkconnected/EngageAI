"""Reading Learning. No write method to reach for.

Separate from ``LearningObservationService`` for the reason the Memory
Platform separates its own reader: a class that both read and wrote would
make "who can write Learning?" a question about which method you called
rather than which object you hold, and charter I-2 says Learning writes
only its own tables through one path.
"""

from __future__ import annotations

from uuid import UUID

from blinkengage.api.schemas.learning import LearningHealthResponse
from blinkengage.domain.company_settings import is_learning_enabled
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.domain.learning_observation import PIPELINE_VERSION, ObservationState
from blinkengage.infrastructure.database.models.learning import (
    LearningObservation,
    LearningRun,
)
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.learning_repository import (
    LearningObservationRepository,
    LearningRunRepository,
)


class LearningQueryService:
    def __init__(
        self,
        *,
        observations: LearningObservationRepository,
        runs: LearningRunRepository,
        companies: CompanyRepository,
    ) -> None:
        self._observations = observations
        self._runs = runs
        self._companies = companies

    async def list_observations(
        self,
        *,
        company_id: UUID,
        state: ObservationState | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[LearningObservation], int]:
        return await self._observations.list_for_company(
            company_id=company_id, state=state, limit=limit, offset=offset
        )

    async def get_for_source(self, *, company_id: UUID, source_id: UUID) -> LearningObservation:
        """What Learning extracted from one conversation, and from what.

        The traceability endpoint. Everything an observation claims must
        be answerable from the refs it carries, which is why they are
        loaded here rather than behind a second call nobody makes.
        """
        row = await self._observations.get_for_source(
            company_id=company_id, source_id=source_id, with_refs=True
        )
        if row is None:
            raise EntityNotFoundError("LearningObservation", source_id)
        return row

    async def list_runs(self, *, limit: int = 20) -> list[LearningRun]:
        """Execution history — what ran, over what window, with what result.

        Not company-scoped, and that is the one read here that is not.
        A run is a *sweep*, and the settle sweep serves every company in
        one pass, so its row carries no company at all. Runs expose no
        customer content — a type, a window and three counts — which is
        what makes that acceptable rather than a leak.
        """
        return await self._runs.recent(limit=limit)

    async def health(self, *, company_id: UUID) -> LearningHealthResponse:
        company = await self._companies.get_by_id(company_id)
        settings = company.settings if company is not None else {}
        counts = await self._observations.counts_by_state(company_id=company_id)
        recent = await self._runs.recent(limit=10)

        return LearningHealthResponse(
            learning_enabled=is_learning_enabled(settings),
            pipeline_version=PIPELINE_VERSION,
            observations_by_state=counts,
            feedback_ratio=await self._observations.feedback_ratio(company_id=company_id),
            observations_awaiting_settlement=counts.get(ObservationState.PENDING.value, 0),
            last_run_at=recent[0].started_at if recent else None,
            recent_run_errors=sum(run.errors for run in recent),
        )


__all__ = ["LearningQueryService"]
