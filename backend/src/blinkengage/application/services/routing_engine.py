"""Narrow, conversation-routing-specific rule evaluation — deliberately
*not* a general rules/workflow engine. See
``docs/architecture/queues-routing.md``'s scope-boundary note.

**Decides and describes; never writes.** ``select_queue`` returns a
``QueueRouting`` — the queue *and* the reasoning that produced it —
because the rule that matched is the answer to "why is this conversation
in this queue", and it used to exist for exactly one stack frame before
being discarded at the return statement. Persisting the description is
the caller's job (``conversation_ingest_consumer``), which is what keeps
this engine unit-testable with a fake repository and no database.
"""

from uuid import UUID

from blinkengage.domain.routing_decisions import (
    MatchedRule,
    QueueRouting,
    RoutingDecisionReason,
    describe_conditions,
)
from blinkengage.infrastructure.repositories.routing_rule_repository import RoutingRuleRepository


class RoutingEngine:
    def __init__(self, *, routing_rules: RoutingRuleRepository) -> None:
        self._routing_rules = routing_rules

    async def select_queue(
        self, *, company_id: UUID, channel_type: str, body: str | None
    ) -> QueueRouting:
        """First matching rule (by ascending ``priority``) wins; no queue
        if nothing matches — the conversation is left unqueued/unassigned,
        not defaulted to some implicit queue.

        The matching rule is captured **as values** (``MatchedRule``), not
        as a reference to the row: rules are edited and deleted through
        the routing-rules admin screen routinely, and a decision that
        re-read its rule would silently rewrite its own history every time
        somebody tuned their routing.

        "No rules at all" and "rules that all missed" are returned as two
        different reasons on purpose — a new company that never configured
        routing and an established one whose forty rules do not cover a
        new channel have the same symptom and different fixes.
        """
        rules = await self._routing_rules.list_active_ordered(company_id=company_id)
        for rule in rules:
            if self._matches(rule.conditions, channel_type=channel_type, body=body):
                return QueueRouting(
                    queue_id=rule.target_queue_id,
                    reason=RoutingDecisionReason.RULE_MATCHED,
                    matched_rule=MatchedRule(
                        rule_id=rule.id,
                        name=describe_conditions(rule.conditions),
                        priority=rule.priority,
                        # Copied, not aliased: the ORM row's own dict stays
                        # attached to a live session and would follow any
                        # later edit into the decision that referenced it.
                        conditions=dict(rule.conditions),
                    ),
                    rules_evaluated=len(rules),
                )
        return QueueRouting(
            queue_id=None,
            reason=(
                RoutingDecisionReason.NO_RULE_MATCHED
                if rules
                else RoutingDecisionReason.NO_RULES_CONFIGURED
            ),
            rules_evaluated=len(rules),
        )

    @staticmethod
    def _matches(conditions: dict[str, str], *, channel_type: str, body: str | None) -> bool:
        expected_channel = conditions.get("channel_type")
        if expected_channel is not None and expected_channel != channel_type:
            return False
        needle = conditions.get("body_contains")
        if needle is None:
            return True
        return body is not None and needle.lower() in body.lower()
