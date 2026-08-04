"""The Memory Platform's HTTP surface.

See ``docs/architecture/memory-platform.md``.

Deliberately a **platform** API rather than an AI one. Nothing here
decides what is worth remembering; callers do — an agent writing a note, a
CRM sync, a workflow action, and later the AI Engine. What this offers is
one way to record an observation with its evidence, one way to read what
is remembered, and one way to erase it.

Writes go through ``MemoryManager`` without exception, including these
endpoints. The route handler resolves the caller and the tenant and then
hands off; it does not touch a repository, because the moment an endpoint
writes a fact directly, "every fact has evidence" stops being a property
of the store.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from blinkengage.api.deps import (
    get_conversation_memory_service,
    get_memory_erasure_service,
    get_memory_manager,
    get_memory_query_service,
    require_permission,
)
from blinkengage.api.schemas.memory import (
    CommitmentModel,
    CorrectFactRequest,
    ErasureResponse,
    EvidenceResponse,
    MemoryFactResponse,
    MemoryStatusResponse,
    OpenQuestionModel,
    RecordFactRequest,
    ResolvedEntityModel,
    SuppressFactRequest,
    WorkingMemoryResponse,
    WorkingMemoryUpdateRequest,
)
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.application.services.conversation_memory_service import (
    ConversationMemoryService,
)
from blinkengage.application.services.memory_erasure_service import MemoryErasureService
from blinkengage.application.services.memory_manager import MemoryManager
from blinkengage.application.services.memory_query_service import MemoryQueryService
from blinkengage.core.auth_context import AuthContext
from blinkengage.domain.conversation_memory import (
    Commitment,
    EntityKind,
    OpenQuestion,
    ResolvedEntity,
    WorkingMemory,
)
from blinkengage.domain.memory import (
    CreatedFrom,
    EvidenceRef,
    EvidenceSourceType,
    HumanState,
    LifecycleState,
    MemoryTier,
    SubjectRef,
    SubjectType,
)
from blinkengage.domain.memory_lifecycle import display_label
from blinkengage.infrastructure.database.models.memory import MemoryEvidence, MemoryFact

router = APIRouter(prefix="/memory", tags=["memory"])


def _fact_to_response(
    fact: MemoryFact, *, evidence: list[MemoryEvidence] | None = None
) -> MemoryFactResponse:
    return MemoryFactResponse(
        id=fact.id,
        tier=MemoryTier(fact.tier),
        fact_type=fact.fact_type,
        subject_type=SubjectType(fact.subject_type),
        subject_id=fact.subject_id,
        statement=fact.statement,
        attributes=dict(fact.attributes or {}),
        attributes_schema_version=fact.attributes_schema_version,
        confidence=float(fact.confidence),
        confidence_state=fact.confidence_state,
        confidence_direction=fact.confidence_direction,
        lifecycle_state=LifecycleState(fact.lifecycle_state),
        display_label=display_label(
            confidence_state=fact.confidence_state,
            lifecycle=LifecycleState(fact.lifecycle_state),
            human_state=HumanState(fact.human_state),
            contradicted=fact.contradiction_count > 0,
        ),
        support_count=fact.support_count,
        distinct_customer_count=fact.distinct_customer_count,
        distinct_agent_count=fact.distinct_agent_count,
        contradiction_count=fact.contradiction_count,
        has_corroboration=bool(fact.has_corroboration),
        created_from=CreatedFrom(fact.created_from),
        human_state=fact.human_state,
        steward_user_id=fact.steward_user_id,
        steward_role=fact.steward_role,
        first_observed_at=fact.first_observed_at,
        last_observed_at=fact.last_observed_at,
        last_confirmed_at=fact.last_confirmed_at,
        due_at=fact.due_at,
        expires_at=fact.expires_at,
        evidence=(
            None
            if evidence is None
            else [
                EvidenceResponse(
                    id=row.id,
                    source_type=EvidenceSourceType(row.source_type),
                    source_id=row.source_id,
                    conversation_id=row.conversation_id,
                    customer_id=row.customer_id,
                    agent_id=row.agent_id,
                    observed_at=row.observed_at,
                    weight=float(row.weight),
                )
                for row in evidence
            ]
        ),
    )


@router.get("/facts", response_model=Page[MemoryFactResponse])
async def list_facts(
    auth: Annotated[AuthContext, Depends(require_permission("memory.read"))],
    service: Annotated[MemoryQueryService, Depends(get_memory_query_service)],
    page_params: Annotated[PageParams, Depends()],
    tier: MemoryTier | None = None,
    fact_type: Annotated[str | None, Query(max_length=48)] = None,
    lifecycle_state: LifecycleState | None = None,
    retrievable_only: bool = True,
) -> Page[MemoryFactResponse]:
    """What this company remembers.

    ``retrievable_only`` defaults to true, so the ordinary reader sees what
    a consumer would actually be given — active and dormant, never
    suppressed. An administrator auditing what the platform is holding can
    turn it off, which is a different question and deserves an explicit
    ask.
    """
    items, total = await service.list_for_company(
        company_id=auth.company_id,
        tier=tier,
        fact_type=fact_type,
        lifecycle_state=lifecycle_state,
        retrievable_only=retrievable_only,
        limit=page_params.page_size,
        offset=page_params.offset,
    )
    return Page(
        items=[_fact_to_response(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.get("/facts/{fact_id}", response_model=MemoryFactResponse)
async def get_fact(
    fact_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("memory.read"))],
    service: Annotated[MemoryQueryService, Depends(get_memory_query_service)],
) -> MemoryFactResponse:
    """One fact, with its evidence.

    Evidence is included here and omitted from the list, deliberately: it
    is the answer to "why do we believe this?", which is a question asked
    of one fact at a time, and loading it for every row of a page would be
    a join nobody reads.
    """
    fact, evidence = await service.get_with_evidence(company_id=auth.company_id, fact_id=fact_id)
    return _fact_to_response(fact, evidence=evidence)


@router.post("/facts", response_model=MemoryFactResponse, status_code=status.HTTP_201_CREATED)
async def record_fact(
    payload: RecordFactRequest,
    auth: Annotated[AuthContext, Depends(require_permission("memory.manage"))],
    manager: Annotated[MemoryManager, Depends(get_memory_manager)],
) -> MemoryFactResponse:
    """Record an observation, or reinforce the one it repeats.

    Returns 201 either way. The caller asked the platform to remember
    something and it now does; whether that created a row or added the
    ninth piece of evidence to an existing one is the platform's business,
    and making the caller care would make every caller implement dedupe
    logic that belongs here.
    """
    outcome = await manager.record(
        company_id=auth.company_id,
        tier=payload.tier,
        subject=SubjectRef(subject_type=payload.subject_type, subject_id=payload.subject_id),
        fact_type=payload.fact_type,
        topic=payload.topic,
        statement=payload.statement,
        evidence=tuple(
            EvidenceRef(
                source_type=item.source_type,
                source_id=item.source_id,
                conversation_id=item.conversation_id,
                customer_id=item.customer_id,
                agent_id=item.agent_id,
                weight=item.weight,
            )
            for item in payload.evidence
        ),
        created_from=payload.created_from,
        attributes=payload.attributes,
        stratum=payload.stratum,
        created_by_user_id=auth.user_id,
        steward_user_id=payload.steward_user_id,
        steward_role=payload.steward_role,
        due_at=payload.due_at,
        expires_at=payload.expires_at,
        outcome_quality=payload.outcome_quality,
    )
    return _fact_to_response(outcome.fact)


@router.post("/facts/{fact_id}/confirm", response_model=MemoryFactResponse)
async def confirm_fact(
    fact_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("memory.manage"))],
    manager: Annotated[MemoryManager, Depends(get_memory_manager)],
) -> MemoryFactResponse:
    """A human vouches for a fact — the strongest corroboration there is,
    and the only thing that turns a recorded promise into a real one."""
    fact = await manager.confirm(company_id=auth.company_id, fact_id=fact_id, user_id=auth.user_id)
    return _fact_to_response(fact)


@router.post("/facts/{fact_id}/suppress", response_model=MemoryFactResponse)
async def suppress_fact(
    fact_id: UUID,
    payload: SuppressFactRequest,
    auth: Annotated[AuthContext, Depends(require_permission("memory.manage"))],
    manager: Annotated[MemoryManager, Depends(get_memory_manager)],
) -> MemoryFactResponse:
    """Mute a fact without deleting it.

    Not erasure. A suppressed fact has to stay, or the platform simply
    re-learns it next week — which is the opposite of what suppressing it
    meant.
    """
    fact = await manager.suppress(
        company_id=auth.company_id,
        fact_id=fact_id,
        user_id=auth.user_id,
        reason=payload.reason,
    )
    return _fact_to_response(fact)


@router.post("/facts/{fact_id}/correct", response_model=MemoryFactResponse)
async def correct_fact(
    fact_id: UUID,
    payload: CorrectFactRequest,
    auth: Annotated[AuthContext, Depends(require_permission("memory.manage"))],
    manager: Annotated[MemoryManager, Depends(get_memory_manager)],
) -> MemoryFactResponse:
    """Rewrite what a fact says, keeping its evidence.

    The observation was real and the wording was wrong — so the support
    stands and the fact gains a human confirmation.
    """
    fact = await manager.correct(
        company_id=auth.company_id,
        fact_id=fact_id,
        user_id=auth.user_id,
        statement=payload.statement,
        attributes=payload.attributes,
    )
    return _fact_to_response(fact)


@router.get("/subjects/{subject_type}/{subject_id}/facts", response_model=list[MemoryFactResponse])
async def list_subject_facts(
    subject_type: SubjectType,
    subject_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("memory.read"))],
    service: Annotated[MemoryQueryService, Depends(get_memory_query_service)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[MemoryFactResponse]:
    """Everything remembered about one subject.

    The Customer Timeline's query, and the agent sidebar's. Also exactly
    what a subject access request needs to answer *"what do you hold about
    me?"* — which is why it is the same endpoint rather than a separate
    export path that could drift from it.
    """
    items, _total = await service.list_for_subject(
        company_id=auth.company_id,
        subject=SubjectRef(subject_type=subject_type, subject_id=subject_id),
        limit=limit,
    )
    return [_fact_to_response(item) for item in items]


@router.delete(
    "/subjects/{subject_type}/{subject_id}",
    response_model=ErasureResponse,
)
async def erase_subject(
    subject_type: SubjectType,
    subject_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("memory.erase"))],
    erasure: Annotated[MemoryErasureService, Depends(get_memory_erasure_service)],
) -> ErasureResponse:
    """Erase everything memory holds about a subject. Irreversible.

    Gated on its own permission rather than ``memory.manage``, because the
    blast radius is different in kind: suppressing a fact is reversible and
    visible, and this is neither. It is also the permission a regulator
    asks who holds.

    Aggregate facts the subject *contributed to* are not deleted — "card
    declines spike at month-end" is a fact about the business — but their
    support is recomputed, so nothing survives claiming a confidence it can
    no longer justify. The response reports both numbers.
    """
    report = await erasure.erase_subject(
        company_id=auth.company_id,
        subject=SubjectRef(subject_type=subject_type, subject_id=subject_id),
    )
    return ErasureResponse(
        subject_type=subject_type,
        subject_id=subject_id,
        facts_deleted=report.facts_deleted,
        evidence_deleted=report.evidence_deleted,
        aggregate_facts_recomputed=report.aggregate_facts_recomputed,
        aggregate_facts_archived=report.aggregate_facts_archived,
        embeddings_deleted=report.embeddings_deleted,
        working_memory_cleared=False,
        erased_at=report.erased_at,
    )


@router.get("/status", response_model=MemoryStatusResponse)
async def memory_status(
    auth: Annotated[AuthContext, Depends(require_permission("memory.read"))],
    service: Annotated[MemoryQueryService, Depends(get_memory_query_service)],
) -> MemoryStatusResponse:
    """What the platform is holding, and under what retention."""
    return await service.status(company_id=auth.company_id)


# --- Conversation (working) memory ----------------------------------------


@router.get("/conversations/{conversation_id}", response_model=WorkingMemoryResponse)
async def get_working_memory(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.read"))],
    service: Annotated[ConversationMemoryService, Depends(get_conversation_memory_service)],
) -> WorkingMemoryResponse:
    """A live conversation's working memory.

    Gated on ``conversations.read`` rather than ``memory.read``: this is
    part of the conversation an agent already has open, not a company-wide
    memory store, and requiring a second permission would hide it from the
    people it exists to help.
    """
    memory = await service.get(company_id=auth.company_id, conversation_id=conversation_id)
    return _working_memory_to_response(memory)


@router.put("/conversations/{conversation_id}", response_model=WorkingMemoryResponse)
async def update_working_memory(
    conversation_id: UUID,
    payload: WorkingMemoryUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.manage"))],
    service: Annotated[ConversationMemoryService, Depends(get_conversation_memory_service)],
) -> WorkingMemoryResponse:
    """Replace the parts of working memory the caller supplies.

    An omitted field means *unchanged*, never cleared — the same rule the
    service directory's update follows, and for the same reason: building
    the new value from the submitted fields alone would silently wipe
    everything the caller did not mention.
    """
    current = await service.get(company_id=auth.company_id, conversation_id=conversation_id)
    updated = WorkingMemory(
        conversation_id=conversation_id,
        company_id=auth.company_id,
        entities=(
            current.entities
            if payload.entities is None
            else tuple(
                ResolvedEntity(
                    kind=_entity_kind(item.kind),
                    value=item.value,
                    turn=item.turn,
                    label=item.label,
                )
                for item in payload.entities
            )
        ),
        open_questions=(
            current.open_questions
            if payload.open_questions is None
            else tuple(
                OpenQuestion(
                    text=item.text,
                    asked_by=item.asked_by,
                    turn=item.turn,
                    answered=item.answered,
                )
                for item in payload.open_questions
            )
        ),
        commitments=(
            current.commitments
            if payload.commitments is None
            else tuple(
                Commitment(text=item.text, turn=item.turn, due_at=item.due_at)
                for item in payload.commitments
            )
        ),
        stated_preferences=(
            current.stated_preferences
            if payload.stated_preferences is None
            else tuple(payload.stated_preferences)
        ),
        summary=current.summary if payload.summary is None else payload.summary,
        turn_count=current.turn_count,
        schema_version=current.schema_version,
    )
    stored = await service.put(updated)
    return _working_memory_to_response(stored)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_working_memory(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.manage"))],
    service: Annotated[ConversationMemoryService, Depends(get_conversation_memory_service)],
) -> None:
    """Drop working memory now rather than waiting for its TTL."""
    await service.clear(company_id=auth.company_id, conversation_id=conversation_id)


def _entity_kind(value: str) -> EntityKind:
    try:
        return EntityKind(value)
    except ValueError:
        return EntityKind.OTHER


def _working_memory_to_response(memory: WorkingMemory) -> WorkingMemoryResponse:
    return WorkingMemoryResponse(
        conversation_id=memory.conversation_id,
        entities=[
            ResolvedEntityModel(
                kind=entity.kind.value, value=entity.value, turn=entity.turn, label=entity.label
            )
            for entity in memory.entities
        ],
        open_questions=[
            OpenQuestionModel(
                text=question.text,
                asked_by=question.asked_by,
                turn=question.turn,
                answered=question.answered,
            )
            for question in memory.open_questions
        ],
        commitments=[
            CommitmentModel(text=item.text, turn=item.turn, due_at=item.due_at)
            for item in memory.commitments
        ],
        stated_preferences=list(memory.stated_preferences),
        summary=memory.summary,
        turn_count=memory.turn_count,
        updated_at=memory.updated_at,
    )
