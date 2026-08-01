"""Deciding which Service a conversation belongs to — as a pipeline, not a guess.

A Service is the business object a customer recognises: Sales, Billing,
Technical Support. Which one a conversation belongs to is a question with many
possible answers — the customer picked one from a menu, an AI classified the
text, a VIP rule overrode everything, an external system said so, or nothing
matched and a fallback caught it.

**Resolution is separated from selection, deliberately.** The routing engine
receives a resolved Service and is structurally incapable of knowing how it was
resolved: nothing in its signature carries the strategy. That separation is
what lets a company change how services are chosen — turn AI classification on,
put an API override in front of it, add a custom strategy next year — without
the routing engine changing at all. The business model stays stable while the
way into it evolves.

**It is a pipeline, not a single decision.** Modelling it as one decision was
the obvious design and it is wrong, because the interesting information is in
the stages that *did not* resolve. "AI classified this at 0.68, below the 0.75
threshold, so the customer was asked" is the sentence an administrator needs,
and a single-decision model throws away everything except the winner. So every
stage records its own outcome, including the ones that skipped, and the
Routing Inspector replays the whole journey.

The four outcomes are distinct on purpose:

- ``RESOLVED`` — this stage knows the answer. The pipeline stops.
- ``CONTINUE`` — this stage ran, had no opinion, and the next stage should try.
- ``SKIPPED`` — this stage did not run at all: not configured, disabled, or its
  precondition was unmet. Different from ``CONTINUE`` because the fix is
  different. "AI had no confident answer" and "AI is switched off" look
  identical on a screen that conflates them, and only one of them is a
  configuration problem.
- ``REJECTED`` — this stage says the conversation must not be routed by this
  pipeline at all, and the ones after it do not get a turn. Reserved for
  deliberate refusals rather than for failures; a stage that errors is
  ``SKIPPED`` with a reason, because a broken strategy must never silently
  swallow a customer's message.

Framework-free, like the rest of ``domain/``. Nothing here reads a database or
calls an AI provider — a stage is handed what it needs and returns what it
concluded, which is what makes the pipeline testable without any of them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Protocol


class ResolutionStrategy(StrEnum):
    """How a stage decides. Open to extension by design.

    A company chooses which of these run and in what order. The set is a
    closed enum rather than free text because a console has to render each
    one's configuration form, and it cannot do that for a name it has never
    heard of — but adding a member is additive, and the pipeline itself has
    no opinion about which members exist.
    """

    #: A rule marked this customer or conversation as taking precedence over
    #: everything else — a named account, a support contract, an escalation.
    #: First in the default order because an override that runs late is not
    #: an override.
    VIP_RULE = "vip_rule"
    #: An external system was asked and its answer wins. For installations
    #: where the CRM, not Blink Engage, owns the routing decision.
    EXTERNAL_API = "external_api"
    #: The customer chose from the Service Directory themselves. The most
    #: trustworthy signal there is: they know what they want better than a
    #: classifier does.
    CUSTOMER_SELECTION = "customer_selection"
    #: A chatbot flow determined it from a conversation with the customer.
    CHATBOT_FLOW = "chatbot_flow"
    #: An AI classified the message text. Carries a confidence, and resolves
    #: only above the configured threshold — below it the stage continues so
    #: something later can ask the customer directly.
    AI_CLASSIFICATION = "ai_classification"
    #: Ordinary business rules — channel, keyword, customer attribute.
    BUSINESS_RULES = "business_rules"
    #: Always resolves, to one configured Service. Last in the order, and the
    #: reason a conversation is never left with no service at all.
    FIXED_SERVICE = "fixed_service"


class StageOutcome(StrEnum):
    """What one stage concluded. See the module docstring for why four."""

    RESOLVED = "resolved"
    CONTINUE = "continue"
    SKIPPED = "skipped"
    REJECTED = "rejected"


class StageReason(StrEnum):
    """Why a stage concluded what it did — a closed set, not prose.

    The Routing Inspector groups, filters and colours by these, and an
    administrator asks "show me everything AI declined to classify". Neither
    is possible against a sentence. The human wording lives in
    ``STAGE_REASON_TEXT`` so a caller that only shows text loses nothing.
    """

    # --- resolved --------------------------------------------------------
    #: The customer picked this service themselves.
    CUSTOMER_CHOSE = "customer_chose"
    #: A classifier was confident enough to decide.
    CONFIDENT_CLASSIFICATION = "confident_classification"
    #: A rule matched and named a service.
    RULE_MATCHED = "rule_matched"
    #: An external system returned a service.
    EXTERNAL_ANSWER = "external_answer"
    #: The stage always resolves to the same service.
    FIXED = "fixed"
    #: Nothing earlier resolved, so the fallback caught it.
    FALLBACK = "fallback"

    # --- continue --------------------------------------------------------
    #: The classifier answered, but below the configured threshold. The
    #: single most useful reason in this enum: it is the difference between
    #: "AI was wrong" and "AI knew it was unsure".
    BELOW_CONFIDENCE_THRESHOLD = "below_confidence_threshold"
    #: The stage ran and nothing matched.
    NO_MATCH = "no_match"
    #: The customer was offered the directory and has not answered yet.
    AWAITING_CUSTOMER_CHOICE = "awaiting_customer_choice"

    # --- skipped ---------------------------------------------------------
    #: The stage is not switched on for this company.
    NOT_CONFIGURED = "not_configured"
    #: Switched on, but its preconditions were not met — no message text to
    #: classify, no customer record to check, no channel that can show a menu.
    PRECONDITION_UNMET = "precondition_unmet"
    #: The stage failed. Recorded as skipped rather than rejected, because a
    #: broken strategy must never swallow a customer's message: the pipeline
    #: carries on and something later resolves it.
    STRATEGY_FAILED = "strategy_failed"
    #: The stage named a service that no longer exists or is inactive. The
    #: pipeline continues rather than routing into a deleted service.
    SERVICE_UNAVAILABLE = "service_unavailable"

    # --- rejected --------------------------------------------------------
    #: A deliberate refusal — this conversation is not for this pipeline.
    REFUSED_BY_RULE = "refused_by_rule"


STAGE_REASON_TEXT: dict[StageReason, str] = {
    StageReason.CUSTOMER_CHOSE: "the customer chose it",
    StageReason.CONFIDENT_CLASSIFICATION: "the classifier was confident",
    StageReason.RULE_MATCHED: "a rule matched",
    StageReason.EXTERNAL_ANSWER: "an external system answered",
    StageReason.FIXED: "this stage always resolves to one service",
    StageReason.FALLBACK: "nothing else resolved, so the fallback applied",
    StageReason.BELOW_CONFIDENCE_THRESHOLD: "the classifier was not confident enough",
    StageReason.NO_MATCH: "nothing matched",
    StageReason.AWAITING_CUSTOMER_CHOICE: "the customer has not chosen yet",
    StageReason.NOT_CONFIGURED: "it is not configured",
    StageReason.PRECONDITION_UNMET: "its preconditions were not met",
    StageReason.STRATEGY_FAILED: "it failed",
    StageReason.SERVICE_UNAVAILABLE: "the service it named is unavailable",
    StageReason.REFUSED_BY_RULE: "a rule refused it",
}


@dataclass(frozen=True, slots=True)
class StageResult:
    """What one stage of the pipeline concluded.

    ``service_id`` is set only when ``outcome`` is ``RESOLVED``; the
    constructor enforces it, because a stage that reports a service *and*
    says it did not resolve is a bug that would otherwise be discovered by
    a conversation going somewhere nobody chose.
    """

    strategy: ResolutionStrategy
    outcome: StageOutcome
    reason: StageReason
    service_id: uuid.UUID | None = None
    #: Only meaningful for a classifier. Kept as ``Decimal`` rather than
    #: ``float``: it is compared against a configured threshold, and two
    #: values that differ in the last binary place must not straddle it.
    confidence: Decimal | None = None
    #: Whatever the stage wants a reader to see — the alternatives a
    #: classifier weighed, the rule it matched, the endpoint it called.
    #: Never the customer's message text: a routing decision does not need
    #: it, and an append-only log is the wrong place to copy it into.
    evidence: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        resolved = self.outcome is StageOutcome.RESOLVED
        if resolved and self.service_id is None:
            raise ValueError(f"{self.strategy} resolved without naming a service")
        if not resolved and self.service_id is not None:
            raise ValueError(
                f"{self.strategy} named a service but reported {self.outcome}; "
                "a stage that has an answer must say it resolved"
            )

    @property
    def sentence(self) -> str:
        """How this stage reads in the Routing Inspector."""
        what = self.strategy.value.replace("_", " ").capitalize()
        why = STAGE_REASON_TEXT[self.reason]
        if self.outcome is StageOutcome.RESOLVED:
            return f"{what}: resolved because {why}."
        if self.confidence is not None:
            return f"{what}: {self.outcome.value} — {why} ({self.confidence})."
        return f"{what}: {self.outcome.value} — {why}."


@dataclass(frozen=True, slots=True)
class ResolvedService:
    """The pipeline's answer, and the whole journey that produced it.

    ``service_id`` is ``None`` when every stage declined — which is a real
    outcome and not an error, and is why a company that wants routing to
    always succeed configures a fixed fallback stage last.

    ``stages`` holds **every** stage that ran, in order, including the ones
    that skipped. That list is the Routing Inspector's narrative, and it is
    the reason this type exists instead of returning a bare service id.
    """

    service_id: uuid.UUID | None
    stages: tuple[StageResult, ...]

    @property
    def resolved(self) -> bool:
        return self.service_id is not None

    @property
    def deciding_stage(self) -> StageResult | None:
        """The stage that actually answered, if any."""
        for stage in self.stages:
            if stage.outcome is StageOutcome.RESOLVED:
                return stage
        return None

    @property
    def rejected(self) -> bool:
        return any(stage.outcome is StageOutcome.REJECTED for stage in self.stages)


class ResolutionStage(Protocol):
    """One strategy's implementation.

    A Protocol rather than a base class so a strategy can live anywhere —
    including in a module that knows about AI providers or HTTP clients,
    neither of which belongs in ``domain/``. "Future Custom Strategies"
    means exactly this: something that satisfies this shape and is added to
    the configured order.
    """

    @property
    def strategy(self) -> ResolutionStrategy: ...

    async def resolve(self, request: ResolutionRequest) -> StageResult: ...


@dataclass(frozen=True, slots=True)
class ResolutionRequest:
    """Everything a stage is allowed to look at.

    Deliberately narrow. A stage gets the conversation's identity, the
    channel it arrived on, the text if there is any, and the customer — and
    nothing else. Widening this is how a resolution strategy grows a
    dependency on the whole database and stops being testable.
    """

    company_id: uuid.UUID
    conversation_id: uuid.UUID
    channel_type: str
    #: ``None`` for a conversation opened without text — a customer who
    #: tapped a button, or a media-only first message. Stages that need text
    #: report ``PRECONDITION_UNMET`` rather than treating absence as a miss.
    body: str | None
    customer_id: uuid.UUID | None
    #: What the customer picked from the directory, if the channel offered
    #: one and they answered.
    customer_selected_service_id: uuid.UUID | None = None


async def resolve_service(
    stages: tuple[ResolutionStage, ...], request: ResolutionRequest
) -> ResolvedService:
    """Runs the pipeline in order and stops at the first stage that answers.

    Every stage's result is kept, not only the winner — see the module
    docstring. A stage that raises is recorded as ``STRATEGY_FAILED`` and the
    pipeline carries on: an exception inside a classifier must not be the
    reason a customer's message goes nowhere, and a stage that failed
    silently would be indistinguishable from one that had no opinion.
    """
    results: list[StageResult] = []
    for stage in stages:
        try:
            result = await stage.resolve(request)
        except Exception as error:  # noqa: BLE001 — see the docstring.
            results.append(
                StageResult(
                    strategy=stage.strategy,
                    outcome=StageOutcome.SKIPPED,
                    reason=StageReason.STRATEGY_FAILED,
                    evidence={"error": str(error)[:500]},
                )
            )
            continue

        results.append(result)
        if result.outcome is StageOutcome.RESOLVED:
            return ResolvedService(service_id=result.service_id, stages=tuple(results))
        if result.outcome is StageOutcome.REJECTED:
            return ResolvedService(service_id=None, stages=tuple(results))

    return ResolvedService(service_id=None, stages=tuple(results))


#: The order stages run in when a company has expressed no preference.
#: An override that runs after a classifier is not an override, and a
#: fallback that runs before anything else is not a fallback — so the two
#: ends of this list are load-bearing rather than arbitrary.
DEFAULT_STAGE_ORDER: tuple[ResolutionStrategy, ...] = (
    ResolutionStrategy.VIP_RULE,
    ResolutionStrategy.EXTERNAL_API,
    ResolutionStrategy.CUSTOMER_SELECTION,
    ResolutionStrategy.CHATBOT_FLOW,
    ResolutionStrategy.AI_CLASSIFICATION,
    ResolutionStrategy.BUSINESS_RULES,
    ResolutionStrategy.FIXED_SERVICE,
)


__all__ = [
    "DEFAULT_STAGE_ORDER",
    "STAGE_REASON_TEXT",
    "ResolutionRequest",
    "ResolutionStage",
    "ResolutionStrategy",
    "ResolvedService",
    "StageOutcome",
    "StageReason",
    "StageResult",
    "resolve_service",
]
