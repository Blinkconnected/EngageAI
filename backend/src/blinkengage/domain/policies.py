"""The Policy Engine: every business rule, in one place, each one explainable.

A rule like "AI may not answer a customer who asked for no automated messages"
is true everywhere or it is not true at all. Left to each module, it gets
implemented in the AI service, forgotten in the automation service, and
implemented slightly differently in the third place somebody needed it — and
the platform then behaves differently depending on which door a conversation
came through. That is the failure this module exists to prevent.

So modules do not evaluate business rules. They ask:

    decision = engine.evaluate(Policy.AI_ENGAGEMENT, execution)
    if decision.allowed:
        ...

**Every evaluation answers with its reasoning.** Not a boolean — a decision
carrying *what* was decided, *why* from a closed set of reasons, and **where
the answer came from**: the service's configuration, the customer's
preferences, the state of the conversation, the platform's own default. That
last field is the one an administrator actually needs. "Denied" tells them
nothing; "denied, from the Customer Context" tells them which screen to open.

**Policies are pure.** They are handed an ``ExecutionContext`` — which already
carries the resolved service and customer, by construction — and they return a
decision. No repository, no clock, no I/O. That is what makes them exhaustively
testable, and it is why the context architecture had to exist first: a policy
that could look things up would be a policy whose answer depended on when you
asked it.

**Policies that are not yet enforced say so.** Several rules here belong to
modules that have not shipped. Rather than omit them — which would leave each
future module free to invent its own — they exist and answer
``NOT_YET_ENFORCED`` from ``PLATFORM_DEFAULT``. A reader of the Routing
Inspector sees "allowed because this policy is not yet enforced", which is the
truth, instead of a fabricated rationale that reads like a real decision.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from blinkengage.domain.customer_context import ContactPreference
from blinkengage.domain.execution_context import ExecutionContext
from blinkengage.domain.routing_decisions import (
    PolicyEvaluation,
    RoutingDecision,
    RoutingDecisionKind,
    RoutingDecisionOutcome,
    RoutingDecisionReason,
)


class Policy(StrEnum):
    """Every question the platform asks about what it is allowed to do.

    A closed set: a policy nothing recognises is a rule nobody enforces, and
    the whole point is that there is exactly one list.
    """

    #: May AI answer this conversation at all?
    AI_ENGAGEMENT = "ai_engagement"
    #: May this conversation be routed by the engine?
    ROUTING = "routing"
    #: May a previous agent keep this conversation rather than it re-queuing?
    OWNERSHIP_CONTINUATION = "ownership_continuation"
    #: May the SLA clock stop?
    SLA_PAUSE = "sla_pause"
    #: May an automation run against this conversation?
    AUTOMATION_EXECUTION = "automation_execution"
    #: May this conversation skip the queue entirely?
    QUEUE_BYPASS = "queue_bypass"
    #: May this conversation enter the VIP lane?
    VIP_QUEUE_ENTRY = "vip_queue_entry"
    #: May an agent take this conversation?
    AGENT_PICKUP = "agent_pickup"
    #: May this conversation be closed without a human doing it?
    AUTO_CLOSE = "auto_close"
    #: May the platform *remember* anything from this conversation? The
    #: Memory Platform's gate, and a genuinely separate question from
    #: whether AI may answer: a hospital may happily let AI reply from
    #: approved articles while forbidding any retention of what patients
    #: said. One switch cannot express that, and a platform selling to
    #: healthcare that offers only one switch will be asked to turn
    #: everything off.
    MEMORY_RECORDING = "memory_recording"
    #: May the platform *learn* from this conversation — turn it into an
    #: observation a pattern could later be detected from? The Learning
    #: Platform's gate and its kill switch. Deliberately separate from
    #: MEMORY_RECORDING: a company may be content for the platform to keep
    #: notes on its own relationships while forbidding those notes being
    #: mined for patterns, and one switch cannot express that.
    KNOWLEDGE_LEARNING = "knowledge_learning"


class Effect(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class PolicySource(StrEnum):
    """Where the answer came from — the field that makes a denial actionable.

    "Denied" sends an administrator hunting. "Denied, from the Customer
    Context" tells them which screen to open.
    """

    SERVICE_CONTEXT = "service_context"
    CUSTOMER_CONTEXT = "customer_context"
    CONVERSATION_STATE = "conversation_state"
    QUEUE_CAPACITY = "queue_capacity"
    #: Company-wide switches, including the AI compliance kill switch. A
    #: separate source because the screen an administrator must open is a
    #: different one, and because these override everything below them.
    COMPANY_SETTINGS = "company_settings"
    #: The platform's own rule, applying because nothing more specific was
    #: configured. Distinct from the three above so "nobody configured this"
    #: is never mistaken for "somebody chose this".
    PLATFORM_DEFAULT = "platform_default"


class PolicyReason(StrEnum):
    """Why a policy answered as it did. Closed, so the Inspector can group."""

    # --- allow -----------------------------------------------------------
    #: Nothing forbids it.
    PERMITTED = "permitted"
    #: The customer's standing earns it.
    CUSTOMER_QUALIFIES = "customer_qualifies"
    #: The service is configured for it.
    SERVICE_ALLOWS = "service_allows"
    #: The rule exists but the module that would enforce it has not shipped.
    #: Answered instead of a fabricated rationale — see the module docstring.
    NOT_YET_ENFORCED = "not_yet_enforced"

    # --- deny ------------------------------------------------------------
    #: The service has this switched off.
    SERVICE_DISABLED = "service_disabled"
    #: The company-wide switch is off — the compliance kill switch.
    COMPANY_DISABLED = "company_disabled"
    #: Switched on, but no provider was ever configured.
    NO_AI_PROVIDER = "no_ai_provider"
    #: The company has memory retention switched off entirely.
    MEMORY_DISABLED = "memory_disabled"
    #: The company has learning switched off entirely.
    LEARNING_DISABLED = "learning_disabled"
    #: AI features are on, but Autopilot itself is not. A company may want
    #: agent-facing suggestions without AI answering customers directly,
    #: and reporting that as "AI is off" would send an administrator to
    #: switch on something already on.
    AUTOPILOT_DISABLED = "autopilot_disabled"
    #: Autopilot is on, but not for brand-new conversations — a company
    #: running it on SLA triggers and agent requests only.
    AUTOPILOT_MODE_EXCLUDES_THIS = "autopilot_mode_excludes_this"
    #: The execution did not say what the company allows, so AI is refused
    #: rather than assumed. Fail-closed, and visibly so: this reason in the
    #: log means a caller needs fixing, not that a customer was refused.
    CAPABILITIES_UNKNOWN = "capabilities_unknown"
    #: The customer asked not to receive automated messages.
    CUSTOMER_OPTED_OUT = "customer_opted_out"
    #: The customer's standing does not qualify.
    CUSTOMER_NOT_ELIGIBLE = "customer_not_eligible"
    #: The service has no queue, so there is nowhere to route to.
    NO_QUEUE_CONFIGURED = "no_queue_configured"
    #: A human already owns it; AI stands down.
    ALREADY_WITH_AN_AGENT = "already_with_an_agent"
    #: It is already finished.
    CONVERSATION_CLOSED = "conversation_closed"
    #: Somebody else has it.
    ALREADY_ASSIGNED = "already_assigned"


#: The human wording. Kept beside the codes rather than instead of them: a
#: console filters on the code and shows the sentence.
REASON_TEXT: dict[PolicyReason, str] = {
    PolicyReason.PERMITTED: "nothing forbids it",
    PolicyReason.CUSTOMER_QUALIFIES: "this customer qualifies",
    PolicyReason.SERVICE_ALLOWS: "the service allows it",
    PolicyReason.NOT_YET_ENFORCED: "this policy is not yet enforced",
    PolicyReason.SERVICE_DISABLED: "the service has it switched off",
    PolicyReason.COMPANY_DISABLED: "the company has AI features switched off",
    PolicyReason.MEMORY_DISABLED: "the company has memory switched off",
    PolicyReason.LEARNING_DISABLED: "the company has learning switched off",
    PolicyReason.NO_AI_PROVIDER: "no AI provider is configured",
    PolicyReason.AUTOPILOT_DISABLED: "AI Autopilot is switched off for this company",
    PolicyReason.AUTOPILOT_MODE_EXCLUDES_THIS: (
        "Autopilot does not answer brand-new conversations for this company"
    ),
    PolicyReason.CAPABILITIES_UNKNOWN: ("the platform could not confirm what this company allows"),
    PolicyReason.CUSTOMER_OPTED_OUT: "the customer asked for no automated messages",
    PolicyReason.CUSTOMER_NOT_ELIGIBLE: "this customer does not qualify",
    PolicyReason.NO_QUEUE_CONFIGURED: "the service has no queue to route to",
    PolicyReason.ALREADY_WITH_AN_AGENT: "an agent already owns it",
    PolicyReason.CONVERSATION_CLOSED: "the conversation is already finished",
    PolicyReason.ALREADY_ASSIGNED: "somebody else already has it",
}

#: Conversation statuses in which a human owns the conversation. Kept here
#: rather than imported from the ORM enum so ``domain/`` stays framework-free;
#: the lifecycle milestone widens this list and these are the values that
#: exist today.
_AGENT_OWNS = frozenset({"in_progress", "waiting_customer", "waiting_agent", "open"})
_FINISHED = frozenset({"resolved", "closed", "customer_feedback"})


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """One answer, with everything needed to explain and act on it."""

    policy: Policy
    effect: Effect
    reason: PolicyReason
    source: PolicySource
    #: Anything a reader needs beyond the reason code — the threshold that
    #: was not met, the status that blocked it. Never customer message text.
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.effect is Effect.ALLOW

    @property
    def denied(self) -> bool:
        return self.effect is Effect.DENY

    @property
    def sentence(self) -> str:
        """How this reads in the Routing Inspector."""
        verb = "Allowed" if self.allowed else "Denied"
        what = self.policy.value.replace("_", " ")
        return f"{verb}: {what} — {REASON_TEXT[self.reason]} ({self.source.value})."


def _allow(
    policy: Policy, reason: PolicyReason, source: PolicySource, **detail: Any
) -> PolicyDecision:
    return PolicyDecision(policy, Effect.ALLOW, reason, source, detail)


def _deny(
    policy: Policy, reason: PolicyReason, source: PolicySource, **detail: Any
) -> PolicyDecision:
    return PolicyDecision(policy, Effect.DENY, reason, source, detail)


# --- the rules -------------------------------------------------------------
#
# Each is a pure function of the ExecutionContext. Order matters inside one:
# the *most specific* reason should win, because "the customer opted out" is a
# more useful answer than "the service has AI off" when both are true and only
# one of them is the thing an administrator wants to change.


def _ai_engagement(execution: ExecutionContext) -> PolicyDecision:
    """May AI answer at all?

    **This rule fails closed.** An execution that did not say what the
    company allows is refused, rather than treated as permission. Every
    other policy here can safely default to allowing; this one cannot,
    because ``ai_enabled`` is a compliance kill switch and a caller that
    forgets to populate capabilities would silently switch it back on.
    Refusing costs a reply; the other direction costs a promise.

    The denial order is *narrowest first* — the reason that stays true after
    the broader ones are fixed. A customer's refusal survives an
    administrator re-enabling AI company-wide, so it is reported first: an
    administrator told "the company has AI off", who turns it on and finds
    AI still silent for this customer, has been sent the wrong way.
    """
    customer = execution.customer
    if customer is not None and (
        customer.contact_preference is ContactPreference.NO_AUTOMATED_MESSAGES
    ):
        return _deny(
            Policy.AI_ENGAGEMENT,
            PolicyReason.CUSTOMER_OPTED_OUT,
            PolicySource.CUSTOMER_CONTEXT,
        )
    if execution.capabilities is None:
        return _deny(
            Policy.AI_ENGAGEMENT,
            PolicyReason.CAPABILITIES_UNKNOWN,
            PolicySource.PLATFORM_DEFAULT,
        )
    if not execution.available.ai_enabled:
        return _deny(
            Policy.AI_ENGAGEMENT,
            PolicyReason.COMPANY_DISABLED,
            PolicySource.COMPANY_SETTINGS,
        )
    if not execution.available.ai_provider_configured:
        # Distinct from the switch above: "turned off" and "turned on but
        # never set up" are different problems with different fixes, and
        # collapsing them sends an administrator to the wrong screen.
        return _deny(
            Policy.AI_ENGAGEMENT,
            PolicyReason.NO_AI_PROVIDER,
            PolicySource.COMPANY_SETTINGS,
        )
    if not execution.available.autopilot_enabled:
        # A company may want agent-facing suggestions without AI answering
        # customers directly. Reported separately, or an administrator is
        # sent to switch on something that is already on.
        return _deny(
            Policy.AI_ENGAGEMENT,
            PolicyReason.AUTOPILOT_DISABLED,
            PolicySource.COMPANY_SETTINGS,
        )
    if (
        execution.conversation.status == "new"
        and not execution.available.autopilot_on_new_conversation
    ):
        # Autopilot running on SLA triggers and agent requests only. The
        # conversation is brand new, so this mode excludes it — and says
        # so rather than reporting Autopilot as off.
        return _deny(
            Policy.AI_ENGAGEMENT,
            PolicyReason.AUTOPILOT_MODE_EXCLUDES_THIS,
            PolicySource.COMPANY_SETTINGS,
        )
    if execution.service is not None and not execution.service.ai.enabled:
        # Only asked where there *is* a service. A company with no service
        # directory has no service policy to consult, and the tiers that do
        # answer for it — the company switches above, the queue's Autopilot
        # opt-in below — have already been checked. Treating a missing
        # service as a refusal would silence AI for every company that has
        # not adopted the directory, which is all of them today.
        return _deny(
            Policy.AI_ENGAGEMENT,
            PolicyReason.SERVICE_DISABLED,
            PolicySource.SERVICE_CONTEXT,
        )
    if execution.conversation.assigned_agent_id is not None:
        # AI is a queue worker, not an agent: the moment a human owns the
        # conversation, AI stands down to assisting.
        return _deny(
            Policy.AI_ENGAGEMENT,
            PolicyReason.ALREADY_WITH_AN_AGENT,
            PolicySource.CONVERSATION_STATE,
        )
    if execution.conversation.status in _FINISHED:
        return _deny(
            Policy.AI_ENGAGEMENT,
            PolicyReason.CONVERSATION_CLOSED,
            PolicySource.CONVERSATION_STATE,
        )
    service = execution.service
    if service is None:
        # Allowed by the tiers that exist for this company. Reported against
        # the company rather than a service, so the Inspector says who
        # actually decided instead of naming configuration nobody wrote.
        return _allow(
            Policy.AI_ENGAGEMENT,
            PolicyReason.PERMITTED,
            PolicySource.COMPANY_SETTINGS,
        )
    return _allow(
        Policy.AI_ENGAGEMENT,
        PolicyReason.SERVICE_ALLOWS,
        PolicySource.SERVICE_CONTEXT,
        pickup_delay_seconds=service.ai.pickup_delay_seconds,
        confidence_threshold=(
            None
            if service.ai.confidence_threshold is None
            else str(service.ai.confidence_threshold)
        ),
    )


def _routing(execution: ExecutionContext) -> PolicyDecision:
    """May this conversation be routed?

    **A service with no queue is no longer a denial**, and that changed when
    the service took ownership of queue selection: routing rules became the
    fallback rather than a parallel mechanism, so a service that names no
    queue is a service whose conversations the rules still place. Refusing
    here would block a configuration that works.

    "Nothing routed this" remains recorded — as ``LEFT_UNROUTED`` by the
    engine that actually tried, which is where the rule count and the reason
    live.
    """
    if execution.conversation.status in _FINISHED:
        return _deny(
            Policy.ROUTING,
            PolicyReason.CONVERSATION_CLOSED,
            PolicySource.CONVERSATION_STATE,
        )
    return _allow(Policy.ROUTING, PolicyReason.PERMITTED, PolicySource.SERVICE_CONTEXT)


def _vip_queue_entry(execution: ExecutionContext) -> PolicyDecision:
    """May this conversation enter the VIP lane?"""
    if execution.is_priority:
        return _allow(
            Policy.VIP_QUEUE_ENTRY,
            PolicyReason.CUSTOMER_QUALIFIES,
            PolicySource.CUSTOMER_CONTEXT,
        )
    return _deny(
        Policy.VIP_QUEUE_ENTRY,
        PolicyReason.CUSTOMER_NOT_ELIGIBLE,
        PolicySource.CUSTOMER_CONTEXT,
    )


def _queue_bypass(execution: ExecutionContext) -> PolicyDecision:
    """May this conversation skip the queue entirely?

    Deliberately stricter than VIP entry. A VIP goes to the front of a lane;
    bypassing means never queuing at all, which contradicts the queue-first
    principle, so it is denied unless a service explicitly opts in.
    """
    service = execution.service
    if (
        service is not None
        and service.setting("routing", "allow_queue_bypass", default=False) is True
    ):
        if execution.is_priority:
            return _allow(
                Policy.QUEUE_BYPASS,
                PolicyReason.CUSTOMER_QUALIFIES,
                PolicySource.SERVICE_CONTEXT,
            )
        return _deny(
            Policy.QUEUE_BYPASS,
            PolicyReason.CUSTOMER_NOT_ELIGIBLE,
            PolicySource.CUSTOMER_CONTEXT,
        )
    return _deny(
        Policy.QUEUE_BYPASS,
        PolicyReason.SERVICE_DISABLED,
        PolicySource.PLATFORM_DEFAULT,
        note="the queue is the source of truth unless a service opts out",
    )


def _agent_pickup(execution: ExecutionContext) -> PolicyDecision:
    """May an agent take this conversation?"""
    if execution.conversation.status in _FINISHED:
        return _deny(
            Policy.AGENT_PICKUP,
            PolicyReason.CONVERSATION_CLOSED,
            PolicySource.CONVERSATION_STATE,
        )
    if execution.conversation.assigned_agent_id is not None:
        return _deny(
            Policy.AGENT_PICKUP,
            PolicyReason.ALREADY_ASSIGNED,
            PolicySource.CONVERSATION_STATE,
            assigned_to=str(execution.conversation.assigned_agent_id),
        )
    return _allow(Policy.AGENT_PICKUP, PolicyReason.PERMITTED, PolicySource.CONVERSATION_STATE)


def _ownership_continuation(execution: ExecutionContext) -> PolicyDecision:
    """May a previous agent keep this rather than it going back to the queue?

    The window and the previous owner are the ownership milestone's business.
    What is knowable here is whether the conversation is in a state where
    continuation is even meaningful.
    """
    if execution.conversation.status in _FINISHED:
        return _deny(
            Policy.OWNERSHIP_CONTINUATION,
            PolicyReason.CONVERSATION_CLOSED,
            PolicySource.CONVERSATION_STATE,
        )
    return _allow(
        Policy.OWNERSHIP_CONTINUATION,
        PolicyReason.NOT_YET_ENFORCED,
        PolicySource.PLATFORM_DEFAULT,
    )


def _memory_recording(execution: ExecutionContext) -> PolicyDecision:
    """May the platform remember anything from this conversation?

    **Fails closed**, like ``AI_ENGAGEMENT`` and for the same kind of
    reason. ``memory_enabled`` is a retention promise a company makes to
    its own customers and to its regulator, and a caller that forgot to
    populate capabilities must not thereby be granted permission to retain
    what somebody said. Refusing costs the platform a memory; the other
    direction costs the promise, and nothing would fail, no test would go
    red, and the company would be retaining data it told people it did not.

    Deliberately independent of ``AI_ENGAGEMENT``. Memory is a platform
    context consumed by Reporting, CRM, the Customer Timeline and
    Analytics as well as by AI, so gating it on the AI switch would mean
    turning AI off silently emptied the Customer Timeline — a consequence
    nobody flipping that switch is asking for.

    A customer who has asked for no automated messages is *not* refused
    here. That preference is about being contacted by a machine, not about
    the company keeping notes on its own relationship with them, and
    conflating the two would let a contact preference quietly delete a
    business record.
    """
    if execution.capabilities is None:
        return _deny(
            Policy.MEMORY_RECORDING,
            PolicyReason.CAPABILITIES_UNKNOWN,
            PolicySource.PLATFORM_DEFAULT,
        )
    if not execution.capabilities.memory_enabled:
        return _deny(
            Policy.MEMORY_RECORDING,
            PolicyReason.MEMORY_DISABLED,
            PolicySource.COMPANY_SETTINGS,
        )
    return _allow(Policy.MEMORY_RECORDING, PolicyReason.PERMITTED, PolicySource.COMPANY_SETTINGS)


def _knowledge_learning(execution: ExecutionContext) -> PolicyDecision:
    """May the platform learn from this conversation?

    **Fails closed**, like every rule here that governs a promise rather
    than a preference. A caller that did not populate capabilities must
    not thereby be granted permission to mine what somebody said.

    Learning is refused wherever memory is, because an observation is a
    weaker form of the same retention — but it can be refused on its own,
    which is the point. A company may accept the platform keeping notes on
    its relationships (Memory) while refusing to have those notes mined
    for patterns (Learning). Collapsing the two would force an
    all-or-nothing choice on exactly the regulated tenants who need the
    distinction most.
    """
    if execution.capabilities is None:
        return _deny(
            Policy.KNOWLEDGE_LEARNING,
            PolicyReason.CAPABILITIES_UNKNOWN,
            PolicySource.PLATFORM_DEFAULT,
        )
    if not execution.capabilities.memory_enabled:
        return _deny(
            Policy.KNOWLEDGE_LEARNING,
            PolicyReason.MEMORY_DISABLED,
            PolicySource.COMPANY_SETTINGS,
        )
    if not execution.capabilities.learning_enabled:
        return _deny(
            Policy.KNOWLEDGE_LEARNING,
            PolicyReason.LEARNING_DISABLED,
            PolicySource.COMPANY_SETTINGS,
        )
    return _allow(Policy.KNOWLEDGE_LEARNING, PolicyReason.PERMITTED, PolicySource.COMPANY_SETTINGS)


def _not_yet_enforced(policy: Policy) -> Callable[[ExecutionContext], PolicyDecision]:
    """A rule whose module has not shipped.

    Present rather than omitted, so a future module asks the engine instead
    of inventing its own answer — and honest about it, so the Inspector never
    shows a fabricated rationale.
    """

    def rule(execution: ExecutionContext) -> PolicyDecision:  # noqa: ARG001
        return _allow(policy, PolicyReason.NOT_YET_ENFORCED, PolicySource.PLATFORM_DEFAULT)

    return rule


class PolicyEngine:
    """The single place a business rule is answered.

    Constructed with the default rules; a rule can be replaced for a test or
    for an installation with genuinely different policy, which is the seam
    that keeps this from becoming a place people work around.
    """

    def __init__(
        self, rules: dict[Policy, Callable[[ExecutionContext], PolicyDecision]] | None = None
    ) -> None:
        self._rules: dict[Policy, Callable[[ExecutionContext], PolicyDecision]] = {
            Policy.AI_ENGAGEMENT: _ai_engagement,
            Policy.ROUTING: _routing,
            Policy.VIP_QUEUE_ENTRY: _vip_queue_entry,
            Policy.QUEUE_BYPASS: _queue_bypass,
            Policy.AGENT_PICKUP: _agent_pickup,
            Policy.OWNERSHIP_CONTINUATION: _ownership_continuation,
            Policy.SLA_PAUSE: _not_yet_enforced(Policy.SLA_PAUSE),
            Policy.AUTOMATION_EXECUTION: _not_yet_enforced(Policy.AUTOMATION_EXECUTION),
            Policy.AUTO_CLOSE: _not_yet_enforced(Policy.AUTO_CLOSE),
            Policy.MEMORY_RECORDING: _memory_recording,
            Policy.KNOWLEDGE_LEARNING: _knowledge_learning,
            **(rules or {}),
        }

    def evaluate(self, policy: Policy, execution: ExecutionContext) -> PolicyDecision:
        """Answer one policy for one execution.

        Every member of ``Policy`` has a rule — enforced by a test rather
        than by hope, because a policy with no rule would raise at the
        moment a module first asked it, which is the worst time to find out.
        """
        return self._rules[policy](execution)

    def evaluate_all(self, execution: ExecutionContext) -> dict[Policy, PolicyDecision]:
        """Every policy at once, for the Routing Inspector.

        The Inspector shows what the platform *would* allow right now, which
        is how somebody answers "why can't AI reply to this?" without
        reproducing the conditions that made it stop.
        """
        return {policy: rule(execution) for policy, rule in self._rules.items()}

    @property
    def policies(self) -> frozenset[Policy]:
        return frozenset(self._rules)


def as_routing_decision(decision: PolicyDecision) -> RoutingDecision:
    """A policy decision as a row in the routing decision log.

    Kept here rather than in ``routing_decisions`` so the log's shape and the
    policy vocabulary cannot drift apart: one module owns what a recorded
    evaluation looks like, and it is the one that owns the words.
    """
    return RoutingDecision(
        kind=RoutingDecisionKind.POLICY_EVALUATED,
        outcome=(
            RoutingDecisionOutcome.ALLOWED if decision.allowed else RoutingDecisionOutcome.DENIED
        ),
        reason=(
            RoutingDecisionReason.POLICY_ALLOWED
            if decision.allowed
            else RoutingDecisionReason.POLICY_DENIED
        ),
        policy=PolicyEvaluation(
            policy=decision.policy.value,
            effect=decision.effect.value,
            reason=decision.reason.value,
            source=decision.source.value,
            text=REASON_TEXT[decision.reason],
        ),
    )


__all__ = [
    "REASON_TEXT",
    "Effect",
    "Policy",
    "PolicyDecision",
    "PolicyEngine",
    "PolicyReason",
    "PolicySource",
    "as_routing_decision",
]
