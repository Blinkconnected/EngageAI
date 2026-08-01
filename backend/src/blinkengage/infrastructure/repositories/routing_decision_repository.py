"""Persistence for routing decisions.

See ``docs/architecture/queues-routing.md``.

Exposes ``record`` and reads — deliberately **no update and no delete**. A
routing decision is a historical fact: if the platform decided wrongly,
the correction is another decision, never an amendment of the first. A
repository that offers no way to amend makes that structural rather than a
convention, and on PostgreSQL a trigger enforces the same rule at the
database, so it also holds against a ``psql`` session.

Translation from the framework-free ``domain.routing_decisions
.RoutingDecision`` into a row happens here and nowhere else — the engines
that produce decisions never learn what a column is, which is what keeps
them unit-testable without a database.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.routing_decisions import RoutingDecision
from blinkengage.infrastructure.database.models.routing_decision import RoutingDecisionRecord


class RoutingDecisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def sla_events(self, *, conversation_id: uuid.UUID) -> list[RoutingDecisionRecord]:
        """Every SLA movement on this conversation, oldest first.

        Filtered on ``sla_timer`` rather than on the kinds, so a kind added
        later is included without this query having to be remembered.
        """
        result = await self._session.execute(
            select(RoutingDecisionRecord)
            .where(
                RoutingDecisionRecord.conversation_id == conversation_id,
                RoutingDecisionRecord.sla_timer.is_not(None),
            )
            .order_by(RoutingDecisionRecord.decided_at)
        )
        return list(result.scalars().all())

    async def record(
        self, *, company_id: uuid.UUID, conversation_id: uuid.UUID, decision: RoutingDecision
    ) -> RoutingDecisionRecord:
        """Writes one decision, flattening its evidence into the row.

        The rule's identity is copied field by field rather than stored as
        a reference: ``matched_rule_name`` is the rendering frozen at the
        instant it matched, and the raw ``conditions`` go into ``details``
        so a console can still filter on the machine-readable form. Editing
        or deleting the rule afterwards changes neither.

        ``sentence`` is rendered here, once, and stored — so an export
        produced years from now reads the way it read the day the decision
        was made, even if the wording in ``domain/routing_decisions.py``
        has since been improved.

        ``decided_at`` comes from the application clock rather than the
        column's server default: several decisions about one conversation
        are written inside a single transaction, and a database ``now()``
        is transaction-start time, so they would all claim the same
        instant and could not be put back in order. See the column's own
        note.
        """
        rule = decision.matched_rule
        record = RoutingDecisionRecord(
            company_id=company_id,
            conversation_id=conversation_id,
            decided_at=datetime.now(UTC),
            kind=decision.kind,
            outcome=decision.outcome,
            reason=decision.reason,
            selected_queue_id=decision.selected_queue_id,
            selected_queue_name=decision.selected_queue_name,
            selected_agent_id=decision.selected_agent_id,
            selected_agent_name=decision.selected_agent_name,
            selected_service_id=decision.selected_service_id,
            selected_service_name=decision.selected_service_name,
            service_version=decision.service_version,
            sla_timer=None if decision.sla is None else decision.sla.timer,
            sla_pause_reason=None if decision.sla is None else decision.sla.pause_reason,
            sla_detail=(
                {}
                if decision.sla is None
                else {
                    "question": decision.sla.question,
                    "pause_text": decision.sla.pause_text,
                    "deadline": (
                        None if decision.sla.deadline is None else decision.sla.deadline.isoformat()
                    ),
                    "elapsed_minutes": decision.sla.elapsed_minutes,
                    "target_minutes": decision.sla.target_minutes,
                }
            ),
            policy=None if decision.policy is None else decision.policy.policy,
            policy_reason=None if decision.policy is None else decision.policy.reason,
            policy_source=None if decision.policy is None else decision.policy.source,
            policy_text=None if decision.policy is None else decision.policy.text,
            resolution_stages=[
                {
                    "strategy": stage.strategy,
                    "outcome": stage.outcome,
                    "reason": stage.reason,
                    "evidence": stage.evidence,
                }
                for stage in decision.resolution_stages
            ],
            matched_rule_id=None if rule is None else rule.rule_id,
            matched_rule_name=None if rule is None else rule.name,
            matched_rule_priority=None if rule is None else rule.priority,
            rules_evaluated=decision.rules_evaluated,
            strategy=decision.strategy,
            candidates_considered=decision.candidates_considered,
            rejected_candidates=[
                {
                    "agent_id": str(candidate.agent_id),
                    "agent_name": candidate.agent_name,
                    "reason": candidate.reason.value,
                }
                for candidate in decision.rejected_candidates
            ],
            rejections_omitted=decision.rejections_omitted,
            ai_pickup_delay_seconds=decision.ai_pickup_delay_seconds,
            sentence=decision.sentence,
            details={} if rule is None else {"rule_conditions": dict(rule.conditions)},
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def for_conversation(self, *, conversation_id: uuid.UUID) -> list[RoutingDecisionRecord]:
        """One conversation's decisions, oldest first — the order somebody
        investigating reads them in, and the order they happened in.

        The order is real because ``record`` stamps ``decided_at`` from
        the application clock — a database ``now()`` would give every
        decision in one transaction the same instant and let this query
        show an assignment before the routing that caused it. ``id`` is a
        deterministic last resort so the SQL has a total order even in the
        impossible case of two writes landing in the same microsecond.
        """
        result = await self._session.execute(
            select(RoutingDecisionRecord)
            .where(RoutingDecisionRecord.conversation_id == conversation_id)
            .order_by(RoutingDecisionRecord.decided_at, RoutingDecisionRecord.id)
        )
        return list(result.scalars().all())

    async def recent_for_company(
        self, *, company_id: uuid.UUID, limit: int = 100
    ) -> list[RoutingDecisionRecord]:
        """The company's latest decisions, newest first — the operations
        console's firehose, served by ``ix_routing_decisions_company_recent``
        scanned backwards."""
        result = await self._session.execute(
            select(RoutingDecisionRecord)
            .where(RoutingDecisionRecord.company_id == company_id)
            .order_by(RoutingDecisionRecord.decided_at.desc(), RoutingDecisionRecord.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


__all__ = ["RoutingDecisionRepository"]
