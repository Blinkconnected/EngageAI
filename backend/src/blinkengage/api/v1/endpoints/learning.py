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

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from blinkengage.api.deps import (
    get_learning_pattern_query_service,
    get_learning_query_service,
    get_learning_settings_service,
    get_learning_shadow_service,
    require_permission,
)
from blinkengage.api.schemas.learning import (
    AnomalyResponse,
    ClusterMemberResponse,
    ClusterNeighbourResponse,
    ClusterResponse,
    LearningHealthResponse,
    LearningMetricsResponse,
    LearningRunResponse,
    LearningThresholdsResponse,
    LearningThresholdsUpdateRequest,
    LearningThresholdsUpdateResponse,
    ObservationFeaturesResponse,
    ObservationRefResponse,
    ObservationResponse,
    ThresholdChangeResponse,
    TrendResponse,
    UnclusteredObservationResponse,
)
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.application.services.learning_pattern_query_service import (
    LearningPatternQueryService,
)
from blinkengage.application.services.learning_query_service import LearningQueryService
from blinkengage.application.services.learning_settings_service import (
    LearningSettingsService,
)
from blinkengage.application.services.learning_shadow_service import LearningShadowService
from blinkengage.core.auth_context import AuthContext
from blinkengage.domain.learning_cluster import ClusterState
from blinkengage.domain.learning_observation import ObservationState
from blinkengage.infrastructure.database.models.learning import LearningObservation
from blinkengage.infrastructure.database.models.learning_analysis import (
    LearningAnomaly,
    LearningCluster,
)

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


# ---------------------------------------------------------------------------
# Phase 2 — what the platform found. Read-only, like everything above it.
# ---------------------------------------------------------------------------


def _cluster_response(row: LearningCluster, *, detailed: bool = False) -> ClusterResponse:
    return ClusterResponse(
        id=row.id,
        signature=row.signature,
        algorithm_version=row.algorithm_version,
        pipeline_version=row.pipeline_version,
        state=row.state,
        size=row.size,
        distinct_customers=row.distinct_customers,
        distinct_days=row.distinct_days,
        confidence=float(row.confidence),
        stability=float(row.stability),
        meets_floors=bool(row.meets_floors),
        first_seen=row.first_seen,
        last_seen=row.last_seen,
        language_distribution=dict(row.language_distribution or {}),
        feature_summary=dict(row.feature_summary or {}),
        centroid=dict(row.centroid or {}) if detailed else None,
        members=(
            [
                ClusterMemberResponse(
                    observation_id=member.observation_id,
                    observed_at=member.observed_at,
                    similarity=float(member.similarity),
                )
                for member in sorted(row.members, key=lambda item: item.observed_at)
            ]
            if detailed
            else None
        ),
    )


@router.get("/clusters", response_model=Page[ClusterResponse])
async def list_clusters(
    auth: Annotated[AuthContext, Depends(require_permission("intelligence.read"))],
    service: Annotated[LearningPatternQueryService, Depends(get_learning_pattern_query_service)],
    page_params: Annotated[PageParams, Depends()],
    state: ClusterState | None = None,
    min_confidence: Annotated[float | None, Query(ge=0.0, le=1.0)] = None,
) -> Page[ClusterResponse]:
    """What recurs, strongest first.

    ``forming`` clusters are included rather than hidden: a shape that has
    not yet cleared the floors is exactly what somebody investigating an
    emerging issue wants to see, and filtering it out of the default view
    would make the platform look like it noticed nothing.
    """
    items, total = await service.list_clusters(
        company_id=auth.company_id,
        state=state,
        min_confidence=min_confidence,
        limit=page_params.page_size,
        offset=page_params.offset,
    )
    return Page(
        items=[_cluster_response(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.get("/clusters/{cluster_id}", response_model=ClusterResponse)
async def get_cluster(
    cluster_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("intelligence.read"))],
    service: Annotated[LearningPatternQueryService, Depends(get_learning_pattern_query_service)],
) -> ClusterResponse:
    """One cluster, its centroid and every observation in it.

    The traceability endpoint for phase 2, and the same argument as phase
    1's: a finding nobody can trace back to the conversations behind it is
    an assertion.
    """
    return _cluster_response(
        await service.get_cluster(company_id=auth.company_id, cluster_id=cluster_id),
        detailed=True,
    )


@router.get("/trends", response_model=Page[TrendResponse])
async def list_trends(
    auth: Annotated[AuthContext, Depends(require_permission("intelligence.read"))],
    service: Annotated[LearningPatternQueryService, Depends(get_learning_pattern_query_service)],
    page_params: Annotated[PageParams, Depends()],
    kind: str | None = None,
    include_provisional: bool = False,
) -> Page[TrendResponse]:
    """Confirmed trends by default.

    ``include_provisional`` shows findings that cleared the statistics
    once and have not yet held for a second window. Off by default because
    mixing them in would defeat the persistence gate — a single window is
    not a direction, and a list that treated it as one would be the noisy
    inbox the correction exists to prevent.
    """
    items, total = await service.list_trends(
        company_id=auth.company_id,
        kind=kind,
        include_provisional=include_provisional,
        limit=page_params.page_size,
        offset=page_params.offset,
    )
    return Page(
        items=[
            TrendResponse(
                id=item.id,
                subject_kind=item.subject_kind,
                subject_key=item.subject_key,
                kind=item.kind,
                p_value=float(item.p_value),
                q_value=float(item.q_value),
                recent_count=item.recent_count,
                baseline_count=item.baseline_count,
                rate_ratio=None if item.rate_ratio is None else float(item.rate_ratio),
                window_start=item.window_start,
                window_end=item.window_end,
                window_days=item.window_days,
                windows_held=item.windows_held,
                provisional=bool(item.provisional),
                detected_at=item.detected_at,
                detail=dict(item.detail or {}),
            )
            for item in items
        ],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.get("/anomalies", response_model=Page[AnomalyResponse])
async def list_anomalies(
    auth: Annotated[AuthContext, Depends(require_permission("intelligence.read"))],
    service: Annotated[LearningPatternQueryService, Depends(get_learning_pattern_query_service)],
    page_params: Annotated[PageParams, Depends()],
    kind: str | None = None,
    severity: str | None = None,
) -> Page[AnomalyResponse]:
    """Things unlike their own history.

    Nothing here was sent anywhere. Phase 2 stores anomalies and notifies
    nobody, so that their precision can be measured before anything is
    wired to them.
    """
    items, total = await service.list_anomalies(
        company_id=auth.company_id,
        kind=kind,
        severity=severity,
        limit=page_params.page_size,
        offset=page_params.offset,
    )
    return Page(
        items=[_anomaly_response(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


def _anomaly_response(row: LearningAnomaly) -> AnomalyResponse:
    return AnomalyResponse(
        id=row.id,
        kind=row.kind,
        subject_key=row.subject_key,
        cluster_id=row.cluster_id,
        severity=row.severity,
        observed=float(row.observed),
        baseline=float(row.baseline),
        score=float(row.score),
        window_start=row.window_start,
        window_end=row.window_end,
        detected_at=row.detected_at,
        summary=row.summary,
        detail=dict(row.detail or {}),
    )


@router.get("/metrics", response_model=LearningMetricsResponse)
async def learning_metrics(
    auth: Annotated[AuthContext, Depends(require_permission("intelligence.read"))],
    service: Annotated[LearningPatternQueryService, Depends(get_learning_pattern_query_service)],
) -> LearningMetricsResponse:
    """Phase 2's own numbers: what it built, and how settled it is."""
    return await service.metrics(company_id=auth.company_id)


# ---------------------------------------------------------------------------
# Phase 2.5 — operator inspection. Read-only, like everything above it.
# ---------------------------------------------------------------------------


@router.get("/shadow")
async def shadow_metrics(
    auth: Annotated[AuthContext, Depends(require_permission("intelligence.read"))],
    service: Annotated[LearningShadowService, Depends(get_learning_shadow_service)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> dict[str, Any]:
    """Everything shadow validation measures, in one payload.

    Deliberately untyped at the edges: this is a diagnostic surface whose
    shape will change as the questions change, and pinning it to a
    response model now would make every future measurement a breaking
    change to an endpoint only operators read.

    Where a number cannot be computed honestly it is **null with a
    reason**, never zero. "Cluster stability: 0.0" on an installation
    with nothing to measure would read as churn.
    """
    return await service.metrics(company_id=auth.company_id, days=days)


@router.get("/unclustered", response_model=list[UnclusteredObservationResponse])
async def unclustered_observations(
    auth: Annotated[AuthContext, Depends(require_permission("intelligence.read"))],
    service: Annotated[LearningShadowService, Depends(get_learning_shadow_service)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[UnclusteredObservationResponse]:
    """What the platform observed and could not group, and why.

    Answers "which observations are never clustered?" — a question the
    cluster list cannot, because it is by construction a list of things
    that *did* group.
    """
    return [
        UnclusteredObservationResponse(
            observation_id=item.observation_id,
            observed_at=item.observed_at,
            topics=item.topics,
            entities=item.entities,
            reason=item.reason,
        )
        for item in await service.unclustered(company_id=auth.company_id, limit=limit)
    ]


@router.get("/clusters/{cluster_id}/neighbours", response_model=list[ClusterNeighbourResponse])
async def cluster_neighbours(
    cluster_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("intelligence.read"))],
    service: Annotated[LearningShadowService, Depends(get_learning_shadow_service)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[ClusterNeighbourResponse]:
    """The clusters most similar to this one.

    Answers "which clusters are clearly wrong?" from the other side: two
    neighbours that a human reads as the same thing, sitting below the
    merge threshold, *is* the evidence that the threshold is wrong.
    """
    return [
        ClusterNeighbourResponse(**item)
        for item in await service.neighbours(
            company_id=auth.company_id, cluster_id=cluster_id, limit=limit
        )
    ]


@router.get("/thresholds", response_model=LearningThresholdsResponse)
async def read_thresholds(
    auth: Annotated[AuthContext, Depends(require_permission("intelligence.read"))],
    service: Annotated[LearningSettingsService, Depends(get_learning_settings_service)],
) -> LearningThresholdsResponse:
    """The thresholds in effect, and where each came from."""
    return LearningThresholdsResponse(**await service.read(company_id=auth.company_id))


@router.patch("/thresholds", response_model=LearningThresholdsUpdateResponse)
async def update_thresholds(
    payload: LearningThresholdsUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("intelligence.manage"))],
    service: Annotated[LearningSettingsService, Depends(get_learning_settings_service)],
) -> LearningThresholdsUpdateResponse:
    """Change a threshold. **Every change is recorded.**

    Behind `intelligence.manage` rather than `intelligence.read`, because
    this is the one control on this surface that changes what the
    platform will find. Everything else here only looks.

    Out-of-bounds values are **refused, not clamped**: clamping would
    accept the request and quietly do something else, and the operator
    would leave believing a number that is not in effect.
    """
    values = {
        name: value
        for name, value in (
            ("cluster_join_threshold", payload.cluster_join_threshold),
            ("cluster_merge_threshold", payload.cluster_merge_threshold),
        )
        if value is not None
    }
    result = await service.update(
        company_id=auth.company_id,
        actor_user_id=auth.user_id,
        values=values,
        reason=payload.reason,
    )
    return LearningThresholdsUpdateResponse(
        thresholds=result.thresholds,
        changes=[
            ThresholdChangeResponse(
                threshold=change.name, previous=change.previous, current=change.current
            )
            for change in result.changes
        ],
        clusters_built_under_previous_thresholds=result.clusters_invalidated,
    )
