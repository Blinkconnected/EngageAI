"""The SLA Inspector — ``/api/v1/conversations/{id}/sla``.

Answers the six questions, for one conversation: why is each clock running,
why is it paused, why was it breached, why was it resumed, why did the deadline
change, and what needs doing now.

Read-only. A clock moves as a *consequence* of something — an owner accepting
it, a reply going out, a status changing — and an endpoint that set one
directly would let somebody change a deadline without the thing that justified
it ever happening.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from blinkengage.api.deps import (
    get_conversation_service,
    get_routing_decision_repository,
    get_sla_engine,
    require_permission,
)
from blinkengage.api.schemas.sla import (
    ClockResponse,
    ConversationSlaResponse,
    SlaEventResponse,
)
from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.application.services.sla_engine import SlaEngine
from blinkengage.core.auth_context import AuthContext
from blinkengage.domain.sla import PAUSE_TEXT, QUESTION, Clock, SlaState
from blinkengage.infrastructure.database.models.routing_decision import RoutingDecisionRecord
from blinkengage.infrastructure.repositories.routing_decision_repository import (
    RoutingDecisionRepository,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _explain(clock: Clock, *, now: datetime) -> str:
    """Why this clock is where it is, in one sentence.

    The thing the Inspector shows before anybody expands anything. Built
    from the structured fields, so two conversations paused for the same
    reason read alike and group together.
    """
    question = QUESTION[clock.timer]
    if clock.state is SlaState.NOT_MEASURED or clock.target_minutes is None:
        return f"Not measured for this service. ({question})"
    if clock.state is SlaState.PAUSED:
        why = PAUSE_TEXT[clock.pause_reason] if clock.pause_reason else "no reason recorded"
        return f"Paused — {why}. The deadline moves out while it is paused."
    if clock.state is SlaState.BREACHED:
        return "The target was missed. A breach is not reversed by a later reply."
    if clock.state is SlaState.ACHIEVED:
        return "The target was met."
    if clock.state is SlaState.STOPPED:
        return "The conversation ended before this clock could be met or missed."
    remaining = clock.remaining(now=now)
    if remaining is not None and remaining.total_seconds() < 0:
        return "Running, and already past its target."
    minutes = 0 if remaining is None else int(remaining.total_seconds() // 60)
    return f"Running, {minutes} minutes left. ({question})"


def _clock(clock: Clock, *, now: datetime, note: str | None) -> ClockResponse:
    remaining = clock.remaining(now=now)
    return ClockResponse(
        timer=clock.timer.value,
        question=QUESTION[clock.timer],
        state=clock.state.value,
        target_minutes=clock.target_minutes,
        elapsed_minutes=round(clock.counted(now=now).total_seconds() / 60, 2),
        remaining_minutes=(
            None if remaining is None else round(remaining.total_seconds() / 60, 2)
        ),
        deadline=clock.deadline(now=now),
        pause_reason=None if clock.pause_reason is None else clock.pause_reason.value,
        pause_text=None if clock.pause_reason is None else PAUSE_TEXT[clock.pause_reason],
        pause_note=note,
        started_at=None,
        settled_at=clock.settled_at,
        urgency=clock.urgency(now=now).value,
        explanation=_explain(clock, now=now),
    )


def _event(row: RoutingDecisionRecord) -> SlaEventResponse:
    detail = row.sla_detail or {}
    deadline = detail.get("deadline")
    return SlaEventResponse(
        kind=row.kind.value,
        timer=row.sla_timer or "",
        at=row.decided_at,
        sentence=row.sentence,
        pause_reason=row.sla_pause_reason,
        deadline=None if deadline is None else datetime.fromisoformat(deadline),
        elapsed_minutes=detail.get("elapsed_minutes"),
        target_minutes=detail.get("target_minutes"),
    )


@router.get("/{conversation_id}/sla", response_model=ConversationSlaResponse)
async def read_sla(
    conversation_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("conversations.read"))],
    conversations: Annotated[ConversationService, Depends(get_conversation_service)],
    engine: Annotated[SlaEngine, Depends(get_sla_engine)],
    decisions: Annotated[RoutingDecisionRepository, Depends(get_routing_decision_repository)],
) -> ConversationSlaResponse:
    """Every clock, what it means, and how it got there.

    The conversation is fetched first purely to enforce tenancy — the SLA
    rows carry a ``company_id`` but reading them directly would make this
    endpoint the one place that checked it for itself.
    """
    await conversations.get(company_id=auth.company_id, conversation_id=conversation_id)

    now = datetime.now(UTC)
    sla = await engine.read(conversation_id, now=now)
    notes = await engine.pause_notes(conversation_id)
    timeline = await decisions.sla_events(conversation_id=conversation_id)

    return ConversationSlaResponse(
        urgency=sla.urgency.value,
        clocks=[
            _clock(clock, now=now, note=notes.get(clock.timer)) for clock in sla.clocks
        ],
        timeline=[_event(row) for row in timeline],
    )


__all__ = ["router"]
