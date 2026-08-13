"""The explanation vocabulary, exercised without a database.

Three things are proven here, and each one guards a specific way the
feature could rot:

- **Every reason code renders.** A code with no sentence is a code that
  reaches an export or a log line as a bare identifier, and the closed set
  is checked exhaustively so adding a member without a sentence fails
  here rather than in production.
- **Rejected candidates survive.** They are the half of an assignment
  decision that answers "why isn't this with Ada?", and they are also the
  half nothing else in the system would notice the loss of.
- **An old decision does not change.** Rules are edited and deleted
  routinely; a decision that re-read its rule would silently rewrite its
  own history every time somebody tuned their routing.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from blinkengage.application.services.routing_engine import RoutingEngine
from blinkengage.domain.execution_context import ConversationFacts, ExecutionContext
from blinkengage.domain.policies import Policy, PolicyEngine, as_routing_decision
from blinkengage.domain.routing_decisions import (
    MAX_RECORDED_REJECTIONS,
    MAX_RULE_NAME,
    AgentAssignment,
    CandidateRejection,
    MatchedRule,
    QueueRouting,
    RejectedCandidate,
    ResolutionStageRecord,
    RoutingDecision,
    RoutingDecisionKind,
    RoutingDecisionOutcome,
    RoutingDecisionReason,
    ai_deferred_decision,
    ai_pickup_decision,
    ai_released_decision,
    ai_stood_down_decision,
    assignment_decision,
    autopilot_decision,
    describe_conditions,
    most_informative,
    queue_decision,
    queue_unavailable_decision,
    service_decision,
)
from blinkengage.domain.runtime_queues import AiOverflowPolicy, OverflowStrategy
from blinkengage.domain.service_context import (
    AiPolicy,
    QueueBinding,
    ServiceContext,
    SlaTargets,
)
from blinkengage.domain.sla import (
    RECORDED_AS,
    Clock,
    PauseReason,
    SlaState,
    SlaTimer,
)
from blinkengage.domain.sla import as_routing_decision as sla_as_routing_decision
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


def _assignment(
    *,
    reason: RoutingDecisionReason,
    agent_id: UUID | None = None,
    agent_name: str | None = None,
    strategy: str = "round_robin",
    considered: int = 1,
    rejected: tuple[RejectedCandidate, ...] = (),
) -> AgentAssignment:
    return AgentAssignment(
        agent_id=agent_id,
        agent_name=agent_name,
        strategy=strategy,
        reason=reason,
        candidates_considered=considered,
        rejected=rejected,
    )


def _a_clock(**kw: object) -> Clock:
    defaults: dict[str, object] = {
        "timer": SlaTimer.FIRST_RESPONSE,
        "state": SlaState.RUNNING,
        "target_minutes": 60,
        "running_since": datetime(2026, 8, 1, tzinfo=UTC),
    }
    return Clock(**{**defaults, **kw})  # type: ignore[arg-type]


def as_sla_decision(clock: Clock, state: SlaState) -> RoutingDecision:
    """One clock movement, through the real factory and the real table."""
    kind, reason = RECORDED_AS[state]
    return sla_as_routing_decision(
        clock, kind=kind, reason=reason, now=datetime(2026, 8, 1, tzinfo=UTC)
    )


def _an_execution(*, status: str = "waiting") -> ExecutionContext:
    """The minimum an execution needs for a policy to answer."""
    company_id = uuid4()
    return ExecutionContext(
        service=ServiceContext(
            service_id=uuid4(),
            version=1,
            service_version_id=uuid4(),
            company_id=company_id,
            name="Support",
            queue=QueueBinding(
                logical_queue_id=uuid4(),
                logical_queue_name="Support",
                overflow_strategy=OverflowStrategy.WAIT,
                ai_overflow_policy=AiOverflowPolicy.NEVER,
            ),
            sla=SlaTargets(),
            ai=AiPolicy(),
        ),
        customer=None,
        conversation=ConversationFacts(
            conversation_id=uuid4(),
            company_id=company_id,
            channel_type="web_chat",
            started_at=datetime(2026, 8, 1, tzinfo=UTC),
            status=status,
        ),
    )


def _released(reason: str) -> RoutingDecision:
    """One hand-off decision, or a failure that names the gap.

    ``ai_released_decision`` answers ``None`` for a reason outside its
    vocabulary — deliberately, so production records nothing rather than an
    invented cause. Here that would silently drop a key and surface as a
    confusing set-difference, so it is asserted at the point it happens.
    """
    decision = ai_released_decision(reason)
    assert decision is not None, f"{reason!r} is not mapped onto the decision vocabulary"
    return decision


def _every_reason() -> dict[RoutingDecisionReason, RoutingDecision]:
    """One decision per reason code, built through the real factories.

    Written as a table so the exhaustiveness assertion below is a single
    set comparison — the point is that nobody can add a reason without
    landing in this map.
    """
    queue_id, agent_id, service_id = uuid4(), uuid4(), uuid4()
    rule = MatchedRule(
        rule_id=uuid4(),
        name="channel is web_chat",
        priority=1,
        conditions={"channel_type": "web_chat"},
    )
    return {
        RoutingDecisionReason.RULE_MATCHED: queue_decision(
            QueueRouting(
                queue_id=queue_id,
                reason=RoutingDecisionReason.RULE_MATCHED,
                matched_rule=rule,
                rules_evaluated=3,
            ),
            queue_name="Billing",
        ),
        RoutingDecisionReason.NO_RULE_MATCHED: queue_decision(
            QueueRouting(
                queue_id=None,
                reason=RoutingDecisionReason.NO_RULE_MATCHED,
                rules_evaluated=3,
            ),
            queue_name=None,
        ),
        RoutingDecisionReason.NO_RULES_CONFIGURED: queue_decision(
            QueueRouting(queue_id=None, reason=RoutingDecisionReason.NO_RULES_CONFIGURED),
            queue_name=None,
        ),
        RoutingDecisionReason.TARGET_QUEUE_MISSING: queue_unavailable_decision(
            queue_id=queue_id, queue_name=None, matched_rule=rule, inactive=False
        ),
        RoutingDecisionReason.TARGET_QUEUE_INACTIVE: queue_unavailable_decision(
            queue_id=queue_id, queue_name="Billing", matched_rule=rule, inactive=True
        ),
        RoutingDecisionReason.AUTOPILOT_QUEUE: autopilot_decision(
            queue_id=queue_id, queue_name="Billing"
        ),
        RoutingDecisionReason.STRATEGY_SELECTED: assignment_decision(
            _assignment(
                reason=RoutingDecisionReason.STRATEGY_SELECTED,
                agent_id=agent_id,
                agent_name="Ada Lovelace",
                considered=3,
                rejected=(
                    RejectedCandidate(
                        agent_id=uuid4(),
                        agent_name="Grace Hopper",
                        reason=CandidateRejection.NOT_CHOSEN_BY_STRATEGY,
                    ),
                ),
            ),
            queue_id=queue_id,
            queue_name="Billing",
        ),
        RoutingDecisionReason.ONLY_CANDIDATE: assignment_decision(
            _assignment(
                reason=RoutingDecisionReason.ONLY_CANDIDATE,
                agent_id=agent_id,
                agent_name="Ada Lovelace",
            ),
            queue_id=queue_id,
            queue_name="Billing",
        ),
        RoutingDecisionReason.QUEUE_IS_MANUAL_PICKUP: assignment_decision(
            _assignment(reason=RoutingDecisionReason.QUEUE_IS_MANUAL_PICKUP, strategy="manual"),
            queue_id=queue_id,
            queue_name="VIP",
        ),
        RoutingDecisionReason.STRATEGY_DECLINED: assignment_decision(
            _assignment(reason=RoutingDecisionReason.STRATEGY_DECLINED, strategy="least_load"),
            queue_id=queue_id,
            queue_name="Billing",
        ),
        RoutingDecisionReason.NO_AGENT_AVAILABLE: assignment_decision(
            _assignment(
                reason=RoutingDecisionReason.NO_AGENT_AVAILABLE,
                considered=2,
                rejected=(
                    RejectedCandidate(
                        agent_id=uuid4(),
                        agent_name="Ada Lovelace",
                        reason=CandidateRejection.AGENT_OFFLINE,
                    ),
                    RejectedCandidate(
                        agent_id=uuid4(),
                        agent_name="Grace Hopper",
                        reason=CandidateRejection.AGENT_BUSY,
                    ),
                ),
            ),
            queue_id=queue_id,
            queue_name="Billing",
        ),
        RoutingDecisionReason.NO_AGENT_WITH_REQUIRED_SKILL: assignment_decision(
            _assignment(
                reason=RoutingDecisionReason.NO_AGENT_WITH_REQUIRED_SKILL,
                considered=2,
                rejected=(
                    RejectedCandidate(
                        agent_id=uuid4(),
                        agent_name="Ada Lovelace",
                        reason=CandidateRejection.MISSING_REQUIRED_SKILL,
                    ),
                ),
            ),
            queue_id=queue_id,
            queue_name="Spanish Support",
        ),
        # --- An SLA clock moved ---------------------------------------
        #
        # Built through the SLA module's own factory, because it owns the
        # wording — the log carries the phrase the clock chose rather than
        # re-rendering it years later in whatever words the code uses then.
        RoutingDecisionReason.SLA_CLOCK_RUNNING: as_sla_decision(_a_clock(), SlaState.RUNNING),
        RoutingDecisionReason.SLA_CLOCK_PAUSED: as_sla_decision(
            _a_clock(
                state=SlaState.PAUSED,
                running_since=None,
                pause_reason=PauseReason.WAITING_FOR_CUSTOMER,
            ),
            SlaState.PAUSED,
        ),
        RoutingDecisionReason.SLA_TARGET_MET: as_sla_decision(
            _a_clock(state=SlaState.ACHIEVED), SlaState.ACHIEVED
        ),
        RoutingDecisionReason.SLA_TARGET_MISSED: as_sla_decision(
            _a_clock(state=SlaState.BREACHED), SlaState.BREACHED
        ),
        RoutingDecisionReason.SLA_CLOCK_STOPPED: as_sla_decision(
            _a_clock(state=SlaState.STOPPED), SlaState.STOPPED
        ),
        # --- A business rule was applied ------------------------------
        #
        # Built through the policy module's own factory, because it owns the
        # wording — the log carries the phrase the policy chose rather than
        # re-rendering it years later in whatever words the code uses then.
        RoutingDecisionReason.POLICY_ALLOWED: as_routing_decision(
            PolicyEngine().evaluate(Policy.ROUTING, _an_execution())
        ),
        RoutingDecisionReason.POLICY_DENIED: as_routing_decision(
            PolicyEngine().evaluate(Policy.ROUTING, _an_execution(status="closed"))
        ),
        RoutingDecisionReason.SERVICE_OWNS_QUEUE: queue_decision(
            QueueRouting(queue_id=queue_id, reason=RoutingDecisionReason.SERVICE_OWNS_QUEUE),
            queue_name="Billing queue",
        ),
        # --- Service resolution ---------------------------------------
        #
        # Built through ``service_decision`` like the rest, so the sentence
        # each produces is the one an export and a support engineer see.
        RoutingDecisionReason.SERVICE_CUSTOMER_CHOSE: service_decision(
            service_id=service_id,
            service_name="Billing",
            service_version=3,
            deciding_reason="customer_chose",
            stages=(),
        ),
        RoutingDecisionReason.SERVICE_RULE_MATCHED: service_decision(
            service_id=service_id,
            service_name="Billing",
            service_version=3,
            deciding_reason="rule_matched",
            stages=(
                ResolutionStageRecord(
                    strategy="business_rules",
                    outcome="resolved",
                    reason="rule_matched",
                    evidence={"matched_keyword": "invoice"},
                ),
            ),
        ),
        RoutingDecisionReason.SERVICE_FIXED: service_decision(
            service_id=service_id,
            service_name="Support",
            service_version=1,
            deciding_reason="fixed",
            stages=(),
        ),
        RoutingDecisionReason.SERVICE_FALLBACK: service_decision(
            service_id=service_id,
            service_name="Support",
            service_version=1,
            deciding_reason="fallback",
            stages=(),
        ),
        RoutingDecisionReason.SERVICE_NOT_CONFIGURED: service_decision(
            service_id=None,
            service_name=None,
            service_version=None,
            deciding_reason=None,
            stages=(),
        ),
        RoutingDecisionReason.PICKUP_DELAY_RUNNING: ai_deferred_decision(
            queue_id=queue_id, queue_name="Support", delay_seconds=30
        ),
        RoutingDecisionReason.PICKUP_DELAY_ELAPSED: ai_pickup_decision(
            queue_id=queue_id, queue_name="Support", delay_seconds=30
        ),
        RoutingDecisionReason.HUMAN_ARRIVED_FIRST: ai_stood_down_decision(
            queue_id=queue_id, queue_name="Support"
        ),
        # The hand-off reasons. Built through the real factory, which is
        # also the assertion that its mapping covers the vocabulary: a reason
        # the factory does not know returns ``None`` and fails here loudly
        # rather than silently recording nothing in production.
        RoutingDecisionReason.MODEL_REQUESTED_HANDOFF: _released("model_requested_handoff"),
        RoutingDecisionReason.CONFIDENCE_BELOW_THRESHOLD: _released("low_confidence"),
        RoutingDecisionReason.NO_REPLY_GENERATED: _released("no_reply_generated"),
        RoutingDecisionReason.ACTIVATION_MODE_EXCLUDES_THIS: _released("mode_disabled"),
        # The grounding verifier's two, which are hand-offs the model did not
        # ask for — it was confident and unsupported, or the records could not
        # settle the question.
        RoutingDecisionReason.UNVERIFIED_COMPANY_FACT: _released("unverified_company_fact"),
        RoutingDecisionReason.KNOWLEDGE_NOT_DECIDABLE: _released("knowledge_not_decidable"),
    }


def test_every_reason_code_has_a_decision_and_a_sentence() -> None:
    """The closed set is closed *and* complete.

    A reason with no rendering reaches a CSV export as a bare identifier,
    which is exactly the black-box behaviour this milestone removes — so
    the check is exhaustive rather than a sample.
    """
    decisions = _every_reason()
    assert set(decisions) == set(RoutingDecisionReason)

    sentences = set()
    for reason, decision in decisions.items():
        assert decision.reason is reason
        sentence = decision.sentence
        assert sentence.endswith("."), sentence
        # The reason code itself must never leak into the prose: the
        # sentence is written for a person, the code is for the console.
        assert reason.value not in sentence
        sentences.add(sentence)
    # Two reasons that render identically are two reasons a reader cannot
    # tell apart, which defeats having two of them.
    assert len(sentences) == len(decisions)


def test_every_rejection_code_can_be_ranked_and_phrased() -> None:
    """Both lookup tables cover the whole enum.

    A missing entry is a ``KeyError`` raised mid-ingest, on the one path
    where an exception costs a customer message — so the tables are
    checked against the enum rather than trusted to stay in step.
    """
    for rejection in CandidateRejection:
        decision = assignment_decision(
            _assignment(
                reason=RoutingDecisionReason.NO_AGENT_AVAILABLE,
                considered=1,
                rejected=(RejectedCandidate(uuid4(), "Ada Lovelace", rejection),),
            ),
            queue_id=uuid4(),
            queue_name="Billing",
        )
        assert "Ada Lovelace (" in decision.sentence
        # And ranking, which only runs on truncation.
        kept, omitted = most_informative(
            [RejectedCandidate(uuid4(), None, rejection) for _ in range(3)], limit=1
        )
        assert len(kept) == 1
        assert omitted == 2


def test_each_decision_kind_matches_its_outcome() -> None:
    """The invariant the factories exist to hold: an assignment always
    names an agent, "nothing" never does."""
    for decision in _every_reason().values():
        if decision.outcome is RoutingDecisionOutcome.AGENT:
            assert decision.kind is RoutingDecisionKind.AGENT_ASSIGNED
            assert decision.selected_agent_id is not None
        elif decision.outcome is RoutingDecisionOutcome.QUEUE:
            assert decision.kind is RoutingDecisionKind.QUEUE_SELECTED
            assert decision.selected_queue_id is not None
        elif decision.outcome is RoutingDecisionOutcome.AUTOPILOT:
            assert decision.kind is RoutingDecisionKind.AI_ENGAGED
            assert decision.selected_agent_id is None
        elif decision.sla is not None:
            # An SLA movement is about a clock, not about a destination. It
            # names no queue and no agent, and it always says which clock —
            # a row that did not would explain nothing.
            assert decision.kind.value.startswith("sla_")
            assert decision.sla.timer
            assert decision.selected_queue_id is None
            assert decision.selected_agent_id is None
        elif decision.outcome in (
            RoutingDecisionOutcome.ALLOWED,
            RoutingDecisionOutcome.DENIED,
        ):
            # A policy answers a question about permission. It names no
            # queue and no agent, and it always says which rule was asked —
            # a row that did not would explain nothing.
            assert decision.kind is RoutingDecisionKind.POLICY_EVALUATED
            assert decision.policy is not None
            assert decision.selected_queue_id is None
            assert decision.selected_agent_id is None
        elif decision.outcome is RoutingDecisionOutcome.SERVICE:
            # Resolution happens before a queue is chosen, so a service
            # decision names neither a queue nor an agent — and must name
            # the service, or the row explains nothing.
            assert decision.kind is RoutingDecisionKind.SERVICE_RESOLVED
            assert decision.selected_service_id is not None
            assert decision.selected_queue_id is None
            assert decision.selected_agent_id is None
        else:
            assert decision.selected_agent_id is None
            assert decision.kind in (
                RoutingDecisionKind.SERVICE_RESOLVED,
                RoutingDecisionKind.LEFT_UNROUTED,
                RoutingDecisionKind.LEFT_UNASSIGNED,
                # AI deliberately not taking a conversation is an outcome of
                # nothing — nothing was chosen — and that is the point of
                # the row rather than a gap in it.
                RoutingDecisionKind.AI_DEFERRED,
                # And AI giving one *back* is the same shape: it names no
                # destination because it chose none. Where the conversation
                # goes next is the ownership timeline's answer, and a
                # decision that also named a queue would be a second one.
                RoutingDecisionKind.AI_RELEASED,
            )


def test_the_sentence_names_the_queue_the_rule_and_the_agent() -> None:
    decisions = _every_reason()

    routed = decisions[RoutingDecisionReason.RULE_MATCHED]
    assert routed.sentence == (
        'Routed to the "Billing" queue because routing rule "channel is web_chat" '
        "(priority 1) matched."
    )

    assigned = decisions[RoutingDecisionReason.STRATEGY_SELECTED]
    assert assigned.sentence == (
        'Assigned to Ada Lovelace by the "Billing" queue\'s round_robin strategy, '
        "chosen from 3 agents considered. Passed over: Grace Hopper (not chosen by "
        "the strategy)."
    )

    unrouted = decisions[RoutingDecisionReason.NO_RULE_MATCHED]
    assert unrouted.sentence == (
        "Left unrouted: none of the 3 active routing rules matched this conversation."
    )

    waiting = decisions[RoutingDecisionReason.QUEUE_IS_MANUAL_PICKUP]
    assert waiting.sentence == (
        'Left unassigned: the "VIP" queue never auto-assigns — it waits for an agent '
        "to pick the conversation up."
    )


def test_a_decision_reads_correctly_when_the_queue_name_is_gone() -> None:
    """A queue deleted before the decision could be read still leaves a
    decision that says which rule sent the conversation there."""
    queue_id = uuid4()
    decision = queue_unavailable_decision(
        queue_id=queue_id,
        queue_name=None,
        matched_rule=MatchedRule(
            rule_id=uuid4(), name="matches everything", priority=100, conditions={}
        ),
        inactive=False,
    )
    assert decision.reason is RoutingDecisionReason.TARGET_QUEUE_MISSING
    assert 'routing rule "matches everything"' in decision.sentence
    assert decision.selected_queue_id == queue_id


def test_rejected_candidates_are_carried_with_their_names_and_reasons() -> None:
    ada, grace, alan = uuid4(), uuid4(), uuid4()
    decision = assignment_decision(
        _assignment(
            reason=RoutingDecisionReason.NO_AGENT_WITH_REQUIRED_SKILL,
            considered=3,
            rejected=(
                RejectedCandidate(ada, "Ada Lovelace", CandidateRejection.MISSING_REQUIRED_SKILL),
                RejectedCandidate(grace, "Grace Hopper", CandidateRejection.AGENT_OFFLINE),
                RejectedCandidate(alan, "Alan Turing", CandidateRejection.AGENT_BUSY),
            ),
        ),
        queue_id=uuid4(),
        queue_name="Spanish Support",
    )

    assert [c.agent_id for c in decision.rejected_candidates] == [ada, grace, alan]
    assert decision.rejections_omitted == 0
    # The whole point: the answer to "why isn't this with Ada" is legible
    # without joining anything.
    assert "Ada Lovelace (missing a required skill)" in decision.sentence
    assert "Grace Hopper (offline)" in decision.sentence
    assert "Alan Turing (busy)" in decision.sentence


def test_a_long_rejection_list_keeps_the_agents_who_were_in_contention() -> None:
    """Truncation must not be a plain head-of-list.

    A company with hundreds of agents produces hundreds of "offline"
    rejections, and the two people who were genuinely in the running are
    the only ones worth the space — so they survive the cap, and the
    overflow is counted rather than silently dropped.
    """
    contenders = [
        RejectedCandidate(uuid4(), f"Contender {i}", CandidateRejection.NOT_CHOSEN_BY_STRATEGY)
        for i in range(2)
    ]
    offline = [
        RejectedCandidate(uuid4(), f"Offline {i}", CandidateRejection.AGENT_OFFLINE)
        for i in range(MAX_RECORDED_REJECTIONS + 40)
    ]
    kept, omitted = most_informative(offline + contenders)

    assert len(kept) == MAX_RECORDED_REJECTIONS
    assert omitted == 40 + 2
    assert [c.agent_name for c in kept[:2]] == ["Contender 0", "Contender 1"]

    decision = assignment_decision(
        _assignment(
            reason=RoutingDecisionReason.NO_AGENT_AVAILABLE,
            considered=len(offline) + len(contenders),
            rejected=tuple(offline + contenders),
        ),
        queue_id=uuid4(),
        queue_name="Billing",
    )
    assert decision.rejections_omitted == 42
    # 25 kept, 3 named in the sentence, so 22 kept-but-unnamed plus the 42
    # that did not fit at all.
    assert "and 64 more" in decision.sentence


def test_no_rejections_leaves_no_dangling_clause() -> None:
    decision = assignment_decision(
        _assignment(
            reason=RoutingDecisionReason.ONLY_CANDIDATE, agent_id=uuid4(), agent_name="Ada"
        ),
        queue_id=uuid4(),
        queue_name="Billing",
    )
    assert "Passed over" not in decision.sentence


async def test_the_routing_engine_reports_the_rule_that_matched() -> None:
    company_id, queue_id = uuid4(), uuid4()
    rule = _rule(
        company_id=company_id,
        priority=5,
        conditions={"body_contains": "refund"},
        target_queue_id=queue_id,
    )
    engine = RoutingEngine(routing_rules=_FakeRoutingRuleRepository([rule]))

    routing = await engine.select_queue(
        company_id=company_id, channel_type="web_chat", body="I want a refund"
    )

    assert routing.queue_id == queue_id
    assert routing.reason is RoutingDecisionReason.RULE_MATCHED
    assert routing.rules_evaluated == 1
    assert routing.matched_rule is not None
    assert routing.matched_rule.rule_id == rule.id
    assert routing.matched_rule.name == 'message contains "refund"'
    assert routing.matched_rule.priority == 5


async def test_the_routing_engine_separates_no_rules_from_no_match() -> None:
    """Two symptoms that look identical and have different fixes: nobody
    has configured routing, versus forty rules that all missed."""
    company_id = uuid4()
    empty = RoutingEngine(routing_rules=_FakeRoutingRuleRepository([]))
    unmatched = RoutingEngine(
        routing_rules=_FakeRoutingRuleRepository(
            [
                _rule(
                    company_id=company_id,
                    priority=1,
                    conditions={"channel_type": "whatsapp"},
                    target_queue_id=uuid4(),
                )
            ]
        )
    )

    none_configured = await empty.select_queue(
        company_id=company_id, channel_type="web_chat", body=None
    )
    none_matched = await unmatched.select_queue(
        company_id=company_id, channel_type="web_chat", body=None
    )

    assert none_configured.reason is RoutingDecisionReason.NO_RULES_CONFIGURED
    assert none_configured.rules_evaluated == 0
    assert none_matched.reason is RoutingDecisionReason.NO_RULE_MATCHED
    assert none_matched.rules_evaluated == 1


async def test_an_inactive_rule_is_not_counted_as_evaluated() -> None:
    """``rules_evaluated`` must mean "rules that had a chance", or the
    sentence tells an operator their disabled rule was tried."""
    company_id = uuid4()
    engine = RoutingEngine(
        routing_rules=_FakeRoutingRuleRepository(
            [
                _rule(
                    company_id=company_id,
                    priority=1,
                    conditions={},
                    target_queue_id=uuid4(),
                    is_active=False,
                )
            ]
        )
    )

    routing = await engine.select_queue(company_id=company_id, channel_type="web_chat", body=None)

    assert routing.queue_id is None
    assert routing.reason is RoutingDecisionReason.NO_RULES_CONFIGURED


async def test_editing_or_deleting_the_rule_does_not_change_an_old_decision() -> None:
    """The property the whole "copy as values" design exists for.

    A routing rule is edited and deleted through an ordinary admin
    screen. A decision that referenced the row would silently rewrite its
    own history every time somebody tuned their routing — and would read
    as an unexplained queue id once the rule was gone entirely.
    """
    company_id, queue_id = uuid4(), uuid4()
    rule = _rule(
        company_id=company_id,
        priority=5,
        conditions={"channel_type": "web_chat"},
        target_queue_id=queue_id,
    )
    repository = _FakeRoutingRuleRepository([rule])
    engine = RoutingEngine(routing_rules=repository)

    routing = await engine.select_queue(
        company_id=company_id, channel_type="web_chat", body="Hello"
    )
    decision = queue_decision(routing, queue_name="Billing")
    original_sentence = decision.sentence

    # The operator retunes the rule...
    rule.conditions = {"body_contains": "invoice"}
    rule.priority = 99
    # ...and then deletes it outright.
    repository._rules.clear()

    assert decision.matched_rule is not None
    assert decision.matched_rule.name == "channel is web_chat"
    assert decision.matched_rule.priority == 5
    assert decision.matched_rule.conditions == {"channel_type": "web_chat"}
    assert decision.sentence == original_sentence
    assert 'routing rule "channel is web_chat" (priority 5)' in original_sentence


def test_a_renamed_queue_or_departed_agent_does_not_change_an_old_decision() -> None:
    """Same property, for the other two referents. The names are copied at
    decision time, so a decision keeps reading the way it read."""
    decision = assignment_decision(
        _assignment(
            reason=RoutingDecisionReason.STRATEGY_SELECTED,
            agent_id=uuid4(),
            agent_name="Ada Lovelace",
            considered=2,
            rejected=(
                RejectedCandidate(uuid4(), "Grace Hopper", CandidateRejection.AGENT_OFFLINE),
            ),
        ),
        queue_id=uuid4(),
        queue_name="Billing",
    )

    # Nothing in the decision can be made to change: it holds no reference
    # to a queue row, an agent row, or a user row.
    assert "Ada Lovelace" in decision.sentence
    assert '"Billing"' in decision.sentence
    assert "Grace Hopper (offline)" in decision.sentence


def test_conditions_are_described_for_a_reader() -> None:
    assert describe_conditions({}) == "matches everything"
    assert describe_conditions({"channel_type": "whatsapp"}) == "channel is whatsapp"
    assert describe_conditions({"body_contains": "refund"}) == 'message contains "refund"'
    assert (
        describe_conditions({"channel_type": "email", "body_contains": "invoice"})
        == 'channel is email and message contains "invoice"'
    )
    # A key this narrow engine does not know is still shown: a condition
    # nobody renders is a condition nobody can debug.
    assert describe_conditions({"language": "ar"}) == "language is ar"


def test_an_over_long_rule_is_clipped_rather_than_losing_its_decision() -> None:
    """Nothing validates how long a ``body_contains`` value may be.

    An unclipped name would not fit ``matched_rule_name``, and the
    audit-write guard would drop the whole decision rather than store it
    short — losing the explanation to protect a column.
    """
    described = describe_conditions({"body_contains": "x" * 5_000})

    assert len(described) == MAX_RULE_NAME
    assert described.endswith("…")
    assert described.startswith('message contains "xxx')
