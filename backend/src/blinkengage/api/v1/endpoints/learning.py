"""The Learning Platform's HTTP surface — phase 1.

**Read-only.** Learning is reached by events and by humans, never by
another service's request path (charter §4), and in phase 1 it proposes
nothing — so there is no endpoint to approve, promote or dismiss a
candidate, because there are no candidates.

The one endpoint that matters most is
``GET /intelligence/observations/{conversation_id}``: it answers *what did
Learning extract from this conversation, and from what?* — the
traceability the charter requires, in one call.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from blinkengage.api.deps import get_learning_query_service, require_permission
from blinkengage.api.schemas.learning import (
    LearningHealthResponse,
    LearningRunResponse,
    ObservationFeaturesResponse,
    ObservationRefResponse,
    ObservationResponse,
)
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.application.services.learning_query_service import LearningQueryService
from blinkengage.core.auth_context import AuthContext
from blinkengage.domain.learning_observation import ObservationState
from blinkengage.infrastructure.database.models.learning import LearningObservation

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


def _to_response(
    observation: LearningObservation, *, with_refs: bool = False
) -> ObservationResponse:
    return ObservationResponse(
        id=observation.id,
        source_kind=observation.source_kind,
        source_id=observation.source_id,
        channel=observation.channel,
        observed_at=observation.observed_at,
        customer_id=observation.customer_id,
        pipeline_version=observation.pipeline_version,
        state=observation.state,
        exclusion_reason=observation.exclusion_reason,
        human_authored_count=observation.human_authored_count,
        ai_generated_count=observation.ai_generated_count,
        ai_assisted_count=observation.ai_assisted_count,
        human_authored_fraction=float(observation.human_authored_fraction),
        resolved=observation.resolved,
        resolved_by=observation.resolved_by,
        outcome_attributable=observation.outcome_attributable,
        reopened=observation.reopened,
        escalated=observation.escalated,
        first_contact_resolution=observation.first_contact_resolution,
        handling_seconds=observation.handling_seconds,
        csat_score=observation.csat_score,
        outcome_quality=(
            None if observation.outcome_quality is None else float(observation.outcome_quality)
        ),
        settled=observation.settled,
        settle_due_at=observation.settle_due_at,
        features=(
            ObservationFeaturesResponse(
                language=observation.features.language,
                topics=list(observation.features.topics),
                entities=list(observation.features.entities),
                inbound_turns=observation.features.inbound_turns,
                outbound_turns=observation.features.outbound_turns,
                human_char_count=observation.features.human_char_count,
            )
            if observation.features is not None
            else None
        ),
        content_refs=(
            [
                ObservationRefResponse(
                    ref_kind=ref.ref_kind, ref_id=ref.ref_id, ordinal=ref.ordinal
                )
                for ref in sorted(observation.content_refs, key=lambda r: r.ordinal)
            ]
            if with_refs
            else None
        ),
    )


@router.get("/observations", response_model=Page[ObservationResponse])
async def list_observations(
    auth: Annotated[AuthContext, Depends(require_permission("intelligence.read"))],
    service: Annotated[LearningQueryService, Depends(get_learning_query_service)],
    page_params: Annotated[PageParams, Depends()],
    state: ObservationState | None = None,
) -> Page[ObservationResponse]:
    """What Learning has observed.

    ``state`` is filterable because the three states answer different
    questions: ``excluded`` is *what did the platform decline to learn
    from, and why* — an audit view, and the reason an excluded observation
    is recorded at all rather than simply not written.
    """
    items, total = await service.list_observations(
        company_id=auth.company_id,
        state=state,
        limit=page_params.page_size,
        offset=page_params.offset,
    )
    return Page(
        items=[_to_response(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.get("/observations/{conversation_id}", response_model=ObservationResponse)
async def get_observation(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("intelligence.read"))],
    service: Annotated[LearningQueryService, Depends(get_learning_query_service)],
) -> ObservationResponse:
    """What was extracted from one conversation, and from what.

    Returns the newest pipeline version's observation. Content refs are
    included here and omitted from the list: traceability is a question
    asked of one observation at a time, and loading refs for every row of
    a page would be a join nobody reads.
    """
    observation = await service.get_for_source(
        company_id=auth.company_id, source_id=conversation_id
    )
    return _to_response(observation, with_refs=True)


@router.get("/runs", response_model=list[LearningRunResponse])
async def list_runs(
    auth: Annotated[AuthContext, Depends(require_permission("intelligence.read"))],
    service: Annotated[LearningQueryService, Depends(get_learning_query_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[LearningRunResponse]:
    """Execution history — what ran, over what window, with what result."""
    runs = await service.list_runs(limit=limit)
    return [
        LearningRunResponse(
            id=run.id,
            run_type=run.run_type,
            pipeline_version=run.pipeline_version,
            window_start=run.window_start,
            window_end=run.window_end,
            started_at=run.started_at,
            finished_at=run.finished_at,
            status=run.status,
            items_in=run.items_in,
            items_out=run.items_out,
            errors=run.errors,
        )
        for run in runs
    ]


@router.get("/health", response_model=LearningHealthResponse)
async def learning_health(
    auth: Annotated[AuthContext, Depends(require_permission("intelligence.read"))],
    service: Annotated[LearningQueryService, Depends(get_learning_query_service)],
) -> LearningHealthResponse:
    """Is Learning healthy, and is it dangerous?

    Both on one screen deliberately. ``feedback_ratio`` — the share of
    observed content the platform itself wrote — is the number most likely
    to be quietly wrong, and an operator should not have to know it lives
    somewhere else.
    """
    return await service.health(company_id=auth.company_id)
