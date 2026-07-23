"""Narrow, conversation-routing-specific rule evaluation — deliberately
*not* a general rules/workflow engine. See
``docs/architecture/queues-routing.md``'s scope-boundary note.
"""

from uuid import UUID

from blinkengage.infrastructure.repositories.routing_rule_repository import RoutingRuleRepository


class RoutingEngine:
    def __init__(self, *, routing_rules: RoutingRuleRepository) -> None:
        self._routing_rules = routing_rules

    async def select_queue(
        self, *, company_id: UUID, channel_type: str, body: str | None
    ) -> UUID | None:
        """First matching rule (by ascending ``priority``) wins; ``None``
        if nothing matches — the conversation is left unqueued/unassigned,
        not defaulted to some implicit queue."""
        rules = await self._routing_rules.list_active_ordered(company_id=company_id)
        for rule in rules:
            if self._matches(rule.conditions, channel_type=channel_type, body=body):
                return rule.target_queue_id
        return None

    @staticmethod
    def _matches(conditions: dict[str, str], *, channel_type: str, body: str | None) -> bool:
        expected_channel = conditions.get("channel_type")
        if expected_channel is not None and expected_channel != channel_type:
            return False
        needle = conditions.get("body_contains")
        if needle is None:
            return True
        return body is not None and needle.lower() in body.lower()
