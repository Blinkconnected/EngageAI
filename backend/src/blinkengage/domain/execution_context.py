"""The ExecutionContext: the one argument every module takes.

Routing, SLA, AI, automation, knowledge, reporting, billing analytics and
whatever ships next all need to know the same three things — how the business
behaves for this conversation, how this customer is treated, and what is true
of the conversation right now. Before this type existed each of them fetched
those separately, which meant each of them could fetch something *different*,
and two modules disagreeing about a customer's tier is a bug that only appears
under the timing nobody reproduces.

So there is one object, assembled once at the top of an execution and passed
down. A module that receives it cannot look anything up again, because it holds
no ids to look up with — only resolved contexts. That is the point.

**Two immutable contexts, one mutable snapshot.** The service and customer
contexts are frozen versions bound to the conversation: they do not change
while it runs, and a configuration edit tomorrow does not reach backwards. The
conversation metadata is different in kind — status, assignment and counts move
constantly — so it is a *snapshot taken at the start of this execution*, and it
is honest about that rather than pretending to be immutable state.

The distinction matters at the call site. A module reading
``execution.service.sla.first_response_minutes`` is reading a decision that was
made when the conversation began and cannot move under it. A module reading
``execution.conversation.status`` is reading what was true a moment ago. Both
are correct; conflating them is how a system starts making decisions on stale
state without anybody noticing which half was stale.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from blinkengage.domain.customer_context import CustomerContext
from blinkengage.domain.service_context import ServiceContext


@dataclass(frozen=True, slots=True)
class ConversationFacts:
    """What is true of this conversation at the moment execution began.

    A snapshot, deliberately — see the module docstring. It is not a version
    and makes no claim to be stable; it exists so every module in one
    execution reasons about the *same* moment rather than each re-reading a
    row that is moving.
    """

    conversation_id: uuid.UUID
    company_id: uuid.UUID
    channel_type: str
    started_at: datetime
    #: As of this execution. Named ``status`` rather than ``state`` to match
    #: the column it came from.
    status: str
    #: ``None`` while the conversation is still waiting in a queue — which
    #: is the normal case for everything routing does, not an edge case.
    assigned_agent_id: uuid.UUID | None = None
    #: The logical queue it is waiting in, and the runtime lane within it.
    logical_queue_id: uuid.UUID | None = None
    runtime_queue_id: uuid.UUID | None = None
    #: When this snapshot was taken. Present so a module that logs a
    #: decision can say what it was looking at, and so two executions can be
    #: told apart in a trace.
    observed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CompanyCapabilities:
    """Company-wide switches that no service or customer may override.

    The fourth member of an execution, and the one with a hard reason to
    exist: some rules are not decided by the service or the customer at all.
    ``ai_enabled`` is the master switch a compliance officer reaches for to
    guarantee no AI-generated content reaches customers. It is not a routing
    preference — it is a promise the company has made, and neither a service
    configured for AI nor a customer happy to receive it may override it.

    Every field defaults to the *unavailable* answer. A caller that forgets
    to populate this gets a refusal, not an unintended AI reply — see
    ``_ai_engagement`` for why that direction is the only safe one.
    """

    #: The company-wide "Enable AI features" switch.
    ai_enabled: bool = False
    #: Whether a provider is actually configured and reachable. Distinct from
    #: the switch above: "turned off" and "turned on but never set up" are
    #: different problems with different fixes.
    ai_provider_configured: bool = False
    #: Whether the platform may retain memory for this company. A
    #: retention promise rather than a feature toggle, and deliberately
    #: independent of `ai_enabled`: Memory is a platform context consumed
    #: by Reporting, CRM and the Customer Timeline as well as by AI, so a
    #: company turning AI off is not thereby asking for its Customer
    #: Timeline to empty. Defaults to the unavailable answer like every
    #: field here.
    memory_enabled: bool = False
    #: Autopilot's own opt-in, separate from AI features generally — a
    #: company may want agent-facing suggestions without AI answering
    #: customers directly.
    autopilot_enabled: bool = False
    #: The "new conversation" activation mode. A company may run Autopilot
    #: on SLA triggers and agent requests *only*, leaving brand-new
    #: conversations to a human — so this is a separate switch from
    #: ``autopilot_enabled`` rather than folded into it.
    autopilot_on_new_conversation: bool = False

    # There is deliberately no ``automation_enabled``. No such company-level
    # switch exists today, and a capability with nothing behind it makes a
    # policy look enforced when it is not — the same fiction as a fabricated
    # reason. It gets added when the setting does.

    @property
    def ai_is_usable(self) -> bool:
        return self.ai_enabled and self.ai_provider_configured


#: What the engine assumes when an execution carries no capabilities: nothing
#: is available. Named so the refusal reads as a deliberate default rather
#: than an accident.
NOTHING_AVAILABLE = CompanyCapabilities()


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Everything a module is allowed to need, resolved once.

    The single operational contract inside Blink Engage. A new module should
    take this and nothing else; if it needs something this does not carry,
    the answer is to add it here — deliberately, where every module sees the
    same value — rather than to open a repository in the corner of a service
    and read a second version of the truth.
    """

    service: ServiceContext
    #: ``None`` for a conversation from somebody the platform has never seen:
    #: a first message on an anonymous web-chat, an unrecognised number. A
    #: real and common case, so every reader must handle it, and the
    #: convenience properties below all answer sensibly without it.
    customer: CustomerContext | None
    conversation: ConversationFacts

    #: Company-wide switches. ``None`` means the caller did not say, which
    #: every policy treats as *nothing is available* rather than guessing —
    #: the alternative is a forgotten field turning a compliance kill switch
    #: back on by omission.
    capabilities: CompanyCapabilities | None = None

    #: Anything an execution wants to hand downstream that is neither
    #: configuration nor conversation state — a correlation id, a trace
    #: handle, a dry-run flag. Not a place for business data: if two modules
    #: need to agree on something, it belongs in a context.
    execution: dict[str, Any] = field(default_factory=dict)

    @property
    def company_id(self) -> uuid.UUID:
        return self.conversation.company_id

    @property
    def available(self) -> CompanyCapabilities:
        """The company's switches, or nothing-available if none were given."""
        return self.capabilities or NOTHING_AVAILABLE

    @property
    def is_priority(self) -> bool:
        """Whether the customer's standing puts them ahead of the queue.

        A *derived fact*, not a decision — the distinction matters now that
        the Policy Engine exists. This says what is true of the customer; it
        does not say what the platform may do about it. A module wanting the
        latter asks ``Policy.VIP_QUEUE_ENTRY`` or ``Policy.QUEUE_BYPASS``,
        which are two different answers built on this one fact.

        An unknown customer is not priority — the honest default, since the
        alternative is treating every stranger as a named account.
        """
        return self.customer is not None and self.customer.deserves_priority

    @property
    def language(self) -> str | None:
        """The customer's language, where one is known.

        ``None`` means undetected rather than English. A module that needs a
        concrete language substitutes its own default and can say that it
        did; one handed a wrong language cannot.
        """
        return self.customer.language if self.customer else None

    # There is deliberately no ``ai_may_engage`` here, and there was until the
    # Policy Engine existed. "May AI act?" is a business rule, and a business
    # rule answered on this object is one the AI module reads, the automation
    # module forgets, and a third module reimplements slightly differently.
    # Ask ``PolicyEngine.evaluate(Policy.AI_ENGAGEMENT, execution)`` instead:
    # it answers with a reason and a source rather than a bare boolean, which
    # is what makes a refusal explainable in the Routing Inspector.

    def describe(self) -> str:
        """One line for a log or a trace. Never for a customer to read."""
        customer = self.customer.display_name if self.customer else "an unknown customer"
        return (
            f"{self.service.name} v{self.service.version} · {customer} · "
            f"conversation {self.conversation.conversation_id} ({self.conversation.status})"
        )


__all__ = ["ConversationFacts", "ExecutionContext"]
