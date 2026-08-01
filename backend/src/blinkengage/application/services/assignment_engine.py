"""Skill/load-based agent assignment. See
``docs/architecture/queues-routing.md`` decision #5 for why this is a
small strategy interface rather than one branching function.

**Decides and describes; never writes.** ``select_agent`` returns an
``AgentAssignment`` — the chosen agent *and* which strategy ran, how many
people were considered, and why each of the others was passed over.
"Why isn't this with Ada?" is answerable only if Ada was recorded at the
moment she was skipped; a bare ``UUID | None`` threw that away. The
caller (``conversation_ingest_consumer``) persists it, so this engine
stays testable against a session and no decision table.
"""

from abc import ABC, abstractmethod
from typing import ClassVar
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.lifecycle import ACTIVE, AWAITING_OTHERS
from blinkengage.domain.routing_decisions import (
    AgentAssignment,
    CandidateRejection,
    RejectedCandidate,
    RoutingDecisionReason,
)
from blinkengage.infrastructure.database.models.agent import Agent, AgentStatus
from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
)
from blinkengage.infrastructure.database.models.queue import Queue, QueueAssignmentStrategy
from blinkengage.infrastructure.database.models.user import User
from blinkengage.infrastructure.repositories.agent_skill_repository import AgentSkillRepository
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository

#: What counts against an agent's workload. From the lifecycle's own sets,
#: so a new status cannot silently stop counting.
_OPEN_STATUSES = tuple(ACTIVE | AWAITING_OTHERS)


class AssignmentStrategy(ABC):
    #: What to report when this strategy selects nobody despite having
    #: eligible candidates. A class attribute rather than a check on the
    #: queue's configured enum inside ``select_agent`` so a future
    #: strategy that declines for its own reasons declares that reason
    #: itself — the same open-for-extension shape decision #5 committed
    #: to, extended to the explanation rather than only to the choice.
    no_selection_reason: ClassVar[RoutingDecisionReason] = RoutingDecisionReason.STRATEGY_DECLINED

    @abstractmethod
    async def select(self, *, candidate_ids: list[UUID], session: AsyncSession) -> UUID | None: ...


class RoundRobinStrategy(AssignmentStrategy):
    """Picks whoever among the candidates has been assigned the fewest
    conversations ever — approximates "least recently assigned" without a
    separate rotation cursor, and cycles fairly over time."""

    async def select(self, *, candidate_ids: list[UUID], session: AsyncSession) -> UUID | None:
        if not candidate_ids:
            return None
        result = await session.execute(
            select(Conversation.assigned_agent_id, func.count())
            .where(Conversation.assigned_agent_id.in_(candidate_ids))
            .group_by(Conversation.assigned_agent_id)
        )
        counts: dict[UUID, int] = {
            agent_id: count for agent_id, count in result.all() if agent_id is not None
        }
        return min(candidate_ids, key=lambda agent_id: counts.get(agent_id, 0))


class LeastLoadStrategy(AssignmentStrategy):
    """Picks whoever currently has the fewest open/pending conversations
    assigned, company-wide (not just this queue) — the point of load
    balancing is total workload, not a per-queue count."""

    async def select(self, *, candidate_ids: list[UUID], session: AsyncSession) -> UUID | None:
        if not candidate_ids:
            return None
        result = await session.execute(
            select(Conversation.assigned_agent_id, func.count())
            .where(
                Conversation.assigned_agent_id.in_(candidate_ids),
                Conversation.status.in_(_OPEN_STATUSES),
                Conversation.deleted_at.is_(None),
            )
            .group_by(Conversation.assigned_agent_id)
        )
        counts: dict[UUID, int] = {
            agent_id: count for agent_id, count in result.all() if agent_id is not None
        }
        return min(candidate_ids, key=lambda agent_id: counts.get(agent_id, 0))


class ManualPickupStrategy(AssignmentStrategy):
    """Deliberately never auto-assigns — a queue configured for manual
    pickup exists precisely so a conversation waits, visible to every
    eligible agent, until one claims it via ConversationService.pick().
    See queues-routing.md decision #6."""

    #: Not the generic "the strategy declined": this queue was configured
    #: to wait, and an operator asking "why is nothing being assigned"
    #: needs to be told that rather than sent looking for a fault.
    no_selection_reason: ClassVar[RoutingDecisionReason] = (
        RoutingDecisionReason.QUEUE_IS_MANUAL_PICKUP
    )

    async def select(self, *, candidate_ids: list[UUID], session: AsyncSession) -> UUID | None:
        return None


_STRATEGIES: dict[QueueAssignmentStrategy, AssignmentStrategy] = {
    QueueAssignmentStrategy.ROUND_ROBIN: RoundRobinStrategy(),
    QueueAssignmentStrategy.LEAST_LOAD: LeastLoadStrategy(),
    QueueAssignmentStrategy.MANUAL: ManualPickupStrategy(),
}


#: Which statuses exclude an agent from auto-assignment, and how each
#: exclusion is *explained*. Two codes rather than one "unavailable":
#: offline is a connection state the gateway observed, busy is a choice
#: the agent made (queues-routing.md decision #10), and an operator
#: reading "busy" knows to ask a person rather than check the network.
_UNAVAILABILITY_REASON: dict[AgentStatus, CandidateRejection] = {
    AgentStatus.OFFLINE: CandidateRejection.AGENT_OFFLINE,
    AgentStatus.BUSY: CandidateRejection.AGENT_BUSY,
}

#: Derived from the map above rather than listed a second time, so a
#: status can never become ineligible without also declaring what a
#: decision should say about it — the two drifting apart would raise a
#: ``KeyError`` mid-ingest, on the least convenient path in the system.
_INELIGIBLE_FOR_AUTO_ASSIGNMENT = tuple(_UNAVAILABILITY_REASON)


async def filter_by_required_skills(
    *,
    candidate_ids: list[UUID],
    queue_id: UUID,
    company_id: UUID,
    queues: QueueRepository,
    agent_skills: AgentSkillRepository,
) -> list[UUID]:
    """Narrows ``candidate_ids`` to agents satisfying a queue's required
    skills (any-of match) — zero required skills means no restriction.
    Shared by ``AssignmentEngine.select_agent`` and
    ``ConversationService.pick`` so the eligibility rule can't drift
    between auto-assignment and manual pickup."""
    if not candidate_ids:
        return candidate_ids
    required_skill_ids = await queues.required_skill_ids(queue_id=queue_id)
    if not required_skill_ids:
        return candidate_ids
    eligible_agent_ids = await agent_skills.agents_with_any_skill(
        company_id=company_id, skill_ids=required_skill_ids
    )
    return [a for a in candidate_ids if a in eligible_agent_ids]


class AssignmentEngine:
    def __init__(self, *, queues: QueueRepository, agent_skills: AgentSkillRepository) -> None:
        self._queues = queues
        self._agent_skills = agent_skills

    async def select_agent(self, *, queue: Queue, session: AsyncSession) -> AgentAssignment:
        """Who gets this conversation, and who else was in the running.

        The selection itself is unchanged: eligible means active, not
        offline, not busy; narrowed by the queue's required skills; then
        the queue's configured strategy chooses. What is new is that every
        agent excluded along the way is *named* in the result, because
        "why isn't this with Ada?" cannot be answered from the winner
        alone.

        Availability is filtered in Python rather than by a
        ``status NOT IN`` predicate, which is what makes that possible:
        an agent the query never returned is an agent no decision can
        mention. The roster is one company's agents joined to their user
        row for a display name — the selective predicate was always
        ``company_id``, so dropping the status filter costs nothing an
        index was providing.
        """
        strategy = _STRATEGIES[queue.assignment_strategy]
        roster = await session.execute(
            select(Agent.id, Agent.status, User.full_name)
            .join(User, User.id == Agent.user_id)
            .where(Agent.company_id == queue.company_id, Agent.deleted_at.is_(None))
        )
        names: dict[UUID, str] = {}
        candidate_ids: list[UUID] = []
        rejected: list[RejectedCandidate] = []
        considered = 0
        for agent_id, status, full_name in roster.all():
            considered += 1
            names[agent_id] = full_name
            if status in _INELIGIBLE_FOR_AUTO_ASSIGNMENT:
                rejected.append(
                    RejectedCandidate(
                        agent_id=agent_id,
                        agent_name=full_name,
                        reason=_UNAVAILABILITY_REASON[status],
                    )
                )
            else:
                candidate_ids.append(agent_id)

        def _outcome(selected: UUID | None, reason: RoutingDecisionReason) -> AgentAssignment:
            return AgentAssignment(
                agent_id=selected,
                agent_name=None if selected is None else names.get(selected),
                strategy=queue.assignment_strategy.value,
                reason=reason,
                candidates_considered=considered,
                rejected=tuple(rejected),
            )

        if not candidate_ids:
            return _outcome(None, RoutingDecisionReason.NO_AGENT_AVAILABLE)

        eligible_ids = await filter_by_required_skills(
            candidate_ids=candidate_ids,
            queue_id=queue.id,
            company_id=queue.company_id,
            queues=self._queues,
            agent_skills=self._agent_skills,
        )
        eligible = set(eligible_ids)
        rejected.extend(
            RejectedCandidate(
                agent_id=agent_id,
                agent_name=names.get(agent_id),
                reason=CandidateRejection.MISSING_REQUIRED_SKILL,
            )
            for agent_id in candidate_ids
            if agent_id not in eligible
        )
        if not eligible_ids:
            return _outcome(None, RoutingDecisionReason.NO_AGENT_WITH_REQUIRED_SKILL)

        selected = await strategy.select(candidate_ids=eligible_ids, session=session)
        rejected.extend(
            RejectedCandidate(
                agent_id=agent_id,
                agent_name=names.get(agent_id),
                reason=CandidateRejection.NOT_CHOSEN_BY_STRATEGY,
            )
            for agent_id in eligible_ids
            if agent_id != selected
        )
        if selected is None:
            return _outcome(None, strategy.no_selection_reason)
        # One eligible agent is not a strategy outcome: round-robin and
        # least-load would both have picked the same person, and telling
        # an operator "least-load chose them" when there was no choice to
        # make misrepresents what happened.
        return _outcome(
            selected,
            RoutingDecisionReason.ONLY_CANDIDATE
            if len(eligible_ids) == 1
            else RoutingDecisionReason.STRATEGY_SELECTED,
        )
