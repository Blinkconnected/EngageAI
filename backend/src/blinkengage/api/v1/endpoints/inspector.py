"""The Conversation Black Box — ``GET /api/v1/conversations/{id}/inspector``.

Read-only, and one call. A support engineer with a customer on the phone
should not assemble the answer from six endpoints in an order that tells them
nothing.

Gated on ``conversations.read``, the permission an agent already needs to open
the conversation itself. Deliberately not a new permission: this screen shows
*why* the platform did what it did to a conversation the caller can already
see in full, and inventing a second gate would put the explanation further out
of reach than the thing being explained. The advanced view carries policy
sources and rule internals, which is administrator-grade detail — the console
hides it behind a toggle rather than the API refusing it, because an agent who
can read a conversation can already see everything it is derived from.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from blinkengage.api.deps import (
    get_conversation_inspector,
    get_conversation_service,
    require_permission,
)
from blinkengage.api.schemas.inspector import (
    AiResponse,
    ClockResponse,
    ConversationInspectorResponse,
    DecisionResponse,
    OwnershipSpanResponse,
    PolicyResponse,
    SummaryResponse,
    TechnicalResponse,
    TimelineEntryResponse,
)
from blinkengage.application.services.conversation_inspector import (
    ConversationInspection,
    ConversationInspectorService,
)
from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.core.auth_context import AuthContext
from blinkengage.infrastructure.database.models.routing_decision import RoutingDecisionRecord

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _decision(row: RoutingDecisionRecord) -> DecisionResponse:
    return DecisionResponse(
        id=row.id,
        at=row.decided_at,
        kind=row.kind.value,
        outcome=row.outcome.value,
        reason=row.reason.value,
        sentence=row.sentence,
        selected_queue_id=row.selected_queue_id,
        selected_queue_name=row.selected_queue_name,
        selected_agent_id=row.selected_agent_id,
        selected_agent_name=row.selected_agent_name,
        selected_service_id=row.selected_service_id,
        selected_service_name=row.selected_service_name,
        service_version=row.service_version,
        policy=row.policy,
        policy_reason=row.policy_reason,
        policy_source=row.policy_source,
        policy_text=row.policy_text,
        sla_timer=row.sla_timer,
        sla_pause_reason=row.sla_pause_reason,
        matched_rule_id=row.matched_rule_id,
        matched_rule_name=row.matched_rule_name,
        matched_rule_priority=row.matched_rule_priority,
        rules_evaluated=row.rules_evaluated,
        strategy=row.strategy,
        candidates_considered=row.candidates_considered,
        rejected_candidates=list(row.rejected_candidates or []),
        rejections_omitted=row.rejections_omitted,
        ai_pickup_delay_seconds=row.ai_pickup_delay_seconds,
        resolution_stages=list(row.resolution_stages or []),
        details=dict(row.details or {}),
    )


def _to_response(inspection: ConversationInspection) -> ConversationInspectorResponse:
    summary = inspection.summary
    ai = inspection.ai
    technical = inspection.technical
    return ConversationInspectorResponse(
        summary=SummaryResponse(
            status=summary.status,
            service_name=summary.service_name,
            service_version=summary.service_version,
            queue_id=summary.queue_id,
            queue_name=summary.queue_name,
            runtime_queue_id=summary.runtime_queue_id,
            runtime_queues_in_use=summary.runtime_queues_in_use,
            owner_kind=summary.owner_kind,
            owner_id=summary.owner_id,
            owner_name=summary.owner_name,
            owner_label=summary.owner_label,
            responsibility=summary.responsibility,
            sla_health=summary.sla_health,
            ai_state=summary.ai_state,
            age_seconds=summary.age_seconds,
            created_at=summary.created_at,
            customer_name=summary.customer_name,
            assigned_agent_name=summary.assigned_agent_name,
        ),
        timeline=[
            TimelineEntryResponse(
                at=entry.at,
                stream=entry.stream,
                actor=entry.actor,
                actor_kind=entry.actor_kind,
                title=entry.title,
                detail=entry.detail,
                why=list(entry.why),
                impact=list(entry.impact),
                facts=[list(fact) for fact in entry.facts],
                decision_id=entry.decision_id,
                code=entry.code,
                severity=entry.severity.value,
            )
            for entry in inspection.timeline
        ],
        decisions=[_decision(row) for row in inspection.decisions],
        ownership=[
            OwnershipSpanResponse(
                at=span.at,
                owner_kind=span.owner_kind,
                owner_id=span.owner_id,
                owner_name=span.owner_name,
                owner_label=span.owner_label,
                responsibility=span.responsibility,
                previous_kind=span.previous_kind,
                previous_label=span.previous_label,
                reason=span.reason,
                reason_text=span.reason_text,
                note=span.note,
                held_seconds=span.held_seconds,
            )
            for span in inspection.ownership
        ],
        clocks=[
            ClockResponse(
                timer=clock.timer,
                question=clock.question,
                state=clock.state,
                health=clock.health,
                target_minutes=clock.target_minutes,
                counted_seconds=clock.counted_seconds,
                remaining_seconds=clock.remaining_seconds,
                pause_reason=clock.pause_reason,
                pause_text=clock.pause_text,
                pause_note=clock.pause_note,
                responsible=clock.responsible,
                settled_at=clock.settled_at,
            )
            for clock in inspection.clocks
        ],
        sla_health=inspection.sla_health,
        ai=AiResponse(
            engaged=ai.engaged,
            state=ai.state,
            pickup_delay_seconds=ai.pickup_delay_seconds,
            pickup_eligible_at=ai.pickup_eligible_at,
            confidence_threshold=ai.confidence_threshold,
            threshold_source=ai.threshold_source,
            reasons=list(ai.reasons),
            release_reason=ai.release_reason,
            resume_eligible=ai.resume_eligible,
            resume_blocked_because=ai.resume_blocked_because,
        ),
        policies=[
            PolicyResponse(
                at=policy.at,
                policy=policy.policy,
                effect=policy.effect,
                reason=policy.reason,
                reason_text=policy.reason_text,
                source=policy.source,
                sentence=policy.sentence,
            )
            for policy in inspection.policies
        ],
        technical=TechnicalResponse(
            conversation_id=technical.conversation_id,
            company_id=technical.company_id,
            customer_id=technical.customer_id,
            channel_type=technical.channel_type,
            external_thread_id=technical.external_thread_id,
            service_id=technical.service_id,
            service_version_id=technical.service_version_id,
            service_version=technical.service_version,
            customer_context_version_id=technical.customer_context_version_id,
            context_bound_at=technical.context_bound_at,
            context_binding_reason=technical.context_binding_reason,
            unversioned=list(technical.unversioned),
        ),
        generated_at=inspection.generated_at,
        gaps=list(inspection.gaps),
    )


@router.get("/{conversation_id}/inspector", response_model=ConversationInspectorResponse)
async def inspect_conversation(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.read"))],
    conversations: Annotated[ConversationService, Depends(get_conversation_service)],
    inspector: Annotated[ConversationInspectorService, Depends(get_conversation_inspector)],
) -> ConversationInspectorResponse:
    """Everything that happened to this conversation, from the first second.

    The conversation is fetched through ``ConversationService.get``, which
    scopes by company — so this cannot be used to read another tenant's
    history by guessing an id.
    """
    conversation = await conversations.get(
        company_id=auth.company_id, conversation_id=conversation_id
    )
    return _to_response(await inspector.inspect(conversation=conversation))
