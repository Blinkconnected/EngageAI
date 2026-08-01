"""The resolution strategies that can run today.

See ``docs/architecture/routing-rules.md``.

``domain/service_resolution.py`` defines the pipeline and what a stage must
look like. These are the implementations that read the database — which is
why they live here and not in ``domain/``: a strategy that needs a repository
is not framework-free, and pretending otherwise would drag SQLAlchemy into
the one package that is deliberately without it.

Four strategies, in the order they are useful:

- **customer selection** — the customer told us, and nothing should
  second-guess that;
- **business rules** — a company's own conditions on channel and keywords;
- **fixed service** — the company has one service, or has nominated a
  default;
- **fallback** — the last stage, so a conversation always lands somewhere.

AI classification is deliberately absent. It belongs with the AI queue worker,
and a stage that guessed without a model would be a guess wearing a
classifier's name.

Every stage answers with a ``StageResult`` carrying evidence — what it looked
at, and what it found. That evidence is what the Routing Inspector shows, and
it is the reason a stage that resolves nothing is still worth running.
"""

import re
import uuid
from typing import Any

from blinkengage.domain.service_resolution import (
    ResolutionRequest,
    ResolutionStage,
    ResolutionStrategy,
    StageOutcome,
    StageReason,
    StageResult,
)
from blinkengage.infrastructure.repositories.service_directory_repository import (
    ServiceRepository,
)


class CustomerSelectionStage:
    """The customer picked a service from the directory.

    First in the order, and it has to be: a customer who chose "Billing" has
    stated what they want, and a classifier overriding that would be the
    platform telling somebody they are wrong about their own problem.

    Also the cheapest stage — one comparison, no query — so putting it first
    costs nothing even when it does not apply.
    """

    strategy = ResolutionStrategy.CUSTOMER_SELECTION

    def __init__(self, services: ServiceRepository) -> None:
        self._services = services

    async def resolve(self, request: ResolutionRequest) -> StageResult:
        chosen = request.customer_selected_service_id
        if chosen is None:
            # Not "no match": nothing was asked. A conversation that never
            # offered a menu has not had a customer decline to use it.
            return StageResult(
                strategy=self.strategy,
                outcome=StageOutcome.SKIPPED,
                reason=StageReason.PRECONDITION_UNMET,
                evidence={"note": "no service was selected on this conversation"},
            )

        service = await self._services.get(chosen)
        if service is None or service.deleted_at is not None or not service.is_active:
            # A selection pointing at a service that has since been switched
            # off. Continue rather than reject: the customer's intent is not
            # actionable, but somebody still needs answering.
            return StageResult(
                strategy=self.strategy,
                outcome=StageOutcome.CONTINUE,
                reason=StageReason.NO_MATCH,
                evidence={"selected_service_id": str(chosen), "note": "service unavailable"},
            )

        if service.company_id != request.company_id:
            # A selection naming another company's service. Recorded, not
            # silently dropped: it means something upstream is wrong.
            return StageResult(
                strategy=self.strategy,
                outcome=StageOutcome.CONTINUE,
                reason=StageReason.NO_MATCH,
                evidence={
                    "selected_service_id": str(chosen),
                    "note": "service belongs to another company",
                },
            )

        return StageResult(
            strategy=self.strategy,
            outcome=StageOutcome.RESOLVED,
            reason=StageReason.CUSTOMER_CHOSE,
            service_id=service.id,
            evidence={"service": service.name},
        )


#: One company's routing conditions, stored on the service version's
#: ``extras`` under this namespace. A separate table would be the tidier
#: answer eventually; today a rule is read only during resolution, always
#: whole, and never queried across services — which is exactly the shape
#: ``extras`` exists for.
RULES_NAMESPACE = "resolution_rules"


class BusinessRulesStage:
    """A company's own conditions: channel, and keywords in the first message.

    Deliberately not a general expression language. Two conditions cover what
    companies actually ask for — "WhatsApp goes to Sales", "anything saying
    'invoice' goes to Billing" — and every condition added here is one an
    administrator has to understand before they can trust the routing.

    Rules are evaluated in the order an operator wrote them, and the first
    match wins. Order is the only priority mechanism, because a separate
    priority number that disagrees with the visible order is a bug report
    waiting to happen.
    """

    strategy = ResolutionStrategy.BUSINESS_RULES

    def __init__(self, services: ServiceRepository) -> None:
        self._services = services

    async def resolve(self, request: ResolutionRequest) -> StageResult:
        services = await self._services.active_for_company(request.company_id)
        rules = await self._rules_for(services)
        if not rules:
            return StageResult(
                strategy=self.strategy,
                outcome=StageOutcome.SKIPPED,
                reason=StageReason.NOT_CONFIGURED,
                evidence={"note": "no service defines routing rules"},
            )

        body = (request.body or "").lower()
        for service_id, service_name, rule in rules:
            channels = [str(c).lower() for c in rule.get("channels", []) or []]
            if channels and request.channel_type.lower() not in channels:
                continue

            keywords = [str(k).lower().strip() for k in rule.get("keywords", []) or []]
            keywords = [k for k in keywords if k]
            if keywords:
                if not body:
                    # A keyword rule against a message with no text. Not a
                    # miss — there was nothing to match against — so it is
                    # skipped silently rather than counted as "no match".
                    continue
                matched = next((k for k in keywords if _contains_word(body, k)), None)
                if matched is None:
                    continue
                return StageResult(
                    strategy=self.strategy,
                    outcome=StageOutcome.RESOLVED,
                    reason=StageReason.RULE_MATCHED,
                    service_id=service_id,
                    evidence={"service": service_name, "matched_keyword": matched},
                )

            if channels:
                return StageResult(
                    strategy=self.strategy,
                    outcome=StageOutcome.RESOLVED,
                    reason=StageReason.RULE_MATCHED,
                    service_id=service_id,
                    evidence={"service": service_name, "matched_channel": request.channel_type},
                )

        return StageResult(
            strategy=self.strategy,
            outcome=StageOutcome.CONTINUE,
            reason=StageReason.NO_MATCH,
            evidence={"rules_evaluated": len(rules)},
        )

    async def _rules_for(
        self, services: list[Any]
    ) -> list[tuple[uuid.UUID, str, dict[str, Any]]]:
        """Every active service's rules, in the operator's chosen order.

        Read from each service's *current* version. A rule is configuration
        for what happens next, not a record of what already happened, so
        unlike an SLA target it is correct to read the newest one.
        """
        rules: list[tuple[uuid.UUID, str, dict[str, Any]]] = []
        for service in services:
            context = await self._services.current_context(service.id)
            if context is None:
                continue
            defined = context.setting(RULES_NAMESPACE, "rules", default=[])
            if not isinstance(defined, list):
                # Stored JSON is not typed. A malformed rule set must not
                # take routing down for the whole company.
                continue
            for rule in defined:
                if isinstance(rule, dict):
                    rules.append((service.id, context.name, rule))
        return rules


def _contains_word(body: str, keyword: str) -> bool:
    """Whether ``keyword`` appears in ``body`` as a word, not a fragment.

    Substring matching would route every message containing "invoiced",
    "invoices" — fine — but also send "I can't access my account" to a
    service keyed on "count". Word boundaries make the rule mean what an
    administrator reading it thinks it means.

    Multi-word keywords are matched as a phrase, which is what somebody
    typing "payment failed" intends.
    """
    return re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", body) is not None


class FixedServiceStage:
    """Always resolves to one nominated service.

    Two jobs. It is how a company with a single service routes at all —
    the overwhelmingly common case at signup, where a directory with one
    entry should never be shown to a customer as a choice. And it is how a
    company nominates a default without making it a "fallback", which is a
    word that implies something went wrong.
    """

    strategy = ResolutionStrategy.FIXED_SERVICE

    def __init__(self, services: ServiceRepository, *, service_id: uuid.UUID | None = None) -> None:
        self._services = services
        self._service_id = service_id

    async def resolve(self, request: ResolutionRequest) -> StageResult:
        if self._service_id is not None:
            service = await self._services.get(self._service_id)
            if service is None or not service.is_active or service.deleted_at is not None:
                return StageResult(
                    strategy=self.strategy,
                    outcome=StageOutcome.SKIPPED,
                    reason=StageReason.PRECONDITION_UNMET,
                    evidence={"note": "the nominated service is unavailable"},
                )
            return StageResult(
                strategy=self.strategy,
                outcome=StageOutcome.RESOLVED,
                reason=StageReason.FIXED,
                service_id=service.id,
                evidence={"service": service.name},
            )

        active = await self._services.active_for_company(request.company_id)
        if len(active) != 1:
            # Ambiguous by definition. With none there is nothing to pick;
            # with several, picking one would be a guess presented as a
            # decision.
            return StageResult(
                strategy=self.strategy,
                outcome=StageOutcome.SKIPPED,
                reason=StageReason.PRECONDITION_UNMET,
                evidence={"active_services": len(active)},
            )

        only = active[0]
        return StageResult(
            strategy=self.strategy,
            outcome=StageOutcome.RESOLVED,
            reason=StageReason.FIXED,
            service_id=only.id,
            evidence={"service": only.name, "note": "the company's only active service"},
        )


class FallbackStage:
    """The last stage. Catches everything nothing else claimed.

    A conversation that resolves to no service has no SLA, no queue and no
    owner — it is a customer waiting in a room the platform does not know
    exists. So the pipeline ends here, and this stage resolves whenever it
    possibly can.

    It answers ``FALLBACK`` rather than ``FIXED`` even when it picks the same
    service a fixed stage would, because the two mean different things to
    somebody reading the Inspector: one is a decision, the other is nothing
    having decided.
    """

    strategy = ResolutionStrategy.FIXED_SERVICE

    def __init__(self, services: ServiceRepository, *, service_id: uuid.UUID | None = None) -> None:
        self._services = services
        self._service_id = service_id

    async def resolve(self, request: ResolutionRequest) -> StageResult:
        if self._service_id is not None:
            service = await self._services.get(self._service_id)
            if service is not None and service.is_active and service.deleted_at is None:
                return StageResult(
                    strategy=self.strategy,
                    outcome=StageOutcome.RESOLVED,
                    reason=StageReason.FALLBACK,
                    service_id=service.id,
                    evidence={"service": service.name, "note": "company default"},
                )

        active = await self._services.active_for_company(request.company_id)
        if not active:
            # A company with no services at all. Answered honestly rather
            # than invented: the conversation is handled the way it was
            # before services existed, and the Inspector says why.
            return StageResult(
                strategy=self.strategy,
                outcome=StageOutcome.CONTINUE,
                reason=StageReason.NOT_CONFIGURED,
                evidence={"note": "this company has no active services"},
            )

        # The first in the operator's own display order. Not alphabetical
        # and not the oldest: the order they arranged the directory in is
        # the closest thing to a stated preference.
        first = active[0]
        return StageResult(
            strategy=self.strategy,
            outcome=StageOutcome.RESOLVED,
            reason=StageReason.FALLBACK,
            service_id=first.id,
            evidence={"service": first.name, "note": "first service in the directory"},
        )


def default_stages(
    services: ServiceRepository, *, default_service_id: uuid.UUID | None = None
) -> tuple[ResolutionStage, ...]:
    """The pipeline as it runs today.

    Order matters and is stated once, here, rather than assembled at three
    call sites that could disagree. AI classification slots in between rules
    and fixed when the AI queue worker lands.
    """
    return (
        CustomerSelectionStage(services),
        BusinessRulesStage(services),
        FixedServiceStage(services),
        FallbackStage(services, service_id=default_service_id),
    )


__all__ = [
    "RULES_NAMESPACE",
    "BusinessRulesStage",
    "CustomerSelectionStage",
    "FallbackStage",
    "FixedServiceStage",
    "default_stages",
]
