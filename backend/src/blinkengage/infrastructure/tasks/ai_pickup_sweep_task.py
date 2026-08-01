"""Gives AI its turn, once the humans have had theirs.

See ``docs/architecture/ai-engine.md``.

AI Autopilot is a queue **worker**, not a first responder. When a conversation
arrives on an Autopilot queue and every gate is open, ingest does not hand it
to AI — it stamps ``ai_pickup_eligible_at`` and leaves the conversation in its
queue, where an agent can see it and take it. This is what happens when
nobody does.

Until this existed, ``pickup_delay_seconds`` was configuration nothing read:
AI answered the instant a conversation arrived, so the chance it describes —
"a human picking up within a few seconds should get there first" — was never
actually offered.

**The policy is asked again, here.** Not carried forward from ingest. Thirty
seconds is long enough for a compliance officer to switch AI off, for a
service to be archived, for the conversation to be resolved; re-evaluating is
the difference between a delay and a queued instruction that fires whatever
has happened since. It is also what keeps the refusal explainable, because
the second evaluation is recorded like any other.

**Three outcomes, all of them recorded.** AI takes it; a human already has it
and AI stands down; or the policy now refuses and AI never takes it. The
marker is cleared in every case, so a conversation is settled exactly once.

Every ten seconds. The delay defaults to thirty, and a sweep on the same order
as the thing it is waiting for keeps the *effective* delay close to the
configured one — a minute-long sweep would turn a thirty-second delay into
anything up to ninety, which is a different promise than the one an
administrator typed into the box.
"""

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.ai_service import AiService
from blinkengage.application.services.autopilot_service import AutopilotTrigger
from blinkengage.application.services.company_capabilities import capabilities_for
from blinkengage.application.services.ownership_service import AI_OWNER, OwnershipService
from blinkengage.application.services.policy_recorder import RecordingPolicyEngine
from blinkengage.application.services.sla_engine import SlaEngine
from blinkengage.application.services.sla_lifecycle import SlaLifecycle
from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.execution_context import ConversationFacts, ExecutionContext
from blinkengage.domain.lifecycle import FINISHED, ConversationStatus
from blinkengage.domain.ownership import OwnershipReason
from blinkengage.domain.policies import Policy, PolicyEngine
from blinkengage.domain.routing_decisions import ai_pickup_decision, ai_stood_down_decision
from blinkengage.infrastructure.ai.factory import build_ai_provider_for_company
from blinkengage.infrastructure.autopilot_factory import build_autopilot_service
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
from blinkengage.infrastructure.repositories.ownership_repository import OwnershipRepository
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.repositories.routing_decision_repository import (
    RoutingDecisionRepository,
)
from blinkengage.infrastructure.repositories.service_directory_repository import (
    ContextBindingRepository,
    ServiceRepository,
)
from blinkengage.infrastructure.tasks.run_recorder import record_run

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

#: A ceiling per run. A burst of arrivals must not become one enormous
#: transaction; the next sweep is ten seconds away.
_BATCH = 200


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


async def _due_conversations(
    session: AsyncSession, *, now: datetime
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Everything AI has waited long enough for, soonest first.

    One indexed range scan: the column is null for every conversation AI is
    not waiting on, so they are not merely filtered out — they are not in the
    index at all.
    """
    rows = (
        (
            await session.execute(
                select(Conversation)
                .where(
                    Conversation.ai_pickup_eligible_at.is_not(None),
                    Conversation.ai_pickup_eligible_at <= now,
                    Conversation.deleted_at.is_(None),
                )
                .order_by(Conversation.ai_pickup_eligible_at)
                .limit(_BATCH)
            )
        )
        .scalars()
        .all()
    )
    return [(row.id, row.company_id) for row in rows]


async def _settle_one(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    company_id: uuid.UUID,
    now: datetime,
    settings: Settings,
) -> str:
    """Decide one conversation. Returns what happened, for the counters."""
    conversation = (
        await session.execute(select(Conversation).where(Conversation.id == conversation_id))
    ).scalar_one_or_none()
    if conversation is None or conversation.ai_pickup_eligible_at is None:
        # Settled by another sweep between the scan and now. Not an error:
        # two sweeps overlapping is the normal cost of a short interval, and
        # the second one finding nothing to do is how that stays harmless.
        return "already_settled"

    queue_id = conversation.queue_id
    queue = (
        await QueueRepository(session).get_by_id(company_id=company_id, queue_id=queue_id)
        if queue_id is not None
        else None
    )
    queue_name = queue.name if queue is not None else None
    decisions = RoutingDecisionRepository(session)

    # Whatever happens below, this conversation leaves the index. A marker
    # that survived its own decision would be swept again every ten seconds
    # forever.
    conversation.ai_pickup_eligible_at = None

    if conversation.assigned_agent_id is not None:
        # The delay worked. Recorded here rather than by the claim itself:
        # claiming a conversation is on the path an agent waits for, and
        # writing an explanation of what AI decided *not* to do is not worth
        # a millisecond of it.
        await decisions.record(
            company_id=company_id,
            conversation_id=conversation_id,
            decision=ai_stood_down_decision(queue_id=queue_id, queue_name=queue_name),
        )
        return "human_first"

    if conversation.status in FINISHED:
        # Resolved or closed while the delay ran. Nothing for AI to answer.
        return "finished"

    # The service *version the conversation is bound to*, not the service's
    # current one. A conversation's configuration is frozen when it starts,
    # so a delay edited while this one waited must not change the answer it
    # gets — the whole reason bindings are by version.
    binding = await ContextBindingRepository(session).current(conversation_id)
    service = (
        await ServiceRepository(session).context_for_version(binding.service_version_id)
        if binding is not None
        else None
    )
    if service is None:
        return "no_service"

    company = await CompanyRepository(session).get_by_id(company_id)
    policies = RecordingPolicyEngine(
        PolicyEngine(), decisions, company_id=company_id, conversation_id=conversation_id
    )
    allowed = (
        await policies.evaluate(
            Policy.AI_ENGAGEMENT,
            ExecutionContext(
                service=service,
                customer=None,
                conversation=ConversationFacts(
                    conversation_id=conversation_id,
                    company_id=company_id,
                    channel_type="",
                    started_at=conversation.created_at or now,
                    # The status as it actually is now, not "new" as ingest
                    # asked with. The activation-mode gate is about brand-new
                    # conversations, and this one has been waiting.
                    status=str(conversation.status),
                    logical_queue_id=queue_id,
                ),
                capabilities=capabilities_for(company, settings=settings),
            ),
        )
    ).allowed
    if not allowed:
        # The refusal is already recorded by the evaluation above — that is
        # what RecordingPolicyEngine is for — so there is nothing to add
        # here beyond letting the marker stay cleared.
        return "refused"

    # Hand over through AutopilotService, not by setting the flag here.
    #
    # It activates a conversation *only once a usable reply exists* — the
    # rule the SLA and agent-request triggers already follow, and it matters
    # more here than anywhere: taking a conversation out of a queue and then
    # discovering AI cannot answer it would strip it from the humans who
    # could, for nothing. If the model is unavailable or unsure, the
    # conversation simply stays where it is.
    autopilot = build_autopilot_service(session=session, settings=settings)
    events = OutboxEventPublisher(EventOutboxRepository(session))
    company_ai_config = company.ai_config if company is not None else None

    def _ai() -> AiService | None:
        provider = build_ai_provider_for_company(settings, company_ai_config)
        return AiService(provider=provider, events=events) if provider is not None else None

    outcome = await autopilot.run(
        company_id=company_id,
        conversation_id=conversation_id,
        trigger=AutopilotTrigger.QUEUE_PICKUP,
        ai_service_factory=_ai,
    )
    if not outcome.replied:
        # AI was allowed to take it and could not answer. The conversation
        # stays in its queue for a human, which is the right outcome and not
        # a failure — but it is recorded, because "AI was going to take this
        # and then didn't" is otherwise invisible.
        logger.info(
            "ai_pickup_declined",
            conversation_id=str(conversation_id),
            reason=outcome.reason,
        )
        return "not_answered"

    conversation.status = ConversationStatus.IN_PROGRESS
    # The queue clock is answered on acceptance, not on reply — the same
    # rule ingest follows when AI takes a conversation immediately.
    await SlaLifecycle(SlaEngine(session, decisions)).owner_accepted(
        conversation_id=conversation_id, now=now
    )
    # AI is an owner, not an absence. Without this the moment AI later hands
    # back would have nothing to be a transition *from*.
    await OwnershipService(OwnershipRepository(session)).transfer(
        conversation_id=conversation_id,
        company_id=company_id,
        to=AI_OWNER,
        reason=OwnershipReason.AI_ENGAGEMENT,
        now=now,
    )
    await decisions.record(
        company_id=company_id,
        conversation_id=conversation_id,
        decision=ai_pickup_decision(
            queue_id=queue_id,
            queue_name=queue_name,
            delay_seconds=service.ai.pickup_delay_seconds,
        ),
    )
    return "engaged"


async def _sweep_async() -> int:
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    try:
        async with record_run(
            session_factory, task_name="blinkengage.ai.pickup_waiting_conversations"
        ) as report:
            now = datetime.now(UTC)
            async with session_scope(session_factory) as session:
                due = await _due_conversations(session, now=now)

            outcomes: dict[str, int] = {}
            for conversation_id, company_id in due:
                # One transaction each. A conversation that cannot be
                # settled fails alone rather than holding up every other
                # company's.
                try:
                    async with session_scope(session_factory) as session:
                        outcome = await _settle_one(
                            session,
                            conversation_id=conversation_id,
                            company_id=company_id,
                            now=now,
                            settings=settings,
                        )
                    outcomes[outcome] = outcomes.get(outcome, 0) + 1
                    logger.info(
                        "ai_pickup_settled",
                        conversation_id=str(conversation_id),
                        outcome=outcome,
                    )
                except Exception:  # noqa: BLE001
                    report.record_failure()
                    logger.exception("ai_pickup_not_settled", conversation_id=str(conversation_id))

            report.count("conversations_due", len(due))
            report.count("ai_engaged", outcomes.get("engaged", 0))
            report.count("ai_could_not_answer", outcomes.get("not_answered", 0))
            report.count("human_arrived_first", outcomes.get("human_first", 0))
            return outcomes.get("engaged", 0)
    finally:
        # Required, not tidiness — see ``events/relay.py``.
        if _engine is not None:
            await _engine.dispose()


@celery_app.task(name="blinkengage.ai.pickup_waiting_conversations")  # type: ignore[misc]
def pickup_waiting_conversations() -> int:
    return asyncio.run(_sweep_async())


__all__ = ["pickup_waiting_conversations"]
