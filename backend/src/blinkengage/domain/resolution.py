"""Where a piece of configuration came from.

See ``docs/architecture/service-centric-migration.md``.

The platform resolves configuration down four tiers — **Service, then Queue,
then Company, then the platform default** — and the same chain governs every
fact: SLA targets, AI policy, business-hours awareness, the activity window.
The narrower configuration wins and the broader one is a *fallback*, never an
override, so configuring a service never silently discards what a queue
already promised.

**The tier is carried, not inferred.** "Why is this conversation due in three
minutes?" is a question a supervisor asks about one conversation, and
reconstructing the answer later means re-reading a service version, a queue and
a policy as they are *now* rather than as they were when the decision was made.
So a resolved value travels with the tier that produced it, and every engine
that acts on one records that tier alongside the action.

This module holds the *shape* of that answer. The rules for each fact live
beside the fact — SLA targets in ``domain/sla.py``, AI policy in
``domain/ai_policy.py`` — because a single module that knew how to resolve
everything would be a second place to look for every rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class ConfigurationSource(StrEnum):
    """Which tier answered.

    Ordered narrowest to broadest, which is also the order they are consulted
    in. The values are stored on ``conversation_sla_clocks.target_source`` and
    recorded on routing decisions, so they are part of the platform's history
    and are not renamed casually.
    """

    #: The service version the conversation is bound to. The operational
    #: source of truth: what a company promised for this line of business.
    SERVICE = "service"
    #: The queue's own configuration — its attached SLA policy, its legacy
    #: minute targets, its Autopilot opt-in.
    QUEUE = "queue"
    #: A company-wide setting. Broader than a queue and narrower than the
    #: platform: the AI kill switch and the confidence threshold live here.
    COMPANY = "company"
    #: Nothing was configured anywhere, so the platform's own conservative
    #: answer applies. Deliberately the last resort — see
    #: ``PLATFORM_DEFAULT_SLA_TARGETS`` for what the platform is willing to
    #: promise on a company's behalf, and how little that is.
    PLATFORM_DEFAULT = "platform_default"


#: Consultation order. Stated once, as data, so a resolver cannot quietly
#: disagree with another about which tier outranks which.
TIER_ORDER: Final[tuple[ConfigurationSource, ...]] = (
    ConfigurationSource.SERVICE,
    ConfigurationSource.QUEUE,
    ConfigurationSource.COMPANY,
    ConfigurationSource.PLATFORM_DEFAULT,
)


@dataclass(frozen=True, slots=True)
class Resolved[T]:
    """A configuration value, and the answer to "says who?"."""

    value: T
    source: ConfigurationSource

    def replace(self, value: T) -> Resolved[T]:
        """The same provenance, a different value.

        For modifiers that adjust a resolved value without changing who
        decided it — the business-hours rule that collapses a pickup delay to
        zero is still the *service's* delay, adjusted, and reporting it as a
        platform default would lose who set it.
        """
        return Resolved(value=value, source=self.source)


def resolve_first[T](*candidates: tuple[ConfigurationSource, T | None]) -> Resolved[T] | None:
    """The first tier that answered, or ``None`` if none did.

    Candidates are passed narrowest-first. ``None`` means *this tier did not
    configure it* and is different from a tier configuring a falsy value: a
    company that set its confidence threshold to zero has made a choice, and a
    resolver that treated ``0`` as absent would overwrite it from the tier
    below.

    Callers that must always produce an answer supply a platform default as
    the final candidate; callers for whom "nobody configured this" is a real
    outcome — an optional feature, say — handle the ``None``.
    """
    for source, value in candidates:
        if value is not None:
            return Resolved(value=value, source=source)
    return None


#: What each tier means, in the words somebody reading a conversation needs.
#:
#: Beside the codes, never instead of them: a console filters on the code and
#: shows the sentence. Every tier has one — a tier with no wording renders as
#: a raw enum name on the screen whose whole purpose is explaining what
#: happened, which is the console equivalent of a raw translation key.
SOURCE_TEXT: Final[dict[ConfigurationSource, str]] = {
    ConfigurationSource.SERVICE: "set by the service this conversation runs in",
    ConfigurationSource.QUEUE: "set by the queue it is waiting in",
    ConfigurationSource.COMPANY: "set company-wide",
    ConfigurationSource.PLATFORM_DEFAULT: (
        "the platform default — nothing was configured for this conversation"
    ),
}


__all__ = [
    "SOURCE_TEXT",
    "TIER_ORDER",
    "ConfigurationSource",
    "Resolved",
    "resolve_first",
]
