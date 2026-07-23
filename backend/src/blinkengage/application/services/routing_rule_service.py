"""Routing rule CRUD. See ``docs/architecture/queues-routing.md`` — the
rules themselves are evaluated by ``RoutingEngine``, not here.
"""

from uuid import UUID

from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.infrastructure.database.models.queue import RoutingRule
from blinkengage.infrastructure.repositories.routing_rule_repository import RoutingRuleRepository


class RoutingRuleService:
    def __init__(
        self, *, routing_rules: RoutingRuleRepository, events: DomainEventPublisher
    ) -> None:
        self._routing_rules = routing_rules
        self._events = events

    async def list_rules(self, *, company_id: UUID) -> list[RoutingRule]:
        return await self._routing_rules.list_for_company(company_id=company_id)

    async def get(self, *, company_id: UUID, rule_id: UUID) -> RoutingRule:
        rule = await self._routing_rules.get_by_id(company_id=company_id, rule_id=rule_id)
        if rule is None:
            raise EntityNotFoundError("RoutingRule", rule_id)
        return rule

    async def create(
        self,
        *,
        company_id: UUID,
        priority: int,
        conditions: dict[str, str],
        target_queue_id: UUID,
        actor_user_id: UUID | None = None,
    ) -> RoutingRule:
        rule = await self._routing_rules.add(
            RoutingRule(
                company_id=company_id,
                priority=priority,
                conditions=conditions,
                target_queue_id=target_queue_id,
            )
        )
        await self._events.publish(
            DomainEvent(
                event_type="routing_rule.created",
                company_id=company_id,
                aggregate_type="routing_rule",
                aggregate_id=rule.id,
                actor_user_id=actor_user_id,
                payload={"priority": priority, "conditions": conditions},
            )
        )
        return rule

    async def update(
        self,
        *,
        company_id: UUID,
        rule_id: UUID,
        priority: int | None,
        conditions: dict[str, str] | None,
        target_queue_id: UUID | None,
        is_active: bool | None,
        actor_user_id: UUID | None = None,
    ) -> RoutingRule:
        rule = await self.get(company_id=company_id, rule_id=rule_id)
        if priority is not None:
            rule.priority = priority
        if conditions is not None:
            rule.conditions = conditions
        if target_queue_id is not None:
            rule.target_queue_id = target_queue_id
        if is_active is not None:
            rule.is_active = is_active

        await self._events.publish(
            DomainEvent(
                event_type="routing_rule.updated",
                company_id=company_id,
                aggregate_type="routing_rule",
                aggregate_id=rule.id,
                actor_user_id=actor_user_id,
                payload={"priority": rule.priority, "is_active": rule.is_active},
            )
        )
        return rule

    async def delete(
        self, *, company_id: UUID, rule_id: UUID, actor_user_id: UUID | None = None
    ) -> None:
        rule = await self.get(company_id=company_id, rule_id=rule_id)
        await self._routing_rules.delete(rule)
        await self._events.publish(
            DomainEvent(
                event_type="routing_rule.deleted",
                company_id=company_id,
                aggregate_type="routing_rule",
                aggregate_id=rule_id,
                actor_user_id=actor_user_id,
                payload={},
            )
        )
