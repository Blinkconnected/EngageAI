"""``select_queue`` now returns a ``QueueRouting`` — the queue *and* the
reasoning that produced it — so every assertion here reads ``.queue_id``.
The reasoning itself (which rule matched, why nothing did) is covered in
``tests/unit/test_routing_decisions.py``; these stay focused on the
matching rules they were written for.
"""

from uuid import UUID, uuid4

from blinkengage.application.services.routing_engine import RoutingEngine
from blinkengage.infrastructure.database.models.queue import RoutingRule


class _FakeRoutingRuleRepository:
    def __init__(self, rules: list[RoutingRule]) -> None:
        self._rules = rules

    async def list_active_ordered(self, *, company_id: UUID) -> list[RoutingRule]:
        return sorted(
            (r for r in self._rules if r.company_id == company_id and r.is_active),
            key=lambda r: r.priority,
        )


def _rule(
    *,
    company_id: UUID,
    priority: int,
    conditions: dict[str, str],
    target_queue_id: UUID,
    is_active: bool = True,
) -> RoutingRule:
    return RoutingRule(
        company_id=company_id,
        priority=priority,
        conditions=conditions,
        target_queue_id=target_queue_id,
        is_active=is_active,
    )


async def test_first_matching_rule_by_priority_wins() -> None:
    company_id = uuid4()
    queue_a, queue_b = uuid4(), uuid4()
    rules = [
        _rule(
            company_id=company_id,
            priority=10,
            conditions={"channel_type": "web_chat"},
            target_queue_id=queue_a,
        ),
        _rule(
            company_id=company_id,
            priority=5,
            conditions={"body_contains": "billing"},
            target_queue_id=queue_b,
        ),
    ]
    engine = RoutingEngine(routing_rules=_FakeRoutingRuleRepository(rules))

    # Both rules would match, but priority 5 (queue_b) evaluates first.
    selected = await engine.select_queue(
        company_id=company_id, channel_type="web_chat", body="a billing question"
    )
    assert selected.queue_id == queue_b


async def test_channel_type_condition_matches_exactly() -> None:
    company_id = uuid4()
    queue_id = uuid4()
    rules = [
        _rule(
            company_id=company_id,
            priority=1,
            conditions={"channel_type": "whatsapp"},
            target_queue_id=queue_id,
        )
    ]
    engine = RoutingEngine(routing_rules=_FakeRoutingRuleRepository(rules))

    unmatched = await engine.select_queue(company_id=company_id, channel_type="web_chat", body=None)
    matched = await engine.select_queue(company_id=company_id, channel_type="whatsapp", body=None)
    assert unmatched.queue_id is None
    assert matched.queue_id == queue_id


async def test_body_contains_is_case_insensitive() -> None:
    company_id = uuid4()
    queue_id = uuid4()
    rules = [
        _rule(
            company_id=company_id,
            priority=1,
            conditions={"body_contains": "REFUND"},
            target_queue_id=queue_id,
        )
    ]
    engine = RoutingEngine(routing_rules=_FakeRoutingRuleRepository(rules))

    matched = await engine.select_queue(
        company_id=company_id, channel_type="web_chat", body="I want a refund please"
    )
    unmatched = await engine.select_queue(
        company_id=company_id, channel_type="web_chat", body="no relevant keyword"
    )
    assert matched.queue_id == queue_id
    assert unmatched.queue_id is None


async def test_inactive_rules_are_ignored() -> None:
    company_id = uuid4()
    rules = [
        _rule(
            company_id=company_id,
            priority=1,
            conditions={},
            target_queue_id=uuid4(),
            is_active=False,
        )
    ]
    engine = RoutingEngine(routing_rules=_FakeRoutingRuleRepository(rules))

    selected = await engine.select_queue(company_id=company_id, channel_type="web_chat", body=None)
    assert selected.queue_id is None


async def test_no_matching_rule_returns_none() -> None:
    engine = RoutingEngine(routing_rules=_FakeRoutingRuleRepository([]))
    selected = await engine.select_queue(company_id=uuid4(), channel_type="web_chat", body=None)
    assert selected.queue_id is None
