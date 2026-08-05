"""Turns finished conversations into observations.

Stage 3, phase 1. See
``docs/architecture/learning-platform-charter.md``.

Binds ``conversation.resolved`` and ``conversation.closed`` — the two
events that mean *this piece of work is over*. It does **not** bind
``message.persisted``: an observation is about a finished unit, and
assembling one per message would produce a row per turn that the settle
window then has to reconcile.

**The gate comes first.** ``Policy.KNOWLEDGE_LEARNING`` is evaluated
before any content is read, and a refusal writes an *excluded*
observation rather than nothing: "the platform saw this and chose not to
learn from it" is a different fact from "the platform never saw it", and
only the first can be audited.

**Learning never blocks anything.** This consumer reads conversations and
writes only Learning's own tables. If it is down, every other context
continues unaffected — which is charter §5, and is why it is a separate
process rather than a hook in the conversation path.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import orjson
from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.company_capabilities import capabilities_for
from blinkengage.application.services.learning_observation_service import (
    LearningObservationService,
    TurnInput,
)
from blinkengage.application.services.policy_recorder import RecordingPolicyEngine
from blinkengage.application.services.service_context_resolver import (
    ServiceContextResolver,
)
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.conversation_outcome import OutcomeInputs, ResolvedBy
from blinkengage.domain.execution_context import ConversationFacts, ExecutionContext
from blinkengage.domain.learning_observation import (
    ContentRefKind,
    ObservationSource,
    Participants,
    SourceKind,
)
from blinkengage.domain.policies import Policy, PolicyEngine
from blinkengage.infrastructure.database.models.channel_config import ChannelConfig
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.message import Message, MessageDirection
from blinkengage.infrastructure.database.models.reporting import CsatResponse
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.rabbitmq import run_consumer
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.learning_repository import (
    LearningObservationRepository,
)
from blinkengage.infrastructure.repositories.routing_decision_repository import (
    RoutingDecisionRepository,
)
from blinkengage.infrastructure.repositories.service_directory_repository import (
    ContextBindingRepository,
    ServiceRepository,
)

logger = get_logger(__name__)

QUEUE_NAME = "learning-observation"
ROUTING_KEYS = ["conversation.resolved", "conversation.closed"]

#: A ceiling on how much of one conversation is read. A thread with
#: thousands of turns is real, and loading all of them to extract a
#: handful of topic tokens is not worth the memory — the newest turns
#: carry the outcome, which is what phase 1 is about.
_MAX_TURNS = 500

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


async def handle_event(event: dict[str, Any], session: AsyncSession, settings: Settings) -> str:
    """Assemble one observation. Returns an outcome label for the logs."""
    conversation_id = UUID(str(event["aggregate_id"]))
    company_id = UUID(str(event["company_id"]))

    conversation = (
        await session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.company_id == company_id,
            )
        )
    ).scalar_one_or_none()
    if conversation is None:
        # Deleted between the event and now. Not an error; nothing to
        # observe and nothing to record about it.
        return "vanished"

    # The channel lives on the config, not on the conversation. Read here
    # once and passed down: **nothing in Learning branches on it** (see
    # ``domain/learning_observation``) — it is recorded for reporting and
    # handed to the Policy Engine, which is allowed to care.
    channel_type = (
        await session.execute(
            select(ChannelConfig.channel_type).where(
                ChannelConfig.id == conversation.channel_config_id
            )
        )
    ).scalar_one_or_none()

    policy_allows = await _may_learn(
        session,
        conversation=conversation,
        company_id=company_id,
        settings=settings,
        channel_type=channel_type,
    )

    turns: tuple[TurnInput, ...] = ()
    if policy_allows:
        # Content is read only after the gate opens. A company that
        # forbids learning has its conversations left unread, not read
        # and then discarded.
        turns = await _turns_for(session, conversation_id=conversation_id)

    csat = (
        await session.execute(
            select(CsatResponse).where(CsatResponse.conversation_id == conversation_id)
        )
    ).scalar_one_or_none()

    service = LearningObservationService(observations=LearningObservationRepository(session))
    result = await service.assemble(
        company_id=company_id,
        source=ObservationSource(
            kind=SourceKind.CONVERSATION,
            source_id=conversation_id,
            occurred_at=conversation.created_at or datetime.now(UTC),
            channel=channel_type,
        ),
        participants=Participants(
            customer_id=conversation.customer_id,
            agent_ids=((conversation.assigned_agent_id,) if conversation.assigned_agent_id else ()),
            ai_involved=any(turn.is_ai_generated or turn.is_ai_assisted for turn in turns),
        ),
        turns=turns,
        outcome_inputs=_outcome_inputs(conversation, turns=turns, csat=csat),
        policy_allows=policy_allows,
    )

    logger.info(
        "learning_observation_assembled",
        conversation_id=str(conversation_id),
        company_id=str(company_id),
        state=result.state.value,
        created=result.created,
    )
    return result.state.value


async def _may_learn(
    session: AsyncSession,
    *,
    conversation: Conversation,
    company_id: UUID,
    settings: Settings,
    channel_type: str | None,
) -> bool:
    """The kill switch, asked through the Policy Engine.

    Recorded like every other policy evaluation, so "why did Learning
    ignore this company?" is answerable from the decision log rather than
    from worker output nobody keeps.
    """
    company = await CompanyRepository(session).get_by_id(company_id)
    service = await ServiceContextResolver(
        bindings=ContextBindingRepository(session), services=ServiceRepository(session)
    ).for_conversation(conversation.id)

    engine = RecordingPolicyEngine(
        PolicyEngine(),
        RoutingDecisionRepository(session),
        company_id=company_id,
        conversation_id=conversation.id,
    )
    decision = await engine.evaluate(
        Policy.KNOWLEDGE_LEARNING,
        ExecutionContext(
            service=service,
            customer=None,
            conversation=ConversationFacts(
                conversation_id=conversation.id,
                company_id=company_id,
                channel_type=channel_type or "",
                started_at=conversation.created_at or datetime.now(UTC),
                status=str(conversation.status),
                logical_queue_id=conversation.queue_id,
            ),
            capabilities=capabilities_for(company, settings=settings),
        ),
    )
    return decision.allowed


async def _turns_for(session: AsyncSession, *, conversation_id: UUID) -> tuple[TurnInput, ...]:
    """The conversation's turns, with their provenance.

    ``message_metadata`` already carries ``is_ai_generated`` and
    ``is_ai_assisted`` — stamped by ``ConversationService`` and read by
    billing. Learning reads the same flags rather than inferring
    authorship, which is what makes the anti-feedback-loop defence a fact
    about the data rather than a guess.
    """
    rows = (
        (
            await session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at)
                .limit(_MAX_TURNS)
            )
        )
        .scalars()
        .all()
    )

    turns: list[TurnInput] = []
    for ordinal, message in enumerate(rows):
        metadata = message.message_metadata or {}
        turns.append(
            TurnInput(
                ref_id=message.id,
                ordinal=ordinal,
                inbound=message.direction == MessageDirection.INBOUND,
                text=message.body or "",
                is_ai_generated=metadata.get("is_ai_generated") is True,
                is_ai_assisted=metadata.get("is_ai_assisted") is True,
                is_system_generated=metadata.get("is_system_generated") is True,
                kind=ContentRefKind.MESSAGE,
            )
        )
    return tuple(turns)


def _outcome_inputs(
    conversation: Conversation,
    *,
    turns: tuple[TurnInput, ...],
    csat: CsatResponse | None,
) -> OutcomeInputs:
    """Everything the single outcome resolver needs.

    ``resolved_by`` is the one that matters. A workflow auto-close reads
    as ``resolved`` on the status column, and anything learning from
    outcomes would conclude that whatever preceded it worked — a feedback
    loop the AI-provenance filter does not touch, because a workflow is
    not AI. Phase 1 can distinguish the AI case from the assignment and
    the human case from an assigned agent; a workflow close is not yet
    separable from a human one on this data, so it answers ``UNKNOWN``
    rather than guessing ``HUMAN``, and ``UNKNOWN`` is not attributable.
    """
    ai_closed = bool(turns) and turns[-1].is_ai_generated
    if ai_closed:
        resolved_by = ResolvedBy.AI
    elif conversation.assigned_agent_id is not None:
        resolved_by = ResolvedBy.HUMAN
    else:
        resolved_by = ResolvedBy.UNKNOWN

    return OutcomeInputs(
        status=str(conversation.status),
        started_at=conversation.created_at or datetime.now(UTC),
        ended_at=conversation.updated_at,
        now=datetime.now(UTC),
        resolved_by=resolved_by,
        inbound_message_count=sum(1 for turn in turns if turn.inbound),
        outbound_message_count=sum(1 for turn in turns if not turn.inbound),
        escalated=False,
        transferred_count=0,
        csat_score=csat.rating if csat is not None else None,
    )


async def main() -> None:
    settings = get_settings()
    session_factory = _get_session_factory(settings)

    async def _handler(message: AbstractIncomingMessage) -> None:
        event = orjson.loads(message.body)
        async with session_scope(session_factory) as session:
            await handle_event(event, session, settings)

    await run_consumer(settings, queue_name=QUEUE_NAME, routing_keys=ROUTING_KEYS, handler=_handler)


if __name__ == "__main__":
    asyncio.run(main())
