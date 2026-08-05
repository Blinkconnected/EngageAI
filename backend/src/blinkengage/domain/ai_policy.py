"""What AI is allowed to do here, resolved down the configuration chain.

See ``docs/architecture/ai-eligibility-model.md`` and
``docs/architecture/service-centric-migration.md``.

Every AI fact used to resolve differently. The confidence threshold had a
service→company resolver; the pickup delay had a hard-coded ``0`` for any
company without a service directory; whether AI may engage at all was a Policy
Engine evaluation on one path and five inline conditions on the other, and the
inline path recorded nothing. Three answers to *"what does this company's AI
configuration say"*, and the one a reader found first was whichever module they
opened.

This is the one answer. Framework-free, like the rest of ``domain/``: it takes
the tiers as values and returns what applies plus which tier said so.

**The company switch is a kill switch, not a tier.** A service cannot turn AI
on for a company that has switched it off — a compliance officer must not have
to visit every service to make a promise stick. So ``enabled`` is an AND across
tiers rather than a first-non-null lookup, which is why it does not use
``resolve_first``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from blinkengage.domain.company_settings import DEFAULT_AUTOPILOT_CONFIDENCE_THRESHOLD
from blinkengage.domain.resolution import ConfigurationSource, Resolved, resolve_first
from blinkengage.domain.service_context import AiPolicy

#: What the platform is willing to decide about AI when nobody else has.
#:
#: Deliberately the *permissive* delay — zero — and the *restrictive* engage
#: — off. The two look inconsistent and are not: the platform will never make
#: AI speak for a company that has not asked, and it will not impose a wait
#: nobody configured either.
#:
#: The reasoning on the delay is the same one ``PLATFORM_DEFAULT_SLA_TARGETS``
#: gives for leaving ``queue_minutes`` unmeasured: *how long a conversation may
#: sit before somebody accepts it is an operational promise a business makes,
#: not one the platform may make for it.* A thirty-second wait is a real
#: decision about giving humans first refusal, and it belongs to a Service —
#: which defaults to exactly that (``AiPolicy.pickup_delay_seconds``) the
#: moment a company defines one.
PLATFORM_DEFAULT_PICKUP_DELAY_SECONDS: Final[int] = 0

#: Long enough that AI does not talk over an agent who is simply typing. Only
#: consulted once the resume behaviour exists; carried here so the tier is
#: defined in one place rather than invented at the call site later.
PLATFORM_DEFAULT_RESUME_DELAY_SECONDS: Final[int] = 900

#: The platform's own confidence bar, used only when neither the service nor
#: the company states one.
#:
#: **Derived from the existing constant rather than restated.** Writing the
#: number here would have created a second platform default — this module
#: first said ``0.75`` where ``company_settings`` has always said ``0.7``, and
#: the two would have disagreed the moment a company relied on the fallback.
#: That is precisely the divergence this whole resolution chain exists to
#: remove, so the chain must not introduce one of its own.
PLATFORM_DEFAULT_CONFIDENCE_THRESHOLD: Final[Decimal] = Decimal(
    str(DEFAULT_AUTOPILOT_CONFIDENCE_THRESHOLD)
)

#: How stale a customer's last message may be and still be worth an automated
#: answer. Inside business hours a human is expected, so the window is short;
#: outside them nobody is coming, so a message from the night is still worth
#: answering in the morning. See ``ai-eligibility-model.md`` §12.
PLATFORM_DEFAULT_ACTIVITY_WINDOW_SECONDS: Final[int] = 60 * 60
PLATFORM_DEFAULT_OUT_OF_HOURS_ACTIVITY_WINDOW_SECONDS: Final[int] = 12 * 60 * 60


@dataclass(frozen=True, slots=True)
class CompanyAiSettings:
    """The company tier, as values.

    A plain record rather than the settings dict, so this module never learns
    the shape of ``Company.settings`` and the readers in
    ``domain/company_settings.py`` stay the only thing that does.
    """

    enabled: bool
    autopilot_enabled: bool
    confidence_threshold: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ResolvedAiPolicy:
    """The AI *settings* that apply here, with the tier behind each answer.

    **Deliberately no ``enabled``.** Whether AI may act is
    ``Policy.AI_ENGAGEMENT``'s decision and nobody else's — policies decide,
    engines execute. An ``enabled`` here would be a second answer to that
    question, resolved from a subset of the facts the policy weighs, and the
    two would diverge the first time a policy gained a condition. The policy
    already reports *who* decided through ``PolicySource``, so nothing is lost
    by not restating it.
    """

    pickup_delay_seconds: Resolved[int]
    resume_delay_seconds: Resolved[int]
    confidence_threshold: Resolved[Decimal]
    #: Empty when no tier defines any. Handover rules are additive rather than
    #: overriding: a service's rules do not replace a company's promise, they
    #: narrow it further.
    handover_rules: tuple[str, ...] = ()


def resolve_ai_policy(*, service: AiPolicy | None, company: CompanyAiSettings) -> ResolvedAiPolicy:
    """The AI settings for this conversation, and who set each one.

    A company with no service directory resolves here exactly as it always
    behaved, and now *says so*: the tiers report ``COMPANY`` and
    ``PLATFORM_DEFAULT`` instead of a branch nobody could see.
    """
    service_pickup = service.pickup_delay_seconds if service is not None else None
    service_resume = service.resume_delay_seconds if service is not None else None
    service_threshold = service.confidence_threshold if service is not None else None

    pickup = resolve_first(
        (ConfigurationSource.SERVICE, service_pickup),
        (ConfigurationSource.PLATFORM_DEFAULT, PLATFORM_DEFAULT_PICKUP_DELAY_SECONDS),
    )
    resume = resolve_first(
        (ConfigurationSource.SERVICE, service_resume),
        (ConfigurationSource.PLATFORM_DEFAULT, PLATFORM_DEFAULT_RESUME_DELAY_SECONDS),
    )
    threshold = resolve_first(
        (ConfigurationSource.SERVICE, service_threshold),
        (ConfigurationSource.COMPANY, company.confidence_threshold),
        (ConfigurationSource.PLATFORM_DEFAULT, PLATFORM_DEFAULT_CONFIDENCE_THRESHOLD),
    )
    assert pickup is not None and resume is not None and threshold is not None  # platform tier

    return ResolvedAiPolicy(
        pickup_delay_seconds=pickup,
        resume_delay_seconds=resume,
        confidence_threshold=threshold,
        handover_rules=service.handover_rules if service is not None else (),
    )


def effective_pickup_delay(
    policy: ResolvedAiPolicy, *, within_business_hours: bool
) -> Resolved[int]:
    """The delay that actually applies right now.

    **Outside business hours it collapses to zero.** The delay exists to give
    a human first refusal; at 03:00 there is no human to defer to, and thirty
    seconds of deliberate silence serves nobody. This inverts the naive
    reading of business hours as a gate that stops AI — outside hours is when
    AI is worth most.

    Business hours never *enable* AI. A service with AI switched off stays off
    at 03:00; this only adjusts how long an enabled AI waits.

    The provenance is preserved rather than reset: the delay is still the
    service's, adjusted by the calendar, and reporting it as a platform
    default would lose who set it.
    """
    if within_business_hours:
        return policy.pickup_delay_seconds
    return policy.pickup_delay_seconds.replace(0)


def effective_activity_window(
    *, service_window_seconds: int | None, within_business_hours: bool
) -> Resolved[int]:
    """How stale the customer's last message may be and still deserve AI.

    Selected by the business-hours state **at evaluation time**, not at the
    message's arrival. A message that landed at 23:00 under the twelve-hour
    out-of-hours window is judged against the one-hour business-hours window
    at 09:00 — and is therefore out of window. Freezing the window at arrival
    would let an overnight message stay answerable deep into a working morning
    during which humans were available and chose not to answer it.
    """
    platform_default = (
        PLATFORM_DEFAULT_ACTIVITY_WINDOW_SECONDS
        if within_business_hours
        else PLATFORM_DEFAULT_OUT_OF_HOURS_ACTIVITY_WINDOW_SECONDS
    )
    resolved = resolve_first(
        (ConfigurationSource.SERVICE, service_window_seconds),
        (ConfigurationSource.PLATFORM_DEFAULT, platform_default),
    )
    assert resolved is not None  # platform tier always answers
    return resolved


__all__ = [
    "PLATFORM_DEFAULT_ACTIVITY_WINDOW_SECONDS",
    "PLATFORM_DEFAULT_CONFIDENCE_THRESHOLD",
    "PLATFORM_DEFAULT_OUT_OF_HOURS_ACTIVITY_WINDOW_SECONDS",
    "PLATFORM_DEFAULT_PICKUP_DELAY_SECONDS",
    "PLATFORM_DEFAULT_RESUME_DELAY_SECONDS",
    "CompanyAiSettings",
    "ResolvedAiPolicy",
    "effective_activity_window",
    "effective_pickup_delay",
    "resolve_ai_policy",
]
