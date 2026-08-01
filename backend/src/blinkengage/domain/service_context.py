"""The Service Context: the complete execution environment a conversation runs in.

A Service is not a pointer to configuration. It is the **operational boundary**
of the platform: once routing has resolved which Service a conversation belongs
to, everything that happens afterwards — which queue it waits in, which SLA
clocks run, whether AI may answer, which skills an agent needs, which forms and
knowledge apply — is answered by that Service's context and by nothing else.

Two rules make that real rather than aspirational.

**Resolved once, consumed everywhere.** The routing engine resolves a Service a
single time, at the start. Every module downstream receives the resulting
``ServiceContext`` *object* rather than a ``service_id``, which means it
structurally cannot perform its own lookup — there is nothing to look up with.
That is deliberate: a second lookup is a second chance to read different
configuration than the one the conversation is running under, and the two would
diverge in exactly the situations nobody tests.

**Bound at the start, and stable.** A context is an immutable version. When an
administrator edits a Service, a *new version* is written and new conversations
bind to it; conversations already running keep the version they started with,
until somebody explicitly re-routes them. Without this, changing an SLA target
at noon silently rewrites the deadline of every conversation opened that
morning, and an agent watching a countdown sees it jump.

This is the same guarantee the billing engine gives an invoice, for the same
reason, with one deliberate difference. An invoice snapshots **by value**
because each is unique. Thousands of conversations share one service
configuration, so a context is a **version by reference**: one immutable row,
many conversations pointing at it. Cheap to store, and it stays joinable for
reporting — which snapshot-per-conversation would not be.

Framework-free. Nothing here reads a database; a context is assembled by the
application layer from a stored version and handed down.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

from blinkengage.domain.runtime_queues import AiOverflowPolicy, OverflowStrategy


class ContextBindingReason(StrEnum):
    """Why a conversation is running under the version it is.

    A closed set because the Routing Inspector answers "why is this
    conversation still on the old SLA" from it, and that question has
    exactly these answers.
    """

    #: Bound at the start, to whatever was current then. The ordinary case.
    BOUND_AT_START = "bound_at_start"
    #: An administrator explicitly moved it to the current version.
    REBOUND_BY_ADMINISTRATOR = "rebound_by_administrator"
    #: Re-routed into a different Service entirely, which necessarily binds
    #: a new context.
    REROUTED_TO_ANOTHER_SERVICE = "rerouted_to_another_service"


@dataclass(frozen=True, slots=True)
class SlaTargets:
    """The four clocks, in minutes. ``None`` means "not measured".

    Four independent timers rather than one, because they answer different
    questions and a service can care about some and not others: a sales
    service may have a hard first-response target and no resolution target
    at all, and folding them together would invent a deadline nobody set.

    ``None`` and ``0`` are different: nothing is measured versus a target
    that is already breached the moment it starts.
    """

    #: How long a conversation may wait before an agent picks it up.
    queue_minutes: int | None = None
    #: How long until the first reply reaches the customer.
    first_response_minutes: int | None = None
    #: How long the assigned agent has after a customer replies again.
    next_response_minutes: int | None = None
    #: How long until the whole conversation is resolved.
    resolution_minutes: int | None = None

    @property
    def measures_anything(self) -> bool:
        return any(
            target is not None
            for target in (
                self.queue_minutes,
                self.first_response_minutes,
                self.next_response_minutes,
                self.resolution_minutes,
            )
        )


@dataclass(frozen=True, slots=True)
class AiPolicy:
    """When AI may act, and when it must stop.

    AI is a queue worker here, not an agent: it answers conversations that
    are waiting, and it stands down the moment a human takes one. These
    values are what "the moment" means in practice.
    """

    enabled: bool = False
    #: How long a conversation waits before AI offers an answer. Not zero by
    #: default: a human picking up within a few seconds should get there
    #: first, and an AI that always replies instantly removes that chance.
    pickup_delay_seconds: int = 30
    #: How long an assigned agent must be inactive before AI may resume
    #: assisting. Resuming too eagerly talks over an agent who is simply
    #: typing.
    resume_delay_seconds: int = 900
    #: Below this, AI does not answer and the conversation waits for a
    #: human. ``Decimal`` rather than ``float`` because it is compared
    #: against a threshold and two values differing in the last binary
    #: place must not straddle it.
    confidence_threshold: Decimal = Decimal("0.75")
    #: Phrases or conditions that hand the conversation to a human
    #: immediately, whatever the confidence.
    handover_rules: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.pickup_delay_seconds < 0 or self.resume_delay_seconds < 0:
            raise ValueError("an AI delay cannot be negative")
        if not (Decimal("0") <= self.confidence_threshold <= Decimal("1")):
            raise ValueError("a confidence threshold must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class QueueBinding:
    """The logical queue a service waits in, and how its lanes behave.

    ``logical_queue_name`` is carried **as a value** beside the id, for the
    same reason a routing decision carries the rule's name: a queue can be
    renamed or deleted, and a context that then explained itself as a blank
    would be evidence that quietly changed its story.
    """

    logical_queue_id: uuid.UUID
    logical_queue_name: str
    overflow_strategy: OverflowStrategy = OverflowStrategy.WAIT
    ai_overflow_policy: AiOverflowPolicy = AiOverflowPolicy.NEVER
    max_waiting: int = 0
    max_concurrent_agents: int = 0


@dataclass(frozen=True, slots=True)
class ServiceContext:
    """Everything a conversation's Service decides, frozen at one version.

    Passed **as this object** to every module downstream. A module that
    received a ``service_id`` instead could look the service up again and
    read configuration the conversation is not running under; a module that
    receives this cannot, because there is nothing here to look up with.

    Modules that do not exist yet — knowledge, automation, reports, billing
    analytics, integrations — reach the context through ``extras``. That is
    a deliberate seam rather than a placeholder: a version written before a
    module existed simply has no entry for it, and ``setting()`` answers with
    the caller's default instead of raising. Adding a module therefore needs
    no migration and does not change how already-bound conversations behave,
    which is the whole guarantee this type exists to provide.
    """

    service_id: uuid.UUID
    #: Which immutable version this is. Monotonic per service, starting at 1.
    version: int
    service_version_id: uuid.UUID
    company_id: uuid.UUID

    #: Carried as values, so a context explains itself even after the
    #: service has been renamed or archived.
    name: str
    description: str | None = None
    icon: str | None = None

    queue: QueueBinding | None = None
    sla: SlaTargets = field(default_factory=SlaTargets)
    ai: AiPolicy = field(default_factory=AiPolicy)

    #: Business hours calendar this service runs on. ``None`` means the
    #: clocks run continuously — which is a real choice, not an absence.
    business_hours_id: uuid.UUID | None = None
    #: Skills an agent must hold to be assigned. Empty means anyone.
    required_skill_ids: tuple[uuid.UUID, ...] = ()
    #: Who escalations and supervisor overflow reach.
    supervisor_user_ids: tuple[uuid.UUID, ...] = ()
    #: Forms shown to the customer before or during the conversation.
    form_ids: tuple[uuid.UUID, ...] = ()

    #: Where modules that do not exist yet keep their settings. See the
    #: class docstring — this is the seam that lets the platform grow
    #: without reshaping every stored version.
    extras: dict[str, Any] = field(default_factory=dict)

    def setting(self, module: str, key: str, default: Any = None) -> Any:
        """One module's setting, or ``default`` if this version predates it.

        Never raises for an unknown module. A version written last year has
        no entry for a module shipped last week, and a conversation bound to
        it must keep running rather than fail on a key nobody could have
        stored.
        """
        section = self.extras.get(module)
        if not isinstance(section, dict):
            return default
        return section.get(key, default)

    @property
    def routes_anywhere(self) -> bool:
        """Whether this context can actually queue a conversation.

        A service with no queue is a configuration an administrator can
        create and a conversation cannot run in. Asked explicitly so the
        engine records a decision about it rather than failing on a ``None``.
        """
        return self.queue is not None


@dataclass(frozen=True, slots=True)
class ContextBinding:
    """The link between one conversation and the version it runs under."""

    conversation_id: uuid.UUID
    context: ServiceContext
    reason: ContextBindingReason

    @property
    def is_original(self) -> bool:
        return self.reason is ContextBindingReason.BOUND_AT_START


def is_stale(binding: ContextBinding, current_version: int) -> bool:
    """Whether the service has moved on since this conversation bound to it.

    Stale is **not** wrong. It is the guarantee working: an administrator
    changed the configuration and running conversations deliberately kept
    the one they started with. The console shows it so a supervisor
    wondering why two conversations in the same queue have different
    deadlines gets an answer, and can re-route if that is what they want.
    """
    return binding.context.version < current_version


__all__ = [
    "AiPolicy",
    "ContextBinding",
    "ContextBindingReason",
    "QueueBinding",
    "ServiceContext",
    "SlaTargets",
    "is_stale",
]
